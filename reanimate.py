import re

app_path = r"c:\Project 1 - SmartGate - Backups\Smart_GATE_ML_Model - with Email\app.py"

with open(app_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the missing part between ensure_home_vehicle_schema and _camera_fallback_stream
# Use re.escape or be very careful about exact formatting.
# The previous view showed 4 spaces indentation.

# We'll use a more flexible regex for whitespace.
pattern = r'(def ensure_home_vehicle_schema\(conn\):\s+global _HOME_COLS_CACHE\s+cols = _fetch_home_vehicle_columns\(conn\)\s+cursor = conn.cursor\(\))\s+(def _camera_fallback_stream\(\):)'

replacement = r'''\1

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

    cursor.close()
    _HOME_COLS_CACHE = None

def init_db():
    conn = get_db_connection()
    if conn:
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
                INDEX (plate_number),
                INDEX (status),
                INDEX (entry_time)
            )
        """)
        ensure_system_config_schema(conn)
        ensure_home_vehicle_schema(conn)
        cursor.close()
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

\2'''

# Multi-line match is needed
if re.search(pattern, content, flags=re.MULTILINE):
    new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    with open(app_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("app.py repaired successfully with init_db and indices.")
else:
    print("Could not find the insertion point in app.py")
    # Debugging: show the problematic area
    idx = content.find("def ensure_home_vehicle_schema")
    if idx != -1:
        print("Found ensure_home_vehicle_schema at index", idx)
        print("Context:", content[idx:idx+300])
