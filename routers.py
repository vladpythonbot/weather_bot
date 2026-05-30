import logging
import os
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import aiohttp
import dotenv
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from timezonefinder import TimezoneFinder

from bot import bot
from db import Reminder, get_all_reminders, get_reminder, get_user_location, save_reminder

dotenv.load_dotenv()
API_KEY = (os.getenv("API_KEY") or "").strip()

router = Router()
logger = logging.getLogger(__name__)
tf = TimezoneFinder()

BTN_WEATHER_NOW = "🌤 Погода сейчас"
BTN_CHANGE_LOCATION = "📍 Изменить место"
BTN_CHANGE_TIME = "⏰ Изменить время"
BTN_SETTINGS = "📋 Настройки"
BTN_SEND_LOCATION = "📍 Отправить геолокацию"


class Form(StatesGroup):
    wait_location = State()
    wait_time = State()
    wait_new_time = State()


main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_WEATHER_NOW)],
        [KeyboardButton(text=BTN_CHANGE_LOCATION), KeyboardButton(text=BTN_CHANGE_TIME)],
        [KeyboardButton(text=BTN_SETTINGS)],
    ],
    resize_keyboard=True,
)

location_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_SEND_LOCATION, request_location=True)]],
    resize_keyboard=True,
    one_time_keyboard=True,
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


def weather_advice(temp: float, desc: str, wind: float) -> str:
    desc_lower = desc.lower()

    if "дожд" in desc_lower:
        return "Возьми зонт или накинь что-то непромокаемое."
    if "снег" in desc_lower:
        return "Обувь с нормальной подошвой сегодня будет кстати."
    if wind >= 9:
        return "Ветер заметный, лучше одеться чуть теплее."
    if temp <= 0:
        return "Холодно. Перчатки и шапка не будут лишними."
    if temp < 8:
        return "Прохладно. Лучше взять тёплый слой."
    if temp >= 28:
        return "Жарко. Вода и лёгкая одежда спасут день."
    return "Погода без крайностей. Одевайся по ощущениям."


async def fetch_weather(lat: float, lng: float) -> dict | None:
    if not API_KEY:
        logger.error("API_KEY не найден")
        return None

    url = "https://api.openweathermap.org/data/2.5/weather"
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

    if str(data.get("cod")) != "200":
        logger.error("OpenWeatherMap вернул ошибку: %s", data)
        return None

    return data


async def build_weather_text(lat: float, lng: float) -> str:
    data = await fetch_weather(lat, lng)
    if not data:
        return "❌ Не удалось получить погоду. Проверь API_KEY или попробуй позже."

    temp = data["main"]["temp"]
    feels_like = data["main"]["feels_like"]
    humidity = data["main"].get("humidity")
    pressure = data["main"].get("pressure")
    desc = data["weather"][0]["description"]
    wind = data["wind"]["speed"]
    sunrise_ts = data["sys"]["sunrise"]
    sunset_ts = data["sys"]["sunset"]

    tz_name = timezone_for_location(lat, lng)
    tz = ZoneInfo(tz_name)
    local_time = datetime.now(tz)
    sunrise_time = datetime.fromtimestamp(sunrise_ts, tz=tz)
    sunset_time = datetime.fromtimestamp(sunset_ts, tz=tz)

    pressure_text = f"\nДавление: {pressure} гПа" if pressure else ""
    humidity_text = f"\nВлажность: {humidity}%" if humidity is not None else ""

    return (
        "🌤 <b>Погода сейчас</b>\n"
        f"🕒 Местное время: <b>{local_time.strftime('%H:%M')}</b>\n\n"
        f"🌡 Температура: <b>{temp:.1f}°C</b>\n"
        f"🤔 Ощущается: <b>{feels_like:.1f}°C</b>\n"
        f"☁️ {escape(desc.capitalize())}\n"
        f"💨 Ветер: <b>{wind:.1f} м/с</b>"
        f"{humidity_text}"
        f"{pressure_text}\n\n"
        f"🌅 Рассвет: {sunrise_time.strftime('%H:%M')}\n"
        f"🌇 Закат: {sunset_time.strftime('%H:%M')}\n\n"
        f"💡 {weather_advice(temp, desc, wind)}"
    )


async def ask_for_location(message: types.Message, state: FSMContext):
    await message.answer(
        "Отправь геолокацию, чтобы я показывал погоду и присылал прогноз в твоё местное время.",
        reply_markup=location_keyboard,
    )
    await state.set_state(Form.wait_location)


