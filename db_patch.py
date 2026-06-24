import mysql.connector

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "smart_gate",
    "autocommit": True
}

def fix_db():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # Check vehicle_activity
        cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='smart_gate' AND TABLE_NAME='vehicle_activity'")
        cols = {row[0] for row in cursor.fetchall()}
        
        if "updated_at" not in cols:
            print("Adding updated_at to vehicle_activity...")
            cursor.execute("ALTER TABLE vehicle_activity ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")
            cursor.execute("CREATE INDEX idx_updated_at ON vehicle_activity(updated_at)")
        
        # Check home_vehicles
        cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA='smart_gate' AND TABLE_NAME='home_vehicles'")
        cols = {row[0] for row in cursor.fetchall()}
        
        if "updated_at" not in cols:
            print("Adding updated_at to home_vehicles...")
            cursor.execute("ALTER TABLE home_vehicles ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")

        print("DB fix complete.")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_db()
