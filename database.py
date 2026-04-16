# database.py
# Асинхронный модуль для работы с SQLite (aiosqlite).
# Сохраняет всю функциональность: историю диалогов, тест Бека, лимиты, суммаризации.

import aiosqlite
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple

DB_NAME = "dialog_history.db"

# -------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ (АСИНХРОННАЯ)
# -------------------------------------------------------------------
async def init_db() -> None:
    """
    Создаёт таблицы, если их нет. Вызывается один раз при старте бота.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        # Таблица истории диалогов
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                timestamp TIMESTAMP
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON chat_history(user_id)")

        # Таблица результатов теста Бека
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bdi_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TIMESTAMP,
                score INTEGER,
                interpretation TEXT
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_bdi_user_id ON bdi_results(user_id)")

        # Таблица лимитов сообщений
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS message_limits (
                user_id INTEGER PRIMARY KEY,
                daily_count INTEGER DEFAULT 0,
                reset_date TEXT
            )
        """)

        # Таблица суммаризаций
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                start_message_id INTEGER,
                end_message_id INTEGER,
                summary_text TEXT,
                created_at TIMESTAMP
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_summaries_user_id ON summaries(user_id)")

        await conn.commit()


# -------------------------------------------------------------------
# ИСТОРИЯ ДИАЛОГОВ
# -------------------------------------------------------------------
async def save_message(user_id: int, role: str, content: str) -> None:
    """Асинхронно сохраняет одно сообщение."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO chat_history (user_id, role, content, timestamp)
            VALUES (?, ?, ?, ?)
        """, (user_id, role, content, datetime.now()))
        await conn.commit()


async def get_recent_history(user_id: int, limit: int = 20) -> List[Dict[str, str]]:
    """
    Возвращает последние `limit` сообщений пользователя.
    Результат: список словарей [{"role": "user", "content": "..."}, ...]
    в хронологическом порядке (старые → новые).
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT role, content FROM chat_history
            WHERE user_id = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (user_id, limit))
        rows = await cursor.fetchall()
    # rows приходят от новых к старым, переворачиваем
    return [{"role": role, "content": content} for role, content in reversed(rows)]


async def clear_user_history(user_id: int) -> None:
    """Удаляет всю историю диалога пользователя."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
        await conn.commit()


# -------------------------------------------------------------------
# ТЕСТ БЕКА
# -------------------------------------------------------------------
async def save_bdi_result(user_id: int, score: int, interpretation: str) -> None:
    """Сохраняет результат теста Бека."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO bdi_results (user_id, date, score, interpretation)
            VALUES (?, ?, ?, ?)
        """, (user_id, datetime.now(), score, interpretation))
        await conn.commit()


# -------------------------------------------------------------------
# ЛИМИТЫ СООБЩЕНИЙ
# -------------------------------------------------------------------
async def get_message_count_today(user_id: int) -> int:
    """Возвращает количество сообщений, отправленных пользователем сегодня."""
    today_str = date.today().isoformat()
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute(
            "SELECT daily_count, reset_date FROM message_limits WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
    if not row:
        return 0
    count, reset_date = row
    return count if reset_date == today_str else 0


async def increment_message_count(user_id: int) -> int:
    """
    Увеличивает счётчик сообщений на 1.
    Если запись отсутствует или reset_date не сегодня, сбрасывает на 1.
    Возвращает новое значение счётчика.
    """
    today_str = date.today().isoformat()
    async with aiosqlite.connect(DB_NAME) as conn:
        # UPSERT с условным сбросом
        await conn.execute("""
            INSERT INTO message_limits (user_id, daily_count, reset_date)
            VALUES (?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                daily_count = CASE
                    WHEN reset_date = ? THEN daily_count + 1
                    ELSE 1
                END,
                reset_date = ?
        """, (user_id, today_str, today_str, today_str))
        await conn.commit()

        cursor = await conn.execute(
            "SELECT daily_count FROM message_limits WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 1


async def can_send_message(user_id: int, limit: int = 20) -> bool:
    """Проверяет, не превышен ли дневной лимит."""
    count = await get_message_count_today(user_id)
    return count < limit


# -------------------------------------------------------------------
# СУММАРИЗАЦИЯ
# -------------------------------------------------------------------
async def save_summary(user_id: int, start_msg_id: int, end_msg_id: int, summary_text: str) -> None:
    """Сохраняет суммаризацию диалога."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO summaries (user_id, start_message_id, end_message_id, summary_text, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, start_msg_id, end_msg_id, summary_text, datetime.now()))
        await conn.commit()


async def get_all_summaries(user_id: int) -> List[str]:
    """Возвращает все суммаризации пользователя в хронологическом порядке."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT summary_text FROM summaries
            WHERE user_id = ?
            ORDER BY created_at ASC
        """, (user_id,))
        rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def get_messages_for_summary(user_id: int, limit: int = 30) -> Tuple[List[Dict], int, int]:
    """
    Возвращает последние N сообщений для создания суммаризации.
    Возвращает: (messages, start_id, end_id)
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT id, role, content FROM chat_history
            WHERE user_id = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (user_id, limit))
        rows = await cursor.fetchall()

    if not rows:
        return [], 0, 0

    rows = list(reversed(rows))  # от старых к новым
    messages = [{"role": row[1], "content": row[2]} for row in rows]
    start_id = rows[0][0]
    end_id = rows[-1][0]
    return messages, start_id, end_id


async def count_user_messages(user_id: int) -> int:
    """Общее количество сообщений пользователя (роль 'user')."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT COUNT(*) FROM chat_history
            WHERE user_id = ? AND role = 'user'
        """, (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0
