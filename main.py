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
DB_NAME = "casino_ludo.db"

# Настройки баланса и игр
MINES_COUNT = 3  
HOUSE_EDGE = 0.93 # 7% преимущество казино в Сапере

if not BOT_TOKEN:
    exit("❌ Ошибка: BOT_TOKEN не найден в переменных окружения!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# --- FSM (Машина состояний) ---
class UserState(StatesGroup):
    waiting_for_bet = State() 

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
    if num % 1 == 0: return f"{int(num)}"
    return f"{round(num, 2)}"

# --- КЛАВИАТУРЫ ---

def main_kb(user_id, mode, bet):
    mode_txt = "🟢 DEMO" if mode == "demo" else "🔴 REAL"
    btns = [
        [InlineKeyboardButton(text="🎮 Игры Ludo", callback_data="games_menu")],
        [InlineKeyboardButton(text=f"💰 Ставка: {fmt(bet)}", callback_data="change_bet")],
        [InlineKeyboardButton(text=f"🔄 Режим: {mode_txt}", callback_data="switch_mode")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")]
    ]
    if user_id == ADMIN_ID:
        btns.append([InlineKeyboardButton(text="⚙️ Админ", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def games_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Кубик", callback_data="pre_dice"), InlineKeyboardButton(text="🎰 Слоты", callback_data="pre_slots")],
        [InlineKeyboardButton(text="⚽ Футбол", callback_data="pre_foot"), InlineKeyboardButton(text="🏀 Баскет", callback_data="pre_basket")],
        [InlineKeyboardButton(text="🎯 Дартс", callback_data="pre_darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="pre_bowl")],
        [InlineKeyboardButton(text="💣 Сапер PRO", callback_data="game_mines_pre")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="main_menu")]
    ])

# --- ВАРИАНТЫ ИСХОДОВ ---

def dice_variants_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Дуэль (Bot vs You) | x1.9", callback_data="play_dice_duel")],
        [InlineKeyboardButton(text="Больше 4 (5-6) | x2.8", callback_data="play_dice_over4")],
        [InlineKeyboardButton(text="Меньше 4 (1-3) | x1.9", callback_data="play_dice_under4")],
        [InlineKeyboardButton(text="Четное (2,4,6) | x1.9", callback_data="play_dice_even")],
        [InlineKeyboardButton(text="Нечетное (1,3,5) | x1.9", callback_data="play_dice_odd")],
        [InlineKeyboardButton(text="🔢 Угадай число | x5.0", callback_data="dice_guess_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
    ])

def dice_guess_kb():
    # Выбор конкретного числа
    btns = []
    for i in range(1, 4): btns.append(InlineKeyboardButton(text=f"{i}", callback_data=f"play_dice_exact_{i}"))
    row2 = []
    for i in range(4, 7): row2.append(InlineKeyboardButton(text=f"{i}", callback_data=f"play_dice_exact_{i}"))
    return InlineKeyboardMarkup(inline_keyboard=[btns, row2, [InlineKeyboardButton(text="🔙 Назад", callback_data="pre_dice")]])

def sport_variants_kb(sport_type):
    emoji = "⚽" if sport_type == "foot" else "🏀"
    # Для футбола и баскета логика схожая в коде, но разная в кэфах
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{emoji} Гол/Попадание | x1.8", callback_data=f"play_{sport_type}_goal")],
        [InlineKeyboardButton(text="❌ Мимо | x1.8", callback_data=f"play_{sport_type}_miss")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
    ])

def darts_variants_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Центр (Bullseye) | x5.0", callback_data="play_darts_center")],
        [InlineKeyboardButton(text="🔴 Красное | x1.8", callback_data="play_darts_red")],
        [InlineKeyboardButton(text="⚪️ Белое | x1.8", callback_data="play_darts_white")],
        [InlineKeyboardButton(text="❌ Мимо | x2.5", callback_data="play_darts_miss")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
    ])

def bowl_variants_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Дуэль (Bot vs You) | x1.9", callback_data="play_bowl_duel")],
        [InlineKeyboardButton(text="🎳 Страйк (только 6) | x5.0", callback_data="play_bowl_strike")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
    ])

# --- ХЕНДЛЕРЫ МЕНЮ ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = await get_user(message.from_user.id)
    txt = (f"👋 <b>LudoCasino</b>\nБаланс: <b>{fmt(user['demo'] if user['mode']=='demo' else user['real'])}</b>\n"
           f"Ставка: <b>{fmt(user['bet'])}</b>")
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
    await cb.message.edit_text("✍️ <b>Введите сумму ставки:</b>\n(Например: 10, 100, 0.5)", parse_mode="HTML")
    await state.set_state(UserState.waiting_for_bet)

@dp.message(StateFilter(UserState.waiting_for_bet))
async def process_bet(msg: Message, state: FSMContext):
    try:
        val = float(msg.text.replace(",", "."))
        if val < 0.1: return await msg.answer("❌ Минимум 0.1")
        await set_bet(msg.from_user.id, val)
        user = await get_user(msg.from_user.id)
        await msg.answer(f"✅ Ставка: <b>{fmt(val)}</b>", reply_markup=main_kb(user['user_id'], user['mode'], val), parse_mode="HTML")
        await state.clear()
    except:
        await msg.answer("❌ Введите число.")

@dp.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    txt = (f"👤 <b>Профиль</b>\n🆔: <code>{user['user_id']}</code>\n"
           f"💵 Real: <b>{fmt(user['real'])}</b>\n🕹 Demo: <b>{fmt(user['demo'])}</b>\n"
           f"⚙️ Ставка: <b>{fmt(user['bet'])}</b>")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💰 Изменить ставку", callback_data="change_bet")],[InlineKeyboardButton(text="🔙 Меню", callback_data="main_menu")]])
    await cb.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")

# --- МЕНЮ ИГР ---

@dp.callback_query(F.data == "games_menu")
async def cb_games(cb: CallbackQuery):
    await cb.message.edit_text("🔥 <b>Ludo Игры:</b>", reply_markup=games_kb(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("pre_"))
async def cb_pre(cb: CallbackQuery):
    game = cb.data.split("_")[1]
    if game == "dice": await cb.message.edit_text("🎲 <b>Кубик:</b> Выбери исход", reply_markup=dice_variants_kb(), parse_mode="HTML")
    elif game == "foot": await cb.message.edit_text("⚽ <b>Футбол:</b> Выбери исход", reply_markup=sport_variants_kb("foot"), parse_mode="HTML")
    elif game == "basket": await cb.message.edit_text("🏀 <b>Баскет:</b> Выбери исход", reply_markup=sport_variants_kb("basket"), parse_mode="HTML")
    elif game == "darts": await cb.message.edit_text("🎯 <b>Дартс:</b> Выбери исход", reply_markup=darts_variants_kb(), parse_mode="HTML")
    elif game == "bowl": await cb.message.edit_text("🎳 <b>Боулинг:</b> Выбери исход", reply_markup=bowl_variants_kb(), parse_mode="HTML")
    elif game == "slots": 
        # Сразу запуск слотов
        await run_game(cb, "slots", "spin")

@dp.callback_query(F.data == "dice_guess_menu")
async def cb_guess_menu(cb: CallbackQuery):
    await cb.message.edit_text("🔢 <b>Угадай число:</b> Какое выпадет?", reply_markup=dice_guess_kb(), parse_mode="HTML")

# --- ЛОГИКА ИГР ---

@dp.callback_query(F.data.startswith("play_"))
async def cb_play(cb: CallbackQuery):
    parts = cb.data.split("_") # play, dice, over4
    game = parts[1]
    variant = parts[2]
    # Если ставка на точное число (play_dice_exact_5)
    if variant == "exact": variant = f"exact_{parts[3]}"
    
    await run_game(cb, game, variant)

async def run_game(cb: CallbackQuery, game, variant):
    user_id = cb.from_user.id
    user = await get_user(user_id)
    bet = user['bet']
    bal = user['demo'] if user['mode'] == 'demo' else user['real']

    if bal < bet: return await cb.answer("❌ Недостаточно средств!", show_alert=True)
    await update_balance(user_id, -bet, user['mode'])

    # --- ЛОГИКА ДУЭЛИ (ОТДЕЛЬНАЯ) ---
    if variant == "duel":
        emoji = "🎲" if game == "dice" else "🎳"
        await cb.message.answer(f"🤖 <b>Бот бросает...</b> ({emoji})", parse_mode="HTML")
        msg_bot = await cb.message.answer_dice(emoji=emoji)
        bot_val = msg_bot.dice.value
        await asyncio.sleep(3)
        
        await cb.message.answer(f"👤 <b>Ты бросаешь...</b> ({emoji})", parse_mode="HTML")
        msg_user = await cb.message.answer_dice(emoji=emoji)
        user_val = msg_user.dice.value
        await asyncio.sleep(3)
        
        win = False
        refund = False
        
        if user_val > bot_val:
            win = True
        elif user_val == bot_val:
            refund = True
            
        if refund:
            await update_balance(user_id, bet, user['mode'])
            res_txt = "🤝 <b>Ничья!</b> (Возврат ставки)"
        elif win:
            payout = bet * 1.9
            await update_balance(user_id, payout, user['mode'])
            res_txt = f"✅ <b>Ты победил!</b> (+{fmt(payout)})"
        else:
            res_txt = f"❌ <b>Бот победил.</b>"
            
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Реванш", callback_data=cb.data)], [InlineKeyboardButton(text="🔙 Меню", callback_data="games_menu")]])
        await cb.message.answer(f"Бот: {bot_val} | Ты: {user_val}\n{res_txt}", reply_markup=kb, parse_mode="HTML")
        return

    # --- ОБЫЧНЫЕ ИГРЫ ---
    emoji_map = {"dice": "🎲", "foot": "⚽", "basket": "🏀", "darts": "🎯", "bowl": "🎳", "slots": "🎰"}
    emoji = emoji_map.get(game)
    
    await cb.message.answer(f"{emoji} Ставка: <b>{fmt(bet)}</b>...", parse_mode="HTML")
    msg = await cb.message.answer_dice(emoji=emoji)
    val = msg.dice.value
    await asyncio.sleep(3.5)

    win = False
    coeff = 0.0

    # ЛОГИКА ПОБЕД
    
    # 🎲 КУБИК
    if game == "dice":
        if "exact" in variant:
            target = int(variant.split("_")[1])
            if val == target: win=True; coeff=5.0
        elif variant == "over4": # Больше 4 (5,6)
            if val > 4: win=True; coeff=2.8
        elif variant == "under4": # Меньше 4 (1,2,3)
            if val < 4: win=True; coeff=1.9
        elif variant == "even": # Четное (2,4,6)
            if val % 2 == 0: win=True; coeff=1.9
        elif variant == "odd": # Нечетное (1,3,5)
            if val % 2 != 0: win=True; coeff=1.9

    # ⚽ ФУТБОЛ
    elif game == "foot":
        # 3,4,5 = Гол. 1,2 = Мимо
        is_goal = val >= 3
        if variant == "goal" and is_goal: win=True; coeff=1.8
        elif variant == "miss" and not is_goal: win=True; coeff=1.8 # Мимо сложнее поймать по логике TG, но сделаем равный кэф

    # 🏀 БАСКЕТ
    elif game == "basket":
        # 4,5 = Попадание. 1,2,3 = Мимо
        is_goal = val >= 4
        if variant == "goal" and is_goal: win=True; coeff=1.8
        elif variant == "miss" and not is_goal: win=True; coeff=1.8

    # 🎯 ДАРТС
    elif game == "darts":
        # 1=Мимо, 2,4=Белое, 3,5=Красное, 6=Центр
        if variant == "center" and val == 6: win=True; coeff=5.0
        elif variant == "miss" and val == 1: win=True; coeff=2.5
        elif variant == "white" and val in [2, 4]: win=True; coeff=1.8
        elif variant == "red" and val in [3, 5]: win=True; coeff=1.8

    # 🎳 БОУЛИНГ
    elif game == "bowl":
        # Страйк только 6
        if variant == "strike" and val == 6: win=True; coeff=5.0

    # 🎰 СЛОТЫ
    elif game == "slots":
        if val == 64: win=True; coeff=10.0 # 777
        elif val in [1, 22, 43]: win=True; coeff=3.0 # Ягоды
        elif val in [16, 32, 48]: win=True; coeff=1.5

    if win:
        pay = bet * coeff
        await update_balance(user_id, pay, user['mode'])
        res = f"✅ <b>ПОБЕДА!</b> (+{fmt(pay)})"
    else:
        res = "❌ <b>Проигрыш</b>"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Еще раз", callback_data=cb.data)],[InlineKeyboardButton(text="🔙 Меню", callback_data="games_menu")]])
    await cb.message.answer(f"Результат: {val}\n{res}", reply_markup=kb, parse_mode="HTML")

# --- САПЕР (MINES) ---
mines_sessions = {}

def get_mines_coeff(steps):
    curr = 1.0
    rem_cells = 25
    rem_safe = 25 - MINES_COUNT
    for _ in range(steps):
        chance = rem_safe / rem_cells
        curr *= (1 / chance) * HOUSE_EDGE
        rem_cells -= 1
        rem_safe -= 1
    return round(curr, 2)

def mines_kb(game_data, revealed=False):
    kb = []
    grid = game_data['grid']
    opens = game_data['opens']
    for r in range(5):
        row = []
        for c in range(5):
            idx = r*5 + c
            txt, cb = "⬜", f"m_step_{idx}"
            if idx in opens: txt, cb = "💎", "ignore"
            elif revealed:
                if grid[idx]==1: txt, cb = "💣", "ignore"
                else: txt, cb = "▪️", "ignore"
            row.append(InlineKeyboardButton(text=txt, callback_data=cb))
        kb.append(row)
    if not revealed:
        if len(opens) > 0:
            cf = get_mines_coeff(len(opens))
            win = game_data['bet'] * cf
            kb.append([InlineKeyboardButton(text=f"💰 ЗАБРАТЬ: {fmt(win)} (x{cf})", callback_data="m_cash")])
    else:
        kb.append([InlineKeyboardButton(text="🔄 Заново", callback_data="game_mines_pre")])
        kb.append([InlineKeyboardButton(text="🔙 Меню", callback_data="games_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data == "game_mines_pre")
async def m_pre(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    await cb.message.edit_text(f"💣 <b>Сапер PRO</b>\nСтавка: <b>{fmt(user['bet'])}</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 ИГРАТЬ", callback_data="m_start")],[InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]]), parse_mode="HTML")

@dp.callback_query(F.data == "m_start")
async def m_start(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    if (user['demo'] if user['mode']=='demo' else user['real']) < user['bet']: return await cb.answer("❌ Нет денег", show_alert=True)
    await update_balance(cb.from_user.id, -user['bet'], user['mode'])
    grid = [0]*25
    for i in random.sample(range(25), MINES_COUNT): grid[i]=1
    mines_sessions[cb.from_user.id] = {"grid": grid, "opens": [], "active": True, "mode": user['mode'], "bet": user['bet']}
    await cb.message.edit_text("💣 Сапер: Ходи", reply_markup=mines_kb(mines_sessions[cb.from_user.id]), parse_mode="HTML")

@dp.callback_query(F.data.startswith("m_step_"))
async def m_step(cb: CallbackQuery):
    uid = cb.from_user.id
    if uid not in mines_sessions or not mines_sessions[uid]['active']: return await cb.answer("Игра окончена")
    idx = int(cb.data.split("_")[2])
    sess = mines_sessions[uid]
    if sess['grid'][idx] == 1:
        sess['active'] = False
        await cb.message.edit_text("💥 <b>БАБАХ!</b>", reply_markup=mines_kb(sess, True), parse_mode="HTML")
    else:
        if idx not in sess['opens']: sess['opens'].append(idx)
        cf = get_mines_coeff(len(sess['opens']))
        await cb.message.edit_text(f"💎 Коэф: x{cf}", reply_markup=mines_kb(sess), parse_mode="HTML")

@dp.callback_query(F.data == "m_cash")
async def m_cash(cb: CallbackQuery):
    uid = cb.from_user.id
    sess = mines_sessions.get(uid)
    if not sess or not sess['active']: return
    cf = get_mines_coeff(len(sess['opens']))
    win = sess['bet'] * cf
    sess['active'] = False
    await update_balance(uid, win, sess['mode'])
    await cb.message.edit_text(f"💰 <b>Вы забрали {fmt(win)}!</b>", reply_markup=mines_kb(sess, True), parse_mode="HTML")

@dp.callback_query(F.data == "ignore")
async def ign(cb: CallbackQuery): await cb.answer()

@dp.callback_query(F.data == "admin_panel")
async def adm(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    cnt = await get_all_users_count()
    await cb.message.edit_text(f"Users: {cnt}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙", callback_data="main_menu")]]))

async def main():
    await init_db()
    print("Bot Ludo v3 Started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
