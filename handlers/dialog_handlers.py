# handlers/dialog_handlers.py
# Здесь реализован режим диалога с использованием DeepSeek API,
# с сохранением истории в SQLite
# Этот файл содержит все обработчики для кнопки "💬 Поговорить":
# вход в диалог, выход, обработка сообщений с ИИ.
# Добавлена проверка лимита бесплатных сообщений (20 в день).

# -------------------------------------------------------------------
# ИМПОРТЫ
# -------------------------------------------------------------------
import asyncio  # <-- Добавляет задержку индикатора печати
from aiogram import types, F    # типы Telegram и фильтры
from aiogram.fsm.context import FSMContext       # контекст машины состояний
from aiogram.fsm.state import State, StatesGroup # для определения состояний
from aiogram.types import ReplyKeyboardRemove    # для принудительного удаления клавиатуры
from keyboards import dialog_kb, main_menu_kb    # наши клавиатуры (импорт из keyboards.py)
from ai_client import get_ai_response            # функция вызова DeepSeek API
from database import (
    init_db, save_message, get_recent_history,
    can_send_message, increment_message_count, get_message_count_today,
    count_user_messages, get_messages_for_summary, save_summary, get_all_summaries
)   # <-- добавил базу данных
from crisis_detector import detect_crisis, get_crisis_response  # детектор кризисов
from ai_client import get_ai_response, create_summary  # AI функции

# -------------------------------------------------------------------
# ХРАНИЛИЩЕ ИСТОРИИ СООБЩЕНИЙ (в базе данных SQLite)
# -------------------------------------------------------------------
# Инициализируем базу данных (создаёт таблицы, если их нет)
init_db()

# -------------------------------------------------------------------
# FSM СОСТОЯНИЕ ДЛЯ РЕЖИМА ДИАЛОГА
# -------------------------------------------------------------------
class DialogState(StatesGroup):
    """
    Состояние ожидания сообщения от пользователя.
    Когда бот находится в этом состоянии, все текстовые сообщения
    (кроме команды выхода) направляются в обработчик process_dialog.
    """
    waiting_for_message = State()   # бот ожидает сообщение от пользователя

# -------------------------------------------------------------------
# ВХОД В РЕЖИМ ДИАЛОГА (кнопка "Поговорить")
# -------------------------------------------------------------------
async def start_talk(message: types.Message, state: FSMContext):
    """
    Обработчик нажатия кнопки "💬 Поговорить".
    Устанавливает состояние ожидания сообщения и показывает клавиатуру с кнопкой "Завершить диалог".
    """
    await state.set_state(DialogState.waiting_for_message)
    await message.answer(
        "💬 Режим беседы включён. Напишите, что вас беспокоит.\n"
        "Чтобы завершить диалог, нажмите кнопку ниже.",
        reply_markup=dialog_kb
    )

# -------------------------------------------------------------------
# ВЫХОД ИЗ РЕЖИМА ДИАЛОГА (кнопка "Завершить диалог")
# -------------------------------------------------------------------
async def exit_dialog(message: types.Message, state: FSMContext):
    """
    Вызывается при нажатии кнопки "❌ Завершить диалог" в состоянии диалога.
    - Сбрасывает состояние FSM.
    - Убирает клавиатуру диалога и показывает главное меню.
    """
    # user_id = message.from_user.id
    # Раскомментируйте следующую строку, если хотите удалять историю при выходе
    # clear_user_history(user_id)

    await state.clear()
    # Сбрасываем состояние FSM
    # Telegram может не сразу обновить клавиатуру, поэтому сначала отправляем сообщение
    # с ReplyKeyboardRemove (удаляет текущую клавиатуру),
    # Сначала убираем клавиатуру диалога
    # await message.answer("Диалог завершён.", reply_markup=ReplyKeyboardRemove())

    # затем отдельным сообщением показываем главное меню.
    await message.answer("Диалог завершён.", reply_markup=main_menu_kb)


