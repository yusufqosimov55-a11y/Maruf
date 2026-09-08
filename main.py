import os
import sqlite3
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask
from telebot import TeleBot, types
from apscheduler.schedulers.background import BackgroundScheduler

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "8657040766:AAHeBxOmF86zv__MaIzayHuoOoZ5B7ycSeo")
DOCTOR_CHAT_ID = int(os.getenv("DOCTOR_CHAT_ID", "934720885"))

bot = TeleBot(BOT_TOKEN)
app = Flask('')

# Временное хранилище шагов записи клиентов
user_data = {}

# --- FLASK ДЛЯ UPTIMEROBOT ---
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
def init_db():
    conn = sqlite3.connect('dentistry.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            patient_name TEXT,
            phone_number TEXT,
            username TEXT,
            problem TEXT,
            appointment_time TEXT,
            status TEXT DEFAULT 'active'
        )
    ''')
    conn.commit()
    conn.close()

# --- КЛАВИАТУРЫ (КНОПКИ МЕНЮ) ---

# Главное меню для клиентов (Исправлен параметр на is_persistent)
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    markup.row("📅 Записаться на приём", "🩺 Услуги и лечение")
    markup.row("⭐ Оценить лечение / Отзыв", "ℹ️ Информация")
    return markup

# Меню для доктора
def get_doctor_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    markup.row("📋 Панель врача", "📊 Все записи")
    markup.row("📱 Главное меню клиента")
    return markup

# --- СТАРТ И ОБРАБОТКА КОМАНД ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    chat_id = message.chat.id
    
    if chat_id == DOCTOR_CHAT_ID:
        bot.send_message(
            chat_id,
            "Здравствуйте, доктор Маруф! Панель администратора готова.",
            reply_markup=get_doctor_keyboard()
        )
        return

    welcome_text = (
        "Здравствуйте! Вас приветствует бот стоматологической клиники доктора Маруфа. 🦷\n\n"
        "Используйте меню ниже для записи или получения информации."
    )
    bot.send_message(chat_id, welcome_text, reply_markup=get_main_keyboard())

# --- ТЕКСТОВЫЕ КНОПКИ ГЛАВНОГО МЕНЮ ---

@bot.message_handler(func=lambda message: message.text == "📱 Главное меню клиента")
def show_client_menu(message):
    bot.send_message(message.chat.id, "Переключено на меню клиента:", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text in ["📅 Записаться на приём", "/book"])
def start_booking_button(message):
    start_date_selection(message.chat.id)

@bot.message_handler(func=lambda message: message.text == "🩺 Услуги и лечение")
def services_info(message):
    text = (
        "🏥 Услуги клиники доктора Маруфа:\n\n"
        "• Лечение кариеса и пульпита\n"
        "• Профессиональная гигиена и чистка\n"
        "• Протезирование и установка коронок\n"
        "• Удаление зубов любой сложности\n"
        "• Эстетическая стоматология и отбеливание\n\n"
        "Нажмите «📅 Записаться на приём», чтобы выбрать удобное время!"
    )
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "ℹ️ Информация")
def clinic_info(message):
    text = (
        "📍 Клиника доктора Маруфа\n\n"
        "⏰ Режим работы: Пн-Сб с 09:00 до 19:00\n"
        "📞 Телефон для связи: +998 (90) 123-45-67\n\n"
        "Заботьтесь о своей улыбке вовремя!"
    )
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda message: message.text == "⭐ Оценить лечение / Отзыв")
def ask_feedback(message):
    msg = bot.send_message(message.chat.id, "Напишите ваш отзыв или оценку работы клиники:", reply_markup=get_main_keyboard())
    bot.register_next_step_handler(msg, save_feedback)

def save_feedback(message):
    bot.send_message(message.chat.id, "Спасибо за ваш отзыв! Мы ценим ваше мнение. ❤️", reply_markup=get_main_keyboard())
    review_msg = f"🌟 НОВЫЙ ОТЗЫВ!\n\nОт: {message.from_user.first_name} (@{message.from_user.username or 'без_юзернейма'})\nТекст: {message.text}"
    bot.send_message(DOCTOR_CHAT_ID, review_msg)

# --- ПРОЦЕСС ЗАПИСИ НА ПРИЕМ ---

def start_date_selection(chat_id):
    markup = types.InlineKeyboardMarkup()
    today = datetime.now()
    
    for i in range(1, 6):
        date_str = (today + timedelta(days=i)).strftime("%d.%m.%Y")
        markup.add(types.InlineKeyboardButton(f"📅 {date_str}", callback_data=f"date_{date_str}"))

    bot.send_message(chat_id, "Выберите дату для визита:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "start_booking")
def cb_start_booking(call):
    start_date_selection(call.message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("date_"))
def choose_time(call):
    selected_date = call.data.split("_")[1]
    user_data[call.message.chat.id] = {"date": selected_date}

    markup = types.InlineKeyboardMarkup()
    times = ["09:00", "10:30", "12:00", "14:00", "15:30", "17:00", "18:30"]
    
    row = []
    for t in times:
        row.append(types.InlineKeyboardButton(t, callback_data=f"time_{t}"))
        if len(row) == 2:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)

    bot.edit_message_text(
        f"Выбранная дата: {selected_date}\nТеперь выберите время:",
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
    if message.contact:
        phone = message.contact.phone_number
    else:
        phone = message.text

    user_data[chat_id]["phone"] = phone
    msg = bot.send_message(chat_id, "Опишите вашу жалобу или причину визита (например: боль в зубе, чистка, консультация):", reply_markup=get_main_keyboard())
    bot.register_next_step_handler(msg, process_problem)

def process_problem(message):
    chat_id = message.chat.id
    user_data[chat_id]["problem"] = message.text
    data = user_data[chat_id]

    conn = sqlite3.connect('dentistry.db')
    cursor = conn.cursor()
    app_time_str = f"{data['date']} {data['time']}"
    
    cursor.execute('''
        INSERT INTO appointments (user_id, patient_name, phone_number, username, problem, appointment_time)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (chat_id, data['name'], data['phone'], message.from_user.username or "", data['problem'], app_time_str))
    
    app_id = cursor.lastrowid
    conn.commit()
    conn.close()

    bot.send_message(
        chat_id,
        f"✅ Вы успешно записаны!\n\n"
        f"👤 Имя: {data['name']}\n"
        f"📅 Дата и время: {app_time_str}\n"
        f"🩺 Жалоба: {data['problem']}\n\n"
        f"Мы ждём вас!",
        reply_markup=get_main_keyboard()
    )

    # Уведомление врачу
    user_link = f"@{message.from_user.username}" if message.from_user.username else "Не указан"
    doctor_msg = (
        f"🆕 НОВАЯ ЗАПИСЬ №{app_id}!\n\n"
        f"👤 Пациент: {data['name']}\n"
        f"📞 Телефон: {data['phone']}\n"
        f"💬 Telegram: {user_link}\n"
        f"⏰ Время: {app_time_str}\n"
        f"🩺 Жалоба: {data['problem']}"
    )
    
    markup = types.InlineKeyboardMarkup()
    if message.from_user.username:
        markup.add(types.InlineKeyboardButton("💬 Написать клиенту", url=f"https://t.me/{message.from_user.username}"))
    markup.add(types.InlineKeyboardButton("❌ Отменить эту запись", callback_data=f"cancel_{app_id}"))

    bot.send_message(DOCTOR_CHAT_ID, doctor_msg, reply_markup=markup)

