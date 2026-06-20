import os
import asyncio
import logging
from datetime import datetime
import asyncpg
import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command, CommandObject
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
        'comment': "💬 Введите комментарий для курьера и адрес текстом точки А и точки Б. Нажмите /skip для пропуска:",
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
        'client_notif_courier_at_a': "🔔 Курьер прибыл на точку А! Пожалуйста, выходите.",
        'client_notif_courier_at_b': "🔔 Курьер на месте назначения (Точка Б)! Заберите посылку.",
        'afk_question': "📢 Вы тут? Подтвердите, что вы онлайн. У вас 10 минут!",
        'afk_btn': "🙋‍♂️ Я тут!",
        'afk_cancelled': "🔴 Заказ отменен из-за неактивности клиента. Курьер, вы можете оставить посылку себе!",
        'cant_cancel': "⚠️ Нельзя отменить заказ после того, как курьер прибыл на точку А.",
        'order_cancelled': "🗑 Заказ успешно отменен.",
        'invalid_geo': "⚠️ Пожалуйста, используйте только кнопку «📍 Отправить геопозицию» 👇",
        'afk_ok': "✅ Спасибо! Вы подтвердили свой статус онлайн.",
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
        'comment': "💬Introduceți un comentariu pentru curier și adresa în text pentru punctul A și punctul B. /skip pentru a sări peste:",
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
        'afk_question': "📢 Sunteți aici? Confirmați prezența. Aveți 10 minute!",
        'afk_btn': "🙋‍♂️ Sunt aici!",
        'afk_cancelled': "🔴 Comanda a fost anulată din cauza inactivității clientului.",
        'cant_cancel': "⚠️ Comanda nu может быть отменена после того, как курьер прибыл на точку А.",
        'order_cancelled': "🗑 Comanda a fost anulată.",
        'invalid_geo': "⚠️ Vă rugăm să folosiți butonul „📍 Trimiteți locația” 👇",
        'afk_ok': "✅ Mulțumesc! Ați confirmat prezența online.",
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
        'comment': "Enter a comment for the courier and the address in text for point A and point B. Press /skip to skip:",
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
        'afk_question': "📢 Are you here? Confirm you are online. You have 10 minutes!",
        'afk_btn': "🙋‍♂️ I am here!",
        'afk_cancelled': "🔴 Order cancelled due to client inactivity.",
        'cant_cancel': "⚠️ Cannot cancel order after the courier has arrived at point A.",
        'order_cancelled': "🗑 Order successfully cancelled.",
        'invalid_geo': "⚠️ Please use the '📍 Send location' button below 👇",
        'afk_ok': "✅ Thank you! You confirmed your online status.",
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
    if callback.from_user.id != ADMIN_ID: return
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
                await bot.send_message(target_user_id, "⚠️ Ваша заявка на курьера была отклонена.")
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

# --- КОМАНДА ОТМЕНЫ ЗАКАЗА КЛИЕНТОМ ---
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    async with db_pool.acquire() as conn:
        current_order = await conn.fetchrow("""
            SELECT id, status FROM orders 
            WHERE client_id = $1 AND status IN ('pending', 'accepted')
            ORDER BY created_at DESC LIMIT 1
        """, message.from_user.id)
        
        if not current_order:
            await message.answer("📭 У вас нет активных заказов для отмены.")
            return
            
        if current_order['status'] != 'pending':
            await message.answer(TEXTS[lang]['cant_cancel'])
            return
            
        await conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = $1", current_order['id'])
        await message.answer(TEXTS[lang]['order_cancelled'])
        
# --- ПРОЦЕСС СОЗДАНИЯ ЗАКАЗА КЛИЕНТОМ ---
@router.message(Command("order"))
async def cmd_create_order(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    async with db_pool.acquire() as conn:
        active = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE client_id = $1 AND status NOT IN ('completed', 'cancelled')", message.from_user.id)
        if active > 0:
            await message.answer("⚠️ У вас уже есть активный заказ. Сначала завершите или отмените его.")
            return
            
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]['std'], callback_data="cargo_standard")],
        [InlineKeyboardButton(text=TEXTS[lang]['frg'], callback_data="cargo_freight")]
    ])
    await message.answer(TEXTS[lang]['cargo_type'], reply_markup=kb)
    await state.set_state(CreateOrder.cargo_type)

