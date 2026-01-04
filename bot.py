import os
import asyncio
import logging
import hashlib
import math
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

# ==========================================
# 1. КОНФИГУРАЦИЯ И ОЖИВИТЕЛЬ ДЛЯ RENDER
# ==========================================

TOKEN = "8519096046:AAFPwqAigHoBkasZ595iESWsSuvrBincYUo"

# Мини-сервер Flask для обмана Render
app = Flask('')

@app.route('/')
def home():
    return "I am alive! 🚀"

def run_web_server():
    # Render передает порт в переменную среды PORT, по умолчанию 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True # Поток завершится вместе с основным процессом
    t.start()

# Настройка логирования и бота
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- БАЗА ДАННЫХ ---
# ВАЖНО: На бесплатном Render данные сотрутся после перезагрузки сервера!
custom_commands = {}
PAGE_SIZE = 5

# --- СОСТОЯНИЯ ---
class Form(StatesGroup):
    create_name = State()
    create_proposal = State()
    create_template = State()
    create_emoji = State()
    edit_value = State()

# ==========================================
# 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def get_main_menu():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Создать команду", callback_data="menu_create"))
    builder.row(InlineKeyboardButton(text="📂 Список команд", callback_data="menu_list"))
    return builder.as_markup()

def get_cancel_kb(action="menu_main"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена / Назад", callback_data=action)]
    ])

# ==========================================
# 3. ХЕНДЛЕРЫ (СТАРТ И МЕНЮ)
# ==========================================

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 <b>Привет! Я RP-бот.</b>\n\n"
        "Я работаю через инлайн-режим. Создавайте свои действия и используйте их в любых чатах!\n\n"
        "⬇️ <b>Выберите действие:</b>",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "menu_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👋 <b>Главное меню</b>",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

# ==========================================
# 4. СОЗДАНИЕ КОМАНДЫ (WIZARD)
# ==========================================

@dp.callback_query(F.data == "menu_create")
async def start_create(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "1️⃣ <b>Введите название команды</b>\n"
        "(Например: <i>дать пять</i>, <i>поцеловать</i>)\n"
        "Максимум 60 символов.",
        reply_markup=get_cancel_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Form.create_name)

@dp.message(Form.create_name)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.lower().strip()
    if len(name) > 60:
        await message.answer("❌ Слишком длинное название. Попробуйте еще раз.", reply_markup=get_cancel_kb())
        return
    if "|" in name:
        await message.answer("❌ Символ '|' запрещен.", reply_markup=get_cancel_kb())
        return

    await state.update_data(name=name)
    await message.answer(
        f"Название: <b>{name}</b>\n\n"
        "2️⃣ <b>Введите текст предложения</b>\n"
        "Это текст, который виден <b>ДО</b> принятия.\n"
        "<i>Пример: хочет обнять</i>",
        reply_markup=get_cancel_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Form.create_proposal)

@dp.message(Form.create_proposal)
async def process_proposal(message: types.Message, state: FSMContext):
    if len(message.text) > 100:
        await message.answer("❌ Максимум 100 символов.", reply_markup=get_cancel_kb())
        return

    await state.update_data(proposal=message.text)
    await message.answer(
        "3️⃣ <b>Введите шаблон результата</b>\n"
        "Используйте переменные:\n"
        "<b>@s</b> — Ваш ник (кто отправил)\n"
        "<b>@r</b> — Ник собеседника (кто принял)\n\n"
        "<i>Пример: @s крепко обнял @r</i>",
        reply_markup=get_cancel_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Form.create_template)

@dp.message(Form.create_template)
async def process_template(message: types.Message, state: FSMContext):
    template = message.text
    if len(template) > 150:
        await message.answer("❌ Максимум 150 символов.", reply_markup=get_cancel_kb())
        return
    
    await state.update_data(template=template)
    await message.answer(
        "4️⃣ <b>Выберите эмодзи</b>\n"
        "Отправьте ОДИН смайлик. Он будет стоять в начале (как разделитель).\n"
        "<i>Пример: 😃</i>",
        reply_markup=get_cancel_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Form.create_emoji)

