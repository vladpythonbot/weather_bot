import logging
import os
from collections import Counter
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import aiohttp
import dotenv
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from timezonefinder import TimezoneFinder

from bot import bot
from db import (
    Reminder,
    get_all_reminders,
    get_reminder,
    save_reminder,
    update_preferences,
)

dotenv.load_dotenv()
API_KEY = (os.getenv("API_KEY") or "").strip()

router = Router()
logger = logging.getLogger(__name__)
tf = TimezoneFinder()

DAY_NAMES = {
    0: "Пн",
    1: "Вт",
    2: "Ср",
    3: "Чт",
    4: "Пт",
    5: "Сб",
    6: "Вс",
}

DEFAULT_SCHEDULE_DAYS = "0,1,2,3,4,5,6"

BTN_WEATHER_NOW = "🌤 Сейчас"
BTN_DAY_FORECAST = "🌦 День"
BTN_CHANGE_LOCATION = "📍 Место"
BTN_CHANGE_TIME = "⏰ Время"
BTN_SETTINGS = "⚙️ Настройки"


class Form(StatesGroup):
    wait_location = State()
    wait_time = State()
    wait_new_time = State()


main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_WEATHER_NOW), KeyboardButton(text=BTN_DAY_FORECAST)],
        [KeyboardButton(text=BTN_CHANGE_LOCATION), KeyboardButton(text=BTN_CHANGE_TIME)],
        [KeyboardButton(text=BTN_SETTINGS)],
    ],
    resize_keyboard=True,
)

def parse_time(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None

    try:
        hour, minute = map(int, text.strip().split(":"))
    except ValueError:
        return None

    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None

    if minute % 5 != 0:
        return None

    return hour, minute


def time_help_text() -> str:
    return (
        "Введи время в формате <b>ЧЧ:ММ</b>.\n"
        "Минуты должны быть кратны 5.\n\n"
        "Примеры: <b>08:00</b>, <b>08:05</b>, <b>21:30</b>"
    )


def timezone_for_location(lat: float, lng: float) -> str:
    return tf.timezone_at(lat=lat, lng=lng) or "Europe/Kyiv"


def local_now_for_location(lat: float, lng: float) -> datetime:
    return datetime.now(ZoneInfo(timezone_for_location(lat, lng)))


def parse_schedule_days(value: str | None) -> set[int]:
    if not value:
        return set(range(7))

    days = set()
    for part in value.split(","):
        if part.strip().isdigit():
            day = int(part)
            if 0 <= day <= 6:
                days.add(day)

    return days or set(range(7))


def format_schedule_days(value: str | None) -> str:
    days = parse_schedule_days(value)

    if days == set(range(7)):
        return "каждый день"
    if days == set(range(5)):
        return "будни"
    if days == {5, 6}:
        return "выходные"

    return ", ".join(DAY_NAMES[day] for day in sorted(days))


def serialize_schedule_days(days: set[int]) -> str:
    return ",".join(str(day) for day in sorted(days)) or DEFAULT_SCHEDULE_DAYS


def wind_text(speed_ms: float, wind_unit: str) -> str:
    if wind_unit == "kmh":
        return f"{speed_ms * 3.6:.0f} км/ч"

    return f"{speed_ms:.1f} м/с"


def city_text(data: dict) -> str:
    name = data.get("name")
    country = data.get("sys", {}).get("country")

    if name and country:
        return f"{name}, {country}"
    if name:
        return name
    return "текущее место"


def weather_advice(temp: float, desc: str, wind: float) -> str:
    desc_lower = desc.lower()

    if "дожд" in desc_lower:
        return "Возьми зонт или непромокаемый слой."
    if "снег" in desc_lower:
        return "Лучше выбрать тёплую обувь с нормальной подошвой."
    if wind >= 9:
        return "Ветер заметный. Капюшон или плотный верх пригодятся."
    if temp <= 0:
        return "Холодно. Шапка и перчатки будут к месту."
    if temp < 8:
        return "Прохладно. Возьми тёплый слой."
    if temp >= 28:
        return "Жарко. Лёгкая одежда и вода — хорошая идея."
    if temp >= 20:
        return "Комфортно. Можно одеться легко, но проверь ветер."
    return "Погода спокойная. Одевайся по ощущениям."


def forecast_advice(temp: float, desc: str, wind: float, pop: float | None = None) -> str:
    tips = []
    desc_lower = desc.lower()

    if pop is not None and pop >= 0.45:
        tips.append("зонт")
    elif "дожд" in desc_lower:
        tips.append("зонт")

    if temp <= 0:
        tips.extend(["тёплая куртка", "шапка"])
    elif temp < 8:
        tips.append("тёплый слой")
    elif temp < 16:
        tips.append("лёгкая куртка")
    elif temp >= 28:
        tips.extend(["вода", "лёгкая одежда"])

    if wind >= 9:
        tips.append("защита от ветра")

    if not tips:
        return "Можно выходить без особой подготовки."

    return "Стоит учесть: " + ", ".join(dict.fromkeys(tips)) + "."


async def fetch_openweather(endpoint: str, lat: float, lng: float) -> dict | None:
    if not API_KEY:
        logger.error("API_KEY не найден")
        return None

    url = f"https://api.openweathermap.org/data/2.5/{endpoint}"
    params = {
        "lat": lat,
        "lon": lng,
        "appid": API_KEY,
        "units": "metric",
        "lang": "ru",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                data = await resp.json()
    except aiohttp.ClientError as e:
        logger.error("Ошибка запроса OpenWeatherMap: %s", e)
        return None

    if str(data.get("cod")) not in {"200", "2xx"}:
        logger.error("OpenWeatherMap вернул ошибку: %s", data)
        return None

    return data


async def geocode_city(city: str) -> dict | None:
    if not API_KEY:
        logger.error("API_KEY не найден")
        return None

    url = "https://api.openweathermap.org/geo/1.0/direct"
    params = {
        "q": city.strip(),
        "limit": 1,
        "appid": API_KEY,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                data = await resp.json()
    except aiohttp.ClientError as e:
        logger.error("Ошибка геокодинга OpenWeatherMap: %s", e)
        return None

    if not isinstance(data, list) or not data:
        return None

    result = data[0]
    local_names = result.get("local_names") or {}
    name = local_names.get("ru") or result.get("name") or city.strip()
    country = result.get("country")
    state = result.get("state")
    parts = [name]
    if state and state != name:
        parts.append(state)
    if country:
        parts.append(country)

    return {
        "lat": result["lat"],
        "lng": result["lon"],
        "city_name": ", ".join(parts),
    }


async def fetch_weather(lat: float, lng: float) -> dict | None:
    return await fetch_openweather("weather", lat, lng)


async def fetch_forecast(lat: float, lng: float) -> dict | None:
    return await fetch_openweather("forecast", lat, lng)


def forecast_items_for_today(data: dict, lat: float, lng: float) -> list[dict]:
    tz = ZoneInfo(timezone_for_location(lat, lng))
    today = datetime.now(tz).date()
    items = []

    for item in data.get("list", []):
        forecast_time = datetime.fromtimestamp(item["dt"], tz=tz)
        if forecast_time.date() == today:
            items.append(item | {"local_time": forecast_time})

    return items or [(item | {"local_time": datetime.fromtimestamp(item["dt"], tz=tz)}) for item in data.get("list", [])[:5]]


def period_name(hour: int) -> str:
    if 6 <= hour < 12:
        return "Утро"
    if 12 <= hour < 18:
        return "День"
    if 18 <= hour < 24:
        return "Вечер"
    return "Ночь"


def summarize_period(items: list[dict], wind_unit: str) -> str:
    temps = [item["main"]["temp"] for item in items]
    feels = [item["main"]["feels_like"] for item in items]
    winds = [item["wind"]["speed"] for item in items]
    descriptions = [item["weather"][0]["description"] for item in items]
    pop = max((item.get("pop", 0) for item in items), default=0)

    avg_temp = sum(temps) / len(temps)
    avg_feels = sum(feels) / len(feels)
    max_wind = max(winds)
    desc = Counter(descriptions).most_common(1)[0][0]
    rain = f", дождь {round(pop * 100)}%" if pop >= 0.2 else ""

    return (
        f"<b>{escape(period_name(items[0]['local_time'].hour))}</b>: "
        f"{avg_temp:.0f}°C, ощущается {avg_feels:.0f}°C, "
        f"{escape(desc)}{rain}, ветер {wind_text(max_wind, wind_unit)}"
    )


def forecast_city_text(data: dict) -> str:
    city = data.get("city", {})
    name = city.get("name")
    country = city.get("country")

    if name and country:
        return f"{name}, {country}"
    if name:
        return name
    return "текущее место"


def details_text(data: dict, reminder: Reminder) -> str:
    if not reminder.show_details:
        return ""

    humidity = data["main"].get("humidity")
    parts = []

    if humidity is not None:
        parts.append(f"Влажность: {humidity}%")

    return "\n".join(parts) + ("\n" if parts else "")


async def build_weather_text(reminder: Reminder) -> str:
    data = await fetch_weather(reminder.lat, reminder.lng)
    if not data:
        return "❌ Не удалось получить погоду. Проверь API_KEY или попробуй позже."

    temp = data["main"]["temp"]
    feels_like = data["main"]["feels_like"]
    desc = data["weather"][0]["description"]
    wind = data["wind"]["speed"]
    sunrise_ts = data["sys"]["sunrise"]
    sunset_ts = data["sys"]["sunset"]

    tz = ZoneInfo(timezone_for_location(reminder.lat, reminder.lng))
    local_time = datetime.now(tz)
    sunrise_time = datetime.fromtimestamp(sunrise_ts, tz=tz)
    sunset_time = datetime.fromtimestamp(sunset_ts, tz=tz)

    return (
        f"🌤 <b>Погода сейчас · {escape(city_text(data))}</b>\n"
        f"🕒 Местное время: <b>{local_time.strftime('%H:%M')}</b>\n\n"
        f"🌡 Температура: <b>{temp:.1f}°C</b>\n"
        f"🤔 Ощущается: <b>{feels_like:.1f}°C</b>\n"
        f"☁️ {escape(desc.capitalize())}\n"
        f"💨 Ветер: <b>{wind_text(wind, reminder.wind_unit)}</b>\n"
        f"{details_text(data, reminder)}\n"
        f"🌅 Рассвет: {sunrise_time.strftime('%H:%M')}\n"
        f"🌇 Закат: {sunset_time.strftime('%H:%M')}\n\n"
        f"💡 {weather_advice(temp, desc, wind)}"
    )


async def build_day_forecast_text(reminder: Reminder) -> str:
    data = await fetch_forecast(reminder.lat, reminder.lng)
    if not data:
        return "❌ Не удалось получить прогноз на день. Попробуй позже."

    items = forecast_items_for_today(data, reminder.lat, reminder.lng)
    grouped: dict[str, list[dict]] = {}

    for item in items:
        grouped.setdefault(period_name(item["local_time"].hour), []).append(item)

    ordered_periods = ["Утро", "День", "Вечер", "Ночь"]
    lines = [
        f"🌦 <b>Прогноз на день · {escape(forecast_city_text(data))}</b>",
        "",
    ]

    for period in ordered_periods:
        if period in grouped:
            lines.append(summarize_period(grouped[period], reminder.wind_unit))

    hottest = max(items, key=lambda item: item["main"]["temp"])
    coldest = min(items, key=lambda item: item["main"]["temp"])
    max_pop = max((item.get("pop", 0) for item in items), default=0)

    lines.extend([
        "",
        f"Максимум: <b>{hottest['main']['temp']:.0f}°C</b>",
        f"Минимум: <b>{coldest['main']['temp']:.0f}°C</b>",
    ])

    if max_pop >= 0.2:
        lines.append(f"Вероятность дождя: <b>{round(max_pop * 100)}%</b>")

    avg_temp = sum(item["main"]["temp"] for item in items) / len(items)
    max_wind = max(item["wind"]["speed"] for item in items)
    desc = Counter(item["weather"][0]["description"] for item in items).most_common(1)[0][0]
    lines.append("")
    lines.append(f"💡 {forecast_advice(avg_temp, desc, max_wind, max_pop)}")

    return "\n".join(lines)


async def build_daily_forecast_text(reminder: Reminder) -> str:
    data = await fetch_forecast(reminder.lat, reminder.lng)
    if not data:
        weather = await fetch_weather(reminder.lat, reminder.lng)
        if not weather:
            return "❌ Не удалось получить прогноз. Попробуй позже."

        return (
            f"🌤 <b>Прогноз · {escape(city_text(weather))}</b>\n\n"
            f"Сейчас {weather['main']['temp']:.1f}°C, {escape(weather['weather'][0]['description'])}.\n"
            f"💡 {forecast_advice(weather['main']['temp'], weather['weather'][0]['description'], weather['wind']['speed'])}"
        )

    items = forecast_items_for_today(data, reminder.lat, reminder.lng)[:3]
    first = items[0]
    temp = first["main"]["temp"]
    feels = first["main"]["feels_like"]
    desc = first["weather"][0]["description"]
    wind = first["wind"]["speed"]
    pop = max((item.get("pop", 0) for item in items), default=0)
    time_range = f"{items[0]['local_time'].strftime('%H:%M')}–{items[-1]['local_time'].strftime('%H:%M')}"

    return (
        f"🌤 <b>Прогноз · {escape(forecast_city_text(data))}</b>\n\n"
        f"Ближайшие часы: <b>{time_range}</b>\n"
        f"🌡 {temp:.1f}°C, ощущается {feels:.1f}°C\n"
        f"☁️ {escape(desc.capitalize())}\n"
        f"💨 Ветер: {wind_text(wind, reminder.wind_unit)}\n"
        f"Дождь: {round(pop * 100)}%\n\n"
        f"💡 {forecast_advice(temp, desc, wind, pop)}"
    )


async def ask_for_location(message: types.Message, state: FSMContext):
    await message.answer(
        "Напиши город, для которого показывать погоду.\n\n"
        "Например: <b>Киев</b>, <b>Львов</b>, <b>Warsaw</b>.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(Form.wait_location)


async def get_or_ask_reminder(message: types.Message, state: FSMContext) -> Reminder | None:
    reminder = await get_reminder(message.from_user.id)
    if reminder:
        return reminder

    await ask_for_location(message, state)
    return None


@router.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    reminder = await get_reminder(message.from_user.id)
    name = message.from_user.first_name or "друг"

    if reminder:
        await message.answer(
            f"👋 Привет, {escape(name)}.\n\n"
            "Я уже помню твои настройки. Можешь посмотреть погоду сейчас или прогноз на день.",
            reply_markup=main_keyboard,
        )
        return

    await message.answer(
        f"👋 Привет, {escape(name)}.\n\n"
        "Я буду показывать погоду и присылать прогноз в выбранное время.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await ask_for_location(message, state)


@router.message(Form.wait_location)
async def handle_location(message: types.Message, state: FSMContext):
    city = (message.text or "").strip()
    if len(city) < 2:
        await message.answer("Напиши название города текстом. Например: <b>Киев</b>.", parse_mode="HTML")
        return

    place = await geocode_city(city)
    if not place:
        await message.answer("Не нашёл такой город. Попробуй написать по-другому, например: <b>Kyiv</b>.", parse_mode="HTML")
        return

    lat = place["lat"]
    lng = place["lng"]
    city_name = place["city_name"]
    reminder = await get_reminder(message.from_user.id)

    if reminder:
        await save_reminder(
            message.from_user.id,
            lat,
            lng,
            reminder.hour,
            reminder.minute,
            city_name=city_name,
            wind_unit=reminder.wind_unit,
            show_details=reminder.show_details,
            schedule_days=reminder.schedule_days,
        )
        await state.clear()
        updated = await get_reminder(message.from_user.id)

        await message.answer(
            f"✅ Город обновлён: <b>{escape(city_name)}</b>.\n"
            f"Время прогноза осталось прежним: "
            f"<b>{reminder.hour:02d}:{reminder.minute:02d}</b>.",
            parse_mode="HTML",
            reply_markup=main_keyboard,
        )
        await message.answer(await build_weather_text(updated), parse_mode="HTML")
        return

    await state.update_data(lat=lat, lng=lng, city_name=city_name)

    await message.answer(
        f"📍 Город найден: <b>{escape(city_name)}</b>.\n\n" + time_help_text(),
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(Form.wait_time)


@router.message(Form.wait_time)
async def handle_time(message: types.Message, state: FSMContext):
    parsed = parse_time(message.text)
    if not parsed:
        await message.answer("❌ Некорректное время.\n\n" + time_help_text(), parse_mode="HTML")
        return

    hour, minute = parsed
    data = await state.get_data()
    lat = data["lat"]
    lng = data["lng"]
    city_name = data["city_name"]

    await save_reminder(
        message.from_user.id,
        lat,
        lng,
        hour,
        minute,
        city_name=city_name,
    )
    await state.clear()
    reminder = await get_reminder(message.from_user.id)

    await message.answer(
        f"✅ Готово. Буду присылать прогноз в <b>{hour:02d}:{minute:02d}</b>.",
        parse_mode="HTML",
        reply_markup=main_keyboard,
    )
    await message.answer(await build_weather_text(reminder), parse_mode="HTML")


@router.message(F.text == BTN_WEATHER_NOW)
async def weather_now(message: types.Message, state: FSMContext):
    reminder = await get_or_ask_reminder(message, state)
    if not reminder:
        return

    await message.answer(await build_weather_text(reminder), parse_mode="HTML")


@router.message(F.text == BTN_DAY_FORECAST)
async def day_forecast(message: types.Message, state: FSMContext):
    reminder = await get_or_ask_reminder(message, state)
    if not reminder:
        return

    await message.answer(await build_day_forecast_text(reminder), parse_mode="HTML")


@router.message(F.text == BTN_CHANGE_LOCATION)
async def change_location(message: types.Message, state: FSMContext):
    await ask_for_location(message, state)


@router.message(F.text == BTN_SETTINGS)
async def my_settings(message: types.Message):
    await show_settings(message, message.from_user.id)


async def show_settings(obj: types.Message | types.CallbackQuery, user_id: int):
    reminder = await get_reminder(user_id)

    if not reminder:
        text = "Настроек пока нет. Нажми /start и укажи город."
        if isinstance(obj, types.CallbackQuery):
            await obj.message.edit_text(text)
            await obj.answer()
        else:
            await obj.answer(text)
        return

    tz_name = timezone_for_location(reminder.lat, reminder.lng)
    local_time = local_now_for_location(reminder.lat, reminder.lng)
    wind_label = "км/ч" if reminder.wind_unit == "kmh" else "м/с"
    details_label = "включены" if reminder.show_details else "скрыты"
    days_label = format_schedule_days(reminder.schedule_days)

    day_buttons = [
        InlineKeyboardButton(
            text=("✓ " if day in parse_schedule_days(reminder.schedule_days) else "") + label,
            callback_data=f"toggle_day_{day}",
        )
        for day, label in DAY_NAMES.items()
    ]

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Ветер: {wind_label}", callback_data="toggle_wind_unit")],
        [InlineKeyboardButton(text=f"Детали: {details_label}", callback_data="toggle_details")],
        day_buttons[:4],
        day_buttons[4:],
        [
            InlineKeyboardButton(text="Будни", callback_data="days_weekdays"),
            InlineKeyboardButton(text="Все дни", callback_data="days_all"),
        ],
    ])

    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"📍 Город: <b>{escape(reminder.city_name)}</b>\n"
        f"🌍 Часовой пояс: <b>{escape(tz_name)}</b>\n"
        f"🕒 Сейчас там: <b>{local_time.strftime('%H:%M')}</b>\n"
        f"⏰ Прогноз: <b>{reminder.hour:02d}:{reminder.minute:02d}</b>\n"
        f"📅 Дни: <b>{days_label}</b>\n"
        f"💨 Ветер: <b>{wind_label}</b>\n"
        f"📎 Влажность: <b>{details_label}</b>"
    )

    if isinstance(obj, types.CallbackQuery):
        await obj.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        await obj.answer()
    else:
        await obj.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "toggle_wind_unit")
async def toggle_wind_unit(callback: types.CallbackQuery):
    reminder = await get_reminder(callback.from_user.id)
    if not reminder:
        await callback.answer("Сначала настрой бота", show_alert=True)
        return

    new_unit = "kmh" if reminder.wind_unit == "ms" else "ms"
    await update_preferences(callback.from_user.id, wind_unit=new_unit)
    await show_settings(callback, callback.from_user.id)


@router.callback_query(F.data == "toggle_details")
async def toggle_details(callback: types.CallbackQuery):
    reminder = await get_reminder(callback.from_user.id)
    if not reminder:
        await callback.answer("Сначала настрой бота", show_alert=True)
        return

    await update_preferences(callback.from_user.id, show_details=not reminder.show_details)
    await show_settings(callback, callback.from_user.id)


@router.callback_query(F.data.startswith("toggle_day_"))
async def toggle_schedule_day(callback: types.CallbackQuery):
    reminder = await get_reminder(callback.from_user.id)
    if not reminder:
        await callback.answer("Сначала настрой бота", show_alert=True)
        return

    day = int(callback.data.split("_")[-1])
    days = parse_schedule_days(reminder.schedule_days)

    if day in days and len(days) > 1:
        days.remove(day)
    else:
        days.add(day)

    await update_preferences(callback.from_user.id, schedule_days=serialize_schedule_days(days))
    await show_settings(callback, callback.from_user.id)


@router.callback_query(F.data == "days_weekdays")
async def set_weekdays(callback: types.CallbackQuery):
    if not await update_preferences(callback.from_user.id, schedule_days="0,1,2,3,4"):
        await callback.answer("Сначала настрой бота", show_alert=True)
        return

    await show_settings(callback, callback.from_user.id)


@router.callback_query(F.data == "days_all")
async def set_all_days(callback: types.CallbackQuery):
    if not await update_preferences(callback.from_user.id, schedule_days=DEFAULT_SCHEDULE_DAYS):
        await callback.answer("Сначала настрой бота", show_alert=True)
        return

    await show_settings(callback, callback.from_user.id)


@router.message(F.text == BTN_CHANGE_TIME)
async def change_time(message: types.Message, state: FSMContext):
    reminder = await get_reminder(message.from_user.id)

    if not reminder:
        await message.answer("Сначала настрой бота через /start.")
        return

    await message.answer(
        f"Текущее время прогноза: <b>{reminder.hour:02d}:{reminder.minute:02d}</b>\n\n"
        + time_help_text(),
        parse_mode="HTML",
    )
    await state.set_state(Form.wait_new_time)


@router.message(Form.wait_new_time)
async def process_new_time(message: types.Message, state: FSMContext):
    parsed = parse_time(message.text)
    if not parsed:
        await message.answer("❌ Некорректное время.\n\n" + time_help_text(), parse_mode="HTML")
        return

    reminder = await get_reminder(message.from_user.id)
    if not reminder:
        await message.answer("Настройки не найдены. Нажми /start.")
        await state.clear()
        return

    hour, minute = parsed
    await save_reminder(
        message.from_user.id,
        reminder.lat,
        reminder.lng,
        hour,
        minute,
        city_name=reminder.city_name,
        wind_unit=reminder.wind_unit,
        show_details=reminder.show_details,
        schedule_days=reminder.schedule_days,
    )
    await state.clear()

    await message.answer(
        f"✅ Новое время прогноза: <b>{hour:02d}:{minute:02d}</b>",
        parse_mode="HTML",
        reply_markup=main_keyboard,
    )


async def should_notify_now(reminder: Reminder) -> bool:
    local_now = local_now_for_location(reminder.lat, reminder.lng)
    if local_now.weekday() not in parse_schedule_days(reminder.schedule_days):
        return False

    return local_now.hour == reminder.hour and local_now.minute == reminder.minute


async def daily_weather():
    now_kyiv = datetime.now(ZoneInfo("Europe/Kyiv"))
    logger.info("Проверка рассылки на %s (Киев)", now_kyiv.strftime("%H:%M"))

    try:
        reminders = await get_all_reminders()
        users_to_notify = [reminder for reminder in reminders if await should_notify_now(reminder)]

        success = 0
        if not users_to_notify:
            logger.debug("На это время нет пользователей для рассылки")
        else:
            for reminder in users_to_notify:
                try:
                    text = await build_daily_forecast_text(reminder)
                    await bot.send_message(
                        chat_id=reminder.user_id,
                        text=(
                            f"⏰ <b>Прогноз на {local_now_for_location(reminder.lat, reminder.lng).strftime('%H:%M')}</b>\n\n"
                            f"{text}"
                        ),
                        parse_mode="HTML",
                    )
                    success += 1
                    logger.info("Прогноз отправлен пользователю %s", reminder.user_id)
                except Exception as e:
                    logger.error("Ошибка отправки пользователю %s: %s", reminder.user_id, e)

            logger.info("Рассылка завершена: %s/%s", success, len(users_to_notify))

    except Exception as e:
        logger.error("Ошибка при выполнении рассылки: %s", e, exc_info=True)
