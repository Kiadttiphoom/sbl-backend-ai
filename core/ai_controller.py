import json
import logging
import time
from typing import AsyncGenerator, Dict, Any, List

from core.intent import detect_intent
from security.injection import detect_prompt_injection
from security.business_rules import validate_business_logic
from db.templates import render_query, SQL_TEMPLATES
from db.fetch import fetch_data
from services.formatter import engine
from llm.ollama_client import OllamaClient
from config import MODEL_NAME
from skills.registry import execute_skill
from core.exceptions import SecurityError, SBLError

logger = logging.getLogger(__name__)

class AIController:
    """
    The Main Brain of the Agent.
    Replaces the scattered pipelines in ask_service.py.
    """
    def __init__(self, ollama: OllamaClient, schema: Dict[str, Any]):
        self.ollama = ollama
        self.schema = schema

    def _event(self, type_: str, **kwargs: Any) -> str:
        """Helper for SSE formatting."""
        return json.dumps({"type": type_, **kwargs}, ensure_ascii=False) + "\n"

    async def _decide_sql_template(self, q: str) -> Dict[str, Any]:
        """
        Uses the LLM to choose the correct SQL template and extract parameters.
        Returns a dictionary: {"template_name": "...", "params": {...}}
        """
        # Prompt the 7B model to output JSON only
        template_list = "\n".join([f"- {k}" for k in SQL_TEMPLATES.keys()])
        prompt = f"""
Choose the correct SQL template for this question based on these options:
{template_list}

Question: "{q}"

Output ONLY a raw JSON object with the keys "template_name" and "params". 
For example: {{"template_name": "PAID_UP_LIST", "params": {{"branch_code": "AA"}}}}
If you cannot find a matching template, output {{"template_name": "UNKNOWN", "params": {{}}}}
        """
        # We use a non-streaming basic call for classification
        try:
            res_text = await self.ollama.generate(prompt, tokens=100, temperature=0.1)
            # Find JSON boundaries just in case it added Markdown
            START = res_text.find('{')
            END = res_text.rfind('}')
            if START != -1 and END != -1:
                return json.loads(res_text[START:END+1])
            return {"template_name": "UNKNOWN", "params": {}}
        except Exception as e:
            logger.error(f"Template decision failed: {e}")
            return {"template_name": "UNKNOWN", "params": {}}

    async def process_request(self, q: str, history: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        start_time = time.time()
        
        try:
            # 1. Security First
            yield self._event("status", content="ตรวจสอบข้อจำกัดด้านความปลอดภัย...")
            injected, pattern = detect_prompt_injection(q)
            if injected:
                raise SecurityError("คำถามไม่ผ่านการตรวจสอบความปลอดภัย", details=pattern)

            # 2. Intent Analysis
            yield self._event("status", content="กำลังวิเคราะห์คำถามด้วยสมองส่วนกลาง...")
            intent_res = detect_intent(q, history)
            intent = intent_res["intent"]
            yield self._event("intent", intent=intent, confidence=intent_res["confidence"])

            context_str = ""
            stats_str = ""
            db_results = []
            
            # 3. Routing (The Core Router)
            if intent == "DATA_QUERY":
                yield self._event("status", content="กำลังดึงข้อมูลด้วย Template ที่ปลอดภัย...")
                decision = await self._decide_sql_template(q)
                template_name = decision.get("template_name", "UNKNOWN")
                params = decision.get("params", {})
                
                if template_name != "UNKNOWN" and template_name in SQL_TEMPLATES:
                    # RENDER TEMPLATE
                    sql, _ = render_query(template_name, params)
                    yield self._event("sql", sql=sql)
                    
                    # RUN DB
                    try:
                        db_results = fetch_data(sql)
                        if db_results:
                            yield self._event("data_count", count=len(db_results))
                            context_str = engine.format_db_results(db_results, self.schema, question=q)
                            stats_str = engine.get_summary_stats(db_results)
                        else:
                            context_str = "ไม่มีข้อมูลจากฐานข้อมูล"
                    except Exception as e:
                        logger.error(f"Database template execution error: {e}")
                        context_str = f"เกิดข้อผิดพลาดในการดึงข้อมูล: {e}"
                else:
                    # Fallback if no template matches
                    yield self._event("status", content="ค้นหาข้อมูลจากทักษะเสริม (Skill Engine)...")
                    skill_res = execute_skill("search-data", q)
                    context_str = str(skill_res)
                    yield self._event("content", content=f"(ใช้ Skill fallback)\n{context_str}\n")
                    yield self._event("done", time=round(time.time() - start_time, 2))
                    return

            # 4. Final Insight Generation
            yield self._event("status", content="กำลังสรุปคำตอบ...")
            
            sys_msg = "คุณคือ AI ผู้ช่วยวิเคราะห์ข้อมูล"
            if context_str:
                sys_msg += f"\nคุณได้รับข้อมูลตารางแล้ว ห้ามก็อปปี้ตาราง ให้วิเคราะห์จากข้อมูลนี้:\n{context_str}\nสถิติ:{stats_str}"
                
            messages = [{"role": "system", "content": sys_msg}] + history + [{"role": "user", "content": q}]
            
            async for chunk in self.ollama.chat_stream(messages, model=MODEL_NAME):
                yield self._event("content", content=chunk)

            yield self._event("done", time=round(time.time() - start_time, 2))

        except SecurityError as e:
            yield self._event("error", content=f"⚠️ ระงับการค้นหา: {e.message}")
        except SBLError as e:
            yield self._event("error", content=f"❌ เกิดข้อผิดพลาด: {e.message}")
        except Exception as e:
            logger.error(f"AI Controller Crash: {e}")
            yield self._event("error", content="ผมเผชิญปัญหาระบบขัดข้องครับ โปรดลองใหม่อีกครั้ง")
