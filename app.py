import os
import re
os.environ["KMP_DUPLICATE_LIB_OK"]="TRUE"
from flask import Flask, render_template, jsonify, send_from_directory, request, redirect, url_for, session, Response, send_file
from werkzeug.utils import secure_filename
import mysql.connector
import io
import pandas as pd
from datetime import datetime
import threading
import hmac
import time


import chatbot_logic

app = Flask(__name__)

def env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"Invalid integer for {name}: {raw}. Using default {default}.")
        return default


ENABLE_DETECTION = env_bool("SMARTGATE_ENABLE_DETECTION", True)
_DETECTION_MODULE = None


def _load_detection_module():
    global _DETECTION_MODULE
    if _DETECTION_MODULE is False:
        return None
    if _DETECTION_MODULE is not None:
        return _DETECTION_MODULE
    try:
        import main as detection_main
        _DETECTION_MODULE = detection_main
        return detection_main
    except Exception as e:
        print(f"Detection module disabled: {e}")
        _DETECTION_MODULE = False
        return None


# --- SECURITY CONFIGURATION ---
DEFAULT_SECRET_KEY = "super_secret_key_change_this"
app.secret_key = os.getenv("SMARTGATE_SECRET_KEY", DEFAULT_SECRET_KEY)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.getenv("SMARTGATE_SESSION_SAMESITE", "Lax"),
    SESSION_COOKIE_SECURE=env_bool("SMARTGATE_SESSION_SECURE", False),
)

