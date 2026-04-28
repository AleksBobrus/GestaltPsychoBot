import aiosqlite
import asyncio
from database import get_all_users

async def check():
    async with aiosqlite.connect("dialog_history.db") as conn:
        cursor = await conn.execute("SELECT * FROM users")
        rows = await cursor.fetchall()
        print("Все записи в users:", rows)

async def check2():
    users = await get_all_users()
    print("get_all_users вернул:", users)

asyncio.run(check())
# asyncio.run(check2())
