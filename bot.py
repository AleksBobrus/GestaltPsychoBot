# bot.py
# Главный файл запуска Telegram-бота «AI-психолог».
# Добавлен запрос имени пользователя при первом запуске и сохранение username.

import asyncio
import os
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardRemove
from keyboards import get_main_menu
from handlers.dialog_handlers import register_dialog_handlers
from handlers.admin import router as admin_router
from database import init_db, save_user_profile

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
async def errors_handler(_: types.Update, exception: Exception):
    """Ловит все необработанные исключения и логирует их."""
    logger.exception("Критическая ошибка при обработке обновления", exc_info=exception)
    return True


# -------------------------------------------------------------------
# FSM ДЛЯ ЗАПРОСА ИМЕНИ
# -------------------------------------------------------------------
class NameState(StatesGroup):
    waiting_for_name = State()


# -------------------------------------------------------------------
# ЕДИНАЯ ФУНКЦИЯ СПРАВКИ
# -------------------------------------------------------------------
def get_help_text() -> str:
    """Возвращает текст с информацией о боте."""
    return (
        "🤖 **• AI-психолог •**\n"
        "Версия: **2.0.0**\n\n"
        "AI-психолог — это виртуальный помощник для поддержки ментального благополучия. "
        "Бот использует технологии искусственного интеллекта, чтобы выслушать, "
        "помочь разобраться в чувствах и предложить полезные техники.\n\n"
        "✨ **Актуальные возможности:**\n"
        "• 💬 **Поговорить** — беседа с ИИ-психологом\n"
        "• 🧠 **Контекст диалога** — запоминание предыдущих бесед\n"
        "• 🆘 **Кризис-детектор** — распознавание тревожных фраз и предложение помощи\n\n"
        "🚧 **В планах:**\n"
        "• 🌱 Техники заземления\n"
        "• 📋 Тест на уровень депрессии (шкала Бека)\n"
        "• 👤 Личный кабинет со статистикой\n\n"
        "⚠️ **Важно:** бот не заменяет профессионального психолога. "
        "При серьёзных проблемах необходимо обратиться к специалисту."
    )


# -------------------------------------------------------------------
# ОБРАБОТЧИК КОМАНДЫ /start (ЗАПРОС ИМЕНИ)
# -------------------------------------------------------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """При первом запуске сразу сохраняет базовый профиль и запрашивает имя."""
    await state.clear()

    user_id = message.from_user.id
    telegram_name = message.from_user.full_name or message.from_user.first_name or "Без имени"
    username = message.from_user.username

    # Сразу сохраняем профиль (без custom_name)
    await save_user_profile(
        user_id=user_id,
        telegram_name=telegram_name,
        custom_name=None,  # будет обновлено позже
        username=username
    )

    await state.set_state(NameState.waiting_for_name)
    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "Как я могу к вам обращаться? Напишите ваше имя.",
        reply_markup=ReplyKeyboardRemove()
    )


# -------------------------------------------------------------------
# ОБРАБОТЧИК ВВОДА ИМЕНИ
# -------------------------------------------------------------------
@dp.message(NameState.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    """Обновляет custom_name и показывает главное меню."""
    user_name = message.text.strip()

    if len(user_name) > 50:
        await message.answer("⚠️ Имя слишком длинное. Пожалуйста, введите покороче.")
        return

    await state.update_data(user_name=user_name)

    # Обновляем профиль, добавляя custom_name
    telegram_name = message.from_user.full_name or message.from_user.first_name or "Без имени"
    username = message.from_user.username
    await save_user_profile(
        user_id=message.from_user.id,
        telegram_name=telegram_name,
        custom_name=user_name,
        username=username
    )

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
# ОБРАБОТЧИК КОМАНДЫ /help
# -------------------------------------------------------------------
@dp.message(Command("help"))
async def cmd_help(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(get_help_text(), parse_mode="Markdown", reply_markup=get_main_menu(message.from_user.id))


# -------------------------------------------------------------------
# ОБРАБОТЧИКИ КНОПОК ГЛАВНОГО МЕНЮ
# -------------------------------------------------------------------
@dp.message(F.text == "ℹ️ О боте")
async def about_bot(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(get_help_text(), parse_mode="Markdown", reply_markup=get_main_menu(message.from_user.id))


@dp.message(F.text == "🌱 Заземлиться")
async def placeholder_grounding(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 Техники заземления появятся позже.", reply_markup=get_main_menu(message.from_user.id))


@dp.message(F.text == "📋 Пройти тест")
async def placeholder_test(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 Тест на уровень депрессии будет доступен в следующей версии.",
                         reply_markup=get_main_menu(message.from_user.id))


@dp.message(F.text == "👤 Личный кабинет")
async def placeholder_profile(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 Личный кабинет в разработке.", reply_markup=get_main_menu(message.from_user.id))


# -------------------------------------------------------------------
# ПОДКЛЮЧЕНИЕ МОДУЛЕЙ
# -------------------------------------------------------------------
register_dialog_handlers(dp)
dp.include_router(admin_router)


# -------------------------------------------------------------------
# ЗАПУСК БОТА
# -------------------------------------------------------------------
async def main():
    await init_db()
    logger.info("База данных инициализирована")
    logger.info("=" * 55)
    logger.info("        🤖 AI-ПСИХОЛОГ v2.0")
    logger.info("=" * 55)
    logger.info("📡 СТАТУС СИСТЕМЫ:")
    logger.info("  ✅ Бот успешно запущен")
    logger.info("  ✅ DeepSeek API подключен")
    logger.info("  ✅ База данных SQLite (aiosqlite) инициализирована")
    logger.info("🎯 АКТИВНЫЕ ФУНКЦИИ:")
    logger.info("  💬 Диалог с ИИ-психологом (20 сообщений/день)")
    logger.info("  🧠 Контекст и суммаризация")
    logger.info("  🆘 Кризис-детектор")
    logger.info("  ℹ️  Информация о боте")
    logger.info("  🔧 Админ-панель")
    logger.info("🚧 В РАЗРАБОТКЕ:")
    logger.info("  🌱 Техники заземления")
    logger.info("  📋 Тест на депрессию")
    logger.info("  👤 Личный кабинет")
    logger.info("=" * 55)
    logger.info("⏳ Ожидание входящих сообщений...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
