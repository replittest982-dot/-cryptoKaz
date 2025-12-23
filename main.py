import asyncio
import logging
import os
import random
import aiosqlite
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from dotenv import load_dotenv

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_TOKEN = os.getenv("CRYPTO_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DB_NAME = "casino_usd_pro.db"

# Настройки экономики (USD)
MINES_COUNT = 3  
HOUSE_EDGE = 0.94 # Оставляем игроку 94% от честного кэфа (чтобы цифры были красивые)
WIN_CHANCE_MODIFIER = 0.20 # 20% шанс, что бот взорвет игрока в Сапере специально

if not BOT_TOKEN:
    exit("❌ Ошибка: BOT_TOKEN не найден!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

# --- FSM ---
class UserState(StatesGroup):
    waiting_for_bet = State()
    waiting_for_deposit = State()
    waiting_for_withdraw = State()
    waiting_for_treasury_topup = State()

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Таблица пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                real_balance REAL DEFAULT 0.0,
                demo_balance REAL DEFAULT 1000.0,
                current_mode TEXT DEFAULT 'demo',
                current_bet REAL DEFAULT 1.0
            )
        """)
        # Таблица Казны (Банка)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS treasury (
                id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 0.0
            )
        """)
        await db.execute("INSERT OR IGNORE INTO treasury (id, balance) VALUES (1, 0.0)")
        await db.commit()

async def get_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
                await db.commit()
                return {"user_id": user_id, "real": 0.0, "demo": 1000.0, "mode": "demo", "bet": 1.0}
            return {"user_id": row[0], "real": row[1], "demo": row[2], "mode": row[3], "bet": row[4]}

async def get_all_users_count():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

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

async def get_treasury():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT balance FROM treasury WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0.0

async def update_treasury(amount):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE treasury SET balance = balance + ? WHERE id = 1", (amount,))
        await db.commit()

# --- CRYPTOBOT API (FIX ДЛЯ ХОСТИНГА) ---
async def create_invoice(amount, description="Deposit USD"):
    if not CRYPTO_TOKEN:
        logging.error("CRYPTO_TOKEN is missing")
        return None
        
    headers = {
        'Crypto-Pay-API-Token': CRYPTO_TOKEN,
        'User-Agent': 'Mozilla/5.0' # Притворяемся браузером
    }
    url = 'https://pay.cryptobot.net/api/createInvoice'
    data = {
        'asset': 'USDT',
        'amount': str(amount),
        'description': description
    }
    
    try:
        # !!! АГРЕССИВНЫЙ ФИКС СЕТИ !!!
        # ssl=False -> Игнорируем ошибки сертификатов
        # family=2 -> Принудительно используем IPv4 (решает проблему DNS)
        connector = aiohttp.TCPConnector(ssl=False, family=2)
        timeout = aiohttp.ClientTimeout(total=20) # Ждем до 20 секунд
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.post(url, headers=headers, json=data) as resp:
                result = await resp.json()
                if not result.get('ok'):
                    logging.error(f"CryptoBot API Error: {result}")
                return result
    except Exception as e:
        logging.error(f"CRITICAL NETWORK ERROR: {e}")
        return None

async def get_invoice_status(invoice_id):
    headers = {'Crypto-Pay-API-Token': CRYPTO_TOKEN}
    url = f'https://pay.cryptobot.net/api/getInvoices?invoice_ids={invoice_id}'
    try:
        # Тот же фикс для проверки статуса
        connector = aiohttp.TCPConnector(ssl=False, family=2)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, headers=headers) as resp:
                data = await resp.json()
                if data['ok'] and data['result']['items']:
                    return data['result']['items'][0]['status']
    except Exception as e:
        logging.error(f"Check Status Error: {e}")
    return None

def fmt(num):
    return f"{num:.2f}$"