@router.callback_query(CreateOrder.cargo_type, F.data.startswith("cargo_"))
async def process_cargo_type(callback: CallbackQuery, state: FSMContext):
    ctype = callback.data.split("_")[1]
    await state.update_data(cargo_type=ctype)
    lang = await get_lang(callback.from_user.id)
    
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]
    ], resize_keyboard=True, one_time_keyboard=True)
    
    await callback.message.delete()
    await callback.message.answer(TEXTS[lang]['addr_a'], reply_markup=kb)
    await state.set_state(CreateOrder.addr_a)
    await callback.answer()

@router.message(CreateOrder.addr_a, F.location)
async def process_addr_a(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(lat_a=message.location.latitude, lon_a=message.location.longitude)
    
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]
    ], resize_keyboard=True, one_time_keyboard=True)
    
    await message.answer(TEXTS[lang]['addr_b'], reply_markup=kb)
    await state.set_state(CreateOrder.addr_b)

@router.message(CreateOrder.addr_a)
async def invalid_addr_a(message: Message):
    lang = await get_lang(message.from_user.id)
    await message.answer(TEXTS[lang]['invalid_geo'])

@router.message(CreateOrder.addr_b, F.location)
async def process_addr_b(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(lat_b=message.location.latitude, lon_b=message.location.longitude)
    
    await message.answer(TEXTS[lang]['phone_sender'], reply_markup=ReplyKeyboardRemove())
    await state.set_state(CreateOrder.phone_sender)

@router.message(CreateOrder.addr_b)
async def invalid_addr_b(message: Message):
    lang = await get_lang(message.from_user.id)
    await message.answer(TEXTS[lang]['invalid_geo'])

@router.message(CreateOrder.phone_sender, F.text)
async def process_phone_sender(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(phone_sender=message.text)
    await message.answer(TEXTS[lang]['phone_receiver'])
    await state.set_state(CreateOrder.phone_receiver)

@router.message(CreateOrder.phone_receiver, F.text)
async def process_phone_receiver(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(phone_receiver=message.text)
    await message.answer(TEXTS[lang]['comment'])
    await state.set_state(CreateOrder.comment)

@router.message(CreateOrder.comment)
async def process_comment(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    comm = message.text if message.text != "/skip" else "-"
    await state.update_data(comment=comm)
    
    data = await state.get_data()
    
    # Расчет дистанции OSRM
    dist_km, map_url = await get_osrm_data(data['lat_a'], data['lon_a'], data['lat_b'], data['lon_b'])
    
    # Расчет цены на основе тарифа курьера: грузовой = 20 лей/км, стандарт = 10 лей/км
    per_km_rate = 20.0 if data['cargo_type'] == 'freight' else 10.0
    
    # Базовая стоимость по километражу + 40 лей сверху, которые нигде отдельно не расписываются
    final_price = round((dist_km * per_km_rate) + 40.0, 2)
    await state.update_data(price=final_price)
    
    cargo_label = TEXTS[lang]['frg'] if data['cargo_type'] == 'freight' else TEXTS[lang]['std']
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]['yes'], callback_data="confirm_order_yes")],
        [InlineKeyboardButton(text=TEXTS[lang]['no'], callback_data="confirm_order_no")]
    ])
    
    confirm_text = TEXTS[lang]['confirm_title'].format(
        type=cargo_label,
        a=f"Точка А ({data['lat_a']:.6f}, {data['lon_a']:.6f})",
        b=f"Точка Б ({data['lat_b']:.6f}, {data['lon_b']:.6f})",
        p_send=data['phone_sender'],
        p_recv=data['phone_receiver'],
        comm=comm,
        price=f"{final_price:.2f}" # Выводит строго 2 цифры после запятой
    )
    
    await message.answer(confirm_text, reply_markup=kb)
    await state.set_state(CreateOrder.confirm)

