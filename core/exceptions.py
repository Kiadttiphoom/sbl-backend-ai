class SBLError(Exception):
    """คลาสพื้นฐานสำหรับ Error ทั้งหมดในระบบ SBL"""
    def __init__(self, message: str, details: str = None):
        super().__init__(message)
        self.message = message
        self.details = details

class DatabaseError(SBLError):
    """เกิดข้อผิดพลาดในการเชื่อมต่อหรือคิวรีฐานข้อมูล"""
    pass

class LLMError(SBLError):
    """เกิดข้อผิดพลาดในการเรียกใช้ Ollama หรือ Agent"""
    pass

class SecurityError(SBLError):
    """ตรวจพบการละเมิดกฎความปลอดภัย เช่น SQL Injection หรือ Prompt Injection"""
    pass

class BusinessRuleError(SBLError):
    """ไม่ผ่านกฎทางธุรกิจ (Business Rules)"""
    pass

class SkillError(SBLError):
    """เกิดข้อผิดพลาดในการโหลดหรือรัน Agent Skill"""
    pass
