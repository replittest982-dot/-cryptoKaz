import asyncio
import os
import random
import sqlite3
from aiohttp import web
import socketio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton

# === КОНФИГ ===
TOKEN = os.getenv("BOT_TOKEN")
# Ссылка на твой GitHub
WEB_APP_URL = "https://replittest982-dot.github.io/-cryptoKaz/"

# === СЕРВЕР ===
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

# Фикс 404 ошибки
async def index(request):
    return web.Response(text="Epic Crash Server is Running!", content_type='text/html')
app.router.add_get('/', index)

# === БАЗА ДАННЫХ ===
DB_NAME = "casino.db"
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 1000)")

def db_update_balance(user_id, amount):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 1000)", (user_id,))
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        return conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]

def db_get_balance(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        res = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if res: return res[0]
        return 1000

# === ИГРОВОЙ ДВИЖОК ===
game = {
    "status": "WAITING", 
    "m": 1.00, 
    "history": [],
    "bets": {} # {sid: {user_id: 123, amount: 100}}
}

async def game_loop():
    print("🚀 GAME ENGINE STARTED")
    while True:
        # 1. ОЖИДАНИЕ (8 секунд для анимации 3-2-1)
        game["status"] = "WAITING"
        game["m"] = 1.00
        game["bets"] = {}
        await sio.emit('game_update', {"status": "WAITING", "history": game["history"]})
        await asyncio.sleep(8) 

        # 2. ПОЛЕТ
        game["status"] = "FLYING"
        crash = round(0.99 / (1 - random.random()), 2)
        if crash > 30: crash = 30.0 
        
        print(f"Round: {crash}x")
        
        # Уведомляем о старте
        await sio.emit('game_start', {"crash": 0}) # crash скрыт от клиента

        while game["m"] < crash:
            game["m"] = round(game["m"] * 1.06 + 0.01, 2)
            if game["m"] >= crash: 
                game["m"] = crash
                break
            
            await sio.emit('tick', game["m"])
            await asyncio.sleep(0.15) # Тик обновления

        # 3. КРАШ
        game["status"] = "CRASHED"
        game["history"].insert(0, crash)
        game["history"] = game["history"][:8]
        await sio.emit('crash', {"m": crash})
        await asyncio.sleep(4)

# === СОКЕТЫ ===
@sio.on('connect')
async def connect(sid, environ):
    await sio.emit('game_update', {"status": game["status"], "history": game["history"]})

@sio.on('auth')
async def auth(sid, data):
    user_id = int(data['user_id'])
    async with sio.session(sid) as session:
        session['user_id'] = user_id
    bal = db_get_balance(user_id)
    await sio.emit('balance', bal, room=sid)

@sio.on('place_bet')
async def place_bet(sid, amount):
    if game["status"] != "WAITING": return
    async with sio.session(sid) as session:
        uid = session.get('user_id')
        if not uid: return
        if db_get_balance(uid) >= amount:
            new_bal = db_update_balance(uid, -amount)
            game["bets"][sid] = {"uid": uid, "amt": amount}
            await sio.emit('balance', new_bal, room=sid)
            await sio.emit('bet_confirmed', amount, room=sid)

@sio.on('cash_out')
async def cash_out(sid):
    if game["status"] != "FLYING": return
    bet = game["bets"].get(sid)
    if bet:
        win = int(bet["amt"] * game["m"])
        new_bal = db_update_balance(bet["uid"], win)
        del game["bets"][sid]
        await sio.emit('balance', new_bal, room=sid)
        await sio.emit('win', win, room=sid)

# === БОТ ===
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: types.Message):
    url = f"{WEB_APP_URL}?user_id={message.from_user.id}"
    kb = [[KeyboardButton(text="🚀 PLAY EPIC CRASH", web_app=WebAppInfo(url=url))]]
    await message.answer("Играй с друзьями в реальном времени:", reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))

async def on_startup(app):
    init_db()
    asyncio.create_task(game_loop())
    asyncio.create_task(dp.start_polling(bot))

app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=3000)
