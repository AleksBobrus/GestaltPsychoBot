# keyboards.py
# Клавиатуры бота. Главное меню формируется динамически в зависимости от того,
# является ли пользователь администратором.

import os
from dotenv import load_dotenv
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Загружаем переменные из .env
load_dotenv()

# Загружаем список ID администраторов из .env
admin_ids_str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = []
if admin_ids_str:
    for part in admin_ids_str.split(","):
        part = part.strip()
        if part:
            try:
                ADMIN_IDS.append(int(part))
            except ValueError:
                print(f"[ERROR] Неверный ADMIN_ID в .env: '{part}'")

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return user_id in ADMIN_IDS

def get_main_menu(user_id: int) -> ReplyKeyboardMarkup:
    """
    Возвращает главное меню. Для администраторов добавляется кнопка «🔧 Админ-панель».
    """
    # ДИАГНОСТИКА: выводим ID пользователя и результат проверки is_admin

    keyboard = [
        [KeyboardButton(text="💬 Поговорить"), KeyboardButton(text="🌱 Заземлиться")],
        [KeyboardButton(text="📋 Пройти тест"), KeyboardButton(text="👤 Личный кабинет")],
        [KeyboardButton(text="ℹ️ О боте")]
    ]
    if is_admin(user_id):
        keyboard.append([KeyboardButton(text="🔧 Админ-панель")])

    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# Клавиатура для режима диалога (без изменений)
dialog_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="❌ Завершить диалог")]
    ],
    resize_keyboard=True
)
