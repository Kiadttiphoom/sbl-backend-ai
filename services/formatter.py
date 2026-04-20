"""
Analysis Engine / Formatter
- Fix: engine = AnalysisEngine() instantiated twice (removed duplicate)
- _get_label: สร้าง map_upper ครั้งเดียวแทนทุก call
- get_summary_stats: ใช้ set สำหรับ agg_keys
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# ── Column label map (class-level constant) ───────────────────────────────────
_COLUMN_LABEL_MAP: Dict[str, str] = {
    "TOTALCONTRACTS": "จำนวนสัญญา",
    "TOTALBALANCE": "รวมยอดหนี้ (ไม่รวม VAT)",
    "TOTALVAT": "รวมภาษี (VAT)",
    "TOTALINTEREST": "รวมดอกเบี้ยค้าง",
    "TOTALCREDIT": "รวมยอดค้างชำระ",
    "AVGBALANCE": "ยอดหนี้เฉลี่ย",
    "TOTALCOUNT": "จำนวนราย",
    "FOLID": "รหัสผู้ดูแล",
    "FOLNAME": "ชื่อผู้ดูแล",
    "ACCNO": "เลขที่สัญญา",
    "CUSID": "รหัสลูกค้า",
    "OLID": "สาขา",
    "STAT2": "สถานะลูกหนี้",
    "ACCSTAT": "สถานะสัญญา",
    "BAL": "ยอดหนี้คงเหลือ",
    "BALTAX": "ภาษีคงเหลือ",
    "CREDIT": "ยอดค้างชำระ",
    "INTEREST": "ดอกเบี้ยค้าง",
    "FDATE": "วันที่ติดตาม",
    "FDETAIL": "รายละเอียดการติดตาม",
    "FTime": "เวลา",
    "DUE_DATE": "วันนัดชำระ",
    "STATUS1": "สถานะ 1",
    "STATUS2": "สถานะ 2",
    "EMPID": "รหัสพนักงาน",
    "MTH": "เดือน",
    "YRS": "ปี",
    "SECTION": "หมวดหมู่",
    "SUCCESSCOUNT": "ติดต่อได้ (สำเร็จ)",
    "FAILCOUNT": "ติดต่อไม่ได้",
    "TOTALCOUNT": "รวมติดตามทั้งหมด",
}

_AGG_KEYS = frozenset(
    {
        "TOTALCONTRACTS",
        "TOTALBALANCE",
        "TOTALCOUNT",
        "TOTALVAT",
        "TOTALINTEREST",
        "TOTALCREDIT",
    }
)

_NUMERIC_KEYS = frozenset(
    {
        "TOTALBALANCE",
        "TOTALVAT",
        "TOTALINTEREST",
        "TOTALCREDIT",
        "BAL",
        "INTEREST",
        "CREDIT",
    }
)
_SUM_KEYS = frozenset(
    {"TOTALBALANCE", "BAL", "TOTALINTEREST", "INTEREST", "CREDIT", "TOTALCREDIT"}
)


class AnalysisEngine:

    # Keep original-case map as public attr for backward compat
    COLUMN_LABEL_MAP = {
        k.title().replace("total", "Total").replace("avg", "Avg"): v
        for k, v in _COLUMN_LABEL_MAP.items()
    }

    def _get_label(self, key: str, schema: Dict[str, Any]) -> str:
        key_u = key.upper()
        if key_u in _COLUMN_LABEL_MAP:
            return _COLUMN_LABEL_MAP[key_u]
        for table in ("LSM010", "LSM008", "LSM007"):
            col_info = schema.get(table, {}).get("columns", {}).get(key, {})
            if not col_info:
                # case-insensitive fallback
                for col_name, col_data in (
                    schema.get(table, {}).get("columns", {}).items()
                ):
                    if col_name.upper() == key_u:
                        return col_data.get("desc", key).split("(")[0].strip()
            else:
                return col_info.get("desc", key).split("(")[0].strip()
        return key

    def _translate_value(self, key: str, val: Any, schema: Dict[str, Any]) -> str:
        if val is None or val == "":
            return "-"
        for table in ("LSM010", "LSM007"):
            options = (
                schema.get(table, {}).get("columns", {}).get(key, {}).get("options")
            )
            if options and str(val) in options:
                return options[str(val)]
        return str(val)

    def format_db_results(
        self, results: List[Dict[str, Any]], schema: Dict[str, Any], question: str = ""
    ) -> str:
        if not results:
            return "ไม่พบข้อมูลที่ต้องการในระบบ"

        from core.pipeline import pipeline

        results = pipeline.run(results)

        # ── Data Sampling Logic ────────────────────────────────────────────────
        # ถ้าเป็นข้อมูลประวัติ (History) หรือจำนวนเยอะมาก ให้ลดจำนวนที่ส่งไป AI
        # เพื่อป้องกัน LLM Timeout หรือ Context Overflow
        limit = 100
        is_crm_log = any(k.upper() in ("FDATE", "FDETAIL", "STATUS1") for k in results[0].keys())
        
        if is_crm_log:
            # CRM Log → เอาแค่ 15 รายการล่าสุด เพื่อป้องกัน LLM timeout
            limit = 15
            logger.info("Formatter: CRM Log detected, sampling top %d rows", limit)
            # ตัด column ที่ไม่จำเป็นออกเพื่อลด context size
            _CRM_DROP_COLS = {"MTH", "YRS", "NUM", "EMPID", "FTIME"}
            results = [
                {k: v for k, v in row.items() if k.upper() not in _CRM_DROP_COLS}
                for row in results
            ]

        sample = results[:limit]
        keys = list(sample[0].keys())
        headers = [self._get_label(k, schema) for k in keys]

        # ── Advanced Sectional Formatting ───────────────────────────────
        # ถ้ามีคอลัมน์ Section/หมวดหมู่ ให้ใช้ format ที่ AI อ่านแล้วไม่หลงคอลัมน์
        has_section = any(k.upper() in ("SECTION", "หมวดหมู่") for k in keys)
        
        if has_section:
            sections = []
            for row in sample:
                section_name = str(row.get("Section") or row.get("หมวดหมู่") or "ข้อมูล")
                details = []
                for k in keys:
                    if k.upper() in ("SECTION", "หมวดหมู่"): continue
                    val = self._translate_value(k, row[k], schema)
                    if val is None or str(val).upper() == "NULL": continue
                    
                    label = self._get_label(k, schema)
                    # Format money
                    if k.upper() in _NUMERIC_KEYS and isinstance(row[k], (int, float)):
                        val = f"{row[k]:,.2f} บาท"
                    
                    v_str = str(val).replace("\n", " ").strip()
                    if len(v_str) > 200: v_str = v_str[:197] + "..."
                    details.append(f"- {label}: {v_str}")
                
                sections.append(f"### {section_name}\n" + "\n".join(details))
            
            ctx = "\n\n".join(sections)
        else:
            # ── Standard Table Formatting ───────────────────────────────
            lines = [
                "| " + " | ".join(headers) + " |",
                "|" + "|".join(["---"] * len(headers)) + "|",
            ]
            for row in sample:
                cells = []
                for k in keys:
                    v = self._translate_value(k, row[k], schema)
                    raw = row[k]
                    if k.upper() in _NUMERIC_KEYS and isinstance(raw, (int, float)):
                        v = f"{raw:,.2f} บาท"
                    
                    v_str = str(v).replace("\n", " ").replace("\r", " ").replace("|", "\\|").strip()
                    if len(v_str) > 200: v_str = v_str[:197] + "..."
                    cells.append(v_str)
                lines.append("| " + " | ".join(cells) + " |")
            ctx = "\n".join(lines)

        if len(results) > limit:
            ctx += f"\n\n*... (และข้อมูลส่วนที่เหลืออีก {len(results) - limit} รายการ ถูกตัดออกเพื่อความเร็ว)*"
        
        return ctx

    def get_summary_stats(self, results: List[Dict[str, Any]]) -> str:
        if not results:
            return "ไม่พบข้อมูลที่เกี่ยวข้องในระบบ"

        count = len(results)

        if count == 1:
            row = results[0]
            items = []
            for k, v in row.items():
                if k.upper() in _AGG_KEYS:
                    label = _COLUMN_LABEL_MAP.get(k.upper(), k)
                    fmt = f"{v:,.2f}" if k.upper() in _NUMERIC_KEYS else str(v)
                    items.append(f"{label}: {fmt}")
            if items:
                return "สรุปภาพรวม: " + " | ".join(items)

        stats: List[str] = [f"พบข้อมูลทั้งหมด: {count} รายการ"]
        if count > 1:
            sums: Dict[str, float] = {}
            for row in results:
                for k, v in row.items():
                    if k.upper() in _SUM_KEYS and isinstance(v, (int, float)):
                        sums[k] = sums.get(k, 0.0) + v
            for k, total in sums.items():
                if total > 0:
                    label = _COLUMN_LABEL_MAP.get(k.upper(), k)
                    stats.append(f"ผลรวม {label}: {total:,.2f}")

        return " | ".join(stats)


# Singleton (instantiated once — ไม่ซ้ำแล้ว)
engine = AnalysisEngine()