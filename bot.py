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

BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН")
DATABASE_URL = os.getenv("DATABASE_URL", "ВАШ_URL_БД")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "8080")) # Порт для Render Free Web Service

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

class SupportStates(StatesGroup):
    waiting_for_text = State()

class AdminReplyStates(StatesGroup):
    waiting_for_reply = State()

# --- ЛОКАЛИЗАЦИЯ (RU, RO, EN) ---
TEXTS = {
    'ru': {
        'start': "🌍 Выберите язык / Alegeți limba / Choose language:",
        'select_role': "👤 Выберите вашу роль в системе:",
        'client': "👨‍💼 Client",
        'courier': "🛵 Courier",
        'send_photo': "📸 Отправьте ваше фото (селфи или паспорт) для верификации администратором:",
        'wait_admin': "⏳ Ваша заявка отправлена. Ожидайте одобрения администратором.",
        'approved': "🎉 Вы успешно одобрены! Наберите /online для начала работы.",
        'not_approved': "⚠️ Вы еще не одобрены админом или заблокированы.",
        'client_menu': "🏬 Вы в меню клиента.\n/order — Создать заказ\n/cancel — Отменить текущий заказ\n/support — Написать в поддержку",
        'courier_menu': "🛵 Вы в меню курьера.\n/online — Встать на смену\n/offline — Уйти со смены\n/orders — Список доступных заказов\n/history — Мой заработок и история\n/support — Написать в поддержку",
        'cargo_type': "📦 Выберите тип доставки:",
        'std': "📦 Стандарт (10 лей/км)",
        'frg': "🚚 Грузовой (20 лей/км)",
        'addr_a': "📍 Отправьте геопозицию ТОЧКИ А с помощью кнопки ниже 👇:",
        'addr_b': "🏁 Отправьте геопозицию НАЗНАЧЕНИЯ Б с помощью кнопки ниже 👇:",
        'phone_sender': "📱 Введите номер телефона ОТПРАВИТЕЛЯ:",
        'phone_receiver': "📱 Введите номер телефона ПОЛУЧАТЕЛЯ:",
        'comment': "💬 Введите комментарий для курьера и адреса текстом. Нажмите /skip для пропуска:",
        'confirm_title': "📋 Подтверждение заказа:\n\n🔹 Тип: {type}\n🔹 Тел. Отправителя: {p_send}\n🔹 Тел. Получателя: {p_recv}\n🔹 Комментарий: {comm}\n💵 Итоговая стоимость: {price} MDL\n\nВсё верно?",
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
        'client_notif_courier_at_a': "🔔 Курьер прибыл на точку А! Пожалуйста, выходите.",
        'client_notif_courier_at_b': "🔔 Курьер на месте назначения (Точка Б)! Заберите посылку.",
        'cant_cancel': "⚠️ Нельзя отменить заказ после того, как курьер его принял.",
        'order_cancelled': "🗑 Заказ успешно отменен.",
        'invalid_geo': "⚠️ Пожалуйста, используйте только кнопку «📍 Отправить геопозицию» 👇",
        'support_req': "📝 Напишите ваше обращение в поддержку одним сообщением. Администратор ответит вам здесь:",
        'support_sent': "⏳ Ваш запрос отправлен в техподдержку. Ожидайте ответа.",
        'support_reply_header': "🔔 **Ответ от техподдержки:**\n\n",
        'history_empty': "📭 У вас еще нет выполненных заказов.",
        'history_title': "📊 **ВАША СТАТИСТИКА И ИСТОРИЯ**\n\n💰 Заработок за этот месяц: `{earnings} MDL`\n📦 Выполнено заказов в этом месяце: `{count}`\n\n📜 **Последние 10 поездок:**\n"
    },
    'ro': {
        'start': "🌍 Alegeți limba / Выберите язык / Choose language:",
        'select_role': "👤 Alegeți rolul dvs. în sistem:",
        'client': "👨‍💼 Client",
        'courier': "🛵 Curier",
        'send_photo': "📸 Trimiteți o fotografie pentru verificare de către administrator:",
        'wait_admin': "⏳ Cererea dvs. a fost trimisă. Așteptați aprobarea administratorului.",
        'approved': "🎉 Ați fost aprobat cu succes! Tastați /online pentru a începe lucrul.",
        'not_approved': "⚠️ Nu sunteți încă aprobat de admin sau sunteți blocat.",
        'client_menu': "🏬 Meniul clientului.\n/order — Crează comandă\n/cancel — Anulează comanda\n/support — Suport tehnic",
        'courier_menu': "🛵 Meniul curierului.\n/online — Intră pe tură\n/offline — Ieși de pe tură\n/orders — Lista comenzilor\n/history — Istorie și câștiguri\n/support — Suport tehnic",
        'cargo_type': "📦 Selectați tipul de livrare:",
        'std': "📦 Standard (10 MDL/km)",
        'frg': "🚚 Marfă (20 MDL/km)",
        'addr_a': "📍 Trimiteți locația PUNCTULUI A folosind butonul de mai jos 👇:",
        'addr_b': "🏁 Trimiteți locația DESTINAȚIEI B folosind butonul de mai jos 👇:",
        'phone_sender': "📱 Introduceți numărul de telefon al EXPEDITORULUI:",
        'phone_receiver': "📱 Introduceți numărul de telefon al RECEPTORULUI:",
        'comment': "💬 Introduceți un comentariu pentru curier și adresa în text. /skip pentru a sări peste:",
        'confirm_title': "📋 Confirmare comandă:\n\n🔹 Tip: {type}\n🔹 Tel. Expeditor: {p_send}\n🔹 Tel. Receptor: {p_recv}\n🔹 Comentariu: {comm}\n💵 Preț total: {price} MDL\n\nEste corect?",
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
        'cant_cancel': "⚠️ Comanda nu poate fi anulată după ce curierul a acceptat-o.",
        'order_cancelled': "🗑 Comanda a fost anulată.",
        'invalid_geo': "⚠️ Vă rugăm să folosiți butonul „📍 Trimiteți locația” 👇",
        'support_req': "📝 Scrieți solicitarea dvs. către suport într-un singur mesaj. Administratorul vă va răspunde aici:",
        'support_sent': "⏳ Solicitarea a fost trimisă. Așteptați răspunsul.",
        'support_reply_header': "🔔 **Răspuns de la suport:**\n\n",
        'history_empty': "📭 Nu aveți comenzi finalizate.",
        'history_title': "📊 **STATISTICI ȘI ISTORIC**\n\n💰 Câștiguri în această lună: `{earnings} MDL`\n📦 Comenzi finalizate în această lună: `{count}`\n\n📜 **Ultimele 10 livrări:**\n"
    },
    'en': {
        'start': "🌍 Choose language / Выберите язык / Alegeți limba:",
        'select_role': "👤 Select your role in the system:",
        'client': "👨‍💼 Client",
        'courier': "🛵 Courier",
        'send_photo': "📸 Please send your photo for admin verification:",
        'wait_admin': "⏳ Your application has been sent. Waiting for admin approval.",
        'approved': "🎉 You have been successfully approved! Type /online to start working.",
        'not_approved': "⚠️ You are not approved by the admin yet or are blocked.",
        'client_menu': "🏬 Client menu.\n/order — Create order\n/cancel — Cancel order\n/support — Contact support",
        'courier_menu': "🛵 Courier menu.\n/online — Go online\n/offline — Go offline\n/orders — View orders\n/history — Earnings & History\n/support — Contact support",
        'cargo_type': "📦 Select delivery type:",
        'std': "📦 Standard (10 MDL/km)",
        'frg': "🚚 Freight (20 MDL/km)",
        'addr_a': "📍 Send the location of POINT A using the button below 👇:",
        'addr_b': "🏁 Send the location of DESTINATION B using the button below 👇:",
        'phone_sender': "📱 Enter SENDER'S phone number:",
        'phone_receiver': "📱 Enter RECEIVER'S phone number:",
        'comment': "💬 Enter a comment for the courier and text addresses. Press /skip to skip:",
        'confirm_title': "📋 Order Confirmation:\n\n🔹 Type: {type}\n🔹 Sender Phone: {p_send}\n🔹 Receiver Phone: {p_recv}\n🔹 Comment: {comm}\n💵 Total price: {price} MDL\n\nIs everything correct?",
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
        'cant_cancel': "⚠️ Cannot cancel order after the courier has accepted it.",
        'order_cancelled': "🗑 Order successfully cancelled.",
        'invalid_geo': "⚠️ Please use the '📍 Send location' button below 👇",
        'support_req': "📝 Please write your support request in a single message. The admin will reply here:",
        'support_sent': "⏳ Your request has been sent to support. Please wait for a response.",
        'support_reply_header': "🔔 **Response from Support:**\n\n",
        'history_empty': "📭 You don't have completed orders yet.",
        'history_title': "📊 **YOUR STATS & HISTORY**\n\n💰 Earnings this month: `{earnings} MDL`\n📦 Orders completed this month: `{count}`\n\n📜 **Last 10 trips:**\n"
    }
}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def get_all_admins():
    return [ADMIN_ID]

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

