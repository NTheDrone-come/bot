import os
import asyncio
import logging
import hashlib
import math
import random
import json  # <--- ДОБАВЛЕН ИМПОРТ
from threading import Thread
from contextlib import suppress

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

# ==========================================
# 1. КОНФИГУРАЦИЯ
# ==========================================

TOKEN = "8568173258:AAEPKVdX8hMhPzRGwiXoUmbpgGrWRYxDeJA" 

# Имя файла для базы данных
DB_FILE = "komandi.json" 

# --- Flask для Render ---
app = Flask('')

@app.route('/')
def home():
    return "I am alive! 🚀"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True 
    t.start()

# --- Настройки бота ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==========================================
# 1.1 ФУНКЦИИ СОХРАНЕНИЯ / ЗАГРУЗКИ (НОВОЕ)
# ==========================================

def load_database():
    """Загружает команды из файла при старте."""
    if not os.path.exists(DB_FILE):
        return {} # Если файла нет, возвращаем пустой словарь
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Ошибка чтения базы данных: {e}")
        return {}

def save_database():
    """Сохраняет текущие команды в файл."""
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            # ensure_ascii=False позволяет сохранять русские буквы читаемыми
            # indent=4 делает файл красивым (с отступами)
            json.dump(custom_commands, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logging.error(f"Ошибка сохранения базы данных: {e}")

# --- БАЗА ДАННЫХ ---
# Теперь загружаем данные из файла при запуске
custom_commands = load_database()
PAGE_SIZE = 5

# --- МАШИНА СОСТОЯНИЙ (FSM) ---
class Form(StatesGroup):
    select_type = State()         
    create_name = State()
    create_proposal = State()
    create_template = State()
    create_emoji = State()
    create_roulette_results = State() 

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
# 3. СТАРТ И МЕНЮ
# ==========================================

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 <b>Привет! Я RP-бот конструктор.</b>\n\n"
        "Я умею создавать обычные действия и <b>Рулетки</b>!\n"
        "Все команды сохраняются в файл.\n"
        "⬇️ <b>Меню:</b>",
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
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔹 Обычная", callback_data="type_normal"))
    builder.row(InlineKeyboardButton(text="🎰 Рулетка", callback_data="type_roulette"))
    builder.row(InlineKeyboardButton(text="🔙 Отмена", callback_data="menu_main"))
    
    await callback.message.edit_text(
        "🛠 <b>Выберите тип команды:</b>\n\n"
        "🔹 <b>Обычная:</b> Просто действие.\n"
        "🎰 <b>Рулетка:</b> Анимация перебора вариантов (@g) перед результатом.",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await state.set_state(Form.select_type)

@dp.callback_query(Form.select_type)
async def process_type(callback: types.CallbackQuery, state: FSMContext):
    c_type = "roulette" if callback.data == "type_roulette" else "normal"
    await state.update_data(cmd_type=c_type)
    
    await callback.message.edit_text(
        "1️⃣ <b>Введите название команды</b>\n"
        "(Пример: <i>поцеловать</i>, <i>крутить слот</i>)",
        reply_markup=get_cancel_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Form.create_name)

@dp.message(Form.create_name)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.lower().strip()
    if len(name) > 60:
        await message.answer("❌ Слишком длинно.", reply_markup=get_cancel_kb())
        return

    await state.update_data(name=name)
    await message.answer(
        f"Название: <b>{name}</b>\n\n"
        "2️⃣ <b>Текст предложения</b>\n"
        "Виден ДО нажатия кнопки.\n"
        "<i>Пример: хочет испытать удачу</i>",
        reply_markup=get_cancel_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Form.create_proposal)

@dp.message(Form.create_proposal)
async def process_proposal(message: types.Message, state: FSMContext):
    await state.update_data(proposal=message.text)
    
    data = await state.get_data()
    is_roulette = (data['cmd_type'] == 'roulette')
    
    info_text = (
        "3️⃣ <b>Шаблон результата</b>\n"
        "Используйте переменные:\n"
        "<b>@s</b> — Вы (отправитель)\n"
        "<b>@r</b> — Собеседник\n"
    )
    
    if is_roulette:
        info_text += "\n🎰 <b>ВАЖНО:</b> Для рулетки ОБЯЗАТЕЛЬНО добавьте <b>@g</b>.\n" \
                     "Там будут мелькать варианты, а потом выпадет итог.\n\n" \
                     "<i>Пример: @s поцеловал @r в @g</i>"
    else:
        info_text += "\n<i>Пример: @s обнял @r</i>"

    await message.answer(info_text, reply_markup=get_cancel_kb(), parse_mode="HTML")
    await state.set_state(Form.create_template)

@dp.message(Form.create_template)
async def process_template(message: types.Message, state: FSMContext):
    data = await state.get_data()
    template = message.text
    
    if data['cmd_type'] == 'roulette' and '@g' not in template:
        await message.answer("❌ Для рулетки нужен символ <b>@g</b> в шаблоне!", reply_markup=get_cancel_kb(), parse_mode="HTML")
        return

    await state.update_data(template=template)
    await message.answer(
        "4️⃣ <b>Выберите эмодзи</b>\n"
        "Один смайлик для начала сообщения.",
        reply_markup=get_cancel_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Form.create_emoji)

@dp.message(Form.create_emoji)
async def process_emoji(message: types.Message, state: FSMContext):
    emoji = message.text.strip()
    if len(emoji) > 10: 
        await message.answer("❌ Слишком длинный эмодзи.", reply_markup=get_cancel_kb())
        return

    await state.update_data(emoji=emoji)
    data = await state.get_data()

    if data['cmd_type'] == 'normal':
        save_command(data)
        await send_success(message, data)
        await state.clear()
    else:
        await message.answer(
            "5️⃣ <b>Варианты для @g</b>\n"
            "Эти слова будут мелькать в анимации, и одно из них выпадет.\n"
            "<b>Каждый вариант с новой строки!</b>\n\n"
            "<i>Пример (для поцелуя):\nгубы\nщеку\nлоб\nнос</i>",
            reply_markup=get_cancel_kb(),
            parse_mode="HTML"
        )
        await state.set_state(Form.create_roulette_results)

@dp.message(Form.create_roulette_results)
async def process_results(message: types.Message, state: FSMContext):
    results = [t.strip() for t in message.text.split('\n') if t.strip()]
    if len(results) < 2:
        await message.answer("❌ Введите хотя бы два варианта для интереса.", reply_markup=get_cancel_kb())
        return
        
    data = await state.get_data()
    data['results_list'] = results 
    
    save_command(data)
    await send_success(message, data)
    await state.clear()

# --- Сохранение ---
def save_command(data):
    cmd_id = hashlib.md5(data['name'].encode()).hexdigest()[:8]
    custom_commands[cmd_id] = {
        "type": data['cmd_type'],
        "name": data['name'],
        "proposal": data['proposal'],
        "template": data['template'],
        "emoji": data['emoji'],
        "results_list": data.get('results_list', [])
    }
    save_database() # <--- СОХРАНЯЕМ В ФАЙЛ

async def send_success(message, data):
    bot_info = await bot.get_me()
    type_icon = "🎰" if data['cmd_type'] == 'roulette' else "🔹"
    await message.answer(
        f"✅ <b>Команда создана!</b>\n\n"
        f"Тип: {type_icon}\n"
        f"Название: {data['name']}\n"
        f"Попробуйте: <code>@{bot_info.username} {data['name']}</code>",
        reply_markup=get_cancel_kb("menu_main"),
        parse_mode="HTML"
    )

# ==========================================
# 5. СПИСОК
# ==========================================
async def show_list_page(callback: types.CallbackQuery, page: int):
    items = list(custom_commands.items())
    if not items:
        await callback.message.edit_text("📂 Пусто.", reply_markup=get_cancel_kb("menu_main"))
        return

    total_pages = math.ceil(len(items) / PAGE_SIZE)
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    
    builder = InlineKeyboardBuilder()
    for cmd_id, data in items[start:end]:
        emoji = data.get('emoji', '🔹')
        builder.row(InlineKeyboardButton(text=f"{emoji} {data['name']}", callback_data=f"del|{cmd_id}|{page}"))

    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"page|{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"page|{page+1}"))
    
    builder.row(*nav)
    builder.row(InlineKeyboardButton(text="🔙 Меню", callback_data="menu_main"))
    await callback.message.edit_text("📂 <b>Команды (нажми чтобы удалить):</b>", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "menu_list")
async def list_start(cb): await show_list_page(cb, 0)

@dp.callback_query(F.data.startswith("page|"))
async def list_page(cb): await show_list_page(cb, int(cb.data.split("|")[1]))

@dp.callback_query(F.data.startswith("del|"))
async def list_del(cb):
    _, cmd_id, page = cb.data.split("|")
    if cmd_id in custom_commands:
        del custom_commands[cmd_id]
        save_database() # <--- СОХРАНЯЕМ ИЗМЕНЕНИЯ (УДАЛЕНИЕ) В ФАЙЛ
    await show_list_page(cb, int(page))

# ==========================================
# 6. INLINE РЕЖИМ
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
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅", callback_data=f"act_yes|{sender_id}|{cmd_id}"),
                InlineKeyboardButton(text="❌", callback_data=f"act_no|{sender_id}|{cmd_id}")
            ]])
            
            msg_text = f"{emoji} | <a href='tg://user?id={sender_id}'>{sender_name}</a> {data['proposal']}"
            res_id = hashlib.md5(f"{cmd_id}{sender_id}".encode()).hexdigest()
            
            description = "Действие"
            if data['type'] == 'roulette':
                description = f"Рулетка: {', '.join(data['results_list'][:3])}..."

            results.append(InlineQueryResultArticle(
                id=res_id, title=f"{emoji} {data['name']}",
                description=description,
                input_message_content=InputTextMessageContent(message_text=msg_text, parse_mode="HTML"),
                reply_markup=kb
            ))
    await query.answer(results, cache_time=1, is_personal=True)