# --- КОЛЛБЭКИ ПОДТВЕРЖДЕНИЯ ЗАКАЗА И РАБОТА КУРЬЕРОВ ---
@router.callback_query(CreateOrder.confirm, F.data.startswith("confirm_order_"))
async def process_order_confirmation(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    action = callback.data.split("_")[2]
    
    if action == "no":
        await callback.message.edit_text(TEXTS[lang]['order_cancelled'])
        await state.clear()
        await callback.answer()
        return
        
    data = await state.get_data()
    
    async with db_pool.acquire() as conn:
        order_id = await conn.fetchval("""
            INSERT INTO orders (client_id, cargo_type, addr_a, addr_b, lat_a, lon_a, lat_b, lon_b, phone_sender, phone_receiver, comment, price, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'pending')
            RETURNING id
        """, callback.from_user.id, data['cargo_type'], "Гео Точка А", "Гео Точка Б", 
           data['lat_a'], data['lon_a'], data['lat_b'], data['lon_b'],
           data['phone_sender'], data['phone_receiver'], data['comment'], data['price'])
           
        # Оповещение всех курьеров на смене
        online_couriers = await conn.fetch("SELECT user_id, lang FROM users WHERE role = 'courier' AND is_online = TRUE AND is_approved = TRUE")
        
    await callback.message.edit_text(TEXTS[lang]['order_placed'])
    await state.clear()
    
    # Рассылка предложения курьерам
    formatted_price = f"{round(float(data['price']), 2):.2f}"
    for courier in online_couriers:
        c_lang = courier['lang']
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=TEXTS[c_lang]['take_btn'].format(price=formatted_price), callback_data=f"order_take_{order_id}")]
        ])
        try:
            await bot.send_message(
                courier['user_id'], 
                f"📦 **Новый заказ #{order_id}!**\nМаршрут OSRM готов.\n💵 Стоимость: {formatted_price} MDL", 
                reply_markup=kb
            )
        except Exception: pass
        
    await callback.answer()

@router.callback_query(F.data.startswith("take_order_"))
async def cb_take_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    courier_id = callback.from_user.id
    
    # 1. Сразу отвечаем Telegram, чтобы убрать "часики"
    await callback.answer("Принимаю...")
    
    async with db_pool.acquire() as conn:
        # 2. Используем транзакцию, чтобы заказ не могли забрать двое одновременно
        async with conn.transaction():
            order = await conn.fetchrow(
                "SELECT status, client_id, cargo_type, addr_a, addr_b, phone_sender, phone_receiver, comment, price FROM orders WHERE id = $1 FOR UPDATE", 
                order_id
            )
            
            if order and order['status'] == 'pending':
                # 3. Бронируем заказ за курьером
                await conn.execute(
                    "UPDATE orders SET status = 'accepted', courier_id = $1 WHERE id = $2",
                    courier_id, order_id
                )
                
                # 4. Формируем OSRM маршрут для курьера
                # Предполагаем, что у тебя есть функция расчета
                dist, url = await get_osrm_data(0, 0, 0, 0) # Здесь твои координаты
                
                lang = await get_lang(courier_id)
                msg_text = TEXTS[lang]['order_taken'].format(
                    p_send=order['phone_sender'],
                    p_recv=order['phone_receiver'],
                    comm=order['comment'],
                    url=url
                )
                
                await callback.message.edit_text(msg_text, parse_mode="Markdown")
                
                # 5. Уведомляем клиента
                try:
                    await bot.send_message(order['client_id'], "✅ Ваш заказ принят! Курьер направляется к вам.")
                except:
                    pass
            else:
                await callback.message.edit_text("❌ Заказ уже занят или отменен.")

@router.callback_query(F.data.startswith("order_ata_"))

async def courier_at_point_a(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    c_lang = await get_lang(callback.from_user.id)
    
    async with db_pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
        await conn.execute("UPDATE orders SET status = 'at_a' WHERE id = $1", order_id)
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[c_lang]['at_b_btn'], callback_data=f"order_atb_{order_id}")]
    ])
    await callback.message.edit_reply_markup(reply_markup=kb)
    
    # Оповещаем клиента и запускаем таймер проверки присутствия клиента (AFK)
    try:
        cl_lang = await get_lang(order['client_id'])
        await bot.send_message(order['client_id'], TEXTS[cl_lang]['client_notif_courier_at_a'])
        
        # Запуск фонового таска AFK на 10 минут
        task = asyncio.create_task(client_afk_timer(order_id, order['client_id'], callback.from_user.id))
        active_afk_tasks[order_id] = task
    except Exception: pass
    
    await callback.answer()

@router.callback_query(F.data.startswith("order_atb_"))
async def courier_at_point_b(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    c_lang = await get_lang(callback.from_user.id)
    
    async with db_pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
        await conn.execute("UPDATE orders SET status = 'at_b' WHERE id = $1", order_id)
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[c_lang]['done_btn'], callback_data=f"order_done_{order_id}")]
    ])
    await callback.message.edit_reply_markup(reply_markup=kb)
    
    try:
        cl_lang = await get_lang(order['client_id'])
        await bot.send_message(order['client_id'], TEXTS[cl_lang]['client_notif_courier_at_b'])
    except Exception: pass
    await callback.answer()

