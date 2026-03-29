# main.py
import asyncio
import logging

from bot import bot, dp
from routers import router,daily_weather
from db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    await init_db()
    print("✅База данных инициализирована")

    dp.include_router(router)
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


    scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")

    scheduler.add_job(daily_weather, # вызов функции из роутера
        "interval",
        minutes=1,
        id="daily_weather_by_time",
        replace_existing=True)

    logger.info("Планировщик запущен — проверка времени рассылки каждую минуту")
    scheduler.start()
    print("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
    except Exception as e:
        logger.error(e)