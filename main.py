import asyncio
import logging
import os
import random
import sqlite3
from aiohttp import web
import socketio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton

# === КОНФИГУРАЦИЯ ===
TOKEN = os.getenv("BOT_TOKEN") # Или вставь токен в кавычках
WEB_APP_URL = "https://replittest982-dot.github.io/-cryptoKaz/" # Твой GitHub

# === НАСТРОЙКА SOCKET.IO И WEB-СЕРВЕРА ===
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

# === БАЗА ДАННЫХ ===
DB_NAME = "casino.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 1000)")

def get_balance(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        res = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if res: return res[0]
        conn.execute("INSERT INTO users (user_id, balance) VALUES (?, ?)", (user_id, 1000))
        return 1000

def update_balance(user_id, amount):
    # amount может быть отрицательным (ставка) или положительным (выигрыш)
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        return conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]

# === ЛОГИКА ИГРЫ ===
game_state = {
    "status": "WAITING", 
    "multiplier": 1.00,
    "history": [],
    "active_bets": {} # user_id: bet_amount
}

async def game_engine():
    print("🚀 ENGINE STARTED")
    while True:
        # 1. ОЖИДАНИЕ
        game_state["status"] = "WAITING"
        game_state["multiplier"] = 1.00
        game_state["active_bets"] = {} # Сброс ставок
        await sio.emit('game_update', {"status": "WAITING", "history": game_state["history"]})
        await asyncio.sleep(8) # 8 секунд на ставки

        # 2. ПОЛЕТ
        game_state["status"] = "FLYING"
        
        # Генерация краша (Алгоритм)
        crash_point = round(0.99 / (1 - random.random()), 2)
        if crash_point > 10: crash_point = float(random.randint(10, 50)) # Иногда даем большие иксы
        if random.random() < 0.05: crash_point = 1.00 # 5% мгновенный краш
        
        print(f"New Round! Crash at: {crash_point}x")

        start_time = asyncio.get_event_loop().time()
        
        while game_state["multiplier"] < crash_point:
            # Расчет множителя по времени (экспонента)
            now = asyncio.get_event_loop().time()
            elapsed = now - start_time
            game_state["multiplier"] = round(1.0 + (0.06 * elapsed + 0.06 * (elapsed**2)), 2)
            
            if game_state["multiplier"] >= crash_point:
                game_state["multiplier"] = crash_point
                break
                
            await sio.emit('tick', game_state["multiplier"])
            await asyncio.sleep(0.1)

        # 3. КРАШ
        game_state["status"] = "CRASHED"
        game_state["history"].insert(0, game_state["multiplier"])
        game_state["history"] = game_state["history"][:8]
        
        await sio.emit('crash', {"multiplier": game_state["multiplier"]})
        await asyncio.sleep(3)

# === SOCKET EVENTS (ОБЩЕНИЕ С КЛИЕНТОМ) ===
@sio.on('connect')
async def connect(sid, environ):
    # При подключении отправляем текущее состояние
    await sio.emit('game_update', {"status": game_state["status"], "history": game_state["history"]}, room=sid)

@sio.on('auth')
async def authenticate(sid, data):
    # Клиент присылает свой ID, мы возвращаем баланс
    user_id = int(data['user_id'])
    balance = get_balance(user_id)
    # Сохраняем user_id в сессии сокета
    async with sio.session(sid) as session:
        session['user_id'] = user_id
    await sio.emit('balance_update', balance, room=sid)

@sio.on('place_bet')
async def place_bet(sid, amount):
    if game_state["status"] != "WAITING": return
    
    async with sio.session(sid) as session:
        user_id = session.get('user_id')
        if not user_id: return
        
        current_bal = get_balance(user_id)
        if current_bal >= amount:
            new_bal = update_balance(user_id, -amount)
            game_state["active_bets"][user_id] = amount
            await sio.emit('balance_update', new_bal, room=sid)
            await sio.emit('bet_confirmed', amount, room=sid)

@sio.on('cash_out')
async def cash_out(sid):
    if game_state["status"] != "FLYING": return

    async with sio.session(sid) as session:
        user_id = session.get('user_id')
        bet = game_state["active_bets"].get(user_id)
        
        if bet:
            # Игрок забирает выигрыш
            win = int(bet * game_state["multiplier"])
            new_bal = update_balance(user_id, win)
            del game_state["active_bets"][user_id] # Удаляем ставку, чтобы не забрал дважды
            
            await sio.emit('balance_update', new_bal, room=sid)
            await sio.emit('win_notification', win, room=sid)

# === БОТ ===
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    # Передаем ID пользователя в URL, чтобы сайт знал, кто зашел
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
    # Bothost сам прокинет порт 8080 на внешний домен
    web.run_app(app, port=8080)
