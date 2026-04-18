import sys
import os

# เพิ่ม Project Root เข้าไปใน sys.path เพื่อให้ import db ได้
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from db.fetch import fetch_data

def run(search_query: str):
    """
    ค้นหาข้อมูลเบื้องต้นจาก query ที่ได้รับ
    ในที่นี้เราจะจำลองการแปลงคำค้นหาเป็น SQL พื้นฐาน
    """
    # ตัวอย่าง: ถ้า query มีคำว่า 'พนักงาน' ให้ลองค้นหาจาก table พนักงาน (ถ้ามี)
    # หมายเหตุ: ในการใช้งานจริง AI ควรเป็นคนสร้าง SQL หรือเรามี Logic แปลง Query ที่แม่นยำกว่านี้
    
    # จำลอง SQL ง่ายๆ สำหรับการสาธิต
    sql = f"SELECT TOP 10 * FROM Employees WHERE Name LIKE '%{search_query}%' OR Position LIKE '%{search_query}%'"
    
    # [LOG] แสดง SQL ที่รันจริงในระบบ
    print(f"DEBUG: Executing Skill SQL: {sql}")
    
    try:
        results = fetch_data(sql)
        if not results:
            return f"ไม่พบข้อมูลสำหรับ: {search_query}"
        return results
    except Exception as e:
        return f"เกิดข้อผิดพลาดในการค้นหา: {str(e)}"
