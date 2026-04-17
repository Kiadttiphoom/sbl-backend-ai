import pyodbc
import os
from dotenv import load_dotenv

load_dotenv()

def analyze_db():
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
        
        print("--- AccStat Distribution ---")
        cursor.execute("SELECT AccStat, COUNT(*) as cnt FROM LSM010 GROUP BY AccStat")
        for row in cursor.fetchall():
            print(f"{row[0]}: {row[1]}")
            
        print("\n--- Stat2 (Aging) Distribution ---")
        cursor.execute("SELECT Stat2, COUNT(*) as cnt FROM LSM010 GROUP BY Stat2")
        for row in cursor.fetchall():
            print(f"{row[0]}: {row[1]}")
            
        print("\n--- TOP 5 Branches (OLID) ---")
        cursor.execute("SELECT TOP 5 OLID, COUNT(*) as cnt FROM LSM010 GROUP BY OLID ORDER BY cnt DESC")
        for row in cursor.fetchall():
            print(f"{row[0]}: {row[1]}")
            
        print("\n--- Watchlist Count ---")
        cursor.execute("SELECT COUNT(*) FROM LSM010 WHERE Watchlist = 'W'")
        print(cursor.fetchone()[0])
        
        print("\n--- Date Range (AccDate) ---")
        cursor.execute("SELECT MIN(AccDate), MAX(AccDate) FROM LSM010 WHERE AccDate <> ''")
        row = cursor.fetchone()
        print(f"Min: {row[0]}, Max: {row[1]}")
        
        print("\n--- Average Fees/Interest ---")
        cursor.execute("SELECT AVG(Interest), AVG(Fee), AVG(CollectionFee) FROM LSM010")
        row = cursor.fetchone()
        print(f"Int: {row[0]}, Fee: {row[1]}, Coll: {row[2]}")

        # Check for Balloon contracts
        print("\n--- Balloon Contracts Count (AccNoB not empty) ---")
        cursor.execute("SELECT COUNT(*) FROM LSM010 WHERE AccNoB <> ''")
        print(cursor.fetchone()[0])

        # Check for Lawsuit cases (LawDate not empty)
        print("\n--- Lawsuit Cases (LawDate not empty) ---")
        cursor.execute("SELECT COUNT(*) FROM LSM010 WHERE LawDate <> ''")
        print(cursor.fetchone()[0])

        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    analyze_db()
