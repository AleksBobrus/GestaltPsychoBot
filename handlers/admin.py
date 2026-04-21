# handlers/admin.py
# Модуль администрирования: статистика, пользователи (список, поиск, инфо, сброс), рассылка.
# Отображает @username в списках пользователей.

import os
import asyncio
import logging
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from keyboards import get_main_menu
from database import (
    get_total_users, get_active_users_today, get_total_messages_today, get_all_user_ids,
    get_user_info, reset_user_limit,
    get_all_users, get_total_users_count,
    search_users
)

logger = logging.getLogger(__name__)

# Загружаем список ID администраторов из .env
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

router = Router()


# -------------------------------------------------------------------
# ФИЛЬТР ПРОВЕРКИ АДМИНИСТРАТОРА
# -------------------------------------------------------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# -------------------------------------------------------------------
# INLINE-КЛАВИАТУРА АДМИН-ПАНЕЛИ
# -------------------------------------------------------------------
def get_admin_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📈 Подробная статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users_menu")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🔙 Закрыть", callback_data="admin_close")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# -------------------------------------------------------------------
# FSM
# -------------------------------------------------------------------
class BroadcastState(StatesGroup):
    waiting_for_message = State()

class SearchState(StatesGroup):
    waiting_for_query = State()


# -------------------------------------------------------------------
# ГЛАВНОЕ МЕНЮ АДМИН-ПАНЕЛИ (СВОДКА)
# -------------------------------------------------------------------
@router.message(F.text == "🔧 Админ-панель")
async def admin_panel(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этой функции.")
        return

    await state.clear()

    total_users = await get_total_users()
    active_today = await get_active_users_today()
    messages_today = await get_total_messages_today()
    purchases_today = 0  # заглушка, пока нет оплат

    stats_text = (
        "🔧 **Админ-панель**\n\n"
        "📊 **Сводка на сегодня:**\n"
        f"👥 Всего пользователей: **{total_users}**\n"
        f"📅 Активных сегодня: **{active_today}**\n"
        f"💬 Сообщений сегодня: **{messages_today}**\n"
        f"💵 Покупки сегодня: **{purchases_today}**\n\n"
        "Выберите действие:"
    )

    await message.answer(stats_text, parse_mode="Markdown", reply_markup=get_admin_keyboard())


# -------------------------------------------------------------------
# ПОДРОБНАЯ СТАТИСТИКА (ЗАГЛУШКА)
# -------------------------------------------------------------------
@router.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await callback.answer("📈 Подробная статистика будет доступна позже.", show_alert=True)


# -------------------------------------------------------------------
# МЕНЮ ПОЛЬЗОВАТЕЛЕЙ (СПИСОК С ПАГИНАЦИЕЙ)
# -------------------------------------------------------------------
@router.callback_query(F.data == "admin_users_menu")
async def admin_users_menu(callback: types.CallbackQuery):
    """Показывает список пользователей с пагинацией и кнопкой поиска."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    await callback.answer()
    await show_user_list(callback.message, page=0)


async def show_user_list(message: types.Message, page: int = 0):
    """Отображает страницу списка пользователей."""
    per_page = 8
    total_users = await get_total_users_count()
    offset = page * per_page
    users = await get_all_users(limit=per_page, offset=offset)

    if not users:
        text = "👥 Пока нет зарегистрированных пользователей."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Поиск", callback_data="admin_search_user")],
            [InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_back_to_panel")]
        ])
    else:
        lines = [f"👥 **Пользователи (стр. {page+1}):**\n"]
        for u in users:
            # Формируем кликабельную ссылку на профиль Telegram
            profile_link = f"tg://user?id={u['user_id']}"
            # Отображаем @username, если он есть, иначе telegram_name
            if u.get('username'):
                # Если есть username, показываем @username как ссылку
                display_name = f"[@{u['username']}]({profile_link})"
            else:
                # Если username нет, показываем telegram_name как ссылку
                name = u['telegram_name'] or "Без имени"
                display_name = f"[{name}]({profile_link})"
            lines.append(f"`{u['user_id']}` – {display_name}")
        text = "\n".join(lines)

        # Кнопки пагинации
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"user_page:{page-1}"))
        if (page + 1) * per_page < total_users:
            nav_buttons.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"user_page:{page+1}"))

        keyboard_rows = []
        if nav_buttons:
            keyboard_rows.append(nav_buttons)

        # Кнопки действий для каждого пользователя
        for u in users:
            user_id = u['user_id']
            keyboard_rows.append([
                InlineKeyboardButton(text=f"ℹ️ {user_id}", callback_data=f"user_info:{user_id}"),
                InlineKeyboardButton(text=f"🔄 Сброс", callback_data=f"user_reset:{user_id}")
            ])

        keyboard_rows.append([InlineKeyboardButton(text="🔍 Поиск", callback_data="admin_search_user")])
        keyboard_rows.append([InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_back_to_panel")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    await message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)


# -------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: ПОКАЗ СПИСКА НОВЫМ СООБЩЕНИЕМ
# -------------------------------------------------------------------
async def show_user_list_new_message(message: types.Message, page: int = 0):
    """Отправляет новое сообщение со списком пользователей (для случаев, когда нельзя редактировать)."""
    per_page = 8
    total_users = await get_total_users_count()
    offset = page * per_page
    users = await get_all_users(limit=per_page, offset=offset)

    if not users:
        text = "👥 Пока нет зарегистрированных пользователей."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Поиск", callback_data="admin_search_user")],
            [InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_back_to_panel")]
        ])
    else:
        lines = [f"👥 **Пользователи (стр. {page+1}):**\n"]
        for u in users:
            profile_link = f"tg://user?id={u['user_id']}"
            if u.get('username'):
                display_name = f"[@{u['username']}]({profile_link})"
            else:
                name = u['telegram_name'] or "Без имени"
                display_name = f"[{name}]({profile_link})"
            lines.append(f"`{u['user_id']}` – {display_name}")
        text = "\n".join(lines)

        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"user_page:{page-1}"))
        if (page + 1) * per_page < total_users:
            nav_buttons.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"user_page:{page+1}"))

        keyboard_rows = []
        if nav_buttons:
            keyboard_rows.append(nav_buttons)

        for u in users:
            user_id = u['user_id']
            keyboard_rows.append([
                InlineKeyboardButton(text=f"ℹ️ {user_id}", callback_data=f"user_info:{user_id}"),
                InlineKeyboardButton(text=f"🔄 Сброс", callback_data=f"user_reset:{user_id}")
            ])

        keyboard_rows.append([InlineKeyboardButton(text="🔍 Поиск", callback_data="admin_search_user")])
        keyboard_rows.append([InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_back_to_panel")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)


# -------------------------------------------------------------------
# ПАГИНАЦИЯ
# -------------------------------------------------------------------
@router.callback_query(F.data.startswith("user_page:"))
async def user_page_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    page = int(callback.data.split(":")[1])
    await callback.answer()
    await show_user_list(callback.message, page=page)


# -------------------------------------------------------------------
# ПОИСК ПОЛЬЗОВАТЕЛЕЙ
# -------------------------------------------------------------------
@router.callback_query(F.data == "admin_search_user")
async def admin_search_user(callback: types.CallbackQuery, state: FSMContext):
    """Запускает режим поиска пользователя."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(SearchState.waiting_for_query)
    await callback.message.edit_text(
        "🔍 Введите имя пользователя, @username или Telegram ID для поиска.\n"
        "Для отмены отправьте /cancel",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_users_menu")]
        ])
    )


@router.message(SearchState.waiting_for_query)
async def process_search(message: types.Message, state: FSMContext):
    """Выполняет поиск и показывает результаты."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        await state.clear()
        return

    if message.text == "/cancel":
        await state.clear()
        await show_user_list_new_message(message, page=0)
        return

    query = message.text.strip()
    users = await search_users(query)

    if not users:
        text = f"❌ По запросу «{query}» ничего не найдено."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К списку пользователей", callback_data="admin_users_menu")]
        ])
        await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        lines = [f"🔍 **Результаты поиска «{query}»:**\n"]
        for u in users:
            profile_link = f"tg://user?id={u['user_id']}"
            if u.get('username'):
                display_name = f"[@{u['username']}]({profile_link})"
            else:
                name = u['telegram_name'] or "Без имени"
                display_name = f"[{name}]({profile_link})"
            lines.append(f"`{u['user_id']}` – {display_name}")
        text = "\n".join(lines)

        keyboard_rows = []
        for u in users:
            user_id = u['user_id']
            keyboard_rows.append([
                InlineKeyboardButton(text=f"ℹ️ {user_id}", callback_data=f"user_info:{user_id}"),
                InlineKeyboardButton(text=f"🔄 Сброс", callback_data=f"user_reset:{user_id}")
            ])
        keyboard_rows.append([InlineKeyboardButton(text="🔙 К списку пользователей", callback_data="admin_users_menu")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

        await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

    await state.clear()


# -------------------------------------------------------------------
# ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ
# -------------------------------------------------------------------
@router.callback_query(F.data.startswith("user_info:"))
async def user_info_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    user_id = int(callback.data.split(":")[1])
    info = await get_user_info(user_id)

    if info["first_seen"] is None:
        await callback.answer("Пользователь не найден в истории сообщений.", show_alert=True)
        return

    first_seen_str = info["first_seen"][:19] if info["first_seen"] else "—"
    text = (
        f"👤 **Информация о пользователе {user_id}**\n\n"
        f"📅 Первое сообщение: {first_seen_str}\n"
        f"💬 Всего сообщений: {info['total_messages']}\n"
        f"📊 Сегодня: {info['messages_today']}/{info['limit']} (осталось {info['remaining']})\n"
    )
    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад к пользователям", callback_data="admin_users_menu")]
        ])
    )


# -------------------------------------------------------------------
# СБРОС ЛИМИТА ПОЛЬЗОВАТЕЛЯ
# -------------------------------------------------------------------
@router.callback_query(F.data.startswith("user_reset:"))
async def user_reset_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    user_id = int(callback.data.split(":")[1])
    await reset_user_limit(user_id)
    await callback.answer(f"✅ Лимит для {user_id} сброшен.", show_alert=True)
    # Возвращаемся к списку пользователей (первая страница)
    await show_user_list(callback.message, page=0)


# -------------------------------------------------------------------
# РАССЫЛКА
# -------------------------------------------------------------------
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_callback(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    await callback.answer()
    await state.set_state(BroadcastState.waiting_for_message)
    await callback.message.edit_text(
        "📢 **Режим рассылки**\n\n"
        "Отправьте сообщение, которое хотите разослать всем пользователям.\n"
        "Для отмены отправьте /cancel",
        parse_mode="Markdown"
    )


@router.message(BroadcastState.waiting_for_message)
async def process_broadcast(message: types.Message, state: FSMContext, bot: Bot):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        await state.clear()
        return

    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Рассылка отменена.", reply_markup=get_main_menu(message.from_user.id))
        return

    await state.clear()

    user_ids = await get_all_user_ids()
    if not user_ids:
        await message.answer("⚠️ Нет пользователей для рассылки.", reply_markup=get_main_menu(message.from_user.id))
        return

    success = 0
    blocked = 0
    failed = 0

    await message.answer(f"🚀 Начинаю рассылку для {len(user_ids)} пользователей...")

    for user_id in user_ids:
        try:
            await bot.send_message(user_id, message.text)
            success += 1
        except Exception as e:
            if "bot was blocked" in str(e).lower() or "forbidden" in str(e).lower():
                blocked += 1
            else:
                failed += 1
                logger.warning(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
        await asyncio.sleep(0.05)

    report = (
        f"📢 **Рассылка завершена**\n\n"
        f"✅ Успешно: {success}\n"
        f"🚫 Заблокировали бота: {blocked}\n"
        f"❌ Ошибок: {failed}"
    )
    await message.answer(report, parse_mode="Markdown", reply_markup=get_main_menu(message.from_user.id))


# -------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ КОМАНДЫ
# -------------------------------------------------------------------
@router.callback_query(F.data == "admin_back_to_panel")
async def back_to_panel(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "🔧 **Админ-панель**\n\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )


@router.callback_query(F.data == "admin_close")
async def admin_close_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await callback.answer()
    await callback.message.delete()


# -------------------------------------------------------------------
# ПРЯМЫЕ КОМАНДЫ
# -------------------------------------------------------------------
@router.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этой команде.")
        return

    total_users = await get_total_users()
    active_today = await get_active_users_today()
    messages_today = await get_total_messages_today()

    stats_text = (
        "📊 **Статистика бота**\n\n"
        f"👥 Всего пользователей: **{total_users}**\n"
        f"📅 Активных сегодня: **{active_today}**\n"
        f"💬 Сообщений сегодня: **{messages_today}**\n"
    )
    await message.answer(stats_text, parse_mode="Markdown")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этой команде.")
        return

    await state.set_state(BroadcastState.waiting_for_message)
    await message.answer(
        "📢 **Режим рассылки**\n\n"
        "Отправьте сообщение для всех пользователей.\n"
        "Для отмены отправьте /cancel"
    )


@router.message(Command("users"))
async def cmd_users(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return

    users = await get_all_users(limit=20, offset=0)
    if not users:
        await message.answer("👥 Пока нет зарегистрированных пользователей.")
        return

    lines = ["👥 **Последние 20 пользователей:**\n"]
    for u in users:
        profile_link = f"tg://user?id={u['user_id']}"
        if u.get('username'):
            display_name = f"[@{u['username']}]({profile_link})"
        else:
            name = u['telegram_name'] or "Без имени"
            display_name = f"[{name}]({profile_link})"
        lines.append(f"`{u['user_id']}` – {display_name}")

    await message.answer("\n".join(lines), parse_mode="Markdown")
