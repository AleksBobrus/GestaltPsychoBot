# handlers/profile_handlers.py
# Личный кабинет пользователя: статус Premium-подписки, история тестов, приглашение друга, покупка.
# Версия 4.0.0 – отображение дней подписки вместо баланса сообщений.

import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from keyboards import get_main_menu
from database import (
    get_user_info, get_user_bdi_results,
    get_referral_count, get_subscription_days_left
)

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
    """
    buttons = [
        [InlineKeyboardButton(text="📋 Пройти тест", callback_data="profile_start_test")],
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
    Отображает статус Premium-подписки и оставшиеся дни.
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

    # Получаем статус Premium-подписки
    days_left = await get_subscription_days_left(user_id)
    if days_left is not None:
        sub_text = f"✅ Активна (осталось {days_left} дн.)"
    else:
        sub_text = "❌ Не активна"

    text = (
        "🏠 **Личный кабинет**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{test_line}\n\n"
        f"⏳ *Подписка:* {sub_text}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
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
        text = (
            "📜 **История тестов**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Пока вы не прошли ни одного теста."
        )
    else:
        lines = [
            "📜 **История тестов**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
        ]
        for r in results:
            date_str = r['date'][:10] if 'date' in r else 'неизвестно'
            score = r.get('score', '?')
            interpretation = r.get('interpretation', '')
            lines.append(f"📅 {date_str}: *{score} баллов* – {interpretation}")
        text = "\n".join(lines)

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_tests_keyboard())
    await callback.answer()


@router.callback_query(F.data == "profile_start_test")
async def profile_start_test(callback: types.CallbackQuery):
    """Заглушка для запуска теста Бека."""
    await callback.answer("📋 Функция прохождения теста появится в ближайшее время.", show_alert=True)


@router.callback_query(F.data == "profile_back_from_tests")
async def profile_back_from_tests(callback: types.CallbackQuery):
    """Возвращает из истории тестов в главное меню личного кабинета."""
    user_id = callback.from_user.id
    info = await get_user_info(user_id)

    if not info:
        await callback.answer("Профиль не найден.", show_alert=True)
        return

    try:
        test_results = await get_user_bdi_results(user_id, limit=1)
    except Exception:   # noqa
        test_results = []

    if test_results:
        last_test = test_results[0]
        test_line = f"📋 Тест Бека: {last_test['score']} баллов ({last_test['interpretation']})"
    else:
        test_line = "📋 Тест Бека: не пройден"

    days_left = await get_subscription_days_left(user_id)
    if days_left is not None:
        sub_text = f"✅ Активна (осталось {days_left} дн.)"
    else:
        sub_text = "❌ Не активна"

    text = (
        "🏠 **Личный кабинет**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{test_line}\n\n"
        f"⏳ *Подписка:* {sub_text}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
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

    text = (
        "💌 **Пригласи друга**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
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
# ПРОДЛЕНИЕ ПОДПИСКИ
# -------------------------------------------------------------------
@router.callback_query(F.data == "profile_renew_subscription")
async def profile_renew_subscription(callback: types.CallbackQuery):
    await callback.answer()

    text = (
        "🔄 **Продление подписки**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📋 *Тарифы:*\n"
        "• 5 дней – 50 ⭐️ (≈100₽)\n"
        "• 10 дней – 100 ⭐️ (≈200₽)\n"
        "• 20 дней – 200 ⭐️ (≈400₽)\n"
        "• 30 дней – 300 ⭐️ (≈600₽)\n\n"
        "⚠️ *Раздел находится в разработке.*\n"
        "Оплата станет доступна в ближайшее время.\n\n"
        "Выберите способ оплаты:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️ Оплатить звёздами", callback_data="pay_stars")],
        [InlineKeyboardButton(text="💳 Оплатить картой", callback_data="pay_card")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="profile_back_from_tests")]
    ])

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)


# Заглушки для кнопок оплаты (пока раздел в разработке)
@router.callback_query(F.data == "pay_stars")
async def pay_stars_stub(callback: types.CallbackQuery):
    await callback.answer("⭐️ Оплата звёздами появится позже.", show_alert=True)

@router.callback_query(F.data == "pay_card")
async def pay_card_stub(callback: types.CallbackQuery):
    await callback.answer("💳 Оплата картой появится позже.", show_alert=True)


@router.callback_query(F.data == "profile_back_to_main")
async def profile_back_to_main(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "↩️ Возврат в главное меню.",
        reply_markup=get_main_menu(callback.from_user.id)
    )
    await callback.answer()
