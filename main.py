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

TZ = ZoneInfo(os.getenv("TZ", "Asia/Tashkent"))
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
DOCTOR_CHAT_ID_RAW = os.getenv("DOCTOR_CHAT_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")
if not DOCTOR_CHAT_ID_RAW:
    raise RuntimeError("DOCTOR_CHAT_ID is not set")
try:
    DOCTOR_CHAT_ID = int(DOCTOR_CHAT_ID_RAW)
except ValueError as exc:
    raise RuntimeError("DOCTOR_CHAT_ID must be an integer") from exc

CLINIC_NAME = os.getenv("CLINIC_NAME", "Stoma dent")
CLINIC_ADDRESS = os.getenv(
    "CLINIC_ADDRESS",
    "Ð³. Ð¢Ð°ÑÐºÐµÐ½Ñ, Ð¯ÑÐ½Ð°Ð±Ð°Ð´ÑÐºÐ¸Ð¹ ÑÐ°Ð¹Ð¾Ð½, 1-Ð¹ ÐºÐ²Ð°ÑÑÐ°Ð» ÐÐ²Ð¸Ð°ÑÐ¾Ð·Ð»Ð°Ñ, 12",
)
CLINIC_LANDMARK = os.getenv("CLINIC_LANDMARK", "Ð¼ÐµÑÑÐ¾ Ð¢ÑÐ·ÐµÐ»Ñ, 1-Ð¹ ÑÑÐ°Ð¶")
CLINIC_PHONE = os.getenv("CLINIC_PHONE", "+998 (93) 508-11-88")
CLINIC_HOURS = os.getenv("CLINIC_HOURS", "ÐÐ¶ÐµÐ´Ð½ÐµÐ²Ð½Ð¾ Ñ 09:00 Ð´Ð¾ 19:00")

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
    "1": "ð¦· ÐÐµÑÐµÐ½Ð¸Ðµ Ð·ÑÐ±Ð°",
    "2": "â¨ Ð§Ð¸ÑÑÐºÐ°",
    "3": "ð ÐÑÐ±ÐµÐ»Ð¸Ð²Ð°Ð½Ð¸Ðµ",
    "4": "ð ÐÐ¾ÑÐ¾Ð½ÐºÐ°",
    "5": "â Ð£Ð´Ð°Ð»ÐµÐ½Ð¸Ðµ",
    "6": "ð ÐÑÐ¾ÑÐ¸Ð²Ð¾Ð²Ð¾ÑÐ¿Ð°Ð»Ð¸ÑÐµÐ»ÑÐ½Ð¾Ðµ Ð»ÐµÑÐµÐ½Ð¸Ðµ",
    "7": "â ÐÑÑÐ³Ð¾Ðµ",
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