# --- КЛАВИАТУРЫ ---
def main_kb(user_id, mode, bet):
    mode_txt = "🟢 DEMO" if mode == "demo" else "🔴 REAL"
    btns = [
        [InlineKeyboardButton(text="🎮 ИГРАТЬ", callback_data="games_menu")],
        [InlineKeyboardButton(text=f"💰 Ставка: {fmt(bet)}", callback_data="change_bet")],
        [InlineKeyboardButton(text=f"🔄 Режим: {mode_txt}", callback_data="switch_mode")],
        [InlineKeyboardButton(text="👤 Мой Кабинет", callback_data="profile")]
    ]
    if user_id == ADMIN_ID:
        btns.append([InlineKeyboardButton(text="🔒 Админ-Панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

def profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Пополнить (CryptoBot)", callback_data="deposit_start")],
        [InlineKeyboardButton(text="💸 Вывести (USDT)", callback_data="withdraw_start")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
    ])

def games_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Кубик", callback_data="pre_dice"), InlineKeyboardButton(text="🎰 Слоты", callback_data="pre_slots")],
        [InlineKeyboardButton(text="⚽ Футбол", callback_data="pre_foot"), InlineKeyboardButton(text="🏀 Баскет", callback_data="pre_basket")],
        [InlineKeyboardButton(text="🎯 Дартс", callback_data="pre_darts"), InlineKeyboardButton(text="🎳 Боулинг", callback_data="pre_bowl")],
        [InlineKeyboardButton(text="💣 Сапер (Boosted)", callback_data="game_mines_pre")],
        [InlineKeyboardButton(text="🔙 Меню", callback_data="main_menu")]
    ])

def dice_variants_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Дуэль (Bot vs You) | x1.9", callback_data="play_dice_duel")],
        [InlineKeyboardButton(text="Больше 4 (5-6) | x2.5", callback_data="play_dice_over4")],
        [InlineKeyboardButton(text="Меньше 4 (1-3) | x1.8", callback_data="play_dice_under4")],
        [InlineKeyboardButton(text="Четное (2,4,6) | x1.8", callback_data="play_dice_even")],
        [InlineKeyboardButton(text="Нечетное (1,3,5) | x1.8", callback_data="play_dice_odd")],
        [InlineKeyboardButton(text="🔢 Угадай число | x4.5", callback_data="dice_guess_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
    ])

def dice_guess_kb():
    btns = [InlineKeyboardButton(text=f"{i}", callback_data=f"play_dice_exact_{i}") for i in range(1, 4)]
    row2 = [InlineKeyboardButton(text=f"{i}", callback_data=f"play_dice_exact_{i}") for i in range(4, 7)]
    return InlineKeyboardMarkup(inline_keyboard=[btns, row2, [InlineKeyboardButton(text="🔙 Назад", callback_data="pre_dice")]])

def sport_variants_kb(sport_type):
    emoji = "⚽" if sport_type == "foot" else "🏀"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{emoji} Гол/Попадание | x1.7", callback_data=f"play_{sport_type}_goal")],
        [InlineKeyboardButton(text="❌ Мимо | x1.7", callback_data=f"play_{sport_type}_miss")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
    ])

def darts_variants_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔴 Центр (Bullseye) | x4.0", callback_data="play_darts_center")],
        [InlineKeyboardButton(text="🔴 Красное | x1.7", callback_data="play_darts_red")],
        [InlineKeyboardButton(text="⚪️ Белое | x1.7", callback_data="play_darts_white")],
        [InlineKeyboardButton(text="❌ Мимо | x2.0", callback_data="play_darts_miss")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
    ])

def bowl_variants_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Дуэль (Bot vs You) | x1.9", callback_data="play_bowl_duel")],
        [InlineKeyboardButton(text="🎳 Страйк (только 6) | x4.0", callback_data="play_bowl_strike")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]
    ])

# --- ЛОГИКА АДМИНКИ И КАЗНЫ ---
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    treasury = await get_treasury()
    count = await get_all_users_count()
    
    txt = (f"🔒 <b>Админ-Панель</b>\n\n"
           f"🏦 <b>Казна (Real):</b> {fmt(treasury)}\n"
           f"👥 Игроков: {count}\n"
           f"Валюта: USD (Доллары)")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Пополнить Казну (CryptoBot)", callback_data="admin_deposit_treasury")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="main_menu")]
    ])
    await cb.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "admin_deposit_treasury")
