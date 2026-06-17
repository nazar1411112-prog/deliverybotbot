import os
import asyncio
import logging
import sqlite3
import urllib.parse
import random  # Для симуляции км Яндекс карт, если нет API ключа
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import Command

# Настройки логирования
logging.basicConfig(level=logging.INFO)

# --- CONFIG AND ENV ---
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))  # Telegram ID главного админа
PORT = int(os.getenv("PORT", "8080"))

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()

# --- ЛОКАЛИЗАЦИЯ (RU, RO, EN) ---
LOCALIZATION = {
    'ru': {
        'start': 'Выберите язык / Alegeți limba / Choose language:',
        'role': 'Выберите вашу роль:',
        'client': 'Клиент 👤',
        'courier': 'Курьер 🚗',
        'blocked': 'Вы заблокированы или ожидаете одобрения.',
        'send_photo': 'Отправьте фото вашего паспорта/документа для верификации:',
        'wait_admin': 'Ваша заявка отправлена админу. Ожидайте одобрения.',
        'approved': 'Вы успешно одобрены! Переключите статус на Онлайн, чтобы работать.',
        'status_changed': 'Статус изменен на: ',
        'online': 'В Сети (Онлайн) 🟢',
        'offline': 'Не в сети (Оффлайн) 🔴',
        'history': 'История заработка 💰',
        'select_car': 'Выберите тип доставки:',
        'standard': 'Стандарт (10 лей/км)',
        'cargo': 'Грузовой (20 лей/км)',
        'enter_address_a': 'Введите адрес точки А:',
        'enter_phone_a': 'Введите номер телефона для точки А:',
        'enter_tg_a': 'Введите Telegram аккаунт для точки А (или нажмите /skip):',
        'enter_address_b': 'Введите адрес точки Б:',
        'enter_phone_b': 'Введите номер телефона для точки Б:',
        'enter_tg_b': 'Введите Telegram аккаунт для точки Б (или нажмите /skip):',
        'enter_comment': 'Оставьте комментарий для курьера (или нажмите /skip):',
        'confirm_order': 'Расчетная стоимость: {price} MDL (Дистанция: {dist} км).\nПодтверждаете заказ?',
        'yes': 'Да ✅',
        'no': 'Нет ❌',
        'order_created': 'Заказ создан! Ищем курьера...',
        'cancel': 'Отменить заказ 🛑',
        'at_point_a': 'Я на точке А 📍',
        'at_point_b': 'Я на месте (Точка Б) 🏁',
        'client_notified_a': 'Клиент уведомлен, что вы на точке А.',
        'client_notified_b': 'Клиент уведомлен, что вы на точке Б.',
        'courier_at_a': 'Курьер прибыл на точку А!',
        'courier_at_b': 'Курьер прибыл на точку Б! Заберите посылку.',
        'afk_check': 'Вы тут? Подтвердите, что вы онлайн за 10 минут!',
        'afk_btn': 'Я тут 👋',
        'order_cancelled_afk': 'Заказ отменен из-за неактивности клиента. Курьер, вы можете оставить посылку себе.',
        'no_orders': 'Нет висящих заказов.',
        'order_info': '📦 Новый заказ [{type}]\nОт: {addr_a} (Тел: {phone_a})\nДо: {addr_b} (Тел: {phone_b})\nЦена курьеру: {price} MDL\nКомментарий: {comment}'
    },
    'ro': {
        'start': 'Alegeți limba:',
        'role': 'Alegeți rolul:',
        'client': 'Client 👤',
        'courier': 'Curier 🚗',
        'blocked': 'Sunteți blocat sau așteptați aprobarea.',
        'send_photo': 'Trimiteți o fotografie a documentului pentru verificare:',
        'wait_admin': 'Cererea a fost trimisă. Așteptați aprobarea.',
        'approved': 'Aprobat cu succes! Schimbați statutul în Online pentru a lucra.',
        'status_changed': 'Statut schimbat în: ',
        'online': 'Online 🟢',
        'offline': 'Offline 🔴',
        'history': 'Istoric câștiguri 💰',
        'select_car': 'Selectați tipul de livrare:',
        'standard': 'Standard (10 MDL/km)',
        'cargo': 'Marfă (20 MDL/km)',
        'enter_address_a': 'Introduceți adresa punctului A:',
        'enter_phone_a': 'Introduceți numărul de telefon pentru punctul A:',
        'enter_tg_a': 'Introduceți contul TG pentru punctul A (sau /skip):',
        'enter_address_b': 'Introduceți adresa punctului B:',
        'enter_phone_b': 'Introduceți numărul de telefon pentru punctul B:',
        'enter_tg_b': 'Introduceți contul TG pentru punctul B (sau /skip):',
        'enter_comment': 'Comentariu pentru curier (sau /skip):',
        'confirm_order': 'Preț estimat: {price} MDL ({dist} km).\nConfirmați comanda?',
        'yes': 'Da ✅',
        'no': 'Nu ❌',
        'order_created': 'Comanda a fost creată! Căutăm un curier...',
        'cancel': 'Anulează comanda 🛑',
        'at_point_a': 'Sunt la punctul A 📍',
        'at_point_b': 'Sunt la locul stabilit (Punctul B) 🏁',
        'client_notified_a': 'Clientul a fost notificat că sunteți la punctul A.',
        'client_notified_b': 'Clientul a fost notificat că sunteți la punctul B.',
        'courier_at_a': 'Curierul a sosit la punctul A!',
        'courier_at_b': 'Curierul a sosit la punctul B!',
        'afk_check': 'Sunteți aici? Confirmați că sunteți online în 10 minute!',
        'afk_btn': 'Sunt aici 👋',
        'order_cancelled_afk': 'Comanda a fost anulată. Curierule, poți păstra pachetul.',
        'no_orders': 'Nu sunt comenzi active.',
        'order_info': '📦 Comandă nouă [{type}]\nDe la: {addr_a}\nLa: {addr_b}\nPreț: {price} MDL'
    },
    'en': {
        'start': 'Choose language:',
        'role': 'Choose your role:',
        'client': 'Client 👤',
        'courier': 'Courier 🚗',
        'blocked': 'You are blocked or awaiting approval.',
        'send_photo': 'Send a photo of your ID for verification:',
        'wait_admin': 'Application sent. Waiting for approval.',
        'approved': 'Approved! Switch your status to Online to work.',
        'status_changed': 'Status changed to: ',
        'online': 'Online 🟢',
        'offline': 'Offline 🔴',
        'history': 'Earnings History 💰',
        'select_car': 'Select delivery type:',
        'standard': 'Standard (10 MDL/km)',
        'cargo': 'Cargo (20 MDL/km)',
        'enter_address_a': 'Enter address of point A:',
        'enter_phone_a': 'Enter phone number for point A:',
        'enter_tg_a': 'Enter TG account for point A (or /skip):',
        'enter_address_b': 'Enter address of point B:',
        'enter_phone_b': 'Enter phone number for point B:',
        'enter_tg_b': 'Enter TG account for point B (or /skip):',
        'enter_comment': 'Leave a comment for courier (or /skip):',
        'confirm_order': 'Estimated price: {price} MDL ({dist} km).\nConfirm order?',
        'yes': 'Yes ✅',
        'no': 'No ❌',
        'order_created': 'Order created! Looking for a courier...',
        'cancel': 'Cancel Order 🛑',
        'at_point_a': 'I am at point A 📍',
        'at_point_b': 'I am at point B 🏁',
        'client_notified_a': 'Client notified that you are at point A.',
        'client_notified_b': 'Client notified that you are at point B.',
        'courier_at_a': 'Courier arrived at point A!',
        'courier_at_b': 'Courier arrived at point B!',
        'afk_check': 'Are you here? Confirm you are online within 10 minutes!',
        'afk_btn': 'I am here 👋',
        'order_cancelled_afk': 'Order cancelled due to client inactivity. Courier can keep the package.',
        'no_orders': 'No pending orders.',
        'order_info': '📦 New Order [{type}]\nFrom: {addr_a}\nTo: {addr_b}\nPrice: {price} MDL'
    }
}

