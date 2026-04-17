import pyodbc

DB_CONFIG = {
    "server": "192.168.2.201",
    "database": "lspdata",
    "username": "sa",
    "password": "1234",
    "driver": "{SQL Server}"
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
