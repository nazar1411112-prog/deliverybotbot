import os
import asyncio
import logging
import random
from datetime import datetime, timedelta
import asyncpg
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, BotCommand
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramBadRequest

# --- ИНИЦИАЛИЗАЦИЯ И ЛОГИРОВАНИЕ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logging.warning("BOT_TOKEN is not set in environment variables!")
    BOT_TOKEN = "PLACEHOLDER_TOKEN"

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
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

# --- ЛОКАЛИЗАЦИЯ (RU, RO, EN, UK, MO) ---
TEXTS = {
    'ru': {
        'start': "🌍 Выберите язык / Alegeți limba / Choose language / Оберіть мову:",
        'select_role': "👤 Выберите вашу роль в системе:",
        'client': "👨‍💼 Client",
        'courier': "🛵 Courier",
        'send_photo': "📸 Отправьте ваше фото (селфи или паспорт) для верификации администратором:",
        'wait_admin': "⏳ Ваша заявка отправлена. Ожидайте одобрения администратором.",
        'approved': "🎉 Вы успешно одобрены! Наберите /online для начала работы.",
        'not_approved': "⚠️ Вы еще не одобрены админом или заблокированы.",
        'client_menu': "🏬 Вы в меню клиента.\n/order — Создать заказ\n/cancel — Отменить текущий заказ\n/support — Написать в поддержку\n/verify — Привязать приложение",
        'courier_menu': "🛵 Вы в меню курьера.\n/online — Встать на смену\n/offline — Уйти со смены\n/orders — Список доступных заказов\n/history — Мой заработок и история\n/support — Написать в поддержку",
        'cargo_type': "📦 Выберите тип доставки:",
        'std': "📦 Стандарт (10 лей/км)",
        'frg': "🚚 Грузовой (20 лей/км)",
        'addr_a': "📍 Отправьте геопозицию ТОЧКИ А с помощью кнопки ниже 👇:",
        'addr_b': "🏁 Отправьте геопозицию НАЗНАЧЕНИЯ Б с помощью кнопки ниже 👇:",
        'phone_sender': "📱 Введите номер телефона ОТПРАВИТЕЛЯ:",
        'phone_receiver': "📱 Введите номер телефона ПОЛУЧАТЕЛЯ:",
        'comment': "💬 Введите комментарий для курьера и адреса точки А и Б текстом:",
        'confirm_title': "📋 Подтверждение заказа:\n\n🔹 Тип: {type}\n🔹 Тел. Отправителя: {p_send}\n🔹 Тел. Получателя: {p_recv}\n🔹 Комментарий: {comm}\n💵 Итоговая стоимость: {price} MDL\n\nВсё верно?",
        'yes': "✅ Да, заказываю",
        'no': "❌ Отмена",
        'order_placed': "🚀 Заказ опубликован! Ищем ближайших курьеров...",
        'no_orders': "📭 На данный момент нет свободных заказов.",
        'take_btn': "✅ Принять заказ за {price} MDL",
        'cancel_btn': "❌ Отказаться",
        'order_taken': "🤝 Вы приняли заказ! Двигайтесь на точку А.\nℹ️ Инфо:\n📞 Отправитель: {p_send}\n📞 Получатель: {p_recv}\n💬 Комм: {comm}\n🗺 Маршрут Google Maps: {url}",
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
        'start': "🌍 Alegeți limba / Выберите язык / Choose language / Оберіть мову:",
        'select_role': "👤 Alegeți rolul dvs. în sistem:",
        'client': "👨‍💼 Client",
        'courier': "🛵 Curier",
        'send_photo': "📸 Trimiteți o fotografie pentru verificare de către administrator:",
        'wait_admin': "⏳ Cererea dvs. a fost trimisă. Așteptați aprobarea administratorului.",
        'approved': "🎉 Ați fost aprobat cu succes! Tastați /online pentru a începe lucrul.",
        'not_approved': "⚠️ Nu sunteți încă aprobat de admin sau sunteți blocat.",
        'client_menu': "🏬 Meniul clientului.\n/order — Crează comandă\n/cancel — Anulează comanda\n/support — Suport tehnic\n/verify — Conectați aplicația",
        'courier_menu': "🛵 Meniul curierului.\n/online — Intră pe tură\n/offline — Ieși de pe tură\n/orders — Lista comenzilor\n/history — Istorie și câștiguri\n/support — Suport tehnic",
        'cargo_type': "📦 Selectați tipul de livrare:",
        'std': "📦 Standard (10 MDL/km)",
        'frg': "🚚 Marfă (20 MDL/km)",
        'addr_a': "📍 Trimiteți locația PUNCTULUI A folosind butonul de mai jos 👇:",
        'addr_b': "🏁 Trimiteți locația DESTINAȚIEI B folosind butonul de mai jos 👇:",
        'phone_sender': "📱 Introduceți numărul de telefon al EXPEDITORULUI:",
        'phone_receiver': "📱 Introduceți numărul de telefon al RECEPTORULUI:",
        'comment': "💬 Introduceți un comentariu pentru curier și adresele punctelor A și B în text:",
        'confirm_title': "📋 Confirmare comandă:\n\n🔹 Tip: {type}\n🔹 Tel. Expeditor: {p_send}\n🔹 Tel. Receptor: {p_recv}\n🔹 Comentariu: {comm}\n💵 Preț total: {price} MDL\n\nEste corect?",
        'yes': "✅ Da, comand",
        'no': "❌ Anulare",
        'order_placed': "🚀 Comanda a fost publicată! Căutăm curieri...",
        'no_orders': "📭 În prezent nu există comenzi disponibile.",
        'take_btn': "✅ Acceptă comanda pentru {price} MDL",
        'cancel_btn': "❌ Refuză",
        'order_taken': "🤝 Ați acceptat comanda! Deplasați-vă la punctul A.\nℹ️ Info:\n📞 Expeditor: {p_send}\n📞 Receptor: {p_recv}\n💬 Comm: {comm}\n🗺 Rută Google Maps: {url}",
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
        'start': "🌍 Choose language / Выберите язык / Alegeți limba / Оберіть мову:",
        'select_role': "👤 Select your role in the system:",
        'client': "👨‍💼 Client",
        'courier': "🛵 Courier",
        'send_photo': "📸 Please send your photo for admin verification:",
        'wait_admin': "⏳ Your application has been sent. Waiting for admin approval.",
        'approved': "🎉 You have been successfully approved! Type /online to start working.",
        'not_approved': "⚠️ You are not approved by the admin yet or are blocked.",
        'client_menu': "🏬 Client menu.\n/order — Create order\n/cancel — Cancel order\n/support — Contact support\n/verify — Bind mobile app",
        'courier_menu': "🛵 Courier menu.\n/online — Go online\n/offline — Go offline\n/orders — View orders\n/history — Earnings & History\n/support — Contact support",
        'cargo_type': "📦 Select delivery type:",
        'std': "📦 Standard (10 MDL/km)",
        'frg': "🚚 Freight (20 MDL/km)",
        'addr_a': "📍 Send the location of POINT A using the button below 👇:",
        'addr_b': "🏁 Send the location of DESTINATION B using the button below 👇:",
        'phone_sender': "📱 Enter SENDER'S phone number:",
        'phone_receiver': "📱 Enter RECEIVER'S phone number:",
        'comment': "💬 Enter a comment for the courier and the addresses of points A and B in text:",
        'confirm_title': "📋 Order Confirmation:\n\n🔹 Type: {type}\n🔹 Sender Phone: {p_send}\n🔹 Receiver Phone: {p_recv}\n🔹 Comment: {comm}\n💵 Total price: {price} MDL\n\nIs everything correct?",
        'yes': "✅ Yes, place order",
        'no': "❌ Cancel",
        'order_placed': "🚀 Order placed! Searching for couriers...",
        'no_orders': "📭 No available orders at the moment.",
        'take_btn': "✅ Accept order for {price} MDL",
        'cancel_btn': "❌ Decline",
        'order_taken': "🤝 You accepted the order! Proceed to point A.\nℹ️ Info:\n📞 Sender: {p_send}\n📞 Receiver: {p_recv}\n💬 Comment: {comm}\n🗺 Google Maps Route: {url}",
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
    },
    'uk': {
        'start': "🌍 Оберіть мову / Выберите язык / Alegeți limba / Choose language:",
        'select_role': "👤 Оберіть вашу роль у системі:",
        'client': "👨‍💼 Клієнт",
        'courier': "🛵 Кур'єр",
        'send_photo': "📸 Надішліть ваше фото (селфі або паспорт) для верифікації адміністратором:",
        'wait_admin': "⏳ Ваша заявка відправлена. Очікуйте схвалення адміністратором.",
        'approved': "🎉 Вас успішно схвалено! Введіть /online для початку роботи.",
        'not_approved': "⚠️ Вас ще не схвалив адмін або ви заблоковані.",
        'client_menu': "🏬 Ви в меню клієнта.\n/order — Створити замовлення\n/cancel — Скасувати поточне замовлення\n/support — Написати в підтримку\n/verify — Прив'язати додаток",
        'courier_menu': "🛵 Ви в меню кур'єра.\n/online — Вийти на зміну\n/offline — Піти зі зміни\n/orders — Список доступних замовлень\n/history — Мій заробіток та історія\n/support — Написати в підтримку",
        'cargo_type': "📦 Оберіть тип доставки:",
        'std': "📦 Стандарт (10 лей/км)",
        'frg': "🚚 Вантажний (20 лей/км)",
        'addr_a': "📍 Надішліть геопозицію ТОЧКИ А за допомогою кнопки нижче 👇:",
        'addr_b': "🏁 Надішліть геопозицію ТОЧКИ Б за допомогою кнопки нижче 👇:",
        'phone_sender': "📱 Введіть номер телефону ВІДПРАВНИКА:",
        'phone_receiver': "📱 Введіть номер телефону ОТРИМУВАЧА:",
        'comment': "💬 Введіть коментар для кур'єра та адреси точок А і Б текстом:",
        'confirm_title': "📋 Підтвердження замовлення:\n\n🔹 Тип: {type}\n🔹 Тел. Відправника: {p_send}\n🔹 Тел. Отримувача: {p_recv}\n🔹 Коментар: {comm}\n💵 Підсумкова вартість: {price} MDL\n\nВсе вірно?",
        'yes': "✅ Так, замовляю",
        'no': "❌ Скасувати",
        'order_placed': "🚀 Замовлення опубліковано! Шукаємо найближчих кур'єрів...",
        'no_orders': "📭 На даний момент немає вільних замовлень.",
        'take_btn': "✅ Прийняти замовлення за {price} MDL",
        'cancel_btn': "❌ Відмовитися",
        'order_taken': "🤝 Ви прийняли замовлення! Рухайтесь на точку А.\nℹ️ Інфо:\n📞 Відправник: {p_send}\n📞 Отримувач: {p_recv}\n💬 Коментар: {comm}\n🗺 Маршрут Google Maps: {url}",
        'at_a_btn': "📍 Я на точці А",
        'at_b_btn': "🏁 Я на місці (Точка Б)",
        'done_btn': "💵 Завершити",
        'client_notif_courier_at_a': "🔔 Кур'єр прибув на точку А! Будь ласка, виходьте.",
        'client_notif_courier_at_b': "🔔 Кур'єр на місці призначення (Точка Б)! Заберіть посилку.",
        'cant_cancel': "⚠️ Не можна скасувати замовлення після того, як кур'єр його прийняв.",
        'order_cancelled': "🗑 Замовлення успішно скасовано.",
        'invalid_geo': "⚠️ Будь ласка, використовуйте тільки кнопку «📍 Надішліть геопозицію» 👇",
        'support_req': "📝 Напишіть ваше звернення до підтримки одним повідомленням. Адміністратор відповість вам тут:",
        'support_sent': "⏳ Ваш запит відправлено до техпідтримки. Очікуйте на відповідь.",
        'support_reply_header': "🔔 **Відповідь від техпідтримки:**\n\n",
        'history_empty': "📭 У вас ще немає виконаних замовлень.",
        'history_title': "📊 **ВАША СТАТИСТИКА ТА ІСТОРІЯ**\n\n💰 Заробіток за цей місяць: `{earnings} MDL`\n📦 Виконано замовлень у цьому місяці: `{count}`\n\n📜 **Останні 10 поїздок:**\n"
    },
    'mo': {
        'start': "🌍 Alegeți limba / Выберите язык / Choose language / Оберіть мову:",
        'select_role': "👤 Selectați rolul în sistem:",
        'client': "👨‍💼 Client",
        'courier': "🛵 Curier",
        'send_photo': "📸 Trimiteți o fotografie pentru verificare de către administrator:",
        'wait_admin': "⏳ Solicitarea dvs. a fost trimisă. Așteptați aprobarea administratorului.",
        'approved': "🎉 Ați fost aprobat cu succes! Introduceți /online pentru a începe lucrul.",
        'not_approved': "⚠️ Nu sunteți aprobat de admin sau sunteți blocat.",
        'client_menu': "🏬 Meniul clientului.\n/order — Crează comandă\n/cancel — Anulează comanda\n/support — Suport\n/verify — Conectați aplicația",
        'courier_menu': "🛵 Meniul curierului.\n/online — Pe tură\n/offline — În afara turei\n/orders — Listează comenzile\n/history — Istoric și venit\n/support — Suport",
        'cargo_type': "📦 Selectați tipul de livrare:",
        'std': "📦 Standard (10 MDL/km)",
        'frg': "🚚 Marfă (20 MDL/km)",
        'addr_a': "📍 Trimiteți locația PUNCTULUI A prin butonul de mai jos 👇:",
        'addr_b': "🏁 Trimiteți locația DESTINAȚIEI B prin butonul de mai jos 👇:",
        'phone_sender': "📱 Introduceți numărul de telefon al EXPEDITORULUI:",
        'phone_receiver': "📱 Introduceți numărul de telefon al RECEPTORULUI:",
        'comment': "💬 Introduceți un comentariu pentru curier și adresele în format text:",
        'confirm_title': "📋 Confirmare comandă:\n\n🔹 Tip: {type}\n🔹 Tel. Expeditor: {p_send}\n🔹 Tel. Receptor: {p_recv}\n🔹 Comentariu: {comm}\n💵 Preț total: {price} MDL\n\nEste corect?",
        'yes': "✅ Da, comand",
        'no': "❌ Anulare",
        'order_placed': "🚀 Comanda a fost plasată! Căutăm curierul...",
        'no_orders': "📭 Momentan nu sunt comenzi disponibile.",
        'take_btn': "✅ Acceptă comanda pentru {price} MDL",
        'cancel_btn': "❌ Refuză",
        'order_taken': "🤝 Ați acceptat comanda! Mergi la punctul A.\nℹ️ Info:\n📞 Expeditor: {p_send}\n📞 Receptor: {p_recv}\n💬 Comm: {comm}\n🗺 Traseu Google Maps: {url}",
        'at_a_btn': "📍 Sunt la punctul A",
        'at_b_btn': "🏁 Sunt la destinație (Punctul B)",
        'done_btn': "💵 Finalizează",
        'client_notif_courier_at_a': "🔔 Curierul a sosit la punctul A! Ieșiți afară.",
        'client_notif_courier_at_b': "🔔 Curierul este la destinație (Punctul B)! Ridicați coletul.",
        'cant_cancel': "⚠️ Nu se poate anula după ce curierul a acceptat-o.",
        'order_cancelled': "🗑 Comanda a fost anulată.",
        'invalid_geo': "⚠️ Vă rugăm să folosiți butonul „📍 Trimiteți locația” de mai jos 👇",
        'support_req': "📝 Scrieți solicitarea dvs. într-un singur mesaj. Administratorul va răspunde aici:",
        'support_sent': "⏳ Solicitarea a fost trimisă. Așteptați răspunsul.",
        'support_reply_header': "🔔 **Răspuns de la suport:**\n\n",
        'history_empty': "📭 Nu aveți comenzi finalizate.",
        'history_title': "📊 **STATISTICI ȘI ISTORIC**\n\n💰 Venit în această lună: `{earnings} MDL`\n📦 Comenzi finalizate: `{count}`\n\n📜 **Ultimele 10 livrări:**\n"
    }
}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
async def get_all_admins():
    return [ADMIN_ID]

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

