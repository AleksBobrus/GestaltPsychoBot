# handlers/admin.py
# Модуль администрирования: статистика, рассылка, админ-панель.

import os
import asyncio
import logging
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from keyboards import main_menu_kb
from database import (
    get_total_users, get_active_users_today, get_total_messages_today, get_all_user_ids
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
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🔙 Закрыть", callback_data="admin_close")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# -------------------------------------------------------------------
# FSM ДЛЯ РАССЫЛКИ
# -------------------------------------------------------------------
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
        await message.answer("❌ Рассылка отменена.", reply_markup=main_menu_kb)
        return

    await state.clear()

    user_ids = await get_all_user_ids()
    if not user_ids:
        await message.answer("⚠️ Нет пользователей для рассылки.", reply_markup=main_menu_kb)
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
        await asyncio.sleep(0.05)  # уважаем лимиты Telegram

    report = (
        f"📢 **Рассылка завершена**\n\n"
        f"✅ Успешно: {success}\n"
        f"🚫 Заблокировали бота: {blocked}\n"
        f"❌ Ошибок: {failed}"
    )
    await message.answer(report, parse_mode="Markdown", reply_markup=main_menu_kb)


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
