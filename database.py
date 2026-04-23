# database.py
# Асинхронный модуль для работы с SQLite (aiosqlite).
# Хранит историю диалогов, тест Бека, суммаризации, профили, рефералы, сессии и подписки.

import aiosqlite
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple

DB_NAME = "dialog_history.db"

# -------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ (АСИНХРОННАЯ) С МИГРАЦИЯМИ
# -------------------------------------------------------------------
async def init_db() -> None:
    """
    Создаёт все необходимые таблицы, если их нет.
    Старые таблицы message_limits и global_stats больше не используются.
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

        # Таблица профилей пользователей
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                telegram_name TEXT,
                custom_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                username TEXT
            )
        """)

        # МИГРАЦИЯ: добавляем столбец username, если он отсутствует
        cursor = await conn.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        if 'username' not in column_names:
            await conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
            print("[MIGRATION] Столбец 'username' добавлен в таблицу 'users'")

        # Таблица рефералов
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inviter_id INTEGER,
                invited_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                bonus_given BOOLEAN DEFAULT 0,
                UNIQUE(invited_id)
            )
        """)

        # Таблица сессий (подсчёт количества диалогов) – пока оставляем, но в ЛК уберём
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                started_at TIMESTAMP,
                ended_at TIMESTAMP,
                message_count INTEGER DEFAULT 0
            )
        """)

        # НОВАЯ ТАБЛИЦА: подписки
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                is_premium BOOLEAN DEFAULT 0,
                expires_at TIMESTAMP
            )
        """)

        await conn.commit()


# -------------------------------------------------------------------
# ИСТОРИЯ ДИАЛОГОВ (без изменений)
# -------------------------------------------------------------------
async def save_message(user_id: int, role: str, content: str) -> None:
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO chat_history (user_id, role, content, timestamp)
            VALUES (?, ?, ?, ?)
        """, (user_id, role, content, datetime.now()))
        await conn.commit()


async def get_recent_history(user_id: int, limit: int = 20) -> List[Dict[str, str]]:
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT role, content FROM chat_history
            WHERE user_id = ?
            ORDER BY timestamp DESC LIMIT ?
        """, (user_id, limit))
        rows = await cursor.fetchall()
    return [{"role": role, "content": content} for role, content in reversed(rows)]


async def clear_user_history(user_id: int) -> None:
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
        await conn.commit()


# -------------------------------------------------------------------
# ТЕСТ БЕКА (без изменений)
# -------------------------------------------------------------------
async def save_bdi_result(user_id: int, score: int, interpretation: str) -> None:
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO bdi_results (user_id, date, score, interpretation)
            VALUES (?, ?, ?, ?)
        """, (user_id, datetime.now(), score, interpretation))
        await conn.commit()


