# -*- coding: utf-8 -*-

import os
import html
import logging
import re
from datetime import datetime, timedelta, time
from threading import Lock, Thread
from zoneinfo import ZoneInfo

from flask import Flask
from telebot import TeleBot, types
from apscheduler.schedulers.background import BackgroundScheduler
import psycopg2
from psycopg2 import errors
from psycopg2.extras import RealDictCursor

# ============================================================
# Dr. Maruf / Stoma dent Telegram bot
# ============================================================

BOT_VERSION = "2026-09-12-fixed-v3"

TZ = ZoneInfo(os.getenv("TZ", "Asia/Tashkent"))
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
DOCTOR_CHAT_ID_RAW = os.getenv("DOCTOR_CHAT_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в переменных окружения")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL не задан в переменных окружения")
if not DOCTOR_CHAT_ID_RAW:
    raise RuntimeError("DOCTOR_CHAT_ID не задан в переменных окружения")
try:
    DOCTOR_CHAT_ID = int(DOCTOR_CHAT_ID_RAW)
except ValueError as exc:
    raise RuntimeError("DOCTOR_CHAT_ID должен быть целым числом") from exc

CLINIC_NAME = os.getenv("CLINIC_NAME", "Stoma dent")
CLINIC_ADDRESS = os.getenv(
    "CLINIC_ADDRESS",
    "г. Ташкент, Яшнабадский район, 1-й квартал Авиасозлар, 12",
)
CLINIC_LANDMARK = os.getenv("CLINIC_LANDMARK", "метро Тузель, 1-й этаж")
CLINIC_PHONE = os.getenv("CLINIC_PHONE", "+998 (93) 508-11-88")
CLINIC_HOURS = os.getenv("CLINIC_HOURS", "Ежедневно с 09:00 до 19:00")

# Coordinates are intentionally not hard-coded until the exact clinic pin is verified.
CLINIC_LAT = os.getenv("CLINIC_LAT")
CLINIC_LON = os.getenv("CLINIC_LON")

OPEN_WEEKDAYS = {
    int(x.strip())
    for x in os.getenv("OPEN_WEEKDAYS", "0,1,2,3,4,5,6").split(",")
    if x.strip().isdigit() and 0 <= int(x.strip()) <= 6
}
BOOKING_DAYS = int(os.getenv("BOOKING_DAYS", "5"))

SLOTS = ["09:00", "10:30", "12:00", "14:00", "15:30", "17:00"]
SERVICES = {
    "1": "🦷 Лечение зуба",
    "2": "✨ Чистка",
    "3": "😁 Отбеливание",
    "4": "👑 Коронка",
    "5": "❌ Удаление",
    "6": "💊 Противовоспалительное лечение",
    "7": "❓ Другое",
}

MAX_NAME_LEN = 120
MAX_PHONE_LEN = 30
MAX_PROBLEM_LEN = 1000
MAX_REVIEW_LEN = 1500
MAX_ACTIVE_APPOINTMENTS_PER_USER = int(os.getenv("MAX_ACTIVE_APPOINTMENTS_PER_USER", "3"))
CANCEL_MINUTES_BEFORE = int(os.getenv("CANCEL_MINUTES_BEFORE", "60"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("stoma_dent_bot")

bot = TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)
user_data = {}
state_lock = Lock()

DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS_RU = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


# ============================================================
# Basic helpers
# ============================================================

def now_local():
    return datetime.now(TZ)


def safe_text(value, default=""):
    return html.escape(str(value if value is not None else default))


def format_dt(dt):
    return dt.astimezone(TZ).strftime("%d.%m.%Y %H:%M")


def get_db_connection():
    conn = psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
        connect_timeout=10,
    )
    conn.autocommit = False
    return conn


def set_state(chat_id, **values):
    with state_lock:
        user_data.setdefault(chat_id, {}).update(values)


def get_state(chat_id):
    with state_lock:
        return dict(user_data.get(chat_id, {}))


def clear_state(chat_id):
    with state_lock:
        user_data.pop(chat_id, None)


def cancel_steps(chat_id):
    try:
        bot.clear_step_handler_by_chat_id(chat_id)
    except Exception:
        logger.exception("Не удалось очистить обработчик шага")


def reset_flow(chat_id):
    cancel_steps(chat_id)
    clear_state(chat_id)


def is_doctor(chat_id):
    return chat_id == DOCTOR_CHAT_ID


def normalize_phone(raw):
    if not raw:
        return None
    phone = re.sub(r"[^\d+]", "", str(raw).strip())
    # Uzbek local formats: 90XXXXXXX (9 digits), 8 90XXXXXXX (10 digits),
    # 99890XXXXXXX (12 digits) and +99890XXXXXXX (13 characters).
    if phone.startswith("8") and len(phone) == 10:
        phone = "+998" + phone[1:]
    elif phone.isdigit() and len(phone) == 9:
        phone = "+998" + phone
    elif phone.startswith("998") and len(phone) == 12:
        phone = "+" + phone
    elif phone.startswith("+998") and len(phone) == 13:
        pass
    elif phone.startswith("+") and 10 <= len(phone) <= 16:
        pass
    else:
        return None
    return phone


def valid_name(text):
    text = " ".join((text or "").split())
    if len(text) < 3 or len(text) > MAX_NAME_LEN:
        return False
    return bool(re.fullmatch(r"[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳІіЪъЬь\- ']+", text))


def valid_problem(text):
    return bool(text and len(text.strip()) <= MAX_PROBLEM_LEN)


def appointment_dt_from_state(data):
    naive = datetime.strptime(
        f"{data['date']} {data['time']}", "%d.%m.%Y %H:%M"
    )
    return naive.replace(tzinfo=TZ)


def send_main_menu(chat_id, text):
    bot.send_message(chat_id, text, reply_markup=get_main_keyboard())


# ============================================================
# Flask health endpoint
# ============================================================

@app.route("/")
def home():
    return "Telegram-бот Stoma dent работает!", 200


@app.route("/health")
def health():
    return {"status": "ok"}, 200


def run_flask():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, use_reloader=False)


def keep_alive():
    Thread(target=run_flask, daemon=True).start()


