# bot.py
# Главный файл запуска Telegram-бота «AI-психолог».
# Версия 4.1.1 – подписка по времени + глобальный счётчик сообщений ИИ (тестовый режим).
# Тест на депрессию теперь по шкале Бернса (25 вопросов).

import asyncio
import os
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from keyboards import get_main_menu
from handlers.dialog_handlers import register_dialog_handlers
from handlers.profile_handlers import router as profile_router
from handlers.admin import router as admin_router
# Платёжный роутер пока не подключён, будет добавлен позже
# from handlers.payments import router as payments_router
from database import (
    init_db, save_user_profile,
    activate_subscription, is_premium_active,
    add_referral, has_pending_referral_bonus, mark_referral_bonus_given, get_inviter_id,
    get_total_users_count
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

# Пишем логи в файл для последующего анализа
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
# ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК (ПРИНИМАЕТ ДВА АРГУМЕНТА: update И exception)
# -------------------------------------------------------------------
@dp.errors()
async def errors_handler(_: types.Update, exception: Exception):
    """Ловит все необработанные исключения и логирует их."""
    logger.exception("Критическая ошибка при обработке обновления", exc_info=exception)
    return True


# -------------------------------------------------------------------
# ЕДИНАЯ ФУНКЦИЯ СПРАВКИ (обновлена: тест Бернса)
# -------------------------------------------------------------------
def get_help_text() -> str:
    return (
        "🤖 **• AI-психолог •**\n"
        "Версия: **4.1.1**\n\n"
        "*Виртуальный помощник для поддержки ментального благополучия на базе ИИ.*\n\n"
        "✨ **Что я умею:**\n"
        "💬 • *Начать сессию* — беседа с психологом (требуется подписка)\n"
        "🏠 • *Личный кабинет* — статус подписки, история тестов\n"
        "💌 • *Пригласи друга* — +10 дней подписки за каждого друга\n"
        "🧠 • *Контекст диалога* — помню предыдущие беседы\n"
        "🆘 • *Кризис-детектор* — распознаю тревожные фразы\n\n"
        "🚧 **В планах:**\n"
        "📋 • Тест на уровень депрессии (шкала Бернса)\n"
        "🛒 • Продление подписки\n\n"
        "⚠️ *Бот не заменяет профессионального психолога.*\n"
        "При серьёзных проблемах обратитесь к специалисту."
    )


# -------------------------------------------------------------------
# ОБРАБОТЧИК КОМАНДЫ /start (БЕЗ ЗАПРОСА ИМЕНИ, БЕЗ ИЗОБРАЖЕНИЙ И РАЗДЕЛИТЕЛЕЙ)
# -------------------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, command: CommandObject):
    """
    При старте:
      - Сохраняет профиль с именем из Telegram.
      - Обрабатывает реферальную ссылку.
      - Активирует пробный период (5 дн.) или реферальный бонус (10 дн.).
      - Начисляет бонус пригласившему (10 дн.).
      - Отправляет уведомление админам по гибкой схеме.
      - Показывает главное меню (чистый текст, без разделителей).
    """
    await state.clear()

    user_id = message.from_user.id
    telegram_name = message.from_user.full_name or message.from_user.first_name or "Без имени"
    username = message.from_user.username

    # Сохраняем профиль (без custom_name)
    await save_user_profile(user_id, telegram_name, None, username)

    # Обработка реферальной ссылки
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

    # --- АКТИВАЦИЯ ПРОБНОГО ПЕРИОДА ИЛИ РЕФЕРАЛЬНОГО БОНУСА ---
    inviter_id = await get_inviter_id(user_id)
    if inviter_id is not None:
        # Пришёл по реферальной ссылке – получает 10 дней
        await activate_subscription(user_id, 10)
        logger.info(f"10 дней подписки начислено приглашённому пользователю {user_id}")
    else:
        # Обычная регистрация – пробные 5 дней, если подписка ещё не активна
        if not await is_premium_active(user_id):
            await activate_subscription(user_id, 5)
            logger.info(f"Пробные 5 дней подписки активированы для пользователя {user_id}")

    # --- РЕФЕРАЛЬНЫЙ БОНУС ДЛЯ ПРИГЛАСИВШЕГО (10 дней) ---
    if await has_pending_referral_bonus(user_id):
        inviter_id = await get_inviter_id(user_id)
        if inviter_id:
            await activate_subscription(inviter_id, 10)
            await mark_referral_bonus_given(user_id)
            logger.info(f"Бонусные 10 дней подписки начислены пригласившему {inviter_id} за {user_id}")

    # --- УВЕДОМЛЕНИЕ АДМИНИСТРАТОРАМ (ГИБКАЯ СХЕМА) ---
    total_users = await get_total_users_count()

    notify = False
    if total_users <= 100:
        notify = True                     # каждый до 100
    elif total_users <= 500 and total_users % 5 == 0:
        notify = True                     # каждый 5-й до 500
    elif total_users % 10 == 0:
        notify = True                     # каждый 10-й после 500

    if notify:
        admin_ids_str = os.getenv("ADMIN_IDS", "")
        if admin_ids_str:
            admin_ids = [int(uid.strip()) for uid in admin_ids_str.split(",") if uid.strip()]
            user_mention = f"@{username}" if username else telegram_name

            if inviter_id is not None:
                bonus_text = "🎁 +10 дней подписки (реферал)"
            else:
                bonus_text = "⭐ +5 дней пробного периода"

            message_text = (
                f"🎉 Новый пользователь!\n"
                f"Порядковый номер: {total_users}\n"
                f"ID: {user_id}\n"
                f"Имя: {telegram_name}\n"
                f"Username: {user_mention}\n"
                f"Бонус: {bonus_text}"
            )
            for admin_id in admin_ids:
                try:
                    await bot.send_message(admin_id, message_text)
                except Exception as e:
                    logger.warning(f"Не удалось отправить уведомление админу {admin_id}: {e}")

    # --- ПРИВЕТСТВИЕ (ЧИСТЫЙ ТЕКСТ, БЕЗ ИЗОБРАЖЕНИЙ И РАЗДЕЛИТЕЛЕЙ) ---
    await message.answer(
        f"👋 *Привет, {telegram_name}!*\n\n"
        f"⚠️ *Важное предупреждение*\n"
        f"• Я не заменяю профессионального психолога\n"
        f"• При серьёзных проблемах обратитесь к специалисту\n\n"
        f"💬 *Выберите действие на клавиатуре ниже* 👇",
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
    await message.answer(
        "🛠 Тест на уровень депрессии (шкала Бернса) будет доступен в следующей версии.",
        reply_markup=get_main_menu(message.from_user.id)
    )


# -------------------------------------------------------------------
# ПОДКЛЮЧЕНИЕ МОДУЛЕЙ
# -------------------------------------------------------------------
register_dialog_handlers(dp)
dp.include_router(profile_router)
dp.include_router(admin_router)
# Платёжный роутер будет подключён позже
# dp.include_router(payments_router)


# -------------------------------------------------------------------
# ЗАПУСК БОТА
# -------------------------------------------------------------------
async def main():
    await init_db()
    logger.info("╔" + "═" * 53 + "╗")
    logger.info("║" + " " * 12 + "AI-ПСИХОЛОГ v4.1.1 (подписка)" + " " * 12 + "║")
    logger.info("╚" + "═" * 53 + "╝")
    logger.info("📡 СТАТУС СИСТЕМЫ:")
    logger.info("  ✅ Бот успешно запущен")
    logger.info("  ✅ DeepSeek API подключен")
    logger.info("  ✅ База данных SQLite (aiosqlite) инициализирована")
    logger.info("  ✅ Логирование в файл bot_public.log настроено")
    logger.info("🎯 АКТИВНЫЕ ФУНКЦИИ:")
    logger.info("  💬 Начать сессию — диалог с ИИ (требуется подписка)")
    logger.info("  🏠 Личный кабинет — статус подписки, история тестов")
    logger.info("  💌 Реферальная система (+10 дней подписки за друга)")
    logger.info("  🧠 Контекст и суммаризация")
    logger.info("  🆘 Кризис-детектор")
    logger.info("  ℹ️  Информация о боте")
    logger.info("  🔧 Админ-панель (управление пользователями, рассылка)")
    logger.info("🚧 В РАЗРАБОТКЕ:")
    logger.info("  📋 Тест на депрессию (шкала Бернса)")
    logger.info("  🛒 Продление подписки")
    logger.info("═" * 55)
    logger.info("⏳ Ожидание входящих сообщений...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
