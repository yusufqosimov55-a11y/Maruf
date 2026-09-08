import os
import sqlite3
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

# --- СТАРТ И НАВИГАЦИЯ ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = message.chat.id
    if chat_id == DOCTOR_CHAT_ID:
        bot.send_message(chat_id, "Здравствуйте, доктор Маруф! Панель администратора готова.", reply_markup=get_doctor_keyboard())
        return

    welcome_text = (
        "Здравствуйте! Вас приветствует бот стоматологической клиники доктора Маруфа. 🦷\n\n"
        "Используйте меню ниже для записи или получения информации."
    )
    bot.send_message(chat_id, welcome_text, reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "📱 Главное меню клиента")
def show_client_menu(message):
    bot.send_message(message.chat.id, "Переключено на меню клиента:", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text in ["🩺 Услуги и лечение"])
def services_info(message):
    text = (
        "🏥 **Услуги клиники Stoma dent:**\n\n"
        "• Лечение кариеса и пульпита\n"
        "• Профессиональная гигиена и чистка\n"
        "• Протезирование и установка коронок\n"
        "• Удаление зубов любой сложности\n"
        "• Эстетическая стоматология и отбеливание\n\n"
        "Нажмите «📅 Записаться на приём», чтобы выбрать удобное время!"
    )
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

@bot.message_handler(func=lambda message: message.text == "ℹ️ Информация")
def clinic_info(message):
    text = (
        "👨‍⚕️ Стоматологическая клиника Stoma dent (доктор Маруф)\n\n"
        "📍 Адрес: г. Ташкент, Яшнабадский район, 1-й квартал Авиасозлар, 12\n"
        "🚇 Ориентир: метро Тузель (1-й этаж)\n"
        "⏰ Режим работы: Ежедневно с 09:00 до 19:00\n"
        "📞 Телефон для связи: +998 (93) 508-11-88, +998 (90) 175-43-68\n\n"
        "Заботьтесь о своей улыбке вовремя!"
    )
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard())

# --- ТОЧНАЯ ГЕОЛОКАЦИЯ АВИАСОЗЛАР 1, ДОМ 12 ---
@bot.message_handler(func=lambda message: message.text == "📍 Как нас найти")
def send_location(message):
    chat_id = message.chat.id
    bot.send_message(
        chat_id, 
        "📍 Наша клиника Stoma dent находится по адресу:\n"
        "г. Ташкент, Яшнабадский район, 1-й квартал Авиасозлар, 12\n"
        "(1-й этаж, рядом с метро Тузель)"
    )
    
    # Координаты точно по зданию Авиасозлар-1, 12:
    latitude = 41.295246
    longitude = 69.338661
    
    bot.send_location(chat_id, latitude=latitude, longitude=longitude)