# --- DATABASE SETUP ---
DB_PATH = "delivery_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        tg_id INTEGER PRIMARY KEY, role TEXT, lang TEXT, approved INTEGER, status TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS whitelist (tg_id INTEGER PRIMARY KEY)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, courier_id INTEGER,
        type TEXT, addr_a TEXT, phone_a TEXT, tg_a TEXT, addr_b TEXT, phone_b TEXT, tg_b TEXT,
        comment TEXT, price REAL, dist REAL, status TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- FSM STATES ---
class Registration(StatesGroup):
    lang = State()
    role = State()
    photo = State()

class OrderCreation(StatesGroup):
    type = State()
    addr_a = State()
    phone_a = State()
    tg_a = State()
    addr_b = State()
    phone_b = State()
    tg_b = State()
    comment = State()
    confirm = State()

class ClientAFK(StatesGroup):
    waiting_reply = State()

# --- HELPERS ---
def get_lang(tg_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT lang FROM users WHERE tg_id = ?", (tg_id,))
    res = c.fetchone()
    conn.close()
    return res[0] if res and res[0] else 'ru'

def is_whitelisted(tg_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM whitelist WHERE tg_id = ?", (tg_id,))
    res = c.fetchone()
    conn.close()
    return res is not None

def get_yandex_maps_route_link(a, b):
    # Генерирует ссылку на построение автомобильного маршрута между адресами в Яндекс.Картах
    base = "https://yandex.ru/maps/?rtext="
    encoded_a = urllib.parse.quote(a)
    encoded_b = urllib.parse.quote(b)
    return f"{base}{encoded_a}~{encoded_b}&rtt=auto"

def mock_yandex_distance(a, b):
    # В продакшене тут должен быть запрос к Yandex Matrix API / Router API
    # Сейчас возвращаем случайное расстояние от 2 до 15 км
    return round(random.uniform(2.0, 15.0), 1)

# --- KEYBOARDS ---
def lang_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Русский 🇷🇺", callback_data="setlang_ru")],
        [InlineKeyboardButton(text="Română 🇷🇴", callback_data="setlang_ro")],
        [InlineKeyboardButton(text="English 🇬🇧", callback_data="setlang_en")]
    ])

