import telebot
from telebot import types
import sqlite3
from datetime import datetime, timedelta

# ==========================================
# ⚙️ НАСТРОЙКИ (твои данные сохранены)
# ==========================================
BOT_TOKEN = "8657040766:AAHeBxOmF86zv__MaIzayHuoOoZ5B7ycSeo"
MARUF_ID = 934720885  
# ==========================================

bot = telebot.TeleBot(BOT_TOKEN)

RU_DAYS = {
    "Mon": "Пн", "Tue": "Вт", "Wed": "Ср", "Thu": "Чт", "Fri": "Пт", "Sat": "Сб", "Sun": "Вс"
}

WORKING_HOURS = ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00"]

def init_db():
    conn = sqlite3.connect('dent.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            time TEXT,
            client_name TEXT,
            client_phone TEXT,
            client_username TEXT,
            problem TEXT,
            status TEXT DEFAULT 'active'
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

def get_available_dates():
    dates = []
    current_date = datetime.now()
    for i in range(14):
        next_date = current_date + timedelta(days=i)
        if next_date.weekday() != 6:  # Воскресенье — выходной
            dates.append(next_date.strftime("%Y-%m-%d"))
    return dates

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

def build_main_markup(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("🦷 Записаться на прием")
    btn2 = types.KeyboardButton("ℹ️ Информация о докторе")
    btn3 = types.KeyboardButton("⭐ Оценить лечение")
    markup.add(btn1, btn2, btn3)
    
    if user_id == MARUF_ID or user_id == 8657040766:
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
        bot.send_message(message.chat.id, "Пожалуйста, оцените качество лечения по 5-бальной шкале:", reply_markup=markup)

    elif message.text == "👨‍⚕️ Admin":
        if user_id == MARUF_ID or user_id == 8657040766:
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(
                types.InlineKeyboardButton(text="📋 Расписание на 2 недели (Календарь)", callback_data="admin_calendar"),
                types.InlineKeyboardButton(text="🌟 Посмотреть отзывы", callback_data="admin_reviews")
            )
            bot.send_message(message.chat.id, "🔒 Добро пожаловать, Доктор Маруф! Выберите действие:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_calendar")
def handle_admin_calendar(call):
    dates = get_available_dates()
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
    cursor.execute("SELECT time, client_name, client_phone, problem FROM appointments WHERE date = ? AND status = 'active'", (date_str,))
    bookings = {row[0]: (row[1], row[2], row[3]) for row in cursor.fetchall()}
    conn.close()
    
    schedule_msg = f"📋 **Расписание на {display_date}:**\n\n"
    for hour in WORKING_HOURS:
        if hour in bookings:
            name, phone, prob = bookings[hour]
            schedule_msg += f"🔴 **{hour}** — Занято: {name} ({phone})\n💬 Проблема: _{prob}_\n\n"
        else:
            schedule_msg += f"🟢 **{hour}** — Свободно\n\n"
            
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="⬅️ Назад к выбору дней", callback_data="admin_calendar"))
    
    bot.edit_message_text(schedule_msg, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)
    bot.answer_callback_query(call.id)

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
        bot.send_message(call.message.chat.id, review_msg)
    bot.answer_callback_query(call.id)

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
    bot.send_message(MARUF_ID, maruf_review_msg)

@bot.callback_query_handler(func=lambda call: call.data.startswith('date_'))
def handle_date_selection(call):
    date_str = call.data.split('_')[1]
    free_hours = get_free_hours(date_str)
    
    if not free_hours:
        bot.answer_callback_query(call.id, "Извините, на этот день свободных мест нет!")
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
    username = f"@{message.from_user.username}" if message.from_user.username else "Нет юзернейма"
    
    conn = sqlite3.connect('dent.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO appointments (date, time, client_name, client_phone, client_username, problem)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (date_str, hour_str, name, phone, username, problem))
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
# 🚀 ЗАПУСК БОТА
# ==========================================
if __name__ == "__main__":
    init_db()  
    print("Бот запущен...")
    bot.infinity_polling(skip_pending=True)