# --- ПРОЦЕСС ЗАПИСИ ---
@bot.message_handler(func=lambda message: message.text in ["📅 Записаться на приём", "/book"])
def start_booking_button(message):
    markup = types.InlineKeyboardMarkup()
    services = ["🦷 Лечение зуба", "✨ Чистка", "😁 Отбеливание", "👑 Коронка", "❌ Удаление", "❓ Другое"]
    
    for i in range(0, len(services), 2):
        row = [types.InlineKeyboardButton(services[i], callback_data=f"srv_{services[i]}")]
        if i + 1 < len(services):
            row.append(types.InlineKeyboardButton(services[i+1], callback_data=f"srv_{services[i+1]}"))
        markup.row(*row)

    bot.send_message(message.chat.id, "Выберите интересующую вас услугу:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("srv_"))
def process_service_choice(call):
    service_name = call.data.replace("srv_", "")
    user_data[call.message.chat.id] = {"service": service_name}
    bot.answer_callback_query(call.id)
    start_date_selection(call.message.chat.id)

def start_date_selection(chat_id):
    markup = types.InlineKeyboardMarkup()
    today = datetime.now(TZ)
    days_added = 0
    current_day = today

    while days_added < 5:
        current_day += timedelta(days=1)
        if current_day.weekday() == 6:  # Пропуск воскресенья
            continue
        
        days_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        months_ru = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        
        day_str = f"{days_ru[current_day.weekday()]}, {current_day.day} {months_ru[current_day.month-1]}"
        date_val = current_day.strftime("%d.%m.%Y")
        
        markup.add(types.InlineKeyboardButton(f"📅 {day_str}", callback_data=f"date_{date_val}"))
        days_added += 1

    bot.send_message(chat_id, "Выберите дату для визита:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("date_"))
def choose_time(call):
    selected_date = call.data.split("_")[1]
    if call.message.chat.id not in user_data:
        user_data[call.message.chat.id] = {}
    user_data[call.message.chat.id]["date"] = selected_date

    all_times = ["09:00", "10:30", "12:00", "14:00", "15:30", "17:00"]
    booked_times = get_booked_times(selected_date)
    available_times = [t for t in all_times if t not in booked_times]

    if not available_times:
        bot.edit_message_text(
            f"На дату {selected_date} свободных мест нет. Пожалуйста, выберите другую дату.",
            chat_id=call.message.chat.id,
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
        chat_id=call.message.chat.id,
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

    msg = bot.send_message(chat_id, "Введите ваше ФИО (Имя и Фамилию):", reply_markup=get_main_keyboard())
    bot.register_next_step_handler(msg, process_name)

def process_name(message):
    chat_id = message.chat.id
    user_data[chat_id]["name"] = message.text

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📞 Отправить номер телефона", request_contact=True))

    msg = bot.send_message(chat_id, "Отправьте ваш номер телефона с помощью кнопки ниже или введите вручную:", reply_markup=markup)
    bot.register_next_step_handler(msg, process_phone)

def process_phone(message):
    chat_id = message.chat.id
    phone = message.contact.phone_number if message.contact else message.text
    user_data[chat_id]["phone"] = phone
    msg = bot.send_message(chat_id, "Опишите вашу жалобу или причину визита:", reply_markup=get_main_keyboard())
    bot.register_next_step_handler(msg, process_problem)

def process_problem(message):
    chat_id = message.chat.id
    user_data[chat_id]["problem"] = message.text
    data = user_data[chat_id]

    text = (
        "📋 **ПРОВЕРЬТЕ ДАННЫЕ:**\n\n"
        f"👤 Имя: {data.get('name')}\n"
        f"📞 Телефон: {data.get('phone')}\n"
        f"📅 Дата: {data.get('date')}\n"
        f"⏰ Время: {data.get('time')}\n"
        f"🦷 Услуга: {data.get('service', 'Консультация')}\n"
        f"💬 Жалоба: {data.get('problem')}\n\n"
        "Всё верно?"
    )

    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_booking"),
        types.InlineKeyboardButton("❌ Отменить", callback_data="cancel_booking_process")
    )
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

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

    user_data.pop(chat_id, None)

    bot.edit_message_text(
        f"✅ Вы успешно записаны!\n\n👤 Имя: {data['name']}\n📅 Дата и время: {app_time_str}\n🩺 Услуга: {data.get('service')}\n\nМы ждём вас!",
        chat_id=chat_id,
        message_id=call.message.message_id
    )

    user_link = f"@{call.from_user.username}" if call.from_user.username else "Не указан"
    doctor_msg = (
        f"🆕 **НОВАЯ ЗАПИСЬ №{app_id}!**\n\n"
        f"👤 Пациент: {data['name']}\n📞 Телефон: {data['phone']}\n"
        f"💬 Telegram: {user_link}\n⏰ Время: {app_time_str}\n"
        f"🦷 Услуга: {data.get('service')}\n🩺 Жалоба: {data['problem']}"
    )
    
    markup = types.InlineKeyboardMarkup()
    if call.from_user.username:
        markup.add(types.InlineKeyboardButton("💬 Написать клиенту", url=f"https://t.me/{call.from_user.username}"))
    markup.add(types.InlineKeyboardButton("❌ Отменить запись", callback_data=f"cancel_{app_id}"))

    bot.send_message(DOCTOR_CHAT_ID, doctor_msg, reply_markup=markup, parse_mode="Markdown")

# --- МОИ ЗАПИСИ (КЛИЕНТ) ---
@bot.message_handler(func=lambda message: message.text == "📋 Мои записи")
def show_my_appointments(message):
    chat_id = message.chat.id
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, appointment_time, service FROM appointments WHERE user_id=? AND status='active' ORDER BY id DESC",
            (chat_id,)
        )
        records = cursor.fetchall()

    if not records:
        bot.send_message(chat_id, "У вас нет активных записей.")
        return

    bot.send_message(chat_id, "📋 **Ваши активные записи:**", parse_mode="Markdown")
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
        cursor.execute("UPDATE appointments SET status='cancelled' WHERE id=? AND user_id=?", (app_id, call.message.chat.id))
        conn.commit()

    bot.answer_callback_query(call.id, "Запись отменена.")
    bot.edit_message_text("❌ Запись отменена.", chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.send_message(DOCTOR_CHAT_ID, f"⚠️ Пациент отменил запись №{app_id}.")

# --- ОТЗЫВЫ ---
@bot.message_handler(func=lambda message: message.text == "⭐ Оценить лечение / Отзыв")
def ask_rating(message):
    markup = types.InlineKeyboardMarkup()
    buttons = [types.InlineKeyboardButton(f"⭐ {i}", callback_data=f"rate_{i}") for i in range(1, 6)]
    markup.row(buttons[0], buttons[1], buttons[2])
    markup.row(buttons[3], buttons[4])
    bot.send_message(message.chat.id, "Пожалуйста, оцените качество лечения и обслуживания:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("rate_"))
def process_rating(call):
    stars = call.data.split("_")[1]
    if call.message.chat.id not in user_data:
        user_data[call.message.chat.id] = {}
    user_data[call.message.chat.id]["rating"] = "⭐" * int(stars)

    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, f"Оценка: {'⭐' * int(stars)}\n\nНапишите ваш отзыв текстом:")
    bot.register_next_step_handler(msg, save_feedback)

def save_feedback(message):
    chat_id = message.chat.id
    rating = user_data.get(chat_id, {}).get("rating", "⭐5")
    feedback_text = message.text

    bot.send_message(chat_id, "Спасибо за ваш отзыв! ❤️", reply_markup=get_main_keyboard())
    review_msg = f"🌟 **НОВЫЙ ОТЗЫВ!**\n\n👤 От: {message.from_user.first_name} (@{message.from_user.username or 'нет'})\n⭐ Оценка: {rating}\n💬 Текст: {feedback_text}"
    bot.send_message(DOCTOR_CHAT_ID, review_msg, parse_mode="Markdown")

# --- ПАНЕЛЬ ВРАЧА И СТАТИСТИКА ---
@bot.message_handler(commands=['doctor', 'admin'])
@bot.message_handler(func=lambda message: message.text == "📋 Панель врача")
def doctor_panel(message):
    if message.chat.id != DOCTOR_CHAT_ID:
        return

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, patient_name, phone_number, username, service, problem, appointment_time FROM appointments WHERE status='active' ORDER BY id ASC")
        records = cursor.fetchall()

    if not records:
        bot.send_message(message.chat.id, "📅 Активных записей нет.", reply_markup=get_doctor_keyboard())
        return

    bot.send_message(message.chat.id, f"📋 Активные записи ({len(records)}):", reply_markup=get_doctor_keyboard())
    for app_id, name, phone, username, service, problem, app_time in records:
        card_text = f"🆔 **Запись №{app_id}**\n👤 Пациент: {name}\n📞 {phone}\n⏰ {app_time}\n🩺 {service}: {problem}"
        
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ Пришёл", callback_data=f"status_completed_{app_id}"),
            types.InlineKeyboardButton("❌ Не пришёл", callback_data=f"status_noshow_{app_id}")
        )
        markup.row(types.InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{app_id}"))
        bot.send_message(message.chat.id, card_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('status_'))
def handle_status_change(call):
    if call.message.chat.id != DOCTOR_CHAT_ID:
        return
    _, status, app_id = call.data.split('_')
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE appointments SET status=? WHERE id=?", (status, app_id))
        conn.commit()

    bot.answer_callback_query(call.id, "Статус обновлен!")
    status_text = "✅ Отмечено: Пришёл" if status == "completed" else "❌ Отмечено: Не пришёл"
    bot.edit_message_text(f"{call.message.text}\n\n**{status_text}**", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown")

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

            bot.edit_message_text(f"❌ Запись №{app_id} отменена.", chat_id=call.message.chat.id, message_id=call.message.message_id)

@bot.message_handler(func=lambda message: message.text == "📊 Статистика")
def show_statistics(message):
    if message.chat.id != DOCTOR_CHAT_ID:
        return

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM appointments")
        total = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM appointments WHERE status='completed'")
        completed = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM appointments WHERE status='cancelled'")
        cancelled = cursor.fetchone()[0]

    stats_text = (
        "📊 **СТАТИСТИКА КЛИНИКИ**\n\n"
        f"👥 Всего записей: {total}\n"
        f"✅ Успешных визитов: {completed}\n"
        f"❌ Отменено: {cancelled}"
    )
    bot.send_message(message.chat.id, stats_text, parse_mode="Markdown")

# --- ДВУХУРОВНЕВЫЕ НАПОМИНАНИЯ ---
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

                # Напоминание за 24 часа
                if timedelta(hours=23) <= diff <= timedelta(hours=25) and not r24:
                    bot.send_message(user_id, f"🦷 Напоминаем: у вас завтра визит в клинику Stoma dent в {app_dt.strftime('%H:%M')}.")
                    cursor.execute("UPDATE appointments SET reminded_24h = 1 WHERE id = ?", (app_id,))

                # Напоминание за 2 часа
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

    print("Бот успешно запущен!")
    bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
