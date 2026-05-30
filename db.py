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
    wind_unit: str = "ms"
    show_details: bool = True
    sunrise_alarm_enabled: bool = False
    sunrise_alarm_offset: int = 10
    sunrise_alarm_last_date: str | None = None


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
                wind_unit TEXT NOT NULL DEFAULT 'ms',
                show_details INTEGER NOT NULL DEFAULT 1,
                sunrise_alarm_enabled INTEGER NOT NULL DEFAULT 0,
                sunrise_alarm_offset INTEGER NOT NULL DEFAULT 10,
                sunrise_alarm_last_date TEXT
            )
        """)
        await ensure_column(db, "reminders", "wind_unit", "TEXT NOT NULL DEFAULT 'ms'")
        await ensure_column(db, "reminders", "show_details", "INTEGER NOT NULL DEFAULT 1")
        await ensure_column(db, "reminders", "sunrise_alarm_enabled", "INTEGER NOT NULL DEFAULT 0")
        await ensure_column(db, "reminders", "sunrise_alarm_offset", "INTEGER NOT NULL DEFAULT 10")
        await ensure_column(db, "reminders", "sunrise_alarm_last_date", "TEXT")
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
    wind_unit: str | None = None,
    show_details: bool | None = None,
    sunrise_alarm_enabled: bool | None = None,
    sunrise_alarm_offset: int | None = None,
    sunrise_alarm_last_date: str | None = None,
):
    current = await get_reminder(user_id)
    wind_unit = wind_unit or (current.wind_unit if current else "ms")
    show_details = current.show_details if show_details is None and current else (True if show_details is None else show_details)
    sunrise_alarm_enabled = (
        current.sunrise_alarm_enabled
        if sunrise_alarm_enabled is None and current
        else (False if sunrise_alarm_enabled is None else sunrise_alarm_enabled)
    )
    sunrise_alarm_offset = sunrise_alarm_offset if sunrise_alarm_offset is not None else (current.sunrise_alarm_offset if current else 10)
    sunrise_alarm_last_date = sunrise_alarm_last_date if sunrise_alarm_last_date is not None else (current.sunrise_alarm_last_date if current else None)

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO reminders (
                user_id, lat, lng, hour, minute, wind_unit, show_details,
                sunrise_alarm_enabled, sunrise_alarm_offset, sunrise_alarm_last_date
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                lat = excluded.lat,
                lng = excluded.lng,
                hour = excluded.hour,
                minute = excluded.minute,
                wind_unit = excluded.wind_unit,
                show_details = excluded.show_details,
                sunrise_alarm_enabled = excluded.sunrise_alarm_enabled,
                sunrise_alarm_offset = excluded.sunrise_alarm_offset,
                sunrise_alarm_last_date = excluded.sunrise_alarm_last_date
        """, (
            user_id, lat, lng, hour, minute, wind_unit, int(show_details),
            int(sunrise_alarm_enabled), sunrise_alarm_offset, sunrise_alarm_last_date,
        ))
        await db.commit()


async def update_preferences(user_id: int, wind_unit: str | None = None, show_details: bool | None = None):
    reminder = await get_reminder(user_id)
    if not reminder:
        return False

    await save_reminder(
        user_id=user_id,
        lat=reminder.lat,
        lng=reminder.lng,
        hour=reminder.hour,
        minute=reminder.minute,
        wind_unit=wind_unit or reminder.wind_unit,
        show_details=reminder.show_details if show_details is None else show_details,
    )
    return True


async def update_sunrise_alarm(
    user_id: int,
    enabled: bool | None = None,
    offset: int | None = None,
    last_date: str | None = None,
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
        wind_unit=reminder.wind_unit,
        show_details=reminder.show_details,
        sunrise_alarm_enabled=reminder.sunrise_alarm_enabled if enabled is None else enabled,
        sunrise_alarm_offset=reminder.sunrise_alarm_offset if offset is None else offset,
        sunrise_alarm_last_date=reminder.sunrise_alarm_last_date if last_date is None else last_date,
    )
    return True


async def get_reminder(user_id: int) -> Reminder | None:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT
                user_id, lat, lng, hour, minute, wind_unit, show_details,
                sunrise_alarm_enabled, sunrise_alarm_offset, sunrise_alarm_last_date
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
        wind_unit=row[5] or "ms",
        show_details=bool(row[6]),
        sunrise_alarm_enabled=bool(row[7]),
        sunrise_alarm_offset=row[8] if row[8] is not None else 10,
        sunrise_alarm_last_date=row[9],
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
                user_id, lat, lng, hour, minute, wind_unit, show_details,
                sunrise_alarm_enabled, sunrise_alarm_offset, sunrise_alarm_last_date
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
            wind_unit=row[5] or "ms",
            show_details=bool(row[6]),
            sunrise_alarm_enabled=bool(row[7]),
            sunrise_alarm_offset=row[8] if row[8] is not None else 10,
            sunrise_alarm_last_date=row[9],
        )
        for row in rows
    ]


# Backward-compatible name for older imports.
save_location = save_reminder