# ============================================================
# Database initialization + migration
# ============================================================

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                patient_name VARCHAR(120) NOT NULL,
                phone_number VARCHAR(30) NOT NULL,
                username VARCHAR(255) DEFAULT '',
                service VARCHAR(120) NOT NULL DEFAULT 'Консультация',
                problem VARCHAR(1000) NOT NULL DEFAULT '',
                appointment_at TIMESTAMPTZ,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                reminded_24h BOOLEAN NOT NULL DEFAULT FALSE,
                reminded_2h BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                status_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                rating SMALLINT NOT NULL,
                comment VARCHAR(1500) NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Upgrade the original project without destroying its existing data.
        cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS appointment_at TIMESTAMPTZ")
        cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminded_2h BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminded_24h BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("ALTER TABLE reviews ADD COLUMN IF NOT EXISTS created_at_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()")

        # Legacy project stored appointment_time as DD.MM.YYYY HH:MM text.
        cur.execute("""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='appointments' AND column_name='appointment_time'
                ) THEN
                    UPDATE appointments
                    SET appointment_at =
                        to_timestamp(appointment_time, 'DD.MM.YYYY HH24:MI') AT TIME ZONE 'Asia/Tashkent'
                    WHERE appointment_at IS NULL
                      AND appointment_time IS NOT NULL
                      AND appointment_time ~ '^\\d{2}\\.\\d{2}\\.\\d{4} \\d{2}:\\d{2}$';
                END IF;
            END $$;
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_appointments_user_status_time
            ON appointments(user_id, status, appointment_at)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_appointments_status_time
            ON appointments(status, appointment_at)
        """)
        # Remove impossible duplicate active slots created by the old race-prone version
        # before creating the database-level uniqueness guarantee. Keep the earliest row.
        cur.execute("""
            WITH ranked AS (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY appointment_at ORDER BY id) AS rn
                FROM appointments
                WHERE status='active' AND appointment_at IS NOT NULL
            )
            UPDATE appointments a
            SET status='cancelled', status_updated_at=NOW()
            FROM ranked r
            WHERE a.id=r.id AND r.rn>1
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_active_appointment_slot
            ON appointments(appointment_at)
            WHERE status='active' AND appointment_at IS NOT NULL
        """)

        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname='reviews_rating_range'
                ) THEN
                    ALTER TABLE reviews
                    ADD CONSTRAINT reviews_rating_range CHECK (rating BETWEEN 1 AND 5);
                END IF;
            END $$;
        """)

        conn.commit()
        logger.info("База данных инициализирована/обновлена")
    except Exception:
        conn.rollback()
        logger.exception("Не удалось инициализировать базу данных")
        raise
    finally:
        cur.close()
        conn.close()


def create_appointment(data, user_id, username):
    try:
        appointment_at = appointment_dt_from_state(data)
    except (KeyError, ValueError):
        return None, "invalid"

    if appointment_at <= now_local():
        return None, "invalid"
    if appointment_at.strftime("%H:%M") not in SLOTS:
        return None, "invalid"
    if appointment_at.weekday() not in OPEN_WEEKDAYS:
        return None, "invalid"

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Transaction-level advisory lock makes the check+insert atomic even under
        # simultaneous Telegram callbacks. The unique index is the second safety net.
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (appointment_at.isoformat(),))
        cur.execute("""
            SELECT id FROM appointments
            WHERE appointment_at=%s AND status='active'
            FOR UPDATE
        """, (appointment_at,))
        if cur.fetchone():
            conn.rollback()
            return None, "taken"

        cur.execute("""
            SELECT COUNT(*) AS cnt FROM appointments
            WHERE user_id=%s AND status='active' AND appointment_at >= NOW()
        """, (user_id,))
        if cur.fetchone()["cnt"] >= MAX_ACTIVE_APPOINTMENTS_PER_USER:
            conn.rollback()
            return None, "limit"

        cur.execute("""
            INSERT INTO appointments (
                user_id, patient_name, phone_number, username,
                service, problem, appointment_at, status
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,'active')
            RETURNING id
        """, (
            user_id, data["name"], data["phone"], username or "",
            data.get("service", "Консультация"), data["problem"], appointment_at,
        ))
        app_id = cur.fetchone()["id"]
        conn.commit()
        return app_id, "ok"
    except errors.UniqueViolation:
        conn.rollback()
        return None, "taken"
    except Exception:
        conn.rollback()
        logger.exception("Appointment insert failed")
        return None, "error"
    finally:
        cur.close()
        conn.close()


# ============================================================
# Keyboards
# ============================================================

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


def back_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row("⬅️ Отмена")
    return markup


# ============================================================
# Start / navigation
# ============================================================

@bot.message_handler(commands=["start"])
def start_cmd(message):
    reset_flow(message.chat.id)
    if is_doctor(message.chat.id):
        bot.send_message(
            message.chat.id,
            "👨‍⚕️ Здравствуйте, доктор Маруф!\nПанель врача готова.",
            reply_markup=get_doctor_keyboard(),
        )
    else:
        bot.send_message(
            message.chat.id,
            "Здравствуйте! Вас приветствует бот стоматологической клиники "
            "доктора Маруфа. 🦷\n\nВыберите действие в меню ниже.",
            reply_markup=get_main_keyboard(),
        )


@bot.message_handler(commands=["cancel"])
def cancel_command(message):
    reset_flow(message.chat.id)
    keyboard = get_doctor_keyboard() if is_doctor(message.chat.id) else get_main_keyboard()
    bot.send_message(message.chat.id, "❌ Текущая операция отменена.", reply_markup=keyboard)


@bot.message_handler(func=lambda m: m.text == "⬅️ Отмена")
def cancel_button(message):
    reset_flow(message.chat.id)
    keyboard = get_doctor_keyboard() if is_doctor(message.chat.id) else get_main_keyboard()
    bot.send_message(message.chat.id, "❌ Отменено.", reply_markup=keyboard)


@bot.message_handler(func=lambda m: m.text in {
    "📅 Записаться на приём", "📋 Мои записи", "🩺 Услуги и лечение",
    "📍 Как нас найти", "⭐ Оценить лечение / Отзыв", "ℹ️ Информация",
    "📋 Панель врача", "📊 Статистика", "📱 Главное меню клиента",
})
def menu_router(message):
    reset_flow(message.chat.id)
    text = message.text
    if text == "📅 Записаться на приём":
        start_booking(message)
    elif text == "📋 Мои записи":
        show_my_appointments(message)
    elif text == "🩺 Услуги и лечение":
        services_info(message)
    elif text == "📍 Как нас найти":
        send_location(message)
    elif text == "⭐ Оценить лечение / Отзыв":
        ask_rating(message)
    elif text == "ℹ️ Информация":
        clinic_info(message)
    elif text == "📋 Панель врача":
        doctor_panel_menu(message)
    elif text == "📊 Статистика":
        show_statistics(message)
    elif text == "📱 Главное меню клиента":
        show_client_menu(message)


def show_client_menu(message):
    send_main_menu(message.chat.id, "Переключено на меню клиента.")


def services_info(message):
    text = (
        f"🏥 <b>Услуги {safe_text(CLINIC_NAME)}:</b>\n\n"
        "• Лечение зуба\n• Профессиональная чистка\n• Отбеливание\n"
        "• Коронки\n• Удаление\n• Противовоспалительное лечение\n\n"
        "Нажмите «📅 Записаться на приём», чтобы выбрать услугу и время."
    )
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=get_main_keyboard())


def clinic_info(message):
    text = (
        f"👨‍⚕️ <b>{safe_text(CLINIC_NAME)}</b>\n\n"
        f"📍 <b>Адрес:</b> {safe_text(CLINIC_ADDRESS)}\n"
        f"🚇 <b>Ориентир:</b> {safe_text(CLINIC_LANDMARK)}\n"
        f"⏰ <b>Режим:</b> {safe_text(CLINIC_HOURS)}\n"
        f"📞 <b>Телефон:</b> {safe_text(CLINIC_PHONE)}"
    )
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=get_main_keyboard())


def send_location(message):
    chat_id = message.chat.id
    bot.send_message(
        chat_id,
        f"📍 <b>{safe_text(CLINIC_NAME)}</b>\n{safe_text(CLINIC_ADDRESS)}\n"
        f"Ориентир: {safe_text(CLINIC_LANDMARK)}",
        parse_mode="HTML",
    )
    if CLINIC_LAT and CLINIC_LON:
        try:
            bot.send_location(chat_id, float(CLINIC_LAT), float(CLINIC_LON))
        except (ValueError, TypeError):
            logger.warning("Некорректные координаты клиники")
    else:
        bot.send_message(
            chat_id,
            "📌 Точная геометка пока отключена, чтобы не отправлять непроверенную точку.\n"
            f"Можно найти клинику по названию «{safe_text(CLINIC_NAME)}» и адресу выше.",
            reply_markup=get_main_keyboard(),
        )


# ============================================================
# Booking flow
# ============================================================

def start_booking(message):
    chat_id = message.chat.id
    reset_flow(chat_id)
    set_state(chat_id, flow="booking")

    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Продолжить", callback_data="consent:yes"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="consent:no"),
    )
    bot.send_message(
        chat_id,
        "🦷 <b>Запись на приём</b>\n\n"
        "Для записи бот попросит ФИО, телефон и краткую причину визита. "
        "Эти данные используются для организации приёма и связи с клиникой.\n\n"
        "Продолжая, вы соглашаетесь на обработку этих данных для записи.",
        parse_mode="HTML",
        reply_markup=markup,
    )


def show_service_selection(chat_id, message_id=None):
    markup = types.InlineKeyboardMarkup()
    items = list(SERVICES.items())
    for i in range(0, len(items), 2):
        row = [
            types.InlineKeyboardButton(label, callback_data=f"srv:{key}")
            for key, label in items[i:i + 2]
        ]
        markup.row(*row)
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="booking:cancel"))
    text = "Выберите услугу:"
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data in {"consent:yes", "consent:no"})
def booking_consent(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    if call.data == "consent:no":
        reset_flow(chat_id)
        bot.edit_message_text("❌ Запись отменена.", chat_id, call.message.message_id)
        bot.send_message(chat_id, "Главное меню:", reply_markup=get_main_keyboard())
        return
    show_service_selection(chat_id, call.message.message_id)


def next_open_dates(count=BOOKING_DAYS):
    result = []
    current = now_local().date()
    while len(result) < count:
        current += timedelta(days=1)
        if current.weekday() in OPEN_WEEKDAYS:
            result.append(current)
    return result


@bot.callback_query_handler(func=lambda call: call.data.startswith("srv:"))
def process_service_choice(call):
    key = call.data.split(":", 1)[1]
    if key not in SERVICES:
        bot.answer_callback_query(call.id, "Услуга недоступна.")
        return
    set_state(call.message.chat.id, flow="booking", service=SERVICES[key])
    bot.answer_callback_query(call.id)
    show_date_selection(call.message.chat.id, call.message.message_id)


def show_date_selection(chat_id, message_id=None):
    markup = types.InlineKeyboardMarkup()
    for day in next_open_dates():
        label = f"📅 {DAYS_RU[day.weekday()]}, {day.day} {MONTHS_RU[day.month - 1]}"
        markup.add(types.InlineKeyboardButton(label, callback_data=f"date:{day:%d.%m.%Y}"))
    text = "Выберите дату для визита:"
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
            return
        except Exception:
            pass
    bot.send_message(chat_id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("date:"))
def choose_date(call):
    value = call.data.split(":", 1)[1]
    try:
        selected = datetime.strptime(value, "%d.%m.%Y").date()
    except ValueError:
        bot.answer_callback_query(call.id, "Неверная дата.")
        return
    if selected not in next_open_dates(BOOKING_DAYS + 2):
        bot.answer_callback_query(call.id, "Эта дата больше недоступна.")
        return
    set_state(call.message.chat.id, date=value)
    bot.answer_callback_query(call.id)
    show_time_selection(call.message.chat.id, call.message.message_id, selected)


def show_time_selection(chat_id, message_id, date_obj):
    start = datetime.combine(date_obj, time.min).replace(tzinfo=TZ)
    end = start + timedelta(days=1)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT appointment_at FROM appointments WHERE status='active' AND appointment_at >= %s AND appointment_at < %s",
                (start, end),
            )
            booked = {
                row["appointment_at"].astimezone(TZ).strftime("%H:%M")
                for row in cur.fetchall()
                if row["appointment_at"] is not None
            }
        finally:
            cur.close()
            conn.close()
    except Exception:
        logger.exception("Не удалось загрузить свободное время")
        bot.edit_message_text(
            "❌ Не удалось загрузить свободное время. Попробуйте ещё раз через минуту.",
            chat_id, message_id,
        )
        return

    available = [slot for slot in SLOTS if slot not in booked]
    markup = types.InlineKeyboardMarkup()
    if not available:
        markup.add(types.InlineKeyboardButton("⬅️ Другая дата", callback_data="back:dates"))
        bot.edit_message_text(
            f"На {date_obj:%d.%m.%Y} свободных времён нет.",
            chat_id, message_id, reply_markup=markup,
        )
        return

    row = []
    for slot in available:
        row.append(types.InlineKeyboardButton(slot, callback_data=f"time:{slot}"))
        if len(row) == 2:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)
    markup.add(types.InlineKeyboardButton("⬅️ Другая дата", callback_data="back:dates"))

    bot.edit_message_text(
        f"📅 Дата: <b>{date_obj:%d.%m.%Y}</b>\n\nВыберите время:",
        chat_id, message_id, reply_markup=markup, parse_mode="HTML",
    )


@bot.callback_query_handler(func=lambda call: call.data == "back:dates")
def back_dates(call):
    bot.answer_callback_query(call.id)
    show_date_selection(call.message.chat.id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("time:"))
def choose_time(call):
    chat_id = call.message.chat.id
    selected = call.data.split(":", 1)[1]
    if selected not in SLOTS:
        bot.answer_callback_query(call.id, "Неверное время.")
        return
    data = get_state(chat_id)
    if not data.get("service") or not data.get("date"):
        reset_flow(chat_id)
        bot.answer_callback_query(call.id, "Сессия устарела.")
        send_main_menu(chat_id, "Пожалуйста, начните запись заново.")
        return
    set_state(chat_id, time=selected)
    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass
    msg = bot.send_message(
        chat_id,
        "👤 Введите ваше <b>ФИО</b> (Имя и Фамилия):",
        parse_mode="HTML", reply_markup=back_keyboard(),
    )
    bot.register_next_step_handler(msg, process_name)


def process_name(message):
    chat_id = message.chat.id
    if message.text == "⬅️ Отмена":
        cancel_button(message)
        return
    name = " ".join((message.text or "").split())
    if not valid_name(name):
        msg = bot.send_message(
            chat_id,
            f"⚠️ Введите корректное ФИО (до {MAX_NAME_LEN} символов).",
            reply_markup=back_keyboard(),
        )
        bot.register_next_step_handler(msg, process_name)
        return
    set_state(chat_id, name=name)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("📞 Отправить номер телефона", request_contact=True))
    markup.row("⬅️ Отмена")
    msg = bot.send_message(chat_id, "📞 Отправьте номер телефона или введите его вручную.", reply_markup=markup)
    bot.register_next_step_handler(msg, process_phone)


def process_phone(message):
    chat_id = message.chat.id
    if message.text == "⬅️ Отмена":
        cancel_button(message)
        return
    raw = message.contact.phone_number if message.contact else message.text
    phone = normalize_phone(raw)
    if not phone or len(phone) > MAX_PHONE_LEN:
        msg = bot.send_message(
            chat_id,
            "⚠️ Номер не распознан. Пример: +998 90 123 45 67",
            reply_markup=back_keyboard(),
        )
        bot.register_next_step_handler(msg, process_phone)
        return
    set_state(chat_id, phone=phone)
    msg = bot.send_message(
        chat_id,
        f"💬 Опишите жалобу или причину визита (до {MAX_PROBLEM_LEN} символов).",
        reply_markup=back_keyboard(),
    )
    bot.register_next_step_handler(msg, process_problem)


def process_problem(message):
    chat_id = message.chat.id
    if message.text == "⬅️ Отмена":
        cancel_button(message)
        return
    problem = (message.text or "").strip()
    if not valid_problem(problem):
        msg = bot.send_message(
            chat_id,
            f"⚠️ Напишите причину визита (не более {MAX_PROBLEM_LEN} символов).",
            reply_markup=back_keyboard(),
        )
        bot.register_next_step_handler(msg, process_problem)
        return
    set_state(chat_id, problem=problem)
    data = get_state(chat_id)
    try:
        dt = appointment_dt_from_state(data)
    except (KeyError, ValueError):
        reset_flow(chat_id)
        send_main_menu(chat_id, "⚠️ Сессия записи устарела. Начните запись заново.")
        return

    text = (
        "📋 <b>Проверьте данные:</b>\n\n"
        f"👤 ФИО: {safe_text(data['name'])}\n"
        f"📞 Телефон: {safe_text(data['phone'])}\n"
        f"📅 Дата: {dt:%d.%m.%Y}\n"
        f"⏰ Время: {dt:%H:%M}\n"
        f"🦷 Услуга: {safe_text(data['service'])}\n"
        f"💬 Жалоба: {safe_text(data['problem'])}\n\n"
        "Всё верно?"
    )
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Подтвердить", callback_data="booking:confirm"),
        types.InlineKeyboardButton("❌ Отменить", callback_data="booking:cancel"),
    )
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data in {"booking:confirm", "booking:cancel"})
def finalize_booking(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    if call.data == "booking:cancel":
        reset_flow(chat_id)
        bot.edit_message_text("❌ Запись отменена.", chat_id, call.message.message_id)
        bot.send_message(chat_id, "Главное меню:", reply_markup=get_main_keyboard())
        return

    data = get_state(chat_id)
    required = {"name", "phone", "date", "time", "service", "problem"}
    if not required.issubset(data):
        reset_flow(chat_id)
        bot.send_message(chat_id, "⚠️ Сессия устарела. Начните запись заново.", reply_markup=get_main_keyboard())
        return

    try:
        dt = appointment_dt_from_state(data)
    except (KeyError, ValueError):
        reset_flow(chat_id)
        bot.send_message(chat_id, "⚠️ Некорректная дата/время. Начните запись заново.", reply_markup=get_main_keyboard())
        return

    if dt <= now_local():
        reset_flow(chat_id)
        bot.send_message(chat_id, "⚠️ Это время уже прошло. Выберите новую дату.", reply_markup=get_main_keyboard())
        return

    app_id, result = create_appointment(data, chat_id, call.from_user.username)
    if result == "taken":
        bot.edit_message_text(
            "⚠️ Это время только что занял другой пациент.\nПожалуйста, начните запись заново и выберите другое время.",
            chat_id, call.message.message_id,
        )
        reset_flow(chat_id)
        bot.send_message(chat_id, "Выберите действие:", reply_markup=get_main_keyboard())
        return
    if result == "limit":
        bot.edit_message_text(
            f"⚠️ Нельзя иметь больше {MAX_ACTIVE_APPOINTMENTS_PER_USER} активных записей одновременно.",
            chat_id, call.message.message_id,
        )
        reset_flow(chat_id)
        bot.send_message(chat_id, "Вы можете посмотреть текущие записи в «📋 Мои записи».", reply_markup=get_main_keyboard())
        return
    if result == "invalid":
        bot.edit_message_text(
            "⚠️ Это время больше недоступно. Начните запись заново и выберите свободную дату и время.",
            chat_id, call.message.message_id,
        )
        reset_flow(chat_id)
        bot.send_message(chat_id, "Главное меню:", reply_markup=get_main_keyboard())
        return
    if result != "ok":
        logger.error("Ошибка записи на приём №%s", data)
        reset_flow(chat_id)
        bot.edit_message_text("❌ Не удалось сохранить запись. Попробуйте ещё раз.", chat_id, call.message.message_id)
        bot.send_message(chat_id, "Главное меню:", reply_markup=get_main_keyboard())
        return

    bot.edit_message_text(
        f"✅ <b>Вы успешно записаны!</b>\n\n"
        f"👤 {safe_text(data['name'])}\n"
        f"📅 {dt:%d.%m.%Y}\n"
        f"⏰ {dt:%H:%M}\n"
        f"🦷 {safe_text(data['service'])}\n\n"
        "Мы ждём вас!",
        chat_id, call.message.message_id, parse_mode="HTML",
    )

    username = call.from_user.username
    user_link = f"@{safe_text(username)}" if username else "Не указан"
    doctor_msg = (
        f"🆕 <b>НОВАЯ ЗАПИСЬ №{app_id}!</b>\n\n"
        f"👤 Пациент: {safe_text(data['name'])}\n"
        f"📞 Телефон: {safe_text(data['phone'])}\n"
        f"💬 Telegram: {user_link}\n"
        f"⏰ Время: {dt:%d.%m.%Y %H:%M}\n"
        f"🦷 Услуга: {safe_text(data['service'])}\n"
        f"🩺 Жалоба: {safe_text(data['problem'])}"
    )
    markup = types.InlineKeyboardMarkup()
    if username:
        markup.add(types.InlineKeyboardButton("💬 Написать клиенту", url=f"https://t.me/{username}"))
    markup.add(types.InlineKeyboardButton("❌ Отменить запись", callback_data=f"dcancel:{app_id}"))

    try:
        bot.send_message(DOCTOR_CHAT_ID, doctor_msg, reply_markup=markup, parse_mode="HTML")
    except Exception:
        # The appointment is already safely stored; doctor dashboard can still find it.
        logger.exception("Не удалось уведомить врача о записи №%s", app_id)
        bot.send_message(
            chat_id,
            "ℹ️ Запись сохранена в системе. Уведомление врачу временно не доставлено.",
        )

    reset_flow(chat_id)
    bot.send_message(chat_id, "Главное меню:", reply_markup=get_main_keyboard())


# ============================================================
# Client appointments
# ============================================================

def get_user_appointments(user_id, include_history=False):
    """Load a user's appointments safely."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        if include_history:
            cur.execute("""
                SELECT id, appointment_at, service, status
                FROM appointments
                WHERE user_id=%s AND appointment_at IS NOT NULL
                ORDER BY appointment_at DESC LIMIT 20
            """, (user_id,))
        else:
            cur.execute("""
                SELECT id, appointment_at, service, status
                FROM appointments
                WHERE user_id=%s AND status='active'
                  AND appointment_at IS NOT NULL AND appointment_at > NOW()
                ORDER BY appointment_at ASC
            """, (user_id,))
        return cur.fetchall()
    except Exception:
        logger.exception("Не удалось загрузить записи пациента")
        return []
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def show_my_appointments(message):
    records = get_user_appointments(message.chat.id, include_history=False)
    history_markup = types.InlineKeyboardMarkup()
    history_markup.add(types.InlineKeyboardButton("📜 История записей", callback_data="history:show"))

    if not records:
        bot.send_message(
            message.chat.id,
            "У вас нет будущих активных записей.",
            reply_markup=history_markup,
        )
        bot.send_message(message.chat.id, "Главное меню:", reply_markup=get_main_keyboard())
        return

    bot.send_message(message.chat.id, "📋 <b>Ваши активные записи:</b>", parse_mode="HTML", reply_markup=history_markup)
    for row in records:
        dt = row["appointment_at"].astimezone(TZ)
        text = (
            f"🗓 <b>{dt:%d.%m.%Y %H:%M}</b>\n"
            f"🦷 {safe_text(row['service'])}\n"
            f"👨‍⚕️ Доктор Маруф"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("❌ Отменить запись", callback_data=f"ucancel:{row['id']}"))
        bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "history:show")