async def admin_deposit_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("✍️ Введи сумму ($) для пополнения <b>Банка бота</b>:", parse_mode="HTML")
    await state.set_state(UserState.waiting_for_treasury_topup)

@dp.message(StateFilter(UserState.waiting_for_treasury_topup))
async def process_treasury_invoice(msg: Message, state: FSMContext):
    try:
        amount = float(msg.text.replace(",", "."))
        invoice = await create_invoice(amount, "Treasury Top-up")
        
        if invoice and invoice.get('ok'):
            pay_url = invoice['result']['pay_url']
            inv_id = invoice['result']['invoice_id']
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"💳 Оплатить {fmt(amount)}", url=pay_url)],
                [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"checktreasury_{inv_id}_{amount}")]
            ])
            await msg.answer(f"Счет для пополнения Казны создан.", reply_markup=kb)
            await state.clear()
        else: 
            await msg.answer("❌ Не могу соединиться с CryptoBot. Хостинг блокирует сеть?")
    except Exception as e: 
        await msg.answer(f"Ошибка ввода: {e}")

@dp.callback_query(F.data.startswith("checktreasury_"))
async def check_treasury_pay(cb: CallbackQuery):
    _, inv_id, amount = cb.data.split("_")
    status = await get_invoice_status(inv_id)
    if status == 'paid':
        await update_treasury(float(amount))
        await cb.message.edit_text(f"✅ <b>Банк пополнен!</b>\nКазна успешно увеличена на {amount}$", parse_mode="HTML")
    else: 
        await cb.answer("Оплата еще не прошла", show_alert=True)

# --- ОСНОВНЫЕ ХЕНДЛЕРЫ ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = await get_user(message.from_user.id)
    txt = (f"👋 <b>LudoCasino ($)</b>\n"
           f"Баланс: <b>{fmt(user['demo'] if user['mode']=='demo' else user['real'])}</b>\n"
           f"Валюта: Доллары")
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
    await cb.message.edit_text("✍️ <b>Введите ставку в $:</b>\n(Пример: 0.5, 10, 100)", parse_mode="HTML")
    await state.set_state(UserState.waiting_for_bet)

@dp.message(StateFilter(UserState.waiting_for_bet))
async def process_bet(msg: Message, state: FSMContext):
    try:
        val = float(msg.text.replace(",", "."))
        if val < 0.1: return await msg.answer("❌ Минимум 0.10$")
        await set_bet(msg.from_user.id, val)
        user = await get_user(msg.from_user.id)
        await msg.answer(f"✅ Ставка: <b>{fmt(val)}</b>", reply_markup=main_kb(user['user_id'], user['mode'], val), parse_mode="HTML")
        await state.clear()
    except:
        await msg.answer("❌ Введите число.")

@dp.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    txt = (f"👤 <b>Личный кабинет</b>\n\n"
           f"💵 REAL: <b>{fmt(user['real'])}</b>\n"
           f"🕹 DEMO: <b>{fmt(user['demo'])}</b>\n"
           f"⚙️ Ставка: <b>{fmt(user['bet'])}</b>")
    await cb.message.edit_text(txt, reply_markup=profile_kb(), parse_mode="HTML")

# --- ПОПОЛНЕНИЕ ЮЗЕРА (CRYPTOBOT USD) ---
@dp.callback_query(F.data == "deposit_start")
async def deposit_start(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("✍️ Введите сумму пополнения в <b>$ (USDT)</b>:", parse_mode="HTML")
    await state.set_state(UserState.waiting_for_deposit)

@dp.message(StateFilter(UserState.waiting_for_deposit))
async def process_deposit(msg: Message, state: FSMContext):
    try:
        amount = float(msg.text.replace(",", "."))
        if amount < 1.0: return await msg.answer("Минимум 1.00$")
        
        invoice = await create_invoice(amount, "User Deposit")
        if invoice and invoice.get('ok'):
            pay_url = invoice['result']['pay_url']
            inv_id = invoice['result']['invoice_id']
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🔗 Оплатить {fmt(amount)}", url=pay_url)],
                [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check_{inv_id}_{amount}")]
            ])
            await msg.answer(f"Счет на {fmt(amount)} создан.", reply_markup=kb)
            await state.clear()
        else:
            await msg.answer("❌ Не могу соединиться с CryptoBot.")
    except:
        await msg.answer("Введите число.")