async def get_lang(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT lang FROM users WHERE user_id = $1", user_id)
        return row['lang'] if row else 'ru'


# --- КОМАНДА ИСТОРИИ И ЗАРАБОТКА ДЛЯ КУРЬЕРОВ (/history) ---
@router.message(Command("history"))
async def cmd_courier_history(message: Message):
    lang = await get_lang(message.from_user.id)
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT role, is_approved FROM users WHERE user_id = $1", message.from_user.id)
        if not user or user['role'] != 'courier' or not user['is_approved']:
            await message.answer(TEXTS[lang]['not_approved'])
            return
        
        stats = await conn.fetchrow("""
            SELECT COALESCE(SUM(price), 0) AS total_earnings, COUNT(*) AS total_count 
            FROM orders 
            WHERE courier_id = $1 
              AND status = 'completed' 
              AND created_at >= date_trunc('month', CURRENT_TIMESTAMP)
        """, message.from_user.id)
        
        recent_orders = await conn.fetch("""
            SELECT id, cargo_type, price, created_at 
            FROM orders 
            WHERE courier_id = $1 AND status = 'completed' 
            ORDER BY created_at DESC 
            LIMIT 10
        """, message.from_user.id)
        
    earnings = round(float(stats['total_earnings']), 2)
    count = stats['total_count']
    
    text = TEXTS[lang]['history_title'].format(earnings=f"{earnings:.2f}", count=count)
    
    if not recent_orders:
        text += f"_{TEXTS[lang]['history_empty']}_"
    else:
        for o in recent_orders:
            date_str = o['created_at'].strftime('%d.%m %H:%M')
            c_type = "📦 Стандарт" if o['cargo_type'] == 'standard' else "🚚 Грузовой"
            o_price = round(float(o['price']), 2)
            text += f"🔹 **Заказ #{o['id']}** | {date_str} | {c_type} | `{o_price:.2f} MDL`\n"
            
    await message.answer(text, parse_mode="Markdown")

# --- СТАТИСТИКА И ИНТЕРАКТИВНАЯ АДМИН-ПАНЕЛЬ ---
async def render_admin_panel(message_or_callback):
    is_cb = isinstance(message_or_callback, CallbackQuery)
    msg = message_or_callback.message if is_cb else message_or_callback
    
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        active_orders = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status IN ('pending', 'accepted', 'at_a', 'at_b')")
        couriers = await conn.fetch("SELECT user_id, username, is_online, is_approved FROM users WHERE role = 'courier' ORDER BY is_online DESC, user_id ASC")
    
    text = (
        "📊 **ЦЕНТРАЛЬНАЯ ПАНЕЛЬ АДМИНИСТРАТОРА**\n\n"
        f"👥 Всего зарегистрировано: `{total_users}`\n"
        f"📦 Активных заказов в процессе: `{active_orders}`\n\n"
        f"🛵 **База курьеров и управление:**\n"
    )
    
    kb_lines = []
    for c in couriers:
        status_emoji = "🟢 СМЕНА" if c['is_online'] else "🔴 ОФФ"
        tg_user = f"@{c['username']}" if c['username'] else f"ID {c['user_id']}"
        text += f"{status_emoji} | {tg_user} | Доступ: {'✅' if c['is_approved'] else '❌ БАН'}\n"
        
        ban_btn_text = "🚫 Бан" if c['is_approved'] else "🟢 Разбан"
        ban_cb_data = f"p_ban_{c['user_id']}" if c['is_approved'] else f"p_unban_{c['user_id']}"
        
        row = [
            InlineKeyboardButton(text="📊 Фин. История", callback_data=f"p_hist_{c['user_id']}"),
            InlineKeyboardButton(text=ban_btn_text, callback_data=ban_cb_data)
        ]
        kb_lines.append(row)
        
    kb_lines.append([InlineKeyboardButton(text="🔄 Обновить панель", callback_data="p_refresh")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_lines)
    
    if is_cb:
        try: await msg.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        except TelegramBadRequest: pass
    else:
        await msg.answer(text, reply_markup=kb, parse_mode="Markdown")


@router.message(Command("reset_orders"))
async def cmd_reset_orders(message: Message, state: FSMContext):
    admins = await get_all_admins()
    if message.from_user.id not in admins:
        return

    # 1. Отменяем все фоновые таймеры AFK, чтобы они не стучались в пустую БД
    for order_id, task in list(active_afk_tasks.items()):
        task.cancel()
        logging.info(f"Таймер AFK для заказа #{order_id} принудительно остановлен.")
    active_afk_tasks.clear()

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # 2. Полностью очищаем таблицу заказов и сбрасываем счетчик ID
            await conn.execute("TRUNCATE TABLE orders RESTART IDENTITY CASCADE;")
            
            # 3. Возвращаем всех курьеров в оффлайн, чтобы избежать багов со сменами
            await conn.execute("UPDATE users SET is_online = FALSE WHERE role = 'courier';")

    # 4. Сбрасываем FSM-состояние самого админа, если он находился в каком-то меню
    await state.clear()

    await message.answer(
        "🧹 **Система полностью перезапущена:**\n\n"
        "🔹 Все заказы удалены из базы данных.\n"
        "🔹 Счетчики ID заказов сброшены на 1.\n"
        "🔹 Все курьеры принудительно переведены в оффлайн.\n"
        "🔹 Все активные AFK-таймеры уничтожены.",
        parse_mode="Markdown"
    )
    logging.info(f"Администратор {message.from_user.id} выполнил полную очистку заказов (/reset_orders).")

@router.message(Command("admin"))
async def cmd_admin_panel(message: Message):
    admins = await get_all_admins()
    if message.from_user.id not in admins: return
    await render_admin_panel(message)

@router.callback_query(F.data == "p_refresh")
async def cb_refresh_panel(callback: CallbackQuery):
    admins = await get_all_admins()
    if callback.from_user.id not in admins: return
    await callback.answer("Данные обновлены")
    await render_admin_panel(callback)

@router.callback_query(F.data.startswith("p_hist_"))
async def cb_admin_view_history(callback: CallbackQuery):
    admins = await get_all_admins()
    if callback.from_user.id not in admins: return
    
    courier_id = int(callback.data.split("_")[2])
    
    async with db_pool.acquire() as conn:
        c_info = await conn.fetchrow("SELECT username FROM users WHERE user_id = $1", courier_id)
        tg_user = f"@{c_info['username']}" if c_info and c_info['username'] else f"ID {courier_id}"
        
        stats = await conn.fetchrow("""
            SELECT COALESCE(SUM(price), 0) AS total_earnings, COUNT(*) AS total_count 
            FROM orders 
            WHERE courier_id = $1 
              AND status = 'completed' 
              AND created_at >= date_trunc('month', CURRENT_TIMESTAMP)
        """, courier_id)
        
        recent_orders = await conn.fetch("""
            SELECT id, cargo_type, price, created_at 
            FROM orders 
            WHERE courier_id = $1 AND status = 'completed' 
            ORDER BY created_at DESC 
            LIMIT 10
        """, courier_id)
        
    earnings = round(float(stats['total_earnings']), 2)
    count = stats['total_count']
    
    text = (
        f"📊 **ФИНАНСОВАЯ СТАТИСТИКА КУРЬЕРА {tg_user}**\n\n"
        f"💰 Заработок в этом месяце: `{earnings:.2f} MDL`\n"
        f"📦 Выполнено заказов: `{count}`\n\n"
        f"📜 **Последние 10 выполненных поездок:**\n"
    )
    
    if not recent_orders:
        text += "_У этого курьера пока нет выполненных заказов в системе._"
    else:
        for o in recent_orders:
            date_str = o['created_at'].strftime('%d.%m %H:%M')
            c_type = "📦 Стандарт" if o['cargo_type'] == 'standard' else "🚚 Грузовой"
            o_price = round(float(o['price']), 2)
            text += f"🔹 **Заказ #{o['id']}** | {date_str} | {c_type} | `{o_price:.2f} MDL`\n"
            
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад в админку", callback_data="p_refresh")]
    ])
    
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data.startswith("p_ban_"))
async def cb_panel_ban(callback: CallbackQuery):
    admins = await get_all_admins()
    if callback.from_user.id not in admins: return
    target_id = int(callback.data.split("_")[2])
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_approved = FALSE, is_online = FALSE WHERE user_id = $1", target_id)
    await callback.answer(f"Курьер {target_id} заблокирован", show_alert=True)
    try: await bot.send_message(target_id, "⚠️ Вы были заблокированы администратором системы.")
    except Exception: pass
    await render_admin_panel(callback)