def role_kb(lang):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=LOCALIZATION[lang]['client']), KeyboardButton(text=LOCALIZATION[lang]['courier'])]
    ], resize_keyboard=True)

def courier_menu(lang):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=LOCALIZATION[lang]['online']), KeyboardButton(text=LOCALIZATION[lang]['offline'])],
        [KeyboardButton(text=LOCALIZATION[lang]['history'])],
        [KeyboardButton(text="📋 Список заказов / List orders")]
    ], resize_keyboard=True)

# --- HANDLERS: START & REGISTRATION ---
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(LOCALIZATION['ru']['start'], reply_markup=lang_kb())

@router.callback_query(F.data.startswith("setlang_"))
async def set_language(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[1]
    tg_id = callback.from_user.id
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (tg_id, lang, approved, status) VALUES (?, ?, ?, ?)", 
              (tg_id, lang, 0, 'offline'))
    conn.commit()
    conn.close()
    
    await callback.answer()
    await callback.message.answer(LOCALIZATION[lang]['role'], reply_markup=role_kb(lang))
    await state.set_state(Registration.role)

@router.message(Registration.role)
async def process_role(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    role_text = message.text
    
    if role_text == LOCALIZATION[lang]['client']:
        role = 'client'
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET role = ?, approved = 1 WHERE tg_id = ?", (role, message.from_user.id))
        conn.commit()
        conn.close()
        await message.answer("Вы выбрали роль Клиента. Напишите /order для создания заказа.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📦 Создать заказ / Create Order")]], resize_keyboard=True))
        await state.clear()
        
    elif role_text == LOCALIZATION[lang]['courier']:
        role = 'courier'
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET role = ? WHERE tg_id = ?", (role, message.from_user.id))
        conn.commit()
        
        if is_whitelisted(message.from_user.id):
            c.execute("UPDATE users SET approved = 1 WHERE tg_id = ?", (message.from_user.id,))
            conn.commit()
            conn.close()
            await message.answer(LOCALIZATION[lang]['approved'], reply_markup=courier_menu(lang))
            await state.clear()
        else:
            conn.close()
            await message.answer(LOCALIZATION[lang]['send_photo'])
            await state.set_state(Registration.photo)

