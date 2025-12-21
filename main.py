import asyncio
import logging
import sys
import os
import json
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton

# === НАСТРОЙКИ ===
# Токен берется из переменных хостинга. Если нет - вставь свой вручную.
TOKEN = os.getenv("BOT_TOKEN") 
# Твоя ссылка на GitHub Pages
WEB_APP_URL = "https://replittest982-dot.github.io/-cryptoKaz/"

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# === БАЗА ДАННЫХ ===
def init_db():
    with sqlite3.connect("casino.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 1000
            )
        """)
        conn.commit()

def get_balance(user_id):
    with sqlite3.connect("casino.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            return result[0]
        # Если игрока нет, даем 1000 монет и регистрируем
        cursor.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 1000))
        conn.commit()
        return 1000

def update_balance(user_id, new_balance):
    with sqlite3.connect("casino.db") as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        conn.commit()

# === БОТ ===
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: types.Message):
    user_id = message.from_user.id
    balance = get_balance(user_id)
    
    # Мы передаем баланс прямо в ссылку, чтобы игра знала, сколько у нас денег
    app_url = f"{WEB_APP_URL}?balance={balance}"
    
    kb = [
        [KeyboardButton(text="🚀 ИГРАТЬ (CRASH)", web_app=WebAppInfo(url=app_url))]
    ]
    markup = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n"
        f"💰 Твой баланс: <b>{balance}</b> монет.\n\n"
        f"⚠️ <b>ВАЖНО:</b> Чтобы сохранить выигрыш, нажимай кнопку 'СОХРАНИТЬ И ВЫЙТИ' внутри игры!",
        reply_markup=markup,
        parse_mode="HTML"
    )

@dp.message(F.web_app_data)
async def save_data(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        # Получаем новый баланс из игры
        if 'balance' in data:
            new_balance = int(data['balance'])
            update_balance(message.from_user.id, new_balance)
            await message.answer(f"✅ Прогресс сохранен!\n💰 Текущий баланс: {new_balance}")
    except Exception as e:
        logging.error(f"Ошибка сохранения: {e}")

async def main():
    init_db()
    print("Бот запущен...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
