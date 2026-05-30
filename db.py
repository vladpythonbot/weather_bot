# db.py
import os
from pathlib import Path

import aiosqlite


DB_NAME = os.getenv("DB_PATH", str(Path(__file__).with_name("reminders.db")))

async def init_db():
    Path(DB_NAME).parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS reminders (
                user_id INTEGER PRIMARY KEY,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                hour INTEGER NOT NULL,
                minute INTEGER NOT NULL
            )
        """)
        await db.commit()


async def save_location(user_id: int, lat: float, lng: float, hour: int, minute: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO reminders (user_id, lat, lng, hour, minute)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                lat = excluded.lat,
                lng = excluded.lng,
                hour = excluded.hour,
                minute = excluded.minute
        """, (user_id, lat, lng, hour, minute))
        await db.commit()

async def get_user_location(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT lat, lng FROM reminders WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        if row:
            return row[0], row[1]  # lat, lng
        return None, None

async def get_reminder(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT lat, lng, hour, minute FROM reminders WHERE user_id = ?",
            (user_id,)
        )


        result = await cursor.fetchone()
        return result


async def get_all_reminders():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT user_id, lat, lng, hour, minute
            FROM reminders
        """)
        return await cursor.fetchall()