@router.callback_query(F.data.startswith("p_unban_"))
async def cb_panel_unban(callback: CallbackQuery):
    admins = await get_all_admins()
    if callback.from_user.id not in admins: return
    target_id = int(callback.data.split("_")[2])
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_approved = TRUE WHERE user_id = $1", target_id)
    await callback.answer(f"Курьер {target_id} одобрен / разбанен", show_alert=True)
    try: await bot.send_message(target_id, "🎉 Администратор одобрил ваш профиль/разблокировал вас!")
    except Exception: pass
    await render_admin_panel(callback)

# --- МОДУЛЬ ДВУСТОРОННЕЙ ТЕХПОДДЕРЖКИ (/support) ---
@router.message(Command("support"))
async def cmd_support(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await message.answer(TEXTS[lang]['support_req'])
    await state.set_state(SupportStates.waiting_for_text)

@router.message(SupportStates.waiting_for_text)
async def process_support_message(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    tg_user = f"@{message.from_user.username}" if message.from_user.username else "Нет юзернейма"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Ответить клиенту", callback_data=f"ticket_reply_{message.from_user.id}")]
    ])
    
    admin_text = (
        f"📩 **НОВОЕ ОБРАЩЕНИЕ В ТЕХПОДДЕРЖКУ!**\n\n"
        f"👤 Отправитель: {message.from_user.full_name}\n"
        f"🆔 ID пользователя: `{message.from_user.id}`\n"
        f"📱 Телеграм: {tg_user}\n\n"
        f"💬 **Текст обращения:**\n{message.text}"
    )
    
    await bot.send_message(ADMIN_ID, admin_text, reply_markup=kb, parse_mode="Markdown")
    await message.answer(TEXTS[lang]['support_sent'])
    await state.clear()

