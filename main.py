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

# === КОНФИГ ===
TOKEN = os.getenv("BOT_TOKEN") 
WEB_APP_URL = "https://replittest982-dot.github.io/-cryptoKaz/" # Твой URL

logging.basicConfig(level=logging.INFO)
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

# === БАЗА ДАННЫХ ===
DB_NAME = "easywin.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, 
            balance REAL DEFAULT 1000.0
        )""")

def db_process_bet(user_id, amount, is_win, win_amount):
    with sqlite3.connect(DB_NAME) as conn:
        # Списываем ставку
        conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
        # Если победа - начисляем выигрыш
        if is_win:
            conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (win_amount, user_id))
        # Возвращаем новый баланс
        return conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()[0]

def get_balance(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        res = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if not res:
            conn.execute("INSERT INTO users (user_id, balance) VALUES (?, 1000.0)", (user_id,))
            return 1000.0
        return res[0]

# === ЛОГИКА ИГР ===
def play_game(game_type, mode, amount):
    # Генерация результата (имитация кубиков Telegram)
    
    # КУБИК (1-6)
    if game_type == 'cube':
        res = random.randint(1, 6)
        win = False
        coef = 0.0

        if mode == 'over_4': # Больше 4 (5,6)
            win = res > 4
            coef = 2.8
        elif mode == 'under_4': # Меньше или равно 4 (1,2,3,4)
            win = res <= 4
            coef = 1.4
        elif mode == 'even': # Чет
            win = (res % 2) == 0
            coef = 1.9
        elif mode == 'odd': # Нечет
            win = (res % 2) != 0
            coef = 1.9
        elif mode == 'over_5': # Больше 5 (6)
            win = res == 6
            coef = 5.5
        elif mode == 'under_2': # Меньше 2 (1)
            win = res == 1
            coef = 5.5
            
        return res, win, amount * coef

    # ФУТБОЛ (1-5). 1-2 мимо, 3-5 гол
    elif game_type == 'football':
        res = random.randint(1, 5) 
        # Если режим 'goal' (Гол)
        if mode == 'goal':
            win = res >= 3 # Гол это обычно 3,4,5
            coef = 1.6
        else: # Промах
            win = res < 3
            coef = 2.3
        return res, win, amount * coef

    # БАСКЕТБОЛ (1-5). 1-3 мимо, 4-5 попадание
    elif game_type == 'basket':
        res = random.randint(1, 5)
        if mode == 'goal':
            win = res >= 4 
            coef = 2.3
        else:
            win = res < 4
            coef = 1.5
        return res, win, amount * coef

    # ДАРТС (1-6). 1-мимо, 6-центр
    elif game_type == 'darts':
        res = random.randint(1, 6)
        if mode == 'center': # В яблочко
            win = res == 6
            coef = 5.5
        elif mode == 'color': # Красное/Белое (2,3,4,5)
            win = res in [2, 3, 4, 5]
            coef = 1.4
        elif mode == 'miss': # Мимо (1)
            win = res == 1
            coef = 5.5
        return res, win, amount * coef

    # БОУЛИНГ (1-6). 6 - страйк
    elif game_type == 'bowling':
        res = random.randint(1, 6)
        if mode == 'strike':
            win = res == 6
            coef = 5.5
        else: # Не страйк
            win = res != 6
            coef = 1.15
        return res, win, amount * coef

    return 0, False, 0

# === SOCKET EVENTS ===
@sio.on('auth')
async def on_auth(sid, data):
    uid = int(data.get('user_id'))
    async with sio.session(sid) as session: session['uid'] = uid
    bal = get_balance(uid)
    await sio.emit('balance', bal, room=sid)

@sio.on('play')
async def on_play(sid, data):
    # data = {game: 'cube', mode: 'over_4', bet: 100}
    try:
        amount = float(data.get('bet'))
        game_type = data.get('game')
        mode = data.get('mode')
        
        async with sio.session(sid) as session:
            uid = session.get('uid')
            bal = get_balance(uid)
            
            if bal >= amount and amount > 0:
                # Играем
                res_val, is_win, win_amt = play_game(game_type, mode, amount)
                
                # Обновляем БД
                new_bal = db_process_bet(uid, amount, is_win, win_amt)
                
                # Отправляем результат
                await sio.emit('game_result', {
                    'val': res_val,      # Что выпало (число)
                    'win': is_win,       # Победа или нет
                    'win_amt': win_amt,  # Сколько выиграл
                    'balance': new_bal   # Новый баланс
                }, room=sid)

    except Exception as e:
        print(f"Error: {e}")

# === BOT ===
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start(msg: types.Message):
    url = f"{WEB_APP_URL}?user_id={msg.from_user.id}"
    kb = [[KeyboardButton(text="⚡️ EasyWin", web_app=WebAppInfo(url=url))]]
    await msg.answer("Добро пожаловать в EasyWin!", reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))

async def on_startup(app):
    init_db()
    asyncio.create_task(dp.start_polling(bot))

app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=3000)
