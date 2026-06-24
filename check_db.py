import mysql.connector

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "smart_gate"
}

try:
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("DESCRIBE home_vehicles")
    print("Table: home_vehicles")
    for row in cursor.fetchall():
        print(row)
    
    cursor.execute("DESCRIBE vehicle_activity")
    print("\nTable: vehicle_activity")
    for row in cursor.fetchall():
        print(row)
    
    conn.close()
except Exception as e:
    print(f"Error: {e}")
