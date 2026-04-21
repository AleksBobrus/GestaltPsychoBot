# database.py
# Асинхронный модуль для работы с SQLite (aiosqlite).
# Хранит историю диалогов, тест Бека, баланс сообщений (новая модель), суммаризации, профили.
# Проведена миграция: daily_count → balance, удалён reset_date.

import aiosqlite
from datetime import datetime, date
from typing import List, Dict, Tuple

DB_NAME = "dialog_history.db"

# -------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ (АСИНХРОННАЯ) С МИГРАЦИЕЙ
# -------------------------------------------------------------------
async def init_db() -> None:
    """
    Создаёт таблицы, если их нет, и выполняет миграцию для перехода на баланс.
    Вызывается один раз при старте бота.
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

        # Таблица баланса сообщений (ранее message_limits)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS message_limits (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0
            )
        """)

        # МИГРАЦИЯ: если существует столбец daily_count, переименовываем в balance
        cursor = await conn.execute("PRAGMA table_info(message_limits)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]

        if 'daily_count' in column_names:
            # Переименовываем daily_count в balance
            await conn.execute("ALTER TABLE message_limits RENAME COLUMN daily_count TO balance")
            print("[MIGRATION] Столбец 'daily_count' переименован в 'balance'")

        # Если остался столбец reset_date – он больше не используется, но удалить его в SQLite сложно,
        # поэтому просто игнорируем. При желании можно пересоздать таблицу, но это рискованно.
        # В новых версиях таблица создаётся без reset_date.

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

        # Таблица профилей пользователей (создаём с полями в правильном порядке)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                telegram_name TEXT,
                custom_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                username TEXT
            )
        """)

        # МИГРАЦИЯ: добавляем столбец username, если он отсутствует (для старых БД)
        cursor = await conn.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]

        if 'username' not in column_names:
            await conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
            print("[MIGRATION] Столбец 'username' добавлен в таблицу 'users'")

        await conn.commit()


# -------------------------------------------------------------------
# ИСТОРИЯ ДИАЛОГОВ (без изменений)
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
    return [{"role": role, "content": content} for role, content in reversed(rows)]


async def clear_user_history(user_id: int) -> None:
    """Удаляет всю историю диалога пользователя."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
        await conn.commit()


# -------------------------------------------------------------------
# ТЕСТ БЕКА (без изменений)
# -------------------------------------------------------------------
async def save_bdi_result(user_id: int, score: int, interpretation: str) -> None:
    """Сохраняет результат теста Бека."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO bdi_results (user_id, date, score, interpretation)
            VALUES (?, ?, ?, ?)
        """, (user_id, datetime.now(), score, interpretation))
        await conn.commit()


async def get_user_bdi_results(user_id: int, limit: int = 10) -> List[Dict]:
    """Возвращает последние результаты теста Бека."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT date, score, interpretation FROM bdi_results
            WHERE user_id = ?
            ORDER BY date DESC LIMIT ?
        """, (user_id, limit))
        rows = await cursor.fetchall()
        return [
            {"date": row[0], "score": row[1], "interpretation": row[2]}
            for row in rows
        ]


# -------------------------------------------------------------------
# БАЛАНС СООБЩЕНИЙ (НОВАЯ МОДЕЛЬ)
# -------------------------------------------------------------------
async def get_balance(user_id: int) -> int:
    """Возвращает текущий баланс сообщений пользователя."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute(
            "SELECT balance FROM message_limits WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def decrement_balance(user_id: int) -> int:
    """
    Уменьшает баланс пользователя на 1, если он > 0.
    Возвращает новый баланс.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            UPDATE message_limits SET balance = balance - 1
            WHERE user_id = ? AND balance > 0
        """, (user_id,))
        await conn.commit()
        return await get_balance(user_id)


async def try_decrement_balance(user_id: int) -> Tuple[bool, int]:
    """
    Проверяет, что баланс > 0, и если да – уменьшает на 1 атомарно.
    Возвращает (True, new_balance) или (False, current_balance).
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = await conn.execute(
                "SELECT balance FROM message_limits WHERE user_id = ?",
                (user_id,)
            )
            row = await cursor.fetchone()
            if not row:
                # Пользователь ещё не имеет записи – баланс 0
                await conn.commit()
                return False, 0
            balance = row[0]
            if balance <= 0:
                await conn.commit()
                return False, balance
            # Уменьшаем на 1
            await conn.execute(
                "UPDATE message_limits SET balance = balance - 1 WHERE user_id = ?",
                (user_id,)
            )
            await conn.commit()
            return True, balance - 1
        except Exception:
            await conn.rollback()
            raise