DAYS_RU = ["ÐÐ½", "ÐÑ", "Ð¡Ñ", "Ð§Ñ", "ÐÑ", "Ð¡Ð±", "ÐÑ"]
MONTHS_RU = [
    "ÑÐ½Ð²Ð°ÑÑ", "ÑÐµÐ²ÑÐ°Ð»Ñ", "Ð¼Ð°ÑÑÐ°", "Ð°Ð¿ÑÐµÐ»Ñ", "Ð¼Ð°Ñ", "Ð¸ÑÐ½Ñ",
    "Ð¸ÑÐ»Ñ", "Ð°Ð²Ð³ÑÑÑÐ°", "ÑÐµÐ½ÑÑÐ±ÑÑ", "Ð¾ÐºÑÑÐ±ÑÑ", "Ð½Ð¾ÑÐ±ÑÑ", "Ð´ÐµÐºÐ°Ð±ÑÑ",
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
        logger.exception("Failed to clear step handler")


def reset_flow(chat_id):
    cancel_steps(chat_id)
    clear_state(chat_id)


def is_doctor(chat_id):
    return chat_id == DOCTOR_CHAT_ID


def normalize_phone(raw):
    if not raw:
        return None
    phone = re.sub(r"[^\d+]", "", str(raw).strip())
    if phone.startswith("8") and len(phone) == 9:
        phone = "+998" + phone[1:]
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
    return bool(re.fullmatch(r"[A-Za-zÐ-Ð¯Ð°-ÑÐÑÐÑÒÒÒÒÒ²Ò³ÐÑÐªÑÐ¬Ñ\- ']+", text))


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
    return "Stoma dent Telegram Bot is active!", 200


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
                service VARCHAR(120) NOT NULL DEFAULT 'ÐÐ¾Ð½ÑÑÐ»ÑÑÐ°ÑÐ¸Ñ',
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
                created_at TEXT NOT NULL
            )
        """)

        # Upgrade the original project without destroying its existing data.
        cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS appointment_at TIMESTAMPTZ")
        cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS status_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()")
        cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminded_2h BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminded_24h BOOLEAN NOT NULL DEFAULT FALSE")

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
        logger.info("Database initialized/upgraded")
    except Exception:
        conn.rollback()
        logger.exception("Database initialization failed")
        raise
    finally:
        cur.close()
        conn.close()


def create_appointment(data, user_id, username):
    appointment_at = appointment_dt_from_state(data)
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
            data.get("service", "ÐÐ¾Ð½ÑÑÐ»ÑÑÐ°ÑÐ¸Ñ"), data["problem"], appointment_at,
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
    markup.row("ð ÐÐ°Ð¿Ð¸ÑÐ°ÑÑÑÑ Ð½Ð° Ð¿ÑÐ¸ÑÐ¼", "ð ÐÐ¾Ð¸ Ð·Ð°Ð¿Ð¸ÑÐ¸")
    markup.row("ð©º Ð£ÑÐ»ÑÐ³Ð¸ Ð¸ Ð»ÐµÑÐµÐ½Ð¸Ðµ", "ð ÐÐ°Ðº Ð½Ð°Ñ Ð½Ð°Ð¹ÑÐ¸")
    markup.row("â­ ÐÑÐµÐ½Ð¸ÑÑ Ð»ÐµÑÐµÐ½Ð¸Ðµ / ÐÑÐ·ÑÐ²", "â¹ï¸ ÐÐ½ÑÐ¾ÑÐ¼Ð°ÑÐ¸Ñ")
    return markup


def get_doctor_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, is_persistent=True)
    markup.row("ð ÐÐ°Ð½ÐµÐ»Ñ Ð²ÑÐ°ÑÐ°", "ð Ð¡ÑÐ°ÑÐ¸ÑÑÐ¸ÐºÐ°")
    markup.row("ð± ÐÐ»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½Ñ ÐºÐ»Ð¸ÐµÐ½ÑÐ°")
    return markup


def back_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row("â¬ï¸ ÐÑÐ¼ÐµÐ½Ð°")
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
            "ð¨ââï¸ ÐÐ´ÑÐ°Ð²ÑÑÐ²ÑÐ¹ÑÐµ, Ð´Ð¾ÐºÑÐ¾Ñ ÐÐ°ÑÑÑ!\nÐÐ°Ð½ÐµÐ»Ñ Ð²ÑÐ°ÑÐ° Ð³Ð¾ÑÐ¾Ð²Ð°.",
            reply_markup=get_doctor_keyboard(),
        )
    else:
        bot.send_message(
            message.chat.id,
            "ÐÐ´ÑÐ°Ð²ÑÑÐ²ÑÐ¹ÑÐµ! ÐÐ°Ñ Ð¿ÑÐ¸Ð²ÐµÑÑÑÐ²ÑÐµÑ Ð±Ð¾Ñ ÑÑÐ¾Ð¼Ð°ÑÐ¾Ð»Ð¾Ð³Ð¸ÑÐµÑÐºÐ¾Ð¹ ÐºÐ»Ð¸Ð½Ð¸ÐºÐ¸ "
            "Ð´Ð¾ÐºÑÐ¾ÑÐ° ÐÐ°ÑÑÑÐ°. ð¦·\n\nÐÑÐ±ÐµÑÐ¸ÑÐµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ðµ Ð² Ð¼ÐµÐ½Ñ Ð½Ð¸Ð¶Ðµ.",
            reply_markup=get_main_keyboard(),
        )


@bot.message_handler(commands=["cancel"])
def cancel_command(message):
    reset_flow(message.chat.id)
    keyboard = get_doctor_keyboard() if is_doctor(message.chat.id) else get_main_keyboard()
    bot.send_message(message.chat.id, "â Ð¢ÐµÐºÑÑÐ°Ñ Ð¾Ð¿ÐµÑÐ°ÑÐ¸Ñ Ð¾ÑÐ¼ÐµÐ½ÐµÐ½Ð°.", reply_markup=keyboard)


@bot.message_handler(func=lambda m: m.text == "â¬ï¸ ÐÑÐ¼ÐµÐ½Ð°")
def cancel_button(message):
    reset_flow(message.chat.id)
    keyboard = get_doctor_keyboard() if is_doctor(message.chat.id) else get_main_keyboard()
    bot.send_message(message.chat.id, "â ÐÑÐ¼ÐµÐ½ÐµÐ½Ð¾.", reply_markup=keyboard)


@bot.message_handler(func=lambda m: m.text in {
    "ð ÐÐ°Ð¿Ð¸ÑÐ°ÑÑÑÑ Ð½Ð° Ð¿ÑÐ¸ÑÐ¼", "ð ÐÐ¾Ð¸ Ð·Ð°Ð¿Ð¸ÑÐ¸", "ð©º Ð£ÑÐ»ÑÐ³Ð¸ Ð¸ Ð»ÐµÑÐµÐ½Ð¸Ðµ",
    "ð ÐÐ°Ðº Ð½Ð°Ñ Ð½Ð°Ð¹ÑÐ¸", "â­ ÐÑÐµÐ½Ð¸ÑÑ Ð»ÐµÑÐµÐ½Ð¸Ðµ / ÐÑÐ·ÑÐ²", "â¹ï¸ ÐÐ½ÑÐ¾ÑÐ¼Ð°ÑÐ¸Ñ",
    "ð ÐÐ°Ð½ÐµÐ»Ñ Ð²ÑÐ°ÑÐ°", "ð Ð¡ÑÐ°ÑÐ¸ÑÑÐ¸ÐºÐ°", "ð± ÐÐ»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½Ñ ÐºÐ»Ð¸ÐµÐ½ÑÐ°",
})
def menu_router(message):
    reset_flow(message.chat.id)
    text = message.text
    if text == "ð ÐÐ°Ð¿Ð¸ÑÐ°ÑÑÑÑ Ð½Ð° Ð¿ÑÐ¸ÑÐ¼":
        start_booking(message)
    elif text == "ð ÐÐ¾Ð¸ Ð·Ð°Ð¿Ð¸ÑÐ¸":
        show_my_appointments(message)
    elif text == "ð©º Ð£ÑÐ»ÑÐ³Ð¸ Ð¸ Ð»ÐµÑÐµÐ½Ð¸Ðµ":
        services_info(message)
    elif text == "ð ÐÐ°Ðº Ð½Ð°Ñ Ð½Ð°Ð¹ÑÐ¸":
        send_location(message)
    elif text == "â­ ÐÑÐµÐ½Ð¸ÑÑ Ð»ÐµÑÐµÐ½Ð¸Ðµ / ÐÑÐ·ÑÐ²":
        ask_rating(message)
    elif text == "â¹ï¸ ÐÐ½ÑÐ¾ÑÐ¼Ð°ÑÐ¸Ñ":
        clinic_info(message)
    elif text == "ð ÐÐ°Ð½ÐµÐ»Ñ Ð²ÑÐ°ÑÐ°":
        doctor_panel_menu(message)
    elif text == "ð Ð¡ÑÐ°ÑÐ¸ÑÑÐ¸ÐºÐ°":
        show_statistics(message)
    elif text == "ð± ÐÐ»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½Ñ ÐºÐ»Ð¸ÐµÐ½ÑÐ°":
        show_client_menu(message)


def show_client_menu(message):
    send_main_menu(message.chat.id, "ÐÐµÑÐµÐºÐ»ÑÑÐµÐ½Ð¾ Ð½Ð° Ð¼ÐµÐ½Ñ ÐºÐ»Ð¸ÐµÐ½ÑÐ°.")


def services_info(message):
    text = (
        f"ð¥ <b>Ð£ÑÐ»ÑÐ³Ð¸ {safe_text(CLINIC_NAME)}:</b>\n\n"
        "â¢ ÐÐµÑÐµÐ½Ð¸Ðµ Ð·ÑÐ±Ð°\nâ¢ ÐÑÐ¾ÑÐµÑÑÐ¸Ð¾Ð½Ð°Ð»ÑÐ½Ð°Ñ ÑÐ¸ÑÑÐºÐ°\nâ¢ ÐÑÐ±ÐµÐ»Ð¸Ð²Ð°Ð½Ð¸Ðµ\n"
        "â¢ ÐÐ¾ÑÐ¾Ð½ÐºÐ¸\nâ¢ Ð£Ð´Ð°Ð»ÐµÐ½Ð¸Ðµ\nâ¢ ÐÑÐ¾ÑÐ¸Ð²Ð¾Ð²Ð¾ÑÐ¿Ð°Ð»Ð¸ÑÐµÐ»ÑÐ½Ð¾Ðµ Ð»ÐµÑÐµÐ½Ð¸Ðµ\n\n"
        "ÐÐ°Ð¶Ð¼Ð¸ÑÐµ Â«ð ÐÐ°Ð¿Ð¸ÑÐ°ÑÑÑÑ Ð½Ð° Ð¿ÑÐ¸ÑÐ¼Â», ÑÑÐ¾Ð±Ñ Ð²ÑÐ±ÑÐ°ÑÑ ÑÑÐ»ÑÐ³Ñ Ð¸ Ð²ÑÐµÐ¼Ñ."
    )
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=get_main_keyboard())


def clinic_info(message):
    text = (
        f"ð¨ââï¸ <b>{safe_text(CLINIC_NAME)}</b>\n\n"
        f"ð <b>ÐÐ´ÑÐµÑ:</b> {safe_text(CLINIC_ADDRESS)}\n"
        f"ð <b>ÐÑÐ¸ÐµÐ½ÑÐ¸Ñ:</b> {safe_text(CLINIC_LANDMARK)}\n"
        f"â° <b>Ð ÐµÐ¶Ð¸Ð¼:</b> {safe_text(CLINIC_HOURS)}\n"
        f"ð <b>Ð¢ÐµÐ»ÐµÑÐ¾Ð½:</b> {safe_text(CLINIC_PHONE)}"
    )
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=get_main_keyboard())


def send_location(message):
    chat_id = message.chat.id
    bot.send_message(
        chat_id,
        f"ð <b>{safe_text(CLINIC_NAME)}</b>\n{safe_text(CLINIC_ADDRESS)}\n"
        f"ÐÑÐ¸ÐµÐ½ÑÐ¸Ñ: {safe_text(CLINIC_LANDMARK)}",
        parse_mode="HTML",
    )
    if CLINIC_LAT and CLINIC_LON:
        try:
            bot.send_location(chat_id, float(CLINIC_LAT), float(CLINIC_LON))
        except (ValueError, TypeError):
            logger.warning("Invalid clinic coordinates")
    else:
        bot.send_message(
            chat_id,
            "ð Ð¢Ð¾ÑÐ½Ð°Ñ Ð³ÐµÐ¾Ð¼ÐµÑÐºÐ° Ð¿Ð¾ÐºÐ° Ð¾ÑÐºÐ»ÑÑÐµÐ½Ð°, ÑÑÐ¾Ð±Ñ Ð½Ðµ Ð¾ÑÐ¿ÑÐ°Ð²Ð»ÑÑÑ Ð½ÐµÐ¿ÑÐ¾Ð²ÐµÑÐµÐ½Ð½ÑÑ ÑÐ¾ÑÐºÑ.\n"
            f"ÐÐ¾Ð¶Ð½Ð¾ Ð½Ð°Ð¹ÑÐ¸ ÐºÐ»Ð¸Ð½Ð¸ÐºÑ Ð¿Ð¾ Ð½Ð°Ð·Ð²Ð°Ð½Ð¸Ñ Â«{safe_text(CLINIC_NAME)}Â» Ð¸ Ð°Ð´ÑÐµÑÑ Ð²ÑÑÐµ.",
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
        types.InlineKeyboardButton("â ÐÑÐ¾Ð´Ð¾Ð»Ð¶Ð¸ÑÑ", callback_data="consent:yes"),
        types.InlineKeyboardButton("â ÐÑÐ¼ÐµÐ½Ð°", callback_data="consent:no"),
    )
    bot.send_message(
        chat_id,
        "ð¦· <b>ÐÐ°Ð¿Ð¸ÑÑ Ð½Ð° Ð¿ÑÐ¸ÑÐ¼</b>\n\n"
        "ÐÐ»Ñ Ð·Ð°Ð¿Ð¸ÑÐ¸ Ð±Ð¾Ñ Ð¿Ð¾Ð¿ÑÐ¾ÑÐ¸Ñ Ð¤ÐÐ, ÑÐµÐ»ÐµÑÐ¾Ð½ Ð¸ ÐºÑÐ°ÑÐºÑÑ Ð¿ÑÐ¸ÑÐ¸Ð½Ñ Ð²Ð¸Ð·Ð¸ÑÐ°. "
        "Ð­ÑÐ¸ Ð´Ð°Ð½Ð½ÑÐµ Ð¸ÑÐ¿Ð¾Ð»ÑÐ·ÑÑÑÑÑ Ð´Ð»Ñ Ð¾ÑÐ³Ð°Ð½Ð¸Ð·Ð°ÑÐ¸Ð¸ Ð¿ÑÐ¸ÑÐ¼Ð° Ð¸ ÑÐ²ÑÐ·Ð¸ Ñ ÐºÐ»Ð¸Ð½Ð¸ÐºÐ¾Ð¹.\n\n"
        "ÐÑÐ¾Ð´Ð¾Ð»Ð¶Ð°Ñ, Ð²Ñ ÑÐ¾Ð³Ð»Ð°ÑÐ°ÐµÑÐµÑÑ Ð½Ð° Ð¾Ð±ÑÐ°Ð±Ð¾ÑÐºÑ ÑÑÐ¸Ñ Ð´Ð°Ð½Ð½ÑÑ Ð´Ð»Ñ Ð·Ð°Ð¿Ð¸ÑÐ¸.",
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
    markup.add(types.InlineKeyboardButton("â ÐÑÐ¼ÐµÐ½Ð°", callback_data="booking:cancel"))
    text = "ÐÑÐ±ÐµÑÐ¸ÑÐµ ÑÑÐ»ÑÐ³Ñ:"
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
        bot.edit_message_text("â ÐÐ°Ð¿Ð¸ÑÑ Ð¾ÑÐ¼ÐµÐ½ÐµÐ½Ð°.", chat_id, call.message.message_id)
        bot.send_message(chat_id, "ÐÐ»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½Ñ:", reply_markup=get_main_keyboard())
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
        bot.answer_callback_query(call.id, "Ð£ÑÐ»ÑÐ³Ð° Ð½ÐµÐ´Ð¾ÑÑÑÐ¿Ð½Ð°.")
        return
    set_state(call.message.chat.id, flow="booking", service=SERVICES[key])
    bot.answer_callback_query(call.id)
    show_date_selection(call.message.chat.id, call.message.message_id)


def show_date_selection(chat_id, message_id=None):
    markup = types.InlineKeyboardMarkup()
    for day in next_open_dates():
        label = f"ð {DAYS_RU[day.weekday()]}, {day.day} {MONTHS_RU[day.month - 1]}"
        markup.add(types.InlineKeyboardButton(label, callback_data=f"date:{day:%d.%m.%Y}"))
    text = "ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð´Ð°ÑÑ Ð´Ð»Ñ Ð²Ð¸Ð·Ð¸ÑÐ°:"
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
        bot.answer_callback_query(call.id, "ÐÐµÐ²ÐµÑÐ½Ð°Ñ Ð´Ð°ÑÐ°.")
        return
    if selected not in next_open_dates(BOOKING_DAYS + 2):
        bot.answer_callback_query(call.id, "Ð­ÑÐ° Ð´Ð°ÑÐ° Ð±Ð¾Ð»ÑÑÐµ Ð½ÐµÐ´Ð¾ÑÑÑÐ¿Ð½Ð°.")
        return
    set_state(call.message.chat.id, date=value)
    bot.answer_callback_query(call.id)
    show_time_selection(call.message.chat.id, call.message.message_id, selected)


def show_time_selection(chat_id, message_id, date_obj):
    start = datetime.combine(date_obj, time.min).replace(tzinfo=TZ)
    end = start + timedelta(days=1)
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
        }
    finally:
        cur.close()
        conn.close()

    available = [slot for slot in SLOTS if slot not in booked]
    markup = types.InlineKeyboardMarkup()
    if not available:
        markup.add(types.InlineKeyboardButton("â¬ï¸ ÐÑÑÐ³Ð°Ñ Ð´Ð°ÑÐ°", callback_data="back:dates"))
        bot.edit_message_text(
            f"ÐÐ° {date_obj:%d.%m.%Y} ÑÐ²Ð¾Ð±Ð¾Ð´Ð½ÑÑ Ð²ÑÐµÐ¼ÑÐ½ Ð½ÐµÑ.",
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
    markup.add(types.InlineKeyboardButton("â¬ï¸ ÐÑÑÐ³Ð°Ñ Ð´Ð°ÑÐ°", callback_data="back:dates"))

    bot.edit_message_text(
        f"ð ÐÐ°ÑÐ°: <b>{date_obj:%d.%m.%Y}</b>\n\nÐÑÐ±ÐµÑÐ¸ÑÐµ Ð²ÑÐµÐ¼Ñ:",
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
        bot.answer_callback_query(call.id, "ÐÐµÐ²ÐµÑÐ½Ð¾Ðµ Ð²ÑÐµÐ¼Ñ.")
        return
    data = get_state(chat_id)
    if not data.get("service") or not data.get("date"):
        reset_flow(chat_id)
        bot.answer_callback_query(call.id, "Ð¡ÐµÑÑÐ¸Ñ ÑÑÑÐ°ÑÐµÐ»Ð°.")
        send_main_menu(chat_id, "ÐÐ¾Ð¶Ð°Ð»ÑÐ¹ÑÑÐ°, Ð½Ð°ÑÐ½Ð¸ÑÐµ Ð·Ð°Ð¿Ð¸ÑÑ Ð·Ð°Ð½Ð¾Ð²Ð¾.")
        return
    set_state(chat_id, time=selected)
    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass
    msg = bot.send_message(
        chat_id,
        "ð¤ ÐÐ²ÐµÐ´Ð¸ÑÐµ Ð²Ð°ÑÐµ <b>Ð¤ÐÐ</b> (ÐÐ¼Ñ Ð¸ Ð¤Ð°Ð¼Ð¸Ð»Ð¸Ñ):",
        parse_mode="HTML", reply_markup=back_keyboard(),
    )
    bot.register_next_step_handler(msg, process_name)


def process_name(message):
    chat_id = message.chat.id
    if message.text == "â¬ï¸ ÐÑÐ¼ÐµÐ½Ð°":
        cancel_button(message)
        return
    name = " ".join((message.text or "").split())
    if not valid_name(name):
        msg = bot.send_message(
            chat_id,
            f"â ï¸ ÐÐ²ÐµÐ´Ð¸ÑÐµ ÐºÐ¾ÑÑÐµÐºÑÐ½Ð¾Ðµ Ð¤ÐÐ (Ð´Ð¾ {MAX_NAME_LEN} ÑÐ¸Ð¼Ð²Ð¾Ð»Ð¾Ð²).",
            reply_markup=back_keyboard(),
        )
        bot.register_next_step_handler(msg, process_name)
        return
    set_state(chat_id, name=name)
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("ð ÐÑÐ¿ÑÐ°Ð²Ð¸ÑÑ Ð½Ð¾Ð¼ÐµÑ ÑÐµÐ»ÐµÑÐ¾Ð½Ð°", request_contact=True))
    markup.row("â¬ï¸ ÐÑÐ¼ÐµÐ½Ð°")
    msg = bot.send_message(chat_id, "ð ÐÑÐ¿ÑÐ°Ð²ÑÑÐµ Ð½Ð¾Ð¼ÐµÑ ÑÐµÐ»ÐµÑÐ¾Ð½Ð° Ð¸Ð»Ð¸ Ð²Ð²ÐµÐ´Ð¸ÑÐµ ÐµÐ³Ð¾ Ð²ÑÑÑÐ½ÑÑ.", reply_markup=markup)
    bot.register_next_step_handler(msg, process_phone)


def process_phone(message):
    chat_id = message.chat.id
    if message.text == "â¬ï¸ ÐÑÐ¼ÐµÐ½Ð°":
        cancel_button(message)
        return
    raw = message.contact.phone_number if message.contact else message.text
    phone = normalize_phone(raw)
    if not phone or len(phone) > MAX_PHONE_LEN:
        msg = bot.send_message(
            chat_id,
            "â ï¸ ÐÐ¾Ð¼ÐµÑ Ð½Ðµ ÑÐ°ÑÐ¿Ð¾Ð·Ð½Ð°Ð½. ÐÑÐ¸Ð¼ÐµÑ: +998 90 123 45 67",
            reply_markup=back_keyboard(),
        )
        bot.register_next_step_handler(msg, process_phone)
        return
    set_state(chat_id, phone=phone)
    msg = bot.send_message(
        chat_id,
        f"ð¬ ÐÐ¿Ð¸ÑÐ¸ÑÐµ Ð¶Ð°Ð»Ð¾Ð±Ñ Ð¸Ð»Ð¸ Ð¿ÑÐ¸ÑÐ¸Ð½Ñ Ð²Ð¸Ð·Ð¸ÑÐ° (Ð´Ð¾ {MAX_PROBLEM_LEN} ÑÐ¸Ð¼Ð²Ð¾Ð»Ð¾Ð²).",
        reply_markup=back_keyboard(),
    )
    bot.register_next_step_handler(msg, process_problem)


def process_problem(message):
    chat_id = message.chat.id
    if message.text == "â¬ï¸ ÐÑÐ¼ÐµÐ½Ð°":
        cancel_button(message)
        return
    problem = (message.text or "").strip()
    if not valid_problem(problem):
        msg = bot.send_message(
            chat_id,
            f"â ï¸ ÐÐ°Ð¿Ð¸ÑÐ¸ÑÐµ Ð¿ÑÐ¸ÑÐ¸Ð½Ñ Ð²Ð¸Ð·Ð¸ÑÐ° (Ð½Ðµ Ð±Ð¾Ð»ÐµÐµ {MAX_PROBLEM_LEN} ÑÐ¸Ð¼Ð²Ð¾Ð»Ð¾Ð²).",
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
        send_main_menu(chat_id, "â ï¸ Ð¡ÐµÑÑÐ¸Ñ Ð·Ð°Ð¿Ð¸ÑÐ¸ ÑÑÑÐ°ÑÐµÐ»Ð°. ÐÐ°ÑÐ½Ð¸ÑÐµ Ð·Ð°Ð¿Ð¸ÑÑ Ð·Ð°Ð½Ð¾Ð²Ð¾.")
        return

    text = (
        "ð <b>ÐÑÐ¾Ð²ÐµÑÑÑÐµ Ð´Ð°Ð½Ð½ÑÐµ:</b>\n\n"
        f"ð¤ Ð¤ÐÐ: {safe_text(data['name'])}\n"
        f"ð Ð¢ÐµÐ»ÐµÑÐ¾Ð½: {safe_text(data['phone'])}\n"
        f"ð ÐÐ°ÑÐ°: {dt:%d.%m.%Y}\n"
        f"â° ÐÑÐµÐ¼Ñ: {dt:%H:%M}\n"
        f"ð¦· Ð£ÑÐ»ÑÐ³Ð°: {safe_text(data['service'])}\n"
        f"ð¬ ÐÐ°Ð»Ð¾Ð±Ð°: {safe_text(data['problem'])}\n\n"
        "ÐÑÑ Ð²ÐµÑÐ½Ð¾?"
    )
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("â ÐÐ¾Ð´ÑÐ²ÐµÑÐ´Ð¸ÑÑ", callback_data="booking:confirm"),
        types.InlineKeyboardButton("â ÐÑÐ¼ÐµÐ½Ð¸ÑÑ", callback_data="booking:cancel"),
    )
    bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data in {"booking:confirm", "booking:cancel"})
def finalize_booking(call):
    chat_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    if call.data == "booking:cancel":
        reset_flow(chat_id)
        bot.edit_message_text("â ÐÐ°Ð¿Ð¸ÑÑ Ð¾ÑÐ¼ÐµÐ½ÐµÐ½Ð°.", chat_id, call.message.message_id)
        bot.send_message(chat_id, "ÐÐ»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½Ñ:", reply_markup=get_main_keyboard())
        return

    data = get_state(chat_id)
    required = {"name", "phone", "date", "time", "service", "problem"}
    if not required.issubset(data):
        reset_flow(chat_id)
        bot.send_message(chat_id, "â ï¸ Ð¡ÐµÑÑÐ¸Ñ ÑÑÑÐ°ÑÐµÐ»Ð°. ÐÐ°ÑÐ½Ð¸ÑÐµ Ð·Ð°Ð¿Ð¸ÑÑ Ð·Ð°Ð½Ð¾Ð²Ð¾.", reply_markup=get_main_keyboard())
        return

    try:
        dt = appointment_dt_from_state(data)
    except (KeyError, ValueError):
        reset_flow(chat_id)
        bot.send_message(chat_id, "â ï¸ ÐÐµÐºÐ¾ÑÑÐµÐºÑÐ½Ð°Ñ Ð´Ð°ÑÐ°/Ð²ÑÐµÐ¼Ñ. ÐÐ°ÑÐ½Ð¸ÑÐµ Ð·Ð°Ð¿Ð¸ÑÑ Ð·Ð°Ð½Ð¾Ð²Ð¾.", reply_markup=get_main_keyboard())
        return

    if dt <= now_local():
        reset_flow(chat_id)
        bot.send_message(chat_id, "â ï¸ Ð­ÑÐ¾ Ð²ÑÐµÐ¼Ñ ÑÐ¶Ðµ Ð¿ÑÐ¾ÑÐ»Ð¾. ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð½Ð¾Ð²ÑÑ Ð´Ð°ÑÑ.", reply_markup=get_main_keyboard())
        return

    app_id, result = create_appointment(data, chat_id, call.from_user.username)
    if result == "taken":
        bot.edit_message_text(
            "â ï¸ Ð­ÑÐ¾ Ð²ÑÐµÐ¼Ñ ÑÐ¾Ð»ÑÐºÐ¾ ÑÑÐ¾ Ð·Ð°Ð½ÑÐ» Ð´ÑÑÐ³Ð¾Ð¹ Ð¿Ð°ÑÐ¸ÐµÐ½Ñ.\nÐÐ¾Ð¶Ð°Ð»ÑÐ¹ÑÑÐ°, Ð½Ð°ÑÐ½Ð¸ÑÐµ Ð·Ð°Ð¿Ð¸ÑÑ Ð·Ð°Ð½Ð¾Ð²Ð¾ Ð¸ Ð²ÑÐ±ÐµÑÐ¸ÑÐµ Ð´ÑÑÐ³Ð¾Ðµ Ð²ÑÐµÐ¼Ñ.",
            chat_id, call.message.message_id,
        )
        reset_flow(chat_id)
        bot.send_message(chat_id, "ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ðµ:", reply_markup=get_main_keyboard())
        return
    if result == "limit":
        bot.edit_message_text(
            f"â ï¸ ÐÐµÐ»ÑÐ·Ñ Ð¸Ð¼ÐµÑÑ Ð±Ð¾Ð»ÑÑÐµ {MAX_ACTIVE_APPOINTMENTS_PER_USER} Ð°ÐºÑÐ¸Ð²Ð½ÑÑ Ð·Ð°Ð¿Ð¸ÑÐµÐ¹ Ð¾Ð´Ð½Ð¾Ð²ÑÐµÐ¼ÐµÐ½Ð½Ð¾.",
            chat_id, call.message.message_id,
        )
        reset_flow(chat_id)
        bot.send_message(chat_id, "ÐÑ Ð¼Ð¾Ð¶ÐµÑÐµ Ð¿Ð¾ÑÐ¼Ð¾ÑÑÐµÑÑ ÑÐµÐºÑÑÐ¸Ðµ Ð·Ð°Ð¿Ð¸ÑÐ¸ Ð² Â«ð ÐÐ¾Ð¸ Ð·Ð°Ð¿Ð¸ÑÐ¸Â».", reply_markup=get_main_keyboard())
        return
    if result != "ok":
        logger.error("Appointment %s failed", data)
        reset_flow(chat_id)
        bot.edit_message_text("â ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ¾ÑÑÐ°Ð½Ð¸ÑÑ Ð·Ð°Ð¿Ð¸ÑÑ. ÐÐ¾Ð¿ÑÐ¾Ð±ÑÐ¹ÑÐµ ÐµÑÑ ÑÐ°Ð·.", chat_id, call.message.message_id)
        bot.send_message(chat_id, "ÐÐ»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½Ñ:", reply_markup=get_main_keyboard())
        return

    bot.edit_message_text(
        f"â <b>ÐÑ ÑÑÐ¿ÐµÑÐ½Ð¾ Ð·Ð°Ð¿Ð¸ÑÐ°Ð½Ñ!</b>\n\n"
        f"ð¤ {safe_text(data['name'])}\n"
        f"ð {dt:%d.%m.%Y}\n"
        f"â° {dt:%H:%M}\n"
        f"ð¦· {safe_text(data['service'])}\n\n"
        "ÐÑ Ð¶Ð´ÑÐ¼ Ð²Ð°Ñ!",
        chat_id, call.message.message_id, parse_mode="HTML",
    )

    username = call.from_user.username
    user_link = f"@{safe_text(username)}" if username else "ÐÐµ ÑÐºÐ°Ð·Ð°Ð½"
    doctor_msg = (
        f"ð <b>ÐÐÐÐÐ¯ ÐÐÐÐÐ¡Ð¬ â{app_id}!</b>\n\n"
        f"ð¤ ÐÐ°ÑÐ¸ÐµÐ½Ñ: {safe_text(data['name'])}\n"
        f"ð Ð¢ÐµÐ»ÐµÑÐ¾Ð½: {safe_text(data['phone'])}\n"
        f"ð¬ Telegram: {user_link}\n"
        f"â° ÐÑÐµÐ¼Ñ: {dt:%d.%m.%Y %H:%M}\n"
        f"ð¦· Ð£ÑÐ»ÑÐ³Ð°: {safe_text(data['service'])}\n"
        f"ð©º ÐÐ°Ð»Ð¾Ð±Ð°: {safe_text(data['problem'])}"
    )
    markup = types.InlineKeyboardMarkup()
    if username:
        markup.add(types.InlineKeyboardButton("ð¬ ÐÐ°Ð¿Ð¸ÑÐ°ÑÑ ÐºÐ»Ð¸ÐµÐ½ÑÑ", url=f"https://t.me/{username}"))
    markup.add(types.InlineKeyboardButton("â ÐÑÐ¼ÐµÐ½Ð¸ÑÑ Ð·Ð°Ð¿Ð¸ÑÑ", callback_data=f"dcancel:{app_id}"))

    try:
        bot.send_message(DOCTOR_CHAT_ID, doctor_msg, reply_markup=markup, parse_mode="HTML")
    except Exception:
        # The appointment is already safely stored; doctor dashboard can still find it.
        logger.exception("Failed to notify doctor about appointment %s", app_id)
        bot.send_message(
            chat_id,
            "â¹ï¸ ÐÐ°Ð¿Ð¸ÑÑ ÑÐ¾ÑÑÐ°Ð½ÐµÐ½Ð° Ð² ÑÐ¸ÑÑÐµÐ¼Ðµ. Ð£Ð²ÐµÐ´Ð¾Ð¼Ð»ÐµÐ½Ð¸Ðµ Ð²ÑÐ°ÑÑ Ð²ÑÐµÐ¼ÐµÐ½Ð½Ð¾ Ð½Ðµ Ð´Ð¾ÑÑÐ°Ð²Ð»ÐµÐ½Ð¾.",
        )

    reset_flow(chat_id)
    bot.send_message(chat_id, "ÐÐ»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½Ñ:", reply_markup=get_main_keyboard())


# ============================================================
# Client appointments
# ============================================================

def show_my_appointments(message):
    records = get_user_appointments(message.chat.id, include_history=False)
    history_markup = types.InlineKeyboardMarkup()
    history_markup.add(types.InlineKeyboardButton("ð ÐÑÑÐ¾ÑÐ¸Ñ Ð·Ð°Ð¿Ð¸ÑÐµÐ¹", callback_data="history:show"))

    if not records:
        bot.send_message(
            message.chat.id,
            "Ð£ Ð²Ð°Ñ Ð½ÐµÑ Ð±ÑÐ´ÑÑÐ¸Ñ Ð°ÐºÑÐ¸Ð²Ð½ÑÑ Ð·Ð°Ð¿Ð¸ÑÐµÐ¹.",
            reply_markup=history_markup,
        )
        bot.send_message(message.chat.id, "ÐÐ»Ð°Ð²Ð½Ð¾Ðµ Ð¼ÐµÐ½Ñ:", reply_markup=get_main_keyboard())
        return

    bot.send_message(message.chat.id, "ð <b>ÐÐ°ÑÐ¸ Ð°ÐºÑÐ¸Ð²Ð½ÑÐµ Ð·Ð°Ð¿Ð¸ÑÐ¸:</b>", parse_mode="HTML", reply_markup=history_markup)
    for row in records:
        dt = row["appointment_at"].astimezone(TZ)
        text = (
            f"ð <b>{dt:%d.%m.%Y %H:%M}</b>\n"
            f"ð¦· {safe_text(row['service'])}\n"
            f"ð¨ââï¸ ÐÐ¾ÐºÑÐ¾Ñ ÐÐ°ÑÑÑ"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("â ÐÑÐ¼ÐµÐ½Ð¸ÑÑ Ð·Ð°Ð¿Ð¸ÑÑ", callback_data=f"ucancel:{row['id']}"))
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
            WHERE user_id=%s
            ORDER BY appointment_at DESC
            LIMIT 20
        """, (chat_id,))
        records = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    bot.answer_callback_query(call.id)
    if not records:
        bot.send_message(chat_id, "ð ÐÑÑÐ¾ÑÐ¸Ñ Ð¿Ð¾ÐºÐ° Ð¿ÑÑÑÐ°Ñ.")
        return
    lines = ["ð <b>ÐÑÑÐ¾ÑÐ¸Ñ Ð·Ð°Ð¿Ð¸ÑÐµÐ¹</b>\n"]
    status_labels = {"active": "ð¢ Ð°ÐºÑÐ¸Ð²Ð½Ð°", "completed": "â Ð¿ÑÐ¸ÑÑÐ»", "noshow": "â Ð½Ðµ Ð¿ÑÐ¸ÑÑÐ»", "cancelled": "ð« Ð¾ÑÐ¼ÐµÐ½ÐµÐ½Ð°"}
    for row in records:
        dt = row["appointment_at"].astimezone(TZ)
        lines.append(
            f"â{row['id']} â {dt:%d.%m.%Y %H:%M} â {safe_text(row['service'])} â "
            f"{status_labels.get(row['status'], row['status'])}"
        )
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")


