from intent import detect_intent
import time

q = "ยอดรวมคงเหลือทั้งหมด"
start = time.time()
print(f"Testing intent for: {q}")
result = detect_intent(q)
end = time.time()
print(f"Result: {result}")
print(f"Time taken: {end - start:.4f}s")
