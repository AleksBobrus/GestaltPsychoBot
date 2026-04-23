# bot.py
# Главный файл запуска Telegram-бота «AI-психолог».
# Версия 4.0.0 – переход на модель подписки по времени (Premium).

import asyncio
import os
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardRemove
from keyboards import get_main_menu
from handlers.dialog_handlers import register_dialog_handlers
from handlers.profile_handlers import router as profile_router
from handlers.admin import router as admin_router
from database import (
    init_db, save_user_profile,
    activate_subscription, is_premium_active, get_subscription_days_left,
    add_referral, has_pending_referral_bonus, mark_referral_bonus_given, get_inviter_id,
    get_total_users_count   # для уведомлений о юбилейных регистрациях
)

# -------------------------------------------------------------------
# НАСТРОЙКА ЛОГИРОВАНИЯ (КОНСОЛЬ + ФАЙЛ)
# -------------------------------------------------------------------
logger = logging.getLogger()
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = logging.FileHandler("bot_public.log", encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# ЗАГРУЗКА КОНФИГУРАЦИИ
# -------------------------------------------------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в файле .env!")

# -------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ БОТА И ДИСПЕТЧЕРА
# -------------------------------------------------------------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# -------------------------------------------------------------------
# ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК
# -------------------------------------------------------------------
@dp.errors()
async def errors_handler(_: types.Update, exception: Exception):
    logger.exception("Критическая ошибка при обработке обновления", exc_info=exception)
    return True


# -------------------------------------------------------------------
# FSM ДЛЯ ЗАПРОСА ИМЕНИ
# -------------------------------------------------------------------
class NameState(StatesGroup):
    waiting_for_name = State()


# -------------------------------------------------------------------
# ЕДИНАЯ ФУНКЦИЯ СПРАВКИ (ОБНОВЛЕНО ДЛЯ ПОДПИСКИ)
# -------------------------------------------------------------------
def get_help_text() -> str:
    """Возвращает текст с информацией о боте (версия 4.0.0)."""
    return (
        "🤖 **• AI-психолог •**\n"
        "Версия: **4.0.0**\n\n"
        "AI-психолог — это виртуальный помощник для поддержки ментального благополучия. "
        "Бот использует технологии искусственного интеллекта, чтобы выслушать, "
        "помочь разобраться в чувствах и предложить полезные техники.\n\n"
        "✨ **Актуальные возможности:**\n"
        "• 💬 **Начать сессию** — беседа с ИИ-психологом (требуется Premium)\n"
        "• 👤 **Личный кабинет** — статус подписки, история тестов\n"
        "• 🎁 **Пригласи друга** — получайте +10 дней Premium за каждого друга\n"
        "• 🧠 **Контекст диалога** — запоминание предыдущих бесед\n"
        "• 🆘 **Кризис-детектор** — распознавание тревожных фраз\n\n"
        "🚧 **В планах:**\n"
        "• 📋 Тест на уровень депрессии (шкала Бека)\n"
        "• 🛒 Покупка Premium\n\n"
        "⚠️ **Важно:** бот не заменяет профессионального психолога. "
        "При серьёзных проблемах необходимо обратиться к специалисту."
    )


# -------------------------------------------------------------------
# ОБРАБОТЧИК КОМАНДЫ /start (СОХРАНЕНИЕ РЕФЕРАЛЬНОЙ СВЯЗИ)
# -------------------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, command: CommandObject):
    """
    При первом запуске:
      - Сохраняет базовый профиль (без имени).
      - Если передан реферальный параметр ?start=ref123456, сохраняет связь.
      - Запрашивает имя.
    """
    await state.clear()

    user_id = message.from_user.id
    telegram_name = message.from_user.full_name or message.from_user.first_name or "Без имени"
    username = message.from_user.username

    # Сохраняем профиль в таблицу users (пока без custom_name)
    await save_user_profile(user_id, telegram_name, None, username)

    # Обработка реферальной ссылки (только сохранение связи)
    args = command.args
    if args and args.startswith("ref"):
        try:
            inviter_id = int(args[3:])
            if inviter_id != user_id:
                added = await add_referral(inviter_id, user_id)
                if added:
                    logger.info(f"Пользователь {user_id} приглашён пользователем {inviter_id}")
        except ValueError:
            pass

    # Запрашиваем имя
    await state.set_state(NameState.waiting_for_name)
    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "Как я могу к вам обращаться? Напишите ваше имя.",
        reply_markup=ReplyKeyboardRemove()
    )


