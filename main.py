import cv2
import easyocr
import time
import mysql.connector
import re
import os
import datetime
import sys
import numpy as np
import threading
import queue
import urllib.request
import smtplib
import torch
torch.backends.cudnn.benchmark = True
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from ultralytics import YOLO
try:
    import winsound
except ImportError:
    winsound = None

# =========================================================================
# 1. SETUP & CONFIGURATION
# =========================================================================

# --- DATABASE CONFIG ---
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "smart_gate",
    "autocommit": True
}

# --- RESOURCES ---
HAAR_CASCADE_URL = "https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/haarcascade_russian_plate_number.xml"
HAAR_CASCADE_PATH = "haarcascade_plate.xml"
# --- PLATE VALIDATION (INDIA) ---
INDIAN_STATE_CODES = [
    'AN','AP','AR','AS','BR','CG','CH','DD','DL','DN','GA','GJ','HP','HR','JH','JK','KA','KL','LA','LD',
    'MH','ML','MN','MP','MZ','NL','OD','PB','PY','RJ','SK','TN','TR','TS','UK','UP','WB'
]
# Include legacy state codes still present on older vehicles.
LEGACY_STATE_CODES = ['OR', 'UA']
ALL_STATE_CODES = sorted(set(INDIAN_STATE_CODES + LEGACY_STATE_CODES))
STATE_CODE_REGEX = '(?:' + '|'.join(ALL_STATE_CODES) + ')'
# Use doubled braces inside f-string to keep regex quantifiers literal.
STANDARD_PLATE_REGEX = re.compile(rf'^{STATE_CODE_REGEX}\d{{1,2}}[A-Z]{{1,3}}\d{{4}}$')
BH_PLATE_REGEX = re.compile(r'^\d{2}BH\d{4}[A-Z]{1,2}$')
GENERIC_STANDARD_PLATE_REGEX = re.compile(r'^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{4}$')