async def safe_send(func, *args, **kwargs):
    """Защита от падений Telegram API"""
    try:
        return await func(*args, **kwargs)
    except Exception as e:
        logging.warning(f"Telegram send error: {e}")
        return None

def parse_price(value):
    try:
        return round(float(value), 2)
    except:
        return 0.0

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)

    async with db_pool.acquire() as conn:
        # Основная таблица пользователей
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                role TEXT,
                lang TEXT DEFAULT 'ru',
                is_approved BOOLEAN DEFAULT FALSE,
                is_online BOOLEAN DEFAULT FALSE,
                username TEXT
            );
        """)

        # Миграция: Добавляем колонку app_profile_id, если она отсутствует
        await conn.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS app_profile_id TEXT;
        """)

        # Белый список
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS whitelist (
                user_id BIGINT PRIMARY KEY
            );
        """)

        # Заказы
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                client_id BIGINT,
                cargo_type TEXT,
                addr_a TEXT,
                addr_b TEXT,
                lat_a NUMERIC,
                lon_a NUMERIC,
                lat_b NUMERIC,
                lon_b NUMERIC,
                phone_sender TEXT,
                phone_receiver TEXT,
                comment TEXT,
                price NUMERIC,
                status TEXT DEFAULT 'pending',
                courier_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Техподдержка
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id SERIAL PRIMARY KEY,
                client_id BIGINT,
                name TEXT,
                username TEXT,
                message TEXT,
                reply TEXT,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Коды подтверждения (время жизни 30 секунд)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS app_verification_codes (
                profile_id TEXT PRIMARY KEY,
                code TEXT,
                telegram_id BIGINT,
                telegram_username TEXT,
                telegram_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

async def get_lang(user_id):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT lang FROM users WHERE user_id = $1", user_id)
        return row['lang'] if row else 'ru'

# --- ОБЩАЯ КОМАНДА ОТМЕНЫ (/cancel) ---
@router.message(Command("cancel"))
async def cmd_cancel_anywhere(message: Message, state: FSMContext):
    try:
        current_state = await state.get_state()
        if current_state:
            await state.clear()
            await message.answer("❌ Операция отменена. Вы вышли из процесса.", reply_markup=ReplyKeyboardRemove())
        else:
            await message.answer("ℹ️ Сейчас нет активного действия.", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        await state.clear()
        await message.answer("❌ Ошибка отмены, но процесс сброшен.", reply_markup=ReplyKeyboardRemove())

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

# --- КОМАНДА ДЛЯ АВТОРИЗАЦИИ / ПРИВЯЗКИ ПРИЛОЖЕНИЯ (/verify) ---
@router.message(Command("verify"))
async def cmd_verify_app(message: Message):
    lang = await get_lang(message.from_user.id)
    
    # Извлекаем 16-значный ID из команды, например, /verify APP-1234-5678-ABCD
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        help_texts = {
            'ru': "🔑 **Авторизация в приложении**\n\nДля привязки аккаунта введите команду `/verify [16-значный ID]`.\n\n_Пример:_ `/verify DEL-A9F8-B2C3-E5D7`",
            'ro': "🔑 **Autorizare în aplicație**\n\nPentru a asocia contul, introduceți comanda `/verify [ID din 16 caractere]`.\n\n_Exemplu:_ `/verify DEL-A9F8-B2C3-E5D7`",
            'en': "🔑 **App Authorization**\n\nTo bind your account, type `/verify [16-character ID]`.\n\n_Example:_ `/verify DEL-A9F8-B2C3-E5D7`",
            'uk': "🔑 **Авторизація в додатку**\n\nДля прив'язки акаунту введіть команду `/verify [16-значний ID]`.\n\n_Приклад:_ `/verify DEL-A9F8-B2C3-E5D7`",
            'mo': "🔑 **Autorizare în aplicație**\n\nPentru a asocia contul, introduceți comanda `/verify [ID de 16 caractere]`.\n\n_Exemplu:_ `/verify DEL-A9F8-B2C3-E5D7`"
        }
        await message.answer(help_texts.get(lang, help_texts['ru']), parse_mode="Markdown")
        return

    profile_id = parts[1].strip().upper()
    
    # Простая валидация длины ID (должно быть 15-16 символов с учетом дефисов)
    clean_id = profile_id.replace("-", "")
    if len(clean_id) not in (15, 16):
        await message.answer("⚠️ Неверный формат ID. ID в приложении должен содержать ровно 15 или 16 символов. Проверьте ID на вкладке Профиль!")
        return

    # Генерируем 6-значный одноразовый код, действующий ровно 30 секунд
    verification_code = f"{random.randint(100000, 999999)}"
    
    tg_username = message.from_user.username or ""
    tg_name = message.from_user.full_name or ""
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO app_verification_codes (profile_id, code, telegram_id, telegram_username, telegram_name, created_at)
            VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
            ON CONFLICT (profile_id) DO UPDATE 
            SET code = $2, telegram_id = $3, telegram_username = $4, telegram_name = $5, created_at = CURRENT_TIMESTAMP;
        """, clean_id, verification_code, message.from_user.id, tg_username, tg_name)

    success_texts = {
        'ru': f"🔑 **КОД ПОДТВЕРЖДЕНИЯ:** `{verification_code}`\n\n🕒 Код действует ровно **30 секунд**!\nВведите его в приложении доставки для завершения входа.",
        'ro': f"🔑 **COD DE CONFIRMARE:** `{verification_code}`\n\n🕒 Codul este valabil doar **30 de secunde**!\nIntroduceți-l în aplicația de livrare pentru a finaliza autentificarea.",
        'en': f"🔑 **VERIFICATION CODE:** `{verification_code}`\n\n🕒 The code is valid for exactly **30 seconds**!\nEnter it in the delivery app to complete the login.",
        'uk': f"🔑 **КОД ПІДТВЕРДЖЕННЯ:** `{verification_code}`\n\n🕒 Код діє рівно **30 секунд**!\nВведіть його в додатку доставки для завершення входу.",
        'mo': f"🔑 **COD DE CONFIRMARE:** `{verification_code}`\n\n🕒 Codul este valabil doar **30 de secunde**!\nIntroduceți-l în aplicația de livrare pentru a finaliza autentificarea."
    }

    await message.answer(success_texts.get(lang, success_texts['ru']), parse_mode="Markdown")

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

    for order_id, task in list(active_afk_tasks.items()):
        task.cancel()
        logging.info(f"Таймер AFK для заказа #{order_id} принудительно остановлен.")
    active_afk_tasks.clear()

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE TABLE orders RESTART IDENTITY CASCADE;")
            await conn.execute("UPDATE users SET is_online = FALSE WHERE role = 'courier';")

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
    
    # 1. Сохраняем ответ в базу данных, чтобы Android-приложение моментально загрузило его
    async with db_pool.acquire() as conn:
        await conn.execute("""
            UPDATE support_tickets 
            SET reply = $1, status = 'resolved' 
            WHERE client_id = $2 AND status = 'open'
        """, message.text, target_id)

    # 2. Дублируем ответ в Telegram пользователя (если он зарегистрирован у бота)
    try:
        await bot.send_message(target_id, full_reply, parse_mode="Markdown")
        await message.answer(f"✅ Ответ успешно сохранен в базу данных и отправлен в Telegram пользователю `{target_id}`.")
    except Exception as e:
        await message.answer(f"✅ Ответ успешно сохранен в БД и доступен в Android-приложении. (В Telegram отправить не удалось: {e})")
        
    await state.clear()

