import os
import asyncio
import logging
from datetime import datetime
import asyncpg
import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

# --- ИНИЦИАЛИЗАЦИЯ И ЛОГИРОВАНИЕ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

db_pool = None
active_afk_tasks = {}

# --- СОСТОЯНИЯ FSM ---
class UserReg(StatesGroup):
    lang = State()
    role = State()
    photo = State()

class CreateOrder(StatesGroup):
    cargo_type = State()
    addr_a = State()
    addr_b = State()
    phone_sender = State()
    phone_receiver = State()
    comment = State()
    confirm = State()

# --- ЛОКАЛИЗАЦИЯ (RU, RO, EN) ---
TEXTS = {
    'ru': {
        'start': "🌍 Выберите язык / Alegeți limba / Choose language:",
        'select_role': "👤 Выберите вашу роль в системе:",
        'client': "👨‍💼 Клиент",
        'courier': "🛵 Курьер",
        'send_photo': "📸 Отправьте ваше фото (селфи или паспорт) для верификации администратором:",
        'wait_admin': "⏳ Ваша заявка отправлена. Ожидайте одобрения администратором.",
        'approved': "🎉 Вы успешно одобрены! Наберите /online для начала работы.",
        'not_approved': "⚠️ Вы еще не одобрены админом или заблокированы.",
        'client_menu': "🏬 Вы в меню клиента.\n/order — Создать заказ\n/cancel — Отменить мой текущий заказ",
        'courier_menu': "🛵 Вы в меню курьера.\n/online — Встать на смену\n/offline — Уйти со смены\n/orders — Список доступных заказов",
        'cargo_type': "📦 Выберите тип доставки:",
        'std': "📦 Стандарт (10 лей/км)",
        'frg': "🚚 Грузовой (20 лей/км )",
        'addr_a': "📍 Отправьте геопозицию ТОЧКИ А (Откуда вас забрать) с помощью кнопки ниже 👇:",
        'addr_b': "🏁 Отправьте геопозицию НАЗНАЧЕНИЯ Б (Куда везти) с помощью кнопки ниже 👇:",
        'phone_sender': "📱 Введите номер телефона ОТПРАВИТЕЛЯ:",
        'phone_receiver': "📱 Введите номер телефона ПОЛУЧАТЕЛЯ:",
        'comment': "💬 Введите комментарий для курьера или нажмите /skip для пропуска:",
        'confirm_title': "📋 Подтверждение заказа:\n\n🔹 Тип: {type}\n🔹 Откуда: {a}\n🔹 Куда: {b}\n🔹 Тел. Отправителя: {p_send}\n🔹 Тел. Получателя: {p_recv}\n🔹 Комментарий: {comm}\n💵 Итоговая стоимость: {price} MDL\n\nВсё верно?",
        'yes': "✅ Да, заказываю",
        'no': "❌ Отмена",
        'order_placed': "🚀 Заказ опубликован! Ищем ближайших курьеров...",
        'no_orders': "📭 На данный момент нет свободных заказов.",
        'take_btn': "✅ Принять заказ за {price} MDL",
        'cancel_btn': "❌ Отказаться",
        'order_taken': "🤝 Вы приняли заказ! Двигайтесь на точку А.\nℹ️ Инфо:\n📞 Отправитель: {p_send}\n📞 Получатель: {p_recv}\n💬 Комм: {comm}\n🗺 Маршрут OSRM: {url}",
        'at_a_btn': "📍 Я на точке А",
        'at_b_btn': "🏁 Я на месте (Точка Б)",
        'done_btn': "💵 Завершить",
        'client_notif_courier_at_a': "🔔 Курьер прибыл на точку А! Пожалуйста, выходите к курьеру.",
        'client_notif_courier_at_b': "🔔 Курьер на месте назначения (Точка Б)! Заберите посылку.",
        'afk_question': "📢 Вы тут? Подтвердите, что вы онлайн, нажатием на кнопку ниже. У вас 10 минут!",
        'afk_btn': "🙋‍♂️ Я тут!",
        'afk_cancelled': "🔴 Заказ отменен из-за неактивности клиента. Курьер, вы можете оставить посылку себе!",
        'cant_cancel': "⚠️ Нельзя отменить заказ после того, как курьер прибыл на точку А.",
        'order_cancelled': "🗑 Заказ успешно отменен.",
        'invalid_geo': "⚠️ Пожалуйста, используйте только кнопку «📍 Отправить геопозицию» ниже 👇\nРучной ввод адреса текстом отключен."
    },
    'ro': {
        'start': "🌍 Alegeți limba / Выберите язык / Choose language:",
        'select_role': "👤 Alegeți rolul dvs. în sistem:",
        'client': "👨‍💼 Client",
        'courier': "🛵 Curier",
        'send_photo': "📸 Trimiteți o fotografie (selfie sau pașaport) pentru verificare de către administrator:",
        'wait_admin': "⏳ Cererea dvs. a fost trimisă. Așteptați aprobarea administratorului.",
        'approved': "🎉 Ați fost aprobat cu succes! Tastați /online pentru a începe lucrul.",
        'not_approved': "⚠️ Nu sunteți încă aprobat de admin sau sunteți blocat.",
        'client_menu': "🏬 Sunteți în meniul clientului.\n/order — Crează comandă\n/cancel — Anulează comanda curentă",
        'courier_menu': "🛵 Sunteți în meniul curierului.\n/online — Intră pe tură\n/offline — Ieși de pe tură\n/orders — Lista comenzilor disponibile",
        'cargo_type': "📦 Selectați tipul de livrare:",
        'std': "📦 Standard (10 MDL/km )",
        'frg': "🚚 Marfă (20 MDL/km )",
        'addr_a': "📍 Trimiteți locația PUNCTULAI A (De unde preluăm) folosind butonul de mai jos 👇:",
        'addr_b': "🏁 Trimiteți locația DESTINAȚIEI B (Unde livrăm) folosind butonul de mai jos 👇:",
        'phone_sender': "📱 Introduceți numărul de telefon al EXPEDITORULUI:",
        'phone_receiver': "📱 Introduceți numărul de telefon al RECEPTORULUI:",
        'comment': "💬 Introduceți un comentariu pentru curier sau tastați /skip pentru a omite:",
        'confirm_title': "📋 Confirmare comandă:\n\n🔹 Tip: {type}\n🔹 De la: {a}\n🔹 Până la: {b}\n🔹 Tel. Expeditor: {p_send}\n🔹 Tel. Receptor: {p_recv}\n🔹 Comentariu: {comm}\n💵 Preț total: {price} MDL\n\nEste corect?",
        'yes': "✅ Da, comand",
        'no': "❌ Anulare",
        'order_placed': "🚀 Comanda a fost publicată! Căutăm curieri...",
        'no_orders': "📭 În prezent nu există comenzi disponibile.",
        'take_btn': "✅ Acceptă comanda pentru {price} MDL",
        'cancel_btn': "❌ Refuză",
        'order_taken': "🤝 Ați acceptat comanda! Deplasați-vă la punctul A.\nℹ️ Info:\n📞 Expeditor: {p_send}\n📞 Receptor: {p_recv}\n💬 Comm: {comm}\n🗺 Rută OSRM: {url}",
        'at_a_btn': "📍 Sunt la punctul A",
        'at_b_btn': "🏁 Sunt la destinație (Punctul B)",
        'done_btn': "💵 Finalizează",
        'client_notif_courier_at_a': "🔔 Curierul a sosit la punctul A! Vă rugăm să ieșiți.",
        'client_notif_courier_at_b': "🔔 Curierul este la destinație (Punctul B)! Ridicați coletul.",
        'afk_question': "📢 Sunteți aici? Confirmați că sunteți online apăsând butonul de mai jos. Aveți 10 minute!",
        'afk_btn': "🙋‍♂️ Sunt aici!",
        'afk_cancelled': "🔴 Comanda a fost anulată din cauza inactivității clientului. Curierule, poți păstra coletul!",
        'cant_cancel': "⚠️ Comanda nu poate fi anulată după ce curierul a sosit la punctul A.",
        'order_cancelled': "🗑 Comanda a fost anulată cu succes.",
        'invalid_geo': "⚠️ Vă rugăm să folosiți butonul „📍 Trimiteți locația” de mai jos 👇\nIntroducerea manuală a textului este dezactivată."
    },
    'en': {
        'start': "🌍 Choose language / Выберите язык / Alegeți limba:",
        'select_role': "👤 Select your role in the system:",
        'client': "👨‍💼 Client",
        'courier': "🛵 Courier",
        'send_photo': "📸 Please send your photo (selfie or passport) for admin verification:",
        'wait_admin': "⏳ Your application has been sent. Waiting for admin approval.",
        'approved': "🎉 You have been successfully approved! Type /online to start working.",
        'not_approved': "⚠️ You are not approved by the admin yet or are blocked.",
        'client_menu': "🏬 You are in the client menu.\n/order — Create an order\n/cancel — Cancel my current order",
        'courier_menu': "🛵 You are in the courier menu.\n/online — Go online\n/offline — Go offline\n/orders — View available orders",
        'cargo_type': "📦 Select delivery type:",
        'std': "📦 Standard (10 MDL/km)",
        'frg': "🚚 Freight (20 MDL/km )",
        'addr_a': "📍 Send the location of POINT A (Pickup) using the button below 👇:",
        'addr_b': "🏁 Send the location of DESTINATION B (Dropoff) using the button below 👇:",
        'phone_sender': "📱 Enter SENDER'S phone number:",
        'phone_receiver': "📱 Enter RECEIVER'S phone number:",
        'comment': "💬 Enter a comment for the courier or type /skip to pass:",
        'confirm_title': "📋 Order Confirmation:\n\n🔹 Type: {type}\n🔹 From: {a}\n🔹 To: {b}\n🔹 Sender Phone: {p_send}\n🔹 Receiver Phone: {p_recv}\n🔹 Comment: {comm}\n💵 Total price: {price} MDL\n\nIs everything correct?",
        'yes': "✅ Yes, place order",
        'no': "❌ Cancel",
        'order_placed': "🚀 Order placed! Searching for couriers...",
        'no_orders': "📭 No available orders at the moment.",
        'take_btn': "✅ Accept order for {price} MDL",
        'cancel_btn': "❌ Decline",
        'order_taken': "🤝 You accepted the order! Proceed to point A.\nℹ️ Info:\n📞 Sender: {p_send}\n📞 Receiver: {p_recv}\n💬 Comment: {comm}\n🗺 OSRM Route: {url}",
        'at_a_btn': "📍 I am at point A",
        'at_b_btn': "🏁 I am at destination (Point B)",
        'done_btn': "💵 Complete",
        'client_notif_courier_at_a': "🔔 The courier has arrived at point A! Please go out.",
        'client_notif_courier_at_b': "🔔 The courier is at the destination (Point B)! Collect your package.",
        'afk_question': "📢 Are you here? Confirm you are online by clicking the button below. You have 10 minutes!",
        'afk_btn': "🙋‍♂️ I am here!",
        'afk_cancelled': "🔴 Order cancelled due to client inactivity. Courier, you may keep the parcel!",
        'cant_cancel': "⚠️ Cannot cancel order after the courier has arrived at point A.",
        'order_cancelled': "🗑 Order successfully cancelled.",
        'invalid_geo': "⚠️ Please use the '📍 Send location' button below 👇\nManual text entry is disabled."
    }
}