@router.callback_query(F.data.startswith("ticket_reply_"))
async def cb_start_ticket_reply(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    target_user_id = int(callback.data.split("_")[2])
    
    await state.update_data(reply_target_id=target_user_id)
    await callback.message.answer(f"✍️ Введите текст ответа для пользователя `{target_user_id}`. Он будет отправлен мгновенно:")
    await state.set_state(AdminReplyStates.waiting_for_reply)
    await callback.answer()

@router.message(AdminReplyStates.waiting_for_reply)
async def process_admin_reply_send(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    data = await state.get_data()
    target_id = data.get("reply_target_id")
    
    if not target_id:
        await message.answer("❌ Ошибка: пользователь для ответа не найден в сессии.")
        await state.clear()
        return
        
    target_lang = await get_lang(target_id)
    full_reply = f"{TEXTS[target_lang]['support_reply_header']}{message.text}"
    
    try:
        await bot.send_message(target_id, full_reply, parse_mode="Markdown")
        await message.answer(f"✅ Ответ успешно перенаправлен пользователю `{target_id}`.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение. Ошибка: {e}")
        
    await state.clear()

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

# --- HTTP СЕРВЕР ДЛЯ UPTIME ROBOT / RENDER ---
async def handle_ping(request):
    return web.Response(text="Keep Alive OK", status=200)

# --- БАЗОВЫЕ КОМАНДЫ И РЕГИСТРАЦИЯ ---
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

# --- МЕНЮ КЛИЕНТА: СОЗДАНИЕ И ОТМЕНА ЗАКАЗА ---
@router.message(Command("order"))
async def cmd_order(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]['std'], callback_data="cargo_standard")],
        [InlineKeyboardButton(text=TEXTS[lang]['frg'], callback_data="cargo_freight")]
    ])
    await message.answer(TEXTS[lang]['cargo_type'], reply_markup=kb)
    await state.set_state(CreateOrder.cargo_type)

