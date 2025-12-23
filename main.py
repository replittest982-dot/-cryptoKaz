import asyncio
import logging
import os
import random
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# Файл базы данных
DB_NAME = "casino_v2.db"

# Настройки Сапера
MINES_COUNT = 3  
HOUSE_EDGE = 0.93 # 7% преимущества казино (уменьшает коэф)

if not BOT_TOKEN:
    exit("❌ Ошибка: Нет токена в переменных окружения!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# --- МАШИНА СОСТОЯНИЙ (FSM) ---
class UserState(StatesGroup):
    waiting_for_bet = State() # Ждем ввода суммы ставки

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                real_balance REAL DEFAULT 0.0,
                demo_balance REAL DEFAULT 10000.0,
                current_mode TEXT DEFAULT 'demo',
                current_bet REAL DEFAULT 10.0
            )
        """)
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
                await db.commit()
                return {"user_id": user_id, "real": 0.0, "demo": 10000.0, "mode": "demo", "bet": 10.0}
            return {
                "user_id": row[0], "real": row[1], 
                "demo": row[2], "mode": row[3], "bet": row[4]
            }

async def update_balance(user_id, amount, mode):
    col = "real_balance" if mode == "real" else "demo_balance"
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f"UPDATE users SET {col} = {col} + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def set_bet(user_id, amount):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET current_bet = ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def toggle_mode(user_id):
    user = await get_user(user_id)
    new_mode = "real" if user['mode'] == "demo" else "demo"
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET current_mode = ? WHERE user_id = ?", (new_mode, user_id))
        await db.commit()
    return new_mode

async def get_all_users_count():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0]

def fmt(num):
    # Форматирование числа (убираем .0 если целое)
    if num % 1 == 0:
        return f"{int(num)}"
    return f"{round(num, 2)}"

# --- КЛАВИАТУРЫ ---

def main_kb(user_id, mode, bet):
    mode_txt = "🟢 DEMO" if mode == "demo" else "🔴 REAL"
    btns = [
        [InlineKeyboardButton(text="🎮 Игры", callback_data="games_menu")],
        [InlineKeyboardButton(text=f"💰 Ставка: {fmt(bet)}", callback_data="change_bet")],
        [InlineKeyboardButton(text=f"🔄 Режим: {mode_txt}", callback_data="switch_mode")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")]
    ]
    if user_id == ADMIN_ID:
        btns.append([InlineKeyboardButton(text="⚙️ Админ", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def games_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💣 Сапер", callback_data="game_mines_pre")],
        [InlineKeyboardButton(text="🎲 Кубик", callback_data="pre_dice"), InlineKeyboardButton(text="🎰 Слоты", callback_data="pre_slots")],
        [InlineKeyboardButton(text="🏀 Баскет", callback_data="pre_basket"), InlineKeyboardButton(text="⚽ Футбол", callback_data="pre_foot")],
        [InlineKeyboardButton(text="🎯 Дартс", callback_data="pre_darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="pre_bowl")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="main_menu")]
    ])

# Клавиатуры выбора исходов
def dice_variants_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Больше 4 (5-6) | x2.9", callback_data="play_dice_over4")],
        [InlineKeyboardButton(text="Меньше 4 (1-3) | x1.9", callback_data="play_dice_under4")],
        [InlineKeyboardButton(text="Четное (2,4,6) | x1.9", callback_data="play_dice_even")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
    ])

def sport_variants_kb(sport_type):
    # Для Футбола и Баскета
    emoji = "⚽" if sport_type == "foot" else "🏀"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{emoji} Забьет (Гол) | x1.8", callback_data=f"play_{sport_type}_goal")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
    ])

def darts_variants_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 В яблочко (Центр) | x5.0", callback_data="play_darts_bull")],
        [InlineKeyboardButton(text="🎯 Любое попадание | x1.3", callback_data="play_darts_hit")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
    ])

def slots_variants_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Крутить Слот", callback_data="play_slots_spin")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
    ])

# --- ЛОГИКА МЕНЮ И СТАВОК ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = await get_user(message.from_user.id)
    txt = (f"👋 <b>Привет!</b>\nБаланс: <b>{fmt(user['demo'] if user['mode']=='demo' else user['real'])}</b>\n"
           f"Текущая ставка: <b>{fmt(user['bet'])}</b>")
    await message.answer(txt, reply_markup=main_kb(user['user_id'], user['mode'], user['bet']), parse_mode="HTML")

@dp.callback_query(F.data == "main_menu")
async def cb_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(cb.from_user.id)
    await cb.message.edit_text("🏠 Главное меню:", reply_markup=main_kb(user['user_id'], user['mode'], user['bet']))

@dp.callback_query(F.data == "switch_mode")
async def cb_switch(cb: CallbackQuery):
    await toggle_mode(cb.from_user.id)
    user = await get_user(cb.from_user.id)
    await cb.message.edit_reply_markup(reply_markup=main_kb(user['user_id'], user['mode'], user['bet']))

@dp.callback_query(F.data == "change_bet")
async def cb_change_bet(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("✍️ <b>Введите сумму ставки:</b>\n(Минимум 0.1)", parse_mode="HTML")
    await state.set_state(UserState.waiting_for_bet)

@dp.message(StateFilter(UserState.waiting_for_bet))
async def process_bet_input(msg: Message, state: FSMContext):
    try:
        amount = float(msg.text.replace(",", "."))
        if amount < 0.1:
            await msg.answer("❌ Минимум 0.1")
            return
        await set_bet(msg.from_user.id, amount)
        user = await get_user(msg.from_user.id)
        await msg.answer(f"✅ Ставка изменена на: <b>{fmt(amount)}</b>", 
                         reply_markup=main_kb(user['user_id'], user['mode'], amount), parse_mode="HTML")
        await state.clear()
    except ValueError:
        await msg.answer("❌ Введите число (например 10 или 0.5)")

@dp.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    txt = (f"👤 <b>Профиль</b>\n🆔: <code>{user['user_id']}</code>\n"
           f"💵 Real: <b>{fmt(user['real'])}</b>\n🕹 Demo: <b>{fmt(user['demo'])}</b>\n"
           f"⚙️ Ставка: <b>{fmt(user['bet'])}</b>")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Изменить ставку", callback_data="change_bet")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="main_menu")]
    ])
    await cb.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")

# --- ПРЕД-МЕНЮ ИГР (ВЫБОР ИСХОДА) ---

@dp.callback_query(F.data == "games_menu")
async def cb_games(cb: CallbackQuery):
    await cb.message.edit_text("🔥 Выбери игру:", reply_markup=games_kb())

@dp.callback_query(F.data.startswith("pre_"))
async def cb_pre_game(cb: CallbackQuery):
    game = cb.data.split("_")[1]
    if game == "dice":
        await cb.message.edit_text("🎲 <b>Кубик:</b> Выбери исход", reply_markup=dice_variants_kb(), parse_mode="HTML")
    elif game == "foot":
        await cb.message.edit_text("⚽ <b>Футбол:</b> Выбери исход", reply_markup=sport_variants_kb("foot"), parse_mode="HTML")
    elif game == "basket":
        await cb.message.edit_text("🏀 <b>Баскет:</b> Выбери исход", reply_markup=sport_variants_kb("basket"), parse_mode="HTML")
    elif game == "darts":
        await cb.message.edit_text("🎯 <b>Дартс:</b> Выбери исход", reply_markup=darts_variants_kb(), parse_mode="HTML")
    elif game == "slots":
        await cb.message.edit_text("🎰 <b>Слоты 777:</b>", reply_markup=slots_variants_kb(), parse_mode="HTML")
    elif game == "bowl":
        # Боулинг простой, сразу запуск
        await cb.message.answer("🎳 Запускаю боулинг...", reply_markup=None)
        # Перенаправляем на логику игры
        await run_game(cb, "bowl", "strike") 

# --- ЛОГИКА ЗАПУСКА ИГР ---

@dp.callback_query(F.data.startswith("play_"))
async def cb_play_game(cb: CallbackQuery):
    # data format: play_gameType_variant
    parts = cb.data.split("_") # ['play', 'dice', 'over4']
    game_type = parts[1]
    variant = parts[2]
    await run_game(cb, game_type, variant)

async def run_game(cb: CallbackQuery, game, variant):
    user_id = cb.from_user.id
    user = await get_user(user_id)
    bet = user['bet']
    balance = user['demo'] if user['mode'] == 'demo' else user['real']

    if balance < bet:
        return await cb.answer("❌ Недостаточно средств!", show_alert=True)

    # Списываем
    await update_balance(user_id, -bet, user['mode'])

    emoji_map = {
        "dice": "🎲", "foot": "⚽", "basket": "🏀", 
        "darts": "🎯", "bowl": "🎳", "slots": "🎰"
    }
    emoji = emoji_map.get(game, "🎲")

    await cb.message.answer(f"{emoji} Ставка: <b>{fmt(bet)}</b> на исход...", parse_mode="HTML")
    msg = await cb.message.answer_dice(emoji=emoji)
    val = msg.dice.value
    await asyncio.sleep(3.5) # Ждем анимацию

    win = False
    coeff = 0.0

    # --- ЛОГИКА ПОБЕД ---
    # 🎲 КУБИК
    if game == "dice":
        if variant == "over4": # > 4 (5, 6)
            if val > 4: win = True; coeff = 2.9
        elif variant == "under4": # < 4 (1, 2, 3)
            if val < 4: win = True; coeff = 1.9
        elif variant == "even": # Четное (2,4,6)
            if val % 2 == 0: win = True; coeff = 1.9
    
    # ⚽🏀 СПОРТ (Telegram: 1,2=промах, 3,4,5=гол)
    elif game in ["foot", "basket"]:
        is_goal = val >= 3
        if variant == "goal" and is_goal: win = True; coeff = 1.8
    
    # 🎯 ДАРТС (6=центр)
    elif game == "darts":
        if variant == "bull" and val == 6: win = True; coeff = 5.0
        elif variant == "hit" and val > 1: win = True; coeff = 1.3 # 1 это промах обычно
    
    # 🎰 СЛОТЫ
    elif game == "slots":
        # 64=777, 1/22/43=ягоды/бары
        if val == 64: win = True; coeff = 10.0 # ДЖЕКПОТ
        elif val in [1, 22, 43]: win = True; coeff = 3.0
        elif val in [16, 32, 48]: win = True; coeff = 1.5

    # 🎳 БОУЛИНГ (6=страйк)
    elif game == "bowl":
        if val == 6: win = True; coeff = 5.0
        elif val >= 4: win = True; coeff = 1.5 # Сбил почти все

    # ИТОГ
    if win:
        payout = bet * coeff
        await update_balance(user_id, payout, user['mode'])
        res_txt = f"✅ <b>ПОБЕДА!</b> (+{fmt(payout)})"
    else:
        res_txt = "❌ <b>Проигрыш</b>"

    # Кнопка "Играть снова" с тем же исходом
    retry_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Еще раз", callback_data=cb.data)],
        [InlineKeyboardButton(text="🔙 Меню игр", callback_data="games_menu")]
    ])
    
    await cb.message.answer(f"Результат: {val}\n{res_txt}", reply_markup=retry_kb, parse_mode="HTML")

# --- САПЕР (MINES) ---
mines_sessions = {}

def get_mines_coeff(steps):
    # Формула с House Edge (чтобы не было слишком легко)
    # Шанс победы = (Всего - Мины - Шаги) / (Всего - Шаги)
    # Коэф = (1 / Шанс) * (1 - HOUSE_EDGE)
    curr = 1.0
    remaining_cells = 25
    remaining_safe = 25 - MINES_COUNT
    
    for _ in range(steps):
        chance = remaining_safe / remaining_cells
        fair_coeff = 1 / chance
        curr *= fair_coeff
        # Применяем комиссию на каждом шаге
        curr *= HOUSE_EDGE 
        
        remaining_cells -= 1
        remaining_safe -= 1
        
    return round(curr, 2)

def mines_kb(game_data, revealed=False):
    kb = []
    grid = game_data['grid']
    opens = game_data['opens']
    
    for r in range(5):
        row = []
        for c in range(5):
            idx = r*5 + c
            txt = "⬜" # Закрыто
            cb = f"m_step_{idx}"
            
            if idx in opens:
                txt = "💎"
                cb = "ignore"
            elif revealed:
                if grid[idx] == 1: txt, cb = "💣", "ignore"
                else: txt, cb = "▪️", "ignore" # Пустые при проигрыше затемняем
            
            row.append(InlineKeyboardButton(text=txt, callback_data=cb))
        kb.append(row)
    
    if not revealed:
        steps = len(opens)
        if steps > 0:
            coeff = get_mines_coeff(steps)
            win = game_data['bet'] * coeff
            kb.append([InlineKeyboardButton(text=f"💰 ЗАБРАТЬ: {fmt(win)} (x{coeff})", callback_data="m_cash")])
    else:
        kb.append([InlineKeyboardButton(text="🔄 Заново", callback_data="game_mines_pre")])
        kb.append([InlineKeyboardButton(text="🔙 Меню", callback_data="games_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data == "game_mines_pre")
async def m_pre(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    await cb.message.edit_text(
        f"💣 <b>Сапер PRO</b>\n"
        f"Поле: 5x5 | Мины: {MINES_COUNT}\n"
        f"Ставка: <b>{fmt(user['bet'])}</b>\n\n"
        f"<i>Чем больше открыл - тем больше выигрыш!</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 НАЧАТЬ ИГРУ", callback_data="m_start")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
        ]), parse_mode="HTML"
    )

@dp.callback_query(F.data == "m_start")
async def m_start(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    bet = user['bet']
    bal = user['demo'] if user['mode'] == 'demo' else user['real']
    
    if bal < bet: return await cb.answer("❌ Нет денег!", show_alert=True)
    await update_balance(cb.from_user.id, -bet, user['mode'])
    
    # Генерация
    grid = [0]*25
    for i in random.sample(range(25), MINES_COUNT): grid[i] = 1
    
    mines_sessions[cb.from_user.id] = {
        "grid": grid, "opens": [], "active": True, 
        "mode": user['mode'], "bet": bet
    }
    
    await cb.message.edit_text("💣 <b>Сапер</b>: Выбери ячейку", 
        reply_markup=mines_kb(mines_sessions[cb.from_user.id]), parse_mode="HTML")

@dp.callback_query(F.data.startswith("m_step_"))
async def m_step(cb: CallbackQuery):
    uid = cb.from_user.id
    if uid not in mines_sessions or not mines_sessions[uid]['active']:
        return await cb.answer("Игра окончена")
    
    idx = int(cb.data.split("_")[2])
    sess = mines_sessions[uid]
    
    if sess['grid'][idx] == 1:
        sess['active'] = False
        await cb.message.edit_text("💥 <b>БАБАХ!</b> Ты проиграл.", 
            reply_markup=mines_kb(sess, True), parse_mode="HTML")
    else:
        if idx not in sess['opens']: sess['opens'].append(idx)
        coeff = get_mines_coeff(len(sess['opens']))
        win = sess['bet'] * coeff
        await cb.message.edit_text(f"💎 Открыто: {len(sess['opens'])} | Выигрыш: <b>{fmt(win)}</b> (x{coeff})", 
            reply_markup=mines_kb(sess), parse_mode="HTML")

@dp.callback_query(F.data == "m_cash")
async def m_cash(cb: CallbackQuery):
    uid = cb.from_user.id
    sess = mines_sessions.get(uid)
    if not sess or not sess['active']: return
    
    coeff = get_mines_coeff(len(sess['opens']))
    win = sess['bet'] * coeff
    sess['active'] = False
    
    await update_balance(uid, win, sess['mode'])
    await cb.message.edit_text(f"💰 <b>Вы забрали {fmt(win)}!</b>\nКоэффициент: x{coeff}", 
        reply_markup=mines_kb(sess, True), parse_mode="HTML")

@dp.callback_query(F.data == "ignore")
async def ignore(cb: CallbackQuery):
    await cb.answer()

@dp.callback_query(F.data == "admin_panel")
async def admin(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return await cb.answer("Запрещено")
    count = await get_all_users_count()
    await cb.message.edit_text(f"⚙️ Пользователей в БД: {count}", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙", callback_data="main_menu")]]))

# --- ЗАПУСК ---
async def main():
    await init_db()
    print("Бот запущен v2.0 Pro")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
