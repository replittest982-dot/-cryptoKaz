import asyncio
import logging
import sys
import os
import random
from aiohttp import web
import socketio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import WebAppInfo, ReplyKeyboardMarkup, KeyboardButton

# === НАСТРОЙКИ ===
TOKEN = os.getenv("BOT_TOKEN")
# ВАЖНО: Укажи ссылку на свой GitHub Pages
WEB_APP_URL = "https://replittest982-dot.github.io/-cryptoKaz/"
PORT = int(os.getenv("PORT", 8080)) # Bothost обычно дает порт, или используем 8080

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# === 1. НАСТРОЙКА SOCKET.IO (СЕРВЕР) ===
sio = socketio.AsyncServer(async_mode='aiohttp', cors_allowed_origins='*')
app = web.Application()
sio.attach(app)

# Глобальное состояние игры
game_state = {
    "status": "WAITING", # WAITING, FLYING, CRASHED
    "multiplier": 1.00,
    "history": []        # История последних крашей
}

# === 2. ИГРОВОЙ ЦИКЛ (ДВИЖОК) ===
async def game_engine():
    print("🚀 ДВИЖОК ИГРЫ ЗАПУЩЕН")
    while True:
        # ФАЗА 1: ОЖИДАНИЕ (5 сек)
        game_state["status"] = "WAITING"
        game_state["multiplier"] = 1.00
        await sio.emit('game_update', game_state)
        await asyncio.sleep(5)

        # ФАЗА 2: ПОЛЕТ
        game_state["status"] = "FLYING"
        crash_point = generate_crash_point()
        print(f"🎯 Новый раунд! Краш будет на: {crash_point}x")

        while game_state["multiplier"] < crash_point:
            # Рост коэффициента (экспонента)
            game_state["multiplier"] += game_state["multiplier"] * 0.06
            if game_state["multiplier"] > crash_point:
                game_state["multiplier"] = crash_point
            
            # Отправляем всем игрокам новую позицию ракеты
            await sio.emit('game_tick', round(game_state["multiplier"], 2))
            await asyncio.sleep(0.1) # Скорость обновления (чем меньше, тем плавнее)

        # ФАЗА 3: КРАШ (ВЗРЫВ)
        game_state["status"] = "CRASHED"
        game_state["multiplier"] = crash_point
        
        # Добавляем в историю
        game_state["history"].insert(0, round(crash_point, 2))
        if len(game_state["history"]) > 10: game_state["history"].pop()
        
        await sio.emit('game_crash', game_state)
        await asyncio.sleep(3) # Пауза перед новым раундом

def generate_crash_point():
    # Честная генерация (как в Aviator)
    if random.random() < 0.03: return 1.00 # 3% шанс мгновенного краша
    return round(0.99 / (1 - random.random()), 2)

# === 3. НАСТРОЙКА БОТА ===
bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    # Мы должны передать URL сокета, чтобы WebApp знал, куда подключаться
    # На Bothost URL сервера обычно это домен хостинга + порт
    # Но для теста пока оставим просто WebApp URL
    
    kb = [[KeyboardButton(text="🚀 ИГРАТЬ ОНЛАЙН", web_app=WebAppInfo(url=WEB_APP_URL))]]
    await message.answer(f"Подключайся к общей игре! 🌍", reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))

# === ЗАПУСК ВСЕГО ВМЕСТЕ ===
async def on_startup(app):
    asyncio.create_task(game_engine()) # Запускаем игру
    asyncio.create_task(dp.start_polling(bot)) # Запускаем бота

app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, port=PORT)
