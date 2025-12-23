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

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN") 
DB_NAME = "casino_pro.db"

# Настройки игры Сапер
MINES_COUNT = 3  # Количество мин на поле
GRID_SIZE = 25   # Поле 5x5

# Инициализация
bot = Bot(token=TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Создаем таблицу с двумя балансами
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                real_balance INTEGER DEFAULT 0,
                demo_balance INTEGER DEFAULT 10000,
                current_mode TEXT DEFAULT 'demo'
            )
        """)
        await db.commit()

# Получить данные пользователя (баланс и режим)
async def get_user_data(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT real_balance, demo_balance, current_mode FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {"real": row[0], "demo": row[1], "mode": row[2]}
            else:
                # Регистрация нового
                await db.execute("INSERT INTO users (user_id, real_balance, demo_balance, current_mode) VALUES (?, ?, ?, ?)", 
                                 (user_id, 0, 10000, "demo"))
                await db.commit()
                return {"real": 0, "demo": 10000, "mode": "demo"}

# Изменить баланс
async def update_balance(user_id, amount, mode):
    column = "real_balance" if mode == "real" else "demo_balance"
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f"UPDATE users SET {column} = {column} + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

# Переключить режим
async def toggle_mode(user_id):
    data = await get_user_data(user_id)
    new_mode = "real" if data['mode'] == "demo" else "demo"
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET current_mode = ? WHERE user_id = ?", (new_mode, user_id))
        await db.commit()
    return new_mode

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def format_balance(amount):
    return f"{amount:,}".replace(",", ".")

# --- КЛАВИАТУРЫ ---
def main_menu_kb(mode):
    mode_text = "🟢 DEMO (Тест)" if mode == "demo" else "🔴 REAL (Деньги)"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Игры", callback_data="games_menu")],
        [InlineKeyboardButton(text=f"🔄 Режим: {mode_text}", callback_data="switch_mode")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")]
    ])

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

# --- ХЕНДЛЕРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    data = await get_user_data(user_id)
    text = (
        f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        f"Добро пожаловать в <b>EasyWin Casino</b>.\n"
        f"Мы начислили тебе <b>10.000 DEMO</b> фишек для теста тактик.\n"
        f"Когда будешь готов — переключайся на реальный счет!"
    )
    await message.answer(text, reply_markup=main_menu_kb(data['mode']), parse_mode="HTML")

@dp.callback_query(F.data == "main_menu")
async def cb_menu(callback: CallbackQuery):
    data = await get_user_data(callback.from_user.id)
    try:
        await callback.message.edit_text("Главное меню:", reply_markup=main_menu_kb(data['mode']))
    except TelegramBadRequest:
        await callback.message.answer("Главное меню:", reply_markup=main_menu_kb(data['mode']))

@dp.callback_query(F.data == "switch_mode")
async def cb_switch(callback: CallbackQuery):
    new_mode = await toggle_mode(callback.from_user.id)
    data = await get_user_data(callback.from_user.id)
    
    mode_name = "DEMO" if new_mode == "demo" else "REAL"
    bal = data['demo'] if new_mode == "demo" else data['real']
    
    await callback.answer(f"Режим изменен на {mode_name}\nБаланс: {bal}", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=main_menu_kb(new_mode))

@dp.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    data = await get_user_data(callback.from_user.id)
    text = (
        f"👤 <b>Твой профиль:</b>\n\n"
        f"🆔 ID: <code>{callback.from_user.id}</code>\n"
        f"💵 Real Balance: <b>{format_balance(data['real'])}</b>\n"
        f"🕹 Demo Balance: <b>{format_balance(data['demo'])}</b>\n\n"
        f"Текущий режим: <b>{data['mode'].upper()}</b>"
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]]), parse_mode="HTML")

@dp.callback_query(F.data == "games_menu")
async def cb_games(callback: CallbackQuery):
    await callback.message.edit_text("🔥 Выбери игру:", reply_markup=games_kb())

# --- ЛОГИКА СТАВОК (CONST) ---
BET_AMOUNT = 100 # Фиксированная ставка для простоты. В идеале сделать ввод суммы.

async def check_balance(user_id, amount):
    data = await get_user_data(user_id)
    balance = data['demo'] if data['mode'] == 'demo' else data['real']
    if balance < amount:
        return False, data['mode']
    return True, data['mode']

# --- DICE / SPORT / SLOTS ---
@dp.callback_query(F.data.startswith("dice_") | F.data.startswith("game_") & (F.data != "game_mines_menu"))
async def process_simple_games(callback: CallbackQuery):
    if "mines" in callback.data: return # Игнорируем сапера здесь

    user_id = callback.from_user.id
    can_play, mode = await check_balance(user_id, BET_AMOUNT)
    
    if not can_play:
        await callback.answer(f"Недостаточно средств на {mode.upper()} счете!", show_alert=True)
        return

    # Списываем ставку
    await update_balance(user_id, -BET_AMOUNT, mode)
    
    # Определяем игру
    game_type = callback.data
    emoji = "🎲"
    game_name = "Кубик"
    
    if "basket" in game_type: emoji, game_name = "🏀", "Баскетбол"
    elif "foot" in game_type: emoji, game_name = "⚽", "Футбол"
    elif "darts" in game_type: emoji, game_name = "🎯", "Дартс"
    elif "bowl" in game_type: emoji, game_name = "🎳", "Боулинг"
    elif "slots" in game_type: emoji, game_name = "🎰", "Слоты"

    msg = await callback.message.answer_dice(emoji=emoji)
    val = msg.dice.value
    await asyncio.sleep(3.5) # Ждем анимацию

    win = False
    coeff = 0
    
    # Логика побед
    if emoji == "🎰":
        if val == 64: coeff = 5; win = True # 777
        elif val in [1, 22, 43]: coeff = 3; win = True # Ягоды
    elif emoji == "🏀":
        if val in [4, 5]: coeff = 2; win = True
    elif emoji == "⚽":
        if val in [3, 4, 5]: coeff = 2; win = True
    elif emoji == "🎯":
        if val == 6: coeff = 3; win = True # Центр
    elif emoji == "🎳":
        if val == 6: coeff = 3; win = True # Страйк
    elif emoji == "🎲":
        # Логика из ТЗ
        bet = callback.data
        if bet == "dice_over_4" and val > 4: coeff = 2; win = True
        elif bet == "dice_under_4" and val < 4: coeff = 2; win = True
        elif bet == "dice_hard" and val in [5, 6]: coeff = 2.5; win = True

    result_text = ""
    if win:
        win_sum = int(BET_AMOUNT * coeff)
        await update_balance(user_id, win_sum, mode)
        result_text = f"✅ <b>Победа!</b> (+{win_sum})"
    else:
        result_text = "❌ <b>Поражение.</b>"

    kb = dice_bet_kb() if "dice" in game_type else games_kb()
    if "dice" not in game_type:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Играть снова", callback_data=game_type)], [InlineKeyboardButton(text="🔙 Меню", callback_data="games_menu")]])

    await callback.message.answer(
        f"{game_name} | Ставка: {BET_AMOUNT} ({mode.upper()})\nРезультат: {val}\n{result_text}",
        reply_markup=kb,
        parse_mode="HTML"
    )

# --- САПЕР (MINES) PROFESSIONAL ---
# Хранилище активных игр в памяти (быстрый доступ)
mines_sessions = {}

def get_mines_coeff(steps_ok):
    # Математическая формула сапера
    # k = C(Total, Mines) / C(Total - Step, Mines)
    # Упрощенная логика умножения шансов:
    # 3 мины, 25 ячеек.
    # Шаг 1: 22/25 безопасно. Коэф = 1 / 0.88 = 1.13
    # Шаг 2: 21/24 безопасно. Коэф = 1.13 * (24/21) = 1.29
    
    current_coeff = 1.0
    remaining_cells = 25
    remaining_safe = 25 - MINES_COUNT
    
    for _ in range(steps_ok):
        chance = remaining_safe / remaining_cells
        current_coeff = current_coeff * (1 / chance)
        remaining_cells -= 1
        remaining_safe -= 1
        
    return round(current_coeff, 2)

def mines_field_kb(user_id, game_data, revealed=False):
    # Генерация поля 5x5
    keyboard = []
    grid = game_data['grid'] # [0, 1, 0...] 1=mina
    opens = game_data['opens'] # индексы открытых
    
    for row in range(5):
        row_btns = []
        for col in range(5):
            idx = row * 5 + col
            text = "⬜️"
            cb_data = f"m_step_{idx}"
            
            if idx in opens:
                text = "💎" # Уже открытый алмаз
                cb_data = "ignore"
            elif revealed and grid[idx] == 1:
                text = "💣" # Показываем бомбы при проигрыше
                cb_data = "ignore"
            elif revealed and grid[idx] == 0:
                text = "dim" # Показываем остальные (можно оставить пустыми или затемнить)
                cb_data = "ignore"
            
            row_btns.append(InlineKeyboardButton(text=text, callback_data=cb_data))
        keyboard.append(row_btns)
    
    # Кнопка "Забрать деньги" если сделан хотя бы 1 шаг
    if not revealed:
        steps = len(opens)
        if steps > 0:
            coeff = get_mines_coeff(steps)
            win_amount = int(BET_AMOUNT * coeff)
            keyboard.append([InlineKeyboardButton(text=f"💰 ЗАБРАТЬ: {win_amount} ({coeff}x)", callback_data="m_cashout")])
    else:
        keyboard.append([InlineKeyboardButton(text="🔄 Играть снова", callback_data="game_mines_menu")])
        keyboard.append([InlineKeyboardButton(text="🔙 Меню", callback_data="games_menu")])
        
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@dp.callback_query(F.data == "game_mines_menu")
async def start_mines_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        f"💣 <b>Mines (Сапер)</b>\n"
        f"Поле: 5x5 | Мины: {MINES_COUNT}\n"
        f"Ставка: {BET_AMOUNT} фишек\n"
        f"Цель: Открывай ячейки, не наткнись на бомбу. Коэффициент растет с каждым шагом!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 НАЧАТЬ ИГРУ", callback_data="m_start")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
        ]),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "m_start")
async def m_start_game(callback: CallbackQuery):
    user_id = callback.from_user.id
    can_play, mode = await check_balance(user_id, BET_AMOUNT)
    
    if not can_play:
        await callback.answer("Недостаточно средств!", show_alert=True)
        return

    await update_balance(user_id, -BET_AMOUNT, mode)
    
    # Генерация мин
    # 0 - пусто, 1 - мина
    grid = [0] * 25
    bomb_indices = random.sample(range(25), MINES_COUNT)
    for idx in bomb_indices:
        grid[idx] = 1
        
    mines_sessions[user_id] = {
        "grid": grid,
        "opens": [], # Индексы открытых ячеек
        "active": True,
        "mode": mode
    }
    
    await callback.message.edit_text(
        "💣 <b>Mines</b>: Делай ход!",
        reply_markup=mines_field_kb(user_id, mines_sessions[user_id]),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("m_step_"))
async def m_step(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in mines_sessions or not mines_sessions[user_id]['active']:
        await callback.answer("Сессия истекла")
        return
        
    idx = int(callback.data.split("_")[2])
    session = mines_sessions[user_id]
    
    if session['grid'][idx] == 1:
        # ВЗРЫВ
        session['active'] = False
        await callback.message.edit_text(
            "💥 <b>БАБАХ! Ты подорвался!</b>\nСтавка сгорела.",
            reply_markup=mines_field_kb(user_id, session, revealed=True),
            parse_mode="HTML"
        )
    else:
        # УСПЕХ
        session['opens'].append(idx)
        steps = len(session['opens'])
        coeff = get_mines_coeff(steps)
        next_coeff = get_mines_coeff(steps + 1)
        
        await callback.message.edit_text(
            f"💎 <b>Успех!</b>\n"
            f"Текущий коэф: <b>x{coeff}</b>\n"
            f"Следующий шаг: <b>x{next_coeff}</b>",
            reply_markup=mines_field_kb(user_id, session),
            parse_mode="HTML"
        )

@dp.callback_query(F.data == "m_cashout")
async def m_cashout(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in mines_sessions: return
    
    session = mines_sessions[user_id]
    if not session['active']: return
    
    steps = len(session['opens'])
    coeff = get_mines_coeff(steps)
    win_amount = int(BET_AMOUNT * coeff)
    
    session['active'] = False
    await update_balance(user_id, win_amount, session['mode'])
    
    await callback.message.edit_text(
        f"💰 <b>Вы забрали деньги!</b>\n\n"
        f"Коэффициент: x{coeff}\n"
        f"Выигрыш: +{win_amount} фишек",
        reply_markup=mines_field_kb(user_id, session, revealed=True),
        parse_mode="HTML"
    )

# --- ЗАПУСК ---
async def main():
    await init_db()
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