@dp.message(Form.create_emoji)
async def process_emoji(message: types.Message, state: FSMContext):
    emoji = message.text.strip()
    if len(emoji) > 10: # Запас для сложных эмодзи
        await message.answer("❌ Отправьте только один смайлик.", reply_markup=get_cancel_kb())
        return

    data = await state.get_data()
    cmd_id = hashlib.md5(data['name'].encode()).hexdigest()[:8]
    
    custom_commands[cmd_id] = {
        "name": data['name'],
        "proposal": data['proposal'],
        "template": data['template'],
        "emoji": emoji
    }
    
    bot_info = await bot.get_me()
    await message.answer(
        f"✅ <b>Команда создана!</b>\n\n"
        f"Название: {data['name']}\n"
        f"Вид: {emoji} | Ник {data['proposal']}\n\n"
        f"Попробуйте: <code>@{bot_info.username} {data['name']}</code>",
        reply_markup=get_cancel_kb("menu_main"),
        parse_mode="HTML"
    )
    await state.clear()

# ==========================================
# 5. СПИСОК И УПРАВЛЕНИЕ
# ==========================================

async def show_list_page(callback: types.CallbackQuery, page: int):
    items = list(custom_commands.items())
    
    if not items:
        await callback.message.edit_text(
            "📂 Список команд пуст.", 
            reply_markup=get_cancel_kb("menu_main")
        )
        return

    total_pages = math.ceil(len(items) / PAGE_SIZE)
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    current_items = items[start:end]

    builder = InlineKeyboardBuilder()
    
    for cmd_id, data in current_items:
        emoji = data.get('emoji', '🔹')
        builder.row(InlineKeyboardButton(text=f"{emoji} {data['name']}", callback_data=f"view|{cmd_id}|{page}"))

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"page|{page-1}"))
    nav_row.append(InlineKeyboardButton(text=f"Стр {page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"page|{page+1}"))
    
    builder.row(*nav_row)
    builder.row(InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu_main"))

    await callback.message.edit_text("📂 <b>Ваши команды:</b>", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "menu_list")
async def show_list_first_page(callback: types.CallbackQuery):
    await show_list_page(callback, 0)

@dp.callback_query(F.data.startswith("page|"))
async def paginate(callback: types.CallbackQuery):
    page = int(callback.data.split("|")[1])
    await show_list_page(callback, page)

@dp.callback_query(F.data.startswith("view|"))
async def view_command(callback: types.CallbackQuery):
    _, cmd_id, page = callback.data.split("|")
    data = custom_commands.get(cmd_id)
    if not data:
        await callback.answer("Команда не найдена", show_alert=True)
        return

    emoji = data.get('emoji', '🔹')
    text = (
        f"📌 <b>Команда:</b> {emoji} {data['name']}\n\n"
        f"📝 <b>Предложение:</b> {data['proposal']}\n"
        f"💬 <b>Шаблон:</b> {data['template']}\n"
        f"🎨 <b>Эмодзи:</b> {emoji}"
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏️ Название", callback_data=f"edit|{cmd_id}|name|{page}"))
    builder.row(InlineKeyboardButton(text="✏️ Предложение", callback_data=f"edit|{cmd_id}|proposal|{page}"))
    builder.row(InlineKeyboardButton(text="✏️ Шаблон", callback_data=f"edit|{cmd_id}|template|{page}"))
    builder.row(InlineKeyboardButton(text="✏️ Эмодзи", callback_data=f"edit|{cmd_id}|emoji|{page}"))
    builder.row(InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del|{cmd_id}|{page}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data=f"page|{page}"))

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("del|"))
async def delete_command(callback: types.CallbackQuery):
    _, cmd_id, page = callback.data.split("|")
    if cmd_id in custom_commands:
        del custom_commands[cmd_id]
        await callback.answer("Удалено!")
    await show_list_page(callback, int(page))

@dp.callback_query(F.data.startswith("edit|"))
async def edit_start(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("|")
    cmd_id, field, page = parts[1], parts[2], parts[3]
    labels = {"name": "название", "proposal": "предложение", "template": "шаблон", "emoji": "эмодзи"}
    
    await state.update_data(edit_cmd_id=cmd_id, edit_field=field, return_page=page)
    await callback.message.edit_text(
        f"✍️ Введите новое <b>{labels[field]}</b>:",
        reply_markup=get_cancel_kb(f"view|{cmd_id}|{page}"),
        parse_mode="HTML"
    )
    await state.set_state(Form.edit_value)

@dp.message(Form.edit_value)
async def edit_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    cmd_id, field, page = data['edit_cmd_id'], data['edit_field'], data['return_page']
    new_value = message.text.strip()
    
    if field == "emoji" and len(new_value) > 10:
         await message.answer("❌ Эмодзи слишком длинный.")
         return
    
    if cmd_id in custom_commands:
        custom_commands[cmd_id][field] = new_value
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К команде", callback_data=f"view|{cmd_id}|{page}")]
        ])
        await message.answer(f"✅ Поле <b>{field}</b> обновлено.", reply_markup=kb, parse_mode="HTML")
    await state.clear()

# ==========================================
# 6. INLINE РЕЖИМ (ИСПОЛЬЗОВАНИЕ)
# ==========================================

@dp.inline_query()
async def inline_handler(query: types.InlineQuery):
    text = query.query.lower().strip()
    results = []
    sender_id = query.from_user.id
    sender_name = query.from_user.first_name

    for cmd_id, data in custom_commands.items():
        if text in data["name"].lower() or text == "":
            emoji = data.get("emoji", "🔹")
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Принять", callback_data=f"act_yes|{sender_id}|{cmd_id}"),
                    InlineKeyboardButton(text="❌ Отказать", callback_data=f"act_no|{sender_id}|{cmd_id}")
                ]
            ])
            msg_text = f"{emoji} | <a href='tg://user?id={sender_id}'>{sender_name}</a> {data['proposal']}"
            result_id = hashlib.md5(f"{cmd_id}{sender_id}".encode()).hexdigest()
            results.append(InlineQueryResultArticle(
                id=result_id,
                title=f"{emoji} {data['name']}",
                description=data["proposal"],
                input_message_content=InputTextMessageContent(message_text=msg_text, parse_mode="HTML"),
                reply_markup=kb
            ))
    await query.answer(results, cache_time=1, is_personal=True)