def show_history_callback(call):
    chat_id = call.message.chat.id
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, appointment_at, service, status
            FROM appointments
            WHERE user_id=%s AND appointment_at IS NOT NULL
            ORDER BY appointment_at DESC
            LIMIT 20
        """, (chat_id,))
        records = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    bot.answer_callback_query(call.id)
    if not records:
        bot.send_message(chat_id, "📜 История пока пустая.")
        return
    lines = ["📜 <b>История записей</b>\n"]
    status_labels = {"active": "🟢 активна", "completed": "✅ пришёл", "noshow": "❌ не пришёл", "cancelled": "🚫 отменена"}
    for row in records:
        dt = row["appointment_at"].astimezone(TZ)
        lines.append(
            f"№{row['id']} — {dt:%d.%m.%Y %H:%M} — {safe_text(row['service'])} — "
            f"{status_labels.get(row['status'], row['status'])}"
        )
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")


@bot.callback_query_handler(func=lambda call: call.data.startswith("ucancel:"))
def handle_user_cancel(call):
    chat_id = call.message.chat.id
    try:
        app_id = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "Некорректная запись.")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, appointment_at FROM appointments
            WHERE id=%s AND user_id=%s AND status='active'
            FOR UPDATE
        """, (app_id, chat_id))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            bot.answer_callback_query(call.id, "Запись уже отменена или завершена.")
            bot.edit_message_text("ℹ️ Запись уже недоступна для отмены.", chat_id, call.message.message_id)
            return

        appointment_at = row["appointment_at"].astimezone(TZ)
        if appointment_at - now_local() < timedelta(minutes=CANCEL_MINUTES_BEFORE):
            conn.rollback()
            bot.answer_callback_query(call.id, "Слишком поздно для отмены онлайн.", show_alert=True)
            return

        cur.execute("""
            UPDATE appointments
            SET status='cancelled', status_updated_at=NOW()
            WHERE id=%s AND user_id=%s AND status='active'
        """, (app_id, chat_id))
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Ошибка отмены записи пациентом")
        bot.answer_callback_query(call.id, "Ошибка. Попробуйте позже.", show_alert=True)
        return
    finally:
        cur.close()
        conn.close()

    bot.answer_callback_query(call.id, "Запись отменена.")
    bot.edit_message_text("❌ Запись отменена.", chat_id, call.message.message_id)
    try:
        bot.send_message(
            DOCTOR_CHAT_ID,
            f"⚠️ <b>Пациент отменил запись №{app_id}.</b>\n🗓 Время: {format_dt(appointment_at)}\n🟢 Слот снова свободен.",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Не удалось уведомить врача об отмене записи")


# ============================================================
# Reviews
# ============================================================

def rating_keyboard(prefix="rate:"):
    markup = types.InlineKeyboardMarkup()
    buttons = [types.InlineKeyboardButton(f"⭐ {i}", callback_data=f"{prefix}{i}") for i in range(1, 6)]
    markup.row(buttons[0], buttons[1], buttons[2])
    markup.row(buttons[3], buttons[4])
    return markup


def ask_rating(message):
    reset_flow(message.chat.id)
    bot.send_message(
        message.chat.id,
        "Пожалуйста, оцените качество лечения и обслуживания от 1 до 5:",
        reply_markup=rating_keyboard(),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("rate:"))
def process_rating_stars(call):
    try:
        stars = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "Неверная оценка.")
        return
    if not 1 <= stars <= 5:
        bot.answer_callback_query(call.id, "Неверная оценка.")
        return

    chat_id = call.message.chat.id
    set_state(chat_id, flow="review", rating_val=stars, awaiting_comment=True)
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⏩ Пропустить", callback_data="review:skip"))
    bot.edit_message_text(
        f"Оценка принята: {'⭐' * stars}\n\nНапишите короткий отзыв или пропустите.",
        chat_id, call.message.message_id, reply_markup=markup,
    )
    msg = bot.send_message(chat_id, "Ваш комментарий:", reply_markup=back_keyboard())
    bot.register_next_step_handler(msg, save_comment_step)


