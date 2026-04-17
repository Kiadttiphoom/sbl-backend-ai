import json

class AnalysisEngine:
    # Map technical aliases to friendly Thai labels
    COLUMN_LABEL_MAP = {
        "TotalContracts": "จำนวนสัญญา",
        "TotalBalance": "รวมยอดหนี้",
        "TotalVAT": "รวมภาษี (VAT)",
        "TotalInterest": "รวมดอกเบี้ยค้าง",
        "TotalCredit": "รวมยอดค้างชำระ",
        "AvgBalance": "ยอดหนี้เฉลี่ย",
        "TotalCount": "จำนวนราย",
        "FolID": "รหัสพนักงาน",
        "FolName": "ชื่อพนักงาน",
    }

    def format_db_results(self, results, schema, question=""):
        """Formats raw database rows into a human-readable text block for the LLM."""
        if not results:
            return "ไม่พบข้อมูลที่ต้องการในระบบ"
        
        # Data Pipeline: แปลงข้อมูล (Rounding/Masking) ก่อนนำไปแสดงผล
        from core.pipeline import pipeline
        results = pipeline.run(results)
        
        # Take up to top 100 rows to ensure complete data visibility
        sample = results[:100]
        
        lines = []
        if sample:
            # Create Markdown Table Header
            headers = [self.COLUMN_LABEL_MAP.get(k, k) for k in sample[0].keys()]
            lines.append("| " + " | ".join(headers) + " |")
            
            # Create Markdown Separator (---|---|---)
            lines.append("|" + "|".join(["---"] * len(headers)) + "|")
            
            # Add data rows
            for row in sample:
                row_values = [str(v) for v in row.values()]
                lines.append("| " + " | ".join(row_values) + " |")
        
        context = "\n".join(lines)
        # Indicate truncation only if necessary
        if len(results) > 100:
            context += f"\n\n*... (และข้อมูลส่วนที่เหลืออีก {len(results) - 100} รายการ)*"
        
        return context

    def get_summary_stats(self, results):
        """Generates basic statistics about the result set."""
        if not results:
            return "จำนวนข้อมูล: 0 รายการ"
        
        count = len(results)
        stats = [f"พบข้อมูลทั้งหมด: {count} รายการ"]
        
        # Simple aggregation for numeric columns if multiple rows
        if count > 1:
            numeric_sums = {}
            for row in results:
                for k, v in row.items():
                    if isinstance(v, (int, float)):
                        numeric_sums[k] = numeric_sums.get(k, 0) + v
            
            for k, total in numeric_sums.items():
                if total > 0:
                    label = self.COLUMN_LABEL_MAP.get(k, k)
                    stats.append(f"ผลรวม {label}: {total:,.2f}")
                    
        return " | ".join(stats)

engine = AnalysisEngine()
