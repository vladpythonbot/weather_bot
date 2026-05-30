# main.py
import asyncio
import logging

from aiogram.exceptions import TelegramUnauthorizedError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from bot import bot, dp
from db import init_db
from routers import daily_weather, router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main():
    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError as exc:
        logger.error(
            "Telegram отклонил BOT_TOKEN. Проверь переменную BOT_TOKEN на Railway: "
            "токен мог быть отозван через BotFather или скопирован не полностью."
        )
        raise SystemExit(1) from exc

    logger.info("Токен проверен: @%s", me.username)

    await init_db()
    logger.info("База данных инициализирована")

    dp.include_router(router)

    scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")
    scheduler.add_job(
        daily_weather,
        CronTrigger(minute="*/5"),
        id="daily_weather",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Планировщик запущен: проверка рассылки каждые 5 минут")
    logger.info("Бот запущен")

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
    except Exception as e:
        logger.exception("Критическая ошибка: %s", e)
