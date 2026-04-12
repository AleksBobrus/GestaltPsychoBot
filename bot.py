
# bot.py – первая версия: главное меню и кнопки

import asyncio
import os
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path=env_path)

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from database import init_db, save_user, save_message, get_recent_history, save_bdi_result
from ai_client import get_ai_response
from bdi_test import questions, interpret_score

# база дыхательных и релаксационных упражнений
from exercises import get_random_exercise, get_random_anxiety_technique
from crisis_detector import is_crisis_message, get_crisis_response

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# -------------------------------------------------------------------
# Клавиатура главного меню (все кнопки из вашего ТЗ)
main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="😰 Мне тревожно"), KeyboardButton(text="🧘 Хочу упражнение")],
        [KeyboardButton(text="💬 Поговорить"), KeyboardButton(text="📋 Пройти тест")],
        [KeyboardButton(text="ℹ️ О боте")]
    ],
    resize_keyboard=True
)

# -------------------------------------------------------------------
# Состояния FSM (машина состояний)
class DialogState(StatesGroup):
    waiting_for_message = State()   # режим диалога с ИИ

class TestState(StatesGroup):
    waiting_for_answer = State()  # будем хранить номер вопроса и список ответов

# -------------------------------------------------------------------
# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user = message.from_user
    save_user(user.id, user.first_name, user.last_name, user.username)
    # Выходим из любого состояния
    await state.clear()

    """Приветствие и показ главного меню"""
    await message.answer(
        "⚠️ Бот не заменяет профессионального психотерапевта.\n\n"
        "Здравствуйте! Я персоналтный ИИ-психолог на базе нейросети DeepSeek.\n"
        "Работаю в подходах гештальт-терапии и когнитивно-поведенческой терапии.\n"
        "Помогу разобраться с мыслями, чувствами и сложными ситуациями.\n"
        "Пиши мне текст, а скоро станут доступны и голосовые 🙂\n",
        reply_markup=main_menu_kb
    )

# -------------------------------------------------------------------
@dp.message(F.text == "ℹ️ О боте")
async def about_bot(message: types.Message, state: FSMContext):
    await state.clear()
    """Информация о возможностях бота"""
    await message.answer(
        "📋 **Тест Бека** – диагностика уровня депрессии\n"
        "🧘 **Упражнения** – дыхательные и релаксационные техники\n"
        "💬 **Поговорить** – беседа с ИИ-психологом (гештальт + КПТ)\n"
        "😰 **Мне тревожно** – техники совладания с тревогой\n"
        "🆘 **Кризисная помощь** – бот определяет суицидальные мысли и даёт контакты\n\n"
        "⚠️ Бот не заменяет профессионального психотерапевта.",
        parse_mode="Markdown",
        reply_markup=main_menu_kb
    )

# -------------------------------------------------------------------
# Диалоговый режим

@dp.message(F.text == "💬 Поговорить")
async def start_talk(message: types.Message, state: FSMContext):
    await state.set_state(DialogState.waiting_for_message)
    await message.answer(
        "Режим беседы включён. Напишите, что вас беспокоит.\nЧтобы выйти, нажмите любую другую кнопку или /start.",
        reply_markup=main_menu_kb
    )

@dp.message(DialogState.waiting_for_message, F.text)
async def process_dialog(message: types.Message, state: FSMContext):
    # Проверка кризиса
    if is_crisis_message(message.text):
        await message.answer(get_crisis_response(), parse_mode="Markdown", reply_markup=main_menu_kb)
        await state.clear()
        return

    # Если сообщение совпадает с одной из кнопок меню – выходим из режима и обрабатываем соответствующую кнопку
    if message.text in ["😰 Мне тревожно", "🧘 Хочу упражнение", "📋 Пройти тест", "ℹ️ О боте"]:
        await state.clear()
        # В зависимости от кнопки вызываем соответствующий хендлер (дублируем логику)
        if message.text == "ℹ️ О боте":
            await about_bot(message, state)  # state уже очищен, но функция ожидает state
        elif message.text == "📋 Пройти тест":
            await start_bdi_test(message, state)
        elif message.text == "😰 Мне тревожно":
            await send_anxiety_technique(message, state)
        elif message.text == "🧘 Хочу упражнение":
            await send_exercise(message, state)
        return

    user_id = message.from_user.id
    user_text = message.text.strip()
    save_message(user_id, "user", user_text)
    history = get_recent_history(user_id, limit=10)
    messages_for_api = [{"role": role, "content": content} for role, content in history]
    await bot.send_chat_action(user_id, action="typing")
    reply = await get_ai_response(messages_for_api)
    save_message(user_id, "assistant", reply)
    await message.answer(reply, reply_markup=main_menu_kb)

