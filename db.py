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
    city_name: str = "текущее место"
    wind_unit: str = "ms"
    show_details: bool = True
    schedule_days: str = "0,1,2,3,4,5,6"


async def init_db():
    Path(DB_NAME).parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                user_id INTEGER PRIMARY KEY,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                hour INTEGER NOT NULL,
                minute INTEGER NOT NULL,
                city_name TEXT NOT NULL DEFAULT 'текущее место',
                wind_unit TEXT NOT NULL DEFAULT 'ms',
                show_details INTEGER NOT NULL DEFAULT 1,
                schedule_days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6'
            )
        """)
        await ensure_column(db, "reminders", "city_name", "TEXT NOT NULL DEFAULT 'текущее место'")
        await ensure_column(db, "reminders", "wind_unit", "TEXT NOT NULL DEFAULT 'ms'")
        await ensure_column(db, "reminders", "show_details", "INTEGER NOT NULL DEFAULT 1")
        await ensure_column(db, "reminders", "schedule_days", "TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6'")
        await db.commit()


async def ensure_column(db, table: str, column: str, definition: str):
    cursor = await db.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in await cursor.fetchall()]

    if column not in columns:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


async def save_reminder(
    user_id: int,
    lat: float,
    lng: float,
    hour: int,
    minute: int,
    city_name: str | None = None,
    wind_unit: str | None = None,
    show_details: bool | None = None,
    schedule_days: str | None = None,
):
    current = await get_reminder(user_id)
    city_name = city_name or (current.city_name if current else "текущее место")
    wind_unit = wind_unit or (current.wind_unit if current else "ms")
    show_details = current.show_details if show_details is None and current else (True if show_details is None else show_details)
    schedule_days = schedule_days or (current.schedule_days if current else "0,1,2,3,4,5,6")

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO reminders (
                user_id, lat, lng, hour, minute, city_name, wind_unit, show_details, schedule_days
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                lat = excluded.lat,
                lng = excluded.lng,
                hour = excluded.hour,
                minute = excluded.minute,
                city_name = excluded.city_name,
                wind_unit = excluded.wind_unit,
                show_details = excluded.show_details,
                schedule_days = excluded.schedule_days
        """, (
            user_id, lat, lng, hour, minute, city_name, wind_unit, int(show_details), schedule_days,
        ))
        await db.commit()


async def update_preferences(
    user_id: int,
    wind_unit: str | None = None,
    show_details: bool | None = None,
    schedule_days: str | None = None,
):
    reminder = await get_reminder(user_id)
    if not reminder:
        return False

    await save_reminder(
        user_id=user_id,
        lat=reminder.lat,
        lng=reminder.lng,
        hour=reminder.hour,
        minute=reminder.minute,
        city_name=reminder.city_name,
        wind_unit=wind_unit or reminder.wind_unit,
        show_details=reminder.show_details if show_details is None else show_details,
        schedule_days=schedule_days or reminder.schedule_days,
    )
    return True


async def get_reminder(user_id: int) -> Reminder | None:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT
                user_id, lat, lng, hour, minute, city_name, wind_unit, show_details, schedule_days
            FROM reminders
            WHERE user_id = ?
        """, (user_id,))
        row = await cursor.fetchone()

    if not row:
        return None

    return Reminder(
        user_id=row[0],
        lat=row[1],
        lng=row[2],
        hour=row[3],
        minute=row[4],
        city_name=row[5] or "текущее место",
        wind_unit=row[6] or "ms",
        show_details=bool(row[7]),
        schedule_days=row[8] or "0,1,2,3,4,5,6",
    )


async def get_user_location(user_id: int) -> tuple[float | None, float | None]:
    reminder = await get_reminder(user_id)
    if not reminder:
        return None, None

    return reminder.lat, reminder.lng


async def get_all_reminders() -> list[Reminder]:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT
                user_id, lat, lng, hour, minute, city_name, wind_unit, show_details, schedule_days
            FROM reminders
        """)
        rows = await cursor.fetchall()

    return [
        Reminder(
            user_id=row[0],
            lat=row[1],
            lng=row[2],
            hour=row[3],
            minute=row[4],
            city_name=row[5] or "текущее место",
            wind_unit=row[6] or "ms",
            show_details=bool(row[7]),
            schedule_days=row[8] or "0,1,2,3,4,5,6",
        )
        for row in rows
    ]


# Backward-compatible name for older imports.
save_location = save_reminder
