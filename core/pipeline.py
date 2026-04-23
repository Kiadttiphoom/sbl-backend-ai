"""
Data Pipeline Module
--------------------
จัดการลำดับการประมวลผลข้อมูล (Transformation Flows) ก่อนส่งให้ LLM
"""

class DataPipeline:
    def __init__(self):
        self.steps = []

    def add_step(self, func):
        self.steps.append(func)

    def run(self, data: list):
        if not data: return data
        for step in self.steps:
            data = step(data)
        return data

# --- Default Pipeline Steps ---

def format_numeric_values(rows: list) -> list:
    """ปัดเศษทศนิยมให้สวยงาม (2 ตำแหน่ง) และแปลงกลับเป็น int หากไม่มีเศษ"""
    for row in rows:
        for k, v in row.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                rounded_val = round(float(v), 2)
                # ถ้าปัดแล้วเท่ากับจำนวนเต็ม (เช่น 5.0) ให้ส่งเป็น int (5)
                if rounded_val == int(rounded_val):
                    row[k] = int(rounded_val)
                else:
                    row[k] = rounded_val
    return rows

def mask_sensitive_data(rows: list) -> list:
    """ตัวอย่าง: เซ็นเซอร์รหัสพนักงาน (FolID) บางส่วนเพื่อความเป็นส่วนตัว"""
    for row in rows:
        if "FolID" in row:
            val = str(row["FolID"])
            if len(val) > 1:
                row["FolID"] = val[0] + "*" * (len(val)-1)
    return rows

# Initialize Global Pipeline
pipeline = DataPipeline()
pipeline.add_step(format_numeric_values)
pipeline.add_step(mask_sensitive_data)