@bot.callback_query_handler(func=lambda call: call.data == "review:skip")
def skip_comment_callback(call):
    save_review(call.message.chat.id, "", call.message.message_id)
    bot.answer_callback_query(call.id)


def save_comment_step(message):
    chat_id = message.chat.id
    if message.text == "⬅️ Отмена":
        cancel_button(message)
        return
    data = get_state(chat_id)
    if not data.get("awaiting_comment"):
        return
    comment = (message.text or "").strip()
    if len(comment) > MAX_REVIEW_LEN:
        msg = bot.send_message(chat_id, f"⚠️ Отзыв слишком длинный. Максимум {MAX_REVIEW_LEN} символов.", reply_markup=back_keyboard())
        bot.register_next_step_handler(msg, save_comment_step)
        return
    save_review(chat_id, comment)


def save_review(chat_id, comment, edit_message_id=None):
    data = get_state(chat_id)
    rating = int(data.get("rating_val", 5))
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO reviews (user_id, rating, comment, created_at_ts) VALUES (%s,%s,%s,NOW())",
            (chat_id, rating, comment),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Не удалось сохранить отзыв")
        bot.send_message(chat_id, "❌ Не удалось сохранить отзыв. Попробуйте позже.", reply_markup=get_main_keyboard())
        return
    finally:
        cur.close()
        conn.close()

    username = None
    try:
        chat = bot.get_chat(chat_id)
        username = chat.username
        first_name = chat.first_name or "Пациент"
    except Exception:
        first_name = "Пациент"

    clear_state(chat_id)
    cancel_steps(chat_id)
    if edit_message_id:
        try:
            bot.edit_message_text("Спасибо за отзыв! ❤️", chat_id, edit_message_id)
        except Exception:
            bot.send_message(chat_id, "Спасибо за отзыв! ❤️", reply_markup=get_main_keyboard())
    else:
        bot.send_message(chat_id, "Спасибо за отзыв! ❤️", reply_markup=get_main_keyboard())

    try:
        bot.send_message(
            DOCTOR_CHAT_ID,
            f"🌟 <b>Новый отзыв</b>\n\n"
            f"👤 {safe_text(first_name)}\n"
            f"⭐ Оценка: {'⭐' * rating}\n"
            f"💬 {safe_text(comment) if comment else 'Без комментария'}",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Не удалось отправить отзыв врачу")


# ============================================================
# Doctor panel
# ============================================================

def doctor_panel_menu(message):
    if not is_doctor(message.chat.id):
        return
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("📅 Сегодня", callback_data="period:today"),
        types.InlineKeyboardButton("📆 Завтра", callback_data="period:tomorrow"),
    )
    markup.row(types.InlineKeyboardButton("📊 7 дней", callback_data="period:week"))
    bot.send_message(message.chat.id, "👨‍⚕️ <b>Панель врача</b>", parse_mode="HTML", reply_markup=markup)


