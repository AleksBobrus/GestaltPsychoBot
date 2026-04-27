# handlers/profile_handlers.py
# Личный кабинет пользователя: статус подписки, история тестов (тест Бернса),
# приглашение друга, продление подписки через Telegram Stars.
# Версия 4.1.1 – активирована оплата Stars, удалены старые заглушки.

import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    CopyTextButton
)
from keyboards import get_main_menu
from database import (
    get_user_info,
    get_user_depression_results,
    get_referral_count,
    get_subscription_days_left
)
# Импорт функций и данных модуля оплаты Stars
from handlers.payments import SUBSCRIPTION_TIERS, create_stars_invoice

logger = logging.getLogger(__name__)
router = Router()


def get_profile_keyboard() -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура для главного экрана личного кабинета.
    """
    buttons = [
        [InlineKeyboardButton(text="📜 История тестов", callback_data="profile_tests")],
        [InlineKeyboardButton(text="💌 Пригласить друга", callback_data="profile_invite")],
        [InlineKeyboardButton(text="🔄 Продлить подписку", callback_data="profile_renew_subscription")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="profile_back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_tests_keyboard() -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура для раздела истории тестов.
    Кнопка «Пройти тест» удалена – теперь только «Назад».
    """
    buttons = [
        [InlineKeyboardButton(text="🔙 Назад", callback_data="profile_back_from_tests")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# -------------------------------------------------------------------
# ТОЧКА ВХОДА: КНОПКА «🏠 ЛИЧНЫЙ КАБИНЕТ»
# -------------------------------------------------------------------
@router.message(F.text == "🏠 Личный кабинет")
async def profile_main(message: types.Message, state: FSMContext):
    """
    Открывает главное меню личного кабинета.
    Отображает статус подписки и оставшиеся дни, а также последний результат теста Бернса.
    """
    await state.clear()
    user_id = message.from_user.id

    info = await get_user_info(user_id)
    if not info or info.get('created_at') is None:
        await message.answer(
            "⚠️ Ваш профиль ещё не заполнен. Пожалуйста, нажмите /start и введите ваше имя.",
            reply_markup=get_main_menu(user_id)
        )
        return

    # Получаем последний результат теста Бернса
    try:
        test_results = await get_user_depression_results(user_id, limit=1)
    except Exception as e:
        logger.warning(f"Ошибка получения тестов для {user_id}: {e}")
        test_results = []

    if test_results:
        last_test = test_results[0]
        test_line = f"📋 Тест Бернса: {last_test['score']} баллов ({last_test['interpretation']})"
    else:
        test_line = "📋 Тест Бернса: не пройден"

    # Получаем статус подписки
    days_left = await get_subscription_days_left(user_id)
    if days_left is not None:
        sub_text = f"✅ Активна (осталось {days_left} дн.)"
    else:
        sub_text = "❌ Не активна"

    # Текст без разделителей и изображений
    text = (
        "🏠 **Личный кабинет**\n\n"
        f"{test_line}\n\n"
        f"⏳ *Подписка:* {sub_text}\n\n"
        "Выберите действие:"
    )

    await message.answer(text, parse_mode="Markdown", reply_markup=get_profile_keyboard())


# -------------------------------------------------------------------
# ОБРАБОТЧИКИ ИНЛАЙН-КНОПОК ЛИЧНОГО КАБИНЕТА
# -------------------------------------------------------------------
@router.callback_query(F.data == "profile_tests")
async def profile_tests(callback: types.CallbackQuery):
    """Показывает историю пройденных тестов Бернса (с защитой от пустого текста)."""
    user_id = callback.from_user.id

    try:
        results = await get_user_depression_results(user_id, limit=5)
    except Exception as e:
        logger.warning(f"Не удалось получить историю тестов для {user_id}: {e}")
        results = []

    if not results:
        text = "📜 **История тестов**\n\nПока вы не прошли ни одного теста."
    else:
        lines = ["📜 **История тестов**\n"]
        for r in results:
            date_str = r['date'][:10] if 'date' in r else 'неизвестно'
            score = r.get('score', '?')
            interpretation = r.get('interpretation', '')
            lines.append(f"📅 {date_str}: *{score} баллов* – {interpretation}")
        text = "\n".join(lines)

    # Гарантируем, что text не пустой
    if not text or not text.strip():
        text = "📜 **История тестов**\n\nНет данных для отображения."

    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_tests_keyboard())
    except Exception: # noqa
        # fallback без Markdown
        await callback.message.edit_text(text, reply_markup=get_tests_keyboard())

    await callback.answer()


@router.callback_query(F.data == "profile_back_from_tests")
async def profile_back_from_tests(callback: types.CallbackQuery):
    """Возвращает из истории тестов в главное меню личного кабинета."""
    user_id = callback.from_user.id
    info = await get_user_info(user_id)

    if not info:
        await callback.answer("Профиль не найден.", show_alert=True)
        return

    try:
        test_results = await get_user_depression_results(user_id, limit=1)
    except Exception:   # noqa
        test_results = []

    if test_results:
        last_test = test_results[0]
        test_line = f"📋 Тест Бернса: {last_test['score']} баллов ({last_test['interpretation']})"
    else:
        test_line = "📋 Тест Бернса: не пройден"

    days_left = await get_subscription_days_left(user_id)
    if days_left is not None:
        sub_text = f"✅ Активна (осталось {days_left} дн.)"
    else:
        sub_text = "❌ Не активна"

    # Текст без разделителей и изображений
    text = (
        "🏠 **Личный кабинет**\n\n"
        f"{test_line}\n\n"
        f"⏳ *Подписка:* {sub_text}\n\n"
        "Выберите действие:"
    )

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_profile_keyboard())
    await callback.answer()


