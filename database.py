# database.py
# Асинхронный модуль для работы с SQLite (aiosqlite).
# Хранит историю диалогов, тест Бека, подписки, суммаризации, профили,
# рефералов, сессии и глобальный счётчик сообщений ИИ (тестовый режим).

import aiosqlite
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple

DB_NAME = "dialog_history.db"

# -------------------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ (АСИНХРОННАЯ) С МИГРАЦИЯМИ
# -------------------------------------------------------------------
async def init_db() -> None:
    """
    Создаёт все необходимые таблицы, если их ещё нет.
    Старые таблицы message_limits и global_stats (если были) останутся,
    но новые версии будут созданы заново при необходимости.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        # Таблица истории диалогов (сообщения пользователя и ИИ)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,              -- 'user' или 'assistant'
                content TEXT,
                timestamp TIMESTAMP
            )
        """)
        # Индекс для быстрого поиска по пользователю
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON chat_history(user_id)")

        # Таблица результатов теста Бека (опросник депрессии)
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

        # Таблица суммаризаций (выжимки истории диалогов)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                start_message_id INTEGER,   -- с какого сообщения начата суммаризация
                end_message_id INTEGER,     -- по какое сообщение
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
                custom_name TEXT,           -- устаревшее поле, больше не используется
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                username TEXT
            )
        """)

        # МИГРАЦИЯ: добавляем столбец username, если его ещё нет (для старых БД)
        cursor = await conn.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        if 'username' not in column_names:
            await conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
            print("[MIGRATION] Столбец 'username' добавлен в таблицу 'users'")

        # Таблица реферальной программы
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inviter_id INTEGER,
                invited_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                bonus_given BOOLEAN DEFAULT 0,   -- был ли начислен бонус пригласившему
                UNIQUE(invited_id)               -- один пользователь может быть приглашён только раз
            )
        """)

        # Таблица сессий (подсчёт количества завершённых диалогов)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                started_at TIMESTAMP,
                ended_at TIMESTAMP,
                message_count INTEGER DEFAULT 0
            )
        """)

        # Таблица подписок (Premium-доступ)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                is_premium BOOLEAN DEFAULT 0,
                expires_at TIMESTAMP
            )
        """)

        # ТАБЛИЦА ГЛОБАЛЬНОГО СЧЁТЧИКА СООБЩЕНИЙ ИИ (для тестового режима)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS global_stats (
                key TEXT PRIMARY KEY,        -- например, 'total_ai_messages'
                value INTEGER
            )
        """)

        await conn.commit()


# -------------------------------------------------------------------
# ИСТОРИЯ ДИАЛОГОВ
# -------------------------------------------------------------------
async def save_message(user_id: int, role: str, content: str) -> None:
    """Сохраняет одно сообщение (пользователя или ассистента) в историю."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO chat_history (user_id, role, content, timestamp)
            VALUES (?, ?, ?, ?)
        """, (user_id, role, content, datetime.now()))
        await conn.commit()


async def get_recent_history(user_id: int, limit: int = 20) -> List[Dict[str, str]]:
    """
    Возвращает последние N сообщений пользователя в формате
    [{"role": "user/assistant", "content": "текст"}, ...] (старые → новые).
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


async def get_user_bdi_results(user_id: int, limit: int = 10) -> List[Dict]:
    """Возвращает последние N результатов теста Бека для пользователя."""
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
# ПОДПИСКИ (PREMIUM-ДОСТУП)
# -------------------------------------------------------------------
async def activate_subscription(user_id: int, days: int) -> None:
    """Активирует или продлевает подписку на указанное количество дней."""
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
    """Проверяет, активна ли подписка у пользователя."""
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
                    # Подписка истекла — деактивируем
                    await deactivate_subscription(user_id)
                    return False
            except ValueError:
                pass
        return True


async def deactivate_subscription(user_id: int) -> None:
    """Деактивирует подписку (is_premium = 0)."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            UPDATE subscriptions SET is_premium = 0 WHERE user_id = ?
        """, (user_id,))
        await conn.commit()


