
# database.py – работа с SQLite для хранения пользователей и истории сообщений

# database.py – полная версия с поддержкой теста Бека

import sqlite3
from datetime import datetime
from typing import List, Tuple, Optional

def init_db() -> None:
    """Создаёт все необходимые таблицы, если их нет."""
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    # Таблица пользователей
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            first_seen TIMESTAMP
        )
    """)
    # Таблица истории сообщений
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp TIMESTAMP
        )
    """)
    # Таблица результатов теста Бека
    c.execute("""
        CREATE TABLE IF NOT EXISTS bdi_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TIMESTAMP,
            score INTEGER,
            interpretation TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_user(user_id: int, first_name: str, last_name: str, username: str) -> None:
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO users (user_id, first_name, last_name, username, first_seen)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, first_name, last_name, username, datetime.now()))
    conn.commit()
    conn.close()

def save_message(user_id: int, role: str, content: str) -> None:
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO messages (user_id, role, content, timestamp)
        VALUES (?, ?, ?, ?)
    """, (user_id, role, content, datetime.now()))
    conn.commit()
    conn.close()

def get_recent_history(user_id: int, limit: int = 10) -> List[Tuple[str, str]]:
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("""
        SELECT role, content FROM messages
        WHERE user_id = ?
        ORDER BY timestamp DESC LIMIT ?
    """, (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return list(reversed(rows))

def save_bdi_result(user_id: int, score: int, interpretation: str) -> None:
    """Сохраняет результат теста Бека в базу."""
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO bdi_results (user_id, date, score, interpretation)
        VALUES (?, ?, ?, ?)
    """, (user_id, datetime.now(), score, interpretation))
    conn.commit()
    conn.close()

def get_last_bdi_result(user_id: int) -> Optional[Tuple[int, str, str]]:
    """Возвращает последний результат: (score, interpretation, date) или None."""
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("""
        SELECT score, interpretation, date FROM bdi_results
        WHERE user_id = ?
        ORDER BY date DESC LIMIT 1
    """, (user_id,))
    row = c.fetchone()
    conn.close()
    return row