@router.callback_query(CreateOrder.cargo_type, F.data.startswith("cargo_"))
async def process_cargo_type(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    cargo_type = callback.data.split("_")[1]
    await state.update_data(cargo_type=cargo_type)
    
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]], resize_keyboard=True)
    await callback.message.answer(TEXTS[lang]['addr_a'], reply_markup=kb)
    await state.set_state(CreateOrder.addr_a)
    await callback.answer()

@router.message(CreateOrder.addr_a, F.location)
async def process_addr_a(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(lat_a=message.location.latitude, lon_a=message.location.longitude)
    
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]], resize_keyboard=True)
    await message.answer(TEXTS[lang]['addr_b'], reply_markup=kb)
    await state.set_state(CreateOrder.addr_b)

@router.message(CreateOrder.addr_b, F.location)
async def process_addr_b(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(lat_b=message.location.latitude, lon_b=message.location.longitude)
    
    await message.answer(TEXTS[lang]['phone_sender'], reply_markup=ReplyKeyboardRemove())
    await state.set_state(CreateOrder.phone_sender)

@router.message(CreateOrder.phone_sender)
async def process_phone_sender(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(phone_sender=message.text)
    await message.answer(TEXTS[lang]['phone_receiver'])
    await state.set_state(CreateOrder.phone_receiver)

@router.message(CreateOrder.phone_receiver)
async def process_phone_receiver(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(phone_receiver=message.text)
    await message.answer(TEXTS[lang]['comment'])
    await state.set_state(CreateOrder.comment)

@router.message(CreateOrder.comment)
async def process_comment(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    comment = message.text if message.text.lower() != '/skip' else "Нет комментария"
    data = await state.get_data()
    
    dist_km, map_url = await get_osrm_data(data['lat_a'], data['lon_a'], data['lat_b'], data['lon_b'])
    multiplier = 10 if data['cargo_type'] == 'standard' else 20
    price = round(dist_km * multiplier, 2)
    if price < 30: price = 30.0 # Минимальная сумма
    
    await state.update_data(comment=comment, price=price, map_url=map_url)
    
    c_type_str = "📦 Стандарт" if data['cargo_type'] == 'standard' else "🚚 Грузовой"
    text = TEXTS[lang]['confirm_title'].format(
        type=c_type_str,
        p_send=data['phone_sender'],
        p_recv=data['phone_receiver'],
        comm=comment,
        price=price
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]['yes'], callback_data="confirm_order")],
        [InlineKeyboardButton(text=TEXTS[lang]['no'], callback_data="cancel_order_fsm")]
    ])
    await message.answer(text, reply_markup=kb)
    await state.set_state(CreateOrder.confirm)

