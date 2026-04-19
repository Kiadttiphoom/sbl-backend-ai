@echo off
cd /d "%~dp0"

echo [1/4] Create folder venv...
python -m venv venv

echo [2/43] Updating pip...
.\venv\Scripts\python.exe -m pip install --upgrade pip

echo [3/4] Installing dependencies from requirements.txt...
.\venv\Scripts\pip install -r requirements.txt

echo [4/4] Checking essential modules (Backup)...
:: ใส่ตัวที่เคย Error ไว้กันเหนียวครับ
.\venv\Scripts\pip install python-dotenv pyodbc

echo.
echo ---------------------------------------
echo Installation Complete!
echo ---------------------------------------
pause