# -------------------------------------------------------------------
# ОБРАБОТЧИК ВВОДА ИМЕНИ (АКТИВАЦИЯ ПОДПИСКИ И РЕФЕРАЛЬНЫХ БОНУСОВ)
# -------------------------------------------------------------------
@dp.message(NameState.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    """
    После ввода имени:
      - Обновляет custom_name.
      - Активирует пробный период (5 дней) или реферальный бонус (10 дней).
      - Начисляет реферальный бонус пригласившему (10 дней).
      - Отправляет уведомление администраторам о юбилейных регистрациях.
    """
    user_name = message.text.strip()
    if len(user_name) > 50:
        await message.answer("⚠️ Имя слишком длинное. Пожалуйста, введите покороче.")
        return

    await state.update_data(user_name=user_name)

    # Обновляем профиль (добавляем custom_name)
    telegram_name = message.from_user.full_name or message.from_user.first_name or "Без имени"
    username = message.from_user.username
    await save_user_profile(message.from_user.id, telegram_name, user_name, username)

    user_id = message.from_user.id

    # --- АКТИВАЦИЯ ПРОБНОГО ПЕРИОДА ИЛИ РЕФЕРАЛЬНОГО БОНУСА ---
    inviter_id = await get_inviter_id(user_id)
    if inviter_id is not None:
        # Пользователь пришёл по реферальной ссылке – даём 10 дней (пробные 5 не даём)
        await activate_subscription(user_id, 10)
        logger.info(f"10 дней Premium начислено приглашённому пользователю {user_id}")
    else:
        # Обычная регистрация – пробные 5 дней, если подписка ещё не активна
        if not await is_premium_active(user_id):
            await activate_subscription(user_id, 5)
            logger.info(f"Пробные 5 дней Premium активированы для пользователя {user_id}")

    # --- РЕФЕРАЛЬНЫЙ БОНУС ДЛЯ ПРИГЛАСИВШЕГО (10 дней) ---
    if await has_pending_referral_bonus(user_id):
        inviter_id = await get_inviter_id(user_id)
        if inviter_id:
            await activate_subscription(inviter_id, 10)
            await mark_referral_bonus_given(user_id)
            logger.info(f"Бонусные 10 дней Premium начислены пригласившему {inviter_id} за {user_id}")

    # --- УВЕДОМЛЕНИЕ АДМИНИСТРАТОРАМ О ЮБИЛЕЙНЫХ РЕГИСТРАЦИЯХ ---
    total_users = await get_total_users_count()
    notify = False
    if 1 <= total_users <= 5:
        notify = True
    elif total_users >= 10 and total_users % 10 == 0:
        notify = True

    if notify:
        admin_ids_str = os.getenv("ADMIN_IDS", "")
        if admin_ids_str:
            admin_ids = [int(uid.strip()) for uid in admin_ids_str.split(",") if uid.strip()]
            user_mention = f"@{username}" if username else user_name
            message_text = (
                f"🎉 Новый пользователь!\n"
                f"Порядковый номер: {total_users}\n"
                f"ID: {user_id}\n"
                f"Имя: {user_name}\n"
                f"Username: {user_mention}"
            )
            for admin_id in admin_ids:
                try:
                    await bot.send_message(admin_id, message_text)
                except Exception as e:
                    logger.warning(f"Не удалось отправить уведомление админу {admin_id}: {e}")

    await state.clear()

    await message.answer(
        f"👋 Приятно познакомиться, {user_name}!\n\n"
        f"⚠️ **Важно:**\n"
        f"• Я не заменяю профессионального психолога\n"
        f"• При серьёзных проблемах обратитесь к специалисту\n\n"
        f"💬 Выберите действие на клавиатуре ниже 👇",
        parse_mode="Markdown",
        reply_markup=get_main_menu(message.from_user.id)
    )


# -------------------------------------------------------------------
# ОСТАЛЬНЫЕ ОБРАБОТЧИКИ
# -------------------------------------------------------------------
@dp.message(Command("help"))
async def cmd_help(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(get_help_text(), parse_mode="Markdown", reply_markup=get_main_menu(message.from_user.id))


@dp.message(F.text == "ℹ️ О боте")
async def about_bot(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(get_help_text(), parse_mode="Markdown", reply_markup=get_main_menu(message.from_user.id))


@dp.message(F.text == "📋 Пройти тест")
async def placeholder_test(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 Тест на уровень депрессии будет доступен в следующей версии.",
                         reply_markup=get_main_menu(message.from_user.id))


# -------------------------------------------------------------------
# ПОДКЛЮЧЕНИЕ МОДУЛЕЙ
# -------------------------------------------------------------------
register_dialog_handlers(dp)
dp.include_router(profile_router)
dp.include_router(admin_router)


# -------------------------------------------------------------------
# ЗАПУСК БОТА
# -------------------------------------------------------------------
async def main():
    await init_db()
    logger.info("База данных инициализирована")
    logger.info("=" * 55)
    logger.info("        🤖 AI-ПСИХОЛОГ v4.0.0 (Premium-подписка)")
    logger.info("=" * 55)
    logger.info("📡 СТАТУС СИСТЕМЫ:")
    logger.info("  ✅ Бот успешно запущен")
    logger.info("  ✅ DeepSeek API подключен")
    logger.info("  ✅ База данных SQLite (aiosqlite) инициализирована")
    logger.info("  ✅ Логирование в файл bot_public.log настроено")
    logger.info("🎯 АКТИВНЫЕ ФУНКЦИИ:")
    logger.info("  💬 Начать сессию — диалог с ИИ (требуется Premium)")
    logger.info("  👤 Личный кабинет — статус подписки, история тестов")
    logger.info("  🎁 Реферальная система (+10 дней Premium за друга)")
    logger.info("  🧠 Контекст и суммаризация")
    logger.info("  🆘 Кризис-детектор")
    logger.info("  ℹ️  Информация о боте")
    logger.info("  🔧 Админ-панель (управление пользователями, рассылка)")
    logger.info("🚧 В РАЗРАБОТКЕ:")
    logger.info("  📋 Тест на депрессию (шкала Бека)")
    logger.info("  🛒 Покупка Premium")
    logger.info("=" * 55)
    logger.info("⏳ Ожидание входящих сообщений...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
