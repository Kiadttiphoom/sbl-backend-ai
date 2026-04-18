import json
import logging
import time
from typing import AsyncGenerator, Dict, Any, List

from core.intent import detect_intent
from security.injection import detect_prompt_injection
from security.business_rules import validate_business_logic
from db.templates import SQL_TEMPLATES, TEMPLATE_DESCRIPTIONS, TEMPLATE_EXAMPLES, render_query, get_category_list, get_templates_by_category, TEMPLATE_CATEGORIES
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

    async def _detect_category(self, q: str) -> str:
        """
        Detect which category the question belongs to.
        Returns category name (branch, delinquency, contract, payment, employee, accounting, legal, risk, other)
        """
        categories = get_category_list()
        prompt = f"""
Classify this question into ONE of these categories:
{categories}

Question: "{q}"

Respond with ONLY the category name in lowercase. Example responses: "branch", "delinquency", "payment"
If unsure, respond with "other"
        """
        try:
            res_text = await self.ollama.generate(prompt, tokens=20, temperature=0.1)
            category = res_text.strip().lower().split()[0]  # Get first word
            return category if category in ["branch", "delinquency", "contract", "payment", "employee", "accounting", "legal", "risk"] else "other"
        except Exception as e:
            logger.warning(f"Category detection failed: {e}, defaulting to 'other'")
            return "other"

    async def _decide_sql_template(self, q: str) -> Dict[str, Any]:
        """
        Uses the LLM to choose the correct SQL template and extract parameters.
        First detects category, then filters templates by that category.
        Returns a dictionary: {"template_name": "...", "params": {...}}
        """
        # Step 1: Detect category to filter templates
        category = await self._detect_category(q)
        logger.info(f"📂 Detected category: {category}")
        
        # Step 2: Get templates for this category
        category_templates = get_templates_by_category(category)
        if not category_templates:
            logger.warning(f"⚠️ No templates for category '{category}', using all templates")
            category_templates = SQL_TEMPLATES
        
        # Step 3: Build prompt with only relevant templates
        template_info_list = []
        for template_name in category_templates.keys():
            desc = TEMPLATE_DESCRIPTIONS.get(template_name, "")
            examples = TEMPLATE_EXAMPLES.get(template_name, [])
            example_str = f"\n  Example: {examples[0]}" if examples else ""
            template_info_list.append(f"- {template_name}: {desc}{example_str}")
        
        template_list = "\n".join(template_info_list)
        
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
                    logger.info(f"📊 Template: {template_name}")
                    logger.info(f"🔍 SQL Query: {sql}")
                    logger.info(f"📋 Parameters: {params}")
                    yield self._event("sql", sql=sql)
                    
                    # RUN DB
                    try:
                        db_results = fetch_data(sql)
                        if db_results:
                            logger.info(f"✅ ได้ข้อมูล: {len(db_results)} แถว")
                            yield self._event("data_count", count=len(db_results))
                            context_str = engine.format_db_results(db_results, self.schema, question=q)
                            stats_str = engine.get_summary_stats(db_results)
                        else:
                            logger.warning(f"⚠️  ไม่พบข้อมูลจาก SQL query")
                            context_str = "ไม่มีข้อมูลจากฐานข้อมูล"
                    except Exception as e:
                        logger.error(f"❌ Database template execution error: {e}")
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
            logger.info(f"🤖 AI ผู้ช่วยสร้างคำตอบ...")
            
            sys_msg = "คุณคือ AI ผู้ช่วยวิเคราะห์ข้อมูล"
            if context_str:
                logger.info(f"📊 Context ที่ส่งให้ AI:\n{context_str[:300]}...")
                sys_msg += f"\nคุณได้รับข้อมูลตารางแล้ว ห้ามก็อปปี้ตาราง ให้วิเคราะห์จากข้อมูลนี้:\n{context_str}\nสถิติ:{stats_str}"
            else:
                logger.warning(f"⚠️ context_str ว่างเปล่า! ไม่มีข้อมูลที่ส่งให้ AI")
                
            messages = [{"role": "system", "content": sys_msg}] + history + [{"role": "user", "content": q}]
            
            response_text = ""
            async for chunk in self.ollama.chat_stream(messages, model=MODEL_NAME):
                response_text += chunk
                yield self._event("content", content=chunk)
            
            logger.info(f"💬 AI ตอบมา: {response_text[:100]}...") if len(response_text) > 100 else logger.info(f"💬 AI ตอบมา: {response_text}")
            yield self._event("done", time=round(time.time() - start_time, 2))

        except SecurityError as e:
            yield self._event("error", content=f"⚠️ ระงับการค้นหา: {e.message}")
        except SBLError as e:
            yield self._event("error", content=f"❌ เกิดข้อผิดพลาด: {e.message}")
        except Exception as e:
            logger.error(f"AI Controller Crash: {e}")
            yield self._event("error", content="ผมเผชิญปัญหาระบบขัดข้องครับ โปรดลองใหม่อีกครั้ง")