# ==========================================
# 7. ОБРАБОТКА ДЕЙСТВИЙ (YES/NO)
# ==========================================

@dp.callback_query(F.data.startswith("act_"))
async def process_action(callback: types.CallbackQuery):
    data = callback.data.split("|")
    if len(data) != 3: return
    action_type, sender_id, cmd_id = data[0], int(data[1]), data[2]
    target = callback.from_user
    
    if target.id == sender_id:
        await callback.answer("Нельзя использовать на себе!", show_alert=True)
        return

    cmd_data = custom_commands.get(cmd_id)
    if not cmd_data:
        await callback.answer("Команда удалена.", show_alert=True)
        return

    r_link = f"<a href='tg://user?id={target.id}'>{target.first_name}</a>"
    try:
        sender_chat = await bot.get_chat(sender_id)
        s_name = sender_chat.first_name
    except:
        s_name = "Игрок"
    s_link = f"<a href='tg://user?id={sender_id}'>{s_name}</a>"
    emoji = cmd_data.get("emoji", "🔹")

    if action_type == "act_yes":
        result_content = cmd_data["template"].replace("@s", s_link).replace("@r", r_link)
        final_text = f"{emoji} | {result_content}"
    else:
        final_text = f"❌ | {r_link} отказался от действия <b>{cmd_data['name']}</b>."

    await bot.edit_message_text(
        text=final_text,
        inline_message_id=callback.inline_message_id,
        parse_mode="HTML",
        reply_markup=None
    )

# ==========================================
# 8. ЗАПУСК ВСЕГО
# ==========================================

async def main():
    print("Запуск оживителя для Render...")
    keep_alive() # Запуск Flask в фоне
    
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот запущен и готов к работе! 🚀")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")