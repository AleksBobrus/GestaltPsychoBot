# handlers/profile_handlers.py
# Личный кабинет пользователя: статистика и история тестов Бека,
# а также отображение остатка бесплатных сообщений на сегодня.

from aiogram import types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from database import get_message_count_today, get_user_bdi_results, get_bdi_statistics
from keyboards import main_menu_kb

# -------------------------------------------------------------------
# КЛАВИАТУРА ЛИЧНОГО КАБИНЕТА
# -------------------------------------------------------------------
profile_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Статистика тестов")],
        [KeyboardButton(text="📜 История тестов")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)


# -------------------------------------------------------------------
# ГЛАВНОЕ МЕНЮ ЛИЧНОГО КАБИНЕТА (с отображением остатка сообщений)
# -------------------------------------------------------------------
async def profile_menu(message: types.Message, state: FSMContext):
    """
    Показывает главное меню личного кабинета.
    Вызывается при нажатии кнопки "👤 Личный кабинет".
    Отображает:
      - количество сообщений, отправленных сегодня,
      - остаток бесплатных сообщений (20 - today_count).
    """
    user_id = message.from_user.id
    today_count = get_message_count_today(user_id)   # сколько уже отправлено
    remaining = max(0, 20 - today_count)            # остаток (не может быть отрицательным)

    await state.clear()   # очищаем любые активные состояния (например, если выходим из диалога)
    await message.answer(
        f"👤 **Личный кабинет**\n\n"
        f"📊 Сегодня вы отправили **{today_count}** из 20 бесплатных сообщений.\n"
        f"💬 Осталось сообщений на сегодня: **{remaining}**\n\n"
        f"Здесь вы можете посмотреть статистику и историю ваших тестов Бека.\n"
        f"Выберите действие:",
        parse_mode="Markdown",
        reply_markup=profile_kb
    )


# -------------------------------------------------------------------
# СТАТИСТИКА ТЕСТОВ БЕКА
# -------------------------------------------------------------------
async def show_stats(message: types.Message, state: FSMContext):
    """
    Показывает общую статистику по всем тестам Бека пользователя:
      - количество пройденных тестов,
      - средний балл,
      - минимальный и максимальный баллы,
      - последний результат.
    Если тестов нет – сообщает об этом.
    """
    user_id = message.from_user.id
    stats = get_bdi_statistics(user_id)

    if stats["count"] == 0:
        await message.answer(
            "📊 У вас пока нет пройденных тестов.\n"
            "Чтобы пройти тест Бека, вернитесь в главное меню и нажмите «📋 Пройти тест».",
            reply_markup=profile_kb
        )
        return

    text = (
        "📊 **Ваша статистика по тесту Бека**\n\n"
        f"📋 Всего пройдено: **{stats['count']}**\n"
        f"📈 Средний балл: **{stats['avg']}**\n"
        f"🔽 Минимальный балл: **{stats['min']}**\n"
        f"🔼 Максимальный балл: **{stats['max']}**\n"
        f"🔹 Последний результат: **{stats['last']}**\n\n"
        "ℹ️ **Интерпретация баллов:**\n"
        "0-9 — норма\n"
        "10-16 — лёгкая депрессия\n"
        "17-24 — умеренная депрессия\n"
        "25-30 — выраженная депрессия\n"
        "31-63 — тяжёлая депрессия"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=profile_kb)


# -------------------------------------------------------------------
# ИСТОРИЯ ТЕСТОВ БЕКА (последние 10)
# -------------------------------------------------------------------
async def show_history(message: types.Message, state: FSMContext):
    """
    Показывает последние 10 результатов тестов Бека с датами и интерпретацией.
    Если тестов нет – сообщает об этом.
    """
    user_id = message.from_user.id
    results = get_user_bdi_results(user_id, limit=10)

    if not results:
        await message.answer(
            "📜 У вас пока нет истории тестов.\n"
            "Пройдите тест Бека в главном меню.",
            reply_markup=profile_kb
        )
        return

    text = "📜 **История ваших тестов Бека (последние 10):**\n\n"
    for i, res in enumerate(results, 1):
        date_str = str(res['date'])[:10]                     # оставляем только год-месяц-день
        text += f"{i}. **{date_str}** – балл: **{res['score']}** ({res['interpretation']})\n"
        # Защита от слишком длинного сообщения (Telegram лимит 4096 символов)
        if len(text) > 3800:
            text += "\n... (и ещё более ранние записи)"
            break

    await message.answer(text, parse_mode="Markdown", reply_markup=profile_kb)


# -------------------------------------------------------------------
# ВОЗВРАТ В ГЛАВНОЕ МЕНЮ
# -------------------------------------------------------------------
async def back_to_main(message: types.Message, state: FSMContext):
    """
    Возвращает пользователя из личного кабинета в главное меню.
    """
    await state.clear()
    await message.answer("Возврат в главное меню.", reply_markup=main_menu_kb)


# -------------------------------------------------------------------
# РЕГИСТРАЦИЯ ОБРАБОТЧИКОВ
# -------------------------------------------------------------------
def register_profile_handlers(dp):
    """
    Регистрирует все обработчики личного кабинета в диспетчере.
    Вызывается из bot.py.
    """
    dp.message.register(profile_menu, F.text == "👤 Личный кабинет")
    dp.message.register(show_stats, F.text == "📊 Статистика тестов")
    dp.message.register(show_history, F.text == "📜 История тестов")
    dp.message.register(back_to_main, F.text == "🔙 Назад")
