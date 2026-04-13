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

# database.py – добавляем в конец файла

def init_db() -> None:
    # ... существующий код для chat_history ...
    # Добавим таблицу bdi_results
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
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
    conn.commit()
    conn.close()

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

def get_user_bdi_results(user_id: int, limit: int = 10) -> List[Dict]:
    """Возвращает последние limit результатов теста для пользователя."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        SELECT date, score, interpretation FROM bdi_results
        WHERE user_id = ?
        ORDER BY date DESC LIMIT ?
    """, (user_id, limit))
    rows = c.fetchall()
    conn.close()
    results = []
    for row in rows:
        results.append({
            "date": row[0],
            "score": row[1],
            "interpretation": row[2]
        })
    return results

def get_bdi_statistics(user_id: int) -> Dict:
    """Возвращает статистику по тестам пользователя."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), AVG(score), MAX(score), MIN(score) FROM bdi_results WHERE user_id = ?", (user_id,))
    count, avg, max_score, min_score = c.fetchone()
    c.execute("SELECT score FROM bdi_results WHERE user_id = ? ORDER BY date DESC LIMIT 1", (user_id,))
    last = c.fetchone()
    conn.close()
    return {
        "count": count or 0,
        "avg": round(avg, 1) if avg else 0,
        "max": max_score or 0,
        "min": min_score or 0,
        "last": last[0] if last else None
    }