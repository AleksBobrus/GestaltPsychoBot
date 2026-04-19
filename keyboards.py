# keyboards.py – все клавиатуры бота
# ReplyKeyboardMarkup, KeyboardButton – классы для создания обычных (reply) кнопок.
# ReplyKeyboardMarkup – клавиатура с кнопками, которые появляются вместо поля ввода.
# KeyboardButton – одна кнопка на такой клавиатуре.

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
# from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# -------------------------------------------------------------------
# КЛАВИАТУРА ГЛАВНОГО МЕНЮ
# -------------------------------------------------------------------
# Это обычная reply-клавиатура, которая появляется вместо поля ввода.
# Кнопки расположены в два ряда по две и один ряд с одной кнопкой.
main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="💬 Поговорить"), KeyboardButton(text="🌱 Заземлиться")],
        [KeyboardButton(text="📋 Пройти тест"), KeyboardButton(text="👤 Личный кабинет")],
        [KeyboardButton(text="ℹ️ О боте"), KeyboardButton(text="🔧 Админ-панель")]
    ],
    resize_keyboard=True
)

# Клавиатура для режима диалога (только кнопка выхода)
dialog_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="❌ Завершить диалог")]
    ],
    resize_keyboard=True
)
