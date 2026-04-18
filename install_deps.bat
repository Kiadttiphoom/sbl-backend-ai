@echo off
cd /d "%~dp0"

echo [1/3] Updating pip...
.\venv\Scripts\python.exe -m pip install --upgrade pip

echo [2/3] Installing dependencies from requirements.txt...
.\venv\Scripts\pip install -r requirements.txt

echo [3/3] Checking essential modules (Backup)...
:: ใส่ตัวที่เคย Error ไว้กันเหนียวครับ
.\venv\Scripts\pip install python-dotenv pyodbc

echo.
echo ---------------------------------------
echo Installation Complete!
echo ---------------------------------------
pause