# --- РАСЧЕТ МАРШРУТА GOOGLE MAPS & OSRM ---
async def get_osrm_data(lat1, lon1, lat2, lon2):
    # Google Maps URL for driving route
    map_url = f"https://www.google.com/maps/dir/?api=1&origin={lat1},{lon1}&destination={lat2},{lon2}&travelmode=driving"
    osrm_api = (
        f"https://router.project-osrm.org/route/v1/driving/"
        f"{lon1},{lat1};{lon2},{lat2}"
        f"?overview=false&geometries=geojson"
    )
    dist_km = 5.0
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(osrm_api, timeout=10) as resp:
                data = await resp.json()
                if data.get("routes"):
                    dist_km = data["routes"][0]["distance"] / 1000
    except Exception as e:
        logging.error(f"Routing distance fetch error: {e}")

    return round(dist_km, 2), map_url

# --- HTTP СЕРВЕР И REST API ДЛЯ ANDROID ПРИЛОЖЕНИЯ ---

async def handle_ping(request):
    return web.Response(text="Keep Alive OK", status=200)

def get_config_path():
    import os
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/update_config.json"
    return "update_config.json"

def get_apk_path():
    import os
    if os.path.isdir("/data") and os.access("/data", os.W_OK):
        return "/data/app-release.apk"
    return "app-release.apk"

def get_update_config():
    import os
    import json
    default_config = {
        "latest_version": "2.1.4",
        "update_message_ru": "⚡️ Доступно новое полнофункциональное обновление! Нажмите «Обновить сейчас» для скачивания актуального APK-файла.",
        "update_message_ro": "⚡️ O nouă actualizare completă este disponibilă! Apăsați «Actualizează acum» pentru a descărca fișierul APK actual.",
        "update_message_en": "⚡️ A new full update is available! Tap 'Update Now' to download the latest APK file.",
        "force_update": True,
        "new_features": ["Chisinau Autocomplete", "Live Delivery Timer", "40 MDL Base Fare", "Optimized Fluid Interactive Map"]
    }
    config_path = get_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error reading update config: {e}")
    return default_config

def save_update_config(config):
    import json
    config_path = get_config_path()
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        logging.error(f"Error saving update config: {e}")
        return False

async def handle_app_update_api(request):
    """
    API для Android: Проверка обновлений "на лету" без переустановки APK.
    Возвращает актуальный статус и сообщения для пользователей из динамического конфига.
    """
    config = get_update_config()
    return web.json_response({
        "success": True,
        "latest_version": config.get("latest_version", "2.1.4"),
        "update_message_ru": config.get("update_message_ru", ""),
        "update_message_ro": config.get("update_message_ro", ""),
        "update_message_en": config.get("update_message_en", ""),
        "force_update": config.get("force_update", True),
        "new_features": config.get("new_features", []),
        "apk_url": "/api/download-apk"
    })

async def handle_download_apk_api(request):
    """
    API для Android: Скачивание актуального APK-файла обновления.
    Если файл app-release.apk существует, отдает его.
    """
    import os
    apk_path = get_apk_path()
    if os.path.exists(apk_path):
        return web.FileResponse(
            path=apk_path,
            headers={
                "Content-Disposition": 'attachment; filename="delivery-app-update.apk"'
            }
        )
    else:
        # Если APK нет, редиректим на админку загрузки
        raise web.HTTPFound('/admin/upload')