@dp.callback_query(F.data.startswith("check_"))
async def check_pay(cb: CallbackQuery):
    _, inv_id, amount_str = cb.data.split("_")
    status = await get_invoice_status(inv_id)
    if status == 'paid':
        real_money = float(amount_str)
        await update_balance(cb.from_user.id, real_money, "real")
        await update_treasury(real_money * 0.2) # 20% комиссия в казну
        await cb.message.edit_text(f"✅ Оплата принята!\nБаланс пополнен на {fmt(real_money)}")
    elif status == 'active':
        await cb.answer("⏳ Оплата еще не найдена", show_alert=True)
    else:
        await cb.answer("❌ Срок истек", show_alert=True)

# --- ВЫВОД СРЕДСТВ ---
@dp.callback_query(F.data == "withdraw_start")
async def withdraw_start(cb: CallbackQuery, state: FSMContext):
    user = await get_user(cb.from_user.id)
    if user['real'] < 5.0:
        return await cb.answer("❌ Минимум для вывода: 5.00$", show_alert=True)
    await cb.message.edit_text("✍️ Напишите сумму и адрес (USDT TRC20):")
    await state.set_state(UserState.waiting_for_withdraw)

@dp.message(StateFilter(UserState.waiting_for_withdraw))
async def process_withdraw(msg: Message, state: FSMContext):
    user = await get_user(msg.from_user.id)
    try:
        await bot.send_message(ADMIN_ID, f"💸 <b>Заявка на вывод!</b>\nЮзер: {msg.from_user.id} (@{msg.from_user.username})\nТекст: {msg.text}\nБаланс: {fmt(user['real'])}")
        await msg.answer("✅ Заявка отправлена администратору.")
    except:
        await msg.answer("Ошибка отправки.")
    await state.clear()

