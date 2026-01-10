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

# Проверка библиотек
try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    print("❌ Ошибка: Не установлены библиотеки базы данных.")
    print("👉 Введите: pip install motor dnspython")
    sys.exit(1)

# ==========================================
# 1. ПОДКЛЮЧЕНИЕ К БАЗЕ
# ==========================================

cluster = AsyncIOMotorClient(MONGO_URL)
db = cluster["rp_bot_db"]
collection = db["commands"]

PAGE_SIZE = 5

# --- Flask для Render ---
app = Flask('')

@app.route('/')
def home():
    return "I am alive! 🚀"

def keep_alive():
    def run():
        app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
    t = Thread(target=run)
    t.daemon = True 
    t.start()

# --- Настройки бота ---
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
        cmd_id = doc["_id"]
        commands[cmd_id] = doc
    return commands

async def save_command_to_db(cmd_id, data):
    await collection.update_one({"_id": cmd_id}, {"$set": data}, upsert=True)

async def delete_command_from_db(cmd_id):
    await collection.delete_one({"_id": cmd_id})

# ==========================================
# 3. МАШИНА СОСТОЯНИЙ (FSM)
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
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена / Назад", callback_data=action)]])

# ==========================================
# 4. ЛОГИКА БОТА
# ==========================================

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 <b>Привет! Я RP-бот конструктор.</b>\n\n"
        "Я умею создавать и <b>редактировать</b> RP-команды!\n"
        "⬇️ <b>Меню:</b>",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "menu_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🏠 <b>Главное меню</b>", reply_markup=get_main_menu(), parse_mode="HTML")

# --- СОЗДАНИЕ ---

