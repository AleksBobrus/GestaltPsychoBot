# bot.py
# Главный файл запуска Telegram-бота «AI-психолог».
# Реализована реферальная система с бонусами:
#   - Без реферала: +20 сообщений при регистрации.
#   - По реферальной ссылке: приглашённый получает +100, пригласивший +100.

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
    init_db, save_user_profile, add_balance, get_balance,
    add_referral, has_pending_referral_bonus, mark_referral_bonus_given, get_inviter_id
)

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
    """Возвращает текст с информацией о боте (версия 3.2.0)."""
    return (
        "🤖 **• AI-психолог •**\n"
        "Версия: **3.2.0**\n\n"
        "AI-психолог — это виртуальный помощник для поддержки ментального благополучия. "
        "Бот использует технологии искусственного интеллекта, чтобы выслушать, "
        "помочь разобраться в чувствах и предложить полезные техники.\n\n"
        "✨ **Актуальные возможности:**\n"
        "• 💬 **Начать сессию** — беседа с ИИ-психологом (расход баланса)\n"
        "• 👤 **Личный кабинет** — баланс, статистика сессий, история тестов\n"
        "• 🎁 **Пригласи друга** — получайте +100 сообщений за каждого друга\n"
        "• 🧠 **Контекст диалога** — запоминание предыдущих бесед\n"
        "• 🆘 **Кризис-детектор** — распознавание тревожных фраз\n\n"
        "🚧 **В планах:**\n"
        "• 📋 Тест на уровень депрессии (шкала Бека)\n"
        "• 🛒 Покупка сообщений\n\n"
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
                    print(f"[REFERRAL] Пользователь {user_id} приглашён пользователем {inviter_id}")
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
# ОБРАБОТЧИК ВВОДА ИМЕНИ (НАЧИСЛЕНИЕ БАЛАНСА И РЕФЕРАЛЬНЫХ БОНУСОВ)
# -------------------------------------------------------------------
@dp.message(NameState.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    """
    После ввода имени:
      - Обновляет custom_name.
      - Если баланс равен 0 (первая регистрация), начисляет стартовые сообщения:
          * без реферала: 20
          * по реферальной ссылке: 100 (вместо 20)
      - Если пользователь был приглашён и бонус ещё не выплачен:
          * начисляет пригласившему 100 сообщений
          * отмечает бонус как выданный.
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

    # --- НАЧИСЛЕНИЕ СТАРТОВОГО БАЛАНСА (только если баланс равен 0) ---
    current_balance = await get_balance(user_id)
    if current_balance == 0:
        # Проверяем, пришёл ли пользователь по реферальной ссылке
        inviter_id = await get_inviter_id(user_id)
        if inviter_id is not None:
            # Пользователь приглашён – даём 100 сообщений
            await add_balance(user_id, 100)
            print(f"[BALANCE] 100 стартовых сообщений начислено пользователю {user_id} (реферал)")
        else:
            # Обычная регистрация – 20 сообщений
            await add_balance(user_id, 20)
            print(f"[BALANCE] 20 стартовых сообщений начислено пользователю {user_id}")

    # --- ПРОВЕРКА РЕФЕРАЛЬНОГО БОНУСА ДЛЯ ПРИГЛАСИВШЕГО ---
    # Если текущий пользователь был приглашён и бонус ещё не выплачен
    if await has_pending_referral_bonus(user_id):
        inviter_id = await get_inviter_id(user_id)
        if inviter_id:
            # Пригласивший получает 100 сообщений
            await add_balance(inviter_id, 100)
            await mark_referral_bonus_given(user_id)
            print(f"[REFERRAL] Бонус 100 сообщений начислен пользователю {inviter_id} за приглашение {user_id}")

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
# ОСТАЛЬНЫЕ ОБРАБОТЧИКИ (БЕЗ ИЗМЕНЕНИЙ)
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
    logger.info("        🤖 AI-ПСИХОЛОГ v3.2.0")
    logger.info("=" * 55)
    logger.info("📡 СТАТУС СИСТЕМЫ:")
    logger.info("  ✅ Бот успешно запущен")
    logger.info("  ✅ DeepSeek API подключен")
    logger.info("  ✅ База данных SQLite (aiosqlite) инициализирована")
    logger.info("🎯 АКТИВНЫЕ ФУНКЦИИ:")
    logger.info("  💬 Начать сессию — диалог с ИИ (расход баланса)")
    logger.info("  👤 Личный кабинет — баланс, сессии, история тестов, рефералы")
    logger.info("  🎁 Реферальная система (+100 сообщений за друга)")
    logger.info("  🧠 Контекст и суммаризация")
    logger.info("  🆘 Кризис-детектор")
    logger.info("  ℹ️  Информация о боте")
    logger.info("  🔧 Админ-панель (управление пользователями, рассылка)")
    logger.info("🚧 В РАЗРАБОТКЕ:")
    logger.info("  📋 Тест на депрессию (шкала Бека)")
    logger.info("  🛒 Покупка сообщений")
    logger.info("=" * 55)
    logger.info("⏳ Ожидание входящих сообщений...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
