import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

# Вставьте ваш токен
TOKEN = "ВАШ_ТОКЕН_БОТА"
# URL вашего Web App (обязательно https)
WEB_APP_URL = "https://your-webapp-url.com"

dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    # 1. Создаем Reply-кнопку (в меню клавиатуры)
    kb = ReplyKeyboardBuilder()
    kb.add(types.KeyboardButton(
        text="Открыть приложение 📱",
        web_app=WebAppInfo(url=WEB_APP_URL)
    ))

    # 2. Создаем Inline-кнопку (под сообщением)
    inline_kb = InlineKeyboardBuilder()
    inline_kb.add(types.InlineKeyboardButton(
        text="Запустить Mini App 🚀",
        web_app=WebAppInfo(url=WEB_APP_URL)
    ))

    await message.answer(
        "Привет! Нажми на кнопку ниже, чтобы запустить наше Web App.",
        reply_markup=kb.as_markup(resize_keyboard=True)
    )
    
    await message.answer(
        "Или используй эту ссылку:",
        reply_markup=inline_kb.as_markup()
    )

async def main():
    bot = Bot(token=TOKEN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
