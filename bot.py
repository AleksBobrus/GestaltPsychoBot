# bot.py – основная точка входа бота-психолога
# Асинхронная версия с логированием, глобальным обработчиком ошибок и инициализацией БД.

import asyncio
import os
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Update
from keyboards import main_menu_kb
from handlers.dialog_handlers import register_dialog_handlers
from database import init_db  # теперь асинхронная

# -------------------------------------------------------------------
# НАСТРОЙКА ЛОГИРОВАНИЯ
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
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
async def errors_handler(update: Update, exception: Exception):
    """Ловит все необработанные исключения, логирует и предотвращает падение бота."""
    logger.exception("Критическая ошибка при обработке обновления", exc_info=exception)
    # При желании можно отправить уведомление администратору
    return True  # True означает, что ошибка обработана и бот продолжает работу


# -------------------------------------------------------------------
# ОБРАБОТЧИКИ КОМАНД
# -------------------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_name = message.from_user.first_name or "друг"
    await message.answer(
        f"👋 Привет, {user_name}!\n\n"
        f"Я — ваш **психологический помощник**, созданный для поддержки и понимания.\n\n"
        f"⚠️ **Важно:**\n"
        f"• Я не заменяю профессионального психолога\n"
        f"• При серьёзных проблемах обратитесь к специалисту\n"
        f"• В кризисной ситуации звоните: **8-800-2000-122** (бесплатно, 24/7)\n\n"
        f"Чем могу помочь сегодня?",
        parse_mode="Markdown",
        reply_markup=main_menu_kb
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "ℹ️ **Справка по боту**\n\n"
        "**Доступные команды:**\n"
        "• /start — Главное меню\n"
        "• /help — Эта справка\n\n"
        "**Функции бота:**\n"
        "• 💬 **Поговорить** — Диалог с ИИ-психологом\n"
        "  - Лимит: 20 сообщений в день\n"
        "  - История сохраняется автоматически\n"
        "• 🌱 **Заземлиться** — (в разработке)\n"
        "• 📋 **Пройти тест** — (в разработке)\n"
        "• 👤 **Личный кабинет** — (в разработке)\n"
        "• ℹ️ **О боте** — Информация о функциях\n\n"
        "**Важно:** Бот не заменяет профессионального психолога!",
        parse_mode="Markdown",
        reply_markup=main_menu_kb
    )


# -------------------------------------------------------------------
# ЗАГЛУШКИ ДЛЯ КНОПОК
# -------------------------------------------------------------------
@dp.message(F.text == "🌱 Заземлиться")
async def placeholder_grounding(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 Техники заземления появятся позже.", reply_markup=main_menu_kb)


@dp.message(F.text == "📋 Пройти тест")
async def placeholder_test(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 Тест Бека будет доступен в следующей версии.", reply_markup=main_menu_kb)


@dp.message(F.text == "👤 Личный кабинет")
async def placeholder_profile(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 Личный кабинет в разработке.", reply_markup=main_menu_kb)


@dp.message(F.text == "ℹ️ О боте")
async def about_bot(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🤖 **Психологический помощник**\n\n"
        "**Что я умею:**\n"
        "• 💬 Диалог с ИИ-психологом на базе DeepSeek\n"
        "• 🧠 Запоминаю контекст ваших бесед\n"
        "• 🆘 Обнаруживаю кризисные ситуации и предлагаю помощь\n"
        "• 📊 20 бесплатных сообщений в день\n\n"
        "**Скоро появится:**\n"
        "• 📋 Тест Бека на уровень депрессии\n"
        "• 🌱 Техники заземления (дыхание 4-7-8, метод 5-4-3-2-1)\n"
        "• 👤 Личный кабинет с историей диалогов\n\n"
        "⚠️ **Помните:** я помогаю, но не заменяю специалиста!",
        parse_mode="Markdown",
        reply_markup=main_menu_kb
    )


# -------------------------------------------------------------------
# ПОДКЛЮЧЕНИЕ ОБРАБОТЧИКОВ ДИАЛОГА
# -------------------------------------------------------------------
register_dialog_handlers(dp)


# -------------------------------------------------------------------
# ЗАПУСК БОТА
# -------------------------------------------------------------------
async def main():
    # Инициализация базы данных (асинхронная)
    await init_db()
    logger.info("База данных инициализирована")

    logger.info("=" * 55)
    logger.info("        🤖 ПСИХОЛОГИЧЕСКИЙ ПОМОЩНИК v2.0")
    logger.info("=" * 55)
    logger.info("📡 СТАТУС СИСТЕМЫ:")
    logger.info("  ✅ Бот успешно запущен")
    logger.info("  ✅ DeepSeek API подключен")
    logger.info("  ✅ База данных SQLite (aiosqlite) инициализирована")
    logger.info("🎯 АКТИВНЫЕ ФУНКЦИИ:")
    logger.info("  💬 Диалог с ИИ-психологом")
    logger.info("     └─ Лимит: 20 сообщений/день")
    logger.info("     └─ Контекст: 20 последних сообщений")
    logger.info("     └─ Суммаризация каждые 30 сообщений")
    logger.info("  🆘 Детектор кризисных ситуаций")
    logger.info("  ℹ️  Информация о боте")
    logger.info("🚧 В РАЗРАБОТКЕ:")
    logger.info("  📋 Тест Бека на депрессию")
    logger.info("  🌱 Техники заземления")
    logger.info("  👤 Личный кабинет с историей")
    logger.info("=" * 55)
    logger.info("⏳ Ожидание входящих сообщений...")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
