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

# Функция получения ЗАНЯТОГО времени на конкретную дату
def get_booked_times(date_str):
    conn = sqlite3.connect('dentistry.db')
    cursor = conn.cursor()
    cursor.execute(
        "SELECT appointment_time FROM appointments WHERE status='active' AND appointment_time LIKE ?",
        (f"{date_str}%",)
    )
    rows = cursor.fetchall()
    conn.close()
    
    return [r[0].split()[1] for r in rows if len(r[0].split()) > 1]

# --- КЛАВИАТУРЫ ---
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    markup.row("📅 Записаться на приём", "🩺 Услуги и лечение")
    markup.row("⭐ Оценить лечение / Отзыв", "ℹ️ Информация")
    return markup

def get_doctor_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    markup.row("📋 Панель врача", "📊 Все записи")
    markup.row("📱 Главное меню клиента")
    return markup

# --- СТАРТ ---
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

# --- ОБНОВЛЕННЫЙ БЛОК ИНФОРМАЦИИ ---
@bot.message_handler(func=lambda message: message.text == "ℹ️ Информация")
def clinic_info(message):
    text = (
        "👨‍⚕️ Стоматологическая клиника доктора Маруфа\n\n"
        "📍 Адрес: 1-й квартал Авиасозлар, 12\n"
        "⏰ Режим работы: Пн-Сб с 09:00 до 18:00\n"
        "📞 Телефон для связи: +998 (90) 123-45-67\n\n"
        "Заботьтесь о своей улыбке вовремя!"
    )
    bot.send_message(message.chat.id, text, reply_markup=get_main_keyboard())

# --- ОЦЕНКА И ОТЗЫВЫ ---
@bot.message_handler(func=lambda message: message.text == "⭐ Оценить лечение / Отзыв")
def ask_rating(message):
    markup = types.InlineKeyboardMarkup()
    buttons = [
        types.InlineKeyboardButton("⭐ 1", callback_data="rate_1"),
        types.InlineKeyboardButton("⭐⭐ 2", callback_data="rate_2"),
        types.InlineKeyboardButton("⭐⭐⭐ 3", callback_data="rate_3"),
        types.InlineKeyboardButton("⭐⭐⭐⭐ 4", callback_data="rate_4"),
        types.InlineKeyboardButton("⭐⭐⭐⭐⭐ 5", callback_data="rate_5")
    ]
    markup.row(buttons[0], buttons[1], buttons[2])
    markup.row(buttons[3], buttons[4])
    bot.send_message(message.chat.id, "Пожалуйста, оцените качество нашего лечения и обслуживания:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("rate_"))
def process_rating(call):
    stars = call.data.split("_")[1]
    rating_stars = "⭐" * int(stars)
    chat_id = call.message.chat.id
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]["rating"] = rating_stars

    bot.answer_callback_query(call.id)
    msg = bot.send_message(chat_id, f"Вы поставили оценку: {rating_stars}\n\nТеперь напишите ваш комментарий или отзыв текстом:", reply_markup=get_main_keyboard())
    bot.register_next_step_handler(msg, save_feedback)

def save_feedback(message):
    chat_id = message.chat.id
    rating = user_data.get(chat_id, {}).get("rating", "Без оценки")
    feedback_text = message.text

    bot.send_message(chat_id, "Спасибо за ваш отзыв! Мы ценим ваше мнение. ❤️", reply_markup=get_main_keyboard())
    review_msg = f"🌟 НОВЫЙ ОТЗЫВ!\n\n👤 От: {message.from_user.first_name} (@{message.from_user.username or 'без_юзернейма'})\n⭐ Оценка: {rating}\n💬 Текст: {feedback_text}"
    bot.send_message(DOCTOR_CHAT_ID, review_msg)