async def has_balance(user_id: int) -> bool:
    """Проверяет, есть ли у пользователя сообщения на балансе (>0)."""
    balance = await get_balance(user_id)
    return balance > 0


async def add_balance(user_id: int, amount: int) -> int:
    """Добавляет указанное количество сообщений на баланс пользователя."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO message_limits (user_id, balance)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?
        """, (user_id, amount, amount))
        await conn.commit()
        return await get_balance(user_id)


async def reset_balance_to_20(user_id: int) -> None:
    """Устанавливает баланс пользователя равным 20 (для админ-панели)."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO message_limits (user_id, balance)
            VALUES (?, 20)
            ON CONFLICT(user_id) DO UPDATE SET balance = 20
        """, (user_id,))
        await conn.commit()


# -------------------------------------------------------------------
# СУММАРИЗАЦИЯ (без изменений)
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
    """Возвращает список всех уникальных user_id для рассылки (из таблицы users)."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT user_id FROM users")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


# -------------------------------------------------------------------
# ПРОФИЛИ ПОЛЬЗОВАТЕЛЕЙ (ДЛЯ АДМИН-ПАНЕЛИ)
# -------------------------------------------------------------------
async def save_user_profile(user_id: int, telegram_name: str, custom_name: str | None, username: str | None) -> None:
    """
    Сохраняет или обновляет профиль пользователя (включая username).
    custom_name может быть None (при первом сохранении).
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO users (user_id, telegram_name, custom_name, username)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                telegram_name = excluded.telegram_name,
                custom_name = COALESCE(excluded.custom_name, custom_name),
                username = excluded.username
        """, (user_id, telegram_name, custom_name, username))
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
    """
    Возвращает список пользователей с пагинацией.
    Явно указываем порядок полей: user_id, telegram_name, custom_name, created_at, username.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT user_id, telegram_name, custom_name, created_at, username
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
                "created_at": row[3],
                "username": row[4]
            }
            for row in rows
        ]


async def get_total_users_count() -> int:
    """Общее количество записей в таблице users."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_user_info(user_id: int) -> dict:
    """
    Возвращает подробную информацию о пользователе:
    - telegram_name, username, created_at (из таблицы users)
    - total_messages (из chat_history)
    - balance (из message_limits)
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT telegram_name, username, created_at
            FROM users
            WHERE user_id = ?
        """, (user_id,))
        profile_row = await cursor.fetchone()

        if profile_row:
            telegram_name, username, created_at = profile_row
        else:
            telegram_name, username, created_at = None, None, None

        cursor = await conn.execute("""
            SELECT COUNT(*) FROM chat_history
            WHERE user_id = ? AND role = 'user'
        """, (user_id,))
        total_row = await cursor.fetchone()
        total_messages = total_row[0] if total_row else 0

    balance = await get_balance(user_id)
    return {
        "user_id": user_id,
        "telegram_name": telegram_name,
        "username": username,
        "created_at": created_at,
        "total_messages": total_messages,
        "balance": balance
    }


async def search_users(query: str) -> List[Dict]:
    """
    Ищет пользователей только по ID (точное совпадение числа).
    Возвращает список словарей с ключами user_id, telegram_name, custom_name, username.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        try:
            user_id = int(query)
            cursor = await conn.execute("""
                SELECT user_id, telegram_name, custom_name, created_at, username
                FROM users
                WHERE user_id = ?
            """, (user_id,))
            rows = await cursor.fetchall()
            if rows:
                return [
                    {
                        "user_id": row[0],
                        "telegram_name": row[1],
                        "custom_name": row[2],
                        "username": row[4]   # username теперь на позиции 4
                    }
                    for row in rows
                ]
        except ValueError:
            return []
    return []
