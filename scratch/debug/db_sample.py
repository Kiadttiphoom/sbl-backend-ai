import pyodbc
import os
from dotenv import load_dotenv

load_dotenv()

def get_samples():
    conn_str = (
        f"DRIVER={{SQL Server Native Client 10.0}};"
        f"SERVER={os.getenv('DB_SERVER', 'localhost')};"
        f"DATABASE={os.getenv('DB_NAME', 'lspdata')};"
        f"UID={os.getenv('DB_USER', 'sa')};"
        f"PWD={os.getenv('DB_PASS')};"
        f"Connection Timeout=30;"
        f"TrustServerCertificate=yes;"
    )
    
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()
        
        print("--- Sample AccNo ---")
        cursor.execute("SELECT TOP 3 AccNo FROM LSM010")
        for row in cursor.fetchall():
            print(row.AccNo)
            
        print("--- Sample OLID (Branches) ---")
        cursor.execute("SELECT DISTINCT TOP 5 OLID FROM LSM010")
        for row in cursor.fetchall():
            print(row.OLID)
            
        print("--- Sample Stat2 (Aging) ---")
        cursor.execute("SELECT DISTINCT TOP 5 Stat2 FROM LSM010")
        for row in cursor.fetchall():
            print(row.Stat2)
            
        print("--- Record Count ---")
        cursor.execute("SELECT COUNT(*) FROM LSM010")
        print(cursor.fetchone()[0])
        
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    get_samples()
