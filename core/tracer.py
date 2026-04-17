"""
Performance Tracer Module (Placeholder)
---------------------------------------
ใช้สำหรับวัดประสิทธิภาพ (Latency) และลำดับการทำงานของ AI Pipeline
เช่น การวัดเวลาที่ใช้ใน SQL Generation เทียบกับ Insight Generation
"""

import time
from contextlib import contextmanager

@contextmanager
def trace_span(name: str):
    start = time.perf_counter()
    yield
    end = time.perf_counter()
    # ในอนาคตสามารถเก็บลง Database หรือส่งไปยัง OpenTelemetry
    print(f"[TRACE] {name} took {end - start:.4f} seconds")