async def handle_admin_panel(request):
    """
    Веб-панель администратора для удобной и безопасной загрузки APK и настройки обновлений.
    """
    import os
    from datetime import datetime
    
    config = get_update_config()
    apk_path = get_apk_path()
    
    if os.path.exists(apk_path):
        size_bytes = os.path.getsize(apk_path)
        apk_size = f"{size_bytes / (1024 * 1024):.2f} MB"
        mtime = os.path.getmtime(apk_path)
        apk_date = datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M")
    else:
        apk_size = "Не загружен"
        apk_date = "—"
        
    features_raw = "\n".join(config.get("new_features", []))
    force_checked = "checked" if config.get("force_update", True) else ""
    
    html_template = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Панель Администратора | Обновление Delivery App</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0d0f12;
            --card-bg: #14181f;
            --primary: #22c55e;
            --primary-hover: #16a34a;
            --text-color: #f3f4f6;
            --text-muted: #9ca3af;
            --border-color: #1e293b;
            --error-color: #ef4444;
        }
        
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            padding: 40px 20px;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }

        .container {
            width: 100%;
            max-width: 800px;
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.4);
        }

        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 30px;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 20px;
        }

        header h1 {
            font-size: 24px;
            font-weight: 800;
            letter-spacing: -0.5px;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        header h1 span {
            color: var(--primary);
        }

        .badge {
            background: rgba(34, 197, 94, 0.1);
            color: var(--primary);
            padding: 6px 12px;
            border-radius: 50px;
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border: 1px solid rgba(34, 197, 94, 0.2);
        }

        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .status-card {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
        }

        .status-card .label {
            font-size: 12px;
            color: var(--text-muted);
            text-transform: uppercase;
            font-weight: 600;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }

        .status-card .value {
            font-size: 18px;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }

        .status-card .value.active {
            color: var(--primary);
        }

        .form-group {
            margin-bottom: 24px;
        }

        label {
            display: block;
            font-size: 14px;
            font-weight: 600;
            margin-bottom: 8px;
            color: var(--text-color);
        }

        input[type="text"], textarea, input[type="password"] {
            width: 100%;
            background: #090b0d;
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 12px 16px;
            color: var(--text-color);
            font-size: 14px;
            font-family: inherit;
            transition: all 0.2s;
        }

        input[type="text"]:focus, textarea:focus, input[type="password"]:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.1);
        }

        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 24px;
        }

        .checkbox-group input[type="checkbox"] {
            accent-color: var(--primary);
            width: 18px;
            height: 18px;
            cursor: pointer;
        }

        .upload-zone {
            border: 2px dashed var(--border-color);
            border-radius: 16px;
            padding: 40px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s;
            background: rgba(255, 255, 255, 0.01);
            margin-bottom: 30px;
            position: relative;
        }

        .upload-zone:hover, .upload-zone.dragover {
            border-color: var(--primary);
            background: rgba(34, 197, 94, 0.02);
        }

        .upload-zone svg {
            width: 48px;
            height: 48px;
            fill: var(--text-muted);
            margin-bottom: 16px;
            transition: all 0.2s;
        }

        .upload-zone:hover svg, .upload-zone.dragover svg {
            fill: var(--primary);
            transform: translateY(-4px);
        }

        .upload-zone p {
            font-size: 14px;
            color: var(--text-muted);
            margin-bottom: 8px;
        }

        .upload-zone .highlight {
            color: var(--text-color);
            font-weight: 600;
        }

        .file-info {
            display: none;
            margin-top: 15px;
            padding: 10px;
            background: rgba(255, 255, 255, 0.03);
            border-radius: 8px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 12px;
        }

        .progress-container {
            display: none;
            margin-bottom: 24px;
        }

        .progress-bar-wrapper {
            background: #090b0d;
            border-radius: 50px;
            height: 10px;
            overflow: hidden;
            border: 1px solid var(--border-color);
        }

        .progress-bar {
            background: var(--primary);
            width: 0%;
            height: 100%;
            transition: width 0.1s ease-out;
        }

        .progress-text {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 6px;
        }

        button.btn-submit {
            width: 100%;
            background: var(--primary);
            color: #090b0d;
            border: none;
            border-radius: 12px;
            padding: 16px;
            font-size: 16px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }

        button.btn-submit:hover {
            background: var(--primary-hover);
            transform: translateY(-1px);
        }

        button.btn-submit:active {
            transform: translateY(0);
        }

        .alert {
            padding: 16px;
            border-radius: 10px;
            margin-bottom: 24px;
            font-size: 14px;
            font-weight: 600;
            display: none;
        }

        .alert-success {
            background: rgba(34, 197, 94, 0.1);
            color: var(--primary);
            border: 1px solid rgba(34, 197, 94, 0.2);
        }

        .alert-error {
            background: rgba(239, 68, 110, 0.1);
            color: var(--error-color);
            border: 1px solid rgba(239, 68, 110, 0.2);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📦 <span>OTA</span> Update Center</h1>
            <div class="badge">Render Admin</div>
        </header>

        <div id="alert-success" class="alert alert-success"></div>
        <div id="alert-error" class="alert alert-error"></div>

        <div class="status-grid">
            <div class="status-card">
                <div class="label">Текущая Версия</div>
                <div class="value active" id="stat-version">{current_version}</div>
            </div>
            <div class="status-card">
                <div class="label">Размер APK файла</div>
                <div class="value" id="stat-apk-size">{apk_size}</div>
            </div>
            <div class="status-card">
                <div class="label">Последнее изменение</div>
                <div class="value" id="stat-apk-date" style="font-size: 13px;">{apk_date}</div>
            </div>
        </div>

        <form id="upload-form" enctype="multipart/form-data">
            <div class="form-group">
                <label for="latest_version">Номер новой версии (например, 2.1.5)</label>
                <input type="text" id="latest_version" name="latest_version" value="{current_version}" required placeholder="2.1.5">
            </div>

            <div class="form-group">
                <label for="message_ru">Текст обновления на русском (RU)</label>
                <textarea id="message_ru" name="message_ru" rows="2" required placeholder="⚡️ Доступно новое обновление...">{message_ru}</textarea>
            </div>

            <div class="form-group">
                <label for="message_ro">Текст обновления на румынском (RO)</label>
                <textarea id="message_ro" name="message_ro" rows="2" required placeholder="⚡️ O nouă actualizare...">{message_ro}</textarea>
            </div>

            <div class="form-group">
                <label for="message_en">Текст обновления на английском (EN)</label>
                <textarea id="message_en" name="message_en" rows="2" required placeholder="⚡️ A new update is available...">{message_en}</textarea>
            </div>

            <div class="form-group">
                <label for="features">Что нового? (одно изменение на строку)</label>
                <textarea id="features" name="features" rows="4" placeholder="Chisinau Autocomplete&#10;Live Delivery Timer">{features_raw}</textarea>
            </div>

            <div class="checkbox-group">
                <input type="checkbox" id="force_update" name="force_update" value="true" {force_checked}>
                <label for="force_update" style="margin-bottom: 0; cursor: pointer;">Обязательное обновление (пользователь не сможет закрыть окно)</label>
            </div>

            <div class="form-group">
                <label>Загрузить новый APK-файл (drag-and-drop или клик)</label>
                <div class="upload-zone" id="drop-zone">
                    <svg viewBox="0 0 24 24">
                        <path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM14 13v4h-4v-4H7l5-5 5 5h-3z"/>
                    </svg>
                    <p class="highlight">Перетащите сюда APK или нажмите для выбора</p>
                    <p>Поддерживается только формат .apk</p>
                    <input type="file" id="file-input" name="apk_file" accept=".apk" style="display: none;">
                    <div id="file-display" class="file-info"></div>
                </div>
            </div>

            <div class="progress-container" id="progress-container">
                <div class="progress-bar-wrapper">
                    <div class="progress-bar" id="progress-bar"></div>
                </div>
                <div class="progress-text">
                    <span id="progress-percent">0%</span>
                    <span id="progress-bytes">0 / 0 MB</span>
                </div>
            </div>

            <div class="form-group">
                <label for="password">🔑 Пароль Администратора (для защиты от взлома)</label>
                <input type="password" id="password" name="password" required placeholder="Введите ваш ADMIN_PASSWORD с Render">
            </div>

            <button type="submit" class="btn-submit">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="17 8 12 3 7 8"></polyline>
                    <line x1="12" y1="3" x2="12" y2="15"></line>
                </svg>
                Выпустить Обновление по всем Устройствам
            </button>
        </form>
    </div>

    <script>
        const dropZone = document.getElementById('drop-zone');
        const fileInput = document.getElementById('file-input');
        const fileDisplay = document.getElementById('file-display');
        const form = document.getElementById('upload-form');
        const successAlert = document.getElementById('alert-success');
        const errorAlert = document.getElementById('alert-error');
        const progressContainer = document.getElementById('progress-container');
        const progressBar = document.getElementById('progress-bar');
        const progressPercent = document.getElementById('progress-percent');
        const progressBytes = document.getElementById('progress-bytes');

        dropZone.addEventListener('click', () => fileInput.click());

        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'));
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            if (e.dataTransfer.files.length) {
                const file = e.dataTransfer.files[0];
                if (file.name.endsWith('.apk')) {
                    fileInput.files = e.dataTransfer.files;
                    updateFileDisplay(file);
                } else {
                    showAlert(errorAlert, 'Пожалуйста, выберите корректный файл .apk!');
                }
            }
        });

        fileInput.addEventListener('change', () => {
            if (fileInput.files.length) {
                updateFileDisplay(fileInput.files[0]);
            }
        });

        function updateFileDisplay(file) {
            const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
            fileDisplay.innerHTML = `✓ Выбран файл: <strong>${file.name}</strong> (\${sizeMB} MB)`;
            fileDisplay.style.display = 'block';
        }

        function showAlert(element, text) {
            successAlert.style.display = 'none';
            errorAlert.style.display = 'none';
            element.textContent = text;
            element.style.display = 'block';
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        form.addEventListener('submit', (e) => {
            e.preventDefault();
            
            const formData = new FormData(form);
            const forceCheckbox = document.getElementById('force_update');
            formData.set('force_update', forceCheckbox.checked ? "true" : "false");

            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/admin/upload', true);

            progressContainer.style.display = 'block';
            progressBar.style.width = '0%';
            progressPercent.textContent = '0%';

            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    const percent = Math.round((e.loaded / e.total) * 100);
                    const loadedMB = (e.loaded / (1024 * 1024)).toFixed(1);
                    const totalMB = (e.total / (1024 * 1024)).toFixed(1);
                    
                    progressBar.style.width = percent + '%';
                    progressPercent.textContent = percent + '%';
                    progressBytes.textContent = `\${loadedMB} / \${totalMB} MB`;
                }
            });

            xhr.onreadystatechange = () => {
                if (xhr.readyState === XMLHttpRequest.DONE) {
                    progressContainer.style.display = 'none';
                    try {
                        const response = JSON.parse(xhr.responseText);
                        if (xhr.status === 200 && response.success) {
                            showAlert(successAlert, '🚀 Ура! Обновление успешно выпущено на все устройства клиентов!');
                            
                            document.getElementById('stat-version').textContent = document.getElementById('latest_version').value;
                            if (fileInput.files.length) {
                                const sizeMB = (fileInput.files[0].size / (1024 * 1024)).toFixed(2) + ' MB';
                                document.getElementById('stat-apk-size').textContent = sizeMB;
                                document.getElementById('stat-apk-date').textContent = 'Только что';
                            }
                            
                            fileInput.value = '';
                            fileDisplay.style.display = 'none';
                        } else {
                            showAlert(errorAlert, '❌ Ошибка: ' + (response.error || 'Неизвестная ошибка на сервере.'));
                        }
                    } catch (err) {
                        showAlert(errorAlert, '❌ Ошибка обработки ответа сервера.');
                    }
                }
            };

            xhr.send(formData);
        });
    </script>
