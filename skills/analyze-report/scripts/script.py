def run(data_rows: list):
    """
    วิเคราะห์ข้อมูลดิบที่ส่งเข้ามา
    """
    if not data_rows:
        return "ไม่มีข้อมูลให้วิเคราะห์"
    
    total_rows = len(data_rows)
    
    # ตัวอย่าง Logic การวิเคราะห์ง่ายๆ
    # ในการใช้งานจริง เราอาจจะใช้ Pandas หรือ Library อื่นๆ ช่วยที่นี่
    summary = f"📊 **ผลการวิเคราะห์เบื้องต้น**\n"
    summary += f"- จำนวนรายการทั้งหมด: {total_rows} รายการ\n"
    
    # ลองหาคอลัมน์ที่เป็นตัวเลขเพื่อรวมผล (ถ้ามี)
    numeric_cols = [k for k, v in data_rows[0].items() if isinstance(v, (int, float))]
    
    for col in numeric_cols:
        total_val = sum(row.get(col, 0) for row in data_rows)
        avg_val = total_val / total_rows
        summary += f"- ยอดรวมของ {col}: {total_val:,.2f} (เฉลี่ย: {avg_val:,.2f})\n"
        
    summary += "\n**ข้อสรุป:** ข้อมูลมีความสมบูรณ์และพร้อมสำหรับการสรุปในขั้นถัดไป"
    
    return summary
