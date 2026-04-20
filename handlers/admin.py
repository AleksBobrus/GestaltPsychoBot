# handlers/admin.py
# Модуль администрирования: статистика, рассылка, информация о пользователе,
# сброс лимита, список пользователей с пагинацией.

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
    get_all_users, get_total_users_count  # НОВЫЕ ИМПОРТЫ
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
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👤 Информация о пользователе", callback_data="admin_user_info")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_user_list:0")],  # НОВАЯ
        [InlineKeyboardButton(text="🔄 Сбросить лимит", callback_data="admin_reset_limit")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🔙 Закрыть", callback_data="admin_close")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# -------------------------------------------------------------------
# FSM ДЛЯ АДМИНСКИХ ДЕЙСТВИЙ
# -------------------------------------------------------------------
class AdminAction(StatesGroup):
    waiting_for_user_id = State()


class ResetLimit(StatesGroup):
    waiting_for_user_id = State()


class BroadcastState(StatesGroup):
    waiting_for_message = State()


# -------------------------------------------------------------------
# КНОПКА «АДМИН-ПАНЕЛЬ» В ГЛАВНОМ МЕНЮ
# -------------------------------------------------------------------
@router.message(F.text == "🔧 Админ-панель")
async def admin_panel(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к этой функции.")
        return

    await state.clear()
    await message.answer(
        "🔧 **Админ-панель**\n\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )


# -------------------------------------------------------------------
# ОБРАБОТЧИКИ INLINE-КНОПОК
# -------------------------------------------------------------------
@router.callback_query(F.data == "admin_stats")
async def admin_stats_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    await callback.answer()
    total_users = await get_total_users()
    active_today = await get_active_users_today()
    messages_today = await get_total_messages_today()

    stats_text = (
        "📊 **Статистика бота**\n\n"
        f"👥 Всего пользователей: **{total_users}**\n"
        f"📅 Активных сегодня: **{active_today}**\n"
        f"💬 Сообщений сегодня: **{messages_today}**\n"
    )
    try:
        await callback.message.edit_text(stats_text, parse_mode="Markdown", reply_markup=get_admin_keyboard())
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Ошибка при обновлении статистики: {e}")


@router.callback_query(F.data == "admin_user_info")
async def admin_user_info_callback(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    await callback.answer()
    await state.set_state(AdminAction.waiting_for_user_id)
    await callback.message.edit_text(
        "👤 Введите Telegram ID пользователя для получения информации.\n"
        "Для отмены отправьте /cancel",
        parse_mode="Markdown"
    )


@router.callback_query(F.data.startswith("admin_user_list"))
async def admin_user_list_callback(callback: types.CallbackQuery):
    """Показывает список пользователей с пагинацией."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    await callback.answer()

    # Разбираем параметры пагинации
    data_parts = callback.data.split(":")
    page = int(data_parts[1]) if len(data_parts) > 1 else 0
    per_page = 10

    total_users = await get_total_users_count()
    offset = page * per_page
    users = await get_all_users(limit=per_page, offset=offset)

    if not users:
        text = "👥 Пока нет зарегистрированных пользователей."
    else:
        lines = [f"👥 **Список пользователей (страница {page+1}):**\n"]
        for u in users:
            name = u['custom_name'] or u['telegram_name'] or "—"
            lines.append(f"`{u['user_id']}` – {name}")
        text = "\n".join(lines)

    # Клавиатура для навигации
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_user_list:{page-1}")
        )
    if (page + 1) * per_page < total_users:
        nav_buttons.append(
            InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"admin_user_list:{page+1}")
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[nav_buttons] if nav_buttons else [])
    keyboard.inline_keyboard.append(
        [InlineKeyboardButton(text="🔙 В админ-панель", callback_data="admin_back_to_panel")]
    )

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)


@router.callback_query(F.data == "admin_reset_limit")
async def admin_reset_limit_callback(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    await callback.answer()
    await state.set_state(ResetLimit.waiting_for_user_id)
    await callback.message.edit_text(
        "🔄 Введите Telegram ID пользователя, которому нужно сбросить дневной лимит.\n"
        "Для отмены отправьте /cancel",
        parse_mode="Markdown"
    )


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


@router.callback_query(F.data == "admin_close")
async def admin_close_callback(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return

    await callback.answer()
    await callback.message.delete()


@router.callback_query(F.data == "admin_back_to_panel")
async def back_to_panel(callback: types.CallbackQuery):
    """Возвращает в главное меню админ-панели."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "🔧 **Админ-панель**\n\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=get_admin_keyboard()
    )


# -------------------------------------------------------------------
# ОБРАБОТЧИК ВВОДА ID ДЛЯ ПОЛУЧЕНИЯ ИНФОРМАЦИИ
# -------------------------------------------------------------------
@router.message(AdminAction.waiting_for_user_id)
async def process_user_info(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        await state.clear()
        return

    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Действие отменено.", reply_markup=get_main_menu(message.from_user.id))
        return

    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("⚠️ Некорректный ID. Введите целое число.")
        return

    info = await get_user_info(user_id)
    if info["first_seen"] is None:
        await message.answer(f"ℹ️ Пользователь с ID {user_id} не найден в базе.")
    else:
        first_seen_str = info["first_seen"][:19] if info["first_seen"] else "—"
        text = (
            f"👤 **Информация о пользователе {user_id}**\n\n"
            f"📅 Первое сообщение: {first_seen_str}\n"
            f"💬 Всего сообщений: {info['total_messages']}\n"
            f"📊 Сегодня: {info['messages_today']}/{info['limit']} (осталось {info['remaining']})\n"
        )
        await message.answer(text, parse_mode="Markdown")

    await state.clear()
    await message.answer("🔧 Возврат в админ-панель.", reply_markup=get_main_menu(message.from_user.id))


# -------------------------------------------------------------------
# ОБРАБОТЧИК ВВОДА ID ДЛЯ СБРОСА ЛИМИТА
# -------------------------------------------------------------------
@router.message(ResetLimit.waiting_for_user_id)
async def process_reset_limit(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        await state.clear()
        return

    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Действие отменено.", reply_markup=get_main_menu(message.from_user.id))
        return

    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("⚠️ Некорректный ID. Введите целое число.")
        return

    await reset_user_limit(user_id)
    await message.answer(f"✅ Дневной лимит для пользователя {user_id} сброшен.")
    await state.clear()
    await message.answer("🔧 Возврат в админ-панель.", reply_markup=get_main_menu(message.from_user.id))


# -------------------------------------------------------------------
# ОБРАБОТЧИК РАССЫЛКИ
# -------------------------------------------------------------------
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
    """Показывает последних 20 зарегистрированных пользователей."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return

    users = await get_all_users(limit=20, offset=0)
    if not users:
        await message.answer("👥 Пока нет зарегистрированных пользователей.")
        return

    lines = ["👥 **Последние 20 пользователей:**\n"]
    for u in users:
        name = u['custom_name'] or u['telegram_name'] or "—"
        lines.append(f"`{u['user_id']}` – {name}")

    await message.answer("\n".join(lines), parse_mode="Markdown")