</body>
</html>"""
    
    html_filled = html_template.format(
        current_version=config.get("latest_version", "2.1.4"),
        message_ru=config.get("update_message_ru", ""),
        message_ro=config.get("update_message_ro", ""),
        message_en=config.get("update_message_en", ""),
        features_raw=features_raw,
        force_checked=force_checked,
        apk_size=apk_size,
        apk_date=apk_date
    )
    
    return web.Response(text=html_filled, content_type="text/html")

async def handle_admin_upload(request):
    """
    Обработчик загрузки APK-файла и обновления конфигурации.
    """
    import os
    
    reader = await request.multipart()
    
    password = ""
    latest_version = ""
    message_ru = ""
    message_ro = ""
    message_en = ""
    features_raw = ""
    force_update = True
    file_data = None
    
    while True:
        part = await reader.next()
        if part is None:
            break
            
        if part.name == "password":
            password = (await part.read()).decode("utf-8").strip()
        elif part.name == "latest_version":
            latest_version = (await part.read()).decode("utf-8").strip()
        elif part.name == "message_ru":
            message_ru = (await part.read()).decode("utf-8").strip()
        elif part.name == "message_ro":
            message_ro = (await part.read()).decode("utf-8").strip()
        elif part.name == "message_en":
            message_en = (await part.read()).decode("utf-8").strip()
        elif part.name == "features":
            features_raw = (await part.read()).decode("utf-8").strip()
        elif part.name == "force_update":
            val = (await part.read()).decode("utf-8").strip()
            force_update = (val.lower() == "true")
        elif part.name == "apk_file":
            filename = part.filename
            if filename:
                file_data = bytearray()
                while True:
                    chunk = await part.read_chunk()
                    if not chunk:
                        break
                    file_data.extend(chunk)

    # Защитная аутентификация
    env_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    if password != env_password:
        return web.json_response({"success": False, "error": "Неверный пароль администратора!"}, status=403)

    # Сохраняем новые настройки в файл динамического обновления
    config = get_update_config()
    if latest_version:
        config["latest_version"] = latest_version
    if message_ru is not None:
        config["update_message_ru"] = message_ru
    if message_ro is not None:
        config["update_message_ro"] = message_ro
    if message_en is not None:
        config["update_message_en"] = message_en
    config["force_update"] = force_update
    
    if features_raw is not None:
        config["new_features"] = [line.strip() for line in features_raw.split("\n") if line.strip()]
        
    save_update_config(config)

    # Сохраняем APK-файл на диск, если он был передан
    if file_data:
        apk_path = get_apk_path()
        try:
            dir_name = os.path.dirname(apk_path)
            if dir_name and not os.path.exists(dir_name):
                os.makedirs(dir_name, exist_ok=True)
            with open(apk_path, "wb") as f:
                f.write(file_data)
        except Exception as e:
            return web.json_response({"success": False, "error": f"Ошибка при записи APK на диск: {e}"}, status=500)

    return web.json_response({"success": True, "message": "Настройки и файл обновления успешно сохранены!"})

async def handle_verify_api(request):
    """
    API для Android: Проверка 6-значного кода активации.
    Служит для авторизации в приложении и привязки Telegram-профиля к 16-значному profile_id.
    Срок действия кода: 30 секунд.
    """
    try:
        data = await request.json()
        profile_id = str(data['profile_id']).strip().upper().replace("-", "")
        code = str(data['code']).strip()
        
        async with db_pool.acquire() as conn:
            # Получаем код из базы
            row = await conn.fetchrow("""
                SELECT * FROM app_verification_codes 
                WHERE profile_id = $1 AND code = $2
            """, profile_id, code)
            
            if not row:
                return web.json_response({
                    "success": False,
                    "error": "Неверный код или неверный ID профиля приложения"
                }, status=400)
                
            # Проверяем срок действия (30 секунд)
            created_at = row['created_at']
            now = datetime.now()
            # Разница во времени
            delta = now - created_at.replace(tzinfo=None)
            
            if delta.total_seconds() > 30:
                # Удаляем истекший код
                await conn.execute("DELETE FROM app_verification_codes WHERE profile_id = $1", profile_id)
                return web.json_response({
                    "success": False,
                    "error": "Срок действия кода подтверждения (30 секунд) истек!"
                }, status=400)
                
            # Код верный и не истек! Удаляем его, чтобы сделать одноразовым
            await conn.execute("DELETE FROM app_verification_codes WHERE profile_id = $1", profile_id)
            
            # Привязываем Telegram-пользователя к profile_id
            telegram_id = row['telegram_id']
            telegram_username = row['telegram_username']
            telegram_name = row['telegram_name']
            
            await conn.execute("""
                INSERT INTO users (user_id, role, lang, is_approved, is_online, username, app_profile_id)
                VALUES ($1, 'client', 'ru', TRUE, FALSE, $2, $3)
                ON CONFLICT (user_id) DO UPDATE 
                SET app_profile_id = $3, username = $2;
            """, telegram_id, telegram_username, profile_id)
            
        return web.json_response({
            "success": True,
            "telegram_id": telegram_id,
            "telegram_username": telegram_username,
            "telegram_name": telegram_name,
            "error": None
        })
        
    except Exception as e:
        logging.error(f"Error in handle_verify_api: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)

async def handle_delete_account_api(request):
    """ API для Android: Удаление аккаунта пользователя """
    try:
        profile_id = str(request.match_info['profileId']).strip().upper().replace("-", "")
        async with db_pool.acquire() as conn:
            # Сбрасываем привязку profile_id
            await conn.execute("UPDATE users SET app_profile_id = NULL WHERE app_profile_id = $1", profile_id)
            # Удаляем заказы? Обычно оставляют, но здесь сбрасываем привязку
        return web.json_response({
            "success": True,
            "error": None
        })
    except Exception as e:
        logging.error(f"Error deleting account via API: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=400)

async def handle_create_order_api(request):
    """ API для Android: Создание нового заказа """
    try:
        data = await request.json()
        client_id = int(data['client_id'])
        cargo_type = str(data['cargo_type'])
        lat_a = float(data['lat_a'])
        lon_a = float(data['lon_a'])
        lat_b = float(data['lat_b'])
        lon_b = float(data['lon_b'])
        phone_sender = str(data['phone_sender'])
        phone_receiver = str(data['phone_receiver'])
        comment = str(data.get('comment', ''))
        price = float(data['price'])
        
        async with db_pool.acquire() as conn:
            order_id = await conn.fetchval("""
                INSERT INTO orders (
                    client_id, cargo_type, addr_a, addr_b, lat_a, lon_a, lat_b, lon_b, 
                    phone_sender, phone_receiver, comment, price, status
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'pending')
                RETURNING id
            """, 
            client_id, cargo_type, "Точка А (Локация)", "Точка Б (Локация)",
            lat_a, lon_a, lat_b, lon_b, phone_sender, phone_receiver, comment, price)
            
            online_couriers = await conn.fetch(
                "SELECT user_id, lang FROM users WHERE role = 'courier' AND is_online = TRUE AND is_approved = TRUE"
            )
            
        c_type_str = "📦 Стандарт" if cargo_type == 'standard' else "🚚 Грузовой"
        for courier in online_couriers:
            c_lang = courier['lang']
            c_text = (
                f"🆕 **НОВЫЙ ЗАКАЗ #{order_id}!**\n\n"
                f"🔹 Тип: {c_type_str}\n"
                f"💵 Стоимость: `{price:.2f} MDL`\n"
                f"💬 Комментарий: {comment}\n"
            )
            kb_take = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=TEXTS[c_lang]['take_btn'].format(price=f"{price:.2f}"), 
                    callback_data=f"order_take_{order_id}"
                )]
            ])
            try:
                await bot.send_message(courier['user_id'], c_text, reply_markup=kb_take, parse_mode="Markdown")
            except Exception as e:
                logging.error(f"Ошибка отправки заказа курьеру {courier['user_id']}: {e}")
                
        return web.json_response({
            "success": True,
            "order_id": order_id,
            "error": None
        })
    except Exception as e:
        logging.error(f"Error creating order via API: {e}")
        return web.json_response({
            "success": False,
            "order_id": None,
            "error": str(e)
        }, status=400)

async def handle_get_active_order_api(request):
    """ API для Android: Получение текущего активного заказа """
    try:
        client_id = int(request.match_info['clientId'])
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT o.*, u.username as courier_name 
                FROM orders o 
                LEFT JOIN users u ON o.courier_id = u.user_id 
                WHERE o.client_id = $1 AND o.status IN ('pending', 'accepted', 'at_a', 'at_b')
                ORDER BY o.id DESC LIMIT 1
            """, client_id)
            
        if not row:
            return web.json_response({
                "success": True,
                "order": None,
                "error": None
            })
            
        order_dto = {
            "id": row['id'],
            "cargo_type": row['cargo_type'],
            "lat_a": float(row['lat_a']),
            "lon_a": float(row['lon_a']),
            "lat_b": float(row['lat_b']),
            "lon_b": float(row['lon_b']),
            "phone_sender": row['phone_sender'],
            "phone_receiver": row['phone_receiver'],
            "comment": row['comment'],
            "price": float(row['price']),
            "status": row['status'],
            "courier_id": row['courier_id'],
            "courier_name": row['courier_name'],
            "courier_lat": None,
            "courier_lon": None
        }
        
        return web.json_response({
            "success": True,
            "order": order_dto,
            "error": None
        })
    except Exception as e:
        logging.error(f"Error getting active order via API: {e}")
        return web.json_response({
            "success": False,
            "order": None,
            "error": str(e)
        }, status=400)