@bot.callback_query_handler(func=lambda call: call.data.startswith("ucancel:"))
def handle_user_cancel(call):
    chat_id = call.message.chat.id
    try:
        app_id = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "ÐÐµÐºÐ¾ÑÑÐµÐºÑÐ½Ð°Ñ Ð·Ð°Ð¿Ð¸ÑÑ.")
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
            bot.answer_callback_query(call.id, "ÐÐ°Ð¿Ð¸ÑÑ ÑÐ¶Ðµ Ð¾ÑÐ¼ÐµÐ½ÐµÐ½Ð° Ð¸Ð»Ð¸ Ð·Ð°Ð²ÐµÑÑÐµÐ½Ð°.")
            bot.edit_message_text("â¹ï¸ ÐÐ°Ð¿Ð¸ÑÑ ÑÐ¶Ðµ Ð½ÐµÐ´Ð¾ÑÑÑÐ¿Ð½Ð° Ð´Ð»Ñ Ð¾ÑÐ¼ÐµÐ½Ñ.", chat_id, call.message.message_id)
            return

        appointment_at = row["appointment_at"].astimezone(TZ)
        if appointment_at - now_local() < timedelta(minutes=CANCEL_MINUTES_BEFORE):
            conn.rollback()
            bot.answer_callback_query(call.id, "Ð¡Ð»Ð¸ÑÐºÐ¾Ð¼ Ð¿Ð¾Ð·Ð´Ð½Ð¾ Ð´Ð»Ñ Ð¾ÑÐ¼ÐµÐ½Ñ Ð¾Ð½Ð»Ð°Ð¹Ð½.", show_alert=True)
            return

        cur.execute("""
            UPDATE appointments
            SET status='cancelled', status_updated_at=NOW()
            WHERE id=%s AND user_id=%s AND status='active'
        """, (app_id, chat_id))
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Client cancellation failed")
        bot.answer_callback_query(call.id, "ÐÑÐ¸Ð±ÐºÐ°. ÐÐ¾Ð¿ÑÐ¾Ð±ÑÐ¹ÑÐµ Ð¿Ð¾Ð·Ð¶Ðµ.", show_alert=True)
        return
    finally:
        cur.close()
        conn.close()

    bot.answer_callback_query(call.id, "ÐÐ°Ð¿Ð¸ÑÑ Ð¾ÑÐ¼ÐµÐ½ÐµÐ½Ð°.")
    bot.edit_message_text("â ÐÐ°Ð¿Ð¸ÑÑ Ð¾ÑÐ¼ÐµÐ½ÐµÐ½Ð°.", chat_id, call.message.message_id)
    try:
        bot.send_message(
            DOCTOR_CHAT_ID,
            f"â ï¸ <b>ÐÐ°ÑÐ¸ÐµÐ½Ñ Ð¾ÑÐ¼ÐµÐ½Ð¸Ð» Ð·Ð°Ð¿Ð¸ÑÑ â{app_id}.</b>\nð ÐÑÐµÐ¼Ñ: {format_dt(appointment_at)}\nð¢ Ð¡Ð»Ð¾Ñ ÑÐ½Ð¾Ð²Ð° ÑÐ²Ð¾Ð±Ð¾Ð´ÐµÐ½.",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Failed to notify doctor about client cancellation")


# ============================================================
# Reviews
# ============================================================

def rating_keyboard(prefix="rate:"):
    markup = types.InlineKeyboardMarkup()
    buttons = [types.InlineKeyboardButton(f"â­ {i}", callback_data=f"{prefix}{i}") for i in range(1, 6)]
    markup.row(buttons[0], buttons[1], buttons[2])
    markup.row(buttons[3], buttons[4])
    return markup


def ask_rating(message):
    reset_flow(message.chat.id)
    bot.send_message(
        message.chat.id,
        "ÐÐ¾Ð¶Ð°Ð»ÑÐ¹ÑÑÐ°, Ð¾ÑÐµÐ½Ð¸ÑÐµ ÐºÐ°ÑÐµÑÑÐ²Ð¾ Ð»ÐµÑÐµÐ½Ð¸Ñ Ð¸ Ð¾Ð±ÑÐ»ÑÐ¶Ð¸Ð²Ð°Ð½Ð¸Ñ Ð¾Ñ 1 Ð´Ð¾ 5:",
        reply_markup=rating_keyboard(),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("rate:"))
def process_rating_stars(call):
    try:
        stars = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "ÐÐµÐ²ÐµÑÐ½Ð°Ñ Ð¾ÑÐµÐ½ÐºÐ°.")
        return
    if not 1 <= stars <= 5:
        bot.answer_callback_query(call.id, "ÐÐµÐ²ÐµÑÐ½Ð°Ñ Ð¾ÑÐµÐ½ÐºÐ°.")
        return

    chat_id = call.message.chat.id
    set_state(chat_id, flow="review", rating_val=stars, awaiting_comment=True)
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("â© ÐÑÐ¾Ð¿ÑÑÑÐ¸ÑÑ", callback_data="review:skip"))
    bot.edit_message_text(
        f"ÐÑÐµÐ½ÐºÐ° Ð¿ÑÐ¸Ð½ÑÑÐ°: {'â­' * stars}\n\nÐÐ°Ð¿Ð¸ÑÐ¸ÑÐµ ÐºÐ¾ÑÐ¾ÑÐºÐ¸Ð¹ Ð¾ÑÐ·ÑÐ² Ð¸Ð»Ð¸ Ð¿ÑÐ¾Ð¿ÑÑÑÐ¸ÑÐµ.",
        chat_id, call.message.message_id, reply_markup=markup,
    )
    msg = bot.send_message(chat_id, "ÐÐ°Ñ ÐºÐ¾Ð¼Ð¼ÐµÐ½ÑÐ°ÑÐ¸Ð¹:", reply_markup=back_keyboard())
    bot.register_next_step_handler(msg, save_comment_step)