async def get_subscription_days_left(user_id: int) -> int | None:
    """Возвращает количество оставшихся дней подписки или None, если подписка не активна."""
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
# СУММАРИЗАЦИЯ
# -------------------------------------------------------------------
async def save_summary(user_id: int, start_msg_id: int, end_msg_id: int, summary_text: str) -> None:
    """Сохраняет суммаризацию для указанного диапазона сообщений."""
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
    Возвращает: (список сообщений, id первого, id последнего)
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
# СТАТИСТИКА ДЛЯ АДМИН-ПАНЕЛИ
# -------------------------------------------------------------------
async def get_total_users() -> int:
    """Возвращает количество уникальных пользователей, когда-либо отправлявших сообщения."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT COUNT(DISTINCT user_id) FROM chat_history")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_active_users_today() -> int:
    """Пользователи, отправившие хотя бы одно сообщение сегодня."""
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT COUNT(DISTINCT user_id) FROM chat_history
            WHERE DATE(timestamp) = ?
        """, (today,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_total_messages_today() -> int:
    """Общее количество сообщений от пользователей сегодня."""
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT COUNT(*) FROM chat_history
            WHERE DATE(timestamp) = ? AND role = 'user'
        """, (today,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_all_user_ids() -> List[int]:
    """Список всех user_id из таблицы users (для рассылки)."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT user_id FROM users")
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


# -------------------------------------------------------------------
# ПРОФИЛИ ПОЛЬЗОВАТЕЛЕЙ
# -------------------------------------------------------------------
async def save_user_profile(user_id: int, telegram_name: str, custom_name: str | None, username: str | None) -> None:
    """Сохраняет или обновляет профиль пользователя (имя, username)."""
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
    """Возвращает custom_name (устаревшее)."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute(
            "SELECT custom_name FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def get_all_users(limit: int = 50, offset: int = 0) -> List[Dict]:
    """Список пользователей с пагинацией для админ-панели."""
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
    """Возвращает подробную информацию о пользователе, включая подписку."""
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
    """Поиск пользователей по ID (точное совпадение числа)."""
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
    """Добавляет реферальную связь. Возвращает True, если добавлена."""
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
    """Количество приглашённых пользователей."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT COUNT(*) FROM referrals WHERE inviter_id = ?
        """, (inviter_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def has_pending_referral_bonus(invited_id: int) -> bool:
    """Проверяет, есть ли невыплаченный бонус для пригласившего."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT inviter_id FROM referrals
            WHERE invited_id = ? AND bonus_given = 0
        """, (invited_id,))
        row = await cursor.fetchone()
        return row is not None


async def mark_referral_bonus_given(invited_id: int) -> None:
    """Отмечает бонус как выплаченный."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            UPDATE referrals SET bonus_given = 1 WHERE invited_id = ?
        """, (invited_id,))
        await conn.commit()


async def get_inviter_id(invited_id: int) -> int | None:
    """Возвращает ID пригласившего или None."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT inviter_id FROM referrals WHERE invited_id = ?
        """, (invited_id,))
        row = await cursor.fetchone()
        return row[0] if row else None


# -------------------------------------------------------------------
# СЕССИИ (ПОДСЧЁТ ДИАЛОГОВ)
# -------------------------------------------------------------------
async def start_session(user_id: int) -> int:
    """Начинает новую сессию, возвращает её ID."""
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
    """Завершает сессию; если сообщений нет — удаляет."""
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
    """Увеличивает счётчик сообщений в активной сессии."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            UPDATE sessions SET message_count = message_count + 1
            WHERE id = ?
        """, (session_id,))
        await conn.commit()


async def get_session_message_count(session_id: int) -> int:
    """Текущее количество сообщений в сессии."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT message_count FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_total_sessions(user_id: int) -> int:
    """Количество завершённых сессий пользователя."""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("""
            SELECT COUNT(*) FROM sessions
            WHERE user_id = ? AND ended_at IS NOT NULL
        """, (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0


# -------------------------------------------------------------------
# ГЛОБАЛЬНЫЙ СЧЁТЧИК СООБЩЕНИЙ ИИ (ТЕСТОВЫЙ РЕЖИМ)
# -------------------------------------------------------------------
async def increment_global_message_count() -> int:
    """
    Увеличивает счётчик успешных ответов ИИ на 1 и возвращает новое значение.
    Используется для тестового режима с лимитом запросов.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO global_stats (key, value) VALUES ('total_ai_messages', 1)
            ON CONFLICT(key) DO UPDATE SET value = value + 1
        """)
        await conn.commit()
        cursor = await conn.execute("SELECT value FROM global_stats WHERE key = 'total_ai_messages'")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_global_message_count() -> int:
    """
    Возвращает текущее значение глобального счётчика (общее количество ответов ИИ).
    Если запись отсутствует, возвращает 0.
    """
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.execute("SELECT value FROM global_stats WHERE key = 'total_ai_messages'")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def reset_global_message_counter() -> None:
    """Сбрасывает глобальный счётчик в 0 (удобно для нового тестового цикла)."""
    async with aiosqlite.connect(DB_NAME) as conn:
        await conn.execute("""
            INSERT INTO global_stats (key, value) VALUES ('total_ai_messages', 0)
            ON CONFLICT(key) DO UPDATE SET value = 0
        """)
        await conn.commit()