@router.callback_query(CreateOrder.confirm, F.data == "confirm_order")
async def process_confirm_order(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    data = await state.get_data()
    
    async with db_pool.acquire() as conn:
        order_id = await conn.fetchval("""
            INSERT INTO orders (client_id, cargo_type, lat_a, lon_a, lat_b, lon_b, phone_sender, phone_receiver, comment, price, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'pending') RETURNING id
        """, callback.from_user.id, data['cargo_type'], data['lat_a'], data['lon_a'], data['lat_b'], data['lon_b'], data['phone_sender'], data['phone_receiver'], data['comment'], data['price'])
        
        # Оповещаем курьеров онлайн
        couriers = await conn.fetch("SELECT user_id, lang FROM users WHERE role = 'courier' AND is_online = TRUE")
    
    await callback.message.edit_text(TEXTS[lang]['order_placed'])
    
    # Рассылка курьерам
    for c in couriers:
        c_lang = c['lang']
        c_type = "📦 Стандарт" if data['cargo_type'] == 'standard' else "🚚 Грузовой"
        broadcast_text = f"🚨 **НОВЫЙ ЗАКАЗ #{order_id}**\n🔹 {c_type}\n💵 {data['price']} MDL"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=TEXTS[c_lang]['take_btn'].format(price=data['price']), callback_data=f"take_{order_id}")]
        ])
        try:
            await bot.send_message(c['user_id'], broadcast_text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            pass
            
    await state.clear()

@router.callback_query(CreateOrder.confirm, F.data == "cancel_order_fsm")
async def process_cancel_fsm(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(TEXTS[lang]['order_cancelled'])
    await state.clear()

@router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    lang = await get_lang(message.from_user.id)
    async with db_pool.acquire() as conn:
        current_order = await conn.fetchrow("""
            SELECT id, status FROM orders 
            WHERE client_id = $1 AND status = 'pending'
        """, message.from_user.id)
        
        if not current_order:
            await message.answer(TEXTS[lang]['cant_cancel'])
            return
            
        await conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = $1", current_order['id'])
    
    await message.answer(TEXTS[lang]['order_cancelled'])

# --- МЕНЮ КУРЬЕРА: ВЗЯТЬ И ИСПОЛНИТЬ ЗАКАЗ ---
@router.message(Command("online"))
async def go_online(message: Message):
    lang = await get_lang(message.from_user.id)
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT role, is_approved FROM users WHERE user_id = $1", message.from_user.id)
        if user and user['role'] == 'courier' and user['is_approved']:
            await conn.execute("UPDATE users SET is_online = TRUE WHERE user_id = $1", message.from_user.id)
            await message.answer("🟢 Вы вышли на онлайн-смену! Ожидайте новые заказы.")
        else:llback_data="confirm_yes")],
        [InlineKeyboardButton(text=TEXTS[lang]['no'], callback_data="confirm_no")]
    ])
    
    await message.answer(text, reply_markup=kb)
    await state.set_state(CreateOrder.confirm)

