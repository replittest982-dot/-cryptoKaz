import asyncio
import os
import random
import sqlite3
import logging
from aiohttp import web
import socketio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton

# === НАСТРОЙКИ ===
# Убедись, что переменная окружения BOT_TOKEN установлена в настройках хостинга!
# Или вставь токен прямо сюда в кавычки для теста: "12345:ABC..."
TOKEN = os.getenv("BOT_TOKEN") 
WEB_APP_URL = "https://replittest982-dot.github.io/-cryptoKaz/"

# Логирование (чтобы видеть ошибки в консоли)
logging.basicConfig(level=logging.INFO)

# === СЕРВЕР ===
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

async def index(request):
    return web.Response(text="ScarFace Server is Running OK!")

app.router.add_get('/', index)

# === БАЗА ДАННЫХ ===
DB_NAME = "scarface.db"
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, 
            balance REAL DEFAULT 1000.0, 
            referrer_id INTEGER
        )""")

def db_get_user(user_id, ref_id=None):
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            conn.execute("INSERT INTO users (user_id, balance, referrer_id) VALUES (?, 1000.0, ?)", (user_id, ref_id))
            conn.commit()
            return 1000.0
        return row[0]

def db_update_balance(user_id, amount):
    with sqlite3.connect(DB_NAME) as conn:
        # Рефералка
        if amount > 0:
            ref = conn.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if ref and ref[0]:
                bonus = round(amount * 0.005, 2)
                if bonus > 0:
                    conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, ref[0]))
        
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        return conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]

# === CRASH GAME ENGINE ===
game = {"status": "WAITING", "m": 1.00, "history": [], "bets": {}}

async def game_loop():
    print("✅ Game Loop Started")
    while True:
        # 1. WAITING
        game["status"] = "WAITING"
        game["m"] = 1.00
        game["bets"] = {}
        await sio.emit('game_update', {"status": "WAITING", "history": game["history"], "players": []})
        await asyncio.sleep(8)

        # 2. FLYING
        game["status"] = "FLYING"
        crash_point = round(max(1.0, 0.97 / (1 - random.random())), 2)
        print(f"🚀 Round: {crash_point}x")
        
        start_time = asyncio.get_event_loop().time()
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            current_m = round(1.0 * (1.06 ** (elapsed * 8)), 2)
            
            if current_m >= crash_point:
                game["m"] = crash_point
                break
            
            game["m"] = current_m
            await sio.emit('tick', current_m)
            await asyncio.sleep(0.1)

        # 3. CRASHED
        game["status"] = "CRASHED"
        game["history"].insert(0, crash_point)
        game["history"] = game["history"][:5]
        await sio.emit('crash', {"m": crash_point})
        await asyncio.sleep(4)

# === SOCKET EVENTS ===
@sio.on('auth')
async def on_auth(sid, data):
    try:
        uid = int(data.get('user_id'))
        async with sio.session(sid) as session: session['uid'] = uid
        bal = db_get_user(uid)
        await sio.emit('balance', round(bal, 2), room=sid)
    except:
        pass

@sio.on('place_bet')
async def on_bet(sid, amount):
    try:
        amount = float(amount)
        if game["status"] != "WAITING" or amount < 0.1: return
        
        async with sio.session(sid) as session:
            uid = session.get('uid')
            if uid:
                bal = db_get_user(uid)
                if bal >= amount:
                    new_bal = db_update_balance(uid, -amount)
                    game["bets"][sid] = {"uid": uid, "bet": amount, "win": 0}
                    
                    p_list = [{"uid": v["uid"], "bet": v["bet"], "win": v["win"]} for v in game["bets"].values()]
                    await sio.emit('balance', round(new_bal, 2), room=sid)
                    await sio.emit('players_update', p_list)
                    await sio.emit('bet_ok', room=sid)
    except: pass

@sio.on('cash_out')
async def on_cashout(sid):
    if game["status"] != "FLYING": return
    if sid in game["bets"] and game["bets"][sid]["win"] == 0:
        bet_data = game["bets"][sid]
        win = round(bet_data["bet"] * game["m"], 2)
        
        new_bal = db_update_balance(bet_data["uid"], win)
        game["bets"][sid]["win"] = win
        
        p_list = [{"uid": v["uid"], "bet": v["bet"], "win": v["win"]} for v in game["bets"].values()]
        await sio.emit('balance', round(new_bal, 2), room=sid)
        await sio.emit('win', win, room=sid)
        await sio.emit('players_update', p_list)

# === TELEGRAM BOT ===
if TOKEN:
    bot = Bot(token=TOKEN)
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def cmd_start(msg: types.Message):
        url = f"{WEB_APP_URL}?user_id={msg.from_user.id}"
        kb = [[KeyboardButton(text="🕹 PLAY SCARFACE", web_app=WebAppInfo(url=url))]]
        await msg.answer("Welcome to ScarFace Team!", reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))

    async def start_bot():
        await dp.start_polling(bot)

# === STARTUP ===
async def on_startup(app):
    init_db()
    asyncio.create_task(game_loop())
    if TOKEN:
        asyncio.create_task(start_bot())

app.on_startup.append(on_startup)

if __name__ == "__main__":
    # Bothost всегда использует порт 3000, слушаем 0.0.0.0
    web.run_app(app, host='0.0.0.0', port=3000)