@router.message(Registration.photo, F.photo)
async def process_courier_photo(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    photo_id = message.photo[-1].file_id
    
    # Отправка админу на одобрение
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Одобрить ✅", callback_data=f"approve_{message.from_user.id}")],
        [InlineKeyboardButton(text="Отклонить ❌", callback_data=f"decline_{message.from_user.id}")]
    ])
    
    await bot.send_photo(
        chat_id=ADMIN_ID, 
        photo=photo_id, 
        caption=f"Заявка в курьеры!\nID: {message.from_user.id}\nUsername: @{message.from_user.username}",
        reply_markup=admin_kb
    )
    await message.answer(LOCALIZATION[lang]['wait_admin'])
    await state.clear()

# --- ADMIN ACTIONS ---
@router.callback_query(F.data.startswith("approve_"))
async def admin_approve(callback: CallbackQuery):
    courier_id = int(callback.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET approved = 1 WHERE tg_id = ?", (courier_id,))
    conn.commit()
    conn.close()
    
    await callback.message.edit_caption(caption=callback.message.caption + "\n\nОДОБРЕН ✅")
    lang = get_lang(courier_id)
    try:
        await bot.send_message(courier_id, LOCALIZATION[lang]['approved'], reply_markup=courier_menu(lang))
    except Exception:
        pass

@router.callback_query(F.data.startswith("decline_"))
async def admin_decline(callback: CallbackQuery):
    courier_id = int(callback.data.split("_")[1])
    await callback.message.edit_caption(caption=callback.message.caption + "\n\nОТКЛОНЕН ❌")

# --- COURIER LOGIC (ONLINE/OFFLINE/ORDERS) ---
@router.message(F.text.in_({"В Сети (Онлайн) 🟢", "Online 🟢"}))
async def courier_online(message: Message):
    lang = get_lang(message.from_user.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET status = 'online' WHERE tg_id = ? AND approved = 1", (message.from_user.id,))
    conn.commit()
    conn.close()
    await message.answer(f"{LOCALIZATION[lang]['status_changed']} {LOCALIZATION[lang]['online']}")

@router.message(F.text.in_({"Не в сети (Оффлайн) 🔴", "Offline 🔴"}))
async def courier_offline(message: Message):
    lang = get_lang(message.from_user.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET status = 'offline' WHERE tg_id = ?", (message.from_user.id,))
    conn.commit()
    conn.close()
    await message.answer(f"{LOCALIZATION[lang]['status_changed']} {LOCALIZATION[lang]['offline']}")

@router.message(F.text.in_({"История заработка 💰", "Istoric câștiguri 💰", "Earnings History 💰"}))
async def courier_history(message: Message):
    lang = get_lang(message.from_user.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), SUM(price) FROM orders WHERE courier_id = ? AND status = 'completed'", (message.from_user.id,))
    count, total = c.fetchone()
    conn.close()
    total = total if total else 0
    await message.answer(f"Выполнено заказов: {count}\nЗаработано всего: {total} MDL")

# --- CLIENT LOGIC: ORDER CREATION ---
@router.message(F.text.contains("Создать заказ") | F.text.contains("Create Order") | Command("order"))
async def start_order(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=LOCALIZATION[lang]['standard']), KeyboardButton(text=LOCALIZATION[lang]['cargo'])]
    ], resize_keyboard=True)
    await message.answer(LOCALIZATION[lang]['select_car'], reply_markup=kb)
    await state.set_state(OrderCreation.type)