def period_bounds(period):
    today = now_local().date()
    if period == "today":
        start_date = today
        end_date = today + timedelta(days=1)
        title = f"📅 Записи на сегодня ({today:%d.%m.%Y})"
    elif period == "tomorrow":
        start_date = today + timedelta(days=1)
        end_date = today + timedelta(days=2)
        title = f"📆 Записи на завтра ({start_date:%d.%m.%Y})"
    else:
        start_date = today
        end_date = today + timedelta(days=7)
        title = "📊 Активные записи на ближайшие 7 дней"
    start = datetime.combine(start_date, time.min).replace(tzinfo=TZ)
    end = datetime.combine(end_date, time.min).replace(tzinfo=TZ)
    return start, end, title


@bot.callback_query_handler(func=lambda call: call.data.startswith("period:"))
def show_doctor_period(call):
    if not is_doctor(call.message.chat.id):
        bot.answer_callback_query(call.id)
        return
    period = call.data.split(":", 1)[1]
    if period not in {"today", "tomorrow", "week"}:
        bot.answer_callback_query(call.id, "Неверный период.")
        return
    start, end, title = period_bounds(period)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, patient_name, phone_number, username, service, problem, appointment_at
            FROM appointments
            WHERE status='active' AND appointment_at IS NOT NULL
              AND appointment_at >= %s AND appointment_at < %s
            ORDER BY appointment_at ASC
        """, (start, end))
        records = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    bot.answer_callback_query(call.id)
    if not records:
        bot.edit_message_text(f"{title}\n\n📭 Активных записей нет.", call.message.chat.id, call.message.message_id)
        return

    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.send_message(call.message.chat.id, f"<b>{title}</b>", parse_mode="HTML")

    for row in records:
        dt = row["appointment_at"].astimezone(TZ)
        card = (
            f"🆔 <b>Запись №{row['id']}</b>\n"
            f"👤 {safe_text(row['patient_name'])}\n"
            f"📞 {safe_text(row['phone_number'])}\n"
            f"💬 Telegram: {safe_text('@' + row['username']) if row['username'] else 'не указан'}\n"
            f"⏰ {dt:%d.%m.%Y %H:%M}\n"
            f"🦷 {safe_text(row['service'])}\n"
            f"💬 {safe_text(row['problem'])}"
        )
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ Пришёл", callback_data=f"status:completed:{row['id']}"),
            types.InlineKeyboardButton("❌ Не пришёл", callback_data=f"status:noshow:{row['id']}"),
        )
        markup.add(types.InlineKeyboardButton("🚫 Отменить", callback_data=f"dcancel:{row['id']}"))
        bot.send_message(call.message.chat.id, card, parse_mode="HTML", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("status:"))
def handle_status_change(call):
    if not is_doctor(call.message.chat.id):
        bot.answer_callback_query(call.id)
        return
    parts = call.data.split(":")
    if len(parts) != 3 or parts[1] not in {"completed", "noshow"}:
        bot.answer_callback_query(call.id, "Некорректный статус.")
        return
    status = parts[1]
    try:
        app_id = int(parts[2])
    except ValueError:
        bot.answer_callback_query(call.id, "Некорректная запись.")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE appointments
            SET status=%s, status_updated_at=NOW()
            WHERE id=%s AND status='active'
            RETURNING user_id, patient_name, appointment_at
        """, (status, app_id))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            bot.answer_callback_query(call.id, "Статус уже изменён.")
            bot.edit_message_text(f"Запись №{app_id}\n\nℹ️ Статус уже был изменён.", call.message.chat.id, call.message.message_id)
            return
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Ошибка изменения статуса записи")
        bot.answer_callback_query(call.id, "Ошибка базы данных.", show_alert=True)
        return
    finally:
        cur.close()
        conn.close()

    label = "пришёл" if status == "completed" else "не пришёл"
    bot.answer_callback_query(call.id, "Статус обновлён")
    bot.edit_message_text(
        f"🆔 Запись №{app_id}\n\n<b>Статус: {label}</b>",
        call.message.chat.id, call.message.message_id, parse_mode="HTML",
    )

    if status == "completed":
        try:
            bot.send_message(
                row["user_id"],
                f"Здравствуйте, {safe_text(row['patient_name'])}! Спасибо за визит.\n\nОцените качество лечения:",
                parse_mode="HTML",
                reply_markup=rating_keyboard("rate:"),
            )
        except Exception:
            logger.exception("Не удалось отправить запрос на отзыв после приёма")


