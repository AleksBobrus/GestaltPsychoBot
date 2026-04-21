# handlers/profile_handlers.py
# Личный кабинет пользователя: баланс сообщений, история тестов, приглашение друга, покупки.
# Кнопка "Купить" ведёт на заглушку (в будущем – пополнение баланса).

import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from keyboards import get_main_menu
from database import get_user_info, get_user_bdi_results, get_balance

logger = logging.getLogger(__name__)
router = Router()


def get_profile_keyboard() -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура для главного экрана личного кабинета.
    Кнопки:
      - История тестов
      - Пригласить друга
      - Купить
      - Главное меню (возврат)
    """
    buttons = [
        [InlineKeyboardButton(text="📜 История тестов", callback_data="profile_tests")],
        [InlineKeyboardButton(text="🎁 Пригласить друга", callback_data="profile_invite")],
        [InlineKeyboardButton(text="🛒 Купить", callback_data="profile_purchases")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="profile_back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_tests_keyboard() -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура для раздела истории тестов.
    Кнопки:
      - Пройти тест (заглушка)
      - Назад (в личный кабинет)
    """
    buttons = [
        [InlineKeyboardButton(text="📋 Пройти тест", callback_data="profile_start_test")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="profile_back_from_tests")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# -------------------------------------------------------------------
# ТОЧКА ВХОДА: КНОПКА «👤 ЛИЧНЫЙ КАБИНЕТ» (Reply-кнопка)
# -------------------------------------------------------------------
@router.message(F.text == "👤 Личный кабинет")
async def profile_main(message: types.Message, state: FSMContext):
    """
    Открывает главное меню личного кабинета.
    Если профиль пользователя ещё не создан (например, не введено имя),
    предлагается завершить регистрацию через /start.
    """
    await state.clear()
    user_id = message.from_user.id

    # Получаем информацию о пользователе из БД
    info = await get_user_info(user_id)

    # Если записи нет или отсутствует дата регистрации – профиль не заполнен
    if not info or info.get('created_at') is None:
        await message.answer(
            "⚠️ Ваш профиль ещё не заполнен. Пожалуйста, нажмите /start и введите ваше имя.",
            reply_markup=get_main_menu(user_id)
        )
        return

    # Получаем последний результат теста Бека
    try:
        test_results = await get_user_bdi_results(user_id, limit=1)
    except Exception as e:
        logger.warning(f"Ошибка получения тестов для {user_id}: {e}")
        test_results = []

    if test_results:
        last_test = test_results[0]
        test_line = f"📋 Тест Бека: {last_test['score']} баллов ({last_test['interpretation']})"
    else:
        test_line = "📋 Тест Бека: не пройден"

    # Получаем текущий баланс
    balance = await get_balance(user_id)

    # Формируем текст сообщения
    text = (
        "👤 **Личный кабинет**\n\n"
        f"{test_line}\n"
        f"📅 Всего сессий: (в разработке)\n"
        f"💰 Баланс: {balance} сообщ.\n\n"
        "Выберите действие:"
    )

    await message.answer(text, parse_mode="Markdown", reply_markup=get_profile_keyboard())


# -------------------------------------------------------------------
# ОБРАБОТЧИКИ ИНЛАЙН-КНОПОК ЛИЧНОГО КАБИНЕТА
# -------------------------------------------------------------------
@router.callback_query(F.data == "profile_tests")
async def profile_tests(callback: types.CallbackQuery):
    """Показывает историю пройденных тестов Бека."""
    user_id = callback.from_user.id

    try:
        results = await get_user_bdi_results(user_id, limit=5)
    except Exception as e:
        logger.warning(f"Не удалось получить историю тестов для {user_id}: {e}")
        results = []

    if not results:
        text = "📜 **История тестов**\n\nПока вы не прошли ни одного теста."
    else:
        lines = ["📜 **Последние результаты теста Бека:**\n"]
        for r in results:
            date_str = r['date'][:10] if 'date' in r else 'неизвестно'
            score = r.get('score', '?')
            interpretation = r.get('interpretation', '')
            lines.append(f"{date_str}: {score} баллов – {interpretation}")
        text = "\n".join(lines)

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_tests_keyboard())
    await callback.answer()


@router.callback_query(F.data == "profile_start_test")
async def profile_start_test(callback: types.CallbackQuery):
    """Заглушка для запуска теста Бека."""
    await callback.answer("📋 Функция прохождения теста появится в ближайшее время.", show_alert=True)


@router.callback_query(F.data == "profile_back_from_tests")
async def profile_back_from_tests(callback: types.CallbackQuery):
    """
    Возвращает из истории тестов обратно в главное меню личного кабинета.
    """
    user_id = callback.from_user.id
    info = await get_user_info(user_id)

    if not info:
        await callback.answer("Профиль не найден.", show_alert=True)
        return

    try:
        test_results = await get_user_bdi_results(user_id, limit=1)
    except Exception: # noqa
        test_results = []

    if test_results:
        last_test = test_results[0]
        test_line = f"📋 Тест Бека: {last_test['score']} баллов ({last_test['interpretation']})"
    else:
        test_line = "📋 Тест Бека: не пройден"

    balance = await get_balance(user_id)

    text = (
        "👤 **Личный кабинет**\n\n"
        f"{test_line}\n"
        f"📅 Всего сессий: (в разработке)\n"
        f"💰 Баланс: {balance} сообщ.\n\n"
        "Выберите действие:"
    )

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_profile_keyboard())
    await callback.answer()


@router.callback_query(F.data == "profile_invite")
async def profile_invite(callback: types.CallbackQuery):
    """Заглушка для приглашения друга."""
    await callback.answer("🎁 Функция приглашения друга появится позже.", show_alert=True)


@router.callback_query(F.data == "profile_purchases")
async def profile_purchases(callback: types.CallbackQuery):
    """Заглушка для раздела покупок (теперь называется "Купить")."""
    await callback.answer("🛒 Возможность покупки сообщений появится в будущем.", show_alert=True)


@router.callback_query(F.data == "profile_back_to_main")
async def profile_back_to_main(callback: types.CallbackQuery):
    """
    Возвращает пользователя в главное меню (Reply-клавиатура).
    Удаляет сообщение личного кабинета и отправляет клавиатуру главного меню.
    """
    await callback.message.delete()
    await callback.message.answer(
        "↩️ Возврат в главное меню.",
        reply_markup=get_main_menu(callback.from_user.id)
    )
    await callback.answer()
