# handlers/depression_test.py
# Модуль для прохождения теста на депрессию (шкала Бернса, 25 вопросов).
# Использует FSM (конечный автомат) для последовательного опроса.

import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import save_depression_result  # функция сохранения результата

logger = logging.getLogger(__name__)
router = Router()

# Список из 25 вопросов (в соответствии со шкалой Бернса)
QUESTIONS = [
    "Вам грустно или вы в плохом настроении?",
    "Чувствуете грусть, удручены?",
    "Чувствуете желание расплакаться, слезливость?",
    "Чувствуете уныние?",
    "Испытываете чувство безнадежности?",
    "Имеете низкую самооценку?",
    "Испытываете чувство собственной ничтожности и непригодности?",
    "Испытываете чувство вины или стыда?",
    "Критикуете или обвиняете самого себя?",
    "Испытываете трудности с принятием решений?",
    "Чувствуете потерю интереса к членам семьи, друзьям, коллегам?",
    "Испытываете одиночество?",
    "Проводите меньше времени с семьей или с друзьями?",
    "Чувствуете потерю мотивации?",
    "Чувствуете потерю интереса к работе или другим занятиям?",
    "Избегаете работы и другой деятельности?",
    "Ощущаете потерю удовольствия и нехватку удовлетворения от жизни?",
    "Чувствуете усталость?",
    "Испытываете затруднения со сном или, наоборот, слишком много спите?",
    "Имеете сниженный или, наоборот, повышенный аппетит?",
    "Замечаете потерю интереса к сексу?",
    "Беспокоитесь по поводу своего здоровья?",
    "Имеются ли у вас суицидальные мысли?",
    "Хотели бы вы окончить свою жизнь?",
    "Планируете ли вы навредить себе?",
]

# Варианты ответов (одинаковы для всех вопросов)
ANSWER_OPTIONS = [
    ("0 – Ни разу", 0),
    ("1 – Иногда", 1),
    ("2 – Умеренно", 2),
    ("3 – Часто", 3),
    ("4 – Очень часто", 4),
]


# -------------------------------------------------------------------
# СОСТОЯНИЯ FSM
# -------------------------------------------------------------------
class DepressionTest(StatesGroup):
    """Состояния для прохождения теста Бернса."""
    answering = State()  # бот ожидает ответа на текущий вопрос


# -------------------------------------------------------------------
# ИНТЕРПРЕТАЦИЯ РЕЗУЛЬТАТОВ
# -------------------------------------------------------------------
def interpret_score(score: int) -> str:
    """Возвращает текстовую интерпретацию суммы баллов."""
    if score <= 5:
        return "Депрессия отсутствует"
    elif score <= 10:
        return "Нормальное, но несчастливое состояние"
    elif score <= 25:
        return "Слабо выраженная депрессия"
    elif score <= 50:
        return "Умеренная депрессия"
    elif score <= 75:
        return "Сильно выраженная депрессия"
    else:
        return "Крайняя степень депрессии"


def check_crisis_answers(answers: list) -> bool:
    """
    Проверяет, были ли положительные ответы на вопросы 23, 24 или 25.
    Если да – рекомендуется немедленно обратиться за профессиональной помощью.
    """
    # Вопросы 23, 24, 25 имеют индексы 22, 23, 24 (нумерация с 0)
    crisis_indices = [22, 23, 24]
    for idx in crisis_indices:
        if idx < len(answers) and answers[idx] > 0:
            return True
    return False


# -------------------------------------------------------------------
# ЗАПУСК ТЕСТА (ВХОДНАЯ ТОЧКА)
# -------------------------------------------------------------------
@router.message(F.text == "📋 Пройти тест")
async def start_test(message: types.Message, state: FSMContext):
    """Начинает тест, задавая первый вопрос."""
    # Сбрасываем состояние перед началом
    await state.clear()
    # Сохраняем в состояние: текущий индекс вопроса и накопленные баллы
    await state.update_data(question_index=0, answers=[])
    # Отправляем первый вопрос
    await send_question(message, state)


async def send_question(message: types.Message, state: FSMContext):
    """Отправляет текущий вопрос с вариантами ответов."""
    data = await state.get_data()
    idx = data.get("question_index", 0)

    if idx >= len(QUESTIONS):
        # Все вопросы отвечены – показываем результат
        await show_result(message, state)
        return

    question_text = QUESTIONS[idx]
    # Формируем клавиатуру с вариантами ответов
    buttons = []
    for label, value in ANSWER_OPTIONS:
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"depr_answer:{idx}:{value}"
            )
        ])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer(
        f"📋 **Вопрос {idx + 1} из {len(QUESTIONS)}**\n\n{question_text}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


# -------------------------------------------------------------------
# ОБРАБОТКА ОТВЕТА НА ВОПРОС
# -------------------------------------------------------------------
@router.callback_query(F.data.startswith("depr_answer:"))
async def process_answer(callback: types.CallbackQuery, state: FSMContext):
    """Обрабатывает выбор варианта ответа."""
    # Извлекаем данные из callback_data
    parts = callback.data.split(":")
    question_index = int(parts[1])
    score = int(parts[2])

    # Получаем текущее состояние
    data = await state.get_data()
    answers = data.get("answers", [])
    # Сохраняем балл за текущий вопрос
    answers.append(score)
    # Переходим к следующему вопросу
    next_index = question_index + 1
    await state.update_data(question_index=next_index, answers=answers)

    # Отвечаем на callback, чтобы Telegram убрал "часики"
    await callback.answer()

    # Отправляем следующий вопрос или показываем результат
    # Для этого используем сообщение, к которому прикреплена клавиатура
    await callback.message.edit_reply_markup()  # убираем старую клавиатуру
    await send_question(callback.message, state)


# -------------------------------------------------------------------
# ЗАВЕРШЕНИЕ ТЕСТА И ВЫВОД РЕЗУЛЬТАТА
# -------------------------------------------------------------------
async def show_result(message: types.Message, state: FSMContext):
    """Подсчитывает сумму баллов, интерпретирует и сохраняет в БД."""
    data = await state.get_data()
    answers = data.get("answers", [])
    total_score = sum(answers)

    interpretation = interpret_score(total_score)
    crisis = check_crisis_answers(answers)

    # Сохраняем результат в базу данных
    user_id = message.chat.id
    await save_depression_result(user_id, total_score, interpretation)

    # Формируем текст результата
    result_text = (
        f"📊 **Результат теста Бернса**\n\n"
        f"Сумма баллов: **{total_score}** из 100\n"
        f"Интерпретация: **{interpretation}**\n\n"
    )
    if crisis:
        result_text += (
            "⚠️ **Вы дали положительный ответ на один или несколько вопросов "
            "о суицидальных мыслях.**\n"
            "Пожалуйста, немедленно обратитесь за профессиональной помощью!\n"
            "📞 **Телефон доверия:** 8-800-2000-122 (бесплатно, 24/7)\n\n"
        )
    result_text += "Спасибо за прохождение теста."

    await message.answer(result_text, parse_mode="Markdown")
    # Очищаем состояние
    await state.clear()