# --- ПАНЕЛЬ ВРАЧА ---

@bot.message_handler(commands=['doctor', 'admin'])
@bot.message_handler(func=lambda message: message.text in ["📋 Панель врача", "📊 Все записи"])
def doctor_panel(message):
    if message.chat.id != DOCTOR_CHAT_ID:
        bot.send_message(message.chat.id, "⛔ Доступ запрещён.", reply_markup=get_main_keyboard())
        return

    conn = sqlite3.connect('dentistry.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, patient_name, phone_number, username, problem, appointment_time "
        "FROM appointments WHERE status='active' ORDER BY appointment_time ASC"
    )
    records = cursor.fetchall()
    conn.close()

    if not records:
        bot.send_message(message.chat.id, "📅 Активных записей нет.", reply_markup=get_doctor_keyboard())
        return

    bot.send_message(message.chat.id, f"📋 Активные записи ({len(records)}):", reply_markup=get_doctor_keyboard())

    for app_id, name, phone, username, problem, app_time in records:
        user_link = f"@{username}" if username else "Не указан"
        card_text = (
            f"🆔 Запись №{app_id}\n"
            f"👤 Пациент: {name}\n"
            f"📞 Телефон: {phone}\n"
            f"💬 Telegram: {user_link}\n"
            f"⏰ Время: {app_time}\n"
            f"🩺 Жалоба: {problem}"
        )

        markup = types.InlineKeyboardMarkup()
        if username:
            markup.add(types.InlineKeyboardButton("💬 Написать клиенту", url=f"https://t.me/{username}"))
        markup.add(types.InlineKeyboardButton("❌ Отменить запись", callback_data=f"cancel_{app_id}"))

        bot.send_message(message.chat.id, card_text, reply_markup=markup)

# Отмена записи
@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_'))
def handle_cancel_appointment(call):
    if call.message.chat.id != DOCTOR_CHAT_ID:
        return

    app_id = call.data.split('_')[1]

    conn = sqlite3.connect('dentistry.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, patient_name, appointment_time FROM appointments WHERE id=?", (app_id,))
    row = cursor.fetchone()

    if row:
        user_id, patient_name, app_time = row
        cursor.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (app_id,))
        conn.commit()

        try:
            bot.send_message(
                user_id,
                f"⚠️ Здравствуйте, {patient_name}!\n\n"
                f"Ваша запись к доктору Маруфу на {app_time} была отменена.\n"
                f"Для выбора другого времени воспользуйтесь меню ниже.",
                reply_markup=get_main_keyboard()
            )
        except Exception:
            pass

        bot.answer_callback_query(call.id, "Запись отменена.")
        bot.edit_message_text(
            f"❌ Запись №{app_id} ({patient_name}) отменена.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )

    conn.close()

# --- АВТО-НАПОМИНАНИЯ ---
def check_and_send_reminders():
    conn = sqlite3.connect('dentistry.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, patient_name, appointment_time FROM appointments WHERE status='active'")
    records = cursor.fetchall()

    now = datetime.now()
    for app_id, user_id, name, app_time in records:
        try:
            app_dt = datetime.strptime(app_time, "%d.%m.%Y %H:%M")
            if timedelta(hours=0) <= (app_dt - now) <= timedelta(hours=2):
                bot.send_message(
                    user_id,
                    f"⏰ Здравствуйте, {name}!\nНапоминаем о вашем визите к доктору Маруфу сегодня в {app_dt.strftime('%H:%M')}.",
                    reply_markup=get_main_keyboard()
                )
        except ValueError:
            continue

    conn.close()

# --- ЗАПУСК ---
if __name__ == '__main__':
    init_db()
    keep_alive()

    scheduler = BackgroundScheduler()
    scheduler.add_job(check_and_send_reminders, 'interval', minutes=30)
    scheduler.start()

    print("Бот запущен с исправленной клавиатурой!")
    bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
