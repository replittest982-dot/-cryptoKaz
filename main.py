import asyncio
import logging
import sys
import os  # <-- Импортируем модуль для работы с переменными хостинга
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton

# ==========================================
# ЧТЕНИЕ ПЕРЕМЕННЫХ С ХОСТИНГА
# ==========================================

# 1. Получаем токен из переменных окружения
# Внимание: Убедитесь, что на хостинге переменная называется именно "BOT_TOKEN"
TOKEN = os.getenv("BOT_TOKEN")

# 2. Ваша ссылка на Web App
# Я оставил её здесь, но если хотите тоже спрятать в переменные,
# замените строку ниже на: WEB_APP_URL = os.getenv("WEB_APP_URL")
WEB_APP_URL = "https://replittest982-dot.github.io/-cryptoKaz/"

# ==========================================
# ПРОВЕРКА
# ==========================================
if not TOKEN:
    print("ОШИБКА: Токен не найден! Проверьте вкладку 'Startup' или 'Variables' на хостинге.")
    sys.exit(1)

# ==========================================
# ЛОГИКА БОТА
# ==========================================

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def command_start_handler(message: types.Message):
    kb = [
        [
            KeyboardButton(
                text="🚀 Открыть приложение", 
                web_app=WebAppInfo(url=WEB_APP_URL)
            )
        ]
    ]
    
    keyboard = ReplyKeyboardMarkup(
        keyboard=kb, 
        resize_keyboard=True,
        input_field_placeholder="Нажми кнопку ниже..."
    )

    await message.answer(
        "Привет! Нажми на кнопку ниже, чтобы запустить Mini App 👇",
        reply_markup=keyboard
    )

@dp.message(F.web_app_data)
async def web_app_data_handler(message: types.Message):
    data = message.web_app_data.data
    await message.answer(f"✅ Данные получены из Web App:\n{data}")

async def main():
    print("Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