async def get_user_bdi_results(user_id: int, limit: int = 10) -> List[Dict]:
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
# ПОДПИСКИ (НОВАЯ МОДЕЛЬ)
# -------------------------------------------------------------------
async def activate_subscription(user_id: int, days: int) -> None:
    """
    Активирует Premium-подписку на указанное количество дней.
    Если подписка уже есть – добавляет дни к текущему expires_at.
    """
    expires_at = datetime.now() + timedelta(days=days)
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO subscriptions (user_id, is_premium, expires_at)
            VALUES (?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                is_premium = 1,
                expires_at = datetime(expires_at, '+' || ? || ' days')
        """, (user_id, expires_at, days))
        await conn.commit()


async def is_premium_active(user_id: int) -> bool:
    """
    Проверяет, активна ли Premium-подписка у пользователя.
    Возвращает True, если is_premium = 1 и expires_at > текущего времени.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT is_premium, expires_at FROM subscriptions WHERE user_id = ?
        """, (user_id,))
        row = await cursor.fetchone()
        if not row:
            return False
        is_premium, expires_at = row
        if not is_premium:
            return False
        if expires_at:
            try:
                exp = datetime.fromisoformat(expires_at)
                if exp < datetime.now():
                    # Подписка истекла – деактивируем
                    await deactivate_subscription(user_id)
                    return False
            except ValueError:
                pass
        return True


async def deactivate_subscription(user_id: int) -> None:
    """Деактивирует подписку пользователя (is_premium = 0)."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            UPDATE subscriptions SET is_premium = 0 WHERE user_id = ?
        """, (user_id,))
        await conn.commit()


async def get_subscription_days_left(user_id: int) -> int | None:
    """
    Возвращает количество дней, оставшихся до конца подписки.
    Если подписка неактивна или отсутствует, возвращает None.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT is_premium, expires_at FROM subscriptions WHERE user_id = ?
        """, (user_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        is_premium, expires_at = row
        if not is_premium or not expires_at:
            return None
        try:
            exp = datetime.fromisoformat(expires_at)
            now = datetime.now()
            if exp < now:
                await deactivate_subscription(user_id)
                return None
            return (exp - now).days
        except ValueError:
            return None


# -------------------------------------------------------------------
# СУММАРИЗАЦИЯ (без изменений)
# -------------------------------------------------------------------
async def save_summary(user_id: int, start_msg_id: int, end_msg_id: int, summary_text: str) -> None:
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO summaries (user_id, start_message_id, end_message_id, summary_text, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, start_msg_id, end_msg_id, summary_text, datetime.now()))
        await conn.commit()


async def get_all_summaries(user_id: int) -> List[str]:
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT summary_text FROM summaries
            WHERE user_id = ?
            ORDER BY created_at ASC
        """, (user_id,))
        rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def get_messages_for_summary(user_id: int, limit: int = 30) -> Tuple[List[Dict], int, int]:
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
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT COUNT(DISTINCT user_id) FROM chat_history")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_active_users_today() -> int:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT COUNT(DISTINCT user_id) FROM chat_history
            WHERE DATE(timestamp) = ?
        """, (today,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_total_messages_today() -> int:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT COUNT(*) FROM chat_history
            WHERE DATE(timestamp) = ? AND role = 'user'
        """, (today,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_all_user_ids() -> List[int]:
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT user_id FROM users")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


# -------------------------------------------------------------------
# ПРОФИЛИ ПОЛЬЗОВАТЕЛЕЙ
# -------------------------------------------------------------------
async def save_user_profile(user_id: int, telegram_name: str, custom_name: str | None, username: str | None) -> None:
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
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute(
            "SELECT custom_name FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def get_all_users(limit: int = 50, offset: int = 0) -> List[Dict]:
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
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_user_info(user_id: int) -> dict:
    """
    Возвращает подробную информацию о пользователе:
    - telegram_name, username, created_at (из таблицы users)
    - total_messages (из chat_history)
    - subscription_status (из subscriptions)
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

    # Получаем информацию о подписке
    days_left = await get_subscription_days_left(user_id)
    is_premium = days_left is not None

    return {
        "user_id": user_id,
        "telegram_name": telegram_name,
        "username": username,
        "created_at": created_at,
        "total_messages": total_messages,
        "is_premium": is_premium,
        "days_left": days_left
    }


async def search_users(query: str) -> List[Dict]:
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
                        "username": row[4]
                    }
                    for row in rows
                ]
        except ValueError:
            return []
    return []


# -------------------------------------------------------------------
# РЕФЕРАЛЬНАЯ СИСТЕМА
# -------------------------------------------------------------------
async def add_referral(inviter_id: int, invited_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as conn:
        try:
            await conn.execute("""
                INSERT INTO referrals (inviter_id, invited_id)
                VALUES (?, ?)
            """, (inviter_id, invited_id))
            await conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def get_referral_count(inviter_id: int) -> int:
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT COUNT(*) FROM referrals WHERE inviter_id = ?
        """, (inviter_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def has_pending_referral_bonus(invited_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT inviter_id FROM referrals
            WHERE invited_id = ? AND bonus_given = 0
        """, (invited_id,))
        row = await cursor.fetchone()
        return row is not None


async def mark_referral_bonus_given(invited_id: int) -> None:
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            UPDATE referrals SET bonus_given = 1 WHERE invited_id = ?
        """, (invited_id,))
        await conn.commit()


async def get_inviter_id(invited_id: int) -> int | None:
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT inviter_id FROM referrals WHERE invited_id = ?
        """, (invited_id,))
        row = await cursor.fetchone()
        return row[0] if row else None


# -------------------------------------------------------------------
# СЕССИИ (ОСТАВЛЕНЫ, НО В ЛК НЕ ОТОБРАЖАЮТСЯ)
# -------------------------------------------------------------------
async def start_session(user_id: int) -> int:
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            INSERT INTO sessions (user_id, started_at)
            VALUES (?, ?)
            RETURNING id
        """, (user_id, datetime.now()))
        row = await cursor.fetchone()
        await conn.commit()
        return row[0] if row else 0


async def end_session(session_id: int, message_count: int = 0) -> None:
    if message_count > 0:
        async with aiosqlite.connect(DB_NAME) as conn:
            await conn.execute("""
                UPDATE sessions
                SET ended_at = ?, message_count = ?
                WHERE id = ?
            """, (datetime.now(), message_count, session_id))
            await conn.commit()
    else:
        async with aiosqlite.connect(DB_NAME) as conn:
            await conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            await conn.commit()


async def increment_session_message_count(session_id: int) -> None:
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            UPDATE sessions SET message_count = message_count + 1
            WHERE id = ?
        """, (session_id,))
        await conn.commit()


async def get_session_message_count(session_id: int) -> int:
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT message_count FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_total_sessions(user_id: int) -> int:
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT COUNT(*) FROM sessions
            WHERE user_id = ? AND ended_at IS NOT NULL
        """, (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0
