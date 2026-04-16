# handlers/dialog_handlers.py
# Асинхронная версия с aiosqlite и улучшенной обработкой ошибок.
# Сохраняет всю функциональность: диалог с DeepSeek, лимиты, кризис-детектор, суммаризацию.

import asyncio
from aiogram import types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from keyboards import dialog_kb, main_menu_kb
from ai_client import get_ai_response, create_summary
from database import (
    init_db, save_message, get_recent_history,
    can_send_message, increment_message_count, get_message_count_today,
    count_user_messages, get_messages_for_summary, save_summary, get_all_summaries
)
from crisis_detector import detect_crisis, get_crisis_response

# Инициализация базы данных (теперь асинхронная)
# Вызов init_db() должен быть выполнен один раз при старте бота (в bot.py)
# Здесь оставляем импорт, саму инициализацию перенесём в bot.py

class DialogState(StatesGroup):
    waiting_for_message = State()


# -------------------------------------------------------------------
# ВХОД В ДИАЛОГ
# -------------------------------------------------------------------
async def start_talk(message: types.Message, state: FSMContext):
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
    await state.clear()
    await message.answer("Диалог завершён.", reply_markup=main_menu_kb)


# -------------------------------------------------------------------
# ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ
# -------------------------------------------------------------------
async def process_dialog(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_text = message.text

    # --- 1. Проверка лимита ---
    if not await can_send_message(user_id, limit=20):
        from datetime import datetime, timedelta
        today_count = await get_message_count_today(user_id)
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        time_until_reset = tomorrow - now
        hours, remainder = divmod(int(time_until_reset.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)

        await message.answer(
            f"⚠️ Вы исчерпали лимит бесплатных сообщений на сегодня.\n"
            f"Отправлено: {today_count} из 20\n\n"
            f"⏰ До сброса лимита: {hours} ч {minutes} мин\n"
            f"Возвращайтесь завтра!",
            reply_markup=dialog_kb
        )
        return

    # --- 2. Детекция кризиса ---
    is_crisis, matched_phrase = detect_crisis(user_text)
    if is_crisis:
        print(f"⚠️ [CRISIS] Обнаружена кризисная фраза: '{matched_phrase}'")
        await message.answer(
            get_crisis_response(),
            parse_mode="Markdown",
            reply_markup=dialog_kb
        )
        await save_message(user_id, "user", user_text)
        await save_message(user_id, "system", "[CRISIS DETECTED]")
        return

    # --- 3. Сохранение сообщения пользователя ---
    await save_message(user_id, "user", user_text)

    # --- 4. Увеличение счётчика ---
    new_count = await increment_message_count(user_id)
    print(f"[INFO] Сообщение {new_count}/20 получено")

    # --- 5. Триггер суммаризации (каждые 30 сообщений) ---
    total_user_messages = await count_user_messages(user_id)
    if total_user_messages > 0 and total_user_messages % 30 == 0:
        print(f"[INFO] Создание суммаризации для пользователя {user_id} ({total_user_messages} сообщений)")
        messages_to_summarize, start_id, end_id = await get_messages_for_summary(user_id, limit=30)
        if messages_to_summarize:
            summary_text = await create_summary(messages_to_summarize)
            await save_summary(user_id, start_id, end_id, summary_text)
            print(f"[INFO] Суммаризация сохранена: {summary_text[:100]}...")

    # --- 6. Индикатор «печатает» ---
    await message.bot.send_chat_action(chat_id=user_id, action="typing")
    # Пауза больше не нужна, индикатор держится сам

    # --- 7. Сбор контекста (суммаризации + последние 20 сообщений) ---
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

    # --- 8. Вызов DeepSeek API ---
    try:
        reply = await get_ai_response(history)
    except Exception as e:
        print(f"❌ Критическая ошибка при вызове AI: {e}")
        await message.answer(
            "😔 Произошла ошибка при обращении к ИИ. Пожалуйста, попробуйте позже.",
            reply_markup=dialog_kb
        )
        return

    # --- 9. Сохранение ответа бота ---
    await save_message(user_id, "assistant", reply)

    # --- 10. Отправка ответа ---
    try:
        await message.answer(reply, parse_mode="Markdown", reply_markup=dialog_kb)
    except Exception:
        # fallback без Markdown
        await message.answer(reply, reply_markup=dialog_kb)


# -------------------------------------------------------------------
# РЕГИСТРАЦИЯ ХЕНДЛЕРОВ
# -------------------------------------------------------------------
def register_dialog_handlers(dp):
    dp.message.register(start_talk, F.text == "💬 Поговорить")
    dp.message.register(exit_dialog, DialogState.waiting_for_message, F.text == "❌ Завершить диалог")
    dp.message.register(process_dialog, DialogState.waiting_for_message, F.text)