# --- ПОДКЛЮЧЕНИЕ И СОЗДАНИЕ ТАБЛИЦ БД ---
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                role TEXT,
                lang TEXT DEFAULT 'ru',
                is_approved BOOLEAN DEFAULT FALSE,
                is_online BOOLEAN DEFAULT FALSE,
                username TEXT
            );
            CREATE TABLE IF NOT EXISTS whitelist (
                user_id BIGINT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                client_id BIGINT,
                cargo_type TEXT,
                addr_a TEXT,
                addr_b TEXT,
                lat_a NUMERIC, lon_a NUMERIC,
                lat_b NUMERIC, lon_b NUMERIC,
                phone_sender TEXT,
                phone_receiver TEXT,
                comment TEXT,
                price NUMERIC,
                status TEXT DEFAULT 'pending',
                courier_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        try:
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS phone_sender TEXT;")
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS phone_receiver TEXT;")
        except Exception:
            pass

async def get_lang(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT lang FROM users WHERE user_id = $1", user_id)
        return row['lang'] if row else 'ru'

# --- РАСЧЕТ МАРШРУТА OSRM ---
async def get_osrm_data(lat1, lon1, lat2, lon2):
    map_url = f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route={lat1}%2C{lon1}%3B{lat2}%2C{lon2}"
    osrm_api = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    dist_km = 5.0
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(osrm_api, timeout=10) as resp:
                data = await resp.json()
                if data.get("routes"):
                    dist_km = data["routes"][0]["distance"] / 1000
    except Exception as e:
        logging.error(f"OSRM Routing error: {e}")
    return round(dist_km, 2), map_url

# --- КОМАНДА СТАРТ И ВЫБОР ЯЗЫКА ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="setlang_ru")],
        [InlineKeyboardButton(text="🇲🇩 Română", callback_data="setlang_ro")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="setlang_en")]
    ])
    await message.answer(TEXTS['ru']['start'], reply_markup=kb)

