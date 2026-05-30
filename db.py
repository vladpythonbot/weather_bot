# db.py
import os
from dataclasses import dataclass
from pathlib import Path

import aiosqlite


DB_NAME = os.getenv("DB_PATH", str(Path(__file__).with_name("reminders.db")))


@dataclass(frozen=True)
class Reminder:
    user_id: int
    lat: float
    lng: float
    hour: int
    minute: int


async def init_db():
    Path(DB_NAME).parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                user_id INTEGER PRIMARY KEY,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                hour INTEGER NOT NULL,
                minute INTEGER NOT NULL
            )
        """)
        await db.commit()


async def save_reminder(user_id: int, lat: float, lng: float, hour: int, minute: int):
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


async def get_reminder(user_id: int) -> Reminder | None:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT user_id, lat, lng, hour, minute
            FROM reminders
            WHERE user_id = ?
        """, (user_id,))
        row = await cursor.fetchone()

    return Reminder(*row) if row else None


async def get_user_location(user_id: int) -> tuple[float | None, float | None]:
    reminder = await get_reminder(user_id)
    if not reminder:
        return None, None

    return reminder.lat, reminder.lng


async def get_all_reminders() -> list[Reminder]:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT user_id, lat, lng, hour, minute
            FROM reminders
        """)
        rows = await cursor.fetchall()

    return [Reminder(*row) for row in rows]


# Backward-compatible name for older imports.
save_location = save_reminder
