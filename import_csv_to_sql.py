import pandas as pd
import os
import re
import pyodbc

# =========================
# CONFIG
# =========================
FOLDER_PATH = r"C:\Users\User\Desktop\ai\data_lspdata"

DB_SERVER = "DESKTOP-HUMM9V1\\SQLEXPRESS"
DB_NAME = "lspdata"
DB_USER = "sa"
DB_PASS = "1234"

# =========================
# CONNECT
# =========================
conn = pyodbc.connect(
    f"DRIVER={{SQL Server}};"
    f"SERVER={DB_SERVER};"
    f"DATABASE={DB_NAME};"
    f"UID={DB_USER};"
    f"PWD={DB_PASS};"
)
cursor = conn.cursor()

# =========================
# CLEAN TABLE NAME
# =========================
def clean_table_name(name):
    name = os.path.splitext(name)[0]
    name = re.sub(r"\W+", "_", name)
    return name.lower()

# =========================
# CLEAN COLUMN NAME
# =========================
def clean_column_names(df):
    df.columns = df.columns.str.strip()
    df.columns = df.columns.str.replace(" ", "_")
    df.columns = df.columns.str.replace(r"[^\w]", "", regex=True)
    return df

# =========================
# CREATE TABLE
# =========================
def create_table(df, table_name):
    cols = []

    for col in df.columns:
        # 🔥 เพิ่มความยาวกันข้อมูลยาว
        cols.append(f"[{col}] NVARCHAR(MAX)")

    col_sql = ", ".join(cols)

    sql = f"""
    IF NOT EXISTS (
        SELECT * FROM INFORMATION_SCHEMA.TABLES 
        WHERE TABLE_NAME = '{table_name}'
    )
    BEGIN
        CREATE TABLE [{table_name}] (
            {col_sql}
        )
    END
    """

    cursor.execute(sql)
    conn.commit()

# =========================
# INSERT DATA (เร็ว)
# =========================
def insert_data(df, table_name):
    cols = ",".join([f"[{c}]" for c in df.columns])
    placeholders = ",".join(["?"] * len(df.columns))

    sql = f"INSERT INTO [{table_name}] ({cols}) VALUES ({placeholders})"

    # 🔥 เร็วขึ้นมาก
    cursor.fast_executemany = True

    data = df.values.tolist()
    cursor.executemany(sql, data)

    conn.commit()

# =========================
# MAIN
# =========================
def import_csv():
    files = [f for f in os.listdir(FOLDER_PATH) if f.endswith(".csv")]

    print(f"📂 เจอ {len(files)} ไฟล์\n")

    for file in files:
        path = os.path.join(FOLDER_PATH, file)
        table_name = clean_table_name(file)

        print(f"⏳ {file} → {table_name}")

        try:
            # 🔥 อ่าน CSV แบบกันพัง
            df = pd.read_csv(
                path,
                encoding="utf-8-sig",
                dtype=str,
                low_memory=False
            )

            # 🔥 clean data
            df = df.fillna("")
            df = clean_column_names(df)

            # 🔥 สร้าง table
            create_table(df, table_name)

            # 🔥 insert data
            insert_data(df, table_name)

            print(f"✅ สำเร็จ: {table_name}\n")

        except Exception as e:
            print(f"❌ ERROR: {file}")
            print(e)
            print("-" * 40)

    print("🎉 เสร็จแล้ว")

# =========================
# RUN
# =========================
if __name__ == "__main__":
    import_csv()