@router.message(OrderCreation.type)
async def order_type(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    t = 'standard' if 'Стандарт' in message.text or 'Standard' in message.text else 'cargo'
    await state.update_data(type=t)
    await message.answer(LOCALIZATION[lang]['enter_address_a'])
    await state.set_state(OrderCreation.addr_a)

@router.message(OrderCreation.addr_a)
async def order_addr_a(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    await state.update_data(addr_a=message.text)
    await message.answer(LOCALIZATION[lang]['enter_phone_a'])
    await state.set_state(OrderCreation.phone_a)

@router.message(OrderCreation.phone_a)
async def order_phone_a(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    await state.update_data(phone_a=message.text)
    await message.answer(LOCALIZATION[lang]['enter_tg_a'])
    await state.set_state(OrderCreation.tg_a)

@router.message(OrderCreation.tg_a)
async def order_tg_a(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    await state.update_data(tg_a=message.text if message.text != "/skip" else "-")
    await message.answer(LOCALIZATION[lang]['enter_address_b'])
    await state.set_state(OrderCreation.addr_b)

@router.message(OrderCreation.addr_b)
async def order_addr_b(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    await state.update_data(addr_b=message.text)
    await message.answer(LOCALIZATION[lang]['enter_phone_b'])
    await state.set_state(OrderCreation.phone_b)

@router.message(OrderCreation.phone_b)
async def order_phone_b(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    await state.update_data(phone_b=message.text)
    await message.answer(LOCALIZATION[lang]['enter_tg_b'])
    await state.set_state(OrderCreation.tg_b)

@router.message(OrderCreation.tg_b)
async def order_tg_b(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    await state.update_data(tg_b=message.text if message.text != "/skip" else "-")
    await message.answer(LOCALIZATION[lang]['enter_comment'])
    await state.set_state(OrderCreation.comment)

@router.message(OrderCreation.comment)
async def order_comment(message: Message, state: FSMContext):
    lang = get_lang(message.from_user.id)
    await state.update_data(comment=message.text if message.text != "/skip" else "")
    
    data = await state.get_data()
    dist = mock_yandex_distance(data['addr_a'], data['addr_b'])
    per_km = 10 if data['type'] == 'standard' else 20
    price = dist * per_km
    
    await state.update_data(dist=dist, price=price)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=LOCALIZATION[lang]['yes'], callback_data="confirm_order_yes"),
         InlineKeyboardButton(text=LOCALIZATION[lang]['no'], callback_data="confirm_order_no")]
    ])
    await message.answer(LOCALIZATION[lang]['confirm_order'].format(price=price, dist=dist), reply_markup=kb)
    await state.set_state(OrderCreation.confirm)

# --- COURIER DISPATCH & INTERACTION ---
@router.callback_query(F.data == "confirm_order_yes", OrderCreation.confirm)
async def process_confirm_order(callback: CallbackQuery, state: FSMContext):
    lang = get_lang(callback.from_user.id)
    data = await state.get_data()
    await state.clear()
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT INTO orders 
        (client_id, type, addr_a, phone_a, tg_a, addr_b, phone_b, tg_b, comment, price, dist, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')''',
        (callback.from_user.id, data['type'], data['addr_a'], data['phone_a'], data['tg_a'],
         data['addr_b'], data['phone_b'], data['tg_b'], data['comment'], data['price'], data['dist']))
    order_id = c.lastrowid
    conn.commit()
    
    # Ищем активных курьеров онлайн
    c.execute("SELECT tg_id FROM users WHERE role = 'courier' AND status = 'online' AND approved = 1")
    couriers = c.fetchall()
    conn.close()
    
    await callback.message.edit_text(LOCALIZATION[lang]['order_created'])
    
    # Вещание заказа всем свободным курьерам
    for (cour_id,) in couriers:
        c_lang = get_lang(cour_id)
        route_url = get_yandex_maps_route_link(data['addr_a'], data['addr_b'])
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Принять / Accept ✅", callback_data=f"take_{order_id}")],
            [InlineKeyboardButton(text="Отклонить / Decline ❌", callback_data=f"reject_{order_id}")]
        ])
        
        info = (
            f"⚡ {LOCALIZATION[c_lang]['order_info'].format(type=data['type'], addr_a=data['addr_a'], phone_a=data['phone_a'], addr_b=data['addr_b'], phone_b=data['phone_b'], price=data['price'], comment=data['comment'])}\n"
            f"🗺 [Маршрут Яндекс.Карты]({route_url})"
        )
        try:
            await bot.send_message(cour_id, info, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass

@router.callback_query(F.data.startswith("take_"))
async def courier_take_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    courier_id = callback.from_user.id
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT status, client_id, addr_a, addr_b FROM orders WHERE id = ?", (order_id,))
    order = c.fetchone()
    
    if not order or order[0] != 'pending':
        await callback.answer("Заказ уже взят или не актуален.", show_alert=True)
        conn.close()
        return
        
    c.execute("UPDATE orders SET courier_id = ?, status = 'accepted' WHERE id = ?", (courier_id, order_id))
    conn.commit()
    conn.close()
    
    client_id = order[1]
    
    # Кнопки для курьера по ходу выполнения
    kb_courier = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Я на точке А 📍", callback_data=f"ata_{order_id}")],
        [InlineKeyboardButton(text="Отменить заказ ❌", callback_data=f"ccancel_{order_id}")]
    ])
    
    await callback.message.edit_text(callback.message.text + "\n\nВЫ ПРИНЯЛИ ЗАКАЗ!", reply_markup=kb_courier)
    
    # Уведомление клиенту
    cl_lang = get_lang(client_id)
    kb_client = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=LOCALIZATION[cl_lang]['cancel'], callback_data=f"clcancel_{order_id}")]
    ])
    await bot.send_message(client_id, "Курьер принял ваш заказ и направляется в точку А.", reply_markup=kb_client)
    
    # Запуск фонового таймера проверки активности клиента (каждые 10 мин)
    asyncio.create_task(client_afk_monitor(client_id, order_id))

