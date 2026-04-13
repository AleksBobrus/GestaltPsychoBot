# database.py – модуль для работы с базой данных SQLite.
# Здесь хранится история диалогов пользователей с ботом.
# Данные сохраняются на диске и не теряются после перезапуска бота.

import sqlite3
from datetime import datetime
from typing import List, Dict

# Константа с именем файла базы данных
DB_NAME = "dialog_history.db"

def init_db() -> None:
    """
    Создаёт таблицу chat_history, если она ещё не существует.
    Вызывается один раз при старте бота.
    Таблица содержит поля:
        id – уникальный идентификатор записи (автоинкремент)
        user_id – Telegram ID пользователя
        role – роль: 'user' или 'assistant'
        content – текст сообщения
        timestamp – дата и время отправки
    Также создаётся индекс по user_id для ускорения выборки истории.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp TIMESTAMP
        )
    """)
    # Индекс ускоряет запросы вида WHERE user_id = ?
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON chat_history(user_id)")
    conn.commit()
    conn.close()

def save_message(user_id: int, role: str, content: str) -> None:
    """
    Сохраняет одно сообщение (от пользователя или от бота) в базу данных.
    Аргументы:
        user_id – идентификатор пользователя в Telegram
        role – 'user' или 'assistant'
        content – текст сообщения
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO chat_history (user_id, role, content, timestamp)
        VALUES (?, ?, ?, ?)
    """, (user_id, role, content, datetime.now()))
    conn.commit()
    conn.close()

def get_recent_history(user_id: int, limit: int = 20) -> List[Dict[str, str]]:
    """
    Возвращает последние `limit` сообщений пользователя в формате, пригодном для передачи в DeepSeek API.
    Формат: список словарей [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
    Сообщения возвращаются в хронологическом порядке (от старых к новым).
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Выбираем последние limit записей для данного пользователя в обратном порядке (новые сверху)
    cursor.execute("""
        SELECT role, content FROM chat_history
        WHERE user_id = ?
        ORDER BY timestamp DESC LIMIT ?
    """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    # Переворачиваем, чтобы порядок был от старых к новым (как требуется для LLM)
    history = [{"role": role, "content": content} for role, content in reversed(rows)]
    return history

def clear_user_history(user_id: int) -> None:
    """
    Удаляет всю историю диалога для указанного пользователя.
    Может быть полезно, если пользователь хочет очистить свои данные.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()