# handlers/profile_handlers.py
# Личный кабинет пользователя: статистика, история тестов, остаток сообщений, информация о подписке.
# Все данные берутся из базы данных через функции get_user_info и get_user_bdi_results.

import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from keyboards import get_main_menu
from database import get_user_info, get_user_bdi_results

logger = logging.getLogger(__name__)
router = Router()


def get_profile_keyboard() -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура для навигации внутри личного кабинета.
    Кнопки:
      - Моя статистика
      - История тестов
      - Подписка
      - Главное меню (возврат)
    """
    buttons = [
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="profile_stats")],
        [InlineKeyboardButton(text="📜 История тестов", callback_data="profile_tests")],
        [InlineKeyboardButton(text="💎 Подписка", callback_data="profile_subscription")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="profile_back_to_main")]
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

    # Формируем текст сообщения
    text = (
        "👤 **Личный кабинет**\n\n"
        f"{test_line}\n"
        f"📅 Всего сессий: (в разработке)\n"
        f"💬 Сообщений: {info['messages_today']}/{info['limit']} (осталось {info['remaining']})\n\n"
        "Выберите действие:"
    )

    await message.answer(text, parse_mode="Markdown", reply_markup=get_profile_keyboard())


# -------------------------------------------------------------------
# ОБРАБОТЧИКИ ИНЛАЙН-КНОПОК ЛИЧНОГО КАБИНЕТА
# -------------------------------------------------------------------
@router.callback_query(F.data == "profile_stats")
async def profile_stats(callback: types.CallbackQuery):
    """Показывает подробную статистику пользователя."""
    user_id = callback.from_user.id
    info = await get_user_info(user_id)

    if not info:
        await callback.answer("Профиль не найден.", show_alert=True)
        return

    # Здесь можно добавить расчёт дней с регистрации, средней активности и т.д.
    text = (
        "📊 **Ваша статистика**\n\n"
        f"📅 Дней с регистрации: (скоро)\n"
        f"💬 Всего сообщений: {info['total_messages']}\n"
        f"📈 Средняя активность: (скоро)\n\n"
        f"Сегодня: {info['messages_today']}/{info['limit']}\n"
        f"Осталось бесплатных: {info['remaining']}"
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_profile_keyboard())
    await callback.answer()


@router.callback_query(F.data == "profile_tests")
async def profile_tests(callback: types.CallbackQuery):
    """Показывает историю пройденных тестов Бека."""
    user_id = callback.from_user.id

    # Пытаемся получить реальные данные; если функция не реализована – пустой список
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

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_profile_keyboard())
    await callback.answer()


@router.callback_query(F.data == "profile_subscription")
async def profile_subscription(callback: types.CallbackQuery):
    """Информация о подписке (заглушка на будущее)."""
    text = (
        "💎 **Подписка**\n\n"
        "Premium-подписка снимает все лимиты и даёт дополнительные возможности.\n"
        "Оформить можно будет в ближайшее время."
    )
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_profile_keyboard())
    await callback.answer()


@router.callback_query(F.data == "profile_back_to_main")
async def profile_back_to_main(callback: types.CallbackQuery):
    """
    Возвращает пользователя в главное меню.
    Удаляет сообщение личного кабинета и отправляет Reply-клавиатуру главного меню.
    """
    await callback.message.delete()
    await callback.message.answer(
        "↩️ Возврат в главное меню.",
        reply_markup=get_main_menu(callback.from_user.id)
    )
    await callback.answer()