# -------------------------------------------------------------------
# КНОПКА «ПРИГЛАСИТЬ ДРУГА»
# -------------------------------------------------------------------
@router.callback_query(F.data == "profile_invite")
async def profile_invite(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    bot_username = (await callback.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref{user_id}"
    count = await get_referral_count(user_id)

    # Текст без разделителей
    text = (
        "💌 **Пригласи друга**\n\n"
        f"🔗 *Ваша персональная ссылка:*\n`{ref_link}`\n\n"
        f"👥 Приглашено: *{count}*\n\n"
        "🎉 **Бонусы:**\n"
        "▫️ Друг получит **10 дней подписки**\n"
        "▫️ Вы получите **10 дней подписки** за каждого друга\n\n"
        "_Отправьте ссылку другу, и бонусы начислятся автоматически после его регистрации._"
    )
    copy_button = InlineKeyboardButton(
        text="📋 Скопировать ссылку",
        copy_text=CopyTextButton(text=ref_link)
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [copy_button],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="profile_back_from_tests")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    await callback.answer()


# -------------------------------------------------------------------
# ПРОДЛЕНИЕ ПОДПИСКИ (ОПЛАТА STARS)
# -------------------------------------------------------------------
@router.callback_query(F.data == "profile_renew_subscription")
async def profile_renew_subscription(callback: types.CallbackQuery):
    """Показывает тарифы для продления подписки через Stars."""
    await callback.answer()

    text = (
        "🔄 **Продление подписки**\n\n"
        "📋 *Тариф (оплата звёздами):*\n"
        "Выберите тариф, чтобы сразу получить счёт:"
    )

    # Оставлена только кнопка 30 дней
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="30 дней – 150 ⭐️", callback_data="buy_stars:30")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="profile_back_from_tests")]
    ])

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)


@router.callback_query(F.data.startswith("buy_stars:"))
async def buy_stars_handler(callback: types.CallbackQuery):
    """Обрабатывает нажатие на кнопку тарифа и выставляет счёт."""
    days = int(callback.data.split(":")[1])
    price = SUBSCRIPTION_TIERS.get(days, 0)
    if price == 0:
        await callback.answer("❌ Неверный тариф.", show_alert=True)
        return

    # Передаём экземпляр бота (callback.bot) в функцию создания счёта
    success = await create_stars_invoice(callback.from_user.id, days, price, callback.bot)
    if success:
        await callback.answer("Счёт отправлен. Проверьте сообщение ниже.", show_alert=True)
    else:
        await callback.answer("❌ Не удалось создать счёт. Попробуйте позже.", show_alert=True)


# -------------------------------------------------------------------
# ВОЗВРАТ В ГЛАВНОЕ МЕНЮ
# -------------------------------------------------------------------
@router.callback_query(F.data == "profile_back_to_main")
async def profile_back_to_main(callback: types.CallbackQuery):
    await callback.message.delete()
    # Отправляем сообщение с клавиатурой главного меню
    await callback.message.answer(
        "...",  # минимальный текст, чтобы Telegram не выдавал ошибку
        reply_markup=get_main_menu(callback.from_user.id)
    )
    await callback.answer()
