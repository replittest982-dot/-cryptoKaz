import asyncio
import logging
import sys
import os
import json
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton

# === КОНФИГУРАЦИЯ (Берем из переменных Bothost) ===
TOKEN = os.getenv("BOT_TOKEN")
# Если переменная не задана, упадет с ошибкой (это безопасно)
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://replittest982-dot.github.io/-cryptoKaz/") 

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# === БАЗА ДАННЫХ (БЕЗОПАСНАЯ) ===
DB_NAME = "casino.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 1000
            )
        """)

def get_balance(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            return result[0]
        # Регистрация нового юзера
        conn.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 1000))
        return 1000

# ИСПРАВЛЕНИЕ: Атомарное изменение баланса (защита от Race Condition)
# Мы передаем не новый баланс, а "разницу" (выигрыш или проигрыш)
def change_balance(user_id, amount):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        # Проверяем, чтобы баланс не ушел в минус (валидация на бэке)
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        current = cursor.fetchone()
        
        if current and (current[0] + amount < 0):
            return False, current[0] # Недостаточно средств
            
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        
        # Возвращаем актуальный баланс после изменения
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        new_balance = cursor.fetchone()[0]
        return True, new_balance

# === ЛОГИКА БОТА ===
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: types.Message):
    user_id = message.from_user.id
    balance = get_balance(user_id)
    
    # Передаем баланс в URL для инициализации
    app_url = f"{WEB_APP_URL}?start_balance={balance}"
    
    kb = [[KeyboardButton(text="🚀 ИГРАТЬ В NEON CRASH", web_app=WebAppInfo(url=app_url))]]
    
    await message.answer(
        f"🌌 <b>NEON CRASH CASINO</b>\n"
        f"💳 Твой баланс: <code>{balance}</code> монет.\n"
        f"Залетай и поднимай кэш! 👇",
        reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True),
        parse_mode="HTML"
    )

# Обработка данных из игры
@dp.message(F.web_app_data)
async def handle_game_data(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        
        # Валидация: Ожидаем поле 'change' (изменение баланса), а не абсолютное число
        if 'change' in data:
            change = int(data['change'])
            
            # Простая защита от накрутки (никто не может выиграть больше 100000 за раз)
            if change > 100000: 
                await message.answer("⚠️ Подозрительная активность. Ставка отменена.")
                return

            success, new_bal = change_balance(message.from_user.id, change)
            
            if success:
                if change > 0:
                    await message.answer(f"✅ Выигрыш зачислен!\nБаланс: {new_bal} (+{change})")
                else:
                    await message.answer(f"📉 Ставка списана.\nБаланс: {new_bal}")
            else:
                await message.answer("❌ Ошибка синхронизации баланса.")
                
    except Exception as e:
        logging.error(f"Error: {e}")

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
