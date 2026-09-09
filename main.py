import os
import html
from datetime import datetime, timedelta
from threading import Thread
from zoneinfo import ZoneInfo
from flask import Flask
from telebot import TeleBot, types
from apscheduler.schedulers.background import BackgroundScheduler
import psycopg2
from psycopg2.extras import RealDictCursor

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8657040766:AAHeBxOmF86zv__MaIzayHuoOoZ5B7ycSeo")
DOCTOR_CHAT_ID = int(os.getenv("DOCTOR_CHAT_ID", "427415684"))
TZ = ZoneInfo("Asia/Tashkent")

# Строка подключения к Supabase PostgreSQL
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://postgres:ponto1-Fehhum-jaqcyx@db.ayrnqffncsaglfwmcgdu.supabase.co:5432/postgres"
)

bot = TeleBot(BOT_TOKEN)
app = Flask('')

user_data = {}

# --- FLASK ДЛЯ KEEP-ALIVE ---
@app.route('/')
def home():
    return "Dr. Maruf's Dentistry Bot is active!"

def run_flask():
    app.run(host='0.0.0.0', port=10000)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

# --- БАЗА ДАННЫХ (SUPABASE POSTGRESQL) ---
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS appointments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                patient_name TEXT,
                phone_number TEXT,
                username TEXT,
                service TEXT DEFAULT 'Консультация',
                problem TEXT,
                appointment_time TEXT,
                status TEXT DEFAULT 'active',
                reminded_24h INTEGER DEFAULT 0,
                reminded_2h INTEGER DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                rating INTEGER,
                comment TEXT,
                created_at TEXT
            )
        ''')
        conn.commit()
    except Exception as e:
        print(f"Ошибка инициализации БД: {e}")
    finally:
        cursor.close()
        conn.close()

def get_booked_times(date_str):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT appointment_time FROM appointments WHERE status='active' AND appointment_time LIKE %s",
            (f"{date_str}%",)
        )
        rows = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    return [r['appointment_time'].split()[1] for r in rows if len(r['appointment_time'].split()) > 1]

# --- КЛАВИАТУРЫ ---
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    markup.row("📅 Записаться на приём", "📋 Мои записи")
    markup.row("🩺 Услуги и лечение", "📍 Как нас найти")
    markup.row("⭐ Оценить лечение / Отзыв", "ℹ️ Информация")
    return markup

def get_doctor_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    markup.row("📋 Панель врача", "📊 Статистика")
    markup.row("📱 Главное меню клиента")
    return markup

# --- ГЛАВНЫЙ УНИВЕРСАЛЬНЫЙ ОБРАБОТЧИК КНОПОК МЕНЮ ---
@bot.message_handler(func=lambda message: message.text and any(keyword in message.text for keyword in [
    "Записаться на приём", "Мои записи", "Услуги и лечение", 
    "Как нас найти", "Оценить лечение", "Отзыв", "Информация", 
    "Статистика", "Панель врача", "Главное меню клиента"
]))
def handle_menu_router(message):
    chat_id = message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    user_data.pop(chat_id, None)

    text = message.text
    if "Записаться на приём" in text:
        start_booking_button(message)
    elif "Мои записи" in text:
        show_my_appointments(message)
    elif "Услуги и лечение" in text:
        services_info(message)
    elif "Как нас найти" in text:
        send_location(message)
    elif "Оценить лечение" in text or "Отзыв" in text:
        ask_rating(message)
    elif "Информация" in text:
        clinic_info(message)
    elif "Статистика" in text:
        show_statistics(message)
    elif "Панель врача" in text:
        doctor_panel_menu(message)
    elif "Главное меню клиента" in text:
        show_client_menu(message)

# --- СТАРТ ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    user_data.pop(chat_id, None)
    
    if chat_id == DOCTOR_CHAT_ID:
        bot.send_message(chat_id, "👨‍⚕️ Здравствуйте, доктор Маруф! Панель врача готова.", reply_markup=get_doctor_keyboard())
        return

    welcome_text = (
        "Здравствуйте! Вас приветствует бот стоматологической клиники доктора Маруфа. 🦷\n\n"
        "Используйте меню ниже для записи или получения информации."
    )
    bot.send_message(chat_id, welcome_text, reply_markup=get_main_keyboard())

def show_client_menu(message):
    bot.send_message(message.chat.id, "Переключено на меню клиента:", reply_markup=get_main_keyboard())

def services_info(message):
    text = (
        "🏥 <b>Услуги клиники Stoma dent:</b>\n\n"
        "• Лечение кариеса и пульпита\n"
        "• Профессиональная гигиена и чистка\n"
        "• Протезирование и установка коронок\n"
        "• Удаление зубов любой сложности\n"
        "• Эстетическая стоматология и отбеливание\n"
        "• Противовоспалительное лечение\n\n"
        "Нажмите «📅 Записаться на приём», чтобы выбрать удобное время!"
    )
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(), parse_mode="HTML")

def clinic_info(message):
    text = (
        "👨‍⚕️ Стоматологическая клиника Stoma dent (доктор Маруф)\n\n"
        "📍 Адрес: г. Ташкент, Яшнабадский район, 1-й квартал Авиасозлар, 12\n"
        "🚇 Ориентир: метро Тузель (1-й этаж)\n"
        "⏰ Режим работы: Ежедневно с 09:00 до 19:00\n"
        "📞 Телефон: +998 (93) 508-11-88"
    )
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard())

def send_location(message):
    chat_id = message.chat.id
    bot.send_message(
        chat_id, 
        "📍 Наша клиника Stoma dent находится по адресу:\n"
        "г. Ташкент, Яшнабадский район, 1-й квартал Авиасозлар, 12"
    )
    bot.send_location(chat_id, latitude=41.295246, longitude=69.338661)

# --- ПРОЦЕСС ЗАПИСИ ---
def start_booking_button(message):
    chat_id = message.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    user_data[chat_id] = {}

    markup = types.InlineKeyboardMarkup()
    services = [
        "🦷 Лечение зуба", "✨ Чистка", "😁 Отбеливание", 
        "👑 Коронка", "❌ Удаление", "💊 Противовоспалительное", "❓ Другое"
    ]
    
    for i in range(0, len(services), 2):
        row = [types.InlineKeyboardButton(services[i], callback_data=f"srv_{services[i]}")]
        if i + 1 < len(services):
            row.append(types.InlineKeyboardButton(services[i+1], callback_data=f"srv_{services[i+1]}"))
        markup.row(*row)

    bot.send_message(chat_id, "Выберите интересующую вас услугу:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("srv_"))
def process_service_choice(call):
    service_name = call.data.replace("srv_", "")
    chat_id = call.message.chat.id
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]["service"] = service_name
    bot.answer_callback_query(call.id)
    start_date_selection(chat_id, call.message.message_id)

def start_date_selection(chat_id, message_id=None):
    markup = types.InlineKeyboardMarkup()
    today = datetime.now(TZ)
    days_added = 0
    current_day = today

    while days_added < 5:
        current_day += timedelta(days=1)
        if current_day.weekday() == 6:
            continue
        
        days_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        months_ru = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        
        day_str = f"{days_ru[current_day.weekday()]}, {current_day.day} {months_ru[current_day.month-1]}"
        date_val = current_day.strftime("%d.%m.%Y")
        
        markup.add(types.InlineKeyboardButton(f"📅 {day_str}", callback_data=f"date_{date_val}"))
        days_added += 1

    if message_id:
        try:
            bot.edit_message_text("Выберите дату для визита:", chat_id=chat_id, message_id=message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, "Выберите дату для визита:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("date_"))
def choose_time(call):
    selected_date = call.data.split("_")[1]
    chat_id = call.message.chat.id
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]["date"] = selected_date
    bot.answer_callback_query(call.id)

    all_times = ["09:00", "10:30", "12:00", "14:00", "15:30", "17:00"]
    booked_times = get_booked_times(selected_date)
    available_times = [t for t in all_times if t not in booked_times]

    if not available_times:
        bot.edit_message_text(
            f"На дату {selected_date} свободных мест нет. Пожалуйста, выберите другую дату.",
            chat_id=chat_id,
            message_id=call.message.message_id
        )
        return

    markup = types.InlineKeyboardMarkup()
    row = []
    for t in available_times:
        row.append(types.InlineKeyboardButton(t, callback_data=f"time_{t}"))
        if len(row) == 2:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)

    bot.edit_message_text(
        f"Выбранная дата: {selected_date}\nДоступное время:",
        chat_id=chat_id,
        message_id=call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("time_"))
def ask_name(call):
    selected_time = call.data.split("_")[1]
    chat_id = call.message.chat.id
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]["time"] = selected_time

    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass

    msg = bot.send_message(chat_id, "Введите ваше ФИО (Имя и Фамилию):", reply_markup=get_main_keyboard())
    bot.register_next_step_handler(msg, process_name)

def process_name(message):
    chat_id = message.chat.id
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]["name"] = message.text

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📞 Отправить номер телефона", request_contact=True))

    msg = bot.send_message(chat_id, "Отправьте ваш номер телефона кнопкой ниже или введите текстом:", reply_markup=markup)
    bot.register_next_step_handler(msg, process_phone)

def process_phone(message):
    chat_id = message.chat.id
    phone = message.contact.phone_number if message.contact else message.text
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]["phone"] = phone

    msg = bot.send_message(chat_id, "Опишите вашу жалобу или причину визита:", reply_markup=get_main_keyboard())
    bot.register_next_step_handler(msg, process_problem)

def process_problem(message):
    chat_id = message.chat.id
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]["problem"] = message.text
    data = user_data[chat_id]

    text = (
        "📋 <b>ПРОВЕРЬТЕ ДАННЫЕ:</b>\n\n"
        f"👤 Имя: {html.escape(data.get('name', ''))}\n"
        f"📞 Телефон: {html.escape(data.get('phone', ''))}\n"
        f"📅 Дата: {data.get('date')}\n"
        f"⏰ Время: {data.get('time')}\n"
        f"🦷 Услуга: {html.escape(data.get('service', 'Консультация'))}\n"
        f"💬 Жалоба: {html.escape(data.get('problem', ''))}\n\n"
        "Всё верно?"
    )

    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_booking"),
        types.InlineKeyboardButton("❌ Отменить", callback_data="cancel_booking_process")
    )
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data in ["confirm_booking", "cancel_booking_process"])
def finalize_booking(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)

    if call.data == "cancel_booking_process":
        bot.edit_message_text("❌ Запись отменена.", chat_id=chat_id, message_id=call.message.message_id)
        user_data.pop(chat_id, None)
        return

    data = user_data.get(chat_id, {})
    if not data:
        bot.send_message(chat_id, "Ошибка сессии. Пожалуйста, начните запись заново.", reply_markup=get_main_keyboard())
        return

    app_time_str = f"{data['date']} {data['time']}"

    if data['time'] in get_booked_times(data['date']):
        bot.send_message(chat_id, "⚠️ Извините, это время только что заняли! Выберите другое время.", reply_markup=get_main_keyboard())
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO appointments (user_id, patient_name, phone_number, username, service, problem, appointment_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (chat_id, data['name'], data['phone'], call.from_user.username or "", data.get('service', 'Консультация'), data['problem'], app_time_str))
        app_id = cursor.fetchone()['id']
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    bot.edit_message_text(
        f"✅ Вы успешно записаны!\n\n👤 Имя: {data['name']}\n📅 Дата и время: {app_time_str}\n🩺 Услуга: {data.get('service')}\n\nМы ждём вас!",
        chat_id=chat_id,
        message_id=call.message.message_id
    )

    user_link = f"@{call.from_user.username}" if call.from_user.username else "Не указан"
    doctor_msg = (
        f"🆕 <b>НОВАЯ ЗАПИСЬ №{app_id}!</b>\n\n"
        f"👤 Пациент: {html.escape(data['name'])}\n"
        f"📞 Телефон: {html.escape(data['phone'])}\n"
        f"💬 Telegram: {user_link}\n"
        f"⏰ Время: {app_time_str}\n"
        f"🦷 Услуга: {html.escape(data.get('service', 'Консультация'))}\n"
        f"🩺 Жалоба: {html.escape(data['problem'])}"
    )
    
    markup = types.InlineKeyboardMarkup()
    if call.from_user.username:
        markup.add(types.InlineKeyboardButton("💬 Написать клиенту", url=f"https://t.me/{call.from_user.username}"))
    markup.add(types.InlineKeyboardButton("❌ Отменить запись", callback_data=f"cancel_{app_id}"))

    try:
        bot.send_message(DOCTOR_CHAT_ID, doctor_msg, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка отправки врачу: {e}")

    user_data.pop(chat_id, None)

# --- МОИ ЗАПИСИ ---
def show_my_appointments(message):
    chat_id = message.chat.id
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, appointment_time, service FROM appointments WHERE user_id=%s AND status='active' ORDER BY id DESC",
            (chat_id,)
        )
        records = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    if not records:
        bot.send_message(chat_id, "У вас нет активных записей.", reply_markup=get_main_keyboard())
        return

    bot.send_message(chat_id, "📋 <b>Ваши активные записи:</b>", parse_mode="HTML")
    for row in records:
        app_id, app_time, service = row['id'], row['appointment_time'], row['service']
        text = f"🗓 Дата: {app_time}\n🦷 Услуга: {service}\n👨‍⚕️ Доктор Маруф"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ Отменить запись", callback_data=f"usercancel_{app_id}"))
        bot.send_message(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('usercancel_'))
def handle_user_cancel(call):
    app_id = call.data.split('_')[1]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT appointment_time FROM appointments WHERE id=%s AND user_id=%s", (app_id, call.message.chat.id))
        row = cursor.fetchone()
        app_time_val = row['appointment_time'] if row else "неизвестно"

        cursor.execute("UPDATE appointments SET status='cancelled' WHERE id=%s AND user_id=%s", (app_id, call.message.chat.id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    bot.answer_callback_query(call.id, "Запись отменена.")
    bot.edit_message_text("❌ Запись отменена.", chat_id=call.message.chat.id, message_id=call.message.message_id)
    
    try:
        bot.send_message(
            DOCTOR_CHAT_ID, 
            f"⚠️ <b>Пациент отменил запись №{app_id}!</b>\n🗓 Время: {app_time_val}\n🟢 <b>Свободное время доступно.</b>", 
            parse_mode="HTML"
        )
    except Exception:
        pass

# --- ОТЗЫВЫ ---
def ask_rating(message):
    markup = types.InlineKeyboardMarkup()
    buttons = [types.InlineKeyboardButton(f"⭐ {i}", callback_data=f"rate_{i}") for i in range(1, 6)]
    markup.row(buttons[0], buttons[1], buttons[2])
    markup.row(buttons[3], buttons[4])
    bot.send_message(message.chat.id, "Пожалуйста, оцените качество лечения и обслуживания от 1 до 5:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("rate_"))
def process_rating_stars(call):
    is_after_visit = "rate_after_" in call.data
    stars = call.data.replace("rate_after_", "").replace("rate_", "")

    chat_id = call.message.chat.id
    user_data[chat_id] = {
        "rating_val": int(stars),
        "rating": "⭐" * int(stars),
        "is_after_visit": is_after_visit,
        "awaiting_comment": True
    }

    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏩ Пропустить (Закрыть)", callback_data="skip_comment"))

    bot.edit_message_text(
        f"Оценка принята: {'⭐' * int(stars)}\n\nНапишите ваше впечатление или что вам понравилось:",
        chat_id=chat_id,
        message_id=call.message.message_id,
        reply_markup=markup
    )
    bot.register_next_step_handler(call.message, save_comment_step)

@bot.callback_query_handler(func=lambda call: call.data == "skip_comment")
def skip_comment_callback(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    bot.clear_step_handler_by_chat_id(chat_id)
    
    data = user_data.get(chat_id, {})
    rating_val = data.get("rating_val", 5)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO reviews (user_id, rating, comment, created_at) VALUES (%s, %s, %s, %s)",
                       (chat_id, rating_val, "", datetime.now(TZ).strftime("%Y-%m-%d %H:%M")))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    user_data.pop(chat_id, None)
    bot.edit_message_text("Спасибо за отзыв! ❤️ Хорошего дня!", chat_id=chat_id, message_id=call.message.message_id)

def save_comment_step(message):
    chat_id = message.chat.id
    data = user_data.get(chat_id, {})
    if not data.get("awaiting_comment"):
        return

    comment_text = message.text
    rating_val = data.get("rating_val", 5)
    rating = data.get("rating", "⭐5")

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO reviews (user_id, rating, comment, created_at) VALUES (%s, %s, %s, %s)",
                       (chat_id, rating_val, comment_text, datetime.now(TZ).strftime("%Y-%m-%d %H:%M")))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    user_data.pop(chat_id, None)
    bot.send_message(chat_id, "Спасибо за ваш отзыв! ❤️", reply_markup=get_main_keyboard())

    try:
        bot.send_message(
            DOCTOR_CHAT_ID, 
            f"<b>🌟 НОВЫЙ ОТЗЫВ!</b>\n\n👤 От: {html.escape(message.from_user.first_name)}\n⭐ Оценка: {rating}\n💬 Комментарий: {html.escape(comment_text)}", 
            parse_mode="HTML"
        )
    except Exception:
        pass

# --- ПАНЕЛЬ ВРАЧА И РАСШИРЕННАЯ СТАТИСТИКА ---
def doctor_panel_menu(message):
    if message.chat.id != DOCTOR_CHAT_ID:
        return
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("📅 На сегодня", callback_data="doc_period_today"),
        types.InlineKeyboardButton("📆 На завтра", callback_data="doc_period_tomorrow")
    )
    markup.row(types.InlineKeyboardButton("📊 На всю неделю", callback_data="doc_period_week"))
    bot.send_message(message.chat.id, "👨‍⚕️ <b>Панель врача:</b>", reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("doc_period_"))
def show_doctor_period_appointments(call):
    if call.message.chat.id != DOCTOR_CHAT_ID:
        return
    period = call.data.replace("doc_period_", "")
    bot.answer_callback_query(call.id)
    now = datetime.now(TZ)
    
    if period == "today":
        target_str = now.strftime("%d.%m.%Y")
        title = f"📅 Записи на сегодня ({target_str}):"
    elif period == "tomorrow":
        target_str = (now + timedelta(days=1)).strftime("%d.%m.%Y")
        title = f"📆 Записи на завтра ({target_str}):"
    else:
        title = "📊 Записи на всю неделю:"

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if period in ["today", "tomorrow"]:
            cursor.execute("SELECT id, patient_name, phone_number, service, problem, appointment_time FROM appointments WHERE status='active' AND appointment_time LIKE %s ORDER BY appointment_time ASC", (f"{target_str}%",))
        else:
            cursor.execute("SELECT id, patient_name, phone_number, service, problem, appointment_time FROM appointments WHERE status='active' ORDER BY appointment_time ASC")
        records = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    if not records:
        bot.edit_message_text(f"{title}\n\n📭 Активных записей нет.", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML")
        return

    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, f"<b>{title}</b>", parse_mode="HTML")
    
    for row in records:
        app_id, name, phone, service, problem, app_time = row['id'], row['patient_name'], row['phone_number'], row['service'], row['problem'], row['appointment_time']
        card = f"🆔 <b>Запись №{app_id}</b>\n👤 {html.escape(name)}\n📞 {phone}\n⏰ {app_time}\n🦷 {service}\n💬 {problem}"
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ Пришёл", callback_data=f"status_completed_{app_id}"),
            types.InlineKeyboardButton("❌ Не пришёл", callback_data=f"status_noshow_{app_id}")
        )
        markup.row(types.InlineKeyboardButton("❌ Отменить запись", callback_data=f"cancel_{app_id}"))
        bot.send_message(call.message.chat.id, card, reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith('status_'))
def handle_status_change(call):
    if call.message.chat.id != DOCTOR_CHAT_ID:
        return
    parts = call.data.split('_')
    status, app_id = parts[1], parts[2]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id, patient_name FROM appointments WHERE id=%s", (app_id,))
        row = cursor.fetchone()
        cursor.execute("UPDATE appointments SET status=%s WHERE id=%s", (status, app_id))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    bot.answer_callback_query(call.id, "Статус обновлен!")
    bot.edit_message_text(f"Запись №{app_id}\n\n<b>Статус обновлен</b>", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML")

    if status == "completed" and row:
        try:
            markup = types.InlineKeyboardMarkup()
            buttons = [types.InlineKeyboardButton(f"⭐ {i}", callback_data=f"rate_after_{i}") for i in range(1, 6)]
            markup.row(buttons[0], buttons[1], buttons[2])
            markup.row(buttons[3], buttons[4])
            bot.send_message(row['user_id'], f"Здравствуйте, {row['patient_name']}! Пожалуйста, оцените качество лечения:", reply_markup=markup)
        except Exception:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_'))
def handle_cancel_doctor(call):
    if call.message.chat.id != DOCTOR_CHAT_ID:
        return
    app_id = call.data.split('_')[1]
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT user_id, patient_name, appointment_time FROM appointments WHERE id=%s", (app_id,))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE appointments SET status='cancelled' WHERE id=%s", (app_id,))
            conn.commit()
            try:
                bot.send_message(row['user_id'], f"⚠️ Ваша запись на {row['appointment_time']} отменена клиникой.")
            except Exception:
                pass
            bot.edit_message_text(f"❌ Запись №{app_id} отменена.", chat_id=call.message.chat.id, message_id=call.message.message_id)
    finally:
        cursor.close()
        conn.close()

def show_statistics(message):
    if message.chat.id != DOCTOR_CHAT_ID:
        return
    try:
        now = datetime.now(TZ)
        current_month_str = now.strftime("%m.%Y")

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # 1. Всего пациентов (уникальных)
            cursor.execute("SELECT COUNT(DISTINCT user_id) as cnt FROM appointments")
            total_patients = cursor.fetchone()['cnt'] or 0

            # 2. Записи за текущий месяц
            cursor.execute("SELECT COUNT(*) as cnt FROM appointments WHERE appointment_time LIKE %s", (f"%{current_month_str}%",))
            month_appointments = cursor.fetchone()['cnt'] or 0

            # 3. Статусы
            cursor.execute("SELECT COUNT(*) as cnt FROM appointments WHERE status='completed'")
            completed_count = cursor.fetchone()['cnt'] or 0

            cursor.execute("SELECT COUNT(*) as cnt FROM appointments WHERE status='noshow'")
            noshow_count = cursor.fetchone()['cnt'] or 0

            cursor.execute("SELECT COUNT(*) as cnt FROM appointments WHERE status='cancelled'")
            cancelled_count = cursor.fetchone()['cnt'] or 0

            # 4. Процент явок
            total_finished = completed_count + noshow_count
            attendance_rate = round((completed_count / total_finished * 100), 1) if total_finished > 0 else 0.0

            # 5. Средняя оценка и отзывы
            cursor.execute("SELECT AVG(rating) as avg_r, COUNT(*) as cnt FROM reviews")
            rev = cursor.fetchone()
            avg_rating = round(rev['avg_r'], 1) if rev and rev['avg_r'] else 0.0
            total_reviews = rev['cnt'] if rev else 0

            # 6. Самые популярные услуги
            cursor.execute("SELECT service, COUNT(*) as cnt FROM appointments GROUP BY service ORDER BY cnt DESC LIMIT 3")
            top_services = cursor.fetchall()

            # 7. Ближайшие записи по дням (на ближайшие 3 дня)
            upcoming_days_text = ""
            for i in range(3):
                target_date = now + timedelta(days=i)
                d_str = target_date.strftime("%d.%m.%Y")
                d_label = "Сегодня" if i == 0 else ("Завтра" if i == 1 else target_date.strftime("%d.%m"))
                
                cursor.execute("SELECT COUNT(*) as cnt FROM appointments WHERE status='active' AND appointment_time LIKE %s", (f"{d_str}%",))
                cnt_day = cursor.fetchone()['cnt'] or 0
                upcoming_days_text += f"• {d_label} ({d_str}): <b>{cnt_day}</b> заявок\n"
        finally:
            cursor.close()
            conn.close()

        services_text = ""
        if top_services:
            for row in top_services:
                services_text += f"  - {row['service']}: {row['cnt']} раз(а)\n"
        else:
            services_text = "  - Пока нет данных\n"

        stats = (
            f"📊 <b>РАСШИРЕННАЯ СТАТИСТИКА КЛИНИКИ</b>\n\n"
            f"👥 Всего уникальных пациентов: <b>{total_patients}</b>\n"
            f"📆 Записей за текущий месяц: <b>{month_appointments}</b>\n\n"
            f"<b>Статистика визитов:</b>\n"
            f"  ✅ Пришёл (успешно): <b>{completed_count}</b>\n"
            f"  ❌ Не пришёл: <b>{noshow_count}</b>\n"
            f"  🚫 Отменено: <b>{cancelled_count}</b>\n"
            f"  📈 Процент явок: <b>{attendance_rate}%</b>\n\n"
            f"⭐ Средняя оценка: <b>{avg_rating} / 5</b> (отзывов: {total_reviews})\n\n"
            f"🦷 <b>Топ услуг:</b>\n{services_text}\n"
            f"📅 <b>Ближайшие записи по дням:</b>\n{upcoming_days_text}"
        )
        
        bot.send_message(message.chat.id, stats, parse_mode="HTML")
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка при подсчете статистики: {e}")

# --- НАПОМИНАНИЯ ---
def check_and_send_reminders():
    now = datetime.now(TZ)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, user_id, appointment_time, reminded_24h FROM appointments WHERE status='active'")
        records = cursor.fetchall()
        for row in records:
            app_id, user_id, app_time_str, r24 = row['id'], row['user_id'], row['appointment_time'], row['reminded_24h']
            try:
                app_dt = datetime.strptime(app_time_str, "%d.%m.%Y %H:%M").replace(tzinfo=TZ)
                diff = app_dt - now
                if timedelta(hours=23) <= diff <= timedelta(hours=25) and not r24:
                    bot.send_message(user_id, f"🦷 Напоминаем: у вас завтра визит в клинику в {app_dt.strftime('%H:%M')}.")
                    cursor.execute("UPDATE appointments SET reminded_24h = 1 WHERE id = %s", (app_id,))
            except ValueError:
                continue
        conn.commit()
    finally:
        cursor.close()
        conn.close()

# --- ЗАПУСК ---
if __name__ == '__main__':
    init_db()
    keep_alive()

    scheduler = BackgroundScheduler(timezone=TZ)
    scheduler.add_job(check_and_send_reminders, 'interval', minutes=15)
    scheduler.start()

    print("Бот запущен с поддержкой Supabase PostgreSQL!")
    bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
