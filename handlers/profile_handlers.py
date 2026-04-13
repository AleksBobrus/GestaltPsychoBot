# handlers/profile_handlers.py
# Личный кабинет пользователя: статистика и история тестов Бека

from aiogram import types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from database import get_user_bdi_results, get_bdi_statistics
from keyboards import main_menu_kb

# -------------------------------------------------------------------
# КЛАВИАТУРА ЛИЧНОГО КАБИНЕТА
# -------------------------------------------------------------------
# Состоит из двух кнопок действий и кнопки возврата.
profile_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 Статистика тестов")],
        [KeyboardButton(text="📜 История тестов")],
        [KeyboardButton(text="🔙 Назад")]
    ],
    resize_keyboard=True
)

# -------------------------------------------------------------------
# ГЛАВНОЕ МЕНЮ ЛИЧНОГО КАБИНЕТА
# -------------------------------------------------------------------
async def profile_menu(message: types.Message, state: FSMContext):
    """
    Показывает главное меню личного кабинета.
    Вызывается при нажатии кнопки "👤 Личный кабинет".
    """

    await state.clear()  # очищаем любое активное состояние (например, диалог)
    await message.answer(
        "👤 **Личный кабинет**\n\n"
        "Здесь вы можете посмотреть статистику и историю ваших тестов Бека.\n"
        "Выберите действие:",
        parse_mode="Markdown",
        reply_markup=profile_kb
    )

# -------------------------------------------------------------------
# СТАТИСТИКА ТЕСТОВ
# -------------------------------------------------------------------
async def show_stats(message: types.Message, state: FSMContext):
    """
    Показывает общую статистику по всем тестам Бека пользователя.
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
# ИСТОРИЯ ТЕСТОВ
# -------------------------------------------------------------------
async def show_history(message: types.Message, state: FSMContext):
    """
    Показывает последние 10 результатов тестов Бека с датами.
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
        # Извлекаем только дату (год-месяц-день)
        date_str = str(res['date'])[:10]
        text += f"{i}. **{date_str}** – балл: **{res['score']}** ({res['interpretation']})\n"

    # Telegram имеет ограничение на длину сообщения (4096 символов)
    if len(text) > 4000:
        text = text[:4000] + "\n... (слишком много записей)"

    await message.answer(text, parse_mode="Markdown", reply_markup=profile_kb)

# -------------------------------------------------------------------
# ВОЗВРАТ В ГЛАВНОЕ МЕНЮ
# -------------------------------------------------------------------
async def back_to_main(message: types.Message, state: FSMContext):
    """
    Возвращает пользователя в главное меню из личного кабинета.
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