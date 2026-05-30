# main.py
import asyncio
import logging

from apscheduler.triggers.cron import CronTrigger

from bot import bot, dp
from routers import router, daily_weather
from db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    await init_db()
    logger.info("База данных инициализирована")

    dp.include_router(router)
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


    scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")

    scheduler.add_job(
        daily_weather,
        CronTrigger(minute="*/5"),
        id="daily_weather",
        replace_existing=True,
    )

    logger.info("Планировщик запущен: проверка рассылки каждые 5 минут")
    scheduler.start()
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
    except Exception as e:
        logger.exception("Критическая ошибка: %s", e)