ADMIN_USERNAME = os.getenv("SMARTGATE_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("SMARTGATE_ADMIN_PASS", "admin123")

DEFAULT_REPORT_TO = os.getenv("SMARTGATE_DEFAULT_REPORT_TO", "dharshan.s.2026@rkmshome.org")
SMTP_HOST = os.getenv("SMARTGATE_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = env_int("SMARTGATE_SMTP_PORT", 587)
SMTP_USER = os.getenv("SMARTGATE_SMTP_USER", "preetiking143@gmail.com")
SMTP_PASS = os.getenv("SMARTGATE_SMTP_PASS", "qbmg gucd qrlx rzsn")
SMTP_FROM_NAME = os.getenv("SMARTGATE_SMTP_FROM_NAME", "Smart Gate AI")

if app.secret_key == DEFAULT_SECRET_KEY:
    print("Warning: using default SMARTGATE_SECRET_KEY. Set SMARTGATE_SECRET_KEY for production.")
if ADMIN_USERNAME == "admin" and ADMIN_PASSWORD == "admin123":
    print("Warning: using default admin credentials. Set SMARTGATE_ADMIN_USER and SMARTGATE_ADMIN_PASS.")

# --- DATABASE & IMAGE CONFIG ---
IMAGE_FOLDER = os.getenv("SMARTGATE_IMAGE_FOLDER", "captured_images")
DB_CONFIG = {
    "host": os.getenv("SMARTGATE_DB_HOST", "localhost"),
    "user": os.getenv("SMARTGATE_DB_USER", "root"),
    "password": os.getenv("SMARTGATE_DB_PASSWORD", ""),
    "database": os.getenv("SMARTGATE_DB_NAME", "smart_gate"),
    "autocommit": True
}

db_port = os.getenv("SMARTGATE_DB_PORT")
if db_port:
    DB_CONFIG["port"] = env_int("SMARTGATE_DB_PORT", 3306)

_HOME_COLS_CACHE = None
_DETECTION_THREAD = None
_DETECTION_LOCK = threading.Lock()
_HOME_CATEGORY_MAP_CACHE = {}
_HOME_CATEGORY_MAP_CACHE_TS = 0.0

SYSTEM_CONFIG_DEFAULTS = {
    "smtp_user": SMTP_USER,
    "smtp_pass": SMTP_PASS,
    "default_report_to": DEFAULT_REPORT_TO,
    "smtp_from_name": SMTP_FROM_NAME,
    "admin_username": ADMIN_USERNAME,
    "admin_password": ADMIN_PASSWORD,
}


def _safe_int(value, default):
    try:
        return int(str(value).strip())
    except Exception:
        return default


def ensure_system_config_schema(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS system_config (
            id INT AUTO_INCREMENT PRIMARY KEY,
            config_key VARCHAR(100) UNIQUE NOT NULL,
            config_value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """
    )
    cursor.close()


def get_system_settings(conn):
    settings = dict(SYSTEM_CONFIG_DEFAULTS)
    ensure_system_config_schema(conn)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT config_key, config_value FROM system_config")
    for row in cursor.fetchall():
        key = row.get("config_key")
        if key in settings:
            settings[key] = row.get("config_value") or ""
    cursor.close()
    return settings


def save_system_settings(conn, settings):
    ensure_system_config_schema(conn)
    cursor = conn.cursor()
    for key, value in settings.items():
        cursor.execute(
            """
            INSERT INTO system_config (config_key, config_value)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)
            """,
            (key, value),
        )
    cursor.close()


def apply_system_settings(settings):
    global ADMIN_USERNAME, ADMIN_PASSWORD
    global DEFAULT_REPORT_TO, SMTP_USER, SMTP_PASS, SMTP_FROM_NAME

    ADMIN_USERNAME = (settings.get("admin_username") or ADMIN_USERNAME).strip()
    ADMIN_PASSWORD = (settings.get("admin_password") or ADMIN_PASSWORD).strip()
    SMTP_USER = (settings.get("smtp_user") or SMTP_USER).strip()
    SMTP_PASS = (settings.get("smtp_pass") or SMTP_PASS).strip()
    SMTP_FROM_NAME = (settings.get("smtp_from_name") or SMTP_FROM_NAME).strip()
    DEFAULT_REPORT_TO = (settings.get("default_report_to") or DEFAULT_REPORT_TO).strip()

    os.environ["SMARTGATE_ADMIN_USER"] = ADMIN_USERNAME
    os.environ["SMARTGATE_ADMIN_PASS"] = ADMIN_PASSWORD
    os.environ["SMARTGATE_SMTP_USER"] = SMTP_USER
    os.environ["SMARTGATE_SMTP_PASS"] = SMTP_PASS
    os.environ["SMARTGATE_SMTP_FROM_NAME"] = SMTP_FROM_NAME
    os.environ["SMARTGATE_DEFAULT_REPORT_TO"] = DEFAULT_REPORT_TO

    # Keep detector mail worker settings in sync without app restart.
    detection_main = _load_detection_module()
    if detection_main:
        detection_main.SMTP_USER = SMTP_USER
        detection_main.SMTP_PASS = SMTP_PASS
        detection_main.SMTP_FROM_NAME = SMTP_FROM_NAME
        detection_main.VEHICLE_ALERT_TO = DEFAULT_REPORT_TO
        if hasattr(detection_main, "_MAIL_CONFIG_WARNED"):
            detection_main._MAIL_CONFIG_WARNED = False


def load_system_settings_from_db():
    conn = get_db_connection()
    if not conn:
        return
    try:
        settings = get_system_settings(conn)
        apply_system_settings(settings)
    except Exception as e:
        print(f"System settings load error: {e}")
    finally:
        conn.close()

_ANALYTICS_KEYWORDS = {
    "analytics", "chart", "charts", "peak", "today", "hour", "hourly", "traffic",
    "weekly", "monthly", "weekday", "duration", "status", "split", "trend",
    "summary", "eda", "insight", "distribution", "top visitors", "top visitor",
    "type by category", "category", "vehicle type", "stats", "statistics",
    "data analysis", "explore", "pattern",
}

_SETTINGS_KEYWORDS = {
    "settings", "smtp", "email", "report", "default report", "home vehicles",
    "configuration", "config", "credentials", "admin",
}

_LOGIN_KEYWORDS = {
    "login", "login info", "how to login", "identity code", "passkey", "authenticate",
    "restricted access", "login page", "username", "password", "admin login",
}

_REPORT_KEYWORDS = {
    "send report", "email report", "report to email", "how to send", "pdf report",
    "csv report", "send email", "alert mail", "attachment",
}

_HELP_KEYWORDS = {"help", "what can you do", "capabilities", "command", "example", "who are you"}
_GREETING_KEYWORDS = {
    "hi", "hello", "hey", "vanakkam", "morning", "afternoon", "evening",
    "gm", "gn", "night", "how are you", "buddy", "friend", "social",
}

def _is_keyword_query(text, keywords):
    q = (text or "").lower()
    return any(k in q for k in keywords)

def _time_greeting():
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"

def _mask_email(email):
    if not email or "@" not in email:
        return "—"
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked = (name[:1] + "*") if name else "*"
    else:
        masked = name[0] + "*" * (len(name) - 2) + name[-1]
    return f"{masked}@{domain}"

def _get_basic_log_stats():
    conn = get_db_connection()
    if not conn:
        return {
            "total": 0,
            "today": 0,
            "inside": 0,
            "completed": 0,
        }
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) as total FROM vehicle_activity")
        total = cursor.fetchone().get("total", 0)
        cursor.execute("SELECT COUNT(*) as today FROM vehicle_activity WHERE DATE(entry_time) = CURDATE()")
        today = cursor.fetchone().get("today", 0)
        cursor.execute("SELECT COUNT(*) as inside FROM vehicle_activity WHERE status = 'Inside'")
        inside = cursor.fetchone().get("inside", 0)
        cursor.execute("SELECT COUNT(*) as completed FROM vehicle_activity WHERE status = 'Completed'")
        completed = cursor.fetchone().get("completed", 0)
        return {
            "total": total or 0,
            "today": today or 0,
            "inside": inside or 0,
            "completed": completed or 0,
        }
    except Exception:
        return {
            "total": 0,
            "today": 0,
            "inside": 0,
            "completed": 0,
        }
    finally:
        conn.close()

def _hour_label(hour):
    try:
        h = int(hour)
    except Exception:
        return "--"
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    return f"{h12} {suffix}"

def _table_from_rows(headers, rows):
    lines = ["TABLE:", "|".join(headers)]
    for row in rows:
        lines.append("|".join(str(x) for x in row))
    return "\n".join(lines)

def _build_analytics_response(question):
    payload = build_analytics_payload()
    stats = _get_basic_log_stats()

    hourly = payload.get("hourly") or []
    hourly_sorted = sorted(hourly, key=lambda x: (x.get("hour") if x else 0))
    if hourly_sorted:
        peak = max(hourly_sorted, key=lambda x: x.get("count", 0))
        peak_text = f"{_hour_label(peak.get('hour'))} ({peak.get('count', 0)} logs)"
    else:
        peak_text = "No logs today"

    type_data = payload.get("types") or []
    top_type = max(type_data, key=lambda x: x.get("count", 0), default=None)
    top_type_text = f"{top_type.get('vehicle_type')} ({top_type.get('count')} logs)" if top_type else "N/A"

    category_data = payload.get("categories") or []
    top_cat = max(category_data, key=lambda x: x.get("count", 0), default=None)
    top_cat_text = f"{top_cat.get('vehicle')} ({top_cat.get('count')} logs)" if top_cat else "N/A"

    # EDA Calculations
    total_logs = stats.get('total', 1)
    inside_count = stats.get('inside', 0)
    completed_count = stats.get('completed', 0)
    occupancy_rate = (inside_count / total_logs * 100) if total_logs > 0 else 0
    
    # Peak Period Category
    peak_hour = peak.get('hour', 0) if hourly_sorted else 0
    if 6 <= peak_hour < 11: peak_period = "Morning Rush (6 AM - 11 AM)"
    elif 11 <= peak_hour < 15: peak_period = "Noon Traffic (11 AM - 3 PM)"
    elif 15 <= peak_hour < 21: peak_period = "Evening Peak (3 PM - 9 PM)"
    else: peak_period = "Night Time / Late Shift (9 PM - 6 AM)"

    summary = (
        f"📊 **Smart Gate — Intelligence Summary** ({datetime.now().strftime('%d %b %Y')})\n\n"
        f"**Live Snapshot:**\n"
        f"- Currently inside: **{inside_count}** vehicles\n"
        f"- Today's traffic: **{stats.get('today', 0)}** entries\n"
        f"- System total: **{total_logs}** captures\n\n"
        f"**EDA Insights (Exploratory Data Analysis):**\n"
        f"- 📈 **Peak Hour**: {peak_text} — _This falls under {peak_period}._\n"
        f"- 🚗 **Dominant Vehicle**: {top_type_text}\n"
        f"- 🏡 **Most Common Category**: {top_cat_text}\n"
        f"- ⏱️ **Completion Rate**: {((completed_count/total_logs)*100):.1f}% of vehicles have exited.\n"
        f"- 🏢 **Occupancy Factor**: {occupancy_rate:.1f}% (Ratio of current vehicles vs historical total)."
    )

    q = (question or "").lower()
    wants_full = _is_keyword_query(q, {"analytics", "chart", "charts", "eda", "summary", "insight", "distribution", "trend"})
    wants_peak = "peak" in q or "hour" in q or "today" in q
    wants_weekly = "weekly" in q or "week" in q
    wants_monthly = "monthly" in q or "month" in q
    wants_weekday = "weekday" in q or "day" in q
    wants_status = "status" in q
    wants_duration = "duration" in q or "stay" in q
    wants_typecat = "type by category" in q or ("type" in q and "category" in q)
    wants_top = "top" in q or "visitor" in q

    sections = [summary]

    def add_hourly():
        rows = [[_hour_label(r.get("hour")), r.get("count", 0)] for r in hourly_sorted]
        sections.append("Peak Traffic Hours (Today)")
        sections.append(_table_from_rows(["Hour", "Count"], rows if rows else [["—", 0]]))

    def add_weekly():
        weekly = payload.get("weekly_trend") or []
        rows = [[r.get("date", "--"), r.get("count", 0)] for r in weekly]
        sections.append("Weekly Trend (Last 7 Days)")
        sections.append(_table_from_rows(["Date", "Count"], rows if rows else [["—", 0]]))

    def add_monthly():
        monthly = payload.get("monthly_trend") or []
        rows = [[r.get("month", "--"), r.get("count", 0)] for r in monthly]
        sections.append("Monthly Trend (Last 6 Months)")
        sections.append(_table_from_rows(["Month", "Count"], rows if rows else [["—", 0]]))

    def add_weekday():
        weekday = payload.get("weekday_dist") or []
        order = {"Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5, "Saturday": 6, "Sunday": 7}
        weekday = sorted(weekday, key=lambda r: order.get(r.get("day", ""), 99))
        rows = [[r.get("day", "--"), r.get("count", 0)] for r in weekday]
        sections.append("Weekday Distribution")
        sections.append(_table_from_rows(["Day", "Count"], rows if rows else [["—", 0]]))

    def add_duration():
        duration = payload.get("duration") or []
        rows = [[r.get("vehicle_type", "--"), int(r.get("avg_minutes") or 0)] for r in duration]
        sections.append("Avg Stay Duration (Minutes)")
        sections.append(_table_from_rows(["Vehicle Type", "Avg Minutes"], rows if rows else [["—", 0]]))

    def add_status():
        status = payload.get("status_split") or []
        rows = [[r.get("status", "--"), r.get("count", 0)] for r in status]
        sections.append("Status Split")
        sections.append(_table_from_rows(["Status", "Count"], rows if rows else [["—", 0]]))

    def add_type_by_category():
        tbc = payload.get("type_by_category") or []
        rows = [[r.get("category", "--"), r.get("vehicle_type", "--"), r.get("count", 0)] for r in tbc]
        sections.append("Vehicle Type by Category")
        sections.append(_table_from_rows(["Category", "Type", "Count"], rows if rows else [["—", "—", 0]]))

    def add_top_visitors():
        top = payload.get("top_visitors") or []
        rows = [[r.get("plate_number", "--"), r.get("vehicle", "--"), r.get("visits", 0)] for r in top]
        sections.append("Top Frequent Visitors")
        sections.append(_table_from_rows(["Plate", "Category", "Visits"], rows if rows else [["—", "—", 0]]))

    if wants_full or wants_peak:
        add_hourly()
    if wants_full or wants_weekly:
        add_weekly()
    if wants_full or wants_monthly:
        add_monthly()
    if wants_full or wants_weekday:
        add_weekday()
    if wants_full or wants_duration:
        add_duration()
    if wants_full or wants_status:
        add_status()
    if wants_full or wants_typecat:
        add_type_by_category()
    if wants_full or wants_top:
        add_top_visitors()

    return chatbot_logic.format_answer("\n\n".join(sections))

def _build_settings_response():
    base = (
        "⚙️ Settings Page Overview\n"
        "- Admin login username/password update\n"
        "- SMTP email settings (sender, app password)\n"
        "- Default report recipient email\n"
        "- Manage Home Vehicles (plate, type, owner, category)\n"
        "\n"
        "🔐 For security, passwords are never shown in chat."
    )
    if 'user' not in session:
        return chatbot_logic.format_answer(base + "\n\nLogin to view current configured values.")

    conn = get_db_connection()
    if not conn:
        return chatbot_logic.format_answer(base + "\n\n⚠️ Database connection failed.")
    try:
        settings = get_system_settings(conn)
        smtp_user = _mask_email(settings.get("smtp_user"))
        report_to = _mask_email(settings.get("default_report_to"))
        smtp_name = settings.get("smtp_from_name") or "Smart Gate AI"
        admin_user = settings.get("admin_username") or "admin"
        admin_user_masked = (admin_user[0] + "***") if admin_user else "***"
        extra = (
            "\n\nTABLE:\n"
            "Setting|Value\n"
            f"Admin Username|{admin_user_masked}\n"
            f"SMTP User|{smtp_user}\n"
            f"SMTP From Name|{smtp_name}\n"
            f"Default Report To|{report_to}"
        )
        return chatbot_logic.format_answer(base + extra)
    finally:
        conn.close()

def _build_login_info_response():
    text = (
        "🔐 **Security & Login Architecture**\n\n"
        "The login page is the gateway to the system. Here is the lowdown:\n\n"
        "**Features:**\n"
        "- **Identity Code**: Your unique admin ID.\n"
        "- **Secure Passkey**: Your encrypted password.\n"
        "- **Glassmorphism UI**: Uses a premium frosted-glass design with dark/light mode support.\n"
        "- **Authentication**: Uses `hmac` for constant-time password comparison to prevent timing attacks.\n"
        "- **Session Monitoring**: Restricted access with active monitoring.\n\n"
        "**Note:** To change credentials, visit the **Settings** page after logging in."
    )
    return chatbot_logic.format_answer(text)

def _build_help_response():
    greeting = _time_greeting()
    text = (
        f"{greeting}! 👋 நான் **Smart Gate AI Assistant**.\n\n"
        "I'm designed to be your project's mini-intelligence. You can ask me about:\n"
        "- **Analytics & EDA**: \"today peak chart\", \"trends\", \"visitor analysis\", \"summary\"\n"
        "- **Project Docs**: \"tech stack\", \"yolo\", \"database\", \"workflow\"\n"
        "- **Live Data**: Specific logs using `#ID` (example: `#222`)\n"
        "- **System Guide**: \"settings info\", \"login details\", \"hardware config\"\n\n"
        "Try asking: _\"how is the traffic trend?\"_ or _\"tell me about settings\"_"
    )
    return chatbot_logic.format_answer(text)
def _build_report_help_response():
    text = (
        "📩 **Email & Reporting System**\n\n"
        "This project allows sending reports directly to email. Here is how it works:\n\n"
        "- **Alert Mail**: Automatically sent when a vehicle is detected (as configured).\n"
        "- **Manual Export**: Navigate to the **Vehicle Logs** page and click the 'Download PDF/Excel' buttons.\n"
        "- **Send to Email**: In **Vehicle Logs**, click the **Report** (Email) button. You can then specify the receiver's email and choose a specific Log #ID (for photo + details) or send a full CSV.\n"
        "- **Configuration**: SMTP details can be updated in the **Settings** page.\n\n"
        "Note: Reports use the **Report To** email configured in your environment or settings."
    )
    return chatbot_logic.format_answer(text)

def _build_greeting_response(q):
    greeting = _time_greeting()
    
    # Friendly variations
    if "how are you" in q:
        text = f"{greeting}! 😊 I'm doing great, running smoothly on the server! 🚀 How can I help you with the Smart Gate data today?"
    elif "buddy" in q or "friend" in q:
        text = f"{greeting} buddy! 👋 It's nice to chat with you. I'm your Smart Gate AI companion. What shall we analyze today?"
    else:
        text = (
            f"{greeting}! 😊\n\n"
            "நான் **Smart Gate AI Assistant**. நான் ஒரு Project Mini-AI மாதிரி செயல்படுவேன்.\n"
            "Ask me about: **Analytics**, **Logs**, **Settings**, or **Tech Stack**.\n"
            "Example: _\"today peak chart\"_, _\"analytics summary\"_"
        )
    return chatbot_logic.format_answer(text)

def _build_sql_response(sql):
    conn = get_db_connection()
    if not conn:
        return {"html": "⚠️ Database connection failed."}
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql)
        rows = cursor.fetchall()
        
        if not rows:
            return {"html": "🔍 No matching records found in the database."}
        
        # Determine headers from first row
        headers = [str(k).replace("_", " ").title() for k in rows[0].keys() if k != 'image_path']
        
        lines = ["💡 Based on your query, I found the following records:\n\n", "TABLE:"]
        lines.append("|".join(headers))
        
        for row in rows:
            # Exclude image_path for table display cleaness
            row_data = [str(v) for k, v in row.items() if k != 'image_path']
            lines.append("|".join(row_data))
            
        return chatbot_logic.format_answer("\n".join(lines))
    except Exception as e:
        return {"html": f"⚠️ Query Error: {str(e)}"}
    finally:
        conn.close()

def normalize_vehicle_type_label(value):
    if not value:
        return "UNKNOWN"
    raw = str(value).strip().upper()
    aliases = {
        "BIKE": "MOTORCYCLE",
        "MOTORBIKE": "MOTORCYCLE",
        "MOTORCYCLE": "MOTORCYCLE",
        "BICYCLE": "BICYCLE",
        "CAR": "CAR",
        "TRUCK": "TRUCK",
        "BUS": "BUS",
        "TRAIN": "TRAIN",
    }
    return aliases.get(raw, raw)


def normalize_plate_value(value):
    if value is None:
        return ""
    return "".join(ch for ch in str(value).upper() if ch.isalnum())


def normalize_category_label(value):
    text = (value or "").strip()
    if not text:
        return "Home"
    lowered = text.lower()
    if lowered in {"unknown", "unknown vehicle"}:
        return "Home"
    return text


def parse_datetime_input(value):
    if value in (None, "", "null"):
        return None
    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]

    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def build_home_category_map(conn):
    mapping = {}
    try:
        ensure_home_vehicle_schema(conn)
        cols = get_home_vehicle_columns(conn)
        plate_col = cols["plate_col"]
        category_col = cols["category_col"]
        if not plate_col:
            return mapping

        cursor = conn.cursor(dictionary=True)
        if category_col:
            cursor.execute(f"SELECT {plate_col} AS plate_number, {category_col} AS category FROM home_vehicles")
        else:
            cursor.execute(f"SELECT {plate_col} AS plate_number, 'Home' AS category FROM home_vehicles")

        for row in cursor.fetchall():
            plate_key = normalize_plate_value(row.get("plate_number"))
            if not plate_key:
                continue
            mapping[plate_key] = normalize_category_label(row.get("category"))
        cursor.close()
    except Exception as e:
        print(f"Category map build error: {e}")
    return mapping


def get_home_category_map_cached(conn, ttl_sec=2.0):
    global _HOME_CATEGORY_MAP_CACHE, _HOME_CATEGORY_MAP_CACHE_TS
    now_ts = time.time()
    if _HOME_CATEGORY_MAP_CACHE and (now_ts - _HOME_CATEGORY_MAP_CACHE_TS) <= ttl_sec:
        return _HOME_CATEGORY_MAP_CACHE

    fresh_map = build_home_category_map(conn)
    _HOME_CATEGORY_MAP_CACHE = fresh_map
    _HOME_CATEGORY_MAP_CACHE_TS = now_ts
    return fresh_map


def resolve_log_vehicle_category(plate_number, logged_category, home_map):
    """
    Determines how to display the vehicle category.
    Prioritizes manual edits (logged_category) if they are not the default 'Visitor'/'Unknown'.
    If it's the default, tries to use the Home map for registered vehicles.
    """
    current_logged = (logged_category or "").strip()
    current_lowered = current_logged.lower()

    # If the user has manually entered a category (not Visitor/Unknown), respect it.
    if current_lowered not in {"visitor", "unknown", "unknown vehicle", "unregistered", ""}:
        return current_logged

    # Otherwise, fallback to database mapping if available
    plate_key = normalize_plate_value(plate_number)
    if plate_key and plate_key in home_map:
        return home_map[plate_key]

    return current_logged or "Unknown Vehicle"


def _try_remove_log_image(image_path):
    if not image_path:
        return False

    raw = str(image_path).replace("\\", "/").strip()
    if not raw:
        return False

    rel_name = raw
    if raw.startswith("captured_images/"):
        rel_name = raw.split("/", 1)[1]
    else:
        rel_name = os.path.basename(raw)

    if not rel_name:
        return False

    image_root = os.path.abspath(IMAGE_FOLDER)
    full_path = os.path.abspath(os.path.join(image_root, rel_name))
    if full_path != image_root and not full_path.startswith(image_root + os.sep):
        return False

    if os.path.exists(full_path):
        os.remove(full_path)
        return True
    return False

def get_db_connection():
    # Use the shared pool from the detection module if available
    detection_main = _load_detection_module()
    if detection_main and hasattr(detection_main, "get_db_connection"):
        conn = detection_main.get_db_connection()
        if conn: return conn

    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return None

def _fetch_home_vehicle_columns(conn):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
        (DB_CONFIG["database"], "home_vehicles"),
    )
    cols = {row[0] for row in cursor.fetchall()}
    cursor.close()
    return cols

def get_home_vehicle_columns(conn):
    global _HOME_COLS_CACHE
    if _HOME_COLS_CACHE is not None:
        return _HOME_COLS_CACHE

    cols = _fetch_home_vehicle_columns(conn)
    plate_col = "plate_number" if "plate_number" in cols else ("Licence_plate" if "Licence_plate" in cols else None)
    type_col = "vehicle_type" if "vehicle_type" in cols else ("Type" if "Type" in cols else None)
    owner_col = "owner_name" if "owner_name" in cols else None
    category_col = "category" if "category" in cols else None

    _HOME_COLS_CACHE = {
        "plate_col": plate_col,
        "type_col": type_col,
        "owner_col": owner_col,
        "category_col": category_col,
        "all_cols": cols,
    }
    return _HOME_COLS_CACHE

def ensure_home_vehicle_schema(conn):
    global _HOME_COLS_CACHE
    cols = _fetch_home_vehicle_columns(conn)
    cursor = conn.cursor()

    if "plate_number" not in cols:
        cursor.execute("ALTER TABLE home_vehicles ADD COLUMN plate_number VARCHAR(20)")
        if "Licence_plate" in cols:
            cursor.execute("UPDATE home_vehicles SET plate_number = Licence_plate WHERE plate_number IS NULL")

    if "vehicle_type" not in cols:
        cursor.execute("ALTER TABLE home_vehicles ADD COLUMN vehicle_type VARCHAR(50)")
        if "Type" in cols:
            cursor.execute("UPDATE home_vehicles SET vehicle_type = Type WHERE vehicle_type IS NULL")

    if "owner_name" not in cols:
        cursor.execute("ALTER TABLE home_vehicles ADD COLUMN owner_name VARCHAR(100) DEFAULT ''")

    if "category" not in cols:
        cursor.execute("ALTER TABLE home_vehicles ADD COLUMN category VARCHAR(50) DEFAULT 'Home'")

    if "updated_at" not in cols:
        cursor.execute("ALTER TABLE home_vehicles ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")

    cursor.close()
    _HOME_COLS_CACHE = None

def init_db():
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            # Create Home Vehicles Table (with indices)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS home_vehicles (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    plate_number VARCHAR(20) UNIQUE NOT NULL,
                    owner_name VARCHAR(100),
                    vehicle_type VARCHAR(50),
                    category VARCHAR(50) DEFAULT 'Home',
                    INDEX (plate_number)
                )
            """)
            # Create Logs Table (with indices)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vehicle_activity (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    plate_number VARCHAR(20),
                    vehicle_type VARCHAR(50),
                    entry_time DATETIME,
                    exit_time DATETIME,
                    status VARCHAR(20),
                    image_path VARCHAR(255),
                    vehicle VARCHAR(50) DEFAULT 'Visitor',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    INDEX (plate_number),
                    INDEX (status),
                    INDEX (entry_time),
                    INDEX (updated_at)
                )
            """)
            ensure_system_config_schema(conn)
            ensure_home_vehicle_schema(conn)
        finally:
            conn.close()

# Initialize DB on start
init_db()
load_system_settings_from_db()


def ensure_detection_running():
    global _DETECTION_THREAD
    if not ENABLE_DETECTION:
        return
    detection_main = _load_detection_module()
    if not detection_main:
        return
    with _DETECTION_LOCK:
        if _DETECTION_THREAD and _DETECTION_THREAD.is_alive():
            return
        _DETECTION_THREAD = threading.Thread(target=detection_main.start_detection, daemon=True)
        _DETECTION_THREAD.start()

def _camera_fallback_stream():
    # Lightweight fallback stream when detection module is unavailable.
    try:
        import cv2
        import numpy as np
    except Exception:
        # As a last resort, just yield empty frames to keep the connection alive.
        while True:
            time.sleep(0.5)
            yield b""

    cam_w = env_int("SMARTGATE_CAMERA_WIDTH", 1280)
    cam_h = env_int("SMARTGATE_CAMERA_HEIGHT", 720)
    cam_fps = env_int("SMARTGATE_CAMERA_FPS", 20)

    cap = None
    last_retry = 0.0

    def _backend_candidates():
        candidates = []
        if hasattr(cv2, "CAP_DSHOW"):
            candidates.append(("DSHOW", cv2.CAP_DSHOW))
        if hasattr(cv2, "CAP_MSMF"):
            candidates.append(("MSMF", cv2.CAP_MSMF))
        if hasattr(cv2, "CAP_ANY"):
            candidates.append(("ANY", cv2.CAP_ANY))
        candidates.append(("DEFAULT", None))
        return candidates

    camera_index = env_int("SMARTGATE_CAMERA_INDEX", -1)
    index_list = (camera_index,) if camera_index >= 0 else (0, 1, 2)
    backend_name = os.getenv("SMARTGATE_CAMERA_BACKEND", "").strip().upper()
    backend_override = None
    if backend_name == "DSHOW" and hasattr(cv2, "CAP_DSHOW"):
        backend_override = cv2.CAP_DSHOW
    elif backend_name == "MSMF" and hasattr(cv2, "CAP_MSMF"):
        backend_override = cv2.CAP_MSMF
    elif backend_name == "ANY" and hasattr(cv2, "CAP_ANY"):
        backend_override = cv2.CAP_ANY
    elif backend_name == "DEFAULT":
        backend_override = None

    def _open_cam():
        for idx in index_list:
            candidates = (
                [(backend_name or "DEFAULT", backend_override)]
                if backend_name and backend_override is not None
                else _backend_candidates()
            )
            for name, code in candidates:
                c = cv2.VideoCapture(idx) if code is None else cv2.VideoCapture(idx, code)
                if c and c.isOpened():
                    try:
                        c.set(cv2.CAP_PROP_FRAME_WIDTH, cam_w)
                        c.set(cv2.CAP_PROP_FRAME_HEIGHT, cam_h)
                        c.set(cv2.CAP_PROP_FPS, cam_fps)
                    except Exception:
                        pass
                    return c
                if c:
                    c.release()
        return None

    def _fallback_frame():
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        lines = [
            "CAMERA PREVIEW UNAVAILABLE",
            "Detection module not loaded.",
            "Fix: Python 3.10/3.11 + torch",
            "or set SMARTGATE_ENABLE_DETECTION=1",
        ]
        y = 190
        for line in lines:
            cv2.putText(img, line, (30, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 180, 255), 2)
            y += 30
        ok, encoded = cv2.imencode(".jpg", img)
        return encoded.tobytes() if ok else b""

    placeholder = _fallback_frame()
    while True:
        if cap is None or not cap.isOpened():
            now = time.time()
            if now - last_retry > 2.0:
                cap = _open_cam()
                last_retry = now
            if not cap:
                if isinstance(placeholder, bytes) and len(placeholder) > 0:
                    try:
                        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + placeholder + b'\r\n'
                    except Exception:
                        pass
                else:
                    time.sleep(0.1)
                continue

        ret, frame = cap.read()
        if not ret:
            try:
                cap.release()
            except Exception:
                pass
            cap = None
            time.sleep(0.2)
            continue
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            time.sleep(0.02)
            continue
        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + encoded.tobytes() + b'\r\n'

# --- AUTHENTICATION ROUTES ---


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Check credentials from environment-configured admin account
        if hmac.compare_digest(username, ADMIN_USERNAME) and hmac.compare_digest(password, ADMIN_PASSWORD):
            session['user'] = username
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Invalid Username or Password")
                   
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

# --- PROTECTED PAGES (Login Required) ---

@app.route('/')
def index():
    if 'user' not in session: return redirect(url_for('login'))
    ensure_detection_running()
    return render_template('index.html')

@app.route('/logs')
def logs():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template('vehicle_logs.html')

@app.route('/analytics')
def analytics():
    if 'user' not in session: return redirect(url_for('login'))
    return render_template('analytics.html')

@app.route('/settings/delete/<string:plate>')
def delete_vehicle(plate):
    if 'user' not in session: return redirect(url_for('login'))
    global _HOME_CATEGORY_MAP_CACHE, _HOME_CATEGORY_MAP_CACHE_TS
    plate_norm = normalize_plate_value(plate)

    conn = get_db_connection()
    if conn:
        try:
            cols = get_home_vehicle_columns(conn)
            plate_col = cols["plate_col"]
            if not plate_col:
                return redirect(url_for('settings'))
            cursor = conn.cursor()
            plate_expr = f"UPPER(REPLACE(REPLACE(REPLACE(REPLACE(IFNULL({plate_col}, ''), ' ', ''), '-', ''), '.', ''), '_', ''))"
            cursor.execute(
                f"DELETE FROM home_vehicles WHERE {plate_col} = %s OR {plate_expr} = %s",
                (plate_norm, plate_norm),
            )
            conn.commit()
            _HOME_CATEGORY_MAP_CACHE = {}
            _HOME_CATEGORY_MAP_CACHE_TS = 0.0
        finally:
            conn.close()
    
    return redirect(url_for('settings'))

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'user' not in session: return redirect(url_for('login'))
    global _HOME_CATEGORY_MAP_CACHE, _HOME_CATEGORY_MAP_CACHE_TS
    
    conn = get_db_connection()
    if not conn: return "Database Connection Error. Please check if MySQL is running.", 500
    
    message = None
    system_message = None
    vehicles = []
    system_settings = dict(SYSTEM_CONFIG_DEFAULTS)
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        ensure_home_vehicle_schema(conn)
        cols = get_home_vehicle_columns(conn)
        system_settings = get_system_settings(conn)

        if request.method == 'POST':
            form_type = (request.form.get('form_type') or 'vehicle').strip().lower()
            if form_type == 'system':
                updated_settings = {
                    "smtp_user": request.form.get('smtp_user', '').strip(),
                    "smtp_pass": request.form.get('smtp_pass', '').strip(),
                    "default_report_to": request.form.get('default_report_to', '').strip(),
                    "smtp_from_name": request.form.get('smtp_from_name', '').strip() or "Smart Gate AI",
                    "admin_username": request.form.get('admin_username', '').strip(),
                    "admin_password": request.form.get('admin_password', '').strip(),
                }

                if not updated_settings["admin_username"] or not updated_settings["admin_password"]:
                    system_message = "[ERROR] Login username and password are required."
                elif not updated_settings["default_report_to"]:
                    system_message = "[ERROR] Default receiver email is required."
                else:
                    save_system_settings(conn, updated_settings)
                    conn.commit()
                    apply_system_settings(updated_settings)
                    system_settings = updated_settings
                    system_message = "[OK] Email and login credentials updated successfully."
            else:
                plate = normalize_plate_value(request.form.get('plate', ''))
                owner = request.form.get('owner', '').strip()
                v_type = normalize_vehicle_type_label(request.form.get('type', 'UNKNOWN'))
                category = normalize_category_label(request.form.get('category', 'Home'))

                if not plate:
                    message = "[ERROR] Plate number is required."
                else:
                    try:
                        plate_col = cols["plate_col"] or "plate_number"
                        type_col = cols["type_col"] or "vehicle_type"
                        insert_cols = [plate_col, type_col]
                        insert_vals = [plate, v_type]

                        if cols["owner_col"]:
                            insert_cols.append(cols["owner_col"])
                            insert_vals.append(owner)
                        if cols["category_col"]:
                            insert_cols.append(cols["category_col"])
                            insert_vals.append(category)

                        placeholders = ", ".join(["%s"] * len(insert_cols))
                        sql = f"INSERT INTO home_vehicles ({', '.join(insert_cols)}) VALUES ({placeholders})"
                        cursor.execute(sql, tuple(insert_vals))
                        conn.commit()
                        _HOME_CATEGORY_MAP_CACHE = {}
                        _HOME_CATEGORY_MAP_CACHE_TS = 0.0
                        message = f"[OK] Vehicle {plate} registered successfully."
                    except mysql.connector.Error as err:
                        if err.errno == 1062:
                            message = f"[ERROR] Vehicle {plate} is already registered."
                        else:
                            message = f"[ERROR] Database error: {err}"

        plate_col = cols["plate_col"] or "plate_number"
        type_col = cols["type_col"] or "vehicle_type"
        select_parts = [
            f"{plate_col} AS plate_number",
            f"{type_col} AS vehicle_type"
        ]
        if cols["owner_col"]:
            select_parts.append(f"{cols['owner_col']} AS owner_name")
        if cols["category_col"]:
            select_parts.append(f"{cols['category_col']} AS category")

        cursor.execute(f"SELECT {', '.join(select_parts)} FROM home_vehicles")
        vehicles = cursor.fetchall()
        cursor.close()
        
    except Exception as e:
        print(f"Settings Error: {e}")
        return render_template(
            'settings.html',
            vehicles=[],
            message=f"System Error: {str(e)}",
            system_message=system_message,
            system_settings=system_settings
        )
    finally:
        if conn: conn.close()
    
    return render_template(
        'settings.html',
        vehicles=vehicles,
        message=message,
        system_message=system_message,
        system_settings=system_settings
    )

# --- IMAGE SERVING & API ---

# Image serving endpoint
@app.route('/captured_images/<path:filename>')
def serve_image(filename):
    if 'user' not in session: return jsonify({"error": "Unauthorized"}), 401
    clean_name = filename.replace('captured_images/', '').replace('captured_images\\', '')
    file_path = os.path.join(IMAGE_FOLDER, clean_name)
    if not os.path.exists(file_path):
        return send_from_directory("static", "logo.png")
    return send_from_directory(IMAGE_FOLDER, clean_name)

@app.route('/video_feed')
def video_feed():
    if 'user' not in session: return redirect(url_for('login'))
    detection_main = _load_detection_module()
    if not detection_main or not ENABLE_DETECTION:
        return Response(_camera_fallback_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')
    ensure_detection_running()
    return Response(detection_main.generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/latest_alert')
def api_latest_alert():
    if 'user' not in session: return jsonify(None)
    ensure_detection_running()
    conn = get_db_connection()
    if not conn:
        return jsonify(None)
    try:
        cursor = conn.cursor(dictionary=True, buffered=True)
        # Check if updated_at exists, if so use it for most reliable 'latest event' detection
        cursor.execute("SHOW COLUMNS FROM vehicle_activity LIKE 'updated_at'")
        has_updated_at = cursor.fetchone()
        
        if has_updated_at:
            # Sort by ID primary, then updated_at to handle weird future timestamps
            cursor.execute("SELECT *, updated_at as last_event FROM vehicle_activity ORDER BY id DESC, updated_at DESC LIMIT 1")
        else:
            cursor.execute("SELECT *, COALESCE(exit_time, entry_time) as last_event FROM vehicle_activity ORDER BY id DESC LIMIT 1")
            
        row = cursor.fetchone()
        home_map = get_home_category_map_cached(conn)
        if row:
            row['vehicle'] = resolve_log_vehicle_category(row.get('plate_number'), row.get('vehicle'), home_map)
            
            # Use the most recent event for display time
            event_time = row['last_event'] if row.get('last_event') else row['entry_time']
            time_diff = datetime.now() - event_time
            time_str = "Just now" if abs(time_diff.total_seconds()) < 60 else event_time.strftime("%H:%M:%S")

            return jsonify({
                "id": row['id'],
                "plate": row['plate_number'],
                "type": row['vehicle_type'],
                "category": row.get('vehicle'),
                "status": row['status'],
                "time": time_str,
                "image": row['image_path'],
                "last_event_ts": row['last_event'].timestamp() if hasattr(row['last_event'], 'timestamp') else time.time()
            })
        return jsonify(None)
    finally:
        conn.close()

@app.route('/api/stats')
def get_stats():
    if 'user' not in session: return jsonify(None)
    ensure_detection_running()
    conn = get_db_connection()
    if not conn:
        return jsonify({"total_today": 0, "inside_now": 0})
    try:
        cursor = conn.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT COUNT(*) as total FROM vehicle_activity WHERE DATE(entry_time) = CURDATE()")
        total_today = cursor.fetchone()['total']
        cursor.execute("SELECT COUNT(*) as inside FROM vehicle_activity WHERE status = 'Inside'")
        inside_now = cursor.fetchone()['inside']
        return jsonify({"total_today": total_today, "inside_now": inside_now})
    finally:
        conn.close()

@app.route('/api/all_logs')
def api_all_logs():
    if 'user' not in session: return jsonify(None)
    ensure_detection_running()
    try:
        limit = int(request.args.get('limit', 300))
    except (TypeError, ValueError):
        limit = 300
    limit = max(20, min(1000, limit))

    conn = get_db_connection()
    if not conn:
        return jsonify([])
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"SELECT * FROM vehicle_activity ORDER BY id DESC LIMIT {limit}")
        rows = cursor.fetchall()
        home_map = get_home_category_map_cached(conn)
        
        # Calculate duration for each row
        for row in rows:
            row['vehicle'] = resolve_log_vehicle_category(row.get('plate_number'), row.get('vehicle'), home_map)
            if row['exit_time'] and row['entry_time']:
                diff = row['exit_time'] - row['entry_time']
                hours, remainder = divmod(diff.total_seconds(), 3600)
                minutes, _ = divmod(remainder, 60)
                if hours > 0:
                    row['duration'] = f"{int(hours)}h {int(minutes)}m"
                else:
                    row['duration'] = f"{int(minutes)}m"
            else:
                row['duration'] = "N/A"
        return jsonify(rows)
    finally:
        conn.close()


@app.route('/api/logs/<int:record_id>', methods=['PUT', 'POST'])
def api_update_log(record_id):
    if 'user' not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    payload = request.get_json(silent=True) or {}

    plate = normalize_plate_value(payload.get('plate_number'))
    if not plate:
        return jsonify({"success": False, "error": "Plate number is required"}), 400

    vehicle_type = normalize_vehicle_type_label(payload.get('vehicle_type'))
    vehicle_category = (payload.get('vehicle') or "").strip() or "Visitor"
    status = (payload.get('status') or "Inside").strip()
    if status not in {"Inside", "Completed"}:
        return jsonify({"success": False, "error": "Status must be Inside or Completed"}), 400

    entry_time = parse_datetime_input(payload.get('entry_time'))
    if not entry_time:
        return jsonify({"success": False, "error": "Valid entry time is required"}), 400

    exit_time = parse_datetime_input(payload.get('exit_time'))
    if status == "Inside":
        exit_time = None
    elif not exit_time:
        return jsonify({"success": False, "error": "Exit time is required when status is Completed"}), 400
    if exit_time and exit_time < entry_time:
        return jsonify({"success": False, "error": "Exit time cannot be before entry time"}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "error": "Database connection failed"}), 500

    try:
        home_map = build_home_category_map(conn)
        vehicle_category = resolve_log_vehicle_category(plate, vehicle_category, home_map)

        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE vehicle_activity
            SET plate_number=%s, vehicle_type=%s, entry_time=%s, exit_time=%s, status=%s, vehicle=%s
            WHERE id=%s
            """,
            (plate, vehicle_type, entry_time, exit_time, status, vehicle_category, record_id),
        )
        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({"success": False, "error": f"Record #{record_id} not found"}), 404
        return jsonify({"success": True, "message": f"Record #{record_id} updated"})
    except Exception as e:
        print(f"Log update error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()

_LOG_ID_PATTERN = re.compile(r'(?:#\s*(\d+)|\b(?:log|record|id)\s*#?\s*(\d+)\b)', re.IGNORECASE)

def _extract_log_id(text):
    if not text:
        return None
    match = _LOG_ID_PATTERN.search(text)
    if not match:
        return None
    for group in match.groups():
        if group:
            try:
                return int(group)
            except ValueError:
                return None
    return None

def _format_dt(value):
    if not value:
        return "--"
    try:
        return value.strftime("%d/%m/%Y %I:%M:%S %p")
    except Exception:
        return str(value)

def _compute_duration(entry_time, exit_time):
    if not entry_time or not exit_time:
        return "N/A"
    try:
        diff = exit_time - entry_time
        total_minutes = int(diff.total_seconds() // 60)
        hours, minutes = divmod(max(total_minutes, 0), 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    except Exception:
        return "N/A"

def _build_log_details_response(log_id):
    conn = get_db_connection()
    if not conn:
        return {'html': '⚠️ Database connection failed.'}
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM vehicle_activity WHERE id = %s", (log_id,))
        row = cursor.fetchone()
        if not row:
            return chatbot_logic.format_answer(f"❌ Log #{log_id} கிடைக்கவில்லை. Please check the ID.")

        home_map = build_home_category_map(conn)
        row['vehicle'] = resolve_log_vehicle_category(row.get('plate_number'), row.get('vehicle'), home_map)

        plate = row.get('plate_number') or 'N/A'
        vehicle_type = row.get('vehicle_type') or 'UNKNOWN'
        category = row.get('vehicle') or 'Unknown'
        status = row.get('status') or 'Unknown'
        entry_time = _format_dt(row.get('entry_time'))
        exit_time = _format_dt(row.get('exit_time'))
        duration = _compute_duration(row.get('entry_time'), row.get('exit_time'))

        text = (
            f"📄 Log Details for #{log_id}\n\n"
            "TABLE:\n"
            "Field|Value\n"
            f"Plate Number|{plate}\n"
            f"Category|{category}\n"
            f"Vehicle Type|{vehicle_type}\n"
            f"Status|{status}\n"
            f"Entry Time|{entry_time}\n"
            f"Exit Time|{exit_time}\n"
            f"Duration|{duration}"
        )
        result = chatbot_logic.format_answer(text)

        image_path = row.get('image_path') or ''
        if image_path:
            img_src = '/' + str(image_path).lstrip('/')
            result['html'] += (
                '<div class="sg-line">Image:</div>'
                '<div class="sg-line">'
                f'<img src="{img_src}" style="width:100%;max-height:220px;object-fit:cover;'
                'border-radius:10px;border:1px solid rgba(0,212,255,.18);">'
                '</div>'
            )
        return result
    finally:
        conn.close()
  


@app.route('/api/logs/<int:record_id>', methods=['DELETE'])
def api_delete_log(record_id):
    if 'user' not in session:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({"success": False, "error": "Database connection failed"}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, image_path FROM vehicle_activity WHERE id = %s", (record_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "error": f"Record #{record_id} not found"}), 404

        cursor.execute("DELETE FROM vehicle_activity WHERE id = %s", (record_id,))
        conn.commit()

        image_deleted = _try_remove_log_image(row.get("image_path"))
        return jsonify({
            "success": True,
            "message": f"Record #{record_id} deleted",
            "image_deleted": image_deleted
        })
    except Exception as e:
        print(f"Log delete error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/analytics_data')
def api_analytics_data():
    if 'user' not in session: return jsonify(None)

    payload = build_analytics_payload()
    return jsonify(payload)


def build_analytics_payload():
    conn = get_db_connection()
    if not conn:
        return {
            "types": [],
            "hourly": [],
            "categories": [],
            "duration": [],
            "top_visitors": [],
            "weekly_trend": [],
            "monthly_trend": [],
            "weekday_dist": [],
            "status_split": [],
            "type_by_category": [],
        }

    try:
        cursor = conn.cursor(dictionary=True)

        # 1. Types
        cursor.execute("SELECT vehicle_type, COUNT(*) as count FROM vehicle_activity GROUP BY vehicle_type")
        type_data = cursor.fetchall()

        # 2. Hourly
        cursor.execute("""
            SELECT HOUR(entry_time) as hour, COUNT(*) as count
            FROM vehicle_activity
            WHERE DATE(entry_time) = CURDATE()
            GROUP BY HOUR(entry_time)
        """)
        hour_data = cursor.fetchall()

        # 3. Categories
        cursor.execute("SELECT vehicle, COUNT(*) as count FROM vehicle_activity GROUP BY vehicle")
        category_data = cursor.fetchall()

        # 4. Duration
        cursor.execute("""
            SELECT vehicle_type, AVG(TIMESTAMPDIFF(MINUTE, entry_time, exit_time)) as avg_minutes
            FROM vehicle_activity
            WHERE status = 'Completed' AND exit_time IS NOT NULL
            GROUP BY vehicle_type
        """)
        duration_data = cursor.fetchall()

        # 5. Top Visitors
        cursor.execute("""
            SELECT plate_number, vehicle, COUNT(*) as visits
            FROM vehicle_activity
            GROUP BY plate_number, vehicle
            ORDER BY visits DESC
            LIMIT 5
        """)
        top_visitors = cursor.fetchall()

        # 6. Weekly Trend
        weekly_trend = get_weekly_trend(cursor)

        # 7. Monthly Trend (Last 6 Months)
        cursor.execute("""
            SELECT DATE_FORMAT(entry_time, '%Y-%m') as month, COUNT(*) as count
            FROM vehicle_activity
            WHERE entry_time >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
            GROUP BY month
            ORDER BY month ASC
        """)
        monthly_trend = cursor.fetchall()

        # 8. Weekday Distribution
        cursor.execute("""
            SELECT DAYNAME(entry_time) as day, COUNT(*) as count
            FROM vehicle_activity
            GROUP BY day
        """)
        weekday_dist = cursor.fetchall()

        # 9. Status Split
        cursor.execute("SELECT status, COUNT(*) as count FROM vehicle_activity GROUP BY status")
        status_split = cursor.fetchall()

        # 10. Type-by-Category
        cursor.execute("""
            SELECT vehicle as category, vehicle_type, COUNT(*) as count
            FROM vehicle_activity
            GROUP BY vehicle, vehicle_type
            ORDER BY vehicle, vehicle_type
        """)
        type_by_category = cursor.fetchall()

        return {
            "types": type_data,
            "hourly": hour_data,
            "categories": category_data,
            "duration": duration_data,
            "top_visitors": top_visitors,
            "weekly_trend": weekly_trend,
            "monthly_trend": monthly_trend,
            "weekday_dist": weekday_dist,
            "status_split": status_split,
            "type_by_category": type_by_category,
        }
    finally:
        conn.close()


def get_weekly_trend(cursor=None):
    owned_conn = None
    try:
        if cursor is None:
            owned_conn = get_db_connection()
            if not owned_conn:
                return []
            cursor = owned_conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT DATE_FORMAT(entry_time, '%Y-%m-%d') as date, COUNT(*) as count
            FROM vehicle_activity
            WHERE entry_time >= DATE_SUB(CURDATE(), INTERVAL 6 DAY)
            GROUP BY date
            ORDER BY date ASC
        """)
        return cursor.fetchall()
    except Exception:
        return []
    finally:
        if owned_conn:
            owned_conn.close()

@app.route('/api/export_logs')
def export_logs():
    if 'user' not in session: return redirect(url_for('login'))

    fmt = request.args.get('format', 'csv').lower()
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    from_time = request.args.get('from_time')
    to_time = request.args.get('to_time')
    month = request.args.get('month')  # YYYY-MM
    id_from = request.args.get('id_from')
    id_to = request.args.get('id_to')
    types_raw = request.args.get('types') or request.args.get('type')

    conditions = []
    params = []

    if id_from:
        conditions.append("id >= %s")
        params.append(id_from)
    if id_to:
        conditions.append("id <= %s")
        params.append(id_to)

    if types_raw:
        type_list = [t.strip() for t in types_raw.split(',') if t.strip()]
        if type_list:
            type_aliases = {
                'BIKE': 'MOTORCYCLE',
                'MOTORBIKE': 'MOTORCYCLE',
                'MOTORCYCLE': 'MOTORCYCLE',
                'CAR': 'CAR',
                'TRUCK': 'TRUCK',
                'BUS': 'BUS',
                'TRAIN': 'TRAIN',
                'BICYCLE': 'BICYCLE',
            }
            normalized = []
            for t in type_list:
                upper = t.upper()
                normalized.append(type_aliases.get(upper, upper))
            # Deduplicate while preserving order
            seen = set()
            type_list = [x for x in normalized if not (x in seen or seen.add(x))]

            placeholders = ", ".join(["%s"] * len(type_list))
            conditions.append(f"vehicle_type IN ({placeholders})")
            params.extend(type_list)

    if month:
        conditions.append("DATE_FORMAT(entry_time, '%Y-%m') = %s")
        params.append(month)

    if from_date and from_time:
        conditions.append("entry_time >= %s")
        params.append(f"{from_date} {from_time}:00")
    elif from_date:
        conditions.append("DATE(entry_time) >= %s")
        params.append(from_date)

    if to_date and to_time:
        conditions.append("entry_time <= %s")
        params.append(f"{to_date} {to_time}:59")
    elif to_date:
        conditions.append("DATE(entry_time) <= %s")
        params.append(to_date)

    if from_time and not from_date and to_time and not to_date:
        conditions.append("TIME(entry_time) BETWEEN %s AND %s")
        params.extend([from_time, to_time])

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    query = f"SELECT * FROM vehicle_activity {where_clause} ORDER BY entry_time DESC"

    conn = get_db_connection()
    if not conn:
        return "Database Connection Error", 500

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
    finally:
        conn.close()

    # Compute duration and format values
    def fmt_dt(val):
        if not val:
            return ""
        try:
            return val.strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return str(val)

    for row in rows:
        if row.get('exit_time') and row.get('entry_time'):
            diff = row['exit_time'] - row['entry_time']
            h, rem = divmod(diff.total_seconds(), 3600)
            m, _ = divmod(rem, 60)
            row['duration'] = f"{int(h)}h {int(m)}m" if h > 0 else f"{int(m)}m"
        else:
            row['duration'] = "N/A"
        row['entry_time'] = fmt_dt(row.get('entry_time'))
        row['exit_time'] = fmt_dt(row.get('exit_time'))

    cols = [
        'id', 'plate_number', 'vehicle_type', 'vehicle', 'status',
        'entry_time', 'exit_time', 'duration', 'image_path'
    ]

    if fmt in ('excel', 'xls', 'xlsx'):
        # Excel-compatible HTML table (no extra dependencies)
        header = "".join([f"<th>{c}</th>" for c in cols])
        body_rows = []
        for r in rows:
            body_rows.append("<tr>" + "".join([f"<td>{r.get(c, '')}</td>" for c in cols]) + "</tr>")
        table = f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
        return Response(
            table,
            mimetype='application/vnd.ms-excel',
            headers={'Content-Disposition': 'attachment; filename=vehicle_logs.xls'}
        )

    # CSV
    import csv
    from io import StringIO
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=cols)
    writer.writeheader()
    for r in rows:
        writer.writerow({c: r.get(c, "") for c in cols})

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=vehicle_logs.csv'}
    )


@app.route('/api/export_analytics')
def export_analytics():
    if 'user' not in session: return redirect(url_for('login'))

    fmt = request.args.get('format', 'json').lower()
    data = build_analytics_payload()

    if fmt == 'csv':
        import csv
        from io import StringIO
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(['dataset', 'label', 'value', 'extra'])

        for row in data.get('hourly', []):
            writer.writerow(['hourly', f"{row.get('hour', '')}:00", row.get('count', 0), ''])
        for row in data.get('weekly_trend', []):
            writer.writerow(['weekly_trend', row.get('date', ''), row.get('count', 0), ''])
        for row in data.get('monthly_trend', []):
            writer.writerow(['monthly_trend', row.get('month', ''), row.get('count', 0), ''])
        for row in data.get('weekday_dist', []):
            writer.writerow(['weekday_dist', row.get('day', ''), row.get('count', 0), ''])
        for row in data.get('categories', []):
            writer.writerow(['categories', row.get('vehicle', ''), row.get('count', 0), ''])
        for row in data.get('types', []):
            writer.writerow(['types', row.get('vehicle_type', ''), row.get('count', 0), ''])
        for row in data.get('duration', []):
            writer.writerow(['duration', row.get('vehicle_type', ''), row.get('avg_minutes', 0), 'minutes'])
        for row in data.get('status_split', []):
            writer.writerow(['status_split', row.get('status', ''), row.get('count', 0), ''])
        for row in data.get('type_by_category', []):
            writer.writerow(['type_by_category', row.get('vehicle_type', ''), row.get('count', 0), row.get('category', '')])
        for row in data.get('top_visitors', []):
            writer.writerow(['top_visitors', row.get('plate_number', ''), row.get('visits', 0), row.get('vehicle', '')])

        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=analytics.csv'}
        )

    return jsonify(data)


@app.route('/api/send_report')
def send_report():
    if 'user' not in session: return jsonify({"error": "Unauthorized"}), 401
    
    receiver_email = request.args.get('to', DEFAULT_REPORT_TO)
    subject_req = request.args.get('subject')
    record_id = request.args.get('id')
    
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email.mime.image import MIMEImage
    from email import encoders
    import pandas as pd
    import io
    import os
    from datetime import datetime

    try:
        sender_email = SMTP_USER
        sender_password = SMTP_PASS
        if not sender_email or not sender_password:
            return jsonify({
                "success": False,
                "error": "SMTP credentials not configured. Set SMARTGATE_SMTP_USER and SMARTGATE_SMTP_PASS."
            }), 500

        # 1. Prepare Content
        conn = get_db_connection()
        if not conn: return jsonify({"success": False, "error": "Database connection failed"}), 500
        
        try:
            body_html = ""
            subject = subject_req or "Vehicle Activity Report"
            attachment_payload = None
            attachment_filename = ""
            image_part = None

            if record_id:
                # SEND SPECIFIC RECORD (PREMIUM HTML)
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT * FROM vehicle_activity WHERE id = %s", (record_id,))
                row = cursor.fetchone()
                if not row:
                    return jsonify({"success": False, "error": f"Record #{record_id} not found"}), 404
                
                duration = "N/A"
                if row['exit_time'] and row['entry_time']:
                    diff = row['exit_time'] - row['entry_time']
                    h, rem = divmod(diff.total_seconds(), 3600)
                    m, _ = divmod(rem, 60)
                    duration = f"{int(h)}h {int(m)}m" if h > 0 else f"{int(m)}m"

                subject = f"[ALERT] Vehicle Alert: [{row['plate_number']}] - {row['vehicle']}"
                
                # Create Beautiful HTML Body
                body_html = f"""
                <html>
                <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #f0f2f5; color: #1c1e21; margin: 0; padding: 20px;">
                    <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.15); border: 1px solid #ddd;">
                        <!-- Header -->
                        <div style="background: #0f172a; color: #ffffff; padding: 25px; border-bottom: 4px solid #10b981;">
                            <h1 style="margin: 0; font-size: 24px; font-weight: bold; letter-spacing: 2px;">SMART <span style="color: #10b981;">GATE</span></h1>
                            <p style="margin: 5px 0 0; font-size: 10px; opacity: 0.7; letter-spacing: 1px;">AI-POWERED SECURITY SYSTEM</p>
                        </div>
                        
                        <!-- ID Badge -->
                        <div style="padding: 15px 25px 0; text-align: right;">
                            <span style="background: #f1f5f9; padding: 4px 12px; border-radius: 4px; font-size: 11px; font-weight: bold; color: #475569; border: 1px solid #e2e8f0;">
                                LOG REFERENCE: <span style="color: #10b981;">#{row['id']}</span>
                            </span>
                        </div>

                        <!-- Image Section -->
                        <div style="padding: 15px 25px;">
                            <div style="border: 2px solid #f1f5f9; border-radius: 8px; overflow: hidden; background: #000;">
                                <img src="cid:vehicle_image" style="width: 100%; display: block; max-height: 300px; object-fit: contain;">
                            </div>
                            <p style="font-size: 9px; color: #94a3b8; margin-top: 5px; text-align: center;">CONFIDENTIAL: Captured at Entry/Exit Point</p>
                        </div>

                        <!-- Details Section -->
                        <div style="padding: 0 25px 25px;">
                            <table style="width: 100%; border-collapse: collapse;">
                                <tr>
                                    <td style="padding: 15px 10px; background: #f8fafc; border-radius: 8px 0 0 8px; border-left: 5px solid #0f172a;">
                                        <label style="display: block; font-size: 9px; font-weight: bold; color: #64748b; text-transform: uppercase;">License Plate</label>
                                        <span style="font-size: 20px; font-weight: bold; color: #0f172a; font-family: monospace;">{row['plate_number']}</span>
                                    </td>
                                    <td style="padding: 15px 10px; background: #f8fafc; border-radius: 0 8px 8px 0; border-left: 1px solid #e2e8f0;">
                                        <label style="display: block; font-size: 9px; font-weight: bold; color: #64748b; text-transform: uppercase;">Vehicle Type</label>
                                        <span style="font-size: 16px; font-weight: bold; color: #10b981;">Vehicle: {row['vehicle_type'].upper()}</span>
                                    </td>
                                </tr>
                            </table>

                            <div style="margin-top: 20px; padding: 15px; border: 1px solid #e2e8f0; border-radius: 8px;">
                                <table style="width: 100%; font-size: 13px;">
                                    <tr>
                                        <td style="color: #64748b; padding: 5px 0;">Category</td>
                                        <td style="font-weight: bold; text-align: right;">{row['vehicle']}</td>
                                    </tr>
                                    <tr>
                                        <td style="color: #64748b; padding: 5px 0;">Entry Time</td>
                                        <td style="font-weight: bold; text-align: right; color: #059669;">{row['entry_time'].strftime('%d/%m/%Y, %H:%M:%S')}</td>
                                    </tr>
                                    <tr>
                                        <td style="color: #64748b; padding: 5px 0;">Exit Time</td>
                                        <td style="font-weight: bold; text-align: right; color: #dc2626;">{row['exit_time'].strftime('%d/%m/%Y, %H:%M:%S') if row['exit_time'] else '--'}</td>
                                    </tr>
                                </table>
                            </div>

                            <!-- Duration Banner -->
                            <div style="margin-top: 20px; background: #0f172a; color: #ffffff; padding: 15px; border-radius: 8px; text-align: center;">
                                <label style="display: block; font-size: 9px; font-weight: bold; opacity: 0.6; text-transform: uppercase; margin-bottom: 3px;">Total Stay Duration</label>
                                <span style="font-size: 24px; font-weight: bold; color: #10b981;">{duration}</span>
                            </div>
                        </div>

                        <!-- Footer -->
                        <div style="background: #f8fafc; padding: 15px; text-align: center; border-top: 1px solid #eee;">
                            <p style="margin: 0; font-size: 10px; color: #94a3b8; letter-spacing: 1px;">
                                GENERATED BY SMART GATE AI SYSTEM | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                            </p>
                        </div>
                    </div>
                </body>
                </html>
                """
                
                # Attach Image for CID
                img_path = row['image_path']
                if img_path and os.path.exists(img_path):
                    with open(img_path, 'rb') as f:
                        image_part = MIMEImage(f.read())
                    image_part.add_header('Content-ID', '<vehicle_image>')
                    image_part.add_header('Content-Disposition', 'inline', filename=os.path.basename(img_path))
            else:
                # SEND ALL LOGS (CSV)
                df = pd.read_sql("SELECT * FROM vehicle_activity ORDER BY entry_time DESC", conn)
                # Add duration column to export
                def calc_dur_export(r):
                    if r['exit_time'] and r['entry_time']:
                        diff = r['exit_time'] - r['entry_time']
                        h, rem = divmod(diff.total_seconds(), 3600)
                        m, _ = divmod(rem, 60)
                        return f"{int(h)}h {int(m)}m" if h > 0 else f"{int(m)}m"
                    return "N/A"
                df['duration'] = df.apply(calc_dur_export, axis=1)
                
                csv_buffer = io.BytesIO()
                df.to_csv(csv_buffer, index=False)
                attachment_payload = csv_buffer.getvalue()
                attachment_filename = f"SmartGate_Full_Report_{datetime.now().strftime('%Y%m%d')}.csv"
                body_html = f"Attached is the full activity report. Date: {datetime.now().strftime('%Y-%m-%d')}"
        finally:
            conn.close()

        # Setup Email
        msg = MIMEMultipart('related')
        msg['From'] = f"{SMTP_FROM_NAME} <{sender_email}>"
        msg['To'] = receiver_email
        msg['Subject'] = subject
        
        msg_alternative = MIMEMultipart('alternative')
        msg.attach(msg_alternative)
        msg_alternative.attach(MIMEText(body_html, 'html'))

        if image_part:
            msg.attach(image_part)
        
        if attachment_payload:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment_payload)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f"attachment; filename={attachment_filename}")
            msg.attach(part)

        # Send
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()

        return jsonify({"success": True, "message": f"Report sent to {receiver_email} successfully!"})

    except Exception as e:
        print(f"Mail Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/chat_init', methods=['GET'])
def chat_init():
    greeting = _time_greeting()
    user = session.get('user', 'Friend')
    text = f"{greeting}, **{user}**! 👋 நான் **Smart Gate AI Assistant**.\n\n"
    text += "உங்கள் project-இன் **Mini-AI**-யாக நான் செயல்படுவேன். கேளுங்கள்:\n"
    text += "- **Analytics**: Peak traffic, trends, EDA insights\n"
    text += "- **Logs**: Specific #ID details\n"
    text += "- **Project**: Tech stack, YOLO, EasyOCR\n"
    text += "- **Settings**: Login/Config info\n\n"
    text += "எப்படி உதவி செய்யட்டும்? 😊"
    return jsonify(chatbot_logic.format_answer(text))

@app.route('/ocr', methods=['POST'])
def ocr_image():
    if 'image' not in request.files:
        return jsonify({'html': '<div class="sg-ln">❌ No image file provided.</div>'})
    file = request.files['image']
    if not file.filename:
        return jsonify({'html': '<div class="sg-ln">❌ Invalid file.</div>'})
    
    # Minimal response for now as we might not have all OCR libs installed
    # But let's show we received it
    html = f'<div class="sg-ln">📸 Received image: <strong>{file.filename}</strong></div>'
    html += '<div class="sg-ln">Processing... (OCR functionality coming soon)</div>'
    return jsonify({'html': html})

@app.route('/chat_upload', methods=['POST'])
def chat_upload():
    if 'user' not in session:
        return jsonify({'html': '🔒 Upload requires login. Please login and try again.'}), 401

    if 'file' not in request.files:
        return jsonify({'html': '❌ No file uploaded.'}), 400

    upload = request.files['file']
    filename = secure_filename(upload.filename or "")
    if not filename:
        return jsonify({'html': '❌ Invalid file name.'}), 400

    data = upload.read()
    if not data:
        return jsonify({'html': '❌ Empty file.'}), 400

    result = chatbot_logic.ingest_document(filename, data)
    if not result.get("ok"):
        err = result.get("error", "Upload failed.")
        return jsonify({'html': f'❌ {err}'}), 400

    status = chatbot_logic.kb_status()
    text = (
        f"✅ Learned report: {filename}\n"
        f"- Chunks added: {result.get('chunks', 0)}\n"
        f"- Documents in memory: {status.get('docs', 0)}"
    )
    return jsonify(chatbot_logic.format_answer(text))

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json(silent=True) or {}
        question = str(data.get('message', '')).strip()
        if not question:
            return jsonify({'html': 'கேள்வி type பண்ணுங்க! 😊'})

        q_lower = question.lower()

        if _is_keyword_query(q_lower, _GREETING_KEYWORDS):
            return jsonify(_build_greeting_response(q_lower))

        if _is_keyword_query(q_lower, _HELP_KEYWORDS):
            return jsonify(_build_help_response())

        if _is_keyword_query(q_lower, _LOGIN_KEYWORDS):
            return jsonify(_build_login_info_response())

        if _is_keyword_query(q_lower, _SETTINGS_KEYWORDS):
            return jsonify(_build_settings_response())

        if _is_keyword_query(q_lower, _ANALYTICS_KEYWORDS):
            if 'user' not in session:
                return jsonify({'html': '🔒 Analytics details பார்க்க login தேவை. Please login and try again.'}), 401
            return jsonify(_build_analytics_response(question))

        if _is_keyword_query(q_lower, _REPORT_KEYWORDS):
            if 'user' not in session:
                return jsonify({'html': '🔒 Report functionalities require login. Please login and try again.'}), 401
            return jsonify(_build_report_help_response())

        log_id = _extract_log_id(question)
        if log_id is not None:
            # Sensitive data requires login
            if 'user' not in session:
                return jsonify({'html': '🔒 Log details query requires login. Please login first.'}), 401
            return jsonify(_build_log_details_response(log_id))

        # Check for AI Auto-SQL query
        sql_query = chatbot_logic.generate_sql(question)
        if sql_query:
            if 'user' not in session:
                return jsonify({'html': '🔒 Database queries require login. Please login and try again.'}), 401
            return jsonify(_build_sql_response(sql_query))

        # Public project Q&A
        result = chatbot_logic.get_answer(question)
        return jsonify(result)
    except Exception as e:
        print(f"Chat Error: {e}")
        return jsonify({'html': f'⚠️ Error: {str(e)}'}), 500

if __name__ == '__main__':
    ensure_detection_running()

    app.run(debug=False, port=5000)
