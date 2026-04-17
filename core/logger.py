import logging
import sys

def setup_logger(name: str = "sbl_agent"):
    """
    ตั้งค่าระบบ Logging พื้นฐานสำหรับโปรเจค
    ในอนาคตสามารถขยายเพื่อส่ง Log ไปยัง File หรือ Cloud Watch
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

# Global logger instance
logger = setup_logger()