# handlers/dialog_handlers.py
# Обработчики режима диалога с ИИ-психологом.
# Включает: вход/выход, проверку баланса, детектор кризиса, вызов DeepSeek API,
# суммаризацию, сохранение истории, учёт сессий и глобальный лимит сообщений.

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
    count_user_messages, get_messages_for_summary, save_summary, get_all_summaries,
    start_session, end_session, increment_session_message_count, get_session_message_count,
    increment_global_message_count, get_global_message_count
)
from crisis_detector import detect_crisis, get_crisis_response

load_dotenv()
# Читаем настройку детектора кризиса из .env (True/False)
CRISIS_ENABLED = os.getenv("CRISIS_DETECTOR_ENABLED", "True").lower() == "true"

# Глобальный лимит сообщений ИИ (после достижения бот приостанавливается)
GLOBAL_MESSAGE_LIMIT = 500

logger = logging.getLogger(__name__)


# Состояние конечного автомата для диалога
class DialogState(StatesGroup):
    waiting_for_message = State()   # бот ожидает сообщение от пользователя


# -------------------------------------------------------------------
# ВХОД В ДИАЛОГ
# -------------------------------------------------------------------
async def start_talk(message: types.Message, state: FSMContext):
    """
    Обработчик нажатия кнопки "💬 Начать сессию" (или другой текст кнопки).
    Устанавливает состояние диалога, начинает новую сессию и показывает приветствие.
    """
    await state.set_state(DialogState.waiting_for_message)

    # Начинаем сессию (для подсчёта завершённых диалогов)
    session_id = await start_session(message.from_user.id)
    await state.update_data(session_id=session_id)

    await message.answer(
        "🌿 **Начало сессии** 🌿\n\n"
        "💬 Вы можете:\n"
        "• Написать «Хочу поговорить о…» и поделиться тем, что беспокоит.\n"
        "• Попросить напомнить, о чём мы беседовали в прошлые разы.\n"
        "• Просто написать что угодно — мы начнём диалог.\n\n"
        "Я здесь и внимательно слушаю 🤍",
        parse_mode="Markdown",
        reply_markup=dialog_kb
    )


# -------------------------------------------------------------------
# ВЫХОД ИЗ ДИАЛОГА
# -------------------------------------------------------------------
async def exit_dialog(message: types.Message, state: FSMContext):
    """
    Обработчик кнопки "❌ Завершить диалог".
    Завершает текущую сессию и возвращает главное меню.
    """
    data = await state.get_data()
    session_id = data.get("session_id")

    if session_id:
        # Получаем количество сообщений в сессии и завершаем её
        count = await get_session_message_count(session_id)
        await end_session(session_id, count)

    await state.clear()
    await message.answer("Диалог завершён.", reply_markup=get_main_menu(message.from_user.id))


# -------------------------------------------------------------------
# ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ В ДИАЛОГЕ
# -------------------------------------------------------------------
async def process_dialog(message: types.Message, state: FSMContext):
    """
    Главная логика диалога:
    1. Проверка баланса пользователя.
    2. Детекция кризисных фраз.
    3. Сохранение сообщения и учёт в сессии.
    4. Триггер суммаризации.
    5. Индикатор «печатает».
    6. Сбор контекста.
    7. Проверка глобального лимита сообщений ИИ.
    8. Вызов DeepSeek API.
    9. Увеличение глобального счётчика и уведомление админа при лимите.
    10. Отправка ответа.
    11. Сохранение ответа в БД.
    """
    user_id = message.from_user.id
    user_text = message.text

    # ---------- 1. ПРОВЕРКА БАЛАНСА ПОЛЬЗОВАТЕЛЯ ----------
    # Атомарно проверяем, что баланс > 0, и уменьшаем на 1
    allowed, balance = await try_decrement_balance(user_id)
    if not allowed:
        await message.answer(
            f"⚠️ У вас недостаточно сообщений.\n"
            f"Текущий баланс: {balance}\n"
            f"Пополнить баланс можно в Личном кабинете → Купить.",
            reply_markup=dialog_kb
        )
        return

    # ---------- 2. ДЕТЕКЦИЯ КРИЗИСНЫХ ФРАЗ (если включено) ----------
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

    # ---------- 7. ПРОВЕРКА ГЛОБАЛЬНОГО ЛИМИТА СООБЩЕНИЙ ИИ ----------
    total_messages = await get_global_message_count()
    if total_messages >= GLOBAL_MESSAGE_LIMIT:
        await message.answer(
            "😔 Бот временно приостановлен на техническое обслуживание. Пожалуйста, зайдите позже.",
            reply_markup=dialog_kb
        )
        return

    # ---------- 8. ВЫЗОВ DEEPSEEK API ----------
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

    # ---------- 9. УВЕЛИЧЕНИЕ ГЛОБАЛЬНОГО СЧЁТЧИКА И УВЕДОМЛЕНИЕ АДМИНА ----------
    new_total = await increment_global_message_count()
    logger.info(f"Глобальный счётчик ИИ-сообщений: {new_total} / {GLOBAL_MESSAGE_LIMIT}")

    # Каждое 10-е сообщение (10, 20, ..., 500) уведомляем админов о текущем прогрессе
    if new_total % 10 == 0:
        admin_ids_str = os.getenv("ADMIN_IDS", "")
        if admin_ids_str:
            for admin_id in map(int, admin_ids_str.split(",")):
                try:
                    await message.bot.send_message(
                        admin_id,
                        f"📊 Глобальный счётчик: {new_total} / {GLOBAL_MESSAGE_LIMIT}"
                    )
                except Exception as e:
                    logger.warning(f"Не удалось отправить уведомление админу {admin_id}: {e}")

    # Отдельное уведомление при достижении лимита (500)
    if new_total == GLOBAL_MESSAGE_LIMIT:
        admin_ids_str = os.getenv("ADMIN_IDS", "")
        if admin_ids_str:
            for admin_id in map(int, admin_ids_str.split(",")):
                try:
                    await message.bot.send_message(
                        admin_id,
                        f"⚠️ Достигнут лимит в {GLOBAL_MESSAGE_LIMIT} сообщений! Бот больше не отвечает на диалоги."
                    )
                except Exception as e:
                    logger.warning(f"Не удалось уведомить админа {admin_id}: {e}")

    # ---------- 10. ОТПРАВКА ОТВЕТА ПОЛЬЗОВАТЕЛЮ ----------
    try:
        await message.answer(reply, parse_mode="Markdown", reply_markup=dialog_kb)
    except Exception:  # noqa
        await message.answer(reply, reply_markup=dialog_kb)

    # ---------- 11. СОХРАНЕНИЕ ОТВЕТА В БД ----------
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
    # Вход в диалог (текст кнопки должен совпадать с тем, что в keyboards.py)
    dp.message.register(start_talk, F.text == "💬 Начать сессию")
    # Выход из диалога
    dp.message.register(exit_dialog, DialogState.waiting_for_message, F.text == "❌ Завершить диалог")
    # Обработка текстовых сообщений в состоянии диалога
    dp.message.register(process_dialog, DialogState.waiting_for_message, F.text)
