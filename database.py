# database.py
# Асинхронный модуль для работы с SQLite (aiosqlite).
# Сохраняет всю функциональность: историю диалогов, тест Бека, лимиты, суммаризации,
# профили пользователей.

import aiosqlite
from datetime import datetime, date
from typing import List, Dict, Tuple

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

        # НОВАЯ ТАБЛИЦА: профили пользователей (имя из Telegram и кастомное имя)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                telegram_name TEXT,
                custom_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

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


async def try_increment_and_check_limit(user_id: int, limit: int = 20) -> Tuple[bool, int]:
    """
    Атомарно проверяет, не превышен ли лимит, и увеличивает счётчик.
    Возвращает:
        (True, new_count) – если сообщение разрешено,
        (False, current_count) – если лимит уже исчерпан.
    """
    today_str = date.today().isoformat()
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = await conn.execute(
                "SELECT daily_count, reset_date FROM message_limits WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()

            if row:
                count, reset_date = row
                if reset_date == today_str:
                    if count >= limit:
                        await conn.commit()
                        return False, count
                    new_count = count + 1
                else:
                    new_count = 1
                await conn.execute(
                    "UPDATE message_limits SET daily_count = ?, reset_date = ? WHERE user_id = ?",
                    (new_count, today_str, user_id)
                )
            else:
                new_count = 1
                await conn.execute(
                    "INSERT INTO message_limits (user_id, daily_count, reset_date) VALUES (?, ?, ?)",
                    (user_id, new_count, today_str)
                )

            await conn.commit()
            return True, new_count
        except Exception:
            await conn.rollback()
            raise


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

    rows = list(reversed(rows))
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


# -------------------------------------------------------------------
# СТАТИСТИКА (ДЛЯ АДМИН-ПАНЕЛИ)
# -------------------------------------------------------------------
async def get_total_users() -> int:
    """Возвращает общее количество уникальных пользователей (из chat_history)."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT COUNT(DISTINCT user_id) FROM chat_history")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_user_info(user_id: int) -> dict:
    """Возвращает информацию о пользователе: первое сообщение, всего сообщений, лимит на сегодня."""
    async with aiosqlite.connect(DB_NAME) as conn:
        # Дата первого сообщения
        cursor = await conn.execute(
            "SELECT MIN(timestamp) FROM chat_history WHERE user_id = ?",
            (user_id,)
        )
        first_row = await cursor.fetchone()
        first_seen = first_row[0] if first_row and first_row[0] else None

        # Общее количество сообщений пользователя (роль 'user')
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM chat_history WHERE user_id = ? AND role = 'user'",
            (user_id,)
        )
        total_row = await cursor.fetchone()
        total_messages = total_row[0] if total_row else 0

    # Лимит на сегодня (используем уже существующую функцию)
    today_count = await get_message_count_today(user_id)

    return {
        "user_id": user_id,
        "first_seen": first_seen,
        "total_messages": total_messages,
        "messages_today": today_count,
        "limit": 20,
        "remaining": max(0, 20 - today_count)
    }


async def reset_user_limit(user_id: int) -> None:
    """Сбрасывает дневной лимит для пользователя (удаляет запись из message_limits)."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("DELETE FROM message_limits WHERE user_id = ?", (user_id,))
        await conn.commit()


async def get_active_users_today() -> int:
    """Возвращает количество пользователей, отправивших сообщения сегодня."""
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT COUNT(DISTINCT user_id) FROM chat_history
            WHERE DATE(timestamp) = ?
        """, (today,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_total_messages_today() -> int:
    """Возвращает общее количество сообщений за сегодня."""
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT COUNT(*) FROM chat_history
            WHERE DATE(timestamp) = ? AND role = 'user'
        """, (today,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_all_user_ids() -> List[int]:
    """Возвращает список всех уникальных user_id для рассылки."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT DISTINCT user_id FROM chat_history")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


# -------------------------------------------------------------------
# ПРОФИЛИ ПОЛЬЗОВАТЕЛЕЙ (ДЛЯ АДМИН-ПАНЕЛИ)
# -------------------------------------------------------------------
async def save_user_profile(user_id: int, telegram_name: str, custom_name: str) -> None:
    """Сохраняет или обновляет имя пользователя."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO users (user_id, telegram_name, custom_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                telegram_name = excluded.telegram_name,
                custom_name = excluded.custom_name
        """, (user_id, telegram_name, custom_name))
        await conn.commit()


async def get_user_custom_name(user_id: int) -> str | None:
    """Возвращает сохранённое имя пользователя."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute(
            "SELECT custom_name FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def get_all_users(limit: int = 50, offset: int = 0) -> List[Dict]:
    """Возвращает список пользователей с пагинацией."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT user_id, telegram_name, custom_name, created_at
            FROM users
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        rows = await cursor.fetchall()
        return [
            {
                "user_id": row[0],
                "telegram_name": row[1],
                "custom_name": row[2],
                "created_at": row[3]
            }
            for row in rows
        ]


async def get_total_users_count() -> int:
    """Общее количество записей в таблице users."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0] if row else 0
