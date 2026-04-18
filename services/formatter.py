import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class AnalysisEngine:
    # Map technical aliases to friendly Thai labels (FALLBACKS)
    COLUMN_LABEL_MAP: Dict[str, str] = {
        "TotalContracts": "จำนวนสัญญา",
        "TotalBalance": "รวมยอดหนี้ (ไม่รวม VAT)",
        "TotalVAT": "รวมภาษี (VAT)",
        "TotalInterest": "รวมดอกเบี้ยค้าง",
        "TotalCredit": "รวมยอดค้างชำระ",
        "AvgBalance": "ยอดหนี้เฉลี่ย",
        "TotalCount": "จำนวนราย",
        "FolID": "รหัสผู้ดูแล",
        "FolName": "ชื่อผู้ดูแล",
        "AccNo": "เลขที่สัญญา",
        "CusId": "รหัสลูกค้า",
        "OLID": "สาขา",
        "Stat2": "สถานะลูกหนี้",
        "AccStat": "สถานะสัญญา",
        "Bal": "ยอดหนี้คงเหลือ",
        "BalTax": "ภาษีคงเหลือ",
        "Credit": "ยอดค้างชำระ",
        "Interest": "ดอกเบี้ยค้าง",
    }

    def _get_label(self, key: str, schema: Dict[str, Any]) -> str:
        """Helper to get Thai label for a key using Schema or Fallback Map."""
        # Normalize key for lookup
        key_upper = key.upper()
        
        # 1. Look in Static Map (PRIORITY) - Case-insensitive lookup
        map_upper = {k.upper(): v for k, v in self.COLUMN_LABEL_MAP.items()}
        if key_upper in map_upper:
            return map_upper[key_upper]
            
        # 2. Look in Schema Metadata (Desc) as fallback
        for table_name in ["LSM010", "LSM008", "LSM007"]:
            table_info = schema.get(table_name, {})
            cols = table_info.get("columns", {})
            # Look for case-insensitive match in schema columns
            for col_name, col_data in cols.items():
                if col_name.upper() == key_upper:
                    desc = col_data.get("desc", "")
                    clean_desc = desc.split("(")[0].strip()
                    return clean_desc
        
        return key

    def _translate_value(self, key: str, val: Any, schema: Dict[str, Any]) -> str:
        """Helper to translate codes (A, B, F, 1, 2) to Thai descriptions."""
        if val is None or val == "":
            return "-"
        
        # Look for options in Schema metadata
        for table_name in ["LSM010", "LSM007"]:
            table_info = schema.get(table_name, {})
            col_info = table_info.get("columns", {}).get(key, {})
            options = col_info.get("options")
            if options and str(val) in options:
                return options[str(val)]
        
        return str(val)

    def format_db_results(self, results: List[Dict[str, Any]], schema: Dict[str, Any], question: str = "") -> str:
        """Formats raw database rows into a human-readable text block for the LLM."""
        if not results:
            return "ไม่พบข้อมูลที่ต้องการในระบบ"
        
        # Data Pipeline: แปลงข้อมูล (Rounding/Masking)
        from core.pipeline import pipeline
        results = pipeline.run(results)
        
        sample = results[:100]
        lines: List[str] = []
        
        if sample:
            keys = list(sample[0].keys())
            # Create Markdown Table Header (Translate to Thai)
            headers = [self._get_label(k, schema) for k in keys]
            lines.append("| " + " | ".join(headers) + " |")
            
            # Create Markdown Separator
            lines.append("|" + "|".join(["---"] * len(headers)) + "|")
            
            # Add data rows
            for row in sample:
                row_values = []
                for k in keys:
                    v = row[k]
                    # Translate codes (e.g., F -> บอกเลิก 35 วัน)
                    translated_v = self._translate_value(k, v, schema)
                    
                    # Clean data for Markdown
                    clean_v = str(translated_v).replace("\n", " ").replace("\r", "").replace("|", "\\|").strip()
                    row_values.append(clean_v)
                
                lines.append("| " + " | ".join(row_values) + " |")
        
        context = "\n".join(lines)
        if len(results) > 100:
            context += f"\n\n*... (และข้อมูลส่วนที่เหลืออีก {len(results) - 100} รายการ)*"
        
        return context

    def get_summary_stats(self, results: List[Dict[str, Any]]) -> str:
        """Generates basic statistics about the result set."""
        if not results:
            return "ไม่พบข้อมูลที่เกี่ยวข้องในระบบ"
        
        count = len(results)
        
        if count == 1:
            row = results[0]
            agg_items = []
            for k, v in row.items():
                if k in ["TotalContracts", "TotalBalance", "TotalCount", "TotalVAT", "TotalInterest", "TotalCredit"]:
                    val = v if v is not None else 0
                    label = self.COLUMN_LABEL_MAP.get(k, k)
                    formatted_val = f"{val:,.2f}" if any(x in k for x in ["Balance", "VAT", "Interest", "Credit"]) else str(val)
                    agg_items.append(f"{label}: {formatted_val}")
            
            if agg_items:
                return "สรุปภาพรวม: " + " | ".join(agg_items)

        stats: List[str] = [f"พบข้อมูลทั้งหมด: {count} รายการ"]
        
        if count > 1:
            numeric_sums: Dict[str, float] = {}
            for row in results:
                for k, v in row.items():
                    if k in ["TotalBalance", "Bal", "TotalInterest", "Interest", "Credit", "TotalCredit"]:
                        if isinstance(v, (int, float)):
                            numeric_sums[k] = numeric_sums.get(k, 0) + v
            
            for k, total in numeric_sums.items():
                if total > 0:
                    label = self.COLUMN_LABEL_MAP.get(k, k)
                    stats.append(f"ผลรวม {label}: {total:,.2f}")
                    
        return " | ".join(stats)

engine = AnalysisEngine()

engine = AnalysisEngine()
