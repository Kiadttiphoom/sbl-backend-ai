import sys
import os

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from analysis.engine import engine

def test_markdown_table_formatting():
    print("--- Testing Markdown Table Formatting ---")
    mock_results = [
        {"FolID": "373", "FolName": "นางสาวพรศิริ เดชภักดี", "TotalContracts": 5},
        {"FolID": "567", "FolName": "นายบอรอเฮง เปาะแต", "TotalContracts": 4},
    ]
    
    formatted = engine.format_db_results(mock_results, None)
    print("Formatted Output:")
    print(formatted)
    
    if "| รหัสพนักงาน | ชื่อพนักงาน | จำนวนสัญญา |" in formatted:
        print("\n[SUCCESS] Header formatted correctly.")
    if "|---" in formatted:
        print("[SUCCESS] Separator present.")
    if "นางสาวพรศิริ" in formatted and "5" in formatted:
        print("[SUCCESS] Data rows present.")

if __name__ == "__main__":
    test_markdown_table_formatting()
