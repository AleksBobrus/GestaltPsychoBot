# handlers/payments.py
# Модуль оплаты через Telegram Stars (XTR). Позволяет пользователям покупать дни подписки.
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import activate_subscription

logger = logging.getLogger(__name__)
router = Router()

# Конфигурация тарифов: кол-во дней → цена в Stars
SUBSCRIPTION_TIERS = {
    5: 25,    # 50 руб.
    10: 50,   # 100 руб.
    20: 100,  # 200 руб.
    30: 150   # 300 руб.
}

def get_payment_keyboard(amount: int) -> types.InlineKeyboardMarkup:
    """Создаёт клавиатуру с кнопкой оплаты через Telegram Stars."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Оплатить {amount} ⭐️", pay=True)
    return builder.as_markup()

# -------------------------------------------------------------------
# КОМАНДА /stars – показывает доступные тарифы
# -------------------------------------------------------------------
@router.message(Command("stars"))
async def cmd_stars(message: types.Message):
    """Выводит список тарифов с ценами в Stars."""
    text = "💎 **Продление подписки через Stars**\n\n📋 **Доступные тарифы:**\n"
    for days, price in SUBSCRIPTION_TIERS.items():
        text += f"• {days} дней — {price} ⭐️\n"
    text += "\nДля оплаты отправьте `/buy N`, где N — количество дней.\n"
    text += "Например: `/buy 5` – купить 5 дней за 25 ⭐️."

    await message.answer(text, parse_mode="Markdown")

# -------------------------------------------------------------------
# КОМАНДА /buy – создание счёта на оплату
# -------------------------------------------------------------------
@router.message(Command("buy"))
async def cmd_buy(message: types.Message):
    """Создаёт счёт (invoice) на оплату выбранного тарифа."""
    try:
        days = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer(
            "⚠️ Укажите количество дней после команды.\n"
            "Например: `/buy 5`, `/buy 10`, `/buy 20`, `/buy 30`."
        )
        return

    price = SUBSCRIPTION_TIERS.get(days)
    if not price:
        available = ", ".join(map(str, SUBSCRIPTION_TIERS.keys()))
        await message.answer(
            f"⚠️ Тарифа на {days} дней нет.\n"
            f"Доступны: {available} дней.\n"
            f"Посмотрите все тарифы: /stars"
        )
        return

    user_id = message.from_user.id
    prices = [LabeledPrice(label="XTR", amount=price)]
    await message.answer_invoice(
        title="Продление подписки AI-психолог",
        description=f"Premium-доступ на {days} дней",
        payload=f"sub_{user_id}_{days}",
        provider_token="",   # для Stars всегда пусто
        currency="XTR",
        prices=prices,
        reply_markup=get_payment_keyboard(price),
    )

# -------------------------------------------------------------------
# КОМАНДА /paysupport – обязательная команда поддержки платежей
# -------------------------------------------------------------------
@router.message(Command("paysupport"))
async def cmd_paysupport(message: types.Message):
    """Требование Telegram: у бота, принимающего платежи, должна быть команда /paysupport."""
    await message.answer(
        "🛟 **Поддержка по вопросам оплаты**\n\n"
        "Если у вас возникли проблемы с оплатой, напишите администратору: @your_support_username.\n"
        "Для возврата средств используйте команду /refund (в разработке)."
    )

# -------------------------------------------------------------------
# КОМАНДА /refund – возврат средств (заглушка)
# -------------------------------------------------------------------
@router.message(Command("refund"))
async def cmd_refund(message: types.Message):
    """Возврат последнего платежа пользователя. Пока в разработке."""
    await message.answer(
        "ℹ️ Функция возврата находится в разработке.\n"
        "Пожалуйста, обратитесь к администратору: @your_support_username."
    )

# -------------------------------------------------------------------
# PRE-CHECKOUT – обязательный обработчик перед оплатой
# -------------------------------------------------------------------
@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    """Telegram присылает pre_checkout_query перед открытием окна оплаты. Отвечаем ok=True."""
    await pre_checkout_query.answer(ok=True)

# -------------------------------------------------------------------
# SUCCESSFUL PAYMENT – обработка успешной оплаты
# -------------------------------------------------------------------
@router.message(F.successful_payment)
async def process_successful_payment(message: Message):
    """Вызывается, когда пользователь успешно оплатил счёт. Активирует подписку."""
    user_id = message.from_user.id
    payment = message.successful_payment
    payload = payment.invoice_payload  # формат: sub_<user_id>_<days>

    try:
        days = int(payload.split("_")[-1])
    except (ValueError, IndexError):
        logger.error(f"Не удалось извлечь дни из payload: {payload}")
        await message.answer("❌ Ошибка обработки платежа. Пожалуйста, свяжитесь с администратором.")
        return

    await activate_subscription(user_id, days)
    logger.info(f"Пользователь {user_id} оплатил {days} дней подписки через Stars")

    await message.answer(
        f"✅ Оплата прошла успешно!\n"
        f"🎉 Ваша подписка продлена на **{days}** дней.\n"
        f"Спасибо за поддержку!",
        parse_mode="Markdown",
    )
