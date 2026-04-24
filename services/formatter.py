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

    # คอลัมน์ที่ถ้า NULL/empty = ไม่มีผู้รับผิดชอบ
    _UNASSIGNED_KEYS = frozenset({"FOLID", "FOL_ID", "EMPID", "EMP_ID"})

    def _translate_value(self, key: str, val: Any, schema: Dict[str, Any]) -> str:
        key_u = key.upper()

        # NULL / empty
        if val is None or (isinstance(val, str) and val.strip() == ""):
            if key_u in self._UNASSIGNED_KEYS:
                return "ไม่มีผู้ดูแล"
            return "-"
        
        val_str = str(val).strip()

        # Auto-format YYYYMMDD date strings (e.g., 20250422 -> 22/04/2025)
        if len(val_str) == 8 and val_str.isdigit() and val_str.startswith(("20", "25", "19")):
            try:
                y, m, d = val_str[:4], val_str[4:6], val_str[6:]
                if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
                    return f"{d}/{m}/{y}"
            except Exception:
                pass

        # DATA CLEANUP: ปรับปรุงข้อความให้อ่านง่ายขึ้น แต่คงเบอร์โทรไว้ตามต้องการ
        if key_u == "FDETAIL":
            val_str = val_str.replace("ผู้ซื้อ ไม่รับสาย", "ไม่รับสาย").replace("ไม่เปิดบริการ", "ปิดเครื่อง")

        for table in ("LSM010", "LSM007"):
            options = (
                schema.get(table, {}).get("columns", {}).get(key, {}).get("options")
            )
            if options and val_str in options:
                return options[val_str]
        return val_str

    def format_db_results(
        self, 
        results: List[Dict[str, Any]], 
        schema: Dict[str, Any], 
        question: str = "",
        intent: str = "DATA_QUERY"
    ) -> str:
        if not results:
            return "ไม่พบข้อมูลที่ต้องการในระบบ"

        from core.pipeline import pipeline
        results = pipeline.run(results)

        # ── Data Sampling Logic ────────────────────────────────────────────────
        limit = 100
        keys = list(results[0].keys())
        is_crm_log = any(k.upper() in ("FDATE", "FDETAIL", "STATUS1") for k in keys)
        has_section = any(k.upper() in ("SECTION", "หมวดหมู่") for k in keys)
        
        # Fast Advisory Mode: ถ้าเป็นการวิเคราะห์ ให้ตัดเอาเฉพาะสรุป (Section 1 & 2)
        if intent == "ADVISORY" and has_section:
            # เก็บเฉพาะสถิติ (1) และรายการสำคัญ (2) ตัดประวัติดิบ (3) ทิ้งเพื่อความเร็ว
            results = [r for r in results if str(r.get("Section") or "").startswith(("1", "2"))]
            limit = 20
            logger.info("Formatter: ADVISORY mode active, filtering for summary sections only")

        elif is_crm_log:
            # Standard CRM Log → เอาแค่ 15 รายการล่าสุด
            limit = 15
            logger.info("Formatter: CRM Log detected, sampling top %d rows", limit)
            _CRM_DROP_COLS = {"MTH", "YRS", "NUM", "EMPID", "FTIME"}
            results = [
                {k: v for k, v in row.items() if k.upper() not in _CRM_DROP_COLS}
                for row in results
            ]

        # Sort by Section if exists
        if has_section:
            results = sorted(results, key=lambda r: str(r.get("Section") or ""))
            
        sample = results[:limit]
        keys = list(sample[0].keys())
        headers = [self._get_label(k, schema) for k in keys]

        # ── HYBRID Formatting ───────────────────────────────
        if has_section:
            output_parts = []
            current_section = None
            section_rows = []

            for row in sample:
                sec = str(row.get("Section") or row.get("หมวดหมู่") or "ข้อมูล")
                if sec != current_section:
                    if section_rows:
                        # Format previous section
                        output_parts.append(self._format_section(current_section, section_rows, keys, schema))
                    current_section = sec
                    section_rows = [row]
                else:
                    section_rows.append(row)
            
            if section_rows:
                output_parts.append(self._format_section(current_section, section_rows, keys, schema))
            
            ctx = "\n\n".join(output_parts)
        elif len(sample) == 1 and len(keys) == 1:
            # ── Single Value Formatting — แสดงเป็นประโยคภาษาไทย ไม่โชว์ชื่อ column ──
            key = keys[0]
            raw_val = sample[0][key]
            key_u = key.upper()

            _COUNT_KEYS = frozenset({
                "TOTAL_COUNT", "TOTALCOUNT", "COUNT", "CNT",
                "NUM", "NUMROWS", "ROWCOUNT", "ROW_COUNT",
            })
            _MONEY_KEYS = frozenset({
                "TOTALBALANCE", "TOTAL_BALANCE", "TOTALCREDIT", "TOTAL_CREDIT",
                "TOTALINTEREST", "TOTAL_INTEREST", "TOTALVAT", "TOTAL_VAT",
                "BAL", "CREDIT", "INTEREST", "AMOUNT", "SUM",
            })

            if key_u in _COUNT_KEYS or "COUNT" in key_u or "CNT" in key_u:
                # นับจำนวน → "มีทั้งหมด X,XXX ราย"
                try:
                    n = int(raw_val)
                    ctx = f"มีทั้งหมด **{n:,} ราย**"
                except (TypeError, ValueError):
                    ctx = f"ผลลัพธ์: **{raw_val}**"
            elif key_u in _MONEY_KEYS or "BAL" in key_u or "AMOUNT" in key_u:
                # ยอดเงิน → "รวมทั้งสิ้น X,XXX.XX บาท"
                try:
                    ctx = f"รวมทั้งสิ้น **{float(raw_val):,.2f} บาท**"
                except (TypeError, ValueError):
                    ctx = f"ผลลัพธ์: **{raw_val}**"
            elif isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool):
                # ตัวเลขอื่นๆ → แสดงพร้อมหน่วยที่เหมาะสม
                try:
                    ctx = f"**{float(raw_val):,.2f}**"
                except Exception:
                    ctx = f"**{raw_val}**"
            else:
                ctx = f"**{raw_val}**"
        else:
            # ── Standard Table Formatting (Fallback) ───────────────────────────────
            lines = [
                "| " + " | ".join(headers) + " |",
                "|" + "|".join(["---"] * len(headers)) + "|",
            ]
            unassigned_count = 0
            for row in sample:
                cells = []
                row_has_no_owner = False
                for k in keys:
                    v = self._translate_value(k, row[k], schema)
                    raw = row[k]
                    if k.upper() in _NUMERIC_KEYS and isinstance(raw, (int, float)):
                        v = f"{raw:,.2f}"
                    if k.upper() in self._UNASSIGNED_KEYS and v == "ไม่มีผู้ดูแล":
                        row_has_no_owner = True
                    v_str = str(v).replace("\n", " ").replace("|", "\\|").strip()
                    if len(v_str) > 200: v_str = v_str[:197] + "..."
                    cells.append(v_str)
                lines.append("| " + " | ".join(cells) + " |")
                if row_has_no_owner:
                    unassigned_count += 1
            ctx = "\n".join(lines)
            # ⚠️ แจ้งเตือนถ้ามีสัญญาที่ไม่มีผู้รับผิดชอบ
            if unassigned_count > 0:
                ctx += f"\n\n> ⚠️ **พบ {unassigned_count} สัญญาที่ยังไม่มีผู้รับผิดชอบ** กรุณามอบหมายเจ้าหน้าที่ติดตามโดยด่วนครับ"

        if len(results) > limit:
            ctx += f"\n\n*... ยังมีข้อมูลการติดตามอื่นอีก {len(results) - limit} รายการ คุณสามารถสอบถามรายละเอียดเพิ่มเติมได้ครับ*"
        
        return ctx

    def _format_section(self, name: str, rows: List[Dict], keys: List[str], schema: Dict) -> str:
        """Helper to format a specific section as either a Table or a List."""
        # Cleanup name: "1_ล่าสุด_5_ครั้ง" -> "ล่าสุด 5 ครั้ง"
        import re
        clean_name = re.sub(r"^\d+_", "", name).replace("_", " ")
        
        # บังคับให้เป็นตารางสำหรับ Section 1, 2 หรือหัวข้อพวกประวัติ/สถิติ
        is_table = (
            name.startswith(("1", "2")) or 
            any(k in clean_name for k in ("สถิติ", "ประวัติ", "ล่าสุด"))
        )
        
        if is_table:
            headers = [self._get_label(k, schema) for k in keys if k.upper() not in ("SECTION", "หมวดหมู่")]
            lines = [
                f"### {clean_name}",
                "| " + " | ".join(headers) + " |",
                "|" + "|".join(["---"] * len(headers)) + "|",
            ]
            for r in rows:
                cells = []
                for k in keys:
                    if k.upper() in ("SECTION", "หมวดหมู่"): continue
                    val = self._translate_value(k, r[k], schema)
                    if k.upper() in _NUMERIC_KEYS and isinstance(r[k], (int, float)):
                        val = f"{r[k]:,.2f}"
                    v_str = str(val).replace("\n", " ").replace("|", "\\|").strip()
                    cells.append(v_str)
                lines.append("| " + " | ".join(cells) + " |")
            return "\n".join(lines)
        
        # Section อื่นๆ (เช่น Last Contact) ให้เป็น List เพื่อให้อ่านง่ายขึ้น
        items = [f"### {clean_name}"]
        for r in rows:
            details = []
            for k in keys:
                if k.upper() in ("SECTION", "หมวดหมู่"): continue
                val = self._translate_value(k, r[k], schema)
                if val is None or str(val).upper() == "NULL": continue
                label = self._get_label(k, schema)
                if k.upper() in _NUMERIC_KEYS and isinstance(r[k], (int, float)):
                    val = f"{r[k]:,.2f} บาท"
                v_str = str(val).replace("\n", " ").strip()
                if len(v_str) > 250: v_str = v_str[:247] + "..."
                details.append(f"- {label}: {v_str}")
            items.append("\n".join(details))
        return "\n\n".join(items)

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