# --- МЕНЮ ИГР ---
@dp.callback_query(F.data == "games_menu")
async def cb_games(cb: CallbackQuery):
    await cb.message.edit_text("🔥 <b>Игры на $:</b>", reply_markup=games_kb(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("pre_"))
async def cb_pre(cb: CallbackQuery):
    game = cb.data.split("_")[1]
    if game == "dice": await cb.message.edit_text("🎲 <b>Кубик:</b> Выбери исход", reply_markup=dice_variants_kb(), parse_mode="HTML")
    elif game == "foot": await cb.message.edit_text("⚽ <b>Футбол:</b> Выбери исход", reply_markup=sport_variants_kb("foot"), parse_mode="HTML")
    elif game == "basket": await cb.message.edit_text("🏀 <b>Баскет:</b> Выбери исход", reply_markup=sport_variants_kb("basket"), parse_mode="HTML")
    elif game == "darts": await cb.message.edit_text("🎯 <b>Дартс:</b> Выбери исход", reply_markup=darts_variants_kb(), parse_mode="HTML")
    elif game == "bowl": await cb.message.edit_text("🎳 <b>Боулинг:</b> Выбери исход", reply_markup=bowl_variants_kb(), parse_mode="HTML")
    elif game == "slots": await run_game(cb, "slots", "spin")

@dp.callback_query(F.data == "dice_guess_menu")
async def cb_guess_menu(cb: CallbackQuery):
    await cb.message.edit_text("🔢 <b>Угадай число:</b>", reply_markup=dice_guess_kb(), parse_mode="HTML")

# --- ИГРОВОЙ ПРОЦЕСС (С КАЗНОЙ) ---
@dp.callback_query(F.data.startswith("play_"))
async def cb_play(cb: CallbackQuery):
    parts = cb.data.split("_")
    game = parts[1]
    variant = parts[2]
    if variant == "exact": variant = f"exact_{parts[3]}"
    await run_game(cb, game, variant)

async def run_game(cb: CallbackQuery, game, variant):
    user_id = cb.from_user.id
    user = await get_user(user_id)
    bet = user['bet']
    mode = user['mode']
    bal = user['demo'] if mode == 'demo' else user['real']
    treasury = await get_treasury()

    if bal < bet: return await cb.answer("❌ Недостаточно средств!", show_alert=True)

    # Логика СКАМА (если казна пустая - не даем выиграть)
    rigged_loss = False
    if mode == 'real' and treasury < (bet * 3):
        rigged_loss = True

    await update_balance(user_id, -bet, mode)
    if mode == 'real': await update_treasury(bet)

    if variant == "duel":
        emoji = "🎲" if game == "dice" else "🎳"
        await cb.message.answer(f"🤖 <b>Бот бросает...</b> ({emoji})", parse_mode="HTML")
        bot_val = (await cb.message.answer_dice(emoji=emoji)).dice.value
        await asyncio.sleep(2.5)
        
        await cb.message.answer(f"👤 <b>Ты бросаешь...</b> ({emoji})", parse_mode="HTML")
        user_val = (await cb.message.answer_dice(emoji=emoji)).dice.value
        await asyncio.sleep(2.5)
        
        win = False
        refund = False
        if user_val > bot_val: win = True
        elif user_val == bot_val: refund = True
        
        if refund:
            await update_balance(user_id, bet, mode)
            if mode == 'real': await update_treasury(-bet)
            res = "🤝 Возврат"
        elif win and not rigged_loss:
            pay = bet * 1.9
            await update_balance(user_id, pay, mode)
            if mode == 'real': await update_treasury(-pay)
            res = f"✅ Победа (+{fmt(pay)})"
        else:
             if win and rigged_loss: # Выиграл, но денег нет -> скам
                 pay = bet * 1.9
                 await update_balance(user_id, pay, mode)
                 if mode == 'real': await update_treasury(-pay)
                 res = f"✅ Победа (+{fmt(pay)})"
             else:
                 res = "❌ Бот победил"
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Реванш", callback_data=cb.data)], [InlineKeyboardButton(text="🔙 Меню", callback_data="games_menu")]])
        await cb.message.answer(f"Счет: {bot_val} vs {user_val}\n{res}", reply_markup=kb)
        return

    emoji_map = {"dice": "🎲", "foot": "⚽", "basket": "🏀", "darts": "🎯", "bowl": "🎳", "slots": "🎰"}
    emoji = emoji_map.get(game)
    
    await cb.message.answer(f"{emoji} Ставка: <b>{fmt(bet)}</b>...", parse_mode="HTML")
    val = (await cb.message.answer_dice(emoji=emoji)).dice.value
    await asyncio.sleep(3.5)

    win = False
    coeff = 0.0

    if game == "dice":
        if "exact" in variant:
            if val == int(variant.split("_")[1]): win=True; coeff=4.5
        elif variant == "over4" and val > 4: win=True; coeff=2.5
        elif variant == "under4" and val < 4: win=True; coeff=1.8
        elif variant == "even" and val % 2 == 0: win=True; coeff=1.8
        elif variant == "odd" and val % 2 != 0: win=True; coeff=1.8
    elif game == "foot":
        is_goal = val >= 3
        if variant == "goal" and is_goal: win=True; coeff=1.7
        elif variant == "miss" and not is_goal: win=True; coeff=1.7
    elif game == "basket":
        is_goal = val >= 4
        if variant == "goal" and is_goal: win=True; coeff=1.7
        elif variant == "miss" and not is_goal: win=True; coeff=1.7
    elif game == "darts":
        if variant == "center" and val == 6: win=True; coeff=4.0
        elif variant == "miss" and val == 1: win=True; coeff=2.0
        elif variant == "white" and val in [2, 4]: win=True; coeff=1.7
        elif variant == "red" and val in [3, 5]: win=True; coeff=1.7
    elif game == "bowl" and variant == "strike" and val == 6: win=True; coeff=4.0
    elif game == "slots":
        if val == 64: win=True; coeff=10.0
        elif val in [1, 22, 43]: win=True; coeff=3.0
        elif val in [16, 32, 48]: win=True; coeff=1.5

    if win:
        pay = bet * coeff
        await update_balance(user_id, pay, mode)
        if mode == 'real': await update_treasury(-pay)
        res = f"✅ <b>ПОБЕДА!</b> (+{fmt(pay)})"
    else:
        res = "❌ <b>Проигрыш</b>"

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Еще раз", callback_data=cb.data)],[InlineKeyboardButton(text="🔙 Меню", callback_data="games_menu")]])
    await cb.message.answer(f"Результат: {val}\n{res}", reply_markup=kb, parse_mode="HTML")

# --- САПЕР (MINES) ГЕОМЕТРИЧЕСКИЙ + СКАМ ---
mines_sessions = {}

def get_mines_coeff(steps):
    # Геометрическая прогрессия
    multiplier = 1.0
    for i in range(steps):
        # Реальный шанс
        chance = (25 - MINES_COUNT - i) / (25 - i)
        # Множитель
        multiplier *= (1 / chance)
    
    # Применяем HOUSE_EDGE
    return round(multiplier * HOUSE_EDGE, 2)

def mines_kb(game_data, revealed=False):
    kb = []
    grid = game_data['grid']
    opens = game_data['opens']
    for r in range(5):
        row = []
        for c in range(5):
            idx = r*5 + c
            txt, cb = "  ⬜️  ", f"m_step_{idx}"
            if idx in opens: txt, cb = "  💎  ", "ignore"
            elif revealed:
                if grid[idx]==1: txt, cb = "  💣  ", "ignore"
                else: txt, cb = "  ▪️  ", "ignore"
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
    await cb.message.edit_text(f"💣 <b>Сапер ($)</b>\nСтавка: <b>{fmt(user['bet'])}</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚀 ИГРАТЬ", callback_data="m_start")],[InlineKeyboardButton(text="🔙 Назад", callback_data="games_menu")]]), parse_mode="HTML")

