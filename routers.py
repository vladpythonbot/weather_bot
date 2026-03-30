import aiohttp
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import dotenv
import os
dotenv.load_dotenv()
API_KEY = os.getenv("API_KEY")
import aiosqlite
from timezonefinder import TimezoneFinder
from bot import bot
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from db import save_location, get_user_location, get_reminder

router = Router()
tf = TimezoneFinder()
logger = logging.getLogger(__name__)


class Form(StatesGroup):
    wait_location = State()
    wait_time = State()
    wait_new_time = State()


main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🌤 Погода сейчас")],
        [KeyboardButton(text="📍 Изменить местоположение"),
         KeyboardButton(text="⏰ Изменить время")],
        [KeyboardButton(text="📋 Мои настройки")]
    ],
    resize_keyboard=True
)

user_location_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
    resize_keyboard=True,
    one_time_keyboard=True
)

@router.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    name = message.from_user.first_name or "друг"

    await message.answer(
        f"👋 Привет, {name}!\n\n"
        f"Я бот погоды ☀️\n"
        f"Отправь геолокацию 👇",
        reply_markup=user_location_kb
    )

    await state.set_state(Form.wait_location)


@router.message(Form.wait_location, F.location)
async def get_location(message: types.Message, state: FSMContext):
    lat = message.location.latitude
    lng = message.location.longitude

    await state.update_data(lat=lat, lng=lng)

    await message.answer(
        "📍 Геолокация получена\n"
        "Введи время ЧЧ:ММ (например 08:00)",
        reply_markup=ReplyKeyboardRemove()
    )

    await state.set_state(Form.wait_time)


@router.message(Form.wait_time)
async def get_time(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("❌ Пожалуйста, введите время текстом в формате ЧЧ:ММ")
        return
    time_str = message.text.strip()
    try:
        hour, minute = map(int, time_str.split(":"))

        if not (0 <= hour < 24):
            raise ValueError("Неверный час")
        if not (0 <= minute <=59):
            raise ValueError("Минуты должны быть  от 0 до 59")
        if minute % 5 !=0:
            raise ValueError("Минуты должны быть кратны 5 (00, 05, 10, 15...)")
    except ValueError as e:
        error_text = str(e) if str(e) else "Неверный формат времени"
        await message.answer(
            f"❌ {error_text}\n\n"
            f"Введите время в формате ЧЧ:ММ\n"
            f"Минуты должны быть кратны 5.\n"
            f"Примеры: 08:00, 08:05, 08:10, 21:30")
        return

    data = await state.get_data()
    lat = data["lat"]
    lng = data["lng"]

    await save_location(message.from_user.id, lat, lng, hour, minute)

    await message.answer("✅ Сохранено!", reply_markup=main_keyboard)

    await state.clear()

    text = await build_weather_text(lat, lng)
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "🌤 Погода сейчас")
async def weather_now(message: types.Message):
    user_id = message.from_user.id

    lat, lng = await get_user_location(user_id)

    if lat is None:
        await message.answer(
            "Сначала отправь геолокацию 👇",
            reply_markup=user_location_kb
        )
        return

    text = await build_weather_text(lat, lng)
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "📍 Изменить местоположение")
async def change_location(message: types.Message, state: FSMContext):
    await message.answer("Отправь новую геолокацию 👇", reply_markup=user_location_kb)
    await state.set_state(Form.wait_location)


@router.message(F.text == "📋 Мои настройки")
async def my_settings(message: types.Message):
    reminder = await get_reminder(message.from_user.id)

    if not reminder:
        await message.answer("❌ Нет данных. Нажми /start")
        return

    lat, lng, hour, minute = reminder

    await message.answer(
        f"📋 <b>Твои настройки</b>\n\n"
        f"📍 {lat:.3f}, {lng:.3f}\n"
        f"⏰ {hour:02d}:{minute:02d}",
        parse_mode="HTML"
    )