# --- ДИНАМИЧЕСКАЯ ЗАПИСЬ НА ПРИЕМ (С ФИЛЬТРАЦИЕЙ ВРЕМЕНИ) ---
def start_date_selection(chat_id):
    markup = types.InlineKeyboardMarkup()
    today = datetime.now()
    
    for i in range(1, 6):
        date_str = (today + timedelta(days=i)).strftime("%d.%m.%Y")
        markup.add(types.InlineKeyboardButton(f"📅 {date_str}", callback_data=f"date_{date_str}"))

    bot.send_message(chat_id, "Выберите дату для визита:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("date_"))
def choose_time(call):
    selected_date = call.data.split("_")[1]
    user_data[call.message.chat.id] = {"date": selected_date}

    # Рабочие слоты до 18:00
    all_times = ["09:00", "10:30", "12:00", "14:00", "15:30", "17:00"]
    booked_times = get_booked_times(selected_date)
    
    # Скрываем занятые слоты
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
    app_time_str = f"{data['date']} {data['time']}"

    # Проверка перед окончательной записью
    booked_times = get_booked_times(data['date'])
    if data['time'] in booked_times:
        bot.send_message(chat_id, "⚠️ Извините, это время только что кто-то занял! Попробуйте выбрать другое время.", reply_markup=get_main_keyboard())
        return

    conn = sqlite3.connect('dentistry.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO appointments (user_id, patient_name, phone_number, username, problem, appointment_time)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (chat_id, data['name'], data['phone'], message.from_user.username or "", data['problem'], app_time_str))
    app_id = cursor.lastrowid
    conn.commit()
    conn.close()

    bot.send_message(
        chat_id,
        f"✅ Вы успешно записаны!\n\n👤 Имя: {data['name']}\n📅 Дата и время: {app_time_str}\n🩺 Жалоба: {data['problem']}\n\nМы ждём вас!",
        reply_markup=get_main_keyboard()
    )

    user_link = f"@{message.from_user.username}" if message.from_user.username else "Не указан"
    doctor_msg = (
        f"🆕 НОВАЯ ЗАПИСЬ №{app_id}!\n\n👤 Пациент: {data['name']}\n📞 Телефон: {data['phone']}\n"
        f"💬 Telegram: {user_link}\n⏰ Время: {app_time_str}\n🩺 Жалоба: {data['problem']}"
    )
    
    markup = types.InlineKeyboardMarkup()
    if message.from_user.username:
        markup.add(types.InlineKeyboardButton("💬 Написать клиенту", url=f"https://t.me/{message.from_user.username}"))
    markup.add(types.InlineKeyboardButton("❌ Отменить эту запись", callback_data=f"cancel_{app_id}"))

    bot.send_message(DOCTOR_CHAT_ID, doctor_msg, reply_markup=markup)

# --- ПАНЕЛЬ ВРАЧА И ВОЗВРАТ ВРЕМЕНИ ПРИ ОТМЕНЕ ---
@bot.message_handler(commands=['doctor', 'admin'])
@bot.message_handler(func=lambda message: message.text in ["📋 Панель врача", "📊 Все записи"])
def doctor_panel(message):
    if message.chat.id != DOCTOR_CHAT_ID:
        bot.send_message(message.chat.id, "⛔ Доступ запрещён.", reply_markup=get_main_keyboard())
        return

    conn = sqlite3.connect('dentistry.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, patient_name, phone_number, username, problem, appointment_time FROM appointments WHERE status='active' ORDER BY appointment_time ASC")
    records = cursor.fetchall()
    conn.close()

    if not records:
        bot.send_message(message.chat.id, "📅 Активных записей нет.", reply_markup=get_doctor_keyboard())
        return

    bot.send_message(message.chat.id, f"📋 Активные записи ({len(records)}):", reply_markup=get_doctor_keyboard())

    for app_id, name, phone, username, problem, app_time in records:
        user_link = f"@{username}" if username else "Не указан"
        card_text = f"🆔 Запись №{app_id}\n👤 Пациент: {name}\n📞 Телефон: {phone}\n💬 Telegram: {user_link}\n⏰ Время: {app_time}\n🩺 Жалоба: {problem}"

        markup = types.InlineKeyboardMarkup()
        if username:
            markup.add(types.InlineKeyboardButton("💬 Написать клиенту", url=f"https://t.me/{username}"))
        markup.add(types.InlineKeyboardButton("❌ Отменить запись", callback_data=f"cancel_{app_id}"))

        bot.send_message(message.chat.id, card_text, reply_markup=markup)

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
        # Перевод статуса в 'cancelled' возвращает слот в свободный список
        cursor.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (app_id,))
        conn.commit()

        try:
            bot.send_message(
                user_id,
                f"⚠️ Здравствуйте, {patient_name}!\nВаша запись на {app_time} отменена.\nВы можете выбрать другое удобное время.",
                reply_markup=get_main_keyboard()
            )
        except Exception:
            pass

        bot.answer_callback_query(call.id, "Запись отменена, время снова свободно!")
        bot.edit_message_text(f"❌ Запись №{app_id} ({patient_name} на {app_time}) отменена. Время вернулось в свободный список.", chat_id=call.message.chat.id, message_id=call.message.message_id)

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
                bot.send_message(user_id, f"⏰ Напоминание: ваш визит к доктору Маруфу сегодня в {app_dt.strftime('%H:%M')}.", reply_markup=get_main_keyboard())
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

    print("Бот запущен!")
    bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
