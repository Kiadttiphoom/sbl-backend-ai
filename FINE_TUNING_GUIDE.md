# Fine-Tuning Guide for SBL AI Model

## Goal
ให้ local Qwen model เข้าใจบริบท SBL ได้ดีขึ้น

## Data Collection Strategy

### 1. **Stat2 Variations** (ต้องเก็บทั้งหมด)
```
Q: "พนักงานคนไหนดูแล สูญ ปกติ เยอะที่สุด"
A: Stat2 = 'A'

Q: "สูญ ครบกำหนดบอกเลิก 35 วัน"
A: Stat2 = 'F'

Q: "ติดคดี ดำเนินการอยู่"
A: Stat2 = 'G'
... [collect all variations]
```

### 2. **Complex Queries**
```
Q: "ยอดปิดบัญชีประมาณการ + ดอกเบี้ยค้าง + ค่าทวงถาม"
A: SELECT Bal + BalTax + Interest + Fee + CollectionFee

Q: "JOIN ผู้ยึด + พนักงาน"
A: FROM LSM010 INNER JOIN LSM007 ON ...
```

### 3. **Edge Cases**
```
Q: "พนักงาน A มีสัญญา Stat2 = D หรือ F อยู่หรือไม่"
A: Handle OR / IN clauses carefully

Q: "มีความเสี่ยงไหม (สูญ + ติดคดี + ครบกำหนด)"
A: Multiple conditions → Stat2 IN ('D','F','G')
```

## Fine-Tuning Steps

### Phase 1: Data Preparation (สัปดาห์ 1-2)
1. เก็บอย่างน้อย **200 QA pairs** จาก actual user queries
2. Format as JSONL:
```jsonl
{"prompt": "พนักงานคนไหนดูแลสูญปกติเยอะที่สุด", "completion": "SELECT TOP 1 ... WHERE Stat2 = 'A'"}
{"prompt": "ยอดคงเหลือรวม VAT", "completion": "SELECT Bal + BalTax"}
```

### Phase 2: Fine-tune (สัปดาห์ 3-4)
```bash
# ถ้า local Ollama support fine-tuning
ollama fine-tune qwen2.5:3b --data training_data.jsonl --output sbl-model

# หรือใช้ external service ถ้า local ไม่รองรับ
```

### Phase 3: Evaluation (สัปดาห์ 5)
- ทดสอบ 50 คำถามใหม่ ที่ไม่เคยเห็น
- วัด accuracy
- ถ้า < 90% → เก็บ more examples

## ตอนนี้: Start Collection
- สอบถามพนักงานทำรายการค่าเล่นทั้งหมด
- บันทึก query + expected SQL
- เก็บใน `training_data.jsonl`

## Resources
- Ollama Fine-tuning: https://github.com/ollama/ollama
- RLHF Framework: https://github.com/CarperAI/trlx