async def handle_cancel_order_api(request):
    """ API для Android: Отмена заказа клиентом """
    try:
        order_id = int(request.match_info['id'])
        async with db_pool.acquire() as conn:
            order = await conn.fetchrow("SELECT status, client_id, courier_id FROM orders WHERE id = $1", order_id)
            if not order:
                return web.json_response({
                    "success": False,
                    "error": "Заказ не найден"
                }, status=404)
                
            if order['status'] != 'pending':
                return web.json_response({
                    "success": False,
                    "error": "Нельзя отменить заказ после того, как курьер его принял"
                }, status=400)
                
            await conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = $1", order_id)
            
        return web.json_response({
            "success": True,
            "error": None
        })
    except Exception as e:
        logging.error(f"Error cancelling order via API: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=400)

async def handle_get_order_history_api(request):
    """ API для Android: Получение истории заказов """
    try:
        client_id = int(request.match_info['clientId'])
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT o.*, u.username as courier_name 
                FROM orders o 
                LEFT JOIN users u ON o.courier_id = u.user_id 
                WHERE o.client_id = $1 
                ORDER BY o.id DESC LIMIT 50
            """, client_id)
            
        orders = []
        for row in rows:
            orders.append({
                "id": row['id'],
                "cargo_type": row['cargo_type'],
                "lat_a": float(row['lat_a']),
                "lon_a": float(row['lon_a']),
                "lat_b": float(row['lat_b']),
                "lon_b": float(row['lon_b']),
                "phone_sender": row['phone_sender'],
                "phone_receiver": row['phone_receiver'],
                "comment": row['comment'],
                "price": float(row['price']),
                "status": row['status'],
                "courier_id": row['courier_id'],
                "courier_name": row['courier_name'],
                "courier_lat": None,
                "courier_lon": None
            })
            
        return web.json_response({
            "success": True,
            "orders": orders,
            "error": None
        })
    except Exception as e:
        logging.error(f"Error getting order history via API: {e}")
        return web.json_response({
            "success": False,
            "orders": [],
            "error": str(e)
        }, status=400)

async def handle_submit_support_api(request):
    """ API для Android: Отправка тикета в поддержку """
    try:
        data = await request.json()
        client_id = int(data['client_id'])
        name = str(data['name'])
        username = str(data['username'])
        text = str(data['text'])
        
        async with db_pool.acquire() as conn:
            ticket_id = await conn.fetchval("""
                INSERT INTO support_tickets (client_id, name, username, message)
                VALUES ($1, $2, $3, $4)
                RETURNING id
            """, client_id, name, username, text)
            
        # Уведомляем администратора в Telegram с пометкой ЧТО ИЗ ПРИЛОЖЕНИЯ
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✉️ Ответить клиенту", callback_data=f"ticket_reply_{client_id}")]
        ])
        
        admin_text = (
            f"📱 **[СООБЩЕНИЕ ИЗ ПРИЛОЖЕНИЯ]** 📱\n"
            f"📩 **НОВОЕ ОБРАЩЕНИЕ В ПОДДЕРЖКУ!**\n\n"
            f"👤 Отправитель: {name}\n"
            f"🆔 ID клиента: `{client_id}`\n"
            f"📱 Телеграм: @{username if username else 'нет'}\n"
            f"🎫 Тикет: `#{ticket_id}`\n\n"
            f"💬 **Текст:**\n{text}"
        )
        
        try:
            await bot.send_message(ADMIN_ID, admin_text, reply_markup=kb, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Error sending support notification to admin: {e}")
            
        return web.json_response({
            "success": True,
            "ticket_id": ticket_id,
            "error": None
        })
    except Exception as e:
        logging.error(f"Error submitting support via API: {e}")
        return web.json_response({
            "success": False,
            "ticket_id": None,
            "error": str(e)
        }, status=400)

async def handle_get_support_tickets_api(request):
    """ API для Android: Загрузка истории чата поддержки """
    try:
        client_id = int(request.match_info['clientId'])
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM support_tickets 
                WHERE client_id = $1 
                ORDER BY id ASC
            """, client_id)
            
        tickets = []
        for row in rows:
            tickets.append({
                "id": row['id'],
                "client_id": row['client_id'],
                "message": row['message'],
                "reply": row['reply'],
                "status": row['status'],
                "created_at": row['created_at'].strftime('%Y-%m-%d %H:%M:%S') if row['created_at'] else None
            })
            
        return web.json_response({
            "success": True,
            "tickets": tickets,
            "error": None
        })
    except Exception as e:
        logging.error(f"Error getting support tickets via API: {e}")
        return web.json_response({
            "success": False,
            "tickets": [],
            "error": str(e)
        }, status=400)

# --- БАЗОВЫЕ КОМАНДЫ И РЕГИСТРАЦИЯ ---
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="setlang_ru")],
        [InlineKeyboardButton(text="🇲🇩 Română", callback_data="setlang_ro")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="setlang_en")],
        [InlineKeyboardButton(text="🇺🇦 Українська", callback_data="setlang_uk")],
        [InlineKeyboardButton(text="🇲🇩 Moldovenească", callback_data="setlang_mo")]
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
        [InlineKeyboardButton(text=TEXTS[lang].get('client', 'Client'), callback_data="setrole_client")],
        [InlineKeyboardButton(text=TEXTS[lang].get('courier', 'Courier'), callback_data="setrole_courier")]
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

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Одобрить курьера",
                callback_data=f"adm_appr_{message.from_user.id}"
            )],
            [InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"adm_decl_{message.from_user.id}"
            )]
        ]
    )

    username = f"@{message.from_user.username}" if message.from_user.username else "без username"
    caption = f"Новая заявка в курьеры!\nID: `{message.from_user.id}`\nUsername: {username}"

    await bot.send_photo(ADMIN_ID, photo_id, caption=caption, reply_markup=kb, parse_mode="Markdown")
    await message.answer(TEXTS[lang]["wait_admin"])
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

# === ИСПРАВЛЕННАЯ ЛОГИКА ГЕОЛОКАЦИИ ===
@router.message(CreateOrder.addr_a, F.location)
async def process_addr_a(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(lat_a=message.location.latitude, lon_a=message.location.longitude)

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]],
        resize_keyboard=True
    )
    await message.answer(TEXTS[lang]['addr_b'], reply_markup=kb)
    await state.set_state(CreateOrder.addr_b)

