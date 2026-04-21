# handlers/dialog_handlers.py
# Обработчики режима диалога с ИИ-психологом.
# Включает: вход/выход, атомарную проверку лимита, детектор кризиса,
# вызов DeepSeek API (без стриминга), суммаризацию и сохранение истории.

import logging
import os
from dotenv import load_dotenv

from aiogram import types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from openai import APIError, APIConnectionError, RateLimitError, AuthenticationError
from keyboards import dialog_kb, get_main_menu
from ai_client import get_ai_response, create_summary
from database import (
    save_message, get_recent_history,
    try_decrement_balance,
    count_user_messages, get_messages_for_summary, save_summary, get_all_summaries
)
from crisis_detector import detect_crisis, get_crisis_response

load_dotenv()
CRISIS_ENABLED = os.getenv("CRISIS_DETECTOR_ENABLED", "True").lower() == "true"

# Логгер для этого модуля
logger = logging.getLogger(__name__)


# Состояние конечного автомата для диалога
class DialogState(StatesGroup):
    waiting_for_message = State()   # бот ожидает сообщение от пользователя


# -------------------------------------------------------------------
# ВХОД В ДИАЛОГ
# -------------------------------------------------------------------
async def start_talk(message: types.Message, state: FSMContext):
    """
    Обработчик нажатия кнопки "💬 Поговорить".
    Устанавливает состояние диалога и показывает клавиатуру с кнопкой выхода.
    """
    await state.set_state(DialogState.waiting_for_message)
    await message.answer(
        "💬 Режим беседы включён. Напишите, что вас беспокоит.\n"
        "Чтобы завершить диалог, нажмите кнопку ниже.",
        reply_markup=dialog_kb
    )


# -------------------------------------------------------------------
# ВЫХОД ИЗ ДИАЛОГА
# -------------------------------------------------------------------
async def exit_dialog(message: types.Message, state: FSMContext):
    """
    Обработчик кнопки "❌ Завершить диалог".
    Сбрасывает состояние и возвращает главное меню.
    """
    await state.clear()
    await message.answer("Диалог завершён.", reply_markup=get_main_menu(message.from_user.id))


# -------------------------------------------------------------------
# ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ В ДИАЛОГЕ
# -------------------------------------------------------------------
async def process_dialog(message: types.Message, state: FSMContext):    # noqa
    """
    Главная логика диалога (новая модель баланса).
    """
    user_id = message.from_user.id
    user_text = message.text

    # ---------- 1. ПРОВЕРКА БАЛАНСА ----------
    allowed, balance = await try_decrement_balance(user_id)
    if not allowed:
        await message.answer(
            f"⚠️ У вас недостаточно сообщений.\n"
            f"Текущий баланс: {balance}\n"
            f"Пополнить баланс можно в Личном кабинете → Купить.",
            reply_markup=dialog_kb
        )
        return

    # ---------- 2. ДЕТЕКЦИЯ КРИЗИСНЫХ ФРАЗ ----------
    if CRISIS_ENABLED:
        is_crisis, matched_phrase = detect_crisis(user_text)
        if is_crisis:
            logger.warning(f"Обнаружена кризисная фраза: '{matched_phrase}'")
            await message.answer(
                get_crisis_response(),
                parse_mode="Markdown",
                reply_markup=dialog_kb
            )
            await save_message(user_id, "user", user_text)
            await save_message(user_id, "system", "[CRISIS DETECTED]")
            return

    # ---------- 3. СОХРАНЕНИЕ СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ ----------
    await save_message(user_id, "user", user_text)

    # ---------- 4. ТРИГГЕР СУММАРИЗАЦИИ ----------
    total_user_messages = await count_user_messages(user_id)
    if total_user_messages > 0 and total_user_messages % 30 == 0:
        logger.info(f"Создание суммаризации для пользователя {user_id} ({total_user_messages} сообщений)")
        messages_to_summarize, start_id, end_id = await get_messages_for_summary(user_id, limit=30)
        if messages_to_summarize:
            summary_text = await create_summary(messages_to_summarize)
            await save_summary(user_id, start_id, end_id, summary_text)
            logger.info(f"Суммаризация сохранена: {summary_text[:100]}...")

    # ---------- 5. ИНДИКАТОР «ПЕЧАТАЕТ» ----------
    await message.bot.send_chat_action(chat_id=user_id, action="typing")

    # ---------- 6. СБОР КОНТЕКСТА ----------
    summaries = await get_all_summaries(user_id)
    recent_messages = await get_recent_history(user_id, limit=20)

    history = []
    if summaries:
        combined_summary = "\n\n---\n\n".join(summaries)
        history.append({
            "role": "system",
            "content": f"Контекст предыдущих диалогов:\n{combined_summary}"
        })
    history.extend(recent_messages)

    # ---------- 7. ВЫЗОВ DEEPSEEK API ----------
    try:
        reply = await get_ai_response(history)
    except (APIError, APIConnectionError, RateLimitError, AuthenticationError) as e:
        logger.error(f"Ошибка DeepSeek API: {e}")
        await message.answer("😔 Сервис ИИ временно недоступен. Попробуйте позже.", reply_markup=dialog_kb)
        return
    except Exception as e:
        logger.exception(f"Неожиданная ошибка при вызове AI - {e}")
        await message.answer("😔 Произошла внутренняя ошибка. Мы уже работаем над исправлением.", reply_markup=dialog_kb)
        return

    # ---------- 8. ОТПРАВКА ОТВЕТА ----------
    try:
        await message.answer(reply, parse_mode="Markdown", reply_markup=dialog_kb)
    except Exception:  # noqa
        await message.answer(reply, reply_markup=dialog_kb)

    # ---------- 9. СОХРАНЕНИЕ ОТВЕТА ----------
    if reply:
        await save_message(user_id, "assistant", reply)

# -------------------------------------------------------------------
# РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ В ДИСПЕТЧЕРЕ
# -------------------------------------------------------------------
def register_dialog_handlers(dp):
    """
    Подключает все обработчики диалога к переданному диспетчеру.
    Вызывается из bot.py.
    """
    dp.message.register(start_talk, F.text == "💬 Поговорить")
    dp.message.register(exit_dialog, DialogState.waiting_for_message, F.text == "❌ Завершить диалог")
    dp.message.register(process_dialog, DialogState.waiting_for_message, F.text)