@router.callback_query(F.data.startswith("order_done_"))
async def courier_complete_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    c_lang = await get_lang(callback.from_user.id)
    
    async with db_pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
        await conn.execute("UPDATE orders SET status = 'completed' WHERE id = $1", order_id)
        
    # Снимаем таймер AFK, если заказ завершен штатно
    if order_id in active_afk_tasks:
        active_afk_tasks[order_id].cancel()
        del active_afk_tasks[order_id]
        
    await callback.message.edit_text("💵 Заказ успешно завершен! Деньги зачислены на ваш баланс истории.")
    
    try:
        cl_lang = await get_lang(order['client_id'])
        await bot.send_message(order['client_id'], "🎉 Спасибо за заказ! Доставка успешно завершена.")
    except Exception: pass
    await callback.answer()

# --- ТАЙМЕР ОЖИДАНИЯ НЕАКТИВНОГО КЛИЕНТА (AFK) ---
async def client_afk_timer(order_id, client_id, courier_id):
    try:
        await asyncio.sleep(600) # 10 минут ожидания
        cl_lang = await get_lang(client_id)
        c_lang = await get_lang(courier_id)
        
        # Клиент проигнорировал уведомление, производим отмену в пользу курьера
        async with db_pool.acquire() as conn:
            await conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = $1", order_id)
            
        await bot.send_message(client_id, TEXTS[cl_lang]['afk_cancelled'])
        await bot.send_message(courier_id, f"🔴 Заказ #{order_id} отменен автоматической системой из-за AFK клиента. Вы можете оставить посылку себе.")
    except asyncio.CancelledError:
        pass


@router.message(Command("orders"))
async def cmd_view_orders(message: Message):
    lang = await get_lang(message.from_user.id)
    
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT role, is_approved, is_online FROM users WHERE user_id = $1", message.from_user.id)
        
        # 1. Проверка прав доступа курьера
        if not user or user['role'] != 'courier':
            return
            
        if not user['is_approved']:
            await message.answer(TEXTS[lang]['not_approved'])
            return
            
        if not user['is_online']:
            # Напоминаем выйти на смену, если курьер оффлайн
            await message.answer("⚠️ Вы не на смене. Наберите /online, чтобы получать заказы.")
            return
            
        # 2. Ищем свободные заказы в БД
        pending_orders = await conn.fetch("""
            SELECT * FROM orders 
            WHERE status = 'pending' 
            ORDER BY created_at ASC
        """)
        
    # 3. Если свободных заказов нет — выводим сообщение из словаря
    if not pending_orders:
        await message.answer(TEXTS[lang]['no_orders'])
        return
        
    # 4. Если заказы есть, формируем карточки заказов
    for order in pending_orders:
        c_type = TEXTS[lang]['std'] if order['cargo_type'] == 'standard' else TEXTS[lang]['frg']
        price = round(float(order['price']), 2) if order['price'] else 0.0
        
        # Формируем текст заказа
        text = TEXTS[lang]['confirm_title'].format(
            type=c_type,
            a=order['addr_a'],
            b=order['addr_b'],
            p_send=order['phone_sender'],
            p_recv=order['phone_receiver'],
            comm=order['comment'] if order['comment'] else "—",
            price=f"{price:.2f}"
        )
        
        # Добавляем кнопку "Принять заказ"
        btn_text = TEXTS[lang]['take_btn'].format(price=f"{price:.2f}")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=btn_text, callback_data=f"take_order_{order['id']}")]
        ])
        
        await message.answer(text, reply_markup=kb)


async def broadcast_order(order_data: dict):
    # Берем всех онлайн-курьеров
    async with db_pool.acquire() as conn:
        couriers = await conn.fetch("SELECT user_id FROM users WHERE role = 'courier' AND is_online = TRUE")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Принять за {order_data['price']} MDL", callback_data=f"take_order_{order_data['id']}")]
    ])
    
    for c in couriers:
        try:
            await bot.send_message(
                c['user_id'], 
                f"📦 НОВЫЙ ЗАКАЗ #{order_data['id']}\n💰 Оплата: {order_data['price']} MDL", 
                reply_markup=kb
            )
        except Exception as e:
            logging.error(f"Не удалось отправить курьеру {c['user_id']}: {e}")

# --- ГЛАВНАЯ ФУНКЦИЯ ЗАПУСКА ПРИЛОЖЕНИЯ ---
async def main():
    await init_db()
    
    # Интеграция Webhook сервера aiohttp для работы с Render
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    asyncio.create_task(site.start())
    logging.info(f"Keep-Alive HTTP-сервер успешно запущен на порту {PORT}")
    
    # Запуск Long Polling бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