@router.message(F.text == "⏰ Изменить время")
async def change_time(message: types.Message, state: FSMContext):
    reminder = await get_reminder(message.from_user.id)

    if not reminder:
        await message.answer("❌ Сначала настрой бота через /start")
        return

    _, _, hour, minute = reminder

    await message.answer(
        f"Текущее время: {hour:02d}:{minute:02d}\n\n"
        f"Введи новое время ЧЧ:ММ"
    )

    await state.set_state(Form.wait_new_time)


@router.message(Form.wait_new_time)
async def process_new_time(message: types.Message, state: FSMContext):
    try:
        hour, minute = map(int, message.text.split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError
    except:
        await message.answer("❌ Формат ЧЧ:ММ")
        return

    reminder = await get_reminder(message.from_user.id)

    if not reminder:
        await message.answer("Ошибка. Нажми /start")
        await state.clear()
        return

    lat, lng, _, _ = reminder

    await save_location(message.from_user.id, lat, lng, hour, minute)
    await message.answer(
        f"✅ Новое время: {hour:02d}:{minute:02d}",
        reply_markup=main_keyboard
    )

    await state.clear()


async def build_weather_text(lat: float, lng: float) -> str:
    url = (
        f"https://api.openweathermap.org/data/2.5/weather?"
        f"lat={lat}&lon={lng}&appid={API_KEY}"
        f"&units=metric&lang=ru"
    )

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()

    if data.get("cod") != 200:
        logger.error(data)
        return "❌ Ошибка получения погоды"

    temp = data["main"]["temp"]
    feel = data["main"]["feels_like"]
    desc = data["weather"][0]["description"]
    wind = data["wind"]["speed"]
    sunrise_ts = data["sys"]["sunrise"]
    sunset_ts = data["sys"]["sunset"]


    tz_name = tf.timezone_at(lat=lat, lng=lng) or "Europe/Kyiv"
    tZ=ZoneInfo(tz_name)


    sunrise_time=datetime.fromtimestamp(sunrise_ts,tz=tZ)
    sunset_time=datetime.fromtimestamp(sunset_ts,tz=tZ)
    local_time = datetime.now(ZoneInfo(tz_name))

    return (
        f"🌤 <b>Погода сейчас</b>\n"
        f"🕒 {local_time.strftime('%H:%M')}\n\n"
        f"🌡 Температура: <b>{temp:.1f}°C</b>\n"
        f"{desc.capitalize()}\n\n"
        f"🤔 Ощущается: {feel:.1f}°C\n"
        f"💨 Ветер: {wind} м/с\n\n"
        f"Рассвет в {sunrise_time.strftime("%H:%M")}\n"
        f"Закат в {sunset_time.strftime("%H:%M")}"
    )
async def daily_weather():
    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    current_hour = now.hour
    current_minute = now.minute

    logger.info(f"Запуск ежедневной рассылки{current_hour:02d}:{current_minute:02d}")
    try:
        async with aiosqlite.connect("reminders.db") as db:
            cursor = await db.execute("SELECT user_id,lat,lng,hour,minute"
                                   " FROM reminders WHERE hour=? AND minute=?",(current_hour,current_minute))
            users_for_notify = await cursor.fetchall()
        if not users_for_notify:
            logger.info("Нет пользователей для рассылки")
            return

        success=0
        for user in users_for_notify:
            user_id,lat,lng,hour,minute = user
            try:
                text=await build_weather_text(lat,lng)
                if text:
                    await bot.send_message(
                        chat_id=user_id,
                        text=f"Ваш ежедневный прогноз на {hour:02d}:{minute:02d}\n\n{text}",parse_mode="HTML")
                    success+=1
                    logger.info(f"Прогноз отправлен пользователю {user_id}")

            except Exception as e:
                logger.error(f"Ошибка отправки рассылки {user_id},{e}")

        logger.info(f"Рассылка завершена.{success}/{len(users_for_notify)}")

    except Exception as e:
        logger.error(f"Ошибка при начале рассылки: {e}", exc_info=True)
