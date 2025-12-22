import asyncio
import os
import random
import sqlite3
from aiohttp import web
import socketio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# === НАСТРОЙКИ (ЗАПОЛНИ ЭТО) ===
TOKEN = os.getenv("BOT_TOKEN") 
# Ссылка на твой GitHub Pages (где лежит index.html)
WEB_APP_URL = "https://tvoj-github-username.github.io/repo-name/" 

# === СЕРВЕР ===
# Настройка CORS для доступа с GitHub
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

# === БАЗА ДАННЫХ ===
DB_NAME = "scarface.db"
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, 
            balance INTEGER DEFAULT 0,
            referrer_id INTEGER
        )""")

def db_get_user(user_id, ref_id=None):
    with sqlite3.connect(DB_NAME) as conn:
        user = conn.execute("SELECT balance, referrer_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user:
            # Новый юзер + бонус 100 монет за регистрацию
            conn.execute("INSERT INTO users (user_id, balance, referrer_id) VALUES (?, 100, ?)", (user_id, ref_id))
            conn.commit()
            return 100
        return user[0]

def db_add_balance(user_id, amount):
    with sqlite3.connect(DB_NAME) as conn:
        # Логика рефералки (0.5% при пополнении)
        if amount > 0:
            user = conn.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if user and user[0]: # Если есть реферер
                bonus = int(amount * 0.005) # 0.5%
                if bonus > 0:
                    conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, user[0]))
                    print(f"💰 Реферер {user[0]} получил {bonus} за депозит {user_id}")

        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        return conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]

# === ДВИЖОК CRASH ===
game = {
    "status": "WAITING", 
    "m": 1.00, 
    "history": [], 
    "bets": {} # {sid: {uid, name, bet, win}}
}

async def game_loop():
    while True:
        # 1. Ожидание
        game["status"] = "WAITING"
        game["m"] = 1.00
        game["bets"] = {} # Очищаем игроков (нет фейков)
        await sio.emit('game_update', {"status": "WAITING", "history": game["history"], "players": []})
        await asyncio.sleep(8)

        # 2. Полет
        game["status"] = "FLYING"
        crash_point = round(max(1.0, 0.96 / (1 - random.random())), 2) # RTP ~96%
        print(f"🚀 Round starts. Crash at: {crash_point}x")
        
        start_time = asyncio.get_event_loop().time()
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            current_m = round(1.0 * (1.06 ** (elapsed * 8)), 2)
            
            if current_m >= crash_point:
                game["m"] = crash_point
                break
            
            game["m"] = current_m
            await sio.emit('tick', current_m)
            await asyncio.sleep(0.1) # 10 обновлений в секунду

        # 3. Краш
        game["status"] = "CRASHED"
        game["history"].insert(0, crash_point)
        game["history"] = game["history"][:8]
        await sio.emit('crash', {"m": crash_point})
        await asyncio.sleep(4)

# === SOCKET IO ===
@sio.on('auth')
async def on_auth(sid, data):
    uid = int(data.get('user_id'))
    async with sio.session(sid) as session: session['uid'] = uid
    bal = db_get_user(uid)
    await sio.emit('balance', bal, room=sid)

@sio.on('place_bet')
async def on_bet(sid, amount):
    if game["status"] != "WAITING": return
    async with sio.session(sid) as session:
        uid = session.get('uid')
        current_bal = db_get_user(uid)
        
        if current_bal >= amount and amount > 0:
            new_bal = db_add_balance(uid, -amount)
            # Добавляем РЕАЛЬНОГО игрока
            game["bets"][sid] = {"uid": uid, "name": f"Player {uid}", "bet": amount, "win": 0}
            
            # Отправляем всем новый список
            players_list = list(game["bets"].values())
            await sio.emit('players_update', players_list)
            await sio.emit('balance', new_bal, room=sid)
            await sio.emit('bet_ok', room=sid)

@sio.on('cash_out')
async def on_cashout(sid):
    if game["status"] != "FLYING": return
    if sid in game["bets"] and game["bets"][sid]["win"] == 0:
        bet_data = game["bets"][sid]
        win_amt = int(bet_data["bet"] * game["m"])
        
        new_bal = db_add_balance(bet_data["uid"], win_amt)
        game["bets"][sid]["win"] = win_amt # Помечаем выигрыш
        
        await sio.emit('players_update', list(game["bets"].values()))
        await sio.emit('balance', new_bal, room=sid)
        await sio.emit('win', win_amt, room=sid)

# === TELEGRAM BOT ===
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    # Обработка реферальной ссылки: t.me/Bot?start=123
    args = message.text.split()
    ref_id = int(args[1]) if len(args) > 1 and args[1].isdigit() and args[1] != str(message.from_user.id) else None
    
    db_get_user(message.from_user.id, ref_id) # Регистрация
    
    markup = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🕹 Play ScarFace", web_app=WebAppInfo(url=f"{WEB_APP_URL}?user_id={message.from_user.id}"))]
    ], resize_keyboard=True)
    
    await message.answer(f"Добро пожаловать в <b>ScarFaceTeam</b>!\nТвой ID: <code>{message.from_user.id}</code>", 
                         parse_mode="HTML", reply_markup=markup)

# Команда админа для выдачи денег: /pay ID СУММА
@dp.message(Command("pay"))
async def admin_pay(message: types.Message):
    try:
        _, uid, amt = message.text.split()
        db_add_balance(int(uid), int(amt))
        await message.answer(f"✅ Выдано {amt} монет игроку {uid}")
    except:
        await message.answer("Ошибка. Пиши: /pay ID СУММА")

async def main():
    init_db()
    asyncio.create_task(game_loop())
    asyncio.create_task(dp.start_polling(bot))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 3000)
    await site.start()
    print("✅ ScarFace Server Running on port 3000")
    await asyncio.Event().wait() # Keep alive

if __name__ == "__main__":
    asyncio.run(main())
