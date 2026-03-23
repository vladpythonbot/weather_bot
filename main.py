import asyncio
import logging
from os import getenv
from zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

from dotenv import load_dotenv
import aiohttp
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s| %(levelname)-7s| %(name)s| %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = getenv("BOT_TOKEN")
CHAT_ID = getenv("CHAT_ID")

if not TOKEN or not CHAT_ID:
    raise ValueError("BOT_TOKEN или CHAT_ID не указаны в .env")

CHAT_ID = str(CHAT_ID)

bot = Bot(token=TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

location_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

USER_LOCATION: dict[str, tuple[float, float]] = {}


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Я бот прогноза погоды.\n")
    await message.answer("Отправьте геолокацию", reply_markup=location_kb)

@router.message(F.location)
async def handle_location(message: types.Message):
    lat = message.location.latitude
    lon = message.location.longitude
    user_id = str(message.chat.id)

    USER_LOCATION[user_id] = (lat, lon)
    logger.info(f"Сохранены координаты для пользователя:{user_id}: {lat:.3f}, {lon:.3f}")

    await message.answer(
        f"Геолокация получена ({lat:.3f}, {lon:.3f})\nСейчас покажу погоду...",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    await send_weather(user_id)

async def get_weather_text(lat: float, lon: float) -> str | None:
    url = (
        f"https://api.openweathermap.org/data/2.5/weather?"
        f"lat={lat}&lon={lon}&appid=a369e617ef071f8f9364cea8072bd080"
        f"&units=metric&lang=ru"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=12) as resp:
                if resp.status != 200:
                    logger.warning(f"OpenWeather ответил {resp.status}")
                    return None

                data = await resp.json()

                if data.get("cod") != 200:
                    return None

                temp = data["main"]["temp"]
                feel = data["main"]["feels_like"]
                desc = data["weather"][0]["description"]
                tz_offset = data["timezone"]
                sunrise = data["sys"]["sunrise"]
                sunset = data["sys"]["sunset"]
                wind = data["wind"]["speed"]

                sunrise_dt = datetime.fromtimestamp(sunrise, tz=timezone.utc) + timedelta(seconds=tz_offset)
                sunset_dt = datetime.fromtimestamp(sunset, tz=timezone.utc) + timedelta(seconds=tz_offset)
                day=datetime.now().strftime("%A")
                kyiv_tz = ZoneInfo("Europe/Kyiv")
                local_now = datetime.now(kyiv_tz)
                current_time_str = local_now.strftime('%H:%M')

                return (
                    f"🌤 <b>Погода сейчас: {day}\n"
                    f"{current_time_str}</b>\n"
                    f"Температура: <b>{temp:.1f}°C</b>\n"
                    f"{desc.capitalize()}\n\n"
                    f"Ощущается: {feel:.1f}°C\n"
                    f"🌅 Восход: {sunrise_dt.strftime('%H:%M')}\n"
                    f"🌇 Закат:  {sunset_dt.strftime('%H:%M')}\n"
                    f"🌬 Ветер: {wind} м/с"
                )
    except Exception as e:
        logger.error(f"Ошибка при запросе погоды: {e}", exc_info=True)
        return None


async def send_weather(chat_id: str):
    if chat_id not in USER_LOCATION:
        logger.warning(f"Нет координат для {chat_id}")
        return

    lat, lon = USER_LOCATION[chat_id]
    text = await get_weather_text(lat, lon)

    if not text:
        text = "Не удалось получить погоду. Попробуй позже или пришли геолокацию заново."

    try:
        await bot.send_message(chat_id, text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Ошибка отправки в {chat_id}: {e}")


async def daily_weather_job():
    if CHAT_ID not in USER_LOCATION:
        logger.warning(f"Нет координат для ежедневной рассылки ({CHAT_ID})")
        return

    await send_weather(CHAT_ID)
    logger.info(f"Ежедневная погода отправлена в {CHAT_ID}")

async def main():
    scheduler = AsyncIOScheduler(kyiv_tz = ZoneInfo("Europe/Kyiv"))
    scheduler.add_job(
        daily_weather_job,
        CronTrigger(hour=6, minute=00),
        id="daily_weather_kharkiv",
        replace_existing=True,
    )
    CronTriggerTime=CronTrigger
    logger.info(f"Планировщик запущен → ежедневно в {CronTriggerTime} ")

    scheduler.start()

    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")