@bot.callback_query_handler(func=lambda call: call.data == "review:skip")
def skip_comment_callback(call):
    save_review(call.message.chat.id, "", call.message.message_id)
    bot.answer_callback_query(call.id)


def save_comment_step(message):
    chat_id = message.chat.id
    if message.text == "â¬ï¸ ÐÑÐ¼ÐµÐ½Ð°":
        cancel_button(message)
        return
    data = get_state(chat_id)
    if not data.get("awaiting_comment"):
        return
    comment = (message.text or "").strip()
    if len(comment) > MAX_REVIEW_LEN:
        msg = bot.send_message(chat_id, f"â ï¸ ÐÑÐ·ÑÐ² ÑÐ»Ð¸ÑÐºÐ¾Ð¼ Ð´Ð»Ð¸Ð½Ð½ÑÐ¹. ÐÐ°ÐºÑÐ¸Ð¼ÑÐ¼ {MAX_REVIEW_LEN} ÑÐ¸Ð¼Ð²Ð¾Ð»Ð¾Ð².", reply_markup=back_keyboard())
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
            "INSERT INTO reviews (user_id, rating, comment, created_at) VALUES (%s,%s,%s,%s)",
            (chat_id, rating, comment, now_local().strftime("%Y-%m-%d %H:%M:%S%z")),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Review save failed")
        bot.send_message(chat_id, "â ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ ÑÐ¾ÑÑÐ°Ð½Ð¸ÑÑ Ð¾ÑÐ·ÑÐ². ÐÐ¾Ð¿ÑÐ¾Ð±ÑÐ¹ÑÐµ Ð¿Ð¾Ð·Ð¶Ðµ.", reply_markup=get_main_keyboard())
        return
    finally:
        cur.close()
        conn.close()

    username = None
    try:
        chat = bot.get_chat(chat_id)
        username = chat.username
        first_name = chat.first_name or "ÐÐ°ÑÐ¸ÐµÐ½Ñ"
    except Exception:
        first_name = "ÐÐ°ÑÐ¸ÐµÐ½Ñ"

    clear_state(chat_id)
    cancel_steps(chat_id)
    if edit_message_id:
        try:
            bot.edit_message_text("Ð¡Ð¿Ð°ÑÐ¸Ð±Ð¾ Ð·Ð° Ð¾ÑÐ·ÑÐ²! â¤ï¸", chat_id, edit_message_id)
        except Exception:
            bot.send_message(chat_id, "Ð¡Ð¿Ð°ÑÐ¸Ð±Ð¾ Ð·Ð° Ð¾ÑÐ·ÑÐ²! â¤ï¸", reply_markup=get_main_keyboard())
    else:
        bot.send_message(chat_id, "Ð¡Ð¿Ð°ÑÐ¸Ð±Ð¾ Ð·Ð° Ð¾ÑÐ·ÑÐ²! â¤ï¸", reply_markup=get_main_keyboard())

    try:
        bot.send_message(
            DOCTOR_CHAT_ID,
            f"ð <b>ÐÐ¾Ð²ÑÐ¹ Ð¾ÑÐ·ÑÐ²</b>\n\n"
            f"ð¤ {safe_text(first_name)}\n"
            f"â­ ÐÑÐµÐ½ÐºÐ°: {'â­' * rating}\n"
            f"ð¬ {safe_text(comment) if comment else 'ÐÐµÐ· ÐºÐ¾Ð¼Ð¼ÐµÐ½ÑÐ°ÑÐ¸Ñ'}",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Failed to notify doctor about review")


# ============================================================
# Doctor panel
# ============================================================

def doctor_panel_menu(message):
    if not is_doctor(message.chat.id):
        return
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("ð Ð¡ÐµÐ³Ð¾Ð´Ð½Ñ", callback_data="period:today"),
        types.InlineKeyboardButton("ð ÐÐ°Ð²ÑÑÐ°", callback_data="period:tomorrow"),
    )
    markup.row(types.InlineKeyboardButton("ð 7 Ð´Ð½ÐµÐ¹", callback_data="period:week"))
    bot.send_message(message.chat.id, "ð¨ââï¸ <b>ÐÐ°Ð½ÐµÐ»Ñ Ð²ÑÐ°ÑÐ°</b>", parse_mode="HTML", reply_markup=markup)


