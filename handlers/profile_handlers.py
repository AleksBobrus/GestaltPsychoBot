# handlers/profile_handlers.py
# Личный кабинет пользователя: баланс сообщений, история тестов, приглашение друга, покупки.
# Добавлен подсчёт сессий.

import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from keyboards import get_main_menu
from database import (
    get_user_info, get_user_bdi_results, get_balance,
    get_referral_count, get_total_sessions
)

logger = logging.getLogger(__name__)
router = Router()


def get_profile_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📜 История тестов", callback_data="profile_tests")],
        [InlineKeyboardButton(text="🎁 Пригласить друга", callback_data="profile_invite")],
        [InlineKeyboardButton(text="🛒 Купить", callback_data="profile_purchases")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="profile_back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_tests_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📋 Пройти тест", callback_data="profile_start_test")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="profile_back_from_tests")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(F.text == "👤 Личный кабинет")
async def profile_main(message: types.Message, state: FSMContext):
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

    balance = await get_balance(user_id)
    total_sessions = await get_total_sessions(user_id)

    text = (
        "👤 **Личный кабинет**\n\n"
        f"{test_line}\n"
        f"📅 Всего сессий: {total_sessions}\n"
        f"💰 Баланс: {balance} сообщ.\n\n"
        "Выберите действие:"
    )

    await message.answer(text, parse_mode="Markdown", reply_markup=get_profile_keyboard())


@router.callback_query(F.data == "profile_tests")
async def profile_tests(callback: types.CallbackQuery):
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
    await callback.answer("📋 Функция прохождения теста появится в ближайшее время.", show_alert=True)


@router.callback_query(F.data == "profile_back_from_tests")
async def profile_back_from_tests(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    info = await get_user_info(user_id)

    if not info:
        await callback.answer("Профиль не найден.", show_alert=True)
        return

    try:
        test_results = await get_user_bdi_results(user_id, limit=1)
    except Exception:
        test_results = []

    if test_results:
        last_test = test_results[0]
        test_line = f"📋 Тест Бека: {last_test['score']} баллов ({last_test['interpretation']})"
    else:
        test_line = "📋 Тест Бека: не пройден"

    balance = await get_balance(user_id)
    total_sessions = await get_total_sessions(user_id)

    text = (
        "👤 **Личный кабинет**\n\n"
        f"{test_line}\n"
        f"📅 Всего сессий: {total_sessions}\n"
        f"💰 Баланс: {balance} сообщ.\n\n"
        "Выберите действие:"
    )

    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_profile_keyboard())
    await callback.answer()


@router.callback_query(F.data == "profile_invite")
async def profile_invite(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    bot_username = (await callback.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref{user_id}"
    count = await get_referral_count(user_id)

    text = (
        "🎁 **Пригласи друга**\n\n"
        f"Ваша персональная ссылка:\n`{ref_link}`\n\n"
        f"👥 Приглашено: {count}\n\n"
        "🎉 **Бонусы:**\n"
        "• Друг получит **100 сообщений**\n"
        "• Вы получите **100 сообщений** за каждого друга\n\n"
        "Отправьте ссылку другу, и бонусы начислятся автоматически после его регистрации."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Скопировать ссылку", copy_text=ref_link)],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="profile_back_from_tests")]
    ])
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data == "profile_purchases")
async def profile_purchases(callback: types.CallbackQuery):
    await callback.answer("🛒 Возможность покупки сообщений появится в будущем.", show_alert=True)


@router.callback_query(F.data == "profile_back_to_main")
async def profile_back_to_main(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        "↩️ Возврат в главное меню.",
        reply_markup=get_main_menu(callback.from_user.id)
    )
    await callback.answer()
