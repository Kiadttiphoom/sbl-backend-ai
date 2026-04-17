from sql_guard import guard

test_queries = [
    "SELECT COUNT(*) FROM LSM010 WHERE Stat2 = 'D'", # No TOP, but aggregate
    "SELECT SUM(Bal) FROM LSM010",                  # No TOP, but aggregate
    "SELECT AccNo FROM LSM010",                     # No TOP, standard (should be AUTO-FIXED)
]

for q in test_queries:
    print(f"\nOriginal: {q}")
    sanitized = guard.sanitize(q)
    print(f"Sanitized: {sanitized}")
    safe, reason = guard.validate(sanitized)
    print(f"Safe: {safe}, Reason: {reason}")