def env_int(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default

def env_float(name, default):
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default

def env_bool(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

# --- RUNTIME TUNING ---
CAMERA_WIDTH = env_int("SMARTGATE_CAMERA_WIDTH", 1280)
CAMERA_HEIGHT = env_int("SMARTGATE_CAMERA_HEIGHT", 720)
CAMERA_FPS_TARGET = max(1, env_int("SMARTGATE_CAMERA_FPS", 30))
CAMERA_BUFFER_SIZE = max(1, env_int("SMARTGATE_CAMERA_BUFFER_SIZE", 1))
CAMERA_READ_FAIL_LIMIT = max(3, env_int("SMARTGATE_CAMERA_READ_FAIL_LIMIT", 5))
CAMERA_RECONNECT_DELAY_SEC = max(0.2, env_float("SMARTGATE_CAMERA_RECONNECT_DELAY_SEC", 1.0))
CAMERA_INDEX = env_int("SMARTGATE_CAMERA_INDEX", -1)
CAMERA_BACKEND = os.getenv("SMARTGATE_CAMERA_BACKEND", "").strip().upper()
LOW_LATENCY_MODE = env_bool("SMARTGATE_LOW_LATENCY_MODE", True)
YOLO_CONF = env_float("SMARTGATE_YOLO_CONF", 0.20)
YOLO_IMGSZ = max(320, env_int("SMARTGATE_YOLO_IMGSZ", 320))
YOLO_MAX_DET = max(8, env_int("SMARTGATE_YOLO_MAX_DET", 32 if LOW_LATENCY_MODE else 64))
YOLO_USE_HALF = env_bool("SMARTGATE_YOLO_HALF", True)
VEHICLE_MIN_AREA = env_int("SMARTGATE_VEHICLE_MIN_AREA", 5000)
OCR_QUEUE_MAX = env_int("SMARTGATE_OCR_QUEUE_MAX", 8)
OCR_QUEUE_HIGH_WATERMARK = max(1, min(OCR_QUEUE_MAX, env_int("SMARTGATE_OCR_QUEUE_HIGH_WATERMARK", max(1, OCR_QUEUE_MAX - 1))))
OCR_WORKERS = max(1, env_int("SMARTGATE_OCR_WORKERS", 4 if LOW_LATENCY_MODE else 2))
OCR_MAX_QUEUE_AGE_SEC = max(0.2, env_float("SMARTGATE_OCR_MAX_QUEUE_AGE_SEC", 0.8))
PROCESS_ALL_TRACKS_EVERY_N_FRAMES = max(3, env_int("SMARTGATE_TRACK_REFRESH_FRAMES", 6 if LOW_LATENCY_MODE else 8))
MAX_PLATE_CANDIDATES_PER_TRACK = max(1, env_int("SMARTGATE_MAX_PLATE_CANDIDATES", 2 if LOW_LATENCY_MODE else 3))
TRACK_ENQUEUE_INTERVAL_SEC = max(0.05, env_float("SMARTGATE_TRACK_ENQUEUE_INTERVAL_SEC", 0.65 if LOW_LATENCY_MODE else 0.45))
TRACK_STALE_SEC = max(2.0, env_float("SMARTGATE_TRACK_STALE_SEC", 6.0))
SAVE_COOLDOWN_SECONDS = env_int("SMARTGATE_SAVE_COOLDOWN_SEC", 5)
OCR_TARGET_HEIGHT = max(48, env_int("SMARTGATE_OCR_TARGET_HEIGHT", 64))
OCR_VARIANT_LIMIT = max(1, env_int("SMARTGATE_OCR_VARIANT_LIMIT", 2 if LOW_LATENCY_MODE else 3))
OCR_EARLY_EXIT_CONF = env_float("SMARTGATE_OCR_EARLY_EXIT_CONF", 0.78 if LOW_LATENCY_MODE else 0.88)
ENABLE_CONTOUR_FALLBACK = False  # Disable slow contours
ENABLE_FALLBACK_ROI = False      # Disable slow ROI
FALLBACK_ROI_TOP = env_float("SMARTGATE_FALLBACK_ROI_TOP", 0.45)
FALLBACK_ROI_BOTTOM = env_float("SMARTGATE_FALLBACK_ROI_BOTTOM", 0.95)
FALLBACK_ROI_LEFT = env_float("SMARTGATE_FALLBACK_ROI_LEFT", 0.10)
FALLBACK_ROI_RIGHT = env_float("SMARTGATE_FALLBACK_ROI_RIGHT", 0.90)
VEHICLE_PAD_X = env_float("SMARTGATE_VEHICLE_PAD_X", 0.20)
VEHICLE_PAD_Y = env_float("SMARTGATE_VEHICLE_PAD_Y", 0.15)
SAVE_REJECT_CROPS = env_bool("SMARTGATE_SAVE_REJECT_CROPS", False)
REJECT_CROP_DIR = os.getenv("SMARTGATE_REJECT_CROP_DIR", "ocr_rejects")
REJECT_CROP_MIN_INTERVAL_SEC = env_float("SMARTGATE_REJECT_CROP_MIN_INTERVAL_SEC", 1.0)
ALLOW_GENERIC_STATE_CODES = env_bool("SMARTGATE_ALLOW_GENERIC_STATE_CODES", False)
OCR_REQUIRE_STRICT_PATTERN = env_bool("SMARTGATE_OCR_REQUIRE_STRICT_PATTERN", True)
MIN_UNIQUE_FRAMES_FOR_SAVE = max(1, env_int("SMARTGATE_MIN_UNIQUE_FRAMES_FOR_SAVE", 1))
OCR_FAST_SAVE_CONF = env_float("SMARTGATE_OCR_FAST_SAVE_CONF", 0.90)
OCR_FAST_SAVE_STRICT_ONLY = env_bool("SMARTGATE_OCR_FAST_SAVE_STRICT_ONLY", True)
GLOBAL_PLATE_VOTE_THRESHOLD = max(1, env_int("SMARTGATE_GLOBAL_PLATE_VOTE_THRESHOLD", 1))
GLOBAL_PLATE_VOTE_WINDOW_SEC = max(2.0, env_float("SMARTGATE_GLOBAL_PLATE_VOTE_WINDOW_SEC", 8.0))
SMTP_HOST = os.getenv("SMARTGATE_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = env_int("SMARTGATE_SMTP_PORT", 587)
SMTP_USER = os.getenv("SMARTGATE_SMTP_USER", "preetiking143@gmail.com")
SMTP_PASS = os.getenv("SMARTGATE_SMTP_PASS", "qbmg gucd qrlx rzsn")
SMTP_FROM_NAME = os.getenv("SMARTGATE_SMTP_FROM_NAME", "Smart Gate AI")
ALERT_ONLY_UNKNOWN_CATEGORY = env_bool("SMARTGATE_ALERT_ONLY_UNKNOWN_CATEGORY", True)
ALERT_UNKNOWN_BY_REGISTRATION = env_bool("SMARTGATE_ALERT_UNKNOWN_BY_REGISTRATION", True)
VEHICLE_ALERT_TO = os.getenv(
    "SMARTGATE_VEHICLE_ALERT_TO",
    os.getenv(
        "SMARTGATE_UNKNOWN_ALERT_TO",
        os.getenv("SMARTGATE_DEFAULT_REPORT_TO", "dharshan.s.2026@rkmshome.org"),
    ),
)
MAIL_QUEUE_MAX = max(10, env_int("SMARTGATE_MAIL_QUEUE_MAX", 256))
MAIL_RECONNECT_AFTER = max(1, env_int("SMARTGATE_MAIL_RECONNECT_AFTER", 25))
vehicle_alert_queue = queue.Queue(maxsize=MAIL_QUEUE_MAX)
_MAIL_WORKER_STARTED = False
_MAIL_WORKER_LOCK = threading.Lock()
_MAIL_CONFIG_WARNED = False

# =========================================================================
# 2. UTILITY FUNCTIONS
# =========================================================================

def ensure_resources():
    """Downloads necessary Haar Cascade if missing."""
    if not os.path.exists(HAAR_CASCADE_PATH):
        print(f"ðŸ“¥ Downloading Haar Cascade from {HAAR_CASCADE_URL}...")
        try:
            urllib.request.urlretrieve(HAAR_CASCADE_URL, HAAR_CASCADE_PATH)
            print("âœ… Download complete.")
        except Exception as e:
            print(f"â Œ Failed to download Haar Cascade: {e}")
            sys.exit(1)

# --- DATABASE POOLING ---
_DB_POOL = None
_DB_POOL_LOCK = threading.Lock()

def get_db_connection():
    global _DB_POOL
    try:
        if _DB_POOL is None:
            with _DB_POOL_LOCK:
                if _DB_POOL is None:
                    from mysql.connector import pooling
                    # Create a pool with a few connections for threads
                    _DB_POOL = pooling.MySQLConnectionPool(
                        pool_name="smart_gate_pool",
                        pool_size=20,
                        **DB_CONFIG
                    )
        return _DB_POOL.get_connection()
    except Exception as err:
        print(f"â Œ Database Connection Error: {err}")
        return None

# --- GLOBAL CAMERA & BUFFERING ---
_CAMERA_STREAM = None
_CAMERA_LOCK = threading.Lock()
_LATEST_RAW_FRAME = None
_LATEST_PROCESSED_FRAME = None
_STOP_SIGNAL = False

_HOME_COLS_CACHE = None
_ACTIVITY_COLS_CACHE = None

def _fetch_home_vehicle_columns(conn):
    cursor = conn.cursor(buffered=True)
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

    try:
        cols = _fetch_home_vehicle_columns(conn)
    except Exception:
        cols = set()
    plate_col = "plate_number" if "plate_number" in cols else ("Licence_plate" if "Licence_plate" in cols else None)
    category_col = "category" if "category" in cols else None

    _HOME_COLS_CACHE = {
        "plate_col": plate_col,
        "category_col": category_col,
        "all_cols": cols,
    }
    return _HOME_COLS_CACHE

def ensure_home_vehicle_schema(conn):
    global _HOME_COLS_CACHE
    try:
        cols = _fetch_home_vehicle_columns(conn)
    except Exception:
        return

    cursor = conn.cursor(buffered=True)
    if "plate_number" not in cols:
        cursor.execute("ALTER TABLE home_vehicles ADD COLUMN plate_number VARCHAR(20)")
        if "Licence_plate" in cols:
            cursor.execute("UPDATE home_vehicles SET plate_number = Licence_plate WHERE plate_number IS NULL")
    if "category" not in cols:
        cursor.execute("ALTER TABLE home_vehicles ADD COLUMN category VARCHAR(50) DEFAULT 'Home'")

    cursor.close()
    _HOME_COLS_CACHE = None


def _fetch_vehicle_activity_columns(conn):
    cursor = conn.cursor(buffered=True)
    cursor.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
        (DB_CONFIG["database"], "vehicle_activity"),
    )
    cols = {row[0] for row in cursor.fetchall()}
    cursor.close()
    return cols


def ensure_vehicle_activity_schema(conn):
    global _ACTIVITY_COLS_CACHE
    try:
        cols = _fetch_vehicle_activity_columns(conn)
    except Exception:
        return

    cursor = conn.cursor(buffered=True)
    if "vehicle_color" not in cols:
        cursor.execute("ALTER TABLE vehicle_activity ADD COLUMN vehicle_color VARCHAR(30) DEFAULT 'UNKNOWN'")
    if "updated_at" not in cols:
        cursor.execute("ALTER TABLE vehicle_activity ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
    cursor.close()
    _ACTIVITY_COLS_CACHE = None

def preprocess_plate(img):
    """
    Optimal Preprocessing for OCR.
    """
    if img is None or img.size == 0: return None

    h, w = img.shape[:2]
    if h == 0 or w == 0: return None
    target_h = OCR_TARGET_HEIGHT
    scale = target_h / h
    img = cv2.resize(img, (int(w * scale), target_h), interpolation=cv2.INTER_LINEAR)
    
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Improve contrast and let EasyOCR handle its internal thresholds instead of forcing binary
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
    contrast = clahe.apply(gray)
    
    # Slight blur to remove immediate noise but retain edges
    denoised = cv2.GaussianBlur(contrast, (3, 3), 0)
    
    return denoised

def build_ocr_variants_lazy(img):
    """Generate multiple OCR-ready variants lazily; optimized for speed."""
    base = preprocess_plate(img)
    if base is None: return
    
    # 1. Base Preprocessed
    yield base
    
    # 2. Sharpen (Fast & Very effective for OCR)
    sharp_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    yield cv2.filter2D(base, -1, sharp_kernel)

    # 3. Adaptive threshold (Good for reflective/night plates)
    yield cv2.adaptiveThreshold(base, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)

    if not LOW_LATENCY_MODE:
        # Extra variants for difficult frames only in high-accuracy mode
        otsu = cv2.threshold(base, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        yield otsu
        yield cv2.bitwise_not(otsu)

def normalize_plate(text):
    if not text:
        return ''
    return re.sub(r'[^A-Z0-9]', '', text.upper())


def normalized_plate_sql_expr(column_name):
    return f"UPPER(REPLACE(REPLACE(REPLACE(REPLACE(IFNULL({column_name}, ''), ' ', ''), '-', ''), '.', ''), '_', ''))"


def _ocr_box_min_x(entry):
    try:
        return min(float(p[0]) for p in entry[0])
    except Exception:
        return 0.0


def _ocr_box_center_y(entry):
    try:
        ys = [float(p[1]) for p in entry[0]]
        return (min(ys) + max(ys)) / 2.0
    except Exception:
        return 0.0


def _ocr_box_height(entry):
    try:
        ys = [float(p[1]) for p in entry[0]]
        return max(1.0, max(ys) - min(ys))
    except Exception:
        return 1.0


def assemble_ocr_lines(filtered_ocr):
    """
    Group OCR fragments into visual lines, then read each line left-to-right.
    Helps with 2-line number plates.
    """
    if not filtered_ocr:
        return []

    entries = []
    for res in filtered_ocr:
        entries.append({
            "res": res,
            "x": _ocr_box_min_x(res),
            "cy": _ocr_box_center_y(res),
            "h": _ocr_box_height(res),
        })

    entries.sort(key=lambda e: e["cy"])
    median_h = float(np.median([e["h"] for e in entries])) if entries else 10.0
    line_tol = max(8.0, median_h * 0.6)

    lines = []
    for e in entries:
        placed = False
        for line in lines:
            if abs(e["cy"] - line["cy"]) <= line_tol:
                line["items"].append(e)
                line["cy"] = (line["cy"] * line["n"] + e["cy"]) / (line["n"] + 1)
                line["n"] += 1
                placed = True
                break
        if not placed:
            lines.append({"cy": e["cy"], "n": 1, "items": [e]})

    lines.sort(key=lambda line: line["cy"])
    line_texts = []
    for line in lines:
        line["items"].sort(key=lambda e: e["x"])
        text = "".join(str(item["res"][1]) for item in line["items"])
        clean = normalize_plate(text)
        if clean:
            line_texts.append(clean)
    return line_texts


def build_ocr_text_candidates(filtered_ocr):
    """Build multiple text candidates from OCR fragments before plate validation."""
    candidates = []

    lines = assemble_ocr_lines(filtered_ocr)
    if lines:
        candidates.append("".join(lines))
        candidates.extend(lines)

    flat = "".join(str(res[1]) for res in sorted(filtered_ocr, key=lambda r: (_ocr_box_center_y(r), _ocr_box_min_x(r))))
    candidates.append(flat)

    for res in filtered_ocr:
        candidates.append(str(res[1]))

    unique = []
    seen = set()
    for item in candidates:
        clean = normalize_plate(item)
        if not clean or len(clean) < 6 or len(clean) > 14:
            continue
        if clean in seen:
            continue
        seen.add(clean)
        unique.append(clean)
    return unique


def map_chars(res, positions, mapping):
    for i in positions:
        if i < len(res) and res[i] in mapping:
            res[i] = mapping[res[i]]
    return res


def generate_standard_candidates(clean):
    candidates = []
    to_alpha = {'0':'O', '1':'I', '2':'Z', '4':'A', '5':'S', '8':'B', '6':'G', '7':'T'}
    to_num = {'O':'0', 'I':'1', 'Z':'2', 'S':'5', 'B':'8', 'G':'6', 'T':'7', 'A':'4'}

    for dlen in (1, 2):
        for slen in (1, 2, 3):
            if len(clean) != 2 + dlen + slen + 4:
                continue
            res = list(clean)
            # State code (2 letters)
            res = map_chars(res, [0, 1], to_alpha)
            # District digits
            res = map_chars(res, list(range(2, 2 + dlen)), to_num)
            # Series letters
            res = map_chars(res, list(range(2 + dlen, 2 + dlen + slen)), to_alpha)
            # Last 4 digits
            res = map_chars(res, list(range(len(res) - 4, len(res))), to_num)
            candidates.append(''.join(res))
    return candidates


def generate_bh_candidates(clean):
    candidates = []
    if len(clean) != 10:
        return candidates
    to_alpha = {'0':'O', '1':'I', '2':'Z', '4':'A', '5':'S', '8':'B', '6':'G', '7':'T'}
    to_num = {'O':'0', 'I':'1', 'Z':'2', 'S':'5', 'B':'8', 'G':'6', 'T':'7', 'A':'4'}
    res = list(clean)
    res = map_chars(res, [0, 1], to_num)
    res = map_chars(res, [2], {'8': 'B', '0': 'O'})
    res = map_chars(res, [3], {'H': 'H', '0': 'O'})
    res = map_chars(res, [4, 5, 6, 7], to_num)
    res = map_chars(res, [8, 9], to_alpha)
    candidates.append(''.join(res))
    return candidates


def validate_indian_plate(text):
    if not text:
        return None
    clean = normalize_plate(text)
    if STANDARD_PLATE_REGEX.match(clean) or BH_PLATE_REGEX.match(clean):
        return clean
    # Fallback to generic Indian private pattern if state-code list misses legacy/rare variants.
    if ALLOW_GENERIC_STATE_CODES and GENERIC_STANDARD_PLATE_REGEX.match(clean):
        return clean
    return None

def validate_indian_plate_strict(text):
    if not text:
        return None
    clean = normalize_plate(text)
    if STANDARD_PLATE_REGEX.match(clean) or BH_PLATE_REGEX.match(clean):
        return clean
    return None


def extract_valid_plate(text):
    clean = normalize_plate(text)
    if validate_indian_plate(clean):
        return clean

    # Try corrected candidates
    for cand in generate_bh_candidates(clean) + generate_standard_candidates(clean):
        strict = validate_indian_plate_strict(cand)
        if strict:
            return strict

    # OCR sometimes returns extra prefix/suffix characters; scan plausible substrings.
    # Typical Indian plates vary from 7 to 11 chars; include 11-char recovery.
    for size in (11, 10, 9, 8, 7):
        if len(clean) < size:
            continue
        for start in range(0, len(clean) - size + 1):
            chunk = clean[start:start + size]
            if validate_indian_plate(chunk):
                return chunk
            for cand in generate_bh_candidates(chunk) + generate_standard_candidates(chunk):
                strict = validate_indian_plate_strict(cand)
                if strict:
                    return strict
    return None


def smart_format_corrector(text):
    # Backward compatibility: return best candidate or raw cleaned text
    valid = extract_valid_plate(text)
    return valid or normalize_plate(text)


def normalize_vehicle_type(label):
    raw = (label or "").strip().upper()
    mapping = {
        "BIKE": "MOTORCYCLE",
        "MOTORBIKE": "MOTORCYCLE",
        "MOTORCYCLE": "MOTORCYCLE",
        "BICYCLE": "BICYCLE",
        "CAR": "CAR",
        "BUS": "BUS",
        "TRUCK": "TRUCK",
        "TRAIN": "TRAIN",
    }
    return mapping.get(raw, raw or "UNKNOWN")


def _normalize_alert_value(value):
    return str(value or "").strip().lower()


def _is_unknown_vehicle_log(log_row):
    """True if log should be treated as unknown/unregistered for email alerting."""
    category_raw = str(log_row.get("vehicle", "") or "").strip()
    category = _normalize_alert_value(category_raw)
    registration = _normalize_alert_value(log_row.get("registration", ""))

    category_unknown = (
        category == ""
        or "unknown" in category
        or category in {"visitor", "unregistered", "na", "n/a"}
    )
    registration_unknown = (
        registration == ""
        or "unknown" in registration
        or registration in {"visitor", "unregistered", "na", "n/a"}
    )

    if category_unknown:
        return True
    if ALERT_UNKNOWN_BY_REGISTRATION and registration_unknown:
        return True
    return False


def _build_vehicle_alert_message(log_row):
    from email.mime.image import MIMEImage

    entry_dt = log_row.get("entry_time")
    exit_dt = log_row.get("exit_time")
    entry_time = entry_dt.strftime("%d/%m/%Y, %H:%M:%S") if entry_dt else "N/A"
    exit_time = exit_dt.strftime("%d/%m/%Y, %H:%M:%S") if exit_dt else "--"
    duration = log_row.get("duration", "N/A")
    record_id = log_row.get("id", "N/A")
    plate = log_row.get("plate_number", "N/A")
    v_type = log_row.get("vehicle_type", "UNKNOWN")
    category = log_row.get("vehicle", "Unknown")
    registration = log_row.get("registration", "Unknown")
    status = log_row.get("status", "Unknown")
    alert_type = "UNKNOWN VEHICLE ALERT" if _is_unknown_vehicle_log(log_row) else "VEHICLE LOG ALERT"

    subject = f"[ALERT] {alert_type}: {plate} ({status})"
    body_text = (
        "SMART GATE ALERT\n"
        f"Alert Type: {alert_type}\n"
        f"Log Reference: #{record_id}\n"
        f"Plate Number: {plate}\n"
        f"Vehicle Type: {str(v_type).upper()}\n"
        f"Category: {category}\n"
        f"Registration: {registration}\n"
        f"Status: {status}\n"
        f"Entry Time: {entry_time}\n"
        f"Exit Time: {exit_time}\n"
        f"Duration: {duration}\n"
    )
    
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
                    LOG REFERENCE: <span style="color: #10b981;">#{record_id}</span>
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
                            <span style="font-size: 20px; font-weight: bold; color: #0f172a; font-family: monospace;">{plate}</span>
                        </td>
                        <td style="padding: 15px 10px; background: #f8fafc; border-radius: 0 8px 8px 0; border-left: 1px solid #e2e8f0;">
                            <label style="display: block; font-size: 9px; font-weight: bold; color: #64748b; text-transform: uppercase;">Vehicle Type</label>
                            <span style="font-size: 16px; font-weight: bold; color: #10b981;">Vehicle: {v_type.upper()}</span>
                        </td>
                    </tr>
                </table>

                <div style="margin-top: 20px; padding: 15px; border: 1px solid #e2e8f0; border-radius: 8px;">
                    <table style="width: 100%; font-size: 13px;">
                        <tr>
                            <td style="color: #64748b; padding: 5px 0;">Category</td>
                            <td style="font-weight: bold; text-align: right;">{category}</td>
                        </tr>
                        <tr>
                            <td style="color: #64748b; padding: 5px 0;">Registration</td>
                            <td style="font-weight: bold; text-align: right;">{registration}</td>
                        </tr>
                        <tr>
                            <td style="color: #64748b; padding: 5px 0;">Alert Type</td>
                            <td style="font-weight: bold; text-align: right; color: #dc2626;">{alert_type}</td>
                        </tr>
                        <tr>
                            <td style="color: #64748b; padding: 5px 0;">Status</td>
                            <td style="font-weight: bold; text-align: right;">{status}</td>
                        </tr>
                        <tr>
                            <td style="color: #64748b; padding: 5px 0;">Entry Time</td>
                            <td style="font-weight: bold; text-align: right; color: #059669;">{entry_time}</td>
                        </tr>
                        <tr>
                            <td style="color: #64748b; padding: 5px 0;">Exit Time</td>
                            <td style="font-weight: bold; text-align: right; color: #dc2626;">{exit_time}</td>
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
                    GENERATED BY SMART GATE AI SYSTEM | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    msg = MIMEMultipart('related')
    msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
    msg["To"] = VEHICLE_ALERT_TO
    msg["Subject"] = subject

    msg_alternative = MIMEMultipart('alternative')
    msg.attach(msg_alternative)
    msg_alternative.attach(MIMEText(body_text, 'plain'))
    msg_alternative.attach(MIMEText(body_html, 'html'))

    image_path = log_row.get("image_path")
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            image_part = MIMEImage(img_file.read())
            image_part.add_header('Content-ID', '<vehicle_image>')
            image_part.add_header('Content-Disposition', 'inline', filename=os.path.basename(image_path))
            msg.attach(image_part)
            
    return msg


def _create_smtp_client():
    server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
    server.starttls()
    server.login(SMTP_USER, SMTP_PASS)
    return server


def _send_vehicle_alert_now(log_row, smtp_client):
    msg = _build_vehicle_alert_message(log_row)
    smtp_client.send_message(msg)


def _vehicle_alert_worker():
    smtp_client = None
    sent_on_connection = 0

    while True:
        log_row = vehicle_alert_queue.get()
        try:
            if smtp_client is None or sent_on_connection >= MAIL_RECONNECT_AFTER:
                if smtp_client is not None:
                    try:
                        smtp_client.quit()
                    except Exception:
                        pass
                smtp_client = _create_smtp_client()
                sent_on_connection = 0

            _send_vehicle_alert_now(log_row, smtp_client)
            sent_on_connection += 1
            print(f"[MAIL] Vehicle alert sent to {VEHICLE_ALERT_TO} for {log_row['plate_number']}")
        except Exception as first_error:
            if smtp_client is not None:
                try:
                    smtp_client.quit()
                except Exception:
                    pass
                smtp_client = None
                sent_on_connection = 0

            try:
                smtp_client = _create_smtp_client()
                _send_vehicle_alert_now(log_row, smtp_client)
                sent_on_connection = 1
                print(f"[MAIL] Vehicle alert sent to {VEHICLE_ALERT_TO} for {log_row['plate_number']} (retry)")
            except Exception as retry_error:
                print(
                    f"[MAIL] Vehicle alert failed for {log_row.get('plate_number', 'N/A')}: "
                    f"{first_error}; retry={retry_error}"
                )
        finally:
            vehicle_alert_queue.task_done()


def ensure_vehicle_alert_worker():
    global _MAIL_WORKER_STARTED
    if _MAIL_WORKER_STARTED:
        return
    with _MAIL_WORKER_LOCK:
        if _MAIL_WORKER_STARTED:
            return
        threading.Thread(target=_vehicle_alert_worker, daemon=True).start()
        _MAIL_WORKER_STARTED = True


def send_vehicle_alert(log_row):
    global _MAIL_CONFIG_WARNED
    if ALERT_ONLY_UNKNOWN_CATEGORY and not _is_unknown_vehicle_log(log_row):
        return
    if not VEHICLE_ALERT_TO:
        return
    if not SMTP_USER or not SMTP_PASS:
        if not _MAIL_CONFIG_WARNED:
            print("[MAIL] Vehicle alerts disabled: set SMARTGATE_SMTP_USER and SMARTGATE_SMTP_PASS.")
            _MAIL_CONFIG_WARNED = True
        return

    ensure_vehicle_alert_worker()
    try:
        vehicle_alert_queue.put_nowait(log_row)
    except queue.Full:
        print(f"[MAIL] Vehicle alert queue full ({MAIL_QUEUE_MAX}). Dropping alert for {log_row.get('plate_number', 'N/A')}.")


def save_to_db(plate_clean, plate_display, v_type, full_image):
    conn = get_db_connection()
    if not conn: return
    cursor = conn.cursor(buffered=True)

    if winsound:
        threading.Thread(target=lambda: winsound.Beep(1000, 500), daemon=True).start()

    now = datetime.datetime.now()
    t_str = now.strftime("%H:%M:%S")
    img_name = f"captured_images/{plate_clean}_{now.strftime('%H%M%S')}.jpg"

    # Save Image
    cv2.imwrite(img_name, full_image)

    try:
        # 1. Determine Category (Home vs Visitor)
        category = "Visitor"
        is_registered = False
        ensure_home_vehicle_schema(conn)
        cols = get_home_vehicle_columns(conn)
        plate_col = cols["plate_col"]
        category_col = cols["category_col"]
        plate_lookup = normalize_plate(plate_clean)
        if plate_col and category_col:
            plate_expr = normalized_plate_sql_expr(plate_col)
            cursor.execute(
                f"SELECT {category_col} FROM home_vehicles "
                f"WHERE {plate_col} = %s OR {plate_expr} = %s LIMIT 1",
                (plate_lookup, plate_lookup),
            )
            row = cursor.fetchone()
            if row:
                is_registered = True
                if row[0]:
                    raw_category = str(row[0]).strip()
                    if raw_category and raw_category.lower() not in {"unknown", "unknown vehicle"}:
                        category = raw_category
                    else:
                        category = "Home"
                else:
                    category = "Home"
        elif plate_col:
            plate_expr = normalized_plate_sql_expr(plate_col)
            cursor.execute(
                f"SELECT 1 FROM home_vehicles WHERE {plate_col} = %s OR {plate_expr} = %s LIMIT 1",
                (plate_lookup, plate_lookup),
            )
            is_registered = cursor.fetchone() is not None
            if is_registered:
                category = "Home"

        normalized_v_type = normalize_vehicle_type(v_type)

        # 2. Check if vehicle is inside
        cursor.execute("SELECT id, entry_time FROM vehicle_activity WHERE plate_number = %s AND status = 'Inside'", (plate_clean,))
        result = cursor.fetchone()

        if result:
            # EXIT
            record_id, entry_time = result
            diff = now - entry_time
            duration_minutes = int(diff.total_seconds() / 60)
            
            # Simple heuristic: ignore "Exit" if detected within 2 mins of Entry (prevent duplicate toggle)
            if duration_minutes < 1:
                return 

            cursor.execute("UPDATE vehicle_activity SET exit_time=%s, status='Completed', image_path=%s WHERE id=%s", 
                           (now, img_name, record_id))
            conn.commit()
            print(f" {'ðŸ”´ EXIT':<10} | {v_type:<10} | {category:<10} | {plate_display:<15}")

            duration = "N/A"
            if entry_time:
                diff = now - entry_time
                h, rem = divmod(diff.total_seconds(), 3600)
                m, _ = divmod(rem, 60)
                duration = f"{int(h)}h {int(m)}m" if h > 0 else f"{int(m)}m"

            alert_row = {
                "id": record_id,
                "plate_number": plate_display,
                "vehicle_type": normalized_v_type,
                "entry_time": entry_time,
                "exit_time": now,
                "status": "Completed",
                "image_path": img_name,
                "vehicle": category,
                "registration": "Registered" if is_registered else "Unknown",
                "duration": duration,
            }
            send_vehicle_alert(alert_row)

        else:
            # ENTRY
            cursor.execute("INSERT INTO vehicle_activity (plate_number, vehicle_type, entry_time, status, image_path, vehicle) VALUES (%s, %s, %s, %s, %s, %s)", 
                           (plate_clean, normalized_v_type, now, 'Inside', img_name, category))
            record_id = cursor.lastrowid
            conn.commit()
            print(f" {'ðŸŸ¢ ENTRY':<10} | {v_type:<10} | {category:<10} | {plate_display:<15}")

            alert_row = {
                "id": record_id,
                "plate_number": plate_display,
                "vehicle_type": normalized_v_type,
                "entry_time": now,
                "exit_time": None,
                "status": "Inside",
                "image_path": img_name,
                "vehicle": category,
                "registration": "Registered" if is_registered else "Unknown",
                "duration": "N/A",
            }
            send_vehicle_alert(alert_row)

    except Exception as e:
        print(f"DB Error: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

# =========================================================================
# 3. PLATE DETECTION LOGIC (The Core)
# =========================================================================

class PlateDetector:
    def __init__(self):
        self.plate_cascade = cv2.CascadeClassifier(HAAR_CASCADE_PATH)
        self.rectKernel = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
        
    def detect(self, vehicle_img):
        """
        Returns list of (plate_image)
        Uses Haar Cascade for robust plate localization, falling back to contour detection if needed.
        """
        if vehicle_img is None or vehicle_img.size == 0: return []
        
        plates_found = []
        gray = cv2.cvtColor(vehicle_img, cv2.COLOR_BGR2GRAY)
        
        # Downscale for faster Haar detection if crop is too large
        max_dim = 480
        h, w = gray.shape[:2]
        if h > max_dim or w > max_dim:
            scale = max_dim / max(h, w)
            gray_small = cv2.resize(gray, (int(w * scale), int(h * scale)))
            plates_haar = self.plate_cascade.detectMultiScale(gray_small, scaleFactor=1.1, minNeighbors=4, minSize=(20, 10))
            # Upscale results
            rev_scale = 1.0 / scale
            plates_haar = [(int(x*rev_scale), int(y*rev_scale), int(w_box*rev_scale), int(h_box*rev_scale)) for (x,y,w_box,h_box) in plates_haar]
        else:
            plates_haar = self.plate_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(20, 10))
        
        for (x, y, w, h) in plates_haar:
            # Validate Aspect Ratio (Plates are rectangular or square-ish)
            aspect_ratio = float(w) / h
            if 0.8 <= aspect_ratio <= 6.0:
                # Add margin
                pad_w, pad_h = int(w * 0.1), int(h * 0.15)
                x1, y1 = max(0, x - pad_w), max(0, y - pad_h)
                x2, y2 = min(vehicle_img.shape[1], x + w + pad_w), min(vehicle_img.shape[0], y + h + pad_h)
                
                plate_crop = vehicle_img[y1:y2, x1:x2]
                if plate_crop.size > 0:
                    plates_found.append(plate_crop)

        if plates_found: 
            # Sort by size to get the most prominent plate first
            plates_found.sort(key=lambda x: x.shape[0] * x.shape[1], reverse=True)
            return plates_found

        # --- METHOD 2: Advanced Contour Search (Fallback) ---
        if ENABLE_CONTOUR_FALLBACK:
            rectKernel = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
            blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, rectKernel)
            gradX = cv2.Sobel(blackhat, ddepth=cv2.CV_32F, dx=1, dy=0, ksize=-1)
            gradX = np.absolute(gradX)
            (minVal, maxVal) = (np.min(gradX), np.max(gradX))
            dynamic_range = maxVal - minVal
            if dynamic_range > 1e-6:
                gradX = (255 * ((gradX - minVal) / dynamic_range)).astype("uint8")
                gradX = cv2.GaussianBlur(gradX, (5, 5), 0)
                gradX = cv2.morphologyEx(gradX, cv2.MORPH_CLOSE, rectKernel)
                thresh = cv2.threshold(gradX, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
                cnts = cv2.findContours(thresh.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)[0]
                cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:10]

                for c in cnts:
                    x, y, w, h = cv2.boundingRect(c)
                    ar = w / float(h)
                    if 1.0 <= ar <= 6.0 and w > 20 and h > 10:
                        plate_crop = vehicle_img[y:y+h, x:x+w]
                        plates_found.append(plate_crop)

        # Final fallback: ROI mapping
        if not plates_found and ENABLE_FALLBACK_ROI:
            h, w = vehicle_img.shape[:2]
            x1 = int(max(0.0, min(1.0, FALLBACK_ROI_LEFT)) * w)
            x2 = int(max(0.0, min(1.0, FALLBACK_ROI_RIGHT)) * w)
            y1 = int(max(0.0, min(1.0, FALLBACK_ROI_TOP)) * h)
            y2 = int(max(0.0, min(1.0, FALLBACK_ROI_BOTTOM)) * h)
            roi = vehicle_img[y1:y2, x1:x2]
            if roi is not None and roi.size > 0:
                plates_found.append(roi)

        return plates_found

def enhance_plate_clarity(plate_img):
    if plate_img is None or plate_img.size == 0: return None
    kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    return cv2.filter2D(plate_img, -1, kernel)

def to_int_safe(value, fallback=-1):
    try:
        if value is None: return fallback
        if hasattr(value, "item"): return int(value.item())
        return int(value)
    except Exception: return fallback

def plate_crop_quality_score(crop):
    if crop is None or crop.size == 0: return -1.0
    h, w = crop.shape[:2]
    if h <= 0 or w <= 0: return -1.0
    ar = w / float(h)
    area = float(w * h)
    ratio_score = max(0.0, 1.0 - min(abs(ar - 3.2) / 3.2, 1.0))
    size_score = min(area / 8000.0, 1.0)
    return (0.7 * ratio_score) + (0.3 * size_score)

def _camera_backend_candidates():
    raw = []
    if hasattr(cv2, "CAP_DSHOW"): raw.append(("DSHOW", cv2.CAP_DSHOW))
    if hasattr(cv2, "CAP_MSMF"): raw.append(("MSMF", cv2.CAP_MSMF))
    if hasattr(cv2, "CAP_ANY"): raw.append(("ANY", cv2.CAP_ANY))
    raw.append(("DEFAULT", None))
    seen = set()
    result = []
    for name, code in raw:
        key = code if code is not None else -1
        if key in seen: continue
        seen.add(key)
        result.append((name, code))
    return result

def _resolve_backend_code(name):
    if not name: return None
    name = name.strip().upper()
    if name == "DSHOW" and hasattr(cv2, "CAP_DSHOW"): return cv2.CAP_DSHOW
    if name == "MSMF" and hasattr(cv2, "CAP_MSMF"): return cv2.CAP_MSMF
    return None

def configure_capture(cap):
    if cap is None: return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS_TARGET)
    if hasattr(cv2, "CAP_PROP_FOURCC"):
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
        cap.set(cv2.CAP_PROP_BUFFERSIZE, CAMERA_BUFFER_SIZE)

def expand_bbox(x1, y1, x2, y2, frame_shape, pad_x_ratio=0.12, pad_y_ratio=0.10):
    h, w = frame_shape[:2]
    bw, bh = max(1, x2-x1), max(1, y2-y1)
    px, py = int(bw * pad_x_ratio), int(bh * pad_y_ratio)
    nx1, ny1 = max(0, x1 - px), max(0, y1 - py)
    nx2, ny2 = min(w, x2 + px), min(h, y2 + py)
    return nx1, ny1, nx2, ny2

def open_camera_with_fallback(indexes=(0, 1, 2), test_read=True):
    if CAMERA_INDEX >= 0: indexes = (CAMERA_INDEX,)
    backends = _camera_backend_candidates()
    for idx in indexes:
        for b_name, b_code in backends:
            try:
                cap = cv2.VideoCapture(idx) if b_code is None else cv2.VideoCapture(idx, b_code)
                if not cap or not cap.isOpened():
                    if cap: cap.release()
                    continue
                configure_capture(cap)
                if test_read:
                    ok, _ = cap.read()
                    if not ok:
                        cap.release()
                        continue
                return cap, idx, b_name
            except Exception: pass
    return None, None, None

def get_class_name(names, class_id):
    try:
        if isinstance(names, dict): return names.get(class_id, str(class_id))
        return names[class_id]
    except Exception: return str(class_id)

class FastCameraReader:
    def __init__(self, indexes=(0, 1, 2)):
        self.cap = None
        self.running = False
        self.lock = threading.Lock()
        self.frame = None
        self.ret = False
        
        cap, idx, b_name = open_camera_with_fallback(indexes=indexes, test_read=True)
        if cap:
            self.cap = cap
            self.ret, self.frame = self.cap.read()
            self.running = True
            self.thread = threading.Thread(target=self._update, daemon=True)
            self.thread.start()
            print(f"[FAST-CAM] Connected to Cam {idx} via {b_name}")

    def _update(self):
        while self.running:
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                with self.lock:
                    self.ret = ret
                    if ret: self.frame = frame
            else: time.sleep(0.1)

    def read(self):
        with self.lock:
            if self.frame is None: return False, None
            return self.ret, self.frame.copy()

    def stop(self):
        self.running = False
        if self.cap: self.cap.release()

# =========================================================================
# 4. THREADS & GLOBALS
# =========================================================================

ocr_queue = queue.Queue(maxsize=OCR_QUEUE_MAX)
cooldowns = {}
vehicle_best_plates = {}
track_last_enqueue_ts = {}
track_last_seen_ts = {}
track_vtypes = {}
track_finished = set()
plate_votes = {} 
plate_votes_global = {} 
VOTE_THRESHOLD = max(1, env_int("SMARTGATE_VOTE_THRESHOLD", 1))
TRACK_FINISHED_CONF = env_float("SMARTGATE_TRACK_FINISHED_CONF", 0.92)
OCR_MIN_TEXT_CONF = env_float("SMARTGATE_OCR_MIN_TEXT_CONF", 0.25)
OCR_MIN_AVG_CONF = env_float("SMARTGATE_OCR_MIN_AVG_CONF", 0.40)
OCR_MIN_TOTAL_SCORE = env_float("SMARTGATE_OCR_MIN_TOTAL_SCORE", 0.90)
OCR_STRONG_CONF = env_float("SMARTGATE_OCR_STRONG_CONF", 0.82)
video_frame = None
video_lock = threading.Lock()
state_lock = threading.Lock()
last_reject_log_ts = 0.0
last_reject_crop_ts = 0.0
_LATEST_PLATE_INFO = None

_OCR_READER = None
_OCR_READER_LOCK = threading.Lock()

def get_ocr_reader():
    global _OCR_READER
    if _OCR_READER is None:
        with _OCR_READER_LOCK:
            if _OCR_READER is None:
                import torch
                use_gpu = torch.cuda.is_available()
                if use_gpu:
                    torch.backends.cudnn.benchmark = True
                _OCR_READER = easyocr.Reader(['en'], gpu=use_gpu) # Removed quantize to fix stability
    return _OCR_READER

def ocr_worker(plate_detector=None):
    print("ðŸš€ OCR Engine Worker Started...")
    import torch
    reader = get_ocr_reader()

    with torch.no_grad(): # Disable gradient tracking for inference speed
        while True:
            try:
                item = ocr_queue.get()
                if item is None: continue

                # item format: (crop, v_type, full_img, track_id, frame_id, enqueued_ts, is_vehicle_crop)
                if isinstance(item, tuple) and len(item) >= 7:
                    (crop, v_type, full_img, track_id, frame_id, enqueued_ts, is_vehicle) = item[:7]
                else: continue

                if (time.time() - enqueued_ts) > OCR_MAX_QUEUE_AGE_SEC: continue

                # If it's a vehicle crop, we need to find the plate first (offloaded from main loop)
                plate_crop = None
                if is_vehicle and plate_detector:
                    plates = plate_detector.detect(crop)
                    if plates:
                        plate_crop = enhance_plate_clarity(plates[0])
                else:
                    plate_crop = crop

                if plate_crop is None: continue
                
                # --- OCR PIPELINE (High Accuracy & Speed) ---
                best_candidate = None
                variant_count = 0
                for processed in build_ocr_variants_lazy(plate_crop):
                    if variant_count >= OCR_VARIANT_LIMIT: break
                    variant_count += 1
                    
                    results_ocr = reader.readtext(processed, detail=1, paragraph=False, allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
                    if not results_ocr: continue

                    filtered_ocr = [res for res in results_ocr if len(res) >= 3 and float(res[2]) >= OCR_MIN_TEXT_CONF]
                    if not filtered_ocr: continue

                    avg_conf = sum(float(res[2]) for res in filtered_ocr) / len(filtered_ocr)
                    text_candidates = build_ocr_text_candidates(filtered_ocr)
                    
                    found_good_on_this_variant = False
                    for text_candidate in text_candidates:
                        valid_plate = extract_valid_plate(text_candidate)
                        strict_plate = validate_indian_plate_strict(text_candidate)
                        pattern_score = 2 if strict_plate else (1 if valid_plate else 0)
                        quality = (pattern_score, avg_conf, len(text_candidate))

                        if best_candidate is None or quality > best_candidate["quality"]:
                            best_candidate = {
                                "plate": strict_plate or valid_plate,
                                "avg_conf": avg_conf,
                                "quality": quality,
                                "strict": bool(strict_plate)
                            }
                        
                        if strict_plate and avg_conf >= OCR_EARLY_EXIT_CONF:
                            found_good_on_this_variant = True
                            break
                    
                    if found_good_on_this_variant: break

                if best_candidate and best_candidate["plate"]:
                    plate = best_candidate["plate"]
                    avg_conf = best_candidate["avg_conf"]
                    now_ts = time.time()
                    
                    global _LATEST_PLATE_INFO
                    if plate_crop is not None:
                        _LATEST_PLATE_INFO = {
                            "plate": plate,
                            "crop": plate_crop.copy(),
                            "ts": now_ts
                        }
                    
                    should_save = False
                    with state_lock:
                        if track_id not in plate_votes:
                            plate_votes[track_id] = {"counts": {}, "scores": {}, "frames": set()}
                        
                        v_state = plate_votes[track_id]
                        if not isinstance(v_state, dict):
                            v_state = {"counts": {}, "scores": {}, "frames": set()}
                            plate_votes[track_id] = v_state
                        
                        # Explicitly check types to satisfy linter
                        v_frames = v_state.get("frames")
                        v_counts = v_state.get("counts")
                        v_scores = v_state.get("scores")

                        if isinstance(v_frames, set) and isinstance(v_counts, dict) and isinstance(v_scores, dict):
                            if frame_id not in v_frames:
                                v_frames.add(frame_id)
                                v_counts[plate] = v_counts.get(plate, 0) + 1
                                v_scores[plate] = v_scores.get(plate, 0.0) + avg_conf
                        
                        # Track-specific voting thresholds
                        cnt = v_counts.get(plate, 0)
                        score = v_scores.get(plate, 0.0)
                        
                        # Fast Path or Voting Path
                        if avg_conf >= OCR_FAST_SAVE_CONF or (cnt >= VOTE_THRESHOLD and score >= OCR_MIN_TOTAL_SCORE):
                            if (now_ts - cooldowns.get(plate, 0)) > SAVE_COOLDOWN_SECONDS:
                                should_save = True
                    
                    if should_save:
                        cooldowns[plate] = now_ts
                        print(f"ðŸ”Ž Detected: {plate}")
                        save_to_db(plate, plate, v_type, full_img)
                        # If extremely confident, mark track as finished
                        if avg_conf >= TRACK_FINISHED_CONF:
                            with state_lock:
                                track_finished.add(track_id)

            except Exception as e: 
                pass # Keep worker alive

def get_status_frame(msg, color=(0, 0, 255)):
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(img, "SMART GATE AI", (150, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    cv2.putText(img, msg, (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    return img

_DETECTION_RESULTS = []
_DETECTION_LOCK = threading.Lock()
_DETECTION_QUEUE = queue.Queue(maxsize=1)

def detection_loop(model, plate_detector):
    """Background thread to run YOLO and OCR enqueuing without lagging the display."""
    global _DETECTION_RESULTS
    while not _STOP_SIGNAL:
        try:
            frame, frame_idx = _DETECTION_QUEUE.get(timeout=1.0)
            
            # Skip frames in detection to stay real-time if queue builds up
            if _DETECTION_QUEUE.qsize() > 2:
                try: _DETECTION_QUEUE.get_nowait()
                except: pass
                continue
                
            # Run YOLO (Heavy task)
            results = model.track(frame, persist=True, verbose=False, 
                                  conf=YOLO_CONF, imgsz=YOLO_IMGSZ,
                                  classes=[2, 3, 5, 7], half=YOLO_USE_HALF,
                                  max_det=YOLO_MAX_DET)

            # Extract lightweight results for display to avoid GPU-CPU syncing in display loop
            light_results = []
            for r in results:
                if r.boxes is not None:
                    try:
                        # Move critical data to CPU in background thread
                        boxes = r.boxes.xyxy.cpu().numpy().astype(int)
                        ids = r.boxes.id.cpu().numpy().astype(int) if r.boxes.id is not None else [-1]*len(boxes)
                        clss = r.boxes.cls.cpu().numpy().astype(int)
                        
                        for i in range(len(boxes)):
                            tid_v = ids[i]
                            plate_text = None
                            try:
                                with state_lock:
                                    v_state = plate_votes.get(tid_v)
                                    if v_state and "counts" in v_state and v_state["counts"]:
                                        plate_text = max(v_state["counts"].items(), key=lambda x: x[1])[0]
                            except Exception: pass
                            
                            light_results.append({
                                'bbox': boxes[i],
                                'id': tid_v,
                                'v_type': normalize_vehicle_type(get_class_name(model.names, clss[i])),
                                'plate': plate_text
                            })
                    except Exception: pass

            now_ts = time.time()
            
            # Record last seen TS for active tracks
            active_ids = []
            for res in light_results:
                tid = res['id']
                v_type = res['v_type']
                if tid >= 0:
                    track_last_seen_ts[tid] = now_ts
                    active_ids.append(tid)
                    
                    # PURGE ON CLASS CHANGE: If YOLO ID remains but it's a different vehicle type
                    if tid in track_vtypes and track_vtypes[tid] != v_type:
                        try:
                            with state_lock:
                                plate_votes.pop(tid, None)
                                track_finished.discard(tid)
                            track_last_enqueue_ts.pop(tid, None)
                        except Exception: pass
                    track_vtypes[tid] = v_type
                    
            # PURGE STALE TRACKS: Fixes the 'Old Plate stuck on New Vehicle' bug
            # Reduced to 0.4 seconds for commercial toll-gate speed! 
            stale_keys = [t for t, ts in track_last_seen_ts.items() if (now_ts - ts) > 0.4]
            for t in stale_keys:
                try:
                    with state_lock:
                        plate_votes.pop(t, None)
                        track_finished.discard(t)
                    track_last_enqueue_ts.pop(t, None)
                    track_last_seen_ts.pop(t, None)
                    track_vtypes.pop(t, None)
                except Exception: pass

            with _DETECTION_LOCK:
                _DETECTION_RESULTS = light_results
            # Handle OCR Enqueuing
            for r in results:
                if not r.boxes: continue
                box_ids = r.boxes.id if r.boxes.id is not None else [-1]*len(r.boxes)
                for box, track_id in zip(r.boxes, box_ids):
                    tid = int(track_id) if track_id is not None else -1
                    if tid < 0: continue
                    
                    # Skip if track already has a high-conf detection
                    if tid in track_finished: continue

                    # Throttle enqueuing
                    if (now_ts - track_last_enqueue_ts.get(tid, 0)) > TRACK_ENQUEUE_INTERVAL_SEC:
                        try:
                            # Safely extract bounding box
                            bbox = box.xyxy[0].cpu().numpy().astype(int)
                            x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
                            
                            area = (x2 - x1) * (y2 - y1)
                            if area < VEHICLE_MIN_AREA: continue
                            
                            nx1, ny1, nx2, ny2 = expand_bbox(x1, y1, x2, y2, frame.shape, 
                                                            pad_x_ratio=VEHICLE_PAD_X, 
                                                            pad_y_ratio=VEHICLE_PAD_Y)
                            
                            v_crop = frame[ny1:ny2, nx1:nx2]
                            
                            if v_crop is not None and v_crop.size > 0:
                                cls_idx = int(box.cls[0])
                                v_type = normalize_vehicle_type(get_class_name(model.names, cls_idx))
                                
                                # --- AUTOMATIC ZOOM IN & OUT ---
                                v_h, v_w = v_crop.shape[:2]
                                if v_w < 400 or v_h < 300:
                                    # "Zoom In" - upscale for distant vehicles
                                    scale = 640 / max(v_w, v_h)
                                    v_crop = cv2.resize(v_crop, (int(v_w * scale), int(v_h * scale)), interpolation=cv2.INTER_LINEAR)
                                elif v_w > 800 or v_h > 800:
                                    # "Zoom Out" - downscale for vehicles that are too close
                                    scale = 800 / max(v_w, v_h)
                                    v_crop = cv2.resize(v_crop, (int(v_w * scale), int(v_h * scale)), interpolation=cv2.INTER_AREA)
                                
                                if not ocr_queue.full():
                                    # Put VEHICLE CROP in queue; plate detection will happen in ocr_worker threads
                                    ocr_queue.put((v_crop, v_type, frame.copy(), tid, frame_idx, now_ts, True))
                                    track_last_enqueue_ts[tid] = now_ts
                        except Exception as e:
                            print(f"[AI-TRACK] Error processing box: {e}")
                                    
        except queue.Empty:
            continue
        except Exception as e:
            print(f"[AI-THREAD] Error: {e}")

def start_detection():
    global video_frame, video_lock, _STOP_SIGNAL
    
    with video_lock:
        video_frame = get_status_frame("SYSTEM INITIALIZING...", (255, 165, 0))
    
    ensure_resources()
    if not os.path.exists('captured_images'): os.makedirs('captured_images')
    
    print("[SYSTEM] Starting Camera Interface...")
    reader_obj = FastCameraReader(indexes=(0, 1, 2))
    if not reader_obj.running:
        print("[ERROR] No camera detected.")
        with video_lock:
            video_frame = get_status_frame("ERROR: NO CAMERA SIGNAL", (0, 0, 255))
        return

    print("[SYSTEM] Loading YOLOv8...")
    try:
        model = YOLO('yolov8n.pt')
        import torch
        if torch.cuda.is_available():
            model.to("cuda:0")
        
        # Optimize for speed: Half precision & specific input sz
        if YOLO_USE_HALF and torch.cuda.is_available(): 
            print("[YOLO] Fusing and switching to FP16")
            model.fuse()
            model.half()
        else:
            print("[YOLO] Fusing model (CPU)")
            model.fuse()
            
    except Exception as e:
        print(f"[YOLO] Load failed: {e}")
        with video_lock:
            video_frame = get_status_frame("MODEL ERROR", (0, 0, 255))
        return
    
    plate_detector = PlateDetector()
    
    # Start background threads
    for _ in range(OCR_WORKERS):
        threading.Thread(target=ocr_worker, args=(plate_detector,), daemon=True).start()
    
    threading.Thread(target=detection_loop, args=(model, plate_detector), daemon=True).start()
    
    print("[SYSTEM] Monitoring Active.")
    frame_count = 0

    while not _STOP_SIGNAL:
        try:
            ret, frame = reader_obj.read()
            if not ret:
                time.sleep(0.01)
                continue
                
            frame_count += 1
            
            # Feed the detection thread if it's empty
            if _DETECTION_QUEUE.empty():
                try:
                    # Detection thread gets a copy because it runs asynchronously
                    _DETECTION_QUEUE.put_nowait((frame.copy(), frame_count))
                except queue.Full: pass

            # Use the frame directly for display to avoid one extra copy
            display_frame = frame
            
            # Overlay Status & Timestamp (Top right)
            now_str = time.strftime("%H:%M:%S")
            cv2.putText(display_frame, f"AI LIVE - {now_str}", (10, 30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            
            # Draw detections (using latest pre-computed results)
            with _DETECTION_LOCK:
                local_results = list(_DETECTION_RESULTS)
            
            for res in local_results:
                try:
                    x1, y1, x2, y2 = res['bbox']
                    tid = res['id']
                    v_type = res['v_type']
                    p_text = res.get('plate')
                    
                    color = (0, 255, 0) if tid >= 0 else (0, 165, 255)
                    cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
                    
                    label = f"{v_type}"
                    if p_text: label += f" - {p_text}"
                    elif tid >= 0: label += f" ID:{tid}"
                        
                    cv2.putText(display_frame, label, (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                    
                    if tid in track_finished:
                        cv2.putText(display_frame, "SCANNED", (x1, y1-30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
                except Exception:
                    pass

            # Overlay Picture-in-Picture of Latest Plate
            global _LATEST_PLATE_INFO
            if _LATEST_PLATE_INFO:
                info = _LATEST_PLATE_INFO
                # Show for 6 seconds
                if (time.time() - info["ts"]) < 6.0:
                    p_img = info["crop"]
                    p_txt = info["plate"]
                    if p_img is not None and p_img.size > 0:
                        try:
                            ph, pw = p_img.shape[:2]
                            scale = 120.0 / max(ph, pw, 1) # Target size roughly 120px
                            new_w, new_h = max(1, int(pw * scale)), max(1, int(ph * scale))
                            p_img_small = cv2.resize(p_img, (new_w, new_h))
                            
                            if len(p_img_small.shape) == 2:
                                p_img_small = cv2.cvtColor(p_img_small, cv2.COLOR_GRAY2BGR)
                                
                            # Bottom-center overlay position
                            dh, dw = display_frame.shape[:2]
                            dx = max(0, dw // 2 - new_w // 2)
                            dy = max(0, dh - new_h - 40)
                            
                            display_frame[dy:dy+new_h, dx:dx+new_w] = p_img_small
                            cv2.rectangle(display_frame, (dx, dy), (dx+new_w, dy+new_h), (0, 255, 0), 2)
                            cv2.putText(display_frame, p_txt, (dx-10, dy-10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                        except Exception as e:
                            print(f"[DISPLAY] PIP Error: {e}")

            with video_lock:
                video_frame = display_frame

        except Exception as e:
            print(f"[DISPLAY-LOOP] Error: {e}")
            time.sleep(1)

def generate():
    """Generator for the MJPEG video stream."""
    global video_frame, video_lock
    print("[SYSTEM] Video stream requested.")
    
    # Pre-encode a failure frame just in case
    fail_img = get_status_frame("STREAM ERROR", (0, 0, 255))
    _, fail_encoded = cv2.imencode(".jpg", fail_img)
    fail_bytes = fail_encoded.tobytes() if fail_encoded is not None else b""

    while True:
        try:
            with video_lock:
                if video_frame is None:
                    img = get_status_frame("AI INITIALIZING...", (255, 165, 0))
                else:
                    img = video_frame # No copy needed here as we encode it immediately
            
            # Encode frame as JPEG (Moved outside lock for performance)
            ok, encoded = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70]) # Optimize size
            if not ok or encoded is None:
                frame_bytes = fail_bytes
            else:
                frame_bytes = encoded.tobytes()

            # Standards-compliant MJPEG frame
            if isinstance(frame_bytes, bytes):
                header = b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                yield header + frame_bytes + b'\r\n'
            else:
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + fail_bytes + b'\r\n'
            
        except Exception as e:
            print(f"[STREAM] Generator Error: {e}")
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + fail_bytes + b'\r\n'
            time.sleep(1.0)
            
        time.sleep(0.03) # 30fps

if __name__ == '__main__':
    start_detection()