@bot.callback_query_handler(func=lambda call: call.data.startswith("dcancel:"))
def handle_doctor_cancel(call):
    if not is_doctor(call.message.chat.id):
        bot.answer_callback_query(call.id)
        return
    try:
        app_id = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "Некорректная запись.")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE appointments
            SET status='cancelled', status_updated_at=NOW()
            WHERE id=%s AND status='active'
            RETURNING user_id, appointment_at
        """, (app_id,))
        row = cur.fetchone()
        if not row:
            conn.rollback()
            bot.answer_callback_query(call.id, "Запись уже не активна.")
            return
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Ошибка отмены записи врачом")
        bot.answer_callback_query(call.id, "Ошибка базы данных.", show_alert=True)
        return
    finally:
        cur.close()
        conn.close()

    bot.answer_callback_query(call.id, "Запись отменена")
    bot.edit_message_text(f"❌ Запись №{app_id} отменена врачом.", call.message.chat.id, call.message.message_id)
    try:
        bot.send_message(
            row["user_id"],
            f"⚠️ Ваша запись на {format_dt(row['appointment_at'])} отменена клиникой.\n"
            "Пожалуйста, выберите новое время или свяжитесь с клиникой.",
        )
    except Exception:
        logger.exception("Не удалось уведомить пациента об отмене записи")


# ============================================================
# Statistics
# ============================================================

def show_statistics(message):
    if not is_doctor(message.chat.id):
        return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            month_start = now_local().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

            cur.execute("SELECT COUNT(DISTINCT user_id) AS cnt FROM appointments")
            total_patients = cur.fetchone()["cnt"] or 0
            cur.execute("SELECT COUNT(*) AS cnt FROM appointments WHERE appointment_at >= %s AND appointment_at < %s", (month_start, next_month))
            month_appointments = cur.fetchone()["cnt"] or 0

            cur.execute("SELECT status, COUNT(*) AS cnt FROM appointments GROUP BY status")
            status_counts = {r["status"]: r["cnt"] for r in cur.fetchall()}
            completed = status_counts.get("completed", 0)
            noshow = status_counts.get("noshow", 0)
            cancelled = status_counts.get("cancelled", 0)
            total_finished = completed + noshow
            attendance = round(completed / total_finished * 100, 1) if total_finished else 0

            cur.execute("SELECT AVG(rating) AS avg_r, COUNT(*) AS cnt FROM reviews")
            rev = cur.fetchone()
            avg_rating = round(float(rev["avg_r"]), 1) if rev and rev["avg_r"] is not None else 0
            total_reviews = rev["cnt"] if rev else 0

            cur.execute("""
                SELECT service, COUNT(*) AS cnt FROM appointments
                GROUP BY service ORDER BY COUNT(*) DESC LIMIT 5
            """)
            top_services = cur.fetchall()
        finally:
            cur.close()
            conn.close()

        service_text = "\n".join(
            f"• {safe_text(row['service'])}: <b>{row['cnt']}</b>"
            for row in top_services
        ) or "• Пока нет данных"

        upcoming = []
        for i in range(3):
            d = now_local().date() + timedelta(days=i)
            start = datetime.combine(d, time.min).replace(tzinfo=TZ)
            end = start + timedelta(days=1)
            conn = get_db_connection()
            cur = conn.cursor()
            try:
                cur.execute("SELECT COUNT(*) AS cnt FROM appointments WHERE status='active' AND appointment_at >= %s AND appointment_at < %s", (start, end))
                cnt = cur.fetchone()["cnt"] or 0
            finally:
                cur.close()
                conn.close()
            label = "Сегодня" if i == 0 else "Завтра" if i == 1 else d.strftime("%d.%m")
            upcoming.append(f"• {label}: <b>{cnt}</b>")

        stats = (
            "📊 <b>СТАТИСТИКА КЛИНИКИ</b>\n\n"
            f"👥 Уникальных пациентов: <b>{total_patients}</b>\n"
            f"📆 Записей в текущем месяце: <b>{month_appointments}</b>\n\n"
            f"<b>Статусы:</b>\n"
            f"✅ Пришли: <b>{completed}</b>\n"
            f"❌ Не пришли: <b>{noshow}</b>\n"
            f"🚫 Отменено: <b>{cancelled}</b>\n"
            f"📈 Процент явок: <b>{attendance}%</b>\n\n"
            f"⭐ Средняя оценка: <b>{avg_rating}/5</b> ({total_reviews} отзывов)\n\n"
            f"🦷 <b>Топ услуг:</b>\n{service_text}\n\n"
            f"📅 <b>Ближайшие дни:</b>\n" + "\n".join(upcoming)
        )
        bot.send_message(message.chat.id, stats, parse_mode="HTML")
    except Exception:
        logger.exception("Не удалось получить статистику")
        bot.send_message(message.chat.id, "❌ Не удалось получить статистику. Попробуйте позже.")


# ============================================================
# Reminders: 24h + 2h
# ============================================================

def claim_reminder(app_id, column):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            f"""
            UPDATE appointments
            SET {column}=TRUE
            WHERE id=%s AND status='active' AND {column}=FALSE
            RETURNING user_id, appointment_at
            """,
            (app_id,),
        )
        row = cur.fetchone()
        conn.commit()
        return row
    except Exception:
        conn.rollback()
        logger.exception("Не удалось получить напоминание для отправки")
        return None
    finally:
        cur.close()
        conn.close()


def check_and_send_reminders():
    now = now_local()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, user_id, patient_name, appointment_at, reminded_24h, reminded_2h
            FROM appointments
            WHERE status='active'
              AND appointment_at IS NOT NULL
              AND appointment_at > NOW()
              AND appointment_at <= NOW() + INTERVAL '25 hours'
            ORDER BY appointment_at
        """)
        records = cur.fetchall()
    except Exception:
        conn.rollback()
        logger.exception("Ошибка при поиске напоминаний")
        return
    finally:
        cur.close()
        conn.close()

    for row in records:
        app_id = row["id"]
        patient_name = row["patient_name"]
        app_dt = row["appointment_at"].astimezone(TZ)
        diff = app_dt - now

        # 24h window: 23h45m .. 24h15m; scheduler runs every 5 min.
        if timedelta(hours=2) < diff <= timedelta(hours=24) and not row["reminded_24h"]:
            claimed = claim_reminder(app_id, "reminded_24h")
            if claimed:
                try:
                    bot.send_message(
                        claimed["user_id"],
                        f"🦷 Напоминание: завтра у вас визит в {app_dt:%H:%M}.\n"
                        f"📅 {app_dt:%d.%m.%Y}\n📍 {CLINIC_NAME}",
                    )
                    bot.send_message(
                        DOCTOR_CHAT_ID,
                        f"🔔 <b>Напоминание врачу</b>\nЗапись №{app_id}: {app_dt:%d.%m.%Y %H:%M}\n"
                        f"Пациент: {safe_text(patient_name)}",
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.exception("Не удалось отправить напоминание за 24 часа для записи №%s", app_id)

        # 2h window: 1h45m .. 2h15m.
        if timedelta(0) < diff <= timedelta(hours=2) and not row["reminded_2h"]:
            claimed = claim_reminder(app_id, "reminded_2h")
            if claimed:
                try:
                    bot.send_message(
                        claimed["user_id"],
                        f"⏰ Напоминание: сегодня визит в {app_dt:%H:%M}.\n"
                        f"📍 {CLINIC_NAME}\n{CLINIC_ADDRESS}",
                    )
                    bot.send_message(
                        DOCTOR_CHAT_ID,
                        f"⏰ <b>Через 2 часа запись №{app_id}</b>\n"
                        f"Время: {app_dt:%H:%M}\nПациент: {safe_text(patient_name)}",
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.exception("Не удалось отправить напоминание за 2 часа для записи №%s", app_id)


# ============================================================
# Error handler
# ============================================================

@bot.message_handler(func=lambda m: bool(m.text) and not m.text.startswith("/"))
def fallback_handler(message):
    if is_doctor(message.chat.id):
        bot.send_message(message.chat.id, "Используйте кнопки панели врача.", reply_markup=get_doctor_keyboard())
    else:
        bot.send_message(message.chat.id, "Не понял команду. Выберите действие в меню.", reply_markup=get_main_keyboard())


# ============================================================
# Run
# ============================================================

if __name__ == "__main__":
    init_db()
    keep_alive()

    scheduler = BackgroundScheduler(timezone=TZ)
    scheduler.add_job(
        check_and_send_reminders,
        "interval",
        minutes=5,
        id="appointment_reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()

    logger.info("Stoma dent bot started | version=%s", BOT_VERSION)
    try:
        bot.infinity_polling(
            skip_pending=True,
            timeout=20,
            long_polling_timeout=20,
        )
    finally:
        scheduler.shutdown(wait=False)
