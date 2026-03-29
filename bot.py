# bot.py
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env файле")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

print(f"Бот успешно инициализирован")