# ==========================================
# 7. ОБРАБОТКА ДЕЙСТВИЙ
# ==========================================

@dp.callback_query(F.data.startswith("act_"))
async def process_action(callback: types.CallbackQuery):
    try:
        data = callback.data.split("|")
        action_type, sender_id, cmd_id = data[0], int(data[1]), data[2]
        target = callback.from_user
        
        if target.id == sender_id:
            await callback.answer("Нельзя на себе!", show_alert=True)
            return

        cmd_data = custom_commands.get(cmd_id)
        if not cmd_data:
            await callback.answer("Команда удалена.", show_alert=True)
            return

        with suppress(TelegramBadRequest):
            await bot.edit_message_reply_markup(inline_message_id=callback.inline_message_id, reply_markup=None)

        r_link = f"<a href='tg://user?id={target.id}'>{target.first_name}</a>"
        try:
            s_chat = await bot.get_chat(sender_id)
            s_link = f"<a href='tg://user?id={sender_id}'>{s_chat.first_name}</a>"
        except:
            s_link = f"<a href='tg://user?id={sender_id}'>Игрок</a>"
        
        emoji = cmd_data.get("emoji", "🔹")
        template = cmd_data['template']

        if action_type == "act_no":
            final_text = f"❌ | {r_link} отказался от <b>{cmd_data['name']}</b>."
            with suppress(TelegramBadRequest):
                await bot.edit_message_text(text=final_text, inline_message_id=callback.inline_message_id, parse_mode="HTML")
            return

        if cmd_data['type'] == 'roulette':
            variants = cmd_data['results_list']
            for _ in range(15):
                temp_g = random.choice(variants)
                anim_text = template.replace("@s", s_link).replace("@r", r_link).replace("@g", f"<b>{temp_g}</b>")
                full_anim_text = f"{emoji} | {anim_text}"
                
                with suppress(TelegramBadRequest):
                    await bot.edit_message_text(text=full_anim_text, inline_message_id=callback.inline_message_id, parse_mode="HTML")
                
                await asyncio.sleep(0.25)

        final_text_content = template.replace("@s", s_link).replace("@r", r_link)
        
        if cmd_data['type'] == 'roulette':
            final_g = random.choice(cmd_data['results_list'])
            final_text_content = final_text_content.replace("@g", f"<b>{final_g}</b>")
        
        final_message = f"{emoji} | {final_text_content}"

        with suppress(TelegramBadRequest):
            await bot.edit_message_text(text=final_message, inline_message_id=callback.inline_message_id, parse_mode="HTML")

    except Exception as e:
        print(f"Error: {e}")

# ==========================================
# 8. ЗАПУСК
# ==========================================

async def main():
    print("Start Flask...")
    keep_alive()
    await bot.delete_webhook(drop_pending_updates=True)
    print("Bot started! 🚀")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except:
        pass