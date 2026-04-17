import sys
import os
# Add the current directory to sys.path
sys.path.append(os.getcwd())

from training_memory import get_sql_training_context, get_insight_training_context

print("--- SQL Training Context ---")
sql_ctx = get_sql_training_context()
if sql_ctx:
    print(sql_ctx[:500] + "...")
else:
    print("FAILED: SQL context is empty")

print("\n--- Insight Training Context ---")
insight_ctx = get_insight_training_context()
if insight_ctx:
    print(insight_ctx[:500] + "...")
else:
    print("FAILED: Insight context is empty")