# --- STEPS FOR COURIER ON DELIVERY ---
@router.callback_query(F.data.startswith("ata_"))
async def courier_at_a(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE orders SET status = 'at_a' WHERE id = ?", (order_id,))
    c.execute("SELECT client_id FROM orders WHERE id = ?", (order_id,))
    client_id = c.fetchone()[0]
    conn.commit()
    conn.close()
    
    lang = get_lang(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Я на месте (Точка Б) 🏁", callback_data=f"atb_{order_id}")]
    ])
    # После прибытия на точку А отмена невозможна ни для кого (кнопку отмены убираем)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer(LOCALIZATION[lang]['client_notified_a'])
    
    cl_lang = get_lang(client_id)
    await bot.send_message(client_id, LOCALIZATION[cl_lang]['courier_at_a'])

@router.callback_query(F.data.startswith("atb_"))
async def courier_at_b(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE orders SET status = 'completed' WHERE id = ?", (order_id,))
    c.execute("SELECT client_id FROM orders WHERE id = ?", (order_id,))
    client_id = c.fetchone()[0]
    conn.commit()
    conn.close()
    
    lang = get_lang(callback.from_user.id)
    await callback.message.edit_text(callback.message.text + "\n\nЗАКАЗ ВЫПОЛНЕН! Оплата наличными.")
    
    cl_lang = get_lang(client_id)
    await bot.send_message(client_id, LOCALIZATION[cl_lang]['courier_at_b'] + "\nСпасибо за заказ! Оплата наличными.")

# --- CANCELLATION LOGIC (ONLY BEFORE POINT A) ---
@router.callback_query(F.data.startswith("ccancel_"))
async def courier_cancel(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT status, client_id FROM orders WHERE id = ?", (order_id,))
    status, client_id = c.fetchone()
    
    if status == 'accepted':
        c.execute("UPDATE orders SET status = 'pending', courier_id = NULL WHERE id = ?", (order_id,))
        conn.commit()
        await callback.message.edit_text("Вы отменили заказ. Он вернулся в общий пул.")
        await bot.send_message(client_id, "Курьер отказался от заказа. Ищем нового курьера...")
    else:
        await callback.answer("Вы уже на точке А, отмена невозможна!", show_alert=True)
    conn.close()

@router.callback_query(F.data.startswith("clcancel_"))
async def client_cancel(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT status, courier_id FROM orders WHERE id = ?", (order_id,))
    status, courier_id = c.fetchone()
    
    if status in ['pending', 'accepted']:
        c.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
        conn.commit()
        await callback.message.edit_text("Вы отменили заказ.")
        if courier_id:
            await bot.send_message(courier_id, "Клиент отменил заказ.")
    else:
        await callback.answer("Курьер уже прибыл или заказ выполнен. Отмена невозможна!", show_alert=True)
    conn.close()

# --- COURIER LIST OF HANGING ORDERS ---
@router.message(F.text.contains("Список заказов") | F.text.contains("List orders"))
async def list_hanging_orders(message: Message):
    lang = get_lang(message.from_user.id)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, type, addr_a, addr_b, price FROM orders WHERE status = 'pending'")
    orders = c.fetchall()
    conn.close()
    
    if not orders:
        await message.answer(LOCALIZATION[lang]['no_orders'])
        return
        
    for o in orders:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Принять / Accept ✅", callback_data=f"take_{o[0]}")]
        ])
        await message.answer(f"📦 Заказ #{o[0]} [{o[1]}]\nИз: {o[2]}\nВ: {o[3]}\nЦена: {o[4]} MDL", reply_markup=kb)

# --- INACTIVITY/AFK TIMER LOGIC ---
afk_responses = {}

@router.callback_query(F.data.startswith("afk_ok_"))
async def process_afk_ok(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    afk_responses[order_id] = True
    await callback.message.edit_text("Спасибо! Вы онлайн.")

async def client_afk_monitor(client_id, order_id):
    cl_lang = get_lang(client_id)
    while True:
        await asyncio.sleep(600)  # Каждые 10 минут (600 секунд)
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT status, courier_id FROM orders WHERE id = ?", (order_id,))
        res = c.fetchone()
        conn.close()
        
        if not res or res[0] in ['completed', 'cancelled']:
            break  # Заказ завершен, мониторинг выключается
            
        courier_id = res[1]
        afk_responses[order_id] = False
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=LOCALIZATION[cl_lang]['afk_btn'], callback_data=f"afk_ok_{order_id}")]
        ])
        
        try:
            afk_msg = await bot.send_message(client_id, LOCALIZATION[cl_lang]['afk_check'], reply_markup=kb)
        except Exception:
            pass
            
        await asyncio.sleep(600)  # Даем еще 10 минут на нажатие кнопки
        
        if not afk_responses.get(order_id, False):
            # Клиент не ответил -> Отмена
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("UPDATE orders SET status = 'cancelled_afk' WHERE id = ?", (order_id,))
            conn.commit()
            conn.close()
            
            try:
                await bot.delete_message(client_id, afk_msg.message_id)
                await bot.send_message(client_id, "Заказ отменен из-за неактивности.")
            except Exception:
                pass
                
            try:
                c_lang = get_lang(courier_id)
                await bot.send_message(courier_id, LOCALIZATION[c_lang]['order_cancelled_afk'])
            except Exception:
                pass
            break

