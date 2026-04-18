import sys
import os

# เพิ่ม Project Root เข้าไปใน sys.path เพื่อให้ import db ได้
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from db.fetch import fetch_data

def run(sql_query: str):
    """
    ดึงข้อมูลจาก Database ด้วยคำสั่ง SQL ที่ถูกสร้างมาจาก Pipeline หลัก (Agent)
    ห้ามไม่ให้ Skill นี้เขียน SQL เองเด็ดขาด เพื่อป้องกันความมั่ว
    """
    # [LOG] แสดง SQL ที่รันจริงในระบบ
    print(f"DEBUG: Executing Injected Skill SQL: {sql_query}")
    
    try:
        results = fetch_data(sql_query)
        if not results:
            return "ไม่พบข้อมูลจากตาราง"
        return results
    except Exception as e:
        return f"เกิดข้อผิดพลาดในการค้นหา: {str(e)}"