@router.message(CreateOrder.addr_b, F.location)
async def process_addr_b(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    await state.update_data(lat_b=message.location.latitude, lon_b=message.location.longitude)

    await message.answer(TEXTS[lang]['phone_sender'], reply_markup=ReplyKeyboardRemove())
    await state.set_state(CreateOrder.phone_sender)

# Защита от отправки текста вместо локации
@router.message(CreateOrder.addr_a)
@router.message(CreateOrder.addr_b)
async def invalid_geo_catch(message: Message):
    lang = await get_lang(message.from_user.id)
    await message.answer(TEXTS[lang]['invalid_geo'])
# ======================================

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

@router.message(CreateOrder.comment, Command("skip"))
async def skip_comment(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    data = await state.get_data()

    dist_km, map_url = await get_osrm_data(data['lat_a'], data['lon_a'], data['lat_b'], data['lon_b'])

    rate = 10 if data['cargo_type'] == 'standard' else 20
    price = round((dist_km * rate) + 40, 2)
    if price < 60: price = 60.0

    comment = "Нет комментария"
    await state.update_data(comment=comment, price=price, map_url=map_url)

    c_type_str = "📦 Стандарт" if data['cargo_type'] == 'standard' else "🚚 Грузовой"
    text = TEXTS[lang]['confirm_title'].format(
        type=c_type_str, p_send=data['phone_sender'], p_recv=data['phone_receiver'],
        comm=comment, price=price
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]['yes'], callback_data="order_confirm_yes")],
        [InlineKeyboardButton(text=TEXTS[lang]['no'], callback_data="order_confirm_no")]
    ])

    await message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(CreateOrder.confirm)

@router.message(CreateOrder.comment)
async def process_comment(message: Message, state: FSMContext):
    lang = await get_lang(message.from_user.id)
    comment = message.text if message.text.lower() != '/skip' else "Нет комментария"
    data = await state.get_data()

    dist_km, map_url = await get_osrm_data(data['lat_a'], data['lon_a'], data['lat_b'], data['lon_b'])

    rate = 10 if data['cargo_type'] == 'standard' else 20
    price = round((dist_km * rate) + 40, 2)
    if price < 60: price = 60.0

    await state.update_data(comment=comment, price=price, map_url=map_url)
    
    c_type_str = "📦 Стандарт" if data['cargo_type'] == 'standard' else "🚚 Грузовой"
    text = TEXTS[lang]['confirm_title'].format(
        type=c_type_str, p_send=data['phone_sender'], p_recv=data['phone_receiver'],
        comm=comment, price=price
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]['yes'], callback_data="order_confirm_yes")],
        [InlineKeyboardButton(text=TEXTS[lang]['no'], callback_data="order_confirm_no")]
    ])
    
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await state.set_state(CreateOrder.confirm)

@router.callback_query(CreateOrder.confirm, F.data == "order_confirm_yes")
async def process_order_confirm_yes(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    data = await state.get_data()
    
    async with db_pool.acquire() as conn:
        order_id = await conn.fetchval("""
            INSERT INTO orders (
                client_id, cargo_type, addr_a, addr_b, lat_a, lon_a, lat_b, lon_b, 
                phone_sender, phone_receiver, comment, price, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'pending')
            RETURNING id
        """, 
        callback.from_user.id, data['cargo_type'], "Точка А (Локация)", "Точка Б (Локация)",
        data['lat_a'], data['lon_a'], data['lat_b'], data['lon_b'],
        data['phone_sender'], data['phone_receiver'], data['comment'], data['price'])
        
        online_couriers = await conn.fetch(
            "SELECT user_id, lang FROM users WHERE role = 'courier' AND is_online = TRUE AND is_approved = TRUE"
        )
        
    await callback.message.edit_text(TEXTS[lang]['order_placed'])
    await state.clear()
    
    c_type_str = "📦 Стандарт" if data['cargo_type'] == 'standard' else "🚚 Грузовой"
    for courier in online_couriers:
        c_lang = courier['lang']
        c_text = (
            f"🆕 **НОВЫЙ ЗАКАЗ #{order_id}!**\n\n"
            f"🔹 Тип: {c_type_str}\n"
            f"💵 Стоимость: `{data['price']:.2f} MDL`\n"
            f"💬 Комментарий: {data['comment']}\n"
        )
        kb_take = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=TEXTS[c_lang]['take_btn'].format(price=f"{data['price']:.2f}"), 
                callback_data=f"order_take_{order_id}"
            )]
        ])
        try:
            await bot.send_message(courier['user_id'], c_text, reply_markup=kb_take, parse_mode="Markdown")
        except Exception as e:
            logging.error(f"Ошибка отправки заказа курьеру {courier['user_id']}: {e}")
            
    await callback.answer()

@router.callback_query(CreateOrder.confirm, F.data == "order_confirm_no")
async def process_order_confirm_no(callback: CallbackQuery, state: FSMContext):
    lang = await get_lang(callback.from_user.id)
    await callback.message.edit_text(TEXTS[lang]['order_cancelled'])
    await state.clear()
    await callback.answer()

# --- ВЕРИФИКАЦИЯ КУРЬЕРОВ АДМИНИСТРАТОРОМ ---
@router.callback_query(F.data.startswith("adm_appr_"))
async def cb_admin_approve_courier(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    target_courier_id = int(callback.data.split("_")[2])
    
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_approved = TRUE WHERE user_id = $1", target_courier_id)
        target_lang = await conn.fetchval("SELECT lang FROM users WHERE user_id = $1", target_courier_id) or 'ru'
        
    await callback.message.edit_caption(caption=f"{callback.message.caption}\n\n✅ **Заявка одобрена админом!**")
    try:
        await bot.send_message(target_courier_id, TEXTS[target_lang]['approved'])
        await bot.send_message(target_courier_id, TEXTS[target_lang]['courier_menu'])
    except Exception: pass
    await callback.answer("Курьер успешно активирован")

@router.callback_query(F.data.startswith("adm_decl_"))
async def cb_admin_decline_courier(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    target_courier_id = int(callback.data.split("_")[2])
    
    await callback.message.edit_caption(caption=f"{callback.message.caption}\n\n❌ **Заявка отклонена админом.**")
    try:
        await bot.send_message(target_courier_id, "⚠️ Ваша заявка на верификацию курьера была отклонена администратором.")
    except Exception: pass
    await callback.answer("Заявка отклонена")

# --- СМЕНЫ И ЗАКАЗЫ КУРЬЕРОВ (/online, /offline, /orders) ---
@router.message(Command("online"))
async def cmd_courier_online(message: Message):
    lang = await get_lang(message.from_user.id)
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT role, is_approved FROM users WHERE user_id = $1", message.from_user.id)
        if not user or user['role'] != 'courier' or not user['is_approved']:
            await message.answer(TEXTS[lang]['not_approved'])
            return
        await conn.execute("UPDATE users SET is_online = TRUE WHERE user_id = $1", message.from_user.id)
    await message.answer("🟢 Вы вышли на смену! Новые заказы будут приходить автоматически.")

@router.message(Command("offline"))
async def cmd_courier_offline(message: Message):
    lang = await get_lang(message.from_user.id)
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_online = FALSE WHERE user_id = $1", message.from_user.id)
    await message.answer("🔴 Вы ушли со смены. Заказы больше не поступают.")

@router.message(Command("orders"))
async def cmd_view_active_orders(message: Message):
    lang = await get_lang(message.from_user.id)
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT role, is_approved FROM users WHERE user_id = $1", message.from_user.id)
        if not user or user['role'] != 'courier' or not user['is_approved']:
            await message.answer(TEXTS[lang]['not_approved'])
            return
        orders = await conn.fetch("SELECT id, cargo_type, price, comment FROM orders WHERE status = 'pending' ORDER BY id ASC LIMIT 5")
        
    if not orders:
        await message.answer(TEXTS[lang]['no_orders'])
        return
        
    for o in orders:
        c_type_str = "📦 Стандарт" if o['cargo_type'] == 'standard' else "🚚 Грузовой"
        text = f"📦 **Заказ #{o['id']}**\n🔹 Тип: {c_type_str}\n💵 Стоимость: `{float(o['price']):.2f} MDL`\n💬 Комм: {o['comment']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=TEXTS[lang]['take_btn'].format(price=f"{o['price']:.2f}"), callback_data=f"order_take_{o['id']}")]
        ])
        await message.answer(text, reply_markup=kb, parse_mode="Markdown")

# --- ТАЙМЕРЫ ПРОСТОЯ И НЕАКТИВНОСТИ (AFK BACKGROUND TASKS) ---
async def start_afk_inactivity_timer(order_id: int, target_status: str, timeout_seconds: int, client_id: int, courier_id: int):
    await asyncio.sleep(timeout_seconds)
    try:
        async with db_pool.acquire() as conn:
            current_status = await conn.fetchval("SELECT status FROM orders WHERE id = $1", order_id)
            if current_status == target_status:
                logging.warning(f"⏳ Таймер AFK сработал! Заказ #{order_id} завис в статусе '{target_status}'.")
                try:
                    c_lang = await conn.fetchval("SELECT lang FROM users WHERE user_id = $1", courier_id) or 'ru'
                    alert_text = "⚠️ Вы слишком долго не обновляли статус выполнения заказа! Пожалуйста, актуализируйте данные."
                    if c_lang == 'ro': alert_text = "⚠️ Nu ați actualizat statusul comenzii de prea mult timp! Vă rugăm să actualizați datele."
                    elif c_lang == 'en': alert_text = "⚠️ You haven't updated the order status for too long! Please update your progress."
                    await bot.send_message(courier_id, alert_text)
                except Exception: pass
                
                try:
                    await bot.send_message(ADMIN_ID, f"🚨 **ВНИМАНИЕ АДМИНА!** Курьер `ID {courier_id}` завис на заказе **#{order_id}** в состоянии `{target_status}` более {timeout_seconds // 60} минут!")
                except Exception: pass
    except Exception as e:
        logging.error(f"Ошибка выполнения AFK таймера для заказа #{order_id}: {e}")
    finally:
        active_afk_tasks.pop(order_id, None)

