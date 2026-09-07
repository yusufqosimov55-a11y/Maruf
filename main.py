import telebot
from telebot import types
import sqlite3
from datetime import datetime, timedelta

# ==========================================
# ⚙️ НАСТРОЙКИ (ДАННЫЕ УЖЕ ВСТАВЛЕНЫ!)
# ==========================================
BOT_TOKEN = "8657040766:AAHeBxOmF86zv__MaIzayHuoOoZ5B7ycSeo"
MARUF_ID = 8657040766  
# ==========================================

bot = telebot.TeleBot(BOT_TOKEN)

# База данных прямо внутри папки бота
def init_db():
    conn = sqlite3.connect('booking.db')
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
    conn.commit()
    conn.close()

# Доступные часы приема
WORKING_HOURS = ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00"]

# Генерация дат на 14 дней вперед (исключая воскресенья)
def get_available_dates():
    dates = []
    current_date = datetime.now()
    for i in range(14):
        next_date = current_date + timedelta(days=i)
        if next_date.weekday() != 6:  # 6 — это воскресенье, Маруф отдыхает
            dates.append(next_date.strftime("%Y-%m-%d"))
    return dates

# Поиск свободных часов на конкретную дату
def get_free_hours(date_str):
    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    cursor.execute("SELECT time FROM appointments WHERE date = ? AND status = 'active'", (date_str,))
    booked_hours = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    return [hour for hour in WORKING_HOURS if hour not in booked_hours]

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = types.KeyboardButton("🦷 Записаться на прием")
    btn2 = types.KeyboardButton("ℹ️ Информация о докторе")
    markup.add(btn1, btn2)
    bot.send_message(message.chat.id, f"Привет! Я бот-помощник стоматолога Маруфа. Чем могу помочь?", reply_markup=markup)

@bot.message_handler(content_types=['text'])
def handle_text(message):
    if message.text == "ℹ️ Информация о докторе":
        info = ("👨‍⚕️ **Доктор Маруф** — семейный стоматолог.\n"
                "🦷 Услуги: Лечение, чистка, удаление, протезирование.\n"
                "📍 Адрес: Семейная стоматологическая клиника.\n"
                "📞 Телефон для связи напрямую: +998 (ХХ) ХХХ-ХХ-ХХ")
        bot.send_message(message.chat.id, info, parse_mode="Markdown")
        
    elif message.text == "🦷 Записаться на прием":
        dates = get_available_dates()
        markup = types.InlineKeyboardMarkup(row_width=2)
        for d in dates:
            display_date = datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m (%a)")
            markup.add(types.InlineKeyboardButton(text=display_date, callback_data=f"date_{d}"))
        bot.send_message(message.chat.id, "Выберите удобный день для записи:", reply_markup=markup)

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
    
    display_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m")
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
    msg = bot.send_message(message.chat.id, "Коротко опишите вашу проблему (например: болит зуб, чистка, осмотр):")
    bot.register_next_step_handler(msg, process_problem, date_str, hour_str, name, phone)

def process_problem(message, date_str, hour_str, name, phone):
    problem = message.text
    username = f"@{message.from_user.username}" if message.from_user.username else "Нет юзернейма"
    
    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO appointments (date, time, client_name, client_phone, client_username, problem)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (date_str, hour_str, name, phone, username, problem))
    appointment_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    display_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m")
    
    bot.send_message(message.chat.id, f"✅ Вы успешно записаны!\n📅 Дата: {display_date}\n⏰ Время: {hour_str}\n\nДоктор Маруф ждет вас!")
    
    maruf_msg = (f"🆕 **НОВАЯ ЗАПИСЬ НА ПРИЕМ!**\n\n"
                 f"📅 **Дата/Время:** {display_date} в {hour_str}\n"
                 f"👤 **Пациент:** {name}\n"
                 f"📞 **Телефон:** {phone}\n"
                 f"💬 **Телеграм:** {username}\n"
                 f"🦷 **Проблема:** {problem}")
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(text="❌ Отменить эту запись", callback_data=f"cancel_{appointment_id}_{message.chat.id}"))
    
    bot.send_message(MARUF_ID, maruf_msg, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_'))
def handle_cancel(call):
    _, app_id, client_chat_id = call.data.split('_')
    
    conn = sqlite3.connect('booking.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (app_id,))
    conn.commit()
    conn.close()
    
    bot.edit_message_text(call.message.text + "\n\n🛑 **ЗАПИСЬ ОТМЕНЕНА ДОКТОРОМ**", call.message.chat.id, call.message.message_id)
    
    try:
        bot.send_message(client_chat_id, "⚠️ Извините, ваша запись к доктору Маруфу была отменена. Пожалуйста, выберите другое время через /start.")
    except Exception:
        pass

if __name__ == '__main__':
    init_db()
    print("Бот успешно запущен...")
    bot.infinity_polling()
