# handlers/depression_test.py
# Модуль для прохождения теста на депрессию (шкала Бернса, 25 вопросов).
# Использует FSM (конечный автомат) для последовательного опроса.
# Перед началом теста показывается ознакомительное окно с кнопками «Приступить» и «Отмена».
# После каждого ответа сообщение с вопросом удаляется, чтобы не засорять чат.
# На каждом вопросе есть кнопка «Прервать» для досрочного выхода БЕЗ сохранения результата.

import logging
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from keyboards import get_main_menu
from database import save_depression_result

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

# Варианты ответов (текст кнопок – без цифр, только словесное описание)
ANSWER_OPTIONS = [
    ("Ни разу", 0),
    ("Иногда", 1),
    ("Умеренно", 2),
    ("Часто", 3),
    ("Очень часто", 4),
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
# ЗАПУСК ТЕСТА – ТЕПЕРЬ С ПОДТВЕРЖДЕНИЕМ
# -------------------------------------------------------------------
@router.message(F.text == "📋 Пройти тест")
async def start_test(message: types.Message, state: FSMContext):
    """
    Показывает приглашение пройти тест Бернса.
    Пользователь может согласиться или отказаться.
    """
    await state.clear()  # на всякий случай сбрасываем предыдущее состояние

    text = (
        "📋 **Тест на уровень депрессии (шкала Бернса)**\n\n"
        "Вам будет задано 25 вопросов. На каждый вопрос нужно ответить, "
        "насколько часто вы испытывали описанное состояние в течение последней недели.\n\n"
        "Варианты ответов: от «Ни разу» до «Очень часто».\n\n"
        "После завершения теста вы получите интерпретацию результата.\n\n"
        "⚠️ *Тест не является диагнозом и не заменяет консультацию специалиста.*\n"
        "Если вы испытываете серьёзные трудности, обратитесь к психологу или психотерапевту."
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Приступить", callback_data="start_test_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="start_test_cancel")]
    ])

    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)


# -------------------------------------------------------------------
# ОБРАБОТКА КНОПКИ «ПРИСТУПИТЬ»
# -------------------------------------------------------------------
@router.callback_query(F.data == "start_test_confirm")
async def confirm_test(callback: types.CallbackQuery, state: FSMContext):
    """Начинает тест после подтверждения."""
    # Удаляем пригласительное сообщение
    try:
        await callback.message.delete()
    except Exception:
        pass  # если не удалось удалить – ничего страшного
    await callback.answer()

    # Инициализируем состояние теста
    await state.set_state(DepressionTest.answering)
    await state.update_data(question_index=0, answers=[])

    # Отправляем первый вопрос
    await send_question(callback.message, state)


# -------------------------------------------------------------------
# ОБРАБОТКА КНОПКИ «ОТМЕНА»
# -------------------------------------------------------------------
@router.callback_query(F.data == "start_test_cancel")
async def cancel_test(callback: types.CallbackQuery, state: FSMContext):
    """Отменяет тест и возвращает главное меню."""
    await state.clear()
    # Удаляем пригласительное сообщение
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()
    await callback.message.answer(
        "",  # пустой текст
        reply_markup=get_main_menu(callback.from_user.id)
    )


# -------------------------------------------------------------------
# ОТПРАВКА ТЕКУЩЕГО ВОПРОСА
# -------------------------------------------------------------------
async def send_question(message: types.Message, state: FSMContext):
    """Отправляет текущий вопрос с вариантами ответов и кнопкой «Прервать»."""
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
    # Добавляем кнопку досрочного завершения теста
    buttons.append([
        InlineKeyboardButton(
            text="⏹ Прервать тест",
            callback_data="stop_test"
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
    """Обрабатывает выбор варианта ответа и удаляет сообщение с вопросом."""
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

    # Удаляем сообщение с текущим вопросом, чтобы не засорять чат
    try:
        await callback.message.delete()
    except Exception:
        pass  # если удаление не удалось, продолжаем

    # Отправляем следующий вопрос или показываем результат
    await send_question(callback.message, state)


# -------------------------------------------------------------------
# ОБРАБОТКА ДОСРОЧНОГО ЗАВЕРШЕНИЯ ТЕСТА (БЕЗ СОХРАНЕНИЯ)
# -------------------------------------------------------------------
@router.callback_query(F.data == "stop_test")
async def stop_test(callback: types.CallbackQuery, state: FSMContext):
    """
    Досрочно прерывает тест. Ничего не сохраняет в БД.
    Показывает сообщение, что тест не завершён, и возвращает главное меню.
    """
    await callback.answer()
    # Удаляем сообщение с текущим вопросом
    try:
        await callback.message.delete()
    except Exception:
        pass

    # Очищаем состояние теста
    await state.clear()

    # Сообщаем пользователю, что тест не завершён
    await callback.message.answer(
        "⏹ **Тест прерван.**\n\n"
        "Вы не завершили тест. Результат не сохранён.\n"
        "Вы можете пройти тест позже, нажав кнопку «📋 Пройти тест».",
        parse_mode="Markdown",
        reply_markup=get_main_menu(callback.from_user.id)
    )


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
            "⚠️ **Ваши ответы требуют внимания специалиста.**\n"
            "Рекомендуем обратиться к психологу или психотерапевту для профессиональной оценки.\n\n"
        )
    result_text += "Спасибо за прохождение теста."

    await message.answer(result_text, parse_mode="Markdown")
    # Очищаем состояние
    await state.clear()