def period_bounds(period):
    today = now_local().date()
    if period == "today":
        start_date = today
        end_date = today + timedelta(days=1)
        title = f"ð ÐÐ°Ð¿Ð¸ÑÐ¸ Ð½Ð° ÑÐµÐ³Ð¾Ð´Ð½Ñ ({today:%d.%m.%Y})"
    elif period == "tomorrow":
        start_date = today + timedelta(days=1)
        end_date = today + timedelta(days=2)
        title = f"ð ÐÐ°Ð¿Ð¸ÑÐ¸ Ð½Ð° Ð·Ð°Ð²ÑÑÐ° ({start_date:%d.%m.%Y})"
    else:
        start_date = today
        end_date = today + timedelta(days=7)
        title = "ð ÐÐºÑÐ¸Ð²Ð½ÑÐµ Ð·Ð°Ð¿Ð¸ÑÐ¸ Ð½Ð° Ð±Ð»Ð¸Ð¶Ð°Ð¹ÑÐ¸Ðµ 7 Ð´Ð½ÐµÐ¹"
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
        bot.answer_callback_query(call.id, "ÐÐµÐ²ÐµÑÐ½ÑÐ¹ Ð¿ÐµÑÐ¸Ð¾Ð´.")
        return
    start, end, title = period_bounds(period)
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, patient_name, phone_number, username, service, problem, appointment_at
            FROM appointments
            WHERE status='active' AND appointment_at >= %s AND appointment_at < %s
            ORDER BY appointment_at ASC
        """, (start, end))
        records = cur.fetchall()
    finally:
        cur.close()
        conn.close()

    bot.answer_callback_query(call.id)
    if not records:
        bot.edit_message_text(f"{title}\n\nð­ ÐÐºÑÐ¸Ð²Ð½ÑÑ Ð·Ð°Ð¿Ð¸ÑÐµÐ¹ Ð½ÐµÑ.", call.message.chat.id, call.message.message_id)
        return

    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    bot.send_message(call.message.chat.id, f"<b>{title}</b>", parse_mode="HTML")

    for row in records:
        dt = row["appointment_at"].astimezone(TZ)
        card = (
            f"ð <b>ÐÐ°Ð¿Ð¸ÑÑ â{row['id']}</b>\n"
            f"ð¤ {safe_text(row['patient_name'])}\n"
            f"ð {safe_text(row['phone_number'])}\n"
            f"ð¬ Telegram: {safe_text('@' + row['username']) if row['username'] else 'Ð½Ðµ ÑÐºÐ°Ð·Ð°Ð½'}\n"
            f"â° {dt:%d.%m.%Y %H:%M}\n"
            f"ð¦· {safe_text(row['service'])}\n"
            f"ð¬ {safe_text(row['problem'])}"
        )
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("â ÐÑÐ¸ÑÑÐ»", callback_data=f"status:completed:{row['id']}"),
            types.InlineKeyboardButton("â ÐÐµ Ð¿ÑÐ¸ÑÑÐ»", callback_data=f"status:noshow:{row['id']}"),
        )
        markup.add(types.InlineKeyboardButton("ð« ÐÑÐ¼ÐµÐ½Ð¸ÑÑ", callback_data=f"dcancel:{row['id']}"))
        bot.send_message(call.message.chat.id, card, parse_mode="HTML", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("status:"))
def handle_status_change(call):
    if not is_doctor(call.message.chat.id):
        bot.answer_callback_query(call.id)
        return
    parts = call.data.split(":")
    if len(parts) != 3 or parts[1] not in {"completed", "noshow"}:
        bot.answer_callback_query(call.id, "ÐÐµÐºÐ¾ÑÑÐµÐºÑÐ½ÑÐ¹ ÑÑÐ°ÑÑÑ.")
        return
    status = parts[1]
    try:
        app_id = int(parts[2])
    except ValueError:
        bot.answer_callback_query(call.id, "ÐÐµÐºÐ¾ÑÑÐµÐºÑÐ½Ð°Ñ Ð·Ð°Ð¿Ð¸ÑÑ.")
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
            bot.answer_callback_query(call.id, "Ð¡ÑÐ°ÑÑÑ ÑÐ¶Ðµ Ð¸Ð·Ð¼ÐµÐ½ÑÐ½.")
            bot.edit_message_text(f"ÐÐ°Ð¿Ð¸ÑÑ â{app_id}\n\nâ¹ï¸ Ð¡ÑÐ°ÑÑÑ ÑÐ¶Ðµ Ð±ÑÐ» Ð¸Ð·Ð¼ÐµÐ½ÑÐ½.", call.message.chat.id, call.message.message_id)
            return
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Status update failed")
        bot.answer_callback_query(call.id, "ÐÑÐ¸Ð±ÐºÐ° Ð±Ð°Ð·Ñ Ð´Ð°Ð½Ð½ÑÑ.", show_alert=True)
        return
    finally:
        cur.close()
        conn.close()

    label = "Ð¿ÑÐ¸ÑÑÐ»" if status == "completed" else "Ð½Ðµ Ð¿ÑÐ¸ÑÑÐ»"
    bot.answer_callback_query(call.id, "Ð¡ÑÐ°ÑÑÑ Ð¾Ð±Ð½Ð¾Ð²Ð»ÑÐ½")
    bot.edit_message_text(
        f"ð ÐÐ°Ð¿Ð¸ÑÑ â{app_id}\n\n<b>Ð¡ÑÐ°ÑÑÑ: {label}</b>",
        call.message.chat.id, call.message.message_id, parse_mode="HTML",
    )

    if status == "completed":
        try:
            bot.send_message(
                row["user_id"],
                f"ÐÐ´ÑÐ°Ð²ÑÑÐ²ÑÐ¹ÑÐµ, {safe_text(row['patient_name'])}! Ð¡Ð¿Ð°ÑÐ¸Ð±Ð¾ Ð·Ð° Ð²Ð¸Ð·Ð¸Ñ.\n\nÐÑÐµÐ½Ð¸ÑÐµ ÐºÐ°ÑÐµÑÑÐ²Ð¾ Ð»ÐµÑÐµÐ½Ð¸Ñ:",
                parse_mode="HTML",
                reply_markup=rating_keyboard("rate:"),
            )
        except Exception:
            logger.exception("Failed to send post-visit review request")


@bot.callback_query_handler(func=lambda call: call.data.startswith("dcancel:"))
def handle_doctor_cancel(call):
    if not is_doctor(call.message.chat.id):
        bot.answer_callback_query(call.id)
        return
    try:
        app_id = int(call.data.split(":", 1)[1])
    except ValueError:
        bot.answer_callback_query(call.id, "ÐÐµÐºÐ¾ÑÑÐµÐºÑÐ½Ð°Ñ Ð·Ð°Ð¿Ð¸ÑÑ.")
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
            bot.answer_callback_query(call.id, "ÐÐ°Ð¿Ð¸ÑÑ ÑÐ¶Ðµ Ð½Ðµ Ð°ÐºÑÐ¸Ð²Ð½Ð°.")
            return
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Doctor cancellation failed")
        bot.answer_callback_query(call.id, "ÐÑÐ¸Ð±ÐºÐ° Ð±Ð°Ð·Ñ Ð´Ð°Ð½Ð½ÑÑ.", show_alert=True)
        return
    finally:
        cur.close()
        conn.close()

    bot.answer_callback_query(call.id, "ÐÐ°Ð¿Ð¸ÑÑ Ð¾ÑÐ¼ÐµÐ½ÐµÐ½Ð°")
    bot.edit_message_text(f"â ÐÐ°Ð¿Ð¸ÑÑ â{app_id} Ð¾ÑÐ¼ÐµÐ½ÐµÐ½Ð° Ð²ÑÐ°ÑÐ¾Ð¼.", call.message.chat.id, call.message.message_id)
    try:
        bot.send_message(
            row["user_id"],
            f"â ï¸ ÐÐ°ÑÐ° Ð·Ð°Ð¿Ð¸ÑÑ Ð½Ð° {format_dt(row['appointment_at'])} Ð¾ÑÐ¼ÐµÐ½ÐµÐ½Ð° ÐºÐ»Ð¸Ð½Ð¸ÐºÐ¾Ð¹.\n"
            "ÐÐ¾Ð¶Ð°Ð»ÑÐ¹ÑÑÐ°, Ð²ÑÐ±ÐµÑÐ¸ÑÐµ Ð½Ð¾Ð²Ð¾Ðµ Ð²ÑÐµÐ¼Ñ Ð¸Ð»Ð¸ ÑÐ²ÑÐ¶Ð¸ÑÐµÑÑ Ñ ÐºÐ»Ð¸Ð½Ð¸ÐºÐ¾Ð¹.",
        )
    except Exception:
        logger.exception("Failed to notify patient about doctor cancellation")


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
            f"â¢ {safe_text(row['service'])}: <b>{row['cnt']}</b>"
            for row in top_services
        ) or "â¢ ÐÐ¾ÐºÐ° Ð½ÐµÑ Ð´Ð°Ð½Ð½ÑÑ"

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
            label = "Ð¡ÐµÐ³Ð¾Ð´Ð½Ñ" if i == 0 else "ÐÐ°Ð²ÑÑÐ°" if i == 1 else d.strftime("%d.%m")
            upcoming.append(f"â¢ {label}: <b>{cnt}</b>")

        stats = (
            "ð <b>Ð¡Ð¢ÐÐ¢ÐÐ¡Ð¢ÐÐÐ ÐÐÐÐÐÐÐ</b>\n\n"
            f"ð¥ Ð£Ð½Ð¸ÐºÐ°Ð»ÑÐ½ÑÑ Ð¿Ð°ÑÐ¸ÐµÐ½ÑÐ¾Ð²: <b>{total_patients}</b>\n"
            f"ð ÐÐ°Ð¿Ð¸ÑÐµÐ¹ Ð² ÑÐµÐºÑÑÐµÐ¼ Ð¼ÐµÑÑÑÐµ: <b>{month_appointments}</b>\n\n"
            f"<b>Ð¡ÑÐ°ÑÑÑÑ:</b>\n"
            f"â ÐÑÐ¸ÑÐ»Ð¸: <b>{completed}</b>\n"
            f"â ÐÐµ Ð¿ÑÐ¸ÑÐ»Ð¸: <b>{noshow}</b>\n"
            f"ð« ÐÑÐ¼ÐµÐ½ÐµÐ½Ð¾: <b>{cancelled}</b>\n"
            f"ð ÐÑÐ¾ÑÐµÐ½Ñ ÑÐ²Ð¾Ðº: <b>{attendance}%</b>\n\n"
            f"â­ Ð¡ÑÐµÐ´Ð½ÑÑ Ð¾ÑÐµÐ½ÐºÐ°: <b>{avg_rating}/5</b> ({total_reviews} Ð¾ÑÐ·ÑÐ²Ð¾Ð²)\n\n"
            f"ð¦· <b>Ð¢Ð¾Ð¿ ÑÑÐ»ÑÐ³:</b>\n{service_text}\n\n"
            f"ð <b>ÐÐ»Ð¸Ð¶Ð°Ð¹ÑÐ¸Ðµ Ð´Ð½Ð¸:</b>\n" + "\n".join(upcoming)
        )
        bot.send_message(message.chat.id, stats, parse_mode="HTML")
    except Exception:
        logger.exception("Statistics failed")
        bot.send_message(message.chat.id, "â ÐÐµ ÑÐ´Ð°Ð»Ð¾ÑÑ Ð¿Ð¾Ð»ÑÑÐ¸ÑÑ ÑÑÐ°ÑÐ¸ÑÑÐ¸ÐºÑ. ÐÐ¾Ð¿ÑÐ¾Ð±ÑÐ¹ÑÐµ Ð¿Ð¾Ð·Ð¶Ðµ.")


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
        logger.exception("Failed to claim reminder")
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
              AND appointment_at > NOW()
              AND appointment_at <= NOW() + INTERVAL '25 hours'
            ORDER BY appointment_at
        """)
        records = cur.fetchall()
    except Exception:
        conn.rollback()
        logger.exception("Reminder query failed")
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
        if timedelta(hours=23, minutes=45) <= diff <= timedelta(hours=24, minutes=15) and not row["reminded_24h"]:
            claimed = claim_reminder(app_id, "reminded_24h")
            if claimed:
                try:
                    bot.send_message(
                        claimed["user_id"],
                        f"ð¦· ÐÐ°Ð¿Ð¾Ð¼Ð¸Ð½Ð°Ð½Ð¸Ðµ: Ð·Ð°Ð²ÑÑÐ° Ñ Ð²Ð°Ñ Ð²Ð¸Ð·Ð¸Ñ Ð² {app_dt:%H:%M}.\n"
                        f"ð {app_dt:%d.%m.%Y}\nð {CLINIC_NAME}",
                    )
                    bot.send_message(
                        DOCTOR_CHAT_ID,
                        f"ð <b>ÐÐ°Ð¿Ð¾Ð¼Ð¸Ð½Ð°Ð½Ð¸Ðµ Ð²ÑÐ°ÑÑ</b>\nÐÐ°Ð¿Ð¸ÑÑ â{app_id}: {app_dt:%d.%m.%Y %H:%M}\n"
                        f"ÐÐ°ÑÐ¸ÐµÐ½Ñ: {safe_text(patient_name)}",
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.exception("24h reminder delivery failed for %s", app_id)

        # 2h window: 1h45m .. 2h15m.
        if timedelta(hours=1, minutes=45) <= diff <= timedelta(hours=2, minutes=15) and not row["reminded_2h"]:
            claimed = claim_reminder(app_id, "reminded_2h")
            if claimed:
                try:
                    bot.send_message(
                        claimed["user_id"],
                        f"â° ÐÐ°Ð¿Ð¾Ð¼Ð¸Ð½Ð°Ð½Ð¸Ðµ: ÑÐµÐ³Ð¾Ð´Ð½Ñ Ð²Ð¸Ð·Ð¸Ñ Ð² {app_dt:%H:%M}.\n"
                        f"ð {CLINIC_NAME}\n{CLINIC_ADDRESS}",
                    )
                    bot.send_message(
                        DOCTOR_CHAT_ID,
                        f"â° <b>Ð§ÐµÑÐµÐ· 2 ÑÐ°ÑÐ° Ð·Ð°Ð¿Ð¸ÑÑ â{app_id}</b>\n"
                        f"ÐÑÐµÐ¼Ñ: {app_dt:%H:%M}\nÐÐ°ÑÐ¸ÐµÐ½Ñ: {safe_text(patient_name)}",
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.exception("2h reminder delivery failed for %s", app_id)


# ============================================================
# Error handler
# ============================================================

@bot.message_handler(func=lambda m: bool(m.text) and not m.text.startswith("/"))
def fallback_handler(message):
    if is_doctor(message.chat.id):
        bot.send_message(message.chat.id, "ÐÑÐ¿Ð¾Ð»ÑÐ·ÑÐ¹ÑÐµ ÐºÐ½Ð¾Ð¿ÐºÐ¸ Ð¿Ð°Ð½ÐµÐ»Ð¸ Ð²ÑÐ°ÑÐ°.", reply_markup=get_doctor_keyboard())
    else:
        bot.send_message(message.chat.id, "ÐÐµ Ð¿Ð¾Ð½ÑÐ» ÐºÐ¾Ð¼Ð°Ð½Ð´Ñ. ÐÑÐ±ÐµÑÐ¸ÑÐµ Ð´ÐµÐ¹ÑÑÐ²Ð¸Ðµ Ð² Ð¼ÐµÐ½Ñ.", reply_markup=get_main_keyboard())


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

    logger.info("Stoma dent bot started")
    try:
        bot.infinity_polling(
            skip_pending=True,
            timeout=20,
            long_polling_timeout=20,
        )
    finally:
        scheduler.shutdown(wait=False)
