import os
import sqlite3
import html
from datetime import datetime, timedelta
from threading import Thread
from zoneinfo import ZoneInfo
from flask import Flask
from telebot import TeleBot, types
from apscheduler.schedulers.background import BackgroundScheduler

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8657040766:AAHeBxOmF86zv__MaIzayHuoOoZ5B7ycSeo")
DOCTOR_CHAT_ID = int(os.getenv("DOCTOR_CHAT_ID", "934720885"))
TZ = ZoneInfo("Asia/Tashkent")

bot = TeleBot(BOT_TOKEN)
app = Flask('')

user_data = {}

MAIN_MENU_BUTTONS = [
    "📅 Записаться на приём", "📋 Мои записи",
    "🩺 Услуги и лечение", "📍 Как нас найти",
    "⭐ Оценить лечение / Отзыв", "ℹ️ Информация",
    "📋 Панель врача", "📊 Статистика", "📱 Главное меню клиента"
]

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

# --- БАЗА ДАННЫХ ---
def get_db_connection():
    conn = sqlite3.connect('dentistry.db', timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                rating INTEGER,
                comment TEXT,
                created_at TEXT
            )
        ''')
        conn.commit()

def get_booked_times(date_str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT appointment_time FROM appointments WHERE status='active' AND appointment_time LIKE ?",
            (f"{date_str}%",)
        )
        rows = cursor.fetchall()
    return [r[0].split()[1] for r in rows if len(r[0].split()) > 1]

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

# --- ЗАЩИТА ОТ ЛОЖНЫХ СРАБАТЫВАНИЙ ШАГОВ ---
def check_menu_interruption(message):
    if message.text in MAIN_MENU_BUTTONS:
        user_data.pop(message.chat.id, None)
        if message.text == "🩺 Услуги и лечение":
            services_info(message)
        elif message.text == "ℹ️ Информация":
            clinic_info(message)
        elif message.text == "📍 Как нас найти":
            send_location(message)
        elif message.text == "⭐ Оценить лечение / Отзыв":
            ask_rating(message)
        elif message.text == "📋 Мои записи":
            show_my_appointments(message)
        elif message.text == "📅 Записаться на приём":
            start_booking_button(message)
        elif message.text == "📊 Статистика":
            show_statistics(message)
        elif message.text == "📋 Панель врача":
            doctor_panel_menu(message)
        elif message.text == "📱 Главное меню клиента":
            show_client_menu(message)
        return True
    return False

# --- СТАРТ И НАВИГАЦИЯ ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = message.chat.id
    user_data.pop(chat_id, None)
    if chat_id == DOCTOR_CHAT_ID:
        bot.send_message(chat_id, "👨‍⚕️ Здравствуйте, доктор Маруф! Панель врача готова.", reply_markup=get_doctor_keyboard())
        return

    welcome_text = (
        "Здравствуйте! Вас приветствует бот стоматологической клиники доктора Маруфа. 🦷\n\n"
        "Используйте меню ниже для записи или получения информации."
    )
    bot.send_message(chat_id, welcome_text, reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "📱 Главное меню клиента")
def show_client_menu(message):
    user_data.pop(message.chat.id, None)
    bot.send_message(message.chat.id, "Переключено на меню клиента:", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "🩺 Услуги и лечение")
def services_info(message):
    user_data.pop(message.chat.id, None)
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

@bot.message_handler(func=lambda message: message.text == "ℹ️ Информация")
def clinic_info(message):
    user_data.pop(message.chat.id, None)
    text = (
        "👨‍⚕️ Стоматологическая клиника Stoma dent (доктор Маруф)\n\n"
        "📍 Адрес: г. Ташкент, Яшнабадский район, 1-й квартал Авиасозлар, 12\n"
        "🚇 Ориентир: метро Тузель (1-й этаж)\n"
        "⏰ Режим работы: Ежедневно с 09:00 до 19:00\n"
        "📞 Телефон для связи: +998 (93) 508-11-88, +998 (90) 175-43-68\n\n"
        "Заботьтесь о своей улыбке вовремя!"
    )
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "📍 Как нас найти")
def send_location(message):
    user_data.pop(message.chat.id, None)
    chat_id = message.chat.id
    bot.send_message(
        chat_id, 
        "📍 Наша клиника Stoma dent находится по адресу:\n"
        "г. Ташкент, Яшнабадский район, 1-й квартал Авиасозлар, 12\n"
        "(1-й этаж, рядом с метро Тузель)"
    )
    bot.send_location(chat_id, latitude=41.295246, longitude=69.338661)

# --- ПРОЦЕСС ЗАПИСИ (ИСПРАВЛЕННЫЙ) ---
@bot.message_handler(func=lambda message: message.text in ["📅 Записаться на приём", "/book"])
def start_booking_button(message):
    user_data.pop(message.chat.id, None)
    markup = types.InlineKeyboardMarkup()
    services = [
        "🦷 Лечение зуба", "✨ Чистка", "😁 Отбеливание", 
        "👑 Коронка", "❌ Удаление", "💊 Противовоспалительное лечение", "❓ Другое"
    ]
    
    for i in range(0, len(services), 2):
        row = [types.InlineKeyboardButton(services[i], callback_data=f"srv_{services[i]}")]
        if i + 1 < len(services):
            row.append(types.InlineKeyboardButton(services[i+1], callback_data=f"srv_{services[i+1]}"))
        markup.row(*row)

    bot.send_message(message.chat.id, "Выберите интересующую вас услугу:", reply_markup=markup)

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
    if check_menu_interruption(message):
        return
    chat_id = message.chat.id
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]["name"] = message.text

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📞 Отправить номер телефона", request_contact=True))

    msg = bot.send_message(chat_id, "Отправьте ваш номер телефона с помощью кнопки ниже или введите вручную:", reply_markup=markup)
    bot.register_next_step_handler(msg, process_phone)

def process_phone(message):
    if check_menu_interruption(message):
        return
    chat_id = message.chat.id
    phone = message.contact.phone_number if message.contact else message.text
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]["phone"] = phone
    msg = bot.send_message(chat_id, "Опишите вашу жалобу или причину визита:", reply_markup=get_main_keyboard())
    bot.register_next_step_handler(msg, process_problem)

def process_problem(message):
    if check_menu_interruption(message):
        return
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

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO appointments (user_id, patient_name, phone_number, username, service, problem, appointment_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (chat_id, data['name'], data['phone'], call.from_user.username or "", data.get('service', 'Консультация'), data['problem'], app_time_str))
        app_id = cursor.lastrowid
        conn.commit()

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

# --- МОИ ЗАПИСИ (КЛИЕНТ) ---
@bot.message_handler(func=lambda message: message.text == "📋 Мои записи")
def show_my_appointments(message):
    user_data.pop(message.chat.id, None)
    chat_id = message.chat.id
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, appointment_time, service FROM appointments WHERE user_id=? AND status='active' ORDER BY id DESC",
            (chat_id,)
        )
        records = cursor.fetchall()

    if not records:
        bot.send_message(chat_id, "У вас нет активных записей.", reply_markup=get_main_keyboard())
        return

    bot.send_message(chat_id, "📋 <b>Ваши активные записи:</b>", parse_mode="HTML")
    for app_id, app_time, service in records:
        text = f"🗓 Дата: {app_time}\n🦷 Услуга: {service}\n👨‍⚕️ Доктор Маруф"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ Отменить запись", callback_data=f"usercancel_{app_id}"))
        bot.send_message(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('usercancel_'))
def handle_user_cancel(call):
    app_id = call.data.split('_')[1]
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT appointment_time FROM appointments WHERE id=? AND user_id=?", (app_id, call.message.chat.id))
        row = cursor.fetchone()
        app_time_val = row[0] if row else "неизвестно"

        cursor.execute("UPDATE appointments SET status='cancelled' WHERE id=? AND user_id=?", (app_id, call.message.chat.id))
        conn.commit()

    bot.answer_callback_query(call.id, "Запись отменена.")
    bot.edit_message_text("❌ Запись отменена.", chat_id=call.message.chat.id, message_id=call.message.message_id)
    
    try:
        bot.send_message(
            DOCTOR_CHAT_ID, 
            f"⚠️ <b>Пациент отменил запись №{app_id}!</b>\n"
            f"🗓 Время: {app_time_val}\n"
            f"🟢 <b>Свободное время доступно для новых записей.</b>", 
            parse_mode="HTML"
        )
    except Exception:
        pass

# --- СИСТЕМА ОТЗЫВОВ ---
@bot.message_handler(func=lambda message: message.text == "⭐ Оценить лечение / Отзыв")
def ask_rating(message):
    user_data.pop(message.chat.id, None)
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
        f"Оценка принята: {'⭐' * int(stars)}\n\n"
        "Напишите ваше впечатление или что вам понравилось (или нажмите «Пропустить»):",
        chat_id=chat_id,
        message_id=call.message.message_id,
        reply_markup=markup
    )
    bot.register_next_step_handler(call.message, save_comment_step)

@bot.callback_query_handler(func=lambda call: call.data == "skip_comment")
def skip_comment_callback(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    
    data = user_data.get(chat_id, {})
    rating = data.get("rating", "⭐5")
    rating_val = data.get("rating_val", 5)
    is_after = data.get("is_after_visit", False)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO reviews (user_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
                       (chat_id, rating_val, "", datetime.now(TZ).strftime("%Y-%m-%d %H:%M")))
        conn.commit()

    user_data.pop(chat_id, None)

    bot.edit_message_text("Спасибо за отзыв! ❤️ Хорошего дня!", chat_id=chat_id, message_id=call.message.message_id)

    title_text = "🌟 НОВАЯ ОЦЕНКА ПОСЛЕ ВИЗИТА!" if is_after else "🌟 НОВАЯ ОЦЕНКА (БЕЗ ТЕКСТА)!"
    review_msg = (
        f"<b>{title_text}</b>\n\n"
        f"👤 От: {html.escape(call.from_user.first_name)} (@{call.from_user.username or 'нет'})\n"
        f"⭐ Оценка: {rating}"
    )
    try:
        bot.send_message(DOCTOR_CHAT_ID, review_msg, parse_mode="HTML")
    except Exception:
        pass

def save_comment_step(message):
    chat_id = message.chat.id
    if check_menu_interruption(message):
        return
        
    data = user_data.get(chat_id, {})
    if not data.get("awaiting_comment"):
        return

    rating = data.get("rating", "⭐5")
    rating_val = data.get("rating_val", 5)
    is_after = data.get("is_after_visit", False)
    comment_text = message.text

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO reviews (user_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
                       (chat_id, rating_val, comment_text, datetime.now(TZ).strftime("%Y-%m-%d %H:%M")))
        conn.commit()

    user_data.pop(chat_id, None)

    bot.send_message(chat_id, "Спасибо за ваш отзыв! ❤️", reply_markup=get_main_keyboard())

    title_text = "🌟 НОВЫЙ ОТЗЫВ ПОСЛЕ ВИЗИТА!" if is_after else "🌟 НОВЫЙ ОТЗЫВ!"
    review_msg = (
        f"<b>{title_text}</b>\n\n"
        f"👤 От: {html.escape(message.from_user.first_name)} (@{message.from_user.username or 'нет'})\n"
        f"⭐ Оценка: {rating}\n"
        f"💬 Комментарий: {html.escape(comment_text)}"
    )

    try:
        bot.send_message(DOCTOR_CHAT_ID, review_msg, parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка отправки отзыва врачу: {e}")

# --- ПАНЕЛЬ ВРАЧА ---
@bot.message_handler(commands=['doctor', 'admin'])
@bot.message_handler(func=lambda message: message.text == "📋 Панель врача")
def doctor_panel_menu(message):
    user_data.pop(message.chat.id, None)
    if message.chat.id != DOCTOR_CHAT_ID:
        return

    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("📅 На сегодня", callback_data="doc_period_today"),
        types.InlineKeyboardButton("📆 На завтра", callback_data="doc_period_tomorrow")
    )
    markup.row(types.InlineKeyboardButton("📊 На всю неделю", callback_data="doc_period_week"))

    bot.send_message(
        message.chat.id, 
        "👨‍⚕️ <b>Панель врача:</b>\nВыберите период для просмотра записей:", 
        reply_markup=markup, 
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("doc_period_"))
def show_doctor_period_appointments(call):
    if call.message.chat.id != DOCTOR_CHAT_ID:
        return
    
    period = call.data.replace("doc_period_", "")
    bot.answer_callback_query(call.id)

    now = datetime.now(TZ)
    
    if period == "today":
        target_date_str = now.strftime("%d.%m.%Y")
        period_title = f"📅 Записи на сегодня ({target_date_str}):"
    elif period == "tomorrow":
        tomorrow = now + timedelta(days=1)
        target_date_str = tomorrow.strftime("%d.%m.%Y")
        period_title = f"📆 Записи на завтра ({target_date_str}):"
    elif period == "week":
        start_date = now.date()
        end_date = start_date + timedelta(days=6)
        period_title = f"📊 Записи на всю неделю (с {start_date.strftime('%d.%m')} по {end_date.strftime('%d.%m.')}):"
    else:
        return

    with get_db_connection() as conn:
        cursor = conn.cursor()
        if period in ["today", "tomorrow"]:
            cursor.execute(
                "SELECT id, patient_name, phone_number, username, service, problem, appointment_time "
                "FROM appointments WHERE status='active' AND appointment_time LIKE ? ORDER BY appointment_time ASC",
                (f"{target_date_str}%",)
            )
        else:
            cursor.execute(
                "SELECT id, patient_name, phone_number, username, service, problem, appointment_time "
                "FROM appointments WHERE status='active' ORDER BY appointment_time ASC"
            )
        
        all_records = cursor.fetchall()

    records = []
    if period == "week":
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(days=7)
        for row in all_records:
            try:
                app_dt = datetime.strptime(row[6], "%d.%m.%Y %H:%M").replace(tzinfo=TZ)
                if start_dt <= app_dt <= end_dt:
                    records.append(row)
            except ValueError:
                continue
    else:
        records = all_records

    if not records:
        bot.edit_message_text(
            f"{period_title}\n\n📭 Активных записей нет.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML"
        )
        return

    bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.send_message(call.message.chat.id, f"<b>{period_title}</b> (Найдено: {len(records)})", parse_mode="HTML")
    
    for app_id, name, phone, username, service, problem, app_time in records:
        card_text = (
            f"🆔 <b>Запись №{app_id}</b>\n"
            f"👤 Пациент: {html.escape(name)}\n"
            f"📞 Телефон: {html.escape(phone)}\n"
            f"⏰ Время: {app_time}\n"
            f"🩺 Услуга: {html.escape(service)}\n"
            f"💬 Жалоба: {html.escape(problem)}"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ Пришёл", callback_data=f"status_completed_{app_id}"),
            types.InlineKeyboardButton("❌ Не пришёл", callback_data=f"status_noshow_{app_id}")
        )
        markup.row(types.InlineKeyboardButton("❌ Отменить запись", callback_data=f"cancel_{app_id}"))
        
        bot.send_message(call.message.chat.id, card_text, reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith('status_'))
def handle_status_change(call):
    if call.message.chat.id != DOCTOR_CHAT_ID:
        return
    
    parts = call.data.split('_')
    status = parts[1] 
    app_id = parts[2]
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, patient_name FROM appointments WHERE id=?", (app_id,))
        row = cursor.fetchone()
        
        cursor.execute("UPDATE appointments SET status=? WHERE id=?", (status, app_id))
        conn.commit()

    bot.answer_callback_query(call.id, "Статус обновлен!")
    status_text = "✅ Отмечено: Пришёл" if status == "completed" else "❌ Отмечено: Не пришёл"
    
    bot.edit_message_text(f"Запись №{app_id}\n\n<b>{status_text}</b>", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML")

    if status == "completed" and row:
        patient_user_id, patient_name = row
        try:
            markup = types.InlineKeyboardMarkup()
            buttons = [types.InlineKeyboardButton(f"⭐ {i}", callback_data=f"rate_after_{i}") for i in range(1, 6)]
            markup.row(buttons[0], buttons[1], buttons[2])
            markup.row(buttons[3], buttons[4])

            bot.send_message(
                patient_user_id,
                f"Здравствуйте, {patient_name}! Спасибо, что посетили клинику Stoma dent. "
                "Пожалуйста, оцените качество лечения от 1 до 5:",
                reply_markup=markup
            )
        except Exception as e:
            print(f"Не удалось отправить запрос на отзыв клиенту: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_'))
def handle_cancel_appointment(call):
    if call.message.chat.id != DOCTOR_CHAT_ID:
        return
    app_id = call.data.split('_')[1]

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, patient_name, appointment_time FROM appointments WHERE id=?", (app_id,))
        row = cursor.fetchone()
        if row:
            user_id, patient_name, app_time = row
            cursor.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (app_id,))
            conn.commit()

            try:
                bot.send_message(user_id, f"⚠️ Здравствуйте, {patient_name}!\nВаша запись на {app_time} отменена.")
            except Exception:
                pass

            bot.edit_message_text(
                f"❌ Запись №{app_id} отменена.\n"
                f"🗓 Время: {app_time}\n"
                f"🟢 <b>Свободное время доступно для новых записей.</b>", 
                chat_id=call.message.chat.id, 
                message_id=call.message.message_id,
                parse_mode="HTML"
            )

# --- СТАТИСТИКА ВРАЧА ---
@bot.message_handler(func=lambda message: message.text == "📊 Статистика")
def show_statistics(message):
    user_data.pop(message.chat.id, None)
    if message.chat.id != DOCTOR_CHAT_ID:
        bot.send_message(message.chat.id, f"⛔ У вас нет доступа к статистике. Ваш ID: {message.chat.id}")
        return

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM appointments")
            res = cursor.fetchone()
            total_patients = res[0] if res and res[0] is not None else 0
            
            current_month_str = datetime.now(TZ).strftime("%m.%Y")
            cursor.execute("SELECT COUNT(*) FROM appointments WHERE appointment_time LIKE ?", (f"%{current_month_str}%",))
            res = cursor.fetchone()
            month_appointments = res[0] if res and res[0] is not None else 0
            
            cursor.execute("SELECT COUNT(*) FROM appointments WHERE status='completed'")
            res = cursor.fetchone()
            completed = res[0] if res and res[0] is not None else 0
            
            cursor.execute("SELECT COUNT(*) FROM appointments WHERE status='noshow'")
            res = cursor.fetchone()
            noshow = res[0] if res and res[0] is not None else 0
            
            cursor.execute("SELECT COUNT(*) FROM appointments WHERE status='cancelled'")
            res = cursor.fetchone()
            cancelled = res[0] if res and res[0] is not None else 0
            
            total_visited_checked = completed + noshow
            attendance_rate = round((completed / total_visited_checked * 100), 1) if total_visited_checked > 0 else 0
            
            cursor.execute("SELECT AVG(rating), COUNT(*) FROM reviews")
            rev_data = cursor.fetchone()
            avg_rating = round(rev_data[0], 1) if rev_data and rev_data[0] is not None else 0.0
            total_reviews = rev_data[1] if rev_data and rev_data[1] is not None else 0

            cursor.execute("SELECT service, COUNT(*) as cnt FROM appointments GROUP BY service ORDER BY cnt DESC LIMIT 3")
            top_services = cursor.fetchall()
            
            cursor.execute("SELECT SUBSTR(appointment_time, 1, 10) as day_date, COUNT(*) as cnt FROM appointments WHERE status='active' GROUP BY day_date ORDER BY day_date ASC LIMIT 5")
            days_records = cursor.fetchall()

        services_text = "\n".join([f"• {s[0]} — {s[1]} записей" for s in top_services]) if top_services else "• Нет данных"
        days_text = "\n".join([f"• {d[0]} — {d[1]} акт. записей" for d in days_records]) if days_records else "• Нет активных записей"

        stats_text = (
            "📊 <b>РАСШИРЕННАЯ СТАТИСТИКА КЛИНИКИ</b>\n\n"
            f"👥 Всего пациентов: <b>{total_patients}</b>\n"
            f"📅 Записей за месяц: <b>{month_appointments}</b>\n"
            f"✅ Пришли: <b>{completed}</b>\n"
            f"❌ Не пришли: <b>{noshow}</b>\n"
            f"🚫 Отменили: <b>{cancelled}</b>\n"
            f"📈 Процент явки: <b>{attendance_rate}%</b>\n"
            f"⭐ Средняя оценка: <b>{avg_rating} / 5</b> (на основе {total_reviews} отзывов)\n\n"
            f"🦷 <b>Самые популярные услуги:</b>\n{services_text}\n\n"
            f"📆 <b>Ближайшие записи по дням:</b>\n{days_text}"
        )
        
        bot.send_message(message.chat.id, stats_text, parse_mode="HTML")
        
    except Exception as e:
        bot.send_message(message.chat.id, f"⚠️ Ошибка при загрузке статистики:\n<code>{html.escape(str(e))}</code>", parse_mode="HTML")

# --- НАПОМИНАНИЯ ---
def check_and_send_reminders():
    now = datetime.now(TZ)
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, patient_name, appointment_time, reminded_24h, reminded_2h FROM appointments WHERE status='active'")
        records = cursor.fetchall()

        for app_id, user_id, name, app_time_str, r24, r2 in records:
            try:
                app_dt = datetime.strptime(app_time_str, "%d.%m.%Y %H:%M").replace(tzinfo=TZ)
                diff = app_dt - now

                if timedelta(hours=23) <= diff <= timedelta(hours=25) and not r24:
                    bot.send_message(user_id, f"🦷 Напоминаем: у вас завтра визит в клинику Stoma dent в {app_dt.strftime('%H:%M')}.")
                    cursor.execute("UPDATE appointments SET reminded_24h = 1 WHERE id = ?", (app_id,))

                elif timedelta(minutes=105) <= diff <= timedelta(minutes=135) and not r2:
                    bot.send_message(user_id, f"⏰ Напоминание: ваш визит в клинику Stoma dent через 2 часа ({app_dt.strftime('%H:%M')}). Ждем вас!")
                    cursor.execute("UPDATE appointments SET reminded_2h = 1 WHERE id = ?", (app_id,))

            except ValueError:
                continue
        conn.commit()

# --- ЗАПУСК ---
if __name__ == '__main__':
    init_db()
    keep_alive()

    scheduler = BackgroundScheduler(timezone=TZ)
    scheduler.add_job(check_and_send_reminders, 'interval', minutes=15)
    scheduler.start()

    print("Бот успешно запущен, защищен и полностью готов к работе!")
    bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
