import asyncio
import os
import random
import sqlite3
import socketio
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton

# === КОНФИГ ===
TOKEN = os.getenv("BOT_TOKEN")
# Ссылка на твой GitHub Pages (фронтенд)
WEB_APP_URL = "https://replittest982-dot.github.io/-cryptoKaz/"

# === НАСТРОЙКА СЕРВЕРА (AIOHTTP + SOCKET.IO) ===
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

# === БАЗА ДАННЫХ ===
DB_FILE = "casino.db"

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 1000)")

def db_get_balance(user_id):
    with sqlite3.connect(DB_FILE) as conn:
        res = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if res: return res[0]
        conn.execute("INSERT INTO users (user_id, balance) VALUES (?, 1000)", (user_id,))
        return 1000

def db_update_balance(user_id, amount):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        return conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]

# === ИГРОВОЙ ДВИЖОК ===
game_state = {
    "status": "WAITING", 
    "multiplier": 1.00, 
    "history": [],
    "bets": {} # {sid: {user_id: 123, amount: 100}}
}

async def game_engine():
    print("🚀 Движок запущен")
    while True:
        # 1. ОЖИДАНИЕ
        game_state["status"] = "WAITING"
        game_state["multiplier"] = 1.00
        game_state["bets"] = {} 
        await sio.emit('game_update', {"status": "WAITING", "history": game_state["history"]})
        await asyncio.sleep(8) # Время на ставки

        # 2. ПОЛЕТ
        game_state["status"] = "FLYING"
        
        # Генерация краша (честная математика)
        crash_point = round(0.99 / (1 - random.random()), 2)
        if crash_point > 20: crash_point = 20.0 # Лимит для теста
        
        print(f"Раунд начался! Краш на {crash_point}x")
        
        start_time = asyncio.get_event_loop().time()
        
        while game_state["multiplier"] < crash_point:
            now = asyncio.get_event_loop().time()
            elapsed = now - start_time
            # Экспоненциальный рост
            game_state["multiplier"] = round(1.0 + (0.06 * elapsed + 0.06 * (elapsed**2)), 2)
            
            if game_state["multiplier"] >= crash_point:
                game_state["multiplier"] = crash_point
                break
            
            await sio.emit('tick', game_state["multiplier"])
            await asyncio.sleep(0.08) # Плавность

        # 3. КРАШ
        game_state["status"] = "CRASHED"
        game_state["history"].insert(0, game_state["multiplier"])
        game_state["history"] = game_state["history"][:8]
        
        await sio.emit('crash', {"m": game_state["multiplier"]})
        await asyncio.sleep(4)

# === СОКЕТЫ (ОБЩЕНИЕ С ИГРОКОМ) ===
@sio.on('connect')
async def connect(sid, environ):
    # При входе отправляем текущий статус
    await sio.emit('game_update', {"status": game_state["status"], "history": game_state["history"]}, room=sid)

@sio.on('auth')
async def auth(sid, data):
    user_id = int(data.get('user_id'))
    balance = db_get_balance(user_id)
    # Сохраняем ID юзера в сессию сокета
    async with sio.session(sid) as session:
        session['user_id'] = user_id
    await sio.emit('balance', balance, room=sid)

@sio.on('place_bet')
async def place_bet(sid, amount):
    if game_state["status"] != "WAITING": return
    async with sio.session(sid) as session:
        user_id = session.get('user_id')
        if not user_id: return
        
        # Списываем баланс
        if db_get_balance(user_id) >= amount:
            new_bal = db_update_balance(user_id, -amount)
            game_state["bets"][sid] = {"user_id": user_id, "amount": amount}
            await sio.emit('balance', new_bal, room=sid)
            await sio.emit('bet_ok', amount, room=sid)

@sio.on('cash_out')
async def cash_out(sid):
    if game_state["status"] != "FLYING": return
    bet_info = game_state["bets"].get(sid)
    
    if bet_info:
        # Считаем выигрыш по ТЕКУЩЕМУ коэффициенту сервера
        win = int(bet_info["amount"] * game_state["multiplier"])
        user_id = bet_info["user_id"]
        
        new_bal = db_update_balance(user_id, win)
        del game_state["bets"][sid] # Убираем ставку, чтобы не забрал дважды
        
        await sio.emit('balance', new_bal, room=sid)
        await sio.emit('win', win, room=sid)

# === ТЕЛЕГРАМ БОТ ===
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    # Передаем ID юзера в URL
    url = f"{WEB_APP_URL}?user_id={message.from_user.id}"
    kb = [[KeyboardButton(text="🚀 PLAY LIVE", web_app=WebAppInfo(url=url))]]
    await message.answer("Казино открыто! Залетай:", reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))

# === ЗАПУСК ===
async def on_startup(app):
    init_db()
    asyncio.create_task(game_engine())
    asyncio.create_task(dp.start_polling(bot))

app.on_startup.append(on_startup)

if __name__ == "__main__":
    # Bothost сам направит HTTPS домен на порт 3000
    web.run_app(app, host="0.0.0.0", port=3000)