# --- ADMIN PANEL FUNCTIONS ---
@router.message(Command("admin_reset"))
async def admin_reset_orders(message: Message):
    if message.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE orders SET status = 'cancelled' WHERE status = 'pending'")
    conn.commit()
    conn.close()
    await message.answer("Все висящие (pending) заказы сброшены.")

@router.message(Command("admin_couriers"))
async def admin_list_couriers(message: Message):
    if message.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT tg_id, status FROM users WHERE role = 'courier' AND approved = 1")
    list_c = c.fetchall()
    conn.close()
    
    text = "Активные курьеры:\n"
    for cour in list_c:
        text += f"ID: {cour[0]} | Статус: {cour[1]}\n"
    await message.answer(text if list_c else "Нет зарегистрированных курьеров.")

@router.message(Command("add_whitelist"))
async def admin_add_whitelist(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        target_id = int(message.text.split()[1])
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO whitelist (tg_id) VALUES (?)", (target_id,))
        conn.commit()
        conn.close()
        await message.answer(f"Пользователь {target_id} добавлен в белый список (авто-одобрение).")
    except Exception:
        await message.answer("Используйте: /add_whitelist ТГ_ИД")

# --- RENDER WEB SERVER (KEEP-ALIVE) ---
async def handle_root(request):
    return web.Response(text="Bot is running completely fine.")

async def main():
    dp.include_router(router)
    
    # Запуск веб-сервера параллельно с ботом
    app = web.Application()
    app.router.add_get('/', handle_root)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    asyncio.create_task(site.start())
    
    # Запуск лонг-поллинга бота
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