@dp.callback_query(F.data == "m_start")
async def m_start(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    mode = user['mode']
    if (user['demo'] if mode=='demo' else user['real']) < user['bet']: return await cb.answer("❌ Нет денег", show_alert=True)
    
    await update_balance(cb.from_user.id, -user['bet'], mode)
    if mode == 'real': await update_treasury(user['bet'])
    
    grid = [0]*25
    for i in random.sample(range(25), MINES_COUNT): grid[i]=1
    
    mines_sessions[cb.from_user.id] = {"grid": grid, "opens": [], "active": True, "mode": mode, "bet": user['bet']}
    await cb.message.edit_text("💣 Сапер: Выбери ячейку", reply_markup=mines_kb(mines_sessions[cb.from_user.id]), parse_mode="HTML")

@dp.callback_query(F.data.startswith("m_step_"))
async def m_step(cb: CallbackQuery):
    uid = cb.from_user.id
    if uid not in mines_sessions or not mines_sessions[uid]['active']: return await cb.answer("Игра окончена")
    idx = int(cb.data.split("_")[2])
    sess = mines_sessions[uid]
    
    is_bomb = sess['grid'][idx] == 1
    
    # --- ЛОГИКА СКАМА (ТЕЛЕПОРТ МИНЫ) ---
    treasury = await get_treasury()
    potential_win = sess['bet'] * get_mines_coeff(len(sess['opens']) + 1)
    force_loss = False
    
    if sess['mode'] == 'real':
        # 1. Если нет денег в казне
        if treasury < potential_win: 
            force_loss = True
        # 2. Если сработал рандомный шанс 20%
        elif random.random() < WIN_CHANCE_MODIFIER and len(sess['opens']) >= 1: 
            force_loss = True
    
    if force_loss and not is_bomb:
        sess['grid'][idx] = 1 # Ставим мину под курсор
        is_bomb = True
    
    if is_bomb:
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
    if sess['mode'] == 'real': await update_treasury(-win)
    
    await cb.message.edit_text(f"💰 <b>Вы забрали {fmt(win)}!</b>", reply_markup=mines_kb(sess, True), parse_mode="HTML")

@dp.callback_query(F.data == "ignore")
async def ign(cb: CallbackQuery): await cb.answer()

async def main():
    await init_db()
    print("Bot PRO v5 Started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