@dp.callback_query(F.data == "menu_create")
async def start_create(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔹 Обычная", callback_data="type_normal"),
                InlineKeyboardButton(text="🎰 Рулетка", callback_data="type_roulette"))
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="menu_main"))
    await callback.message.edit_text("🛠 <b>Выберите тип команды:</b>", reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.set_state(Form.select_type)

@dp.callback_query(Form.select_type)
async def process_type(callback: types.CallbackQuery, state: FSMContext):
    c_type = "roulette" if callback.data == "type_roulette" else "normal"
    await state.update_data(cmd_type=c_type)
    await callback.message.edit_text("1️⃣ <b>Введите название команды</b> (без /)\n<i>Пример: обнять</i>", reply_markup=get_cancel_kb(), parse_mode="HTML")
    await state.set_state(Form.create_name)

@dp.message(Form.create_name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.lower().strip())
    await message.answer("2️⃣ <b>Текст предложения</b> (до нажатия кнопки)\n<i>Пример: хочет обнять</i>", reply_markup=get_cancel_kb(), parse_mode="HTML")
    await state.set_state(Form.create_proposal)

@dp.message(Form.create_proposal)
async def process_proposal(message: types.Message, state: FSMContext):
    await state.update_data(proposal=message.text)
    data = await state.get_data()
    info = "3️⃣ <b>Введите шаблон сообщения</b>\n\n• <code>@s</code> — автор\n• <code>@r</code> — цель\n"
    if data['cmd_type'] == 'roulette':
        info += "• <code>@g</code> — случайный результат\n\n<i>Пример: @s обнял @r и ему выпало @g</i>"
    else:
        info += "\n<i>Пример: @s крепко обнимает @r</i>"
    await message.answer(info, reply_markup=get_cancel_kb(), parse_mode="HTML")
    await state.set_state(Form.create_template)

@dp.message(Form.create_template)
async def process_template(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data['cmd_type'] == 'roulette' and '@g' not in message.text:
        return await message.answer("❌ Ошибка! В рулетке обязательно должен быть тег <code>@g</code>", parse_mode="HTML")
    await state.update_data(template=message.text)
    await message.answer("4️⃣ <b>Введите смайлик</b> для этой команды:", reply_markup=get_cancel_kb(), parse_mode="HTML")
    await state.set_state(Form.create_emoji)

@dp.message(Form.create_emoji)
async def process_emoji(message: types.Message, state: FSMContext):
    await state.update_data(emoji=message.text.strip())
    data = await state.get_data()
    if data['cmd_type'] == 'normal':
        await finish_creation(message, data, state)
    else:
        await message.answer("5️⃣ <b>Введите варианты результатов</b>\n(каждый с новой строки)", reply_markup=get_cancel_kb(), parse_mode="HTML")
        await state.set_state(Form.create_roulette_results)

@dp.message(Form.create_roulette_results)
async def process_results(message: types.Message, state: FSMContext):
    results = [t.strip() for t in message.text.split('\n') if t.strip()]
    if len(results) < 2: return await message.answer("❌ Нужно минимум 2 варианта!", reply_markup=get_cancel_kb(), parse_mode="HTML")
    data = await state.get_data()
    data['results_list'] = results
    await finish_creation(message, data, state)

async def finish_creation(message, data, state):
    cmd_id = hashlib.md5(data['name'].encode()).hexdigest()[:8]
    payload = {
        "type": data['cmd_type'], "name": data['name'], "proposal": data['proposal'],
        "template": data['template'], "emoji": data['emoji'],
        "results_list": data.get('results_list', [])
    }
    await save_command_to_db(cmd_id, payload)
    await message.answer(f"✅ Команда <b>{data['name']}</b> создана!", reply_markup=get_main_menu(), parse_mode="HTML")
    await state.clear()

# --- СПИСОК И РЕДАКТИРОВАНИЕ ---

@dp.callback_query(F.data.startswith("page|") | (F.data == "menu_list"))
async def list_commands(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    page = int(callback.data.split("|")[1]) if "|" in callback.data else 0
    all_cmds = await get_all_commands()
    items = list(all_cmds.items())
    
    if not items: return await callback.message.edit_text("📂 Список пуст.", reply_markup=get_cancel_kb(), parse_mode="HTML")
    
    total_pages = math.ceil(len(items) / PAGE_SIZE)
    if page >= total_pages: page = max(0, total_pages - 1)
    start, end = page * PAGE_SIZE, (page + 1) * PAGE_SIZE
    
    builder = InlineKeyboardBuilder()
    for cid, d in items[start:end]:
        builder.row(InlineKeyboardButton(text=f"{d['emoji']} {d['name']}", callback_data=f"view|{cid}|{page}"))
    
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"page|{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"page|{page+1}"))
    builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="menu_main"))
    
    await callback.message.edit_text("📂 <b>Ваши команды:</b>", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("view|"))
async def view_cmd(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try: _, cid, page = callback.data.split("|")
    except: return await callback.answer("Ошибка данных", show_alert=True)

    all_cmds = await get_all_commands()
    d = all_cmds.get(cid)
    if not d: 
        await callback.answer("Команда не найдена", show_alert=True)
        return await list_commands(callback, state)

    text = f"🔍 <b>Команда:</b> {d['name']}\n⚙️ Тип: {'🎰 Рулетка' if d['type'] == 'roulette' else '🔹 Обычная'}\n📝 Шаблон: <code>{d['template']}</code>"
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏️ Название", callback_data=f"edit|{cid}|name|{page}"),
                InlineKeyboardButton(text="✏️ Текст до", callback_data=f"edit|{cid}|proposal|{page}"))
    builder.row(InlineKeyboardButton(text="✏️ Шаблон", callback_data=f"edit|{cid}|template|{page}"),
                InlineKeyboardButton(text="✏️ Эмодзи", callback_data=f"edit|{cid}|emoji|{page}"))
    if d['type'] == 'roulette': builder.row(InlineKeyboardButton(text="✏️ Варианты рулетки", callback_data=f"edit|{cid}|results_list|{page}"))
    builder.row(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del|{cid}|{page}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"page|{page}"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("del|"))
async def del_cmd(callback: types.CallbackQuery, state: FSMContext):
    _, cid, page = callback.data.split("|")
    await delete_command_from_db(cid)
    await callback.answer("Удалено!", show_alert=True)
    await list_commands(callback, state)

@dp.callback_query(F.data.startswith("edit|"))
async def edit_start(callback: types.CallbackQuery, state: FSMContext):
    _, cid, field, page = callback.data.split("|")
    await state.update_data(edit_cid=cid, edit_field=field, edit_page=page)
    await callback.message.edit_text(f"✏️ Введите новое значение для <b>{field}</b>:", reply_markup=get_cancel_kb(f"view|{cid}|{page}"), parse_mode="HTML")
    await state.set_state(Form.edit_input_value)

@dp.message(Form.edit_input_value)
async def process_edit_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cid, field, page = data.get('edit_cid'), data.get('edit_field'), data.get('edit_page')
    
    if not await collection.find_one({"_id": cid}):
        await message.answer("❌ Команда удалена.", reply_markup=get_main_menu())
        return await state.clear()

    new_val = message.text.strip()
    if field == "results_list":
        new_val = [t.strip() for t in new_val.split('\n') if t.strip()]
        if len(new_val) < 2: return await message.answer("❌ Минимум 2 варианта!", reply_markup=get_cancel_kb(f"view|{cid}|{page}"))
    
    await save_command_to_db(cid, {field: new_val})
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 К команде", callback_data=f"view|{cid}|{page}"))
    await message.answer(f"✅ Поле <b>{field}</b> обновлено!", reply_markup=builder.as_markup(), parse_mode="HTML")
    await state.clear()

# ==========================================
# 5. INLINE И ДЕЙСТВИЯ (ИСПРАВЛЕНО)
# ==========================================

@dp.inline_query()
async def inline_handler(query: types.InlineQuery):
    text = query.query.lower().strip()
    all_cmds = await get_all_commands()
    results = []
    
    count = 0
    for cid, d in all_cmds.items():
        if count >= 49: break
        if text in d["name"].lower() or not text:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Принять", callback_data=f"act_yes|{query.from_user.id}|{cid}"),
                InlineKeyboardButton(text="❌ Отказать", callback_data=f"act_no|{query.from_user.id}|{cid}")
            ]])
            results.append(InlineQueryResultArticle(
                id=cid, 
                title=f"{d['emoji']} {d['name']}",
                description=f"Отправить: {d['proposal']}",
                input_message_content=InputTextMessageContent(
                    message_text=f"{d['emoji']} | <a href='tg://user?id={query.from_user.id}'>{query.from_user.first_name}</a> {d['proposal']}", 
                    parse_mode="HTML"
                ), 
                reply_markup=kb
            ))
            count += 1
    await query.answer(results, cache_time=1, is_personal=True)