@router.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    reminder = await get_reminder(message.from_user.id)
    name = message.from_user.first_name or "друг"

    if reminder:
        await message.answer(
            f"👋 Привет, {escape(name)}.\n\n"
            "Я уже помню твои настройки. Можешь посмотреть погоду сейчас или изменить время рассылки.",
            reply_markup=main_keyboard,
        )
        return

    await message.answer(
        f"👋 Привет, {escape(name)}.\n\n"
        "Я буду показывать погоду и присылать ежедневный прогноз в выбранное время.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await ask_for_location(message, state)


@router.message(Form.wait_location, F.location)
async def handle_location(message: types.Message, state: FSMContext):
    lat = message.location.latitude
    lng = message.location.longitude
    await state.update_data(lat=lat, lng=lng)

    await message.answer(
        "📍 Геолокация получена.\n\n" + time_help_text(),
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(Form.wait_time)


@router.message(Form.wait_location)
async def handle_location_missing(message: types.Message):
    await message.answer("Нужно отправить именно геолокацию кнопкой ниже.", reply_markup=location_keyboard)


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

    await save_reminder(message.from_user.id, lat, lng, hour, minute)
    await state.clear()

    await message.answer(
        f"✅ Готово. Буду присылать прогноз в <b>{hour:02d}:{minute:02d}</b> по местному времени.",
        parse_mode="HTML",
        reply_markup=main_keyboard,
    )

    await message.answer(await build_weather_text(lat, lng), parse_mode="HTML")


@router.message(F.text == BTN_WEATHER_NOW)
async def weather_now(message: types.Message, state: FSMContext):
    lat, lng = await get_user_location(message.from_user.id)

    if lat is None or lng is None:
        await ask_for_location(message, state)
        return

    await message.answer(await build_weather_text(lat, lng), parse_mode="HTML")


@router.message(F.text == BTN_CHANGE_LOCATION)
async def change_location(message: types.Message, state: FSMContext):
    await ask_for_location(message, state)


@router.message(F.text == BTN_SETTINGS)
async def my_settings(message: types.Message):
    reminder = await get_reminder(message.from_user.id)

    if not reminder:
        await message.answer("Настроек пока нет. Нажми /start и отправь геолокацию.")
        return

    tz_name = timezone_for_location(reminder.lat, reminder.lng)
    local_time = local_now_for_location(reminder.lat, reminder.lng)

    await message.answer(
        "📋 <b>Настройки</b>\n\n"
        f"📍 Координаты: <b>{reminder.lat:.3f}, {reminder.lng:.3f}</b>\n"
        f"🌍 Часовой пояс: <b>{escape(tz_name)}</b>\n"
        f"🕒 Сейчас там: <b>{local_time.strftime('%H:%M')}</b>\n"
        f"⏰ Рассылка: <b>{reminder.hour:02d}:{reminder.minute:02d}</b>",
        parse_mode="HTML",
    )


@router.message(F.text == BTN_CHANGE_TIME)
async def change_time(message: types.Message, state: FSMContext):
    reminder = await get_reminder(message.from_user.id)

    if not reminder:
        await message.answer("Сначала настрой бота через /start.")
        return

    await message.answer(
        f"Текущее время рассылки: <b>{reminder.hour:02d}:{reminder.minute:02d}</b>\n\n"
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
    await save_reminder(message.from_user.id, reminder.lat, reminder.lng, hour, minute)
    await state.clear()

    await message.answer(
        f"✅ Новое время рассылки: <b>{hour:02d}:{minute:02d}</b>",
        parse_mode="HTML",
        reply_markup=main_keyboard,
    )


async def should_notify_now(reminder: Reminder) -> bool:
    local_now = local_now_for_location(reminder.lat, reminder.lng)
    return local_now.hour == reminder.hour and local_now.minute == reminder.minute


async def daily_weather():
    now_kyiv = datetime.now(ZoneInfo("Europe/Kyiv"))
    logger.info("Проверка рассылки на %s (Киев)", now_kyiv.strftime("%H:%M"))

    try:
        reminders = await get_all_reminders()
        users_to_notify = [reminder for reminder in reminders if await should_notify_now(reminder)]

        if not users_to_notify:
            logger.debug("На это время нет пользователей для рассылки")
            return

        success = 0
        for reminder in users_to_notify:
            try:
                text = await build_weather_text(reminder.lat, reminder.lng)
                await bot.send_message(
                    chat_id=reminder.user_id,
                    text=(
                        f"⏰ <b>Ежедневный прогноз на {reminder.hour:02d}:{reminder.minute:02d}</b>\n\n"
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
