import asyncio
import logging
import os
import random
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv

# --- КОНФИГУРАЦИЯ ---
# Загружаем переменные (для локального теста через .env, на хостинге берется из настроек)
load_dotenv()

# Основные переменные
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Получаем ID админа и превращаем в число. Если не задан - будет 0 (никто не админ)
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# Настройки БД и игр
DB_NAME = "casino_pro.db"
MINES_COUNT = 3  
BET_AMOUNT = 100 # Размер ставки (можно вынести в переменные)

# Проверка токена
if not BOT_TOKEN:
    exit("Error: BOT_TOKEN variable is missing!")

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# --- БАЗА ДАННЫХ (Async SQLite) ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Создаем таблицу пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                real_balance INTEGER DEFAULT 0,
                demo_balance INTEGER DEFAULT 10000,
                current_mode TEXT DEFAULT 'demo',
                username TEXT
            )
        """)
        await db.commit()

async def get_user_data(user_id, username=None):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT real_balance, demo_balance, current_mode FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                # Если юзер есть, обновляем юзернейм (на случай смены)
                if username:
                    await db.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
                    await db.commit()
                return {"real": row[0], "demo": row[1], "mode": row[2]}
            else:
                # Регистрируем нового
                await db.execute("INSERT INTO users (user_id, real_balance, demo_balance, current_mode, username) VALUES (?, ?, ?, ?, ?)", 
                                 (user_id, 0, 10000, "demo", username))
                await db.commit()
                return {"real": 0, "demo": 10000, "mode": "demo"}

async def update_balance(user_id, amount, mode):
    column = "real_balance" if mode == "real" else "demo_balance"
    async with aiosqlite.connect(DB_NAME) as db:
        # Обновляем баланс
        await db.execute(f"UPDATE users SET {column} = {column} + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def toggle_mode(user_id):
    data = await get_user_data(user_id)
    new_mode = "real" if data['mode'] == "demo" else "demo"
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET current_mode = ? WHERE user_id = ?", (new_mode, user_id))
        await db.commit()
    return new_mode

async def get_all_users_count():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

def format_balance(amount):
    return f"{amount:,}".replace(",", ".")

# --- КЛАВИАТУРЫ ---
def main_menu_kb(user_id, mode):
    mode_text = "🟢 DEMO" if mode == "demo" else "🔴 REAL"
    
    # Основные кнопки
    buttons = [
        [InlineKeyboardButton(text="🎮 Игры Казино", callback_data="games_menu")],
        [InlineKeyboardButton(text=f"🔄 Режим: {mode_text}", callback_data="switch_mode")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")]
    ]
    
    # Кнопка АДМИНА (видна только если ID совпадает)
    if user_id == ADMIN_ID:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ Панель", callback_data="admin_panel")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def games_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💣 Сапер (Mines)", callback_data="game_mines_menu")],
        [InlineKeyboardButton(text="🎲 Кубик", callback_data="game_dice")],
        [InlineKeyboardButton(text="🏀 Баскет", callback_data="game_basket"), InlineKeyboardButton(text="⚽ Футбол", callback_data="game_foot")],
        [InlineKeyboardButton(text="🎯 Дартс", callback_data="game_darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="game_bowl")],
        [InlineKeyboardButton(text="🎰 Слоты (777)", callback_data="game_slots")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
    ])

def dice_bet_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Больше 4 (x2.0)", callback_data="dice_over_4")],
        [InlineKeyboardButton(text="Меньше 4 (x2.0)", callback_data="dice_under_4")],
        [InlineKeyboardButton(text="Точное 5 или 6 (x2.5)", callback_data="dice_hard")], 
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
    ])

# --- ЛОГИКА СТАРТА И МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    data = await get_user_data(user_id, username)
    
    text = (
        f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        f"Добро пожаловать в <b>Casino Bot Pro</b>.\n"
        f"Твой баланс: <b>{format_balance(data['demo'] if data['mode'] == 'demo' else data['real'])}</b>\n\n"
        f"<i>Выбери игру или смени режим ниже:</i>"
    )
    await message.answer(text, reply_markup=main_menu_kb(user_id, data['mode']), parse_mode="HTML")

@dp.callback_query(F.data == "main_menu")
async def cb_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    data = await get_user_data(user_id)
    try:
        await callback.message.edit_text("🏠 Главное меню:", reply_markup=main_menu_kb(user_id, data['mode']))
    except TelegramBadRequest:
        # Если сообщение не изменилось
        await callback.answer()

@dp.callback_query(F.data == "switch_mode")
async def cb_switch(callback: CallbackQuery):
    user_id = callback.from_user.id
    new_mode = await toggle_mode(user_id)
    # Обновляем клавиатуру с новым статусом
    try:
        await callback.message.edit_reply_markup(reply_markup=main_menu_kb(user_id, new_mode))
        await callback.answer(f"Режим изменен на {new_mode.upper()}")
    except TelegramBadRequest:
        await callback.answer()

@dp.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    data = await get_user_data(callback.from_user.id)
    text = (
        f"👤 <b>Личный кабинет</b>\n\n"
        f"🆔 ID: <code>{callback.from_user.id}</code>\n"
        f"💳 Real Balance: <b>{format_balance(data['real'])}</b>\n"
        f"🕹 Demo Balance: <b>{format_balance(data['demo'])}</b>\n"
        f"⚙️ Текущий режим: <b>{data['mode'].upper()}</b>"
    )
    back_btn = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]])
    await callback.message.edit_text(text, reply_markup=back_btn, parse_mode="HTML")

# --- АДМИН ПАНЕЛЬ ---
@dp.callback_query(F.data == "admin_panel")
async def cb_admin(callback: CallbackQuery):
    # Двойная проверка безопасности
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("⛔ Доступ запрещен!", show_alert=True)
    
    users_count = await get_all_users_count()
    
    text = (
        f"🔒 <b>Панель Администратора</b>\n\n"
        f"👥 Всего пользователей: {users_count}\n"
        f"✅ Бот активен и работает.\n"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

# --- МЕНЮ ИГР ---
@dp.callback_query(F.data == "games_menu")
async def cb_games(callback: CallbackQuery):
    await callback.message.edit_text("🔥 Выбери игру:", reply_markup=games_kb())

# --- ЛОГИКА ДАЙСОВ, СЛОТОВ И СПОРТА ---
async def check_balance(user_id, amount):
    data = await get_user_data(user_id)
    balance = data['demo'] if data['mode'] == 'demo' else data['real']
    return (balance >= amount), data['mode']

@dp.callback_query(F.data.startswith("dice_") | F.data.startswith("game_") & (F.data != "game_mines_menu"))
async def process_dice_games(callback: CallbackQuery):
    if "mines" in callback.data: return 
    
    user_id = callback.from_user.id
    can_play, mode = await check_balance(user_id, BET_AMOUNT)
    
    if not can_play: 
        return await callback.answer(f"Недостаточно средств на {mode.upper()}!", show_alert=True)

    # Списываем ставку
    await update_balance(user_id, -BET_AMOUNT, mode)
    
    game_type = callback.data
    
    # Настройки игр
    config = {
        "game_basket": ("🏀", "Баскетбол"), 
        "game_foot": ("⚽", "Футбол"),
        "game_darts": ("🎯", "Дартс"), 
        "game_bowl": ("🎳", "Боулинг"),
        "game_slots": ("🎰", "Слоты"), 
        "game_dice": ("🎲", "Кубик")
    }
    
    # Если это ставка внутри Dice (больше/меньше), ставим эмодзи кубика
    emoji = "🎲"
    name = "Кубик"
    if game_type in config:
        emoji, name = config[game_type]
    
    await callback.message.answer(f"🎲 Ставка принята: {BET_AMOUNT} ({mode.upper()})...")
    msg = await callback.message.answer_dice(emoji=emoji)
    val = msg.dice.value
    
    # Ждем анимацию
    await asyncio.sleep(3.5)

    win = False
    coeff = 0
    
    # Логика расчета
    if emoji == "🎰":
        if val == 64: coeff, win = 5, True # Три семерки
        elif val in [1, 22, 43]: coeff, win = 3, True # Три винограда/бара
        elif val in [16, 32, 48]: coeff, win = 2, True # Две штуки
    elif emoji == "🏀" and val in [4, 5]: coeff, win = 2, True
    elif emoji == "⚽" and val in [3, 4, 5]: coeff, win = 2, True
    elif emoji in ["🎯", "🎳"] and val == 6: coeff, win = 3, True
    elif emoji == "🎲":
        # Логика для ставок больше/меньше
        if "over_4" in game_type and val > 4: coeff, win = 2, True
        elif "under_4" in game_type and val < 4: coeff, win = 2, True
        elif "hard" in game_type and val in [5, 6]: coeff, win = 2.5, True
        elif game_type == "game_dice":
             # Если просто нажали "Кубик" без выбора стратегии - считаем победой 4,5,6 (простой режим)
             if val >= 4: coeff, win = 2, True

    if win:
        win_sum = int(BET_AMOUNT * coeff)
        await update_balance(user_id, win_sum, mode)
        res_text = f"✅ <b>Победа!</b> (+{win_sum})"
    else:
        res_text = "❌ <b>Проигрыш.</b>"

    # Клавиатура возврата
    if emoji == "🎲" and "game_dice" in game_type:
        kb = dice_bet_kb() # Если играем в дайсы - даем выбрать ставку
    else:
        # Кнопка "Играть снова"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Играть снова", callback_data=game_type)],
            [InlineKeyboardButton(text="🔙 Меню", callback_data="games_menu")]
        ])

    await callback.message.answer(
        f"{name} | Результат: {val}\n{res_text}", 
        reply_markup=kb,
        parse_mode="HTML"
    )

# --- ИГРА MINES (САПЕР) ---
# Хранение сессий в памяти (словарь)
mines_sessions = {}

def get_mines_coeff(steps):
    # Простая прогрессия коэффициентов
    # 1 шаг - 1.13, 2 шаг - 1.29 и т.д.
    curr = 1.0
    for i in range(steps):
        curr *= (25 - i) / (25 - MINES_COUNT - i)
    return round(curr, 2)

def mines_field_kb(game_data, revealed=False):
    keyboard = []
    grid = game_data['grid']
    opens = game_data['opens']
    
    for r in range(5):
        row_btns = []
        for c in range(5):
            idx = r * 5 + c
            
            # Логика отображения кнопок
            text = "⬜️"
            cb_data = f"m_step_{idx}"
            
            if idx in opens:
                text = "💎"
                cb_data = "ignore"
            elif revealed:
                if grid[idx] == 1: text, cb_data = "💣", "ignore"
                else: text, cb_data = "🔹", "ignore"
            
            row_btns.append(InlineKeyboardButton(text=text, callback_data=cb_data))
        keyboard.append(row_btns)
    
    # Кнопки управления
    if not revealed:
        if len(opens) > 0:
            coeff = get_mines_coeff(len(opens))
            win_amount = int(BET_AMOUNT * coeff)
            keyboard.append([InlineKeyboardButton(text=f"💰 ЗАБРАТЬ: {win_amount} ({coeff}x)", callback_data="m_cashout")])
    else:
        keyboard.append([InlineKeyboardButton(text="🔄 Играть снова", callback_data="m_start")])
        keyboard.append([InlineKeyboardButton(text="🔙 Меню игр", callback_data="games_menu")])
        
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@dp.callback_query(F.data == "game_mines_menu")
async def m_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        f"💣 <b>Mines (Сапер)</b>\n"
        f"Найди алмазы и не взорвись на мине.\n"
        f"Ставка: {BET_AMOUNT}", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 НАЧАТЬ ИГРУ", callback_data="m_start")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
        ]), 
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "m_start")
async def m_start(callback: CallbackQuery):
    user_id = callback.from_user.id
    can, mode = await check_balance(user_id, BET_AMOUNT)
    
    if not can: 
        return await callback.answer("Недостаточно средств!", show_alert=True)
        
    await update_balance(user_id, -BET_AMOUNT, mode)
    
    # Генерация поля
    grid = [0]*25
    bomb_indices = random.sample(range(25), MINES_COUNT)
    for i in bomb_indices: 
        grid[i] = 1
        
    mines_sessions[user_id] = {
        "grid": grid, 
        "opens": [], 
        "active": True, 
        "mode": mode
    }
    
    await callback.message.edit_text(
        "💣 <b>Mines</b>: Поле сгенерировано. Ходи!", 
        reply_markup=mines_field_kb(mines_sessions[user_id]),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("m_step_"))
async def m_step(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in mines_sessions or not mines_sessions[user_id]['active']: 
        return await callback.answer("Сессия истекла, начни новую игру.")
        
    idx = int(callback.data.split("_")[2])
    session = mines_sessions[user_id]
    
    if session['grid'][idx] == 1:
        # Взрыв
        session['active'] = False
        await callback.message.edit_text(
            "💥 <b>БАБАХ!</b> Ты наступил на мину.", 
            reply_markup=mines_field_kb(session, revealed=True),
            parse_mode="HTML"
        )
    else:
        # Успех
        if idx not in session['opens']:
            session['opens'].append(idx)
        
        coeff = get_mines_coeff(len(session['opens']))
        await callback.message.edit_text(
            f"💎 <b>Чисто!</b> Коэф: x{coeff}", 
            reply_markup=mines_field_kb(session),
            parse_mode="HTML"
        )

@dp.callback_query(F.data == "m_cashout")
async def m_cash(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = mines_sessions.get(user_id)
    
    if not session or not session['active']: return
    
    coeff = get_mines_coeff(len(session['opens']))
    win_sum = int(BET_AMOUNT * coeff)
    
    session['active'] = False
    await update_balance(user_id, win_sum, session['mode'])
    
    await callback.message.edit_text(
        f"💰 <b>Вы забрали выигрыш!</b>\n+{win_sum} фишек", 
        reply_markup=mines_field_kb(session, revealed=True),
        parse_mode="HTML"
    )
    
@dp.callback_query(F.data == "ignore")
async def ignore_click(callback: CallbackQuery):
    await callback.answer()

# --- ЗАПУСК ---
async def main():
    await init_db()
    print("Бот запущен. Ожидание обновлений...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
