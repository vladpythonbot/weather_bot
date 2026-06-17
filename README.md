# Weather Bot

Telegram weather bot with current weather, daily forecast, personal location settings, and scheduled forecast reminders.

## Features

- Current weather by selected location
- Daily forecast from OpenWeather
- Location setup by city or coordinates
- Scheduled weather messages
- Choice of active reminder days
- Wind units and forecast detail settings
- Local timezone detection for user locations
- SQLite storage for user preferences
- Scheduler that checks due reminders every 5 minutes

## Tech Stack

- Python 3.11+
- aiogram 3
- aiohttp
- aiosqlite
- APScheduler
- timezonefinder
- OpenWeather API
- python-dotenv

## Project Structure

```text
.
├── main.py              # App entry point and scheduler setup
├── bot.py               # Bot and dispatcher initialization
├── routers.py           # Telegram handlers and weather logic
├── db.py                # SQLite storage layer
└── requirements.txt     # Python dependencies
```

## Environment Variables

Create a `.env` file in the project root:

```env
BOT_TOKEN=your_telegram_bot_token
API_KEY=your_openweather_api_key
DB_PATH=reminders.db
```

`DB_PATH` is optional. If it is not set, the bot creates `reminders.db` in the project folder.

## Run Locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Deployment Notes

- Store `BOT_TOKEN` and `API_KEY` only as environment variables.
- Use one running bot instance per token to avoid Telegram `getUpdates` conflicts.
- For cloud hosting, configure persistent storage if you want SQLite data to survive redeploys.