@router.callback_query(CreateOrder.confirm, F.data == "confirm_yes")
async def process_confirm_yes(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    data = await state.get_data()
    
    async with db_pool.acquire() as conn:
        # Добавляем заказ в БД
        order_id = await conn.fetchval('''
            INSERT INTO orders (client_id, cargo_type, lat_a, lon_a, lat_b, lon_b, phone_sender, phone_receiver, comment, price, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'pending')
            RETURNING id
        ''', callback.from_user.id, data['cargo_type'], data['lat_a'], data['lon_a'], data['lat_b'], data['lon_b'], 
             data['phone_sender'], data['phone_receiver'], data['comment'], data['price'])
        
        # Получаем онлайн курьеров
        couriers = await conn.fetch("SELECT user_id, lang FROM users WHERE role = 'courier' AND is_online = TRUE AND is_approved = TRUE")

    await callback.message.edit_text(TEXTS[lang]['order_placed'])
    await state.clear()
    
    # Рассылаем заказ курьерам
    for c in couriers:
        c_lang = c['lang']
        c_type_str = "📦 Стандарт" if data['cargo_type'] == 'standard' else "🚚 Грузовой"
        
        text = (
            f"🔔 **Новый заказ #{order_id}**\n\n"
            f"🔹 Тип: {c_type_str}\n"
            f"💵 Стоимость: `{data['price']} MDL`\n"
            f"🗺 [Маршрут OSRM (нажмите)]({data['map_url']})\n\n"
            f"Быстрее принимайте!"
        )
        
        take_btn_text = TEXTS[c_lang]['take_btn'].format(price=data['price'])
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=take_btn_text, callback_data=f"take_order_{order_id}")]
        ])
        
        try:
            await bot.send_message(c['user_id'], text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление курьеру {c['user_id']}: {e}")

@router.callback_query(CreateOrder.confirm, F.data == "confirm_no")
async def process_confirm_no(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(TEXTS[lang]['order_cancelled'])
    await state.clear()

@router.message(Command("cancel"))
async def cmd_cancel_client(message: Message):
    lang = await get_lang(message.from_user.id)
    async with db_pool.acquire() as conn:
        order = await conn.fetchrow("SELECT id, status FROM orders WHERE client_id = $1 AND status = 'pending' ORDER BY created_at DESC LIMIT 1", message.from_user.id)
        if not order:
            await message.answer(TEXTS[lang]['cant_cancel'])
            return
        
        await conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = $1", order['id'])
        
    await message.answer(TEXTS[lang]['order_cancelled'])


# --- ЛОГИКА КУРЬЕРОВ (РАБОТА С ЗАКАЗАМИ) ---
@router.message(Command("online"))
async def cmd_online(message: Message):
    lang = await get_lang(message.from_user.id)
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT is_approved FROM users WHERE user_id = $1 AND role = 'courier'", message.from_user.id)
        if not user or not user['is_approved']:
            await message.answer(TEXTS[lang]['not_approved'])
            return
            
        await conn.execute("UPDATE users SET is_online = TRUE WHERE user_id = $1", message.from_user.id)
    await message.answer("🟢 Вы вышли на смену. Теперь вы будете получать новые заказы.")

@router.message(Command("offline"))
async def cmd_offline(message: Message):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_online = FALSE WHERE user_id = $1", message.from_user.id)
    await message.answer("🔴 Вы ушли со смены. Заказы временно не будут вам поступать.")

@router.callback_query(F.data.startswith("take_order_"))
async def process_take_order(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    order_id = int(callback.data.split("_")[2])
    
    async with db_pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
        
        if not order or order['status'] != 'pending':
            await callback.answer("⚠️ Этот заказ уже кто-то забрал или он отменен.", show_alert=True)
            await callback.message.delete()
            return
            
        # Назначаем курьера
        await conn.execute("UPDATE orders SET status = 'accepted', courier_id = $1 WHERE id = $2", callback.from_user.id, order_id)
        
    _, map_url = await get_osrm_data(order['lat_a'], order['lon_a'], order['lat_b'], order['lon_b'])
    
    # Формируем сообщение курьеру
    courier_text = TEXTS[lang]['order_taken'].format(
        p_send=order['phone_sender'],
        p_recv=order['phone_receiver'],
        comm=order['comment'],
        url=map_url
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]['at_a_btn'], callback_data=f"at_a_{order_id}")]
    ])
    
    await callback.message.edit_text(courier_text, reply_markup=kb, disable_web_page_preview=True)
    await callback.answer()
    
    # Уведомляем клиента
    client_lang = await get_lang(order['client_id'])
    try:
        await bot.send_message(order['client_id'], f"🚗 Курьер выехал! Ваш заказ #{order_id} в работе.")
    except Exception:
        pass