@dp.callback_query(F.data.startswith("act_"))
async def process_action(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("|")
        act, sid, cid = parts[0], int(parts[1]), parts[2]
    except: return await callback.answer("Ошибка", show_alert=True)

    if callback.from_user.id == sid: 
        return await callback.answer("Нельзя взаимодействовать с самим собой!", show_alert=True)
    
    all_cmds = await get_all_commands()
    cmd = all_cmds.get(cid)
    if not cmd: return await callback.answer("Команда удалена.", show_alert=True)

    # Получаем имена
    try:
        s_chat = await bot.get_chat(sid)
        s_name = s_chat.first_name
    except: s_name = "Игрок"

    s_link = f"<a href='tg://user?id={sid}'>{s_name}</a>"
    r_link = f"<a href='tg://user?id={callback.from_user.id}'>{callback.from_user.first_name}</a>"

    # ОТКАЗ
    if act == "act_no":
        # Одним вызовом меняем текст и удаляем кнопки
        with suppress(TelegramBadRequest):
            await bot.edit_message_text(
                text=f"❌ | {r_link} отказал пользователю {s_link}", 
                inline_message_id=callback.inline_message_id, 
                reply_markup=None, # <-- УДАЛЯЕМ КНОПКИ ТУТ
                parse_mode="HTML"
            )
        return

    # ПРИНЯТИЕ
    
    # 1. Анимация рулетки (если нужна)
    if cmd['type'] == 'roulette':
        delay = 0.1
        variants = cmd.get('results_list', ["?"])
        # Быстрая анимация (как просили)
        for _ in range(7):
            tmp = random.choice(variants)
            txt = cmd['template'].replace("@s", s_link).replace("@r", r_link).replace("@g", f"<b>{tmp}</b>")
            with suppress(TelegramBadRequest):
                # Меняем текст и сразу удаляем кнопки (на всякий случай, чтобы они не моргали)
                await bot.edit_message_text(
                    text=f"{cmd['emoji']} | {txt}", 
                    inline_message_id=callback.inline_message_id, 
                    reply_markup=None, 
                    parse_mode="HTML"
                )
            await asyncio.sleep(delay)
            delay += 0.1

    # 2. Финальный результат
    fin_g = random.choice(cmd.get('results_list', [""]))
    res = cmd['template'].replace("@s", s_link).replace("@r", r_link).replace("@g", f"<b>{fin_g}</b>")
    
    # Одним вызовом ставим финальный текст и гарантируем, что кнопок нет
    with suppress(TelegramBadRequest):
        await bot.edit_message_text(
            text=f"{cmd['emoji']} | {res}", 
            inline_message_id=callback.inline_message_id, 
            reply_markup=None, # <-- ГЛАВНОЕ ИСПРАВЛЕНИЕ: Текст меняется + Кнопки пропадают
            parse_mode="HTML"
        )

# ==========================================
# 6. ЗАПУСК
# ==========================================

async def main():
    print("🤖 Бот запускается...")
    keep_alive()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass