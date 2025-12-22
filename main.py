import asyncio
import os
import random
import sqlite3
from aiohttp import web
import socketio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton

# === КОНФИГ ===
TOKEN = os.getenv("BOT_TOKEN") 
# Твой GitHub
WEB_APP_URL = "https://replittest982-dot.github.io/-cryptoKaz/"

# === СЕРВЕР (Fix CORS) ===
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

# Фикс для проверки работоспособности
async def index(request):
    return web.Response(text="ScarFace Backend Online 🚀")
app.router.add_get('/', index)

# === БАЗА ДАННЫХ ===
DB_NAME = "scarface_v2.db"
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        # Баланс храним как REAL для поддержки 0.1
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, 
            balance REAL DEFAULT 1000.0, 
            referrer_id INTEGER
        )""")

def db_get_user(user_id, ref_id=None):
    with sqlite3.connect(DB_NAME) as conn:
        user = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user:
            # Новичок получает 1000
            conn.execute("INSERT INTO users (user_id, balance, referrer_id) VALUES (?, 1000.0, ?)", (user_id, ref_id))
            conn.commit()
            return 1000.0
        return user[0]

def db_update_balance(user_id, amount):
    with sqlite3.connect(DB_NAME) as conn:
        # Рефералка 0.5% (только при плюсе)
        if amount > 0:
            user = conn.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if user and user[0]:
                bonus = round(amount * 0.005, 2)
                if bonus > 0.01:
                    conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, user[0]))
        
        # Обновляем баланс игрока
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        return conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]

# === CRASH LOGIC ===
game = {"status": "WAITING", "m": 1.00, "history": [], "bets": {}}

async def game_loop():
    print("🔥 ENGINE STARTED")
    while True:
        game["status"] = "WAITING"
        game["m"] = 1.00
        game["bets"] = {}
        await sio.emit('game_update', {"status": "WAITING", "history": game["history"], "players": []})
        await asyncio.sleep(8) 

        game["status"] = "FLYING"
        # RTP 97%
        crash = round(max(1.0, 0.97 / (1 - random.random())), 2)
        print(f"Next crash: {crash}x")
        
        start_time = asyncio.get_event_loop().time()
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            current_m = round(1.0 * (1.06 ** (elapsed * 8)), 2)
            
            if current_m >= crash:
                game["m"] = crash
                break
            
            game["m"] = current_m
            await sio.emit('tick', current_m)
            await asyncio.sleep(0.1)

        game["status"] = "CRASHED"
        game["history"].insert(0, crash)
        game["history"] = game["history"][:5]
        await sio.emit('crash', {"m": crash})
        await asyncio.sleep(4)

# === SOCKETS ===
@sio.on('auth')
async def on_auth(sid, data):
    uid = int(data.get('user_id', 0))
    async with sio.session(sid) as session: session['uid'] = uid
    bal = db_get_user(uid)
    await sio.emit('balance', round(bal, 2), room=sid)

@sio.on('place_bet')
async def on_bet(sid, amount):
    try:
        amount = float(amount)
    except: return

    if game["status"] != "WAITING" or amount < 0.1: return
    
    async with sio.session(sid) as session:
        uid = session.get('uid')
        if not uid: return
        
        bal = db_get_user(uid)
        if bal >= amount:
            new_bal = db_update_balance(uid, -amount)
            game["bets"][sid] = {"uid": uid, "bet": amount, "win": 0}
            
            # Отправляем список (анонимизированный)
            p_list = [{"uid": v["uid"], "bet": v["bet"], "win": v["win"]} for v in game["bets"].values()]
            
            await sio.emit('balance', round(new_bal, 2), room=sid)
            await sio.emit('players_update', p_list)
            await sio.emit('bet_ok', room=sid)

@sio.on('cash_out')
async def on_cashout(sid):
    if game["status"] != "FLYING": return
    if sid in game["bets"] and game["bets"][sid]["win"] == 0:
        bet_data = game["bets"][sid]
        win = round(bet_data["bet"] * game["m"], 2)
        
        new_bal = db_update_balance(bet_data["uid"], win)
        game["bets"][sid]["win"] = win
        
        p_list = [{"uid": v["uid"], "bet": v["bet"], "win": v["win"]} for v in game["bets"].values()]
        await sio.emit('players_update', p_list)
        await sio.emit('balance', round(new_bal, 2), room=sid)
        await sio.emit('win', win, room=sid)

# === BOT ===
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start(msg: types.Message):
    url = f"{WEB_APP_URL}?user_id={msg.from_user.id}"
    kb = [[KeyboardButton(text="🕹 OPEN SCARFACE HUB", web_app=WebAppInfo(url=url))]]
    await msg.answer("<b>ScarFace Team Hub</b>\nДоступ к играм открыт.", reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True), parse_mode="HTML")

async def on_startup(app):
    init_db()
    asyncio.create_task(game_loop())
    asyncio.create_task(dp.start_polling(bot))

app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=3000)
