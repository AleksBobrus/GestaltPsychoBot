# handlers/dialog_handlers.py
# Обработчики режима диалога с ИИ-психологом.
# Версия 4.0.0 – проверка Premium-подписки вместо баланса сообщений.

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
    count_user_messages, get_messages_for_summary, save_summary, get_all_summaries,
    start_session, end_session, increment_session_message_count, get_session_message_count,
    is_premium_active, get_subscription_days_left
)
from crisis_detector import detect_crisis, get_crisis_response

load_dotenv()
CRISIS_ENABLED = os.getenv("CRISIS_DETECTOR_ENABLED", "True").lower() == "true"

logger = logging.getLogger(__name__)


# Состояние конечного автомата для диалога
class DialogState(StatesGroup):
    waiting_for_message = State()


# -------------------------------------------------------------------
# ВХОД В ДИАЛОГ
# -------------------------------------------------------------------
async def start_talk(message: types.Message, state: FSMContext):
    await state.set_state(DialogState.waiting_for_message)

    session_id = await start_session(message.from_user.id)
    await state.update_data(session_id=session_id)

    await message.answer(
        "🌿 **Начало сессии** 🌿\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💬 *Вы можете:*\n"
        "• Написать «Хочу поговорить о…» и поделиться тем, что беспокоит.\n"
        "• Попросить напомнить, о чём мы беседовали в прошлые разы.\n"
        "• Просто написать что угодно — мы начнём диалог.\n\n"
        "_Я здесь и внимательно слушаю_ 🤍",
        parse_mode="Markdown",
        reply_markup=dialog_kb
    )


# -------------------------------------------------------------------
# ВЫХОД ИЗ ДИАЛОГА
# -------------------------------------------------------------------
async def exit_dialog(message: types.Message, state: FSMContext):
    data = await state.get_data()
    session_id = data.get("session_id")

    if session_id:
        count = await get_session_message_count(session_id)
        await end_session(session_id, count)

    await state.clear()
    await message.answer(
        "✅ *Диалог завершён.*\n"
        "До новых встреч!",
        reply_markup=get_main_menu(message.from_user.id),
        parse_mode="Markdown"
    )


# -------------------------------------------------------------------
# ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ В ДИАЛОГЕ (С ПРОВЕРКОЙ PREMIUM)
# -------------------------------------------------------------------
async def process_dialog(message: types.Message, state: FSMContext):
    """
    Главная логика диалога:
    1. Проверка активной Premium-подписки.
    2. Детекция кризисных фраз.
    3. Сохранение сообщения и учёт в сессии.
    4. Триггер суммаризации.
    5. Индикатор «печатает».
    6. Сбор контекста.
    7. Вызов DeepSeek API.
    8. Отправка ответа.
    9. Сохранение ответа в БД.
    """
    user_id = message.from_user.id
    user_text = message.text

    # ---------- 1. ПРОВЕРКА PREMIUM-ПОДПИСКИ ----------
    if not await is_premium_active(user_id):
        days_left = await get_subscription_days_left(user_id)
        if days_left is None:
            # Подписка никогда не была активирована (маловероятно, но для надёжности)
            await message.answer(
                "😔 *Ваша подписка завершена.*\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Чтобы продолжить, оформите подписку в Личном кабинете → Продлить подписку.",
                reply_markup=dialog_kb,
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                "😔 *Ваша подписка завершена.*\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Чтобы продолжить, оформите подписку в Личном кабинете → Продлить подписку.",
                reply_markup=dialog_kb,
                parse_mode="Markdown"
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

    # ---------- 3. СОХРАНЕНИЕ СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ И УЧЁТ В СЕССИИ ----------
    await save_message(user_id, "user", user_text)

    data = await state.get_data()
    session_id = data.get("session_id")
    if session_id:
        await increment_session_message_count(session_id)

    # ---------- 4. ТРИГГЕР СУММАРИЗАЦИИ (каждые 30 сообщений) ----------
    total_user_messages = await count_user_messages(user_id)
    if total_user_messages > 0 and total_user_messages % 30 == 0:
        logger.info(f"Создание суммаризации для {user_id} ({total_user_messages} сообщений)")
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

    # ---------- 7. ВЫЗОВ DEEPSEEK API (БЕЗ ЛИМИТОВ) ----------
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
    dp.message.register(start_talk, F.text == "💬 Начать сессию")
    dp.message.register(exit_dialog, DialogState.waiting_for_message, F.text == "❌ Завершить диалог")
    dp.message.register(process_dialog, DialogState.waiting_for_message, F.text)