@router.callback_query(F.data.startswith("at_a_"))
async def process_at_a(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    order_id = int(callback.data.split("_")[2])
    
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE orders SET status = 'at_a' WHERE id = $1", order_id)
        client_id = await conn.fetchval("SELECT client_id FROM orders WHERE id = $1", order_id)
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]['at_b_btn'], callback_data=f"at_b_{order_id}")]
    ])
    await callback.message.edit_reply_markup(reply_markup=kb)
    
    # Уведомляем клиента
    client_lang = await get_lang(client_id)
    try:
        await bot.send_message(client_id, TEXTS[client_lang]['client_notif_courier_at_a'])
    except Exception:
        pass

@router.callback_query(F.data.startswith("at_b_"))
async def process_at_b(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    order_id = int(callback.data.split("_")[2])
    
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE orders SET status = 'at_b' WHERE id = $1", order_id)
        client_id = await conn.fetchval("SELECT client_id FROM orders WHERE id = $1", order_id)
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]['done_btn'], callback_data=f"done_{order_id}")]
    ])
    await callback.message.edit_reply_markup(reply_markup=kb)
    
    # Уведомляем клиента
    client_lang = await get_lang(client_id)
    try:
        await bot.send_message(client_id, TEXTS[client_lang]['client_notif_courier_at_b'])
    except Exception:
        pass

@router.callback_query(F.data.startswith("done_"))
async def process_done(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE orders SET status = 'completed' WHERE id = $1", order_id)
        client_id, price = await conn.fetchrow("SELECT client_id, price FROM orders WHERE id = $1", order_id)
        
    await callback.message.edit_text(f"✅ Заказ #{order_id} успешно завершен!\n💵 Получено: `{price} MDL`", parse_mode="Markdown")
    
    try:
        await bot.send_message(client_id, f"✅ Ваш заказ #{order_id} успешно доставлен! Спасибо, что выбираете нас.")
    except Exception:
        pass


# --- АДМИНИСТРАТОР: ОДОБРЕНИЕ / ОТКЛОНЕНИЕ КУРЬЕРОВ ---
@router.callback_query(F.data.startswith("adm_appr_"))
async def process_admin_approve(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    target_id = int(callback.data.split("_")[2])
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_approved = TRUE WHERE user_id = $1", target_id)
        
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ ОДОБРЕН")
    
    try:
        target_lang = await get_lang(target_id)
        await bot.send_message(target_id, TEXTS[target_lang]['approved'])
    except Exception:
        pass

@router.callback_query(F.data.startswith("adm_decl_"))
async def process_admin_decline(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    
    target_id = int(callback.data.split("_")[2])
    await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ ОТКЛОНЕН")
    
    try:
        target_lang = await get_lang(target_id)
        await bot.send_message(target_id, "⚠️ Ваша заявка была отклонена администратором.")
    except Exception:
        pass

# --- ГЛАВНАЯ ФУНКЦИЯ И ЗАПУСК ---
async def main():
    # Инициализация пула БД
    await init_db()
    
    # Настройка aiohttp для health-check (Render)
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"Веб-сервер запущен на порту {PORT}")
    
    # Удаление вебхука (на случай, если был настроен ранее) и запуск поллинга
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Bot запущен (Polling)...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Остановка бота...")
