import sqlite3
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
import time
from apscheduler.schedulers.background import BackgroundScheduler
import os
import telebot
from telebot import types

# ==========================================
# ⚙️ НАСТРОЙКИ
# ==========================================
BOT_TOKEN = "8657040766:AAHeBxOmF86zv__MaIzayHuoOoZ5B7ycSeo"
MARUF_ID = 934720885  
# ==========================================

bot = telebot.TeleBot(BOT_TOKEN)

# Веб-сервер для Render
app = Flask('')

@app.route('/')
def home():
    return "Dental Clinic Bot is running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()

RU_DAYS = {
    "Mon": "Пн", "Tue": "Вт", "Wed": "Ср", "Thu": "Чт", "Fri": "Пт", "Sat": "Сб", "Sun": "Вс"
}

WORKING_HOURS = ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00"]
LAST_WORK_HOUR = "18:00"

def init_db():
    conn = sqlite3.connect('dent.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            time TEXT,
            user_id INTEGER,
            client_name TEXT,
            client_phone TEXT,
            client_username TEXT,
            problem TEXT,
            status TEXT DEFAULT 'active',
            notified_day INTEGER DEFAULT 0,
            notified_hour INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_name TEXT,
            client_username TEXT,
            stars INTEGER,
            text TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_free_hours(date_str):
    conn = sqlite3.connect('dent.db')
    cursor = conn.cursor()
    cursor.execute("SELECT time FROM appointments WHERE date = ? AND status = 'active'", (date_str,))
    booked_hours = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    free_hours = []
    current_time_str = datetime.now().strftime("%H:%M")
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    for hour in WORKING_HOURS:
        if hour not in booked_hours:
            if date_str == today_str and hour <= current_time_str:
                continue
            free_hours.append(hour)
            
    return free_hours

def get_available_dates():
    dates = []
    now = datetime.now()
    current_date = now.date()
    current_time_str = now.strftime("%H:%M")
    
    for i in range(14):
        next_date = current_date + timedelta(days=i)
        date_str = next_date.strftime("%Y-%m-%d")
        
        # Пропускаем воскресенье
        if next_date.weekday() == 6:
            continue
            
        # Если проверяем сегодняшний день:
        if i == 0:
            # Если рабочий день уже окончен (после 18:00) или нет свободных слотов — скрываем сегодня
            if current_time_str >= LAST_WORK_HOUR or not get_free_hours(date_str):
                continue
                
        dates.append(date_str)
    return dates

def build_main_markup(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("🦷 Записаться на прием")
    btn2 = types.KeyboardButton("ℹ️ Информация о докторе")
    btn3 = types.KeyboardButton("⭐ Оценить лечение")
    markup.add(btn1, btn2, btn3)
    
    if user_id == MARUF_ID:
        btn4 = types.KeyboardButton("👨‍⚕️ Admin")
        markup.add(btn4)
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = build_main_markup(message.from_user.id)
    bot.send_message(message.chat.id, "Привет! Я бот-помощник стоматолога Маруфа. Чем могу помочь?", reply_markup=markup)

@bot.message_handler(content_types=['text'])
def handle_text(message):
    user_id = message.from_user.id
    
    if message.text == "ℹ️ Информация о докторе":
        info = ("👨‍⚕️ **Доктор Маруф** — семейный стоматолог.\n"
                "🦷 Услуги: Лечение, чистка, удаление, протезирование.\n"
                "📍 Адрес: 1-й квартал Авиасозлар, 12\n"
                "📞 Телефон для связи напрямую: +998 (93) 533-88-59")
        bot.send_message(message.chat.id, info, parse_mode="Markdown")
        
    elif message.text == "🦷 Записаться на прием":
        dates = get_available_dates()
        if not dates:
            bot.send_message(message.chat.id, "К сожалению, на ближайшее время нет свободных дней для записи.")
            return
            
        markup = types.InlineKeyboardMarkup(row_width=2)
        for d in dates:
            dt = datetime.strptime(d, "%Y-%m-%d")
            eng_day = dt.strftime("%a")
            ru_day = RU_DAYS.get(eng_day, eng_day)
            display_date = f"{dt.strftime('%d.%m')} ({ru_day})"
            markup.add(types.InlineKeyboardButton(text=display_date, callback_data=f"date_{d}"))
        bot.send_message(message.chat.id, "Выберите удобный день для записи:", reply_markup=markup)
        
    elif message.text == "⭐ Оценить лечение":
        markup = types.InlineKeyboardMarkup(row_width=5)
        btn_stars = [types.InlineKeyboardButton(text=f"{i}⭐", callback_data=f"stars_{i}") for i in range(1, 6)]
        markup.add(*btn_stars)
        bot.send_message(message.chat.id, "Пожалуйста, оцените качество лечения по 5-балльной шкале:", reply_markup=markup)

    elif message.text == "👨‍⚕️ Admin":
        if user_id == MARUF_ID:
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(text="📋 Расписание (Календарь)", callback_data="admin_calendar"),
                types.InlineKeyboardButton(text="🌟 Посмотреть отзывы", callback_data="admin_reviews"),
                types.InlineKeyboardButton(text="📢 Сделать рассылку пациентам", callback_data="admin_broadcast")
            )
            bot.send_message(message.chat.id, "🔒 Добро пожаловать, Доктор Маруф! Выберите действие:", reply_markup=markup)

# ==========================================
# 👨‍⚕️ АДМИН-ПАНЕЛЬ
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data == "admin_calendar")
def handle_admin_calendar(call):
    dates = []
    current_date = datetime.now().date()
    for i in range(14):
        next_date = current_date + timedelta(days=i)
        if next_date.weekday() != 6:
            dates.append(next_date.strftime("%Y-%m-%d"))
            
    markup = types.InlineKeyboardMarkup(row_width=2)
    for d in dates:
        dt = datetime.strptime(d, "%Y-%m-%d")
        eng_day = dt.strftime("%a")
        ru_day = RU_DAYS.get(eng_day, eng_day)
        display_date = f"{dt.strftime('%d.%m')} ({ru_day})"
        markup.add(types.InlineKeyboardButton(text=display_date, callback_data=f"admin_day_{d}"))
    bot.edit_message_text("📆 Выберите день для просмотра расписания:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_day_'))
def handle_admin_day_schedule(call):
    date_str = call.data.replace("admin_day_", "")
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    display_date = dt.strftime("%d.%m.%Y")
    
    conn = sqlite3.connect('dent.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, time, client_name, client_phone, problem FROM appointments WHERE date = ? AND status = 'active'", (date_str,))
    rows = cursor.fetchall()
    conn.close()
    
    bookings = {row[1]: (row[0], row[2], row[3], row[4]) for row in rows}
    
    schedule_msg = f"📋 **Расписание на {display_date}:**\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for hour in WORKING_HOURS:
        if hour in bookings:
            app_id, name, phone, prob = bookings[hour]
            schedule_msg += f"🔴 **{hour}** — {name} ({phone})\n💬 _{prob}_\n\n"
            markup.add(types.InlineKeyboardButton(text=f"❌ Отменить {hour} ({name})", callback_data=f"cancel_app_{app_id}"))
        else:
            schedule_msg += f"🟢 **{hour}** — Свободно\n\n"
            
    markup.add(types.InlineKeyboardButton(text="⬅️ Назад к выбору дней", callback_data="admin_calendar"))
    bot.edit_message_text(schedule_msg, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_app_'))
def handle_cancel_appointment(call):
    app_id = int(call.data.replace("cancel_app_", ""))
    
    conn = sqlite3.connect('dent.db')
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, date, time, client_name FROM appointments WHERE id = ?", (app_id,))
    row = cursor.fetchone()
    
    if row:
        user_id, date_str, time_str, client_name = row
        cursor.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (app_id,))
        conn.commit()
        
        # Уведомляем клиента об отмене
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m")
            bot.send_message(user_id, f"⚠️ Уважаемый(ая) {client_name}, ваша запись на {dt} в {time_str} была отменена клиникой.")
        except Exception:
            pass
            
        bot.answer_callback_query(call.id, "Запись успешно отменена!")
    conn.close()
    
    handle_admin_calendar(call)

@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast")
def start_broadcast(call):
    msg = bot.send_message(call.message.chat.id, "Введите текст сообщения для рассылки всем пациентам (или /cancel для отмены):")
    bot.register_next_step_handler(msg, process_broadcast)

def process_broadcast(message):
    if message.text == "/cancel":
        bot.send_message(message.chat.id, "Рассылка отменена.")
        return
        
    conn = sqlite3.connect('dent.db')
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT user_id FROM appointments WHERE user_id IS NOT NULL")
    users = cursor.fetchall()
    conn.close()
    
    count = 0
    for u in users:
        try:
            bot.send_message(u[0], message.text)
            count += 1
            time.sleep(0.05)
        except Exception:
            pass
            
    bot.send_message(message.chat.id, f"✅ Рассылка завершена. Сообщение получили: {count} человек.")

@bot.callback_query_handler(func=lambda call: call.data == "admin_reviews")
def handle_admin_reviews_list(call):
    conn = sqlite3.connect('dent.db')
    cursor = conn.cursor()
    cursor.execute("SELECT client_name, client_username, stars, text FROM reviews ORDER BY id DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        bot.send_message(call.message.chat.id, "💬 Отзывов пока нет.")
    else:
        review_msg = "🌟 **Последние 10 отзывов от пациентов:**\n\n"
        for row in rows:
            stars_display = "⭐" * row[2]
            review_msg += f"👤 **{row[0]}** ({row[1]})\n📊 Оценка: {stars_display}\n💬 Отзыв: _{row[3]}_\n───────────────\n"
        bot.send_message(call.message.chat.id, review_msg, parse_mode="Markdown")
    bot.answer_callback_query(call.id)

# ==========================================
# ⭐ ОТЗЫВЫ И ЗАПИСЬ
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith('stars_'))
def handle_stars(call):
    stars = int(call.data.split('_')[1])
    bot.delete_message(call.message.chat.id, call.message.message_id)
    msg = bot.send_message(call.message.chat.id, f"Вы поставили {stars}⭐! Напишите краткий отзыв о лечении (или отправьте /skip):")
    bot.register_next_step_handler(msg, process_review, stars)

def process_review(message, stars):
    review_text = message.text if message.text != "/skip" else "Без текстового отзыва"
    name = message.from_user.first_name or "Пациент"
    username = f"@{message.from_user.username}" if message.from_user.username else "Нет юзернейма"
    
    conn = sqlite3.connect('dent.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO reviews (client_name, client_username, stars, text) VALUES (?, ?, ?, ?)', 
                   (name, username, stars, review_text))
    conn.commit()
    conn.close()
    
    bot.send_message(message.chat.id, "❤️ Спасибо огромное за ваш отзыв!")
    
    stars_display = "⭐" * stars
    maruf_review_msg = (f"🌟 **НОВЫЙ ОТЗЫВ ОТ ПАЦИЕНТА!**\n\n"
                        f"👤 **От кого:** {name} ({username})\n"
                        f"📊 **Оценка:** {stars_display} ({stars} из 5)\n"
                        f"💬 **Текст отзыва:** {review_text}")
    bot.send_message(MARUF_ID, maruf_review_msg, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('date_'))
def handle_date_selection(call):
    date_str = call.data.split('_')[1]
    free_hours = get_free_hours(date_str)
    
    if not free_hours:
        bot.answer_callback_query(call.id, "Извините, на этот день свободного времени нет!")
        return

    markup = types.InlineKeyboardMarkup(row_width=3)
    for hour in free_hours:
        markup.add(types.InlineKeyboardButton(text=hour, callback_data=f"time_{date_str}_{hour}"))
    
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    display_date = dt.strftime("%d.%m")
    bot.edit_message_text(f"Вы выбрали дату {display_date}. Теперь выберите свободное время:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('time_'))
def handle_time_selection(call):
    _, date_str, hour_str = call.data.split('_')
    msg = bot.send_message(call.message.chat.id, "Введите ваше Имя и Фамилию:")
    bot.register_next_step_handler(msg, process_name, date_str, hour_str)

def process_name(message, date_str, hour_str):
    name = message.text
    msg = bot.send_message(message.chat.id, f"Приятно познакомиться, {name}! Теперь напишите ваш номер телефона:")
    bot.register_next_step_handler(msg, process_phone, date_str, hour_str, name)

def process_phone(message, date_str, hour_str, name):
    phone = message.text
    msg = bot.send_message(message.chat.id, "Опишите кратко вашу проблему или причину обращения:")
    bot.register_next_step_handler(msg, process_problem, date_str, hour_str, name, phone)

def process_problem(message, date_str, hour_str, name, phone):
    problem = message.text
    user_id = message.from_user.id
    username = f"@{message.from_user.username}" if message.from_user.username else "Нет юзернейма"
    
    conn = sqlite3.connect('dent.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO appointments (date, time, user_id, client_name, client_phone, client_username, problem)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (date_str, hour_str, user_id, name, phone, username, problem))
    conn.commit()
    conn.close()
    
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    display_date = dt.strftime("%d.%m")
    bot.send_message(
        message.chat.id, 
        f"✅ Вы успешно записаны!\n📅 Дата: {display_date}\n⏰ Время: {hour_str}\n🦷 Доктор ждет вас!"
    )
    
    admin_msg = (
        f"🚨 **НОВАЯ ЗАПИСЬ НА ПРИЕМ!**\n\n"
        f"📅 **Дата:** {display_date} в {hour_str}\n"
        f"👤 **Пациент:** {name} ({username})\n"
        f"📞 **Телефон:** {phone}\n"
        f"💬 **Проблема:** {problem}"
    )
    bot.send_message(MARUF_ID, admin_msg, parse_mode="Markdown")

# ==========================================
# ⏰ НАПОМИНАНИЯ (ПАЦИЕНТАМ И ВРАЧУ)
# ==========================================
def check_reminders():
    conn = sqlite3.connect('dent.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, date, time, user_id, client_name, client_phone FROM appointments WHERE status = 'active'")
    rows = cursor.fetchall()
    
    now = datetime.now()
    
    for row in rows:
        app_id, date_str, time_str, user_id, client_name, client_phone = row
        try:
            app_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            continue
            
        diff = app_datetime - now
        
        # Напоминание за 24 часа (окно в 1 час)
        if timedelta(hours=23, minutes=30) <= diff <= timedelta(hours=24, minutes=30):
            cursor.execute("SELECT notified_day FROM appointments WHERE id = ?", (app_id,))
            notified = cursor.fetchone()
            if notified and not notified[0]:
                # Сообщение пациенту
                if user_id:
                    try:
                        bot.send_message(user_id, f"🔔 **Напоминание:** Завтра в {time_str} у вас прием у доктора Маруфа.")
                    except Exception:
                        pass
                # Сообщение врачу
                bot.send_message(MARUF_ID, f"🔔 **Напоминание:** Завтра в {time_str} приём у пациента {client_name} ({client_phone}).")
                cursor.execute("UPDATE appointments SET notified_day = 1 WHERE id = ?", (app_id,))
                conn.commit()

        # Напоминание за 1 час (окно в 20 минут)
        if timedelta(minutes=50) <= diff <= timedelta(hours=1, minutes=10):
            cursor.execute("SELECT notified_hour FROM appointments WHERE id = ?", (app_id,))
            notified = cursor.fetchone()
            if notified and not notified[0]:
                # Сообщение пациенту
                if user_id:
                    try:
                        bot.send_message(user_id, f"⏰ **Напоминание:** Ровно через 1 час ({time_str}) у вас прием у доктора Маруфа!")
                    except Exception:
                        pass
                # Сообщение врачу
                bot.send_message(MARUF_ID, f"⏰ **Внимание!** Через 1 час ({time_str}) приём у пациента {client_name} ({client_phone}).")
                cursor.execute("UPDATE appointments SET notified_hour = 1 WHERE id = ?", (app_id,))
                conn.commit()
                
    conn.close()

# ==========================================
# 🚀 ЗАПУСК БОТА И ПЛАНИРОВЩИКА
# ==========================================
if __name__ == "__main__":
    init_db()  
    
    # Запуск фонового веб-сервера для Render
    keep_alive()
    
    # Настройка планировщика
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_reminders, 'interval', minutes=1)
    scheduler.start()
    
    print("Бот и веб-сервер запущены...")
    bot.infinity_polling(skip_pending=True)
