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
# Токен бота берем из переменных среды или вставляем сюда
TOKEN = os.getenv("BOT_TOKEN") 
# Твоя ссылка на GitHub Pages
WEB_APP_URL = "https://replittest982-dot.github.io/-cryptoKaz/"

# Включаем логирование, чтобы видеть ошибки в консоли Bothost
logging.basicConfig(level=logging.INFO)

# === СЕРВЕР И CORS (ОЧЕНЬ ВАЖНО) ===
# cors_allowed_origins='*' разрешает подключение с любого сайта (GitHub)
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

# Хелс-чек для проверки, жив ли сервер (Frontend будет пинговать это)
async def index(request):
    return web.Response(
        text="ScarFace Backend is LIVE 🚀", 
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS"
        }
    )

app.router.add_get('/', index)

# === БАЗА ДАННЫХ ===
DB_NAME = "scarface_hub.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        # User ID, Баланс (REAL для дробных), Реферер ID
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, 
            balance REAL DEFAULT 1000.0, 
            referrer_id INTEGER
        )""")

def db_get_user(user_id, ref_id=None):
    with sqlite3.connect(DB_NAME) as conn:
        user = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not user:
            # Регистрация нового игрока + бонус
            conn.execute("INSERT INTO users (user_id, balance, referrer_id) VALUES (?, 1000.0, ?)", (user_id, ref_id))
            conn.commit()
            return 1000.0
        return user[0]

def db_update_balance(user_id, amount):
    with sqlite3.connect(DB_NAME) as conn:
        # Логика рефералки: 0.5% от ПОПОЛНЕНИЯ (если amount > 0)
        # В данной логике amount > 0 это выигрыш, но давай считать это доходом для друга
        if amount > 0:
            ref = conn.execute("SELECT referrer_id FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if ref and ref[0]:
                bonus = round(amount * 0.005, 2) # 0.5%
                if bonus >= 0.01:
                    conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, ref[0]))
        
        # Обновление баланса игрока
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        return conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]

# === ИГРОВОЙ ДВИЖОК (CRASH) ===
game = {
    "status": "WAITING", 
    "m": 1.00, 
    "history": [], 
    "bets": {} 
}

async def game_loop():
    print("✅ Game Engine Started")
    while True:
        # 1. ОЖИДАНИЕ СТАВОК (8 сек)
        game["status"] = "WAITING"
        game["m"] = 1.00
        game["bets"] = {}
        # Отправляем инфо всем, что новый раунд
        await sio.emit('game_update', {"status": "WAITING", "history": game["history"], "players": []})
        await asyncio.sleep(8) 

        # 2. ПОЛЕТ РАКЕТЫ
        game["status"] = "FLYING"
        # Генерация краша (RTP ~96%)
        crash_point = round(max(1.0, 0.96 / (1 - random.random())), 2)
        print(f"🚀 New Round: Crash at {crash_point}x")
        
        start_time = asyncio.get_event_loop().time()
        
        while True:
            # Вычисляем текущий икс
            elapsed = asyncio.get_event_loop().time() - start_time
            # Формула роста (плавная)
            current_m = round(1.0 * (1.06 ** (elapsed * 8)), 2)
            
            # Если долетели до точки краша
            if current_m >= crash_point:
                game["m"] = crash_point
                break
            
            game["m"] = current_m
            # Отправляем тик клиентам
            await sio.emit('tick', current_m)
            # Частота обновления (чем меньше, тем плавнее, но больше нагрузки)
            await asyncio.sleep(0.1)

        # 3. ВЗРЫВ
        game["status"] = "CRASHED"
        game["history"].insert(0, crash_point)
        game["history"] = game["history"][:6] # Храним последние 6
        await sio.emit('crash', {"m": crash_point})
        await asyncio.sleep(4)

# === SOCKET IO СОБЫТИЯ ===
@sio.on('auth')
async def on_auth(sid, data):
    try:
        user_id = int(data.get('user_id'))
        # Сохраняем ID в сессию сокета
        async with sio.session(sid) as session:
            session['uid'] = user_id
        
        # Получаем баланс
        bal = db_get_user(user_id)
        await sio.emit('balance', round(bal, 2), room=sid)
        
        # Отправляем текущее состояние игры новому игроку
        current_players = [{"uid": v["uid"], "bet": v["bet"], "win": v["win"]} for v in game["bets"].values()]
        await sio.emit('game_update', {
            "status": game["status"], 
            "history": game["history"], 
            "players": current_players
        }, room=sid)
        
    except Exception as e:
        print(f"Auth Error: {e}")

@sio.on('place_bet')
async def on_bet(sid, amount):
    if game["status"] != "WAITING": return
    try:
        amount = float(amount)
        if amount < 0.1: return # Мин ставка
        
        async with sio.session(sid) as session:
            uid = session.get('uid')
            if not uid: return
            
            current_bal = db_get_user(uid)
            if current_bal >= amount:
                # Списываем деньги
                new_bal = db_update_balance(uid, -amount)
                # Добавляем ставку
                game["bets"][sid] = {"uid": uid, "bet": amount, "win": 0}
                
                # Обновляем всем список игроков
                p_list = [{"uid": v["uid"], "bet": v["bet"], "win": v["win"]} for v in game["bets"].values()]
                await sio.emit('players_update', p_list)
                
                # Личные обновления
                await sio.emit('balance', round(new_bal, 2), room=sid)
                await sio.emit('bet_ok', room=sid)
    except Exception as e:
        print(f"Bet Error: {e}")

@sio.on('cash_out')
async def on_cashout(sid):
    if game["status"] != "FLYING": return
    try:
        # Проверяем, есть ли ставка и не забрал ли уже
        if sid in game["bets"] and game["bets"][sid]["win"] == 0:
            bet_data = game["bets"][sid]
            current_m = game["m"]
            
            # Считаем выигрыш
            win_amount = round(bet_data["bet"] * current_m, 2)
            
            # Начисляем (тут сработает рефералка 0.5% другу)
            new_bal = db_update_balance(bet_data["uid"], win_amount)
            
            # Помечаем выигрыш
            game["bets"][sid]["win"] = win_amount
            
            # Обновляем список для всех (чтобы видели зеленую цифру)
            p_list = [{"uid": v["uid"], "bet": v["bet"], "win": v["win"]} for v in game["bets"].values()]
            await sio.emit('players_update', p_list)
            
            # Личные уведомления
            await sio.emit('balance', round(new_bal, 2), room=sid)
            await sio.emit('win', win_amount, room=sid)
    except Exception as e:
        print(f"Cashout Error: {e}")

# === TELEGRAM BOT ===
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    # Парсим реферала (/start 12345)
    args = message.text.split()
    ref_id = int(args[1]) if len(args) > 1 and args[1].isdigit() and args[1] != str(message.from_user.id) else None
    
    # Регистрируем/Получаем юзера
    db_get_user(message.from_user.id, ref_id)
    
    # Кнопка WebApp
    url = f"{WEB_APP_URL}?user_id={message.from_user.id}"
    kb = [[KeyboardButton(text="🚀 SCARFACE HUB", web_app=WebAppInfo(url=url))]]
    
    await message.answer(
        f"Добро пожаловать в <b>ScarFace Team</b>! 🦁\nТвой ID: <code>{message.from_user.id}</code>\n\nЖми кнопку ниже, чтобы начать игру!",
        reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True),
        parse_mode="HTML"
    )

# === ЗАПУСК ВСЕГО ===
async def on_startup(app):
    init_db()
    # Запускаем игровой цикл в фоне
    asyncio.create_task(game_loop())
    # Запускаем бота в фоне
    asyncio.create_task(dp.start_polling(bot))

app.on_startup.append(on_startup)

if __name__ == "__main__":
    # Важно: Bothost требует порт 3000 и хост 0.0.0.0
    web.run_app(app, host="0.0.0.0", port=3000)