@router.callback_query(F.data.startswith("setlang_"))
async def process_lang(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[1]
    await state.update_data(lang=lang)
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, lang, username) VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE SET lang = $2, username = $3
        """, callback.from_user.id, lang, callback.from_user.username)
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]['client'], callback_data="setrole_client")],
        [InlineKeyboardButton(text=TEXTS[lang]['courier'], callback_data="setrole_courier")]
    ])
    await callback.message.edit_text(TEXTS[lang]['select_role'], reply_markup=kb)

@router.callback_query(F.data.startswith("setrole_"))
async def process_role(callback: CallbackQuery, state: FSMContext):
    role = callback.data.split("_")[1]
    data = await state.get_data()
    lang = data.get('lang', 'ru')
    
    async with db_pool.acquire() as conn:
        whitelisted = await conn.fetchrow("SELECT user_id FROM whitelist WHERE user_id = $1", callback.from_user.id)
        is_approved = True if whitelisted else False
        await conn.execute("UPDATE users SET role = $1, is_approved = $2 WHERE user_id = $3", role, is_approved, callback.from_user.id)
    
    if role == "courier":
        if is_approved:
            await callback.message.edit_text(TEXTS[lang]['approved'])
            await callback.message.answer(TEXTS[lang]['courier_menu'])
        else:
            await callback.message.edit_text(TEXTS[lang]['send_photo'])
            await state.set_state(UserReg.photo)
    else:
        await callback.message.edit_text(TEXTS[lang]['client_menu'])
        await state.clear()

# --- ВЕРИФИКАЦИЯ КУРЬЕРА ---
@router.message(UserReg.photo, F.photo)
async def courier_photo_reg(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    photo_id = message.photo[-1].file_id
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить курьера", callback_data=f"adm_appr_{message.from_user.id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_decl_{message.from_user.id}")]
    ])
    
    await bot.send_photo(
        ADMIN_ID, 
        photo_id, 
        caption=f"Новая заявка в курьеры!\nID: `{message.from_user.id}`\nUsername: @{message.from_user.username}", 
        reply_markup=kb
    )
    await message.answer(TEXTS[lang]['wait_admin'])
    await state.clear()

@router.callback_query(F.data.startswith("adm_"))
async def process_admin_decision(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("У вас нет прав доступа!", show_alert=True)
        return
        
    parts = callback.data.split("_")
    action = parts[1]
    target_user_id = int(parts[2])
    
    async with db_pool.acquire() as conn:
        if action == "appr":
            await conn.execute("UPDATE users SET is_approved = TRUE WHERE user_id = $1", target_user_id)
            await callback.message.edit_caption(caption=f"{callback.message.caption}\n\n✅ Одобрен администратором.")
            try:
                t_lang = await get_lang(target_user_id)
                await bot.send_message(target_user_id, TEXTS[t_lang]['approved'])
                await bot.send_message(target_user_id, TEXTS[t_lang]['courier_menu'])
            except Exception: pass
        elif action == "decl":
            await conn.execute("UPDATE users SET is_approved = FALSE WHERE user_id = $1", target_user_id)
            await callback.message.edit_caption(caption=f"{callback.message.caption}\n\n❌ Отклонён.")
            try:
                await bot.send_message(target_user_id, "⚠️ Ваша заявка на верификацию курьера была отклонена администратором.")
            except Exception: pass
    await callback.answer()

# --- СМЕНЫ КУРЬЕРОВ ---
@router.message(Command("online"))
async def go_online(message: Message):
    lang = await get_lang(message.from_user.id)
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT role, is_approved FROM users WHERE user_id = $1", message.from_user.id)
        if user and user['role'] == 'courier' and user['is_approved']:
            await conn.execute("UPDATE users SET is_online = TRUE WHERE user_id = $1", message.from_user.id)
            await message.answer("🟢 Вы вышли на онлайн-смену! Ожидайте новые заказы.")
        else:
            await message.answer(TEXTS[lang]['not_approved'])

@router.message(Command("offline"))
async def go_offline(message: Message):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_online = FALSE WHERE user_id = $1 AND role = 'courier'", message.from_user.id)
    await message.answer("🔴 Вы ушли со смены. Новые заказы приходить не будут.")

# --- ОФОРМЛЕНИЕ ЗАКАЗА КЛИЕНТОМ ---
@router.message(Command("order"))
async def cmd_order(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]['std'], callback_data="order_type_standard")],
        [InlineKeyboardButton(text=TEXTS[lang]['frg'], callback_data="order_type_freight")]
    ])
    await message.answer(TEXTS[lang]['cargo_type'], reply_markup=kb)
    await state.set_state(CreateOrder.cargo_type)

@router.callback_query(CreateOrder.cargo_type, F.data.startswith("order_type_"))
async def order_type_chosen(callback: CallbackQuery, state: FSMContext):
    ctype = callback.data.split("_")[2]
    await state.update_data(cargo_type=ctype)
    lang = await get_lang(callback.from_user.id)
    
    geo_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
    await callback.message.answer(TEXTS[lang]['addr_a'], reply_markup=geo_kb)
    await state.set_state(CreateOrder.addr_a)

@router.message(CreateOrder.addr_a, F.location)
async def order_addr_a(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    lat, lon = message.location.latitude, message.location.longitude
    addr_text = f"{lat}, {lon}"
        
    await state.update_data(addr_a=addr_text, lat_a=lat, lon_a=lon)
    
    geo_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer(TEXTS[lang]['addr_b'], reply_markup=geo_kb)
    await state.set_state(CreateOrder.addr_b)

@router.message(CreateOrder.addr_b, F.location)
async def order_addr_b(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    lat, lon = message.location.latitude, message.location.longitude
    addr_text = f"{lat}, {lon}"
        
    await state.update_data(addr_b=addr_text, lat_b=lat, lon_b=lon)
    await message.answer(TEXTS[lang]['phone_sender'], reply_markup=ReplyKeyboardRemove())
    await state.set_state(CreateOrder.phone_sender)

@router.message(CreateOrder.addr_a)
@router.message(CreateOrder.addr_b)
async def order_addr_invalid(message: Message):
    lang = await get_lang(message.from_user.id)
    geo_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer(TEXTS[lang]['invalid_geo'], reply_markup=geo_kb)

@router.message(CreateOrder.phone_sender)
async def order_phone_sender(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(phone_sender=message.text)
    await message.answer(TEXTS[lang]['phone_receiver'])
    await state.set_state(CreateOrder.phone_receiver)

@router.message(CreateOrder.phone_receiver)
async def order_phone_receiver(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(phone_receiver=message.text)
    await message.answer(TEXTS[lang]['comment'])
    await state.set_state(CreateOrder.comment)

@router.message(CreateOrder.comment)
async def order_comment(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    comm = message.text if message.text != "/skip" else "Нет комментария"
    await state.update_data(comment=comm)
    
    data = await state.get_data()
    dist, _ = await get_osrm_data(data['lat_a'], data['lon_a'], data['lat_b'], data['lon_b'])
    
    rate = 10 if data['cargo_type'] == 'standard' else 20
    # ИСПРАВЛЕНО: Убрано +40.0
    price = round(dist * rate, 2)
    if price < 10: price = 10.0
    
    await state.update_data(price=price)
    
    txt = TEXTS[lang]['confirm_title'].format(
        type=data['cargo_type'], a=data['addr_a'], b=data['addr_b'], 
        p_send=data['phone_sender'], p_recv=data['phone_receiver'], comm=comm, price=price
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]['yes'], callback_data="confirm_order_yes")],
        [InlineKeyboardButton(text=TEXTS[lang]['no'], callback_data="confirm_order_no")]
    ])
    
    await message.answer(txt, reply_markup=kb)
    await state.set_state(CreateOrder.confirm)

@router.callback_query(CreateOrder.confirm, F.data == "confirm_order_yes")
async def order_confirmed(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    data = await state.get_data()
    
    async with db_pool.acquire() as conn:
        order_id = await conn.fetchval("""
            INSERT INTO orders (client_id, cargo_type, addr_a, addr_b, lat_a, lon_a, lat_b, lon_b, phone_sender, phone_receiver, comment, price, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'pending') RETURNING id
        """, callback.from_user.id, data['cargo_type'], data['addr_a'], data['addr_b'], data['lat_a'], data['lon_a'], data['lat_b'], data['lon_b'], data['phone_sender'], data['phone_receiver'], data['comment'], data['price'])
        
        couriers = await conn.fetch("SELECT user_id, lang FROM users WHERE role = 'courier' AND is_online = TRUE")
        
    await callback.message.edit_text(TEXTS[lang]['order_placed'])
    await state.clear()
    
    dist, map_url = await get_osrm_data(data['lat_a'], data['lon_a'], data['lat_b'], data['lon_b'])
    for c in couriers:
        c_lang = c['lang']
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=TEXTS[c_lang]['take_btn'].format(price=data['price']), callback_data=f"take_{order_id}")]
        ])
        # ИСПРАВЛЕНО: Убрано (Наличные)
        c_txt = (f"📦 *Новый заказ #{order_id} ({data['cargo_type']})*\n"
                 f"📍 А: {data['addr_a']}\n"
                 f"🏁 Б: {data['addr_b']}\n"
                 f"📱 Отправитель: {data['phone_sender']}\n"
                 f"📱 Получатель: {data['phone_receiver']}\n"
                 f"💬 Комм: {data['comment']}\n"
                 f"💵 Курьер получит: {data['price']} MDL\n"
                 f"🗺 Карта: [Открыть маршрут OSRM]({map_url})")
        try:
            await bot.send_message(c['user_id'], c_txt, reply_markup=kb, parse_mode="Markdown")
            await asyncio.sleep(0.05)
        except Exception:
            pass

@router.callback_query(CreateOrder.confirm, F.data == "confirm_order_no")
async def order_cancelled_fsm(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(TEXTS[lang]['order_cancelled'])
    await state.clear()

# --- ЛОГИКА ВЫПОЛНЕНИЯ ЗАКАЗА КУРЬЕРОМ ---
@router.message(Command("orders"))
async def list_orders(message: Message):
    lang = await get_lang(message.from_user.id)
    async with db_pool.acquire() as conn:
        orders = await conn.fetch("SELECT * FROM orders WHERE status = 'pending' ORDER BY id DESC")
        
    if not orders:
        await message.answer(TEXTS[lang]['no_orders'])
        return
        
    for o in orders:
        _, map_url = await get_osrm_data(o['lat_a'], o['lon_a'], o['lat_b'], o['lon_b'])
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=TEXTS[lang]['take_btn'].format(price=o['price']), callback_data=f"take_{o['id']}")]
        ])
        txt = (f"📦 *Заказ #{o['id']} ({o['cargo_type']})*\n"
               f"📍 А: {o['addr_a']}\n"
               f"🏁 Б: {o['addr_b']}\n"
               f"📱 Отправитель: {o['phone_sender']}\n"
               f"📱 Получатель: {o['phone_receiver']}\n"
               f"💬 Комм: {o['comment']}\n"
               f"💵 Сумма: {o['price']} MDL\n"
               f"🗺 OSRM: [Ссылка]({map_url})")
        await message.answer(txt, reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data.startswith("take_"))
async def take_order_callback(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    order_id = int(callback.data.split("_")[1])
    
    async with db_pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
        if not order or order['status'] != 'pending':
            await callback.answer("⚠️ Этот заказ уже принял другой курьер!", show_alert=True)
            return
            
        await conn.execute("UPDATE orders SET status = 'accepted', courier_id = $1 WHERE id = $2", callback.from_user.id, order_id)
        client_tg = await conn.fetchrow("SELECT username FROM users WHERE user_id = $1", order['client_id'])
            
    _, map_url = await get_osrm_data(order['lat_a'], order['lon_a'], order['lat_b'], order['lon_b'])
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]['at_a_btn'], callback_data=f"sta_ata_{order_id}")],
        [InlineKeyboardButton(text=TEXTS[lang]['cancel_btn'], callback_data=f"sta_curr_cncl_{order_id}")]
    ])
    
    txt = TEXTS[lang]['order_taken'].format(
        p_send=order['phone_sender'], p_recv=order['phone_receiver'], comm=order['comment'], url=map_url
    )
    await callback.message.edit_text(txt, reply_markup=kb, disable_web_page_preview=True)
    
    c_user = callback.from_user.username or "Курьер"
    await bot.send_message(order['client_id'], f"🤝 Ваш заказ #{order_id} принят курьером @{c_user}. Он направляется к вам на точку А.")

# --- ТАЙМЕР АФК КЛИЕНТА (10 МИНУТ) ---
async def client_afk_worker(client_id, order_id, courier_id):
    try:
        await asyncio.sleep(600)
        c_lang = await get_lang(client_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=TEXTS[c_lang]['afk_btn'], callback_data=f"afk_ok_{order_id}")]
        ])
        
        async with db_pool.acquire() as conn:
            current_status = await conn.fetchval("SELECT status FROM orders WHERE id = $1", order_id)
        if current_status != 'at_a': return
        
        msg = await bot.send_message(client_id, TEXTS[c_lang]['afk_question'], reply_markup=kb)
        await asyncio.sleep(600)
        
        async with db_pool.acquire() as conn:
            order = await conn.fetchrow("SELECT status FROM orders WHERE id = $1", order_id)
            if order and order['status'] == 'at_a':
                await conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = $1", order_id)
                await bot.send_message(client_id, "🔴 Заказ отменен из-за вашей неактивности.")
                cr_lang = await get_lang(courier_id)
                await bot.send_message(courier_id, TEXTS[cr_lang]['afk_cancelled'])
                try:
                    await bot.delete_message(client_id, msg.message_id)
                except Exception: pass
    except asyncio.CancelledError:
        pass

@router.callback_query(F.data.startswith("sta_"))
async def handle_courier_stages(callback: CallbackQuery):
    # Пытаемся сразу ответить Telegram, чтобы предотвратить ошибку "query is too old"
    try:
        await callback.answer()
    except Exception:
        pass

    lang = await get_lang(callback.from_user.id)
    parts = callback.data.split("_")

    if parts[1] == "curr" and parts[2] == "cncl":
        action = "curr_cncl"
        order_id = int(parts[3])
    else:
        action = parts[1]
        order_id = int(parts[2])

    async with db_pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)

    if not order:
        # Здесь используем show_alert=True, так как ответ уже был отправлен выше
        await callback.message.answer("⚠️ Заказ не найден.")
        return

    client_lang = await get_lang(order["client_id"])

    if action == "curr_cncl":
        if order["status"] != "accepted":
            await callback.message.answer(TEXTS[lang]["cant_cancel"])
            return
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE orders SET status='pending', courier_id=NULL WHERE id=$1", order_id)
        await callback.message.edit_text("❌ Вы отказались от заказа.")
        await bot.send_message(order["client_id"], "⚠️ Курьер отказался от вашего заказа.")

    elif action == "ata":
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE orders SET status='at_a' WHERE id=$1", order_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=TEXTS[lang]["at_b_btn"], callback_data=f"sta_atb_{order_id}")]
        ])
        await callback.message.edit_reply_markup(reply_markup=kb)
        await bot.send_message(order["client_id"], TEXTS[client_lang]["client_notif_courier_at_a"])
        task = asyncio.create_task(client_afk_worker(order["client_id"], order_id, callback.from_user.id))
        active_afk_tasks[order_id] = task

    elif action == "atb":
        if order_id in active_afk_tasks:
            active_afk_tasks[order_id].cancel()
            del active_afk_tasks[order_id]
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE orders SET status='at_b' WHERE id=$1", order_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=TEXTS[lang]["done_btn"], callback_data=f"sta_done_{order_id}")]
        ])
        await callback.message.edit_reply_markup(reply_markup=kb)
        await bot.send_message(order["client_id"], TEXTS[client_lang]["client_notif_courier_at_b"])

    elif action == "done":
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE orders SET status='completed' WHERE id=$1", order_id)
        await callback.message.edit_text(f"💵 Заказ #{order_id} успешно выполнен! Сумма {order['price']} MDL.")
        await bot.send_message(order["client_id"], f"🏁 Спасибо! Заказ #{order_id} завершён.\nИтоговая оплата: {order['price']} MDL.")
# --- ОТВЕТ КЛИЕНТА НА КНОПКУ АФК ---
@router.callback_query(F.data.startswith("afk_ok_"))
async def client_not_afk(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    if order_id in active_afk_tasks:
        active_afk_tasks[order_id].cancel()
        del active_afk_tasks[order_id]
    try:
        await callback.message.delete()
    except Exception: pass
    await callback.answer("👍 Подтверждено. Вы онлайн.", show_alert=True)

# --- ОТМЕНА ЗАКАЗА КЛИЕНТОМ ---
@router.message(Command("cancel"))
async def client_cancel_order(message: Message):
    lang = await get_lang(message.from_user.id)
    async with db_pool.acquire() as conn:
        order = await conn.fetchrow(
            "SELECT id, status, courier_id FROM orders WHERE client_id = $1 AND status IN ('pending', 'accepted', 'at_a') ORDER BY id DESC LIMIT 1", 
            message.from_user.id
        )
        if not order:
            await message.answer("⚠️ У вас нет активных заказов для отмены.")
            return
        if order['status'] == 'at_a':
            await message.answer(TEXTS[lang]['cant_cancel'])
            return
        await conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = $1", order['id'])
        if order['courier_id']:
            try:
                await bot.send_message(order['courier_id'], f"🔴 Клиент отменил заказ #{order['id']}.")
            except Exception: pass
    await message.answer(TEXTS[lang]['order_cancelled'])

# --- АДМИНСКАЯ КОМАНДА ---
@router.message(Command("clear_orders"))
async def admin_clear_orders(message: Message):
    if message.from_user.id != ADMIN_ID: return
    async with db_pool.acquire() as conn:
        result = await conn.execute("DELETE FROM orders WHERE status = 'pending'")
        await message.answer(f"🧹 База очищена.")

@router.message(Command("stats"))
async def admin_stats(message: Message):
    if message.from_user.id != ADMIN_ID: return
    async with db_pool.acquire() as conn:
        orders = await conn.fetch("SELECT status, COUNT(*) FROM orders GROUP BY status")
        stats_text = "📊 Статистика заказов:\n" + "\n".join([f"{row['status']}: {row['count']}" for row in orders])
        await message.answer(stats_text)

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle_ping(request):
    return web.Response(text="Bot status: Live and healthy", status=200)

async def start_render_port_binding():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000")) 
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Port binding active on port {port}")

async def main():
    # Очистка webhook перед запуском поллинга
    await bot.delete_webhook(drop_pending_updates=True)
await dp.start_polling(bot, drop_pending_updates=True)
    
    logging.info("Starting database tables preparation...")
    # ... остальной код ...
    await init_db()
    await start_render_port_binding()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