# -------------------------------------------------------------------
# ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ В РЕЖИМЕ ДИАЛОГА (с DeepSeek и лимитом)
# -------------------------------------------------------------------
async def process_dialog(message: types.Message, state: FSMContext):
    """
    Обрабатывает текстовые сообщения в режиме диалога.
    Шаги:
    1. Проверка лимита бесплатных сообщений (20 в день).
    2. Детекция кризиса (суицидальные мысли, самоповреждение).
    3. Сохранение сообщения пользователя в БД.
    4. Увеличение счётчика сообщений.
    5. Отправка индикатора "печатает".
    6. Получение контекста (последние 20 сообщений).
    7. Вызов DeepSeek API.
    8. Сохранение ответа бота.
    9. Отправка ответа пользователю.
    """
    user_id = message.from_user.id
    user_text = message.text

    # ---------- ШАГ 1: ПРОВЕРКА ЛИМИТА (20 сообщений в день) ----------
    if not can_send_message(user_id, limit=20):
        from datetime import datetime, timedelta
        today_count = get_message_count_today(user_id)

        # Вычисляем время до полуночи (сброса лимита)
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

    # ---------- ШАГ 2: ДЕТЕКЦИЯ КРИЗИСА ----------
    is_crisis, matched_phrase = detect_crisis(user_text)
    if is_crisis:
        print(f"⚠️ [CRISIS] Обнаружена кризисная фраза: '{matched_phrase}'")
        await message.answer(
            get_crisis_response(),
            parse_mode="Markdown",
            reply_markup=dialog_kb
        )
        # Сохраняем сообщение пользователя для статистики (но не отправляем в AI)
        save_message(user_id, "user", user_text)
        save_message(user_id, "system", "[CRISIS DETECTED]")
        return

    # ---------- ШАГ 3: СОХРАНЕНИЕ СООБЩЕНИЯ ПОЛЬЗОВАТЕЛЯ ----------
    save_message(user_id, "user", user_text)

    # ---------- ШАГ 4: УВЕЛИЧЕНИЕ СЧЁТЧИКА СООБЩЕНИЙ ----------
    new_count = increment_message_count(user_id)
    print(f"[INFO] Сообщение {new_count}/20 получено")

    # ---------- ШАГ 4.5: ТРИГГЕР СУММАРИЗАЦИИ (каждые 30 сообщений) ----------
    total_user_messages = count_user_messages(user_id)
    if total_user_messages > 0 and total_user_messages % 30 == 0:
        print(f"[INFO] Создание суммаризации для пользователя {user_id} ({total_user_messages} сообщений)")
        messages_to_summarize, start_id, end_id = get_messages_for_summary(user_id, limit=30)
        if messages_to_summarize:
            summary_text = create_summary(messages_to_summarize)
            save_summary(user_id, start_id, end_id, summary_text)
            print(f"[INFO] Суммаризация сохранена: {summary_text[:100]}...")

    # ---------- ШАГ 5: ИНДИКАТОР "ПЕЧАТАЕТ" ----------
    await message.bot.send_chat_action(chat_id=user_id, action="typing")
    # Небольшая пауза, чтобы индикатор успел отобразиться
    await asyncio.sleep(0.5)

    # ---------- ШАГ 6: ПОЛУЧЕНИЕ КОНТЕКСТА (суммаризации + последние 20 сообщений) ----------
    # Загружаем все суммаризации (выжимки прошлых диалогов)
    summaries = get_all_summaries(user_id)

    # Загружаем последние 20 сообщений
    recent_messages = get_recent_history(user_id, limit=20)

    # Формируем полный контекст: суммаризации как system-сообщения + последние сообщения
    history = []
    if summaries:
        # Добавляем суммаризации как контекст от системы
        combined_summary = "\n\n---\n\n".join(summaries)
        history.append({
            "role": "system",
            "content": f"Контекст предыдущих диалогов:\n{combined_summary}"
        })

    # Добавляем последние сообщения
    history.extend(recent_messages)

    # ---------- ШАГ 7: ВЫЗОВ DEEPSEEK API ----------
    try:
        reply = get_ai_response(history)
    except Exception as e:
        print(f"❌ Критическая ошибка при вызове AI: {e}")
        await message.answer(
            "😔 Произошла ошибка при обращении к ИИ. Пожалуйста, попробуйте позже.",
            reply_markup=dialog_kb
        )
        return

    # ---------- ШАГ 8: СОХРАНЕНИЕ ОТВЕТА БОТА ----------
    save_message(user_id, "assistant", reply)

    # ---------- ШАГ 9: ОТПРАВКА ОТВЕТА ПОЛЬЗОВАТЕЛЮ ----------
    # Отправляем ответ, оставляя ту же клавиатуру (чтобы можно было выйти)
    try:
        await message.answer(reply, parse_mode="Markdown", reply_markup=dialog_kb)
    except Exception as e:
        # Если Markdown не распарсился, отправляем без форматирования
        print(f"⚠️ Ошибка парсинга Markdown: {e}")
        await message.answer(reply, reply_markup=dialog_kb)

# -------------------------------------------------------------------
# РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ В ДИСПЕТЧЕРЕ
# -------------------------------------------------------------------
def register_dialog_handlers(dp):
    """
    Регистрирует все обработчики диалога в переданном диспетчере.
    Вызывается из bot.py.
    """
    # Вход в диалог (кнопка "Поговорить")
    dp.message.register(start_talk, F.text == "💬 Поговорить")

    # Выход из диалога (кнопка "Завершить диалог") – только в состоянии диалога
    dp.message.register(exit_dialog, DialogState.waiting_for_message, F.text == "❌ Завершить диалог")

    # Обработка текстовых сообщений в состоянии диалога (кроме кнопки выхода)
    dp.message.register(process_dialog, DialogState.waiting_for_message, F.text)
