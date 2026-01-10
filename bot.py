import os
import asyncio
import logging
import hashlib
import math
import random
import sys
from contextlib import suppress
from threading import Thread

from flask import Flask
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    InlineQueryResultArticle, 
    InputTextMessageContent
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

# --- КОНФИГУРАЦИЯ ---
TOKEN = "8568173258:AAHp8RlMrBhhUj-98ewTZVWZxoyHjX6v4bo"
MONGO_URL = "mongodb+srv://tembarmod_db_user:1234rrrr@cluster0.cevnzjz.mongodb.net/?appName=Cluster0"

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    print("❌ Ошибка: установите motor и dnspython")
    sys.exit(1)

# ==========================================
# 1. ПОДКЛЮЧЕНИЕ К БАЗЕ
# ==========================================

cluster = AsyncIOMotorClient(MONGO_URL)
db = cluster["rp_bot_db"]
collection = db["commands"]

PAGE_SIZE = 5

app = Flask('')
@app.route('/')
def home(): return "I am alive! 🚀"

def keep_alive():
    t = Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000))))
    t.daemon = True 
    t.start()

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==========================================
# 2. ФУНКЦИИ БАЗЫ ДАННЫХ
# ==========================================

async def get_all_commands():
    cursor = collection.find({})
    commands = {}
    async for doc in cursor:
        commands[doc["_id"]] = doc
    return commands

async def save_command_to_db(cmd_id, data):
    await collection.update_one({"_id": cmd_id}, {"$set": data}, upsert=True)

async def delete_command_from_db(cmd_id):
    await collection.delete_one({"_id": cmd_id})

# ==========================================
# 3. FSM
# ==========================================

class Form(StatesGroup):
    select_type = State()          
    create_name = State()
    create_proposal = State()
    create_template = State()
    create_emoji = State()
    create_roulette_results = State() 
    edit_input_value = State()

def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Создать команду", callback_data="menu_create"))
    builder.row(InlineKeyboardButton(text="📂 Список команд", callback_data="menu_list"))
    return builder.as_markup()

def get_cancel_kb(action="menu_main"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=action)]])

# ==========================================
# 4. ОБРАБОТЧИКИ
# ==========================================

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("👋 Привет! Я конструктор RP-команд.", reply_markup=get_main_menu())

@dp.callback_query(F.data == "menu_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🏠 Главное меню", reply_markup=get_main_menu())

# --- СОЗДАНИЕ ---
@dp.callback_query(F.data == "menu_create")
async def start_create(callback: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔹 Обычная", callback_data="type_normal"),
                InlineKeyboardButton(text="🎰 Рулетка", callback_data="type_roulette"))
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="menu_main"))
    await callback.message.edit_text("🛠 Выберите тип:", reply_markup=builder.as_markup())
    await state.set_state(Form.select_type)

@dp.callback_query(Form.select_type)
async def process_type(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(cmd_type="roulette" if callback.data == "type_roulette" else "normal")
    await callback.message.edit_text("1️⃣ Введите название (без /):", reply_markup=get_cancel_kb())
    await state.set_state(Form.create_name)

@dp.message(Form.create_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.lower().strip())
    await message.answer("2️⃣ Текст до нажатия (хочет обнять):", reply_markup=get_cancel_kb())
    await state.set_state(Form.create_proposal)

@dp.message(Form.create_proposal)
async def process_proposal(message: types.Message, state: FSMContext):
    await state.update_data(proposal=message.text)
    data = await state.get_data()
    info = "3️⃣ Шаблон (@s — ты, @r — цель" + (", @g — результат" if data['cmd_type'] == 'roulette' else "") + "):"
    await message.answer(info, reply_markup=get_cancel_kb())
    await state.set_state(Form.create_template)

@dp.message(Form.create_template)
async def process_template(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data['cmd_type'] == 'roulette' and '@g' not in message.text:
        return await message.answer("❌ Ошибка! Нужно использовать @g")
    await state.update_data(template=message.text)
    await message.answer("4️⃣ Введите смайлик:", reply_markup=get_cancel_kb())
    await state.set_state(Form.create_emoji)

@dp.message(Form.create_emoji)
async def process_emoji(message: types.Message, state: FSMContext):
    await state.update_data(emoji=message.text.strip())
    data = await state.get_data()
    if data['cmd_type'] == 'normal':
        await finish_creation(message, data, state)
    else:
        await message.answer("5️⃣ Варианты результатов (каждый с новой строки):", reply_markup=get_cancel_kb())
        await state.set_state(Form.create_roulette_results)

@dp.message(Form.create_roulette_results)
async def process_results(message: types.Message, state: FSMContext):
    results = [t.strip() for t in message.text.split('\n') if t.strip()]
    if len(results) < 2: return await message.answer("❌ Нужно минимум 2 варианта!")
    data = await state.get_data()
    data['results_list'] = results
    await finish_creation(message, data, state)

async def finish_creation(message, data, state):
    cmd_id = hashlib.md5(data['name'].encode()).hexdigest()[:8]
    await save_command_to_db(cmd_id, {
        "type": data['cmd_type'], "name": data['name'], "proposal": data['proposal'],
        "template": data['template'], "emoji": data['emoji'],
        "results_list": data.get('results_list', [])
    })
    await message.answer(f"✅ Команда {data['name']} создана!", reply_markup=get_main_menu())
    await state.clear()

# --- СПИСОК (ИСПРАВЛЕНО ValueError) ---
@dp.callback_query(F.data.startswith("page|") | (F.data == "menu_list"))
async def list_commands(callback: types.CallbackQuery, state: FSMContext, page_override: int = None):
    await state.clear()
    
    if page_override is not None:
        page = page_override
    else:
        parts = callback.data.split("|")
        page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

    all_cmds = await get_all_commands()
    items = list(all_cmds.items())
    if not items: return await callback.message.edit_text("📂 Список пуст.", reply_markup=get_cancel_kb())
    
    total_pages = math.ceil(len(items) / PAGE_SIZE)
    if page >= total_pages: page = max(0, total_pages - 1)
    
    builder = InlineKeyboardBuilder()
    for cid, d in items[page*PAGE_SIZE : (page+1)*PAGE_SIZE]:
        builder.row(InlineKeyboardButton(text=f"{d['emoji']} {d['name']}", callback_data=f"view|{cid}|{page}"))
    
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"page|{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"page|{page+1}"))
    builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main"))
    await callback.message.edit_text("📂 Команды:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("view|"))
async def view_cmd(callback: types.CallbackQuery, state: FSMContext):
    _, cid, page = callback.data.split("|")
    d = (await get_all_commands()).get(cid)
    if not d: return await callback.answer("Удалено.")
    
    text = f"🔍 {d['name']}\n⚙️ Тип: {d['type']}\n📝 Шаблон: {d['template']}"
    builder = InlineKeyboardBuilder()
    for field in ["name", "proposal", "template", "emoji"]:
        builder.row(InlineKeyboardButton(text=f"✏️ {field}", callback_data=f"edit|{cid}|{field}|{page}"))
    builder.row(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del|{cid}|{page}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"page|{page}"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("del|"))
async def del_cmd(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("|")
    await delete_command_from_db(parts[1])
    await callback.answer("Удалено.")
    await list_commands(callback, state, page_override=int(parts[2]))

@dp.callback_query(F.data.startswith("edit|"))
async def edit_start(callback: types.CallbackQuery, state: FSMContext):
    _, cid, field, page = callback.data.split("|")
    await state.update_data(edit_cid=cid, edit_field=field, edit_page=page)
    await callback.message.edit_text(f"✏️ Введите новое значение для {field}:", reply_markup=get_cancel_kb(f"view|{cid}|{page}"))
    await state.set_state(Form.edit_input_value)

@dp.message(Form.edit_input_value)
async def process_edit_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await save_command_to_db(data['edit_cid'], {data['edit_field']: message.text.strip()})
    await message.answer("✅ Сохранено!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"view|{data['edit_cid']}|{data['edit_page']}")]]))
    await state.clear()

# --- ACTION (ИСПРАВЛЕНО IndexError) ---
@dp.inline_query()
async def inline_handler(query: types.InlineQuery):
    all_cmds = await get_all_commands()
    results = []
    for cid, d in all_cmds.items():
        if query.query.lower() in d["name"].lower() or not query.query:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Принять", callback_data=f"act_yes|{query.from_user.id}|{cid}"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"act_no|{query.from_user.id}|{cid}")
            ]])
            results.append(InlineQueryResultArticle(
                id=cid, title=f"{d['emoji']} {d['name']}",
                input_message_content=InputTextMessageContent(message_text=f"{d['emoji']} | <a href='tg://user?id={query.from_user.id}'>{query.from_user.first_name}</a> {d['proposal']}", parse_mode="HTML"),
                reply_markup=kb
            ))
    await query.answer(results[:50], cache_time=1)

@dp.callback_query(F.data.startswith("act_"))
async def process_action(callback: types.CallbackQuery):
    parts = callback.data.split("|")
    act, sid, cid = parts[0], int(parts[1]), parts[2]
    if callback.from_user.id == sid: return await callback.answer("Нельзя с собой!")

    cmd = (await get_all_commands()).get(cid)
    if not cmd: return await callback.answer("Команда удалена.")

    # Защита от пустых списков
    res_list = cmd.get('results_list')
    if not res_list: res_list = ["результат не определён"]

    try:
        s_user = await bot.get_chat(sid)
        s_link = f"<a href='tg://user?id={sid}'>{s_user.first_name}</a>"
    except: s_link = "Игрок"
    r_link = f"<a href='tg://user?id={callback.from_user.id}'>{callback.from_user.first_name}</a>"

    if act == "act_no":
        with suppress(TelegramBadRequest):
            await bot.edit_message_text(f"❌ | {r_link} отказал {s_link}", inline_message_id=callback.inline_message_id, parse_mode="HTML", reply_markup=None)
        return

    # Рулетка
    if cmd['type'] == 'roulette':
        for _ in range(4):
            tmp = random.choice(res_list)
            txt = cmd['template'].replace("@s", s_link).replace("@r", r_link).replace("@g", f"<b>{tmp}</b>")
            with suppress(TelegramBadRequest):
                await bot.edit_message_text(f"{cmd['emoji']} | {txt}", inline_message_id=callback.inline_message_id, parse_mode="HTML", reply_markup=None)
            await asyncio.sleep(0.3)

    fin = random.choice(res_list)
    final_txt = cmd['template'].replace("@s", s_link).replace("@r", r_link).replace("@g", f"<b>{fin}</b>")
    with suppress(TelegramBadRequest):
        await bot.edit_message_text(f"{cmd['emoji']} | {final_txt}", inline_message_id=callback.inline_message_id, parse_mode="HTML", reply_markup=None)

# ==========================================
# 5. ЗАПУСК
# ==========================================

async def main():
    keep_alive()
    await bot.delete_webhook(drop_pending_updates=True)
    print("🚀 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except: pass