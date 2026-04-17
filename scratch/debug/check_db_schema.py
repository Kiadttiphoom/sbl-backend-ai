import pyodbc

import os
from dotenv import load_dotenv

load_dotenv()

# Use environment variables instead of hardcoded credentials
DB_CONFIG = {
    "server": os.getenv("DB_SERVER", "localhost"),
    "database": os.getenv("DB_NAME", "lspdata"),
    "username": os.getenv("DB_USER", "sa"),
    "password": os.getenv("DB_PASS", ""),
    "driver": os.getenv("DB_DRIVER", "{SQL Server}")
}

def check_columns():
    conn_str = (
        f"DRIVER={DB_CONFIG['driver']};"
        f"SERVER={DB_CONFIG['server']};"
        f"DATABASE={DB_CONFIG['database']};"
        f"UID={DB_CONFIG['username']};"
        f"PWD={DB_CONFIG['password']};"
    )
    try:
        conn = pyodbc.connect(conn_str, timeout=5)
        cursor = conn.cursor()
        for table in ['LSM010', 'LSM007']:
            cursor.execute(f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '{table}'")
            columns = [row.COLUMN_NAME for row in cursor.fetchall()]
            print(f"\nExisting Columns in {table}:")
            for col in sorted(columns):
                print(f"- {col}")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_columns()