# -------------------------------------------------------------------
# ТЕСТ БЕКА
@dp.message(F.text == "📋 Пройти тест")
async def start_bdi_test(message: types.Message, state: FSMContext):
    print("Начали проходить тест Бека")
    await state.clear()  # сбросить предыдущее состояние
    # Инициализируем данные теста: список ответов (пока пустой), текущий вопрос = 0
    await state.update_data(answers=[], current_q=0)
    await state.set_state(TestState.waiting_for_answer)
    cancel_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Прервать тест")]],
        resize_keyboard=True
    )
    # Отправляем первый вопрос
    q_text = questions[0]
    await message.answer(
        f"📋 **Тест Бека на депрессию** (вопрос 1 из 21)\n\n{q_text}",
        parse_mode="Markdown",
        reply_markup=cancel_kb
    )

@dp.message(TestState.waiting_for_answer, F.text == "❌ Прервать тест")
async def cancel_test(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Тест прерван. Возвращаемся в главное меню.", reply_markup=main_menu_kb)

@dp.message(TestState.waiting_for_answer)
async def process_bdi_answer(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    answers = data.get("answers", [])
    current_q = data.get("current_q", 0)

    # Проверка кризиса
    if is_crisis_message(message.text):
        await message.answer(get_crisis_response(), parse_mode="Markdown", reply_markup=main_menu_kb)
        await state.clear()
        return

    # Проверка на прерывание (уже есть кнопка, но и текстом можно)
    if message.text == "❌ Прервать тест":
        await state.clear()
        await message.answer("Тест прерван. Возвращаемся в главное меню.", reply_markup=main_menu_kb)
        return

    # Пользователь должен ввести число от 0 до 3
    try:
        score = int(message.text.strip())
        if score not in range(4):
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите число от 0 до 3, соответствующее вашему ответу.")
        return

    # Сохраняем ответ
    answers.append(score)
    current_q += 1

    # Клавиатура с кнопкой прерывания (будет использоваться на каждом шаге)
    cancel_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Прервать тест")]],
        resize_keyboard=True
    )

    if current_q < 21:
        # Следующий вопрос
        await state.update_data(answers=answers, current_q=current_q)
        q_text = questions[current_q]
        await message.answer(
            f"📋 Вопрос {current_q + 1} из 21\n\n{q_text}",
            parse_mode="Markdown",
            reply_markup = cancel_kb # <-- вот здесь добавляем клавиатуру
        )
    else:
        # Тест завершён
        total_score = sum(answers)
        interpretation = interpret_score(total_score)
        # Сохраняем в БД
        save_bdi_result(user_id, total_score, interpretation)
        # Выводим результат
        result_text = (
            f"✅ **Тест пройден!**\n\n"
            f"Ваш суммарный балл: **{total_score}** из 63\n"
            f"Интерпретация: **{interpretation}**\n\n"
            f"⚠️ Помните, что тест Бека не является диагнозом. "
            f"При высоких показателях рекомендуется обратиться к психотерапевту."
        )
        await message.answer(result_text, parse_mode="Markdown", reply_markup=main_menu_kb)
        await state.clear()

# -------------------------------------------------------------------
# Упрожнения
@dp.message(F.text == "🧘 Хочу упражнение")
async def send_exercise(message: types.Message, state: FSMContext):
    await state.clear()  # выходим из любого режима (диалог, тест)
    exercise = get_random_exercise()
    await message.answer(
        f"🧘 Вот упражнение для вас:\n\n{exercise}",
        parse_mode="Markdown",
        reply_markup=main_menu_kb
    )

# -------------------------------------------------------------------
@dp.message(F.text == "😰 Мне тревожно")
async def send_anxiety_technique(message: types.Message, state: FSMContext):
    await state.clear()  # выходим из любого режима (диалог, тест)
    technique = get_random_anxiety_technique()
    await message.answer(
        f"😰 Вот техника, которая может помочь справиться с тревогой:\n\n{technique}\n\n"
        f"Вы можете попросить другую технику, снова нажав «😰 Мне тревожно».",
        parse_mode="Markdown",
        reply_markup=main_menu_kb
    )

#--------------------------------------------------------------------
@dp.message(F.text)
async def catch_all_messages(message: types.Message, state: FSMContext):
    if is_crisis_message(message.text):
        await message.answer(get_crisis_response(), parse_mode="Markdown", reply_markup=main_menu_kb)
        await state.clear()
    else:
        await message.answer("Пожалуйста, воспользуйтесь кнопками меню.", reply_markup=main_menu_kb)

# -------------------------------------------------------------------
async def main():
    init_db()
    print("Бот запущен. Тест Бека доступен. Хочу упражнение доступно. ")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())