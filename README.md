# SBL Semantic SQL AI Backend 🚀

ระบบ SQL AI อัจฉริยะสำหรับฐานข้อมูลเช่าซื้อ (SBL) ที่ใช้แนวคิด **Semantic Layer** เพื่อความแม่นยำสูงสุดและปลอดภัยตามกฎธุรกิจ (Business Rules)

## 🌟 Key Features

- **True Semantic Layer**: ไม่ให้ LLM แตะ SQL โดยตรงในขั้นตอนแรก แต่จะให้ LLM แปลงคำถามเป็น "ความหมายธุรกิจ" (JSON Intent) ก่อนเสมอ
- **Trusted SQL Generator**: ระบบสร้าง SQL ที่ถูกควบคุมด้วยกฎเหล็ก (Mandatory Rules) เพื่อให้รองรับ SQL Server 2008 (ใช้ TOP แทน LIMIT, ใช้ CAST AS MONEY สำหรับการคำนวณเงิน)
- **Security Validator**: ระบบตรวจสอบ SQL (Query Validator) ที่จะสกัดกั้นคำสั่งที่ผิดกฎธุรกิจหรือเสี่ยงต่อความปลอดภัย
- **Auto-Fix Engine**: ระบบซ่อมแซม SQL อัตโนมัติสำหรับข้อผิดพลาดที่ LLM มักจะทำพลาดบ่อยๆ (เช่น การใช้ชื่อคอลัมน์ผิด หรือลืมใส่ CAST)
- **Professional Insights**: สรุปข้อมูลดิบจากฐานข้อมูลให้เป็นตาราง Markdown ที่สวยงามและสรุปเนื้อหาเป็นภาษาไทยที่เป็นทางการ

## 🛠️ Tech & Tools

### 🎨 Frontend
![JavaScript](https://img.shields.io/badge/javascript-%23323330.svg?style=for-the-badge&logo=javascript&logoColor=%23F7DF1E)
![TypeScript](https://img.shields.io/badge/typescript-%23007ACC.svg?style=for-the-badge&logo=typescript&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-black?style=for-the-badge&logo=next.js&logoColor=white)
![TailwindCSS](https://img.shields.io/badge/tailwindcss-%2338B2AC.svg?style=for-the-badge&logo=tailwind-css&logoColor=white)

### ⚙️ Backend
![Python](https://img.shields.io/badge/python-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)
![Ollama](https://img.shields.io/badge/Ollama-LLM-blue?style=for-the-badge)
![Qwen 2.5-Coder](https://img.shields.io/badge/Qwen%202.5--Coder-AI-purple?style=for-the-badge)

### 🗄️ Database
![MicrosoftSQLServer](https://img.shields.io/badge/Microsoft%20SQL%20Server-CC2927?style=for-the-badge&logo=microsoft%20sql%20server&logoColor=white)

### 🛠️ AI & Dev Tools
![ChatGPT](https://img.shields.io/badge/ChatGPT-74aa9c?style=for-the-badge&logo=openai&logoColor=white)
![Claude](https://img.shields.io/badge/Claude-d97757?style=for-the-badge&logo=anthropic&logoColor=white)
![Google Antigravity](https://img.shields.io/badge/Google_Antigravity-4285F4?style=for-the-badge&logo=google&logoColor=white)
![GitLab](https://img.shields.io/badge/GitLab-FC6D26?style=for-the-badge&logo=gitlab&logoColor=white)

## 🏗️ Architecture

1. **Semantic Layer (`core/semantic_layer.py`)**: ตีความหมายจาก Natural Language -> JSON Intent
2. **AI Controller (`core/ai_controller.py`)**: ควบคุม Pipeline ทั้งหมด (Routing -> Intent -> SQL -> Fix -> Validate -> Execute)
3. **SQL System Prompt (`prompts/sql_system.py`)**: คัมภีร์ที่ใช้ควบคุม SQL Generator พร้อมตัวอย่าง Few-shot
4. **Query Validator (`security/query_validator.py`)**: ด่านตรวจสุดท้ายก่อนรัน SQL จริง
5. **Database Schema (`data/database_schema.json`)**: แหล่งข้อมูลอ้างอิง (Single Source of Truth) ที่มี metadata ครบถ้วน

## 🛠️ Tech Stack

- **Framework**: FastAPI (Python)
- **LLM Engine**: Ollama (Llama 3 / Mistral / DeepSeek)
- **Database**: SQL Server 2008
- **ORM/Tooling**: Python-dotenv, PyODBC

## 🚀 Getting Started

### 1. Installation
```bash
# ติดตั้ง dependencies
pip install -r requirements.txt
```

### 2. Configuration
แก้ไขไฟล์ `.env` เพื่อเชื่อมต่อกับ Ollama และฐานข้อมูล
```env
OLLAMA_BASE_URL=http://localhost:11434
DB_CONNECTION_STRING=...
```

### 3. Run Server
```bash
uvicorn main:app --reload --host 0.0.0.0
```

## 📝 Usage Example

**คำถาม**: "ขอรายชื่อสัญญาที่ค้างค่างวดของสาขา MN มา 10 รายการ"

**ระบบจะทำงานดังนี้**:
1. **Semantic**: สกัด Intent ว่าต้องการ `search` โดยมี Filter `OLID='MN'` และ `Credit > 0`
2. **SQL Gen**: สร้าง SQL `SELECT TOP 10 AccNo, OLID, Credit FROM LSM010 WHERE OLID = 'MN' AND CAST(Credit AS MONEY) > 0 ORDER BY Credit DESC`
3. **Validate**: ตรวจสอบว่ามีการใช้ `OLID` และ `CAST` ถูกต้องตามกฎ
4. **Display**: แสดงผลเป็นตาราง Markdown พร้อมคำแปลชื่อคอลัมน์เป็นภาษาไทย

---
*Developed with ❤️ by SBL AI Team*
