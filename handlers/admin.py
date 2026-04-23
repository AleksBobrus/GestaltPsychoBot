# handlers/admin.py
# Модуль администрирования: статистика, пользователи (список, поиск по ID, инфо), рассылка.
# Версия 4.0.0 – управление Premium-подписками вместо баланса сообщений.

import os
import asyncio
import logging
import re
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from keyboards import get_main_menu
from database import (
    get_active_users_today, get_total_messages_today, get_all_user_ids,
    get_user_info,
    get_all_users, get_total_users_count,
    search_users,
    activate_subscription, deactivate_subscription, get_subscription_days_left
)

logger = logging.getLogger(__name__)

# ID администраторов загружаются из .env
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []
router = Router()


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return user_id in ADMIN_IDS


# -------------------------------------------------------------------
# СОБСТВЕННАЯ ФУНКЦИЯ ЭКРАНИРОВАНИЯ MARKDOWN
# -------------------------------------------------------------------
def escape_md(text: str) -> str:
    """Экранирует спецсимволы Markdown."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)


# -------------------------------------------------------------------
# КЛАВИАТУРА АДМИН-ПАНЕЛИ (ГЛАВНОЕ МЕНЮ)
# -------------------------------------------------------------------
def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Главное меню админ-панели."""
    buttons = [
        [InlineKeyboardButton(text="📈 Подробная статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users_menu")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🔙 Закрыть", callback_data="admin_close")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# -------------------------------------------------------------------
# СОСТОЯНИЯ FSM
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

    total_users = await get_total_users_count()
    active_today = await get_active_users_today()
    messages_today = await get_total_messages_today()
    purchases_today = 0  # заглушка

    stats_text = (
        "🔧 **Админ-панель**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
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
# РАЗДЕЛ «ПОЛЬЗОВАТЕЛИ» (СПИСОК В ВИДЕ КНОПОК)
# -------------------------------------------------------------------
@router.callback_query(F.data == "admin_users_menu")
async def admin_users_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await callback.answer()
    await show_user_list(callback.message, page=0)


async def show_user_list(message: types.Message, page: int = 0):
    per_page = 10
    total_users = await get_total_users_count()
    offset = page * per_page
    users = await get_all_users(limit=per_page, offset=offset)

    displayed_count = len(users)
    text = f"👥 **Пользователи ({displayed_count}/{total_users}):**"

    if not users:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Поиск по ID", callback_data="admin_search_user")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_to_panel")]
        ])
        await message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
        return

    keyboard_rows = []
    for u in users:
        user_id = u['user_id']
        name = u.get('custom_name') or u.get('telegram_name') or "Без имени"
        safe_name = escape_md(name)
        button_text = f"{user_id} – {safe_name}"
        keyboard_rows.append([InlineKeyboardButton(text=button_text, callback_data=f"user_info:{user_id}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"user_page:{page-1}"))
    if (page + 1) * per_page < total_users:
        nav_buttons.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"user_page:{page+1}"))
    if nav_buttons:
        keyboard_rows.append(nav_buttons)

    keyboard_rows.append([InlineKeyboardButton(text="🔍 Поиск по ID", callback_data="admin_search_user")])
    keyboard_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_to_panel")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    try:
        await message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception:  # noqa
        await message.edit_text(text.replace("*", ""), reply_markup=keyboard)


# -------------------------------------------------------------------
# ПАГИНАЦИЯ СПИСКА ПОЛЬЗОВАТЕЛЕЙ
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
# ПОИСК ПОЛЬЗОВАТЕЛЕЙ (ТОЛЬКО ПО ID)
# -------------------------------------------------------------------
@router.callback_query(F.data == "admin_search_user")
async def admin_search_user(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(SearchState.waiting_for_query)
    await callback.message.edit_text(
        "🔍 Введите Telegram ID пользователя для поиска.\n"
        "Для отмены отправьте /cancel",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_users_menu")]
        ])
    )


@router.message(SearchState.waiting_for_query)
async def process_search(message: types.Message, state: FSMContext):
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
        await message.answer(text, reply_markup=keyboard)
    else:
        total_found = len(users)
        text = f"🔍 Результаты поиска «{query}» ({total_found}):"
        keyboard_rows = []
        for u in users:
            user_id = u['user_id']
            name = u.get('custom_name') or u.get('telegram_name') or "Без имени"
            safe_name = escape_md(name)
            button_text = f"{user_id} – {safe_name}"
            keyboard_rows.append([InlineKeyboardButton(text=button_text, callback_data=f"user_info:{user_id}")])
        keyboard_rows.append([InlineKeyboardButton(text="🔙 К списку пользователей", callback_data="admin_users_menu")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
        await message.answer(text, reply_markup=keyboard)

    await state.clear()


async def show_user_list_new_message(message: types.Message, page: int = 0):
    per_page = 10
    total_users = await get_total_users_count()
    offset = page * per_page
    users = await get_all_users(limit=per_page, offset=offset)

    displayed_count = len(users)
    text = f"👥 **Пользователи ({displayed_count}/{total_users}):**"

    if not users:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Поиск по ID", callback_data="admin_search_user")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_to_panel")]
        ])
        await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
        return

    keyboard_rows = []
    for u in users:
        user_id = u['user_id']
        name = u.get('custom_name') or u.get('telegram_name') or "Без имени"
        safe_name = escape_md(name)
        button_text = f"{user_id} – {safe_name}"
        keyboard_rows.append([InlineKeyboardButton(text=button_text, callback_data=f"user_info:{user_id}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"user_page:{page-1}"))
    if (page + 1) * per_page < total_users:
        nav_buttons.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"user_page:{page+1}"))
    if nav_buttons:
        keyboard_rows.append(nav_buttons)

    keyboard_rows.append([InlineKeyboardButton(text="🔍 Поиск по ID", callback_data="admin_search_user")])
    keyboard_rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_to_panel")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)


# -------------------------------------------------------------------
# ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ (С УПРАВЛЕНИЕМ PREMIUM)
# -------------------------------------------------------------------
@router.callback_query(F.data.startswith("user_info:"))
async def user_info_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    user_id = int(callback.data.split(":")[1])
    info = await get_user_info(user_id)

    display_name = info.get('custom_name') or info.get('telegram_name') or "Без имени"
    safe_display_name = escape_md(display_name)

    reg_date = info.get('created_at')[:19] if info.get('created_at') else "неизвестно"
    days_left = await get_subscription_days_left(user_id)
    if days_left is not None:
        sub_status = f"✅ Активна (осталось {days_left} дн.)"
    else:
        sub_status = "❌ Не активна"

    text = (
        f"👤 **Информация о пользователе**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"ID: **{user_id}**\n"
        f"Имя: *{safe_display_name}*\n"
        f"🚀 Регистрация: {reg_date}\n"
        f"💬 Всего сообщений: **{info['total_messages']}**\n"
        f"⏳ Подписка: {sub_status}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Активировать на 10 дней", callback_data=f"user_add_premium_ask:{user_id}:10")],
        [InlineKeyboardButton(text="🔄 Активировать на 20 дней", callback_data=f"user_add_premium_ask:{user_id}:20")],
        [InlineKeyboardButton(text="🔄 Активировать на 30 дней", callback_data=f"user_add_premium_ask:{user_id}:30")],
        [InlineKeyboardButton(text="🚫 Отключить подписку", callback_data=f"user_deactivate_premium_ask:{user_id}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="admin_users_menu")]
    ])

    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception:  # noqa
        plain_text = text.replace("*", "").replace("_", "").replace("`", "")
        await callback.message.edit_text(plain_text, reply_markup=keyboard)


# -------------------------------------------------------------------
# АКТИВАЦИЯ PREMIUM (ЗАПРОС ПОДТВЕРЖДЕНИЯ)
# -------------------------------------------------------------------
@router.callback_query(F.data.startswith("user_add_premium_ask:"))
async def user_add_premium_ask(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    _, user_id_str, days_str = callback.data.split(":")
    user_id = int(user_id_str)
    days = int(days_str)
    await callback.answer()
    await callback.message.edit_text(
        f"⚠️ *Активировать подписку на {days} дней для пользователя {user_id}?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"user_add_premium_confirm:{user_id}:{days}"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"user_info:{user_id}")
            ]
        ])
    )


@router.callback_query(F.data.startswith("user_add_premium_confirm:"))
async def user_add_premium_confirm(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    _, user_id_str, days_str = callback.data.split(":")
    user_id = int(user_id_str)
    days = int(days_str)
    await activate_subscription(user_id, days)
    await callback.answer(f"✅ Подписка активирована на {days} дней", show_alert=True)
    await user_info_callback(callback)


# -------------------------------------------------------------------
# ДЕАКТИВАЦИЯ PREMIUM
# -------------------------------------------------------------------
@router.callback_query(F.data.startswith("user_deactivate_premium_ask:"))
async def user_deactivate_premium_ask(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    await callback.answer()
    await callback.message.edit_text(
        f"⚠️ *Отключить подписку для пользователя {user_id}?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"user_deactivate_premium_confirm:{user_id}"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"user_info:{user_id}")
            ]
        ])
    )


@router.callback_query(F.data.startswith("user_deactivate_premium_confirm:"))
async def user_deactivate_premium_confirm(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    user_id = int(callback.data.split(":")[1])
    await deactivate_subscription(user_id)
    await callback.answer("✅ Подписка отключена", show_alert=True)
    await user_info_callback(callback)


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
        await message.answer("⚠️ Нет зарегистрированных пользователей для рассылки.", reply_markup=get_main_menu(message.from_user.id))
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

    total_users = await get_total_users_count()
    active_today = await get_active_users_today()
    messages_today = await get_total_messages_today()
    purchases_today = 0

    stats_text = (
        "🔧 **Админ-панель**\n\n"
        "📊 **Сводка на сегодня:**\n"
        f"👥 Всего пользователей: **{total_users}**\n"
        f"📅 Активных сегодня: **{active_today}**\n"
        f"💬 Сообщений сегодня: **{messages_today}**\n"
        f"💵 Покупки сегодня: **{purchases_today}**\n\n"
        "Выберите действие:"
    )

    await callback.message.edit_text(
        stats_text,
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

    total_users = await get_total_users_count()
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
        name = u.get('custom_name') or u.get('telegram_name') or "Без имени"
        lines.append(f"`{u['user_id']}` – {name}")

    await message.answer("\n".join(lines), parse_mode="Markdown")
