# database.py
# Модуль для работы с SQLite базой данных бота-психолога.
# Хранит историю диалогов, результаты теста Бека и лимиты сообщений.

import sqlite3
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple

# Имя файла базы данных (создаётся в папке проекта)
DB_NAME = "dialog_history.db"

# -------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ (СОЗДАНИЕ ТАБЛИЦ)
# -------------------------------------------------------------------
def init_db() -> None:
    """
    Создаёт все необходимые таблицы, если они ещё не существуют.
    Вызывается один раз при запуске бота.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Таблица истории диалогов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,              -- 'user' или 'assistant'
            content TEXT,
            timestamp TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON chat_history(user_id)")

    # Таблица результатов теста Бека
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bdi_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TIMESTAMP,
            score INTEGER,
            interpretation TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bdi_user_id ON bdi_results(user_id)")

    # -------------------------------------------------------------------
    # НОВАЯ ТАБЛИЦА ДЛЯ ЛИМИТОВ СООБЩЕНИЙ
    # -------------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS message_limits (
            user_id INTEGER PRIMARY KEY,
            daily_count INTEGER DEFAULT 0,
            reset_date TEXT        -- дата в формате ГГГГ-ММ-ДД
        )
    """)

    # -------------------------------------------------------------------
    # ТАБЛИЦА СУММАРИЗАЦИЙ ДИАЛОГОВ
    # -------------------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            start_message_id INTEGER,   -- ID первого сообщения в диапазоне
            end_message_id INTEGER,     -- ID последнего сообщения в диапазоне
            summary_text TEXT,          -- Краткая выжимка диалога
            created_at TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_summaries_user_id ON summaries(user_id)")

    conn.commit()
    conn.close()


# -------------------------------------------------------------------
# ФУНКЦИИ ДЛЯ ИСТОРИИ ДИАЛОГОВ (существующие)
# -------------------------------------------------------------------
def save_message(user_id: int, role: str, content: str) -> None:
    """Сохраняет одно сообщение (от пользователя или от бота) в историю."""
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
    Возвращает последние `limit` сообщений пользователя в формате:
    [{"role": "user", "content": "..."}, ...]
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT role, content FROM chat_history
        WHERE user_id = ?
        ORDER BY timestamp DESC LIMIT ?
    """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    # Возвращаем в хронологическом порядке (от старых к новым)
    return [{"role": role, "content": content} for role, content in reversed(rows)]

def clear_user_history(user_id: int) -> None:
    """Удаляет всю историю диалога для пользователя."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# -------------------------------------------------------------------
# ФУНКЦИИ ДЛЯ ТЕСТА БЕКА (существующие)
# -------------------------------------------------------------------
def save_bdi_result(user_id: int, score: int, interpretation: str) -> None:
    """Сохраняет результат теста Бека в базу данных."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        INSERT INTO bdi_results (user_id, date, score, interpretation)
        VALUES (?, ?, ?, ?)
    """, (user_id, datetime.now(), score, interpretation))
    conn.commit()
    conn.close()




# -------------------------------------------------------------------
# НОВЫЕ ФУНКЦИИ ДЛЯ ЛИМИТОВ СООБЩЕНИЙ
# -------------------------------------------------------------------
def get_message_count_today(user_id: int) -> int:
    """
    Возвращает количество сообщений, отправленных пользователем сегодня в режиме диалога.
    Если запись отсутствует или reset_date не сегодня, возвращает 0.
    """
    today_str = date.today().isoformat()   # например, "2025-04-14"
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT daily_count, reset_date FROM message_limits WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return 0
    count, reset_date = row
    if reset_date != today_str:
        return 0   # счётчик за другой день
    return count

def increment_message_count(user_id: int) -> int:
    """
    Увеличивает счётчик сообщений для пользователя на 1.
    Если запись отсутствует или reset_date не сегодня, создаёт новую запись с today_str и count=1.
    Возвращает новое значение счётчика.
    """
    today_str = date.today().isoformat()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Используем INSERT OR REPLACE с условной логикой через CASE
    cursor.execute("""
        INSERT INTO message_limits (user_id, daily_count, reset_date)
        VALUES (?, 1, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            daily_count = CASE
                WHEN reset_date = ? THEN daily_count + 1
                ELSE 1
            END,
            reset_date = ?
    """, (user_id, today_str, today_str, today_str))
    conn.commit()
    # Получаем обновлённое значение
    cursor.execute("SELECT daily_count FROM message_limits WHERE user_id = ?", (user_id,))
    new_count = cursor.fetchone()[0]
    conn.close()
    return new_count

def can_send_message(user_id: int, limit: int = 20) -> bool:
    """
    Проверяет, может ли пользователь отправить сообщение.
    Возвращает True, если текущее количество сообщений за сегодня < limit, иначе False.
    """
    count = get_message_count_today(user_id)
    return count < limit


# -------------------------------------------------------------------
# ФУНКЦИИ ДЛЯ СУММАРИЗАЦИИ ДИАЛОГОВ
# -------------------------------------------------------------------
def save_summary(user_id: int, start_msg_id: int, end_msg_id: int, summary_text: str) -> None:
    """Сохраняет суммаризацию диалога в БД."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO summaries (user_id, start_message_id, end_message_id, summary_text, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, start_msg_id, end_msg_id, summary_text, datetime.now()))
    conn.commit()
    conn.close()
    print(f"[INFO] Создана суммаризация для сообщений {start_msg_id}-{end_msg_id}")


def get_all_summaries(user_id: int) -> List[str]:
    """Возвращает все суммаризации пользователя в хронологическом порядке."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT summary_text FROM summaries
        WHERE user_id = ?
        ORDER BY created_at ASC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]


def get_messages_for_summary(user_id: int, limit: int = 30) -> Tuple[List[Dict], int, int]:
    """
    Возвращает последние N сообщений для создания суммаризации.
    Возвращает: (messages, start_id, end_id)
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, role, content FROM chat_history
        WHERE user_id = ?
        ORDER BY timestamp DESC LIMIT ?
    """, (user_id, limit))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return [], 0, 0

    # Разворачиваем (были в обратном порядке)
    rows = list(reversed(rows))

    messages = [{"role": row[1], "content": row[2]} for row in rows]
    start_id = rows[0][0]
    end_id = rows[-1][0]

    return messages, start_id, end_id


def count_user_messages(user_id: int) -> int:
    """Возвращает общее количество сообщений пользователя в истории."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM chat_history
        WHERE user_id = ? AND role = 'user'
    """, (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count
