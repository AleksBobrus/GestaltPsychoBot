# handlers/dialog_handlers.py
# Обработчики режима диалога с ИИ-психологом.
# Включает: вход/выход, атомарную проверку лимита, детектор кризиса,
# вызов DeepSeek API (без стриминга), суммаризацию и сохранение истории.

import logging
from datetime import datetime, timedelta
from aiogram import types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from openai import APIError, APIConnectionError, RateLimitError, AuthenticationError
from keyboards import dialog_kb, main_menu_kb
from ai_client import get_ai_response, create_summary
from database import (
    save_message, get_recent_history,
    try_increment_and_check_limit,
    count_user_messages, get_messages_for_summary, save_summary, get_all_summaries
)
from crisis_detector import detect_crisis, get_crisis_response

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
    await message.answer("Диалог завершён.", reply_markup=main_menu_kb)


# -------------------------------------------------------------------
# ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ В ДИАЛОГЕ
# -------------------------------------------------------------------
async def process_dialog(message: types.Message, state: FSMContext): # noqa
    """
    Главная логика диалога:
    1. Атомарная проверка и увеличение дневного лимита.
    2. Детекция кризисных фраз.
    3. Сохранение сообщения пользователя в БД.
    4. Триггер суммаризации (каждые 30 сообщений).
    5. Отправка индикатора "печатает".
    6. Сбор контекста (суммаризации + последние 20 сообщений).
    7. Вызов DeepSeek API для получения полного ответа.
    8. Отправка ответа пользователю.
    9. Сохранение ответа в БД.
    """
    user_id = message.from_user.id
    user_text = message.text

    # ---------- 1. АТОМАРНАЯ ПРОВЕРКА ЛИМИТА ----------
    # Функция try_increment_and_check_limit одновременно проверяет,
    # не превышен ли дневной лимит, и увеличивает счётчик.
    # Возвращает (разрешено, количество_сообщений).
    allowed, count_or_limit = await try_increment_and_check_limit(user_id, limit=20)
    if not allowed:
        # Лимит исчерпан – вычисляем время до сброса (полночь)
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        time_until_reset = tomorrow - now
        hours, remainder = divmod(int(time_until_reset.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)

        await message.answer(
            f"⚠️ Вы исчерпали лимит бесплатных сообщений на сегодня.\n"
            f"Отправлено: {count_or_limit} из 20\n\n"
            f"⏰ До сброса лимита: {hours} ч {minutes} мин\n"
            f"Возвращайтесь завтра!",
            reply_markup=dialog_kb
        )
        return  # прерываем обработку

    # ---------- 2. ДЕТЕКЦИЯ КРИЗИСНЫХ ФРАЗ ----------
    # Проверяем, не содержит ли сообщение маркеров суицидальных мыслей и т.п.
    is_crisis, matched_phrase = detect_crisis(user_text)
    if is_crisis:
        logger.warning(f"Обнаружена кризисная фраза: '{matched_phrase}'")
        await message.answer(
            get_crisis_response(),
            parse_mode="Markdown",
            reply_markup=dialog_kb
        )
        # Сохраняем сообщение пользователя и метку о кризисе, но не отправляем в ИИ
        await save_message(user_id, "user", user_text)
        await save_message(user_id, "system", "[CRISIS DETECTED]")
        return

    # ---------- 3. СОХРАНЕНИЕ СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ ----------
    await save_message(user_id, "user", user_text)

    # ---------- 4. ТРИГГЕР СУММАРИЗАЦИИ (каждые 30 сообщений) ----------
    # Каждые 30 сообщений пользователя создаём краткую выжимку диалога через DeepSeek
    total_user_messages = await count_user_messages(user_id)
    if total_user_messages > 0 and total_user_messages % 30 == 0:
        logger.info(f"Создание суммаризации для пользователя {user_id} ({total_user_messages} сообщений)")
        messages_to_summarize, start_id, end_id = await get_messages_for_summary(user_id, limit=30)
        if messages_to_summarize:
            summary_text = await create_summary(messages_to_summarize)
            await save_summary(user_id, start_id, end_id, summary_text)
            logger.info(f"Суммаризация сохранена: {summary_text[:100]}...")

    # ---------- 5. ИНДИКАТОР «ПЕЧАТАЕТ» ----------
    # Показываем пользователю, что бот генерирует ответ
    await message.bot.send_chat_action(chat_id=user_id, action="typing")

    # ---------- 6. СБОР КОНТЕКСТА ----------
    # Загружаем все предыдущие суммаризации (выжимки старых диалогов)
    summaries = await get_all_summaries(user_id)
    # Загружаем последние 20 сообщений (актуальный контекст)
    recent_messages = await get_recent_history(user_id, limit=20)

    history = []
    if summaries:
        # Объединяем суммаризации и добавляем как системное сообщение
        combined_summary = "\n\n---\n\n".join(summaries)
        history.append({
            "role": "system",
            "content": f"Контекст предыдущих диалогов:\n{combined_summary}"
        })
    # Добавляем последние сообщения
    history.extend(recent_messages)

    # ---------- 7. ВЫЗОВ DEEPSEEK API (БЕЗ СТРИМИНГА) ----------
    # Используем обычный вызов, так как стриминг пока нестабилен
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

    # ---------- 8. ОТПРАВКА ОТВЕТА ПОЛЬЗОВАТЕЛЮ ----------
    try:
        # Пытаемся отправить с Markdown-разметкой
        await message.answer(reply, parse_mode="Markdown", reply_markup=dialog_kb)
    except Exception:   # noqa
        # Если Markdown сломался, отправляем без форматирования
        await message.answer(reply, reply_markup=dialog_kb)

    # ---------- 9. СОХРАНЕНИЕ ОТВЕТА В БД ----------
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
