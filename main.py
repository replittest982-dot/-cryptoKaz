import asyncio
import os
import random
import sqlite3
from aiohttp import web
import socketio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton

# === НАСТРОЙКИ ===
TOKEN = os.getenv("BOT_TOKEN")
# Ссылка на GitHub (твое мини-приложение)
WEB_APP_URL = "https://replittest982-dot.github.io/-cryptoKaz/"

# === СЕРВЕР SOCKET.IO ===
# Разрешаем подключение с любого сайта (CORS)
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

# === БАЗА ДАННЫХ ===
DB_NAME = "casino.db"
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 1000)")

# === СОСТОЯНИЕ ИГРЫ ===
game = {
    "status": "WAITING", 
    "m": 1.00, 
    "history": []
}

async def game_loop():
    print("🚀 GAME ENGINE STARTED")
    while True:
        # 1. ОЖИДАНИЕ
        game["status"] = "WAITING"
        game["m"] = 1.00
        await sio.emit('state', game)
        await asyncio.sleep(6) # Время на ставки

        # 2. ПОЛЕТ
        game["status"] = "FLYING"
        # Генерация краша
        crash = round(0.99 / (1 - random.random()), 2)
        if crash > 15: crash = 15.0 # Ограничитель
        
        print(f"New Round: Crash @ {crash}x")

        while game["m"] < crash:
            # Экспоненциальный рост
            game["m"] = round(game["m"] * 1.06, 2) 
            if game["m"] >= crash: 
                game["m"] = crash
                break
            
            await sio.emit('tick', game["m"])
            await asyncio.sleep(0.15) # Скорость обновления

        # 3. КРАШ
        game["status"] = "CRASHED"
        game["history"].insert(0, crash)
        game["history"] = game["history"][:8]
        await sio.emit('crash', game)
        await asyncio.sleep(4)

# === БОТ ТЕЛЕГРАМ ===
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: types.Message):
    url = f"{WEB_APP_URL}?user_id={message.from_user.id}"
    kb = [[KeyboardButton(text="🚀 PLAY LIVE", web_app=WebAppInfo(url=url))]]
    await message.answer("Игра запущена! Присоединяйся к общему столу:", reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))

# === ЗАПУСК ===
async def on_startup(app):
    init_db()
    asyncio.create_task(game_loop())
    asyncio.create_task(dp.start_polling(bot))

app.on_startup.append(on_startup)

if __name__ == "__main__":
    # Bothost перенаправит твой домен сюда
    web.run_app(app, host="0.0.0.0", port=3000)