# --- ОБРАБОТКА ЖИЗНЕННОГО ЦИКЛА ЗАКАЗА КУРЬЕРОМ ---
@router.callback_query(F.data.startswith("order_take_"))
async def cb_courier_take_order(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    order_id = int(callback.data.split("_")[2])

    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT role, is_approved FROM users WHERE user_id = $1", callback.from_user.id)
        if not user or user["role"] != "courier" or not user["is_approved"]:
            await callback.answer("Только одобренный курьер может принять заказ", show_alert=True)
            return

        order = await conn.fetchrow("""
            UPDATE orders SET courier_id = $1, status = 'accepted' WHERE id = $2 AND status = 'pending' RETURNING *
        """, callback.from_user.id, order_id)

    if not order:
        await callback.answer("Заказ уже взят другим курьером", show_alert=True)
        return

    _, map_url = await get_osrm_data(float(order["lat_a"]), float(order["lon_a"]), float(order["lat_b"]), float(order["lon_b"]))

    text = TEXTS[lang]['order_taken'].format(
        p_send=order['phone_sender'], p_recv=order['phone_receiver'], comm=order['comment'], url=map_url
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=TEXTS[lang]['at_a_btn'], callback_data=f"order_ata_{order_id}")]])

    await bot.send_location(callback.from_user.id, latitude=float(order['lat_a']), longitude=float(order['lon_a']))
    await bot.send_location(callback.from_user.id, latitude=float(order['lat_b']), longitude=float(order['lon_b']))
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")

    try:
        await bot.send_message(order['client_id'], f"🤝 Ваш заказ #{order_id} принят курьером!")
    except Exception: pass

    if order_id in active_afk_tasks: active_afk_tasks[order_id].cancel()
    active_afk_tasks[order_id] = asyncio.create_task(start_afk_inactivity_timer(order_id, 'accepted', 600, order['client_id'], callback.from_user.id))
    await callback.answer()

@router.callback_query(F.data.startswith("order_ata_"))
async def cb_courier_at_point_a(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    order_id = int(callback.data.split("_")[2])
    
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE orders SET status = 'at_a' WHERE id = $1", order_id)
        order = await conn.fetchrow("SELECT client_id FROM orders WHERE id = $1", order_id)
        
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=TEXTS[lang]['at_b_btn'], callback_data=f"order_atb_{order_id}")]])
    await callback.message.edit_reply_markup(reply_markup=kb)
    
    try:
        cl_lang = await get_lang(order['client_id'])
        await bot.send_message(order['client_id'], TEXTS[cl_lang]['client_notif_courier_at_a'])
    except Exception: pass

    if order_id in active_afk_tasks: active_afk_tasks[order_id].cancel()
    task = asyncio.create_task(start_afk_inactivity_timer(order_id, 'at_a', 2400, order['client_id'], callback.from_user.id))
    active_afk_tasks[order_id] = task
    await callback.answer()

@router.callback_query(F.data.startswith("order_atb_"))
async def cb_courier_at_point_b(callback: CallbackQuery):
    lang = await get_lang(callback.from_user.id)
    order_id = int(callback.data.split("_")[2])
    
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE orders SET status = 'at_b' WHERE id = $1", order_id)
        order = await conn.fetchrow("SELECT client_id FROM orders WHERE id = $1", order_id)
        
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=TEXTS[lang]['done_btn'], callback_data=f"order_done_{order_id}")]])
    await callback.message.edit_reply_markup(reply_markup=kb)
    
    try:
        cl_lang = await get_lang(order['client_id'])
        await bot.send_message(order['client_id'], TEXTS[cl_lang]['client_notif_courier_at_b'])
    except Exception: pass
    
    if order_id in active_afk_tasks: active_afk_tasks[order_id].cancel()
    await callback.answer()

@router.callback_query(F.data.startswith("order_done_"))
async def cb_courier_complete_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE orders SET status = 'completed' WHERE id = $1", order_id)
        order = await conn.fetchrow("SELECT client_id, price FROM orders WHERE id = $1", order_id)
        
    await callback.message.edit_text(f"💵 **Заказ #{order_id} успешно завершен!** Сумма `{float(order['price']):.2f} MDL` добавлена в вашу статистику.", parse_mode="Markdown")
    
    try:
        await bot.send_message(order['client_id'], "🎉 Ваш заказ успешно доставлен! Спасибо, что выбрали наш сервис!")
    except Exception: pass
    
    if order_id in active_afk_tasks:
        active_afk_tasks[order_id].cancel()
        active_afk_tasks.pop(order_id, None)
        
    await callback.answer()

# --- НАСТРОЙКА КОМАНД БОТА ---
async def set_bot_commands(bot: Bot):
    commands_en = [
        BotCommand(command="start", description="Start"),
        BotCommand(command="order", description="Create order"),
        BotCommand(command="cancel", description="Cancel order"),
        BotCommand(command="support", description="Support"),
        BotCommand(command="online", description="Go online"),
        BotCommand(command="offline", description="Go offline"),
        BotCommand(command="orders", description="Available orders"),
        BotCommand(command="history", description="History & Earnings"),
        BotCommand(command="verify", description="Bind mobile app")
    ]
    
    lang_commands = {
        "ru": [
            BotCommand(command="start", description="Запуск"),
            BotCommand(command="order", description="Создать заказ"),
            BotCommand(command="cancel", description="Отмена заказа"),
            BotCommand(command="support", description="Техподдержка"),
            BotCommand(command="online", description="Начать смену"),
            BotCommand(command="offline", description="Закончить смену"),
            BotCommand(command="orders", description="Доступные заказы"),
            BotCommand(command="history", description="Статистика и доход"),
            BotCommand(command="verify", description="Привязать приложение")
        ],
        "ro": [
            BotCommand(command="start", description="Pornire"),
            BotCommand(command="order", description="Creare comandă"),
            BotCommand(command="cancel", description="Anulare"),
            BotCommand(command="support", description="Suport tehnic"),
            BotCommand(command="online", description="Intrare pe tură"),
            BotCommand(command="offline", description="Ieșire din tură"),
            BotCommand(command="orders", description="Comenzi disponibile"),
            BotCommand(command="history", description="Istoric și câștiguri"),
            BotCommand(command="verify", description="Conectați aplicația")
        ],
        "mo": [
            BotCommand(command="start", description="Pornire"),
            BotCommand(command="order", description="Creare comandă"),
            BotCommand(command="cancel", description="Anulare"),
            BotCommand(command="support", description="Suport tehnic"),
            BotCommand(command="online", description="Intrare pe tură"),
            BotCommand(command="offline", description="Ieșire din tură"),
            BotCommand(command="orders", description="Comenzi disponibile"),
            BotCommand(command="history", description="Istoric și câștiguri"),
            BotCommand(command="verify", description="Conectați aplicația")
        ],
        "uk": [
            BotCommand(command="start", description="Запуск"),
            BotCommand(command="order", description="Створити замовлення"),
            BotCommand(command="cancel", description="Скасувати замовлення"),
            BotCommand(command="support", description="Підтримка"),
            BotCommand(command="online", description="Почати зміну"),
            BotCommand(command="offline", description="Закінчити зміну"),
            BotCommand(command="orders", description="Доступні замовлення"),
            BotCommand(command="history", description="Статистика та дохід"),
            BotCommand(command="verify", description="Прив'язати додаток")
        ]
    }
    
    try:
        await bot.set_my_commands(commands_en)
    except Exception as e:
        logging.error(f"Failed to set default commands: {e}")
        
    for lang, cmds in lang_commands.items():
        try:
            await bot.set_my_commands(cmds, language_code=lang)
        except Exception as e:
            logging.error(f"Failed to set commands for language {lang}: {e}")

# --- СТАРТ СЕРВЕРА С API И BOT ---
async def main():
    await init_db()
    await set_bot_commands(bot)

    app = web.Application()
    
    # Регистрация REST API роутов для работы Android-приложения
    app.router.add_get("/", handle_ping)
    app.router.add_get("/api/app-update", handle_app_update_api)
    app.router.add_get("/api/download-apk", handle_download_apk_api)
    app.router.add_get("/admin/upload", handle_admin_panel)
    app.router.add_post("/admin/upload", handle_admin_upload)
    app.router.add_post("/api/verify", handle_verify_api)  # Метод проверки 6-значного кода
    app.router.add_post("/api/delete-account/{profileId}", handle_delete_account_api) # Метод удаления профиля
    app.router.add_post("/api/orders", handle_create_order_api)
    app.router.add_get("/api/orders/active/{clientId}", handle_get_active_order_api)
    app.router.add_post("/api/orders/{id}/cancel", handle_cancel_order_api)
    app.router.add_get("/api/orders/history/{clientId}", handle_get_order_history_api)
    app.router.add_post("/api/support", handle_submit_support_api)
    app.router.add_get("/api/support/{clientId}", handle_get_support_tickets_api)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    logging.info(f"Bot + Web server with Android Rest API successfully started on port {PORT}")

    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
