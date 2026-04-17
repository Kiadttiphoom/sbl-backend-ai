import httpx
import json
import asyncio
import logging
from typing import Optional, List, Dict
from config import OLLAMA_ENDPOINT_1, OLLAMA_ENDPOINT_2, MODEL_NAME, SQL_MODEL, LLM_TIMEOUT

logger = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF  = [1.0, 2.0, 4.0]


class OllamaClient:

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=LLM_TIMEOUT)

    async def generate(self, prompt: str, tokens: int = 300, model: Optional[str] = None, temperature: float = 0.3, top_p: float = 0.9, top_k: int = 40, repeat_penalty: float = 1.1) -> str:
        """Non-streaming generate พร้อม retry — model และ parameters override ได้"""
        payload = {
            "model":   model or MODEL_NAME,
            "prompt":  prompt,
            "stream":  False,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "repeat_penalty": repeat_penalty,
                "stop": ["\n\nUser:", "用户:", "Assistant:"],
                "num_predict": tokens
            }
        }

        last_error: Optional[Exception] = None

        for attempt in range(_RETRY_ATTEMPTS):
            try:
                r = await self.client.post(OLLAMA_ENDPOINT_1, json=payload)
                r.raise_for_status()
                response_text = r.json().get("response", "")
                logger.debug("LLM generate OK model=%s (attempt %d)", payload["model"], attempt + 1)
                return response_text

            except httpx.HTTPStatusError as e:
                logger.warning("LLM HTTP error %s (attempt %d)", e.response.status_code, attempt + 1)
                last_error = e
                if e.response.status_code < 500:
                    break

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning("LLM connection error: %s (attempt %d)", e, attempt + 1)
                last_error = e

            if attempt < _RETRY_ATTEMPTS - 1:
                await asyncio.sleep(_RETRY_BACKOFF[attempt])

        raise RuntimeError(f"LLM unavailable after {_RETRY_ATTEMPTS} attempts: {last_error}")

    async def stream(self, prompt: str, model: Optional[str] = None, tokens: int = 500, stop: Optional[List[str]] = None, temperature: float = 0.3, top_p: float = 0.8, top_k: int = 40, repeat_penalty: float = 1.1):
        """Streaming generate — yield tokens ทีละตัว"""
        payload = {
            "model":   model or MODEL_NAME,
            "prompt":  prompt,
            "stream":  True,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "repeat_penalty": repeat_penalty,
                "stop": stop or ["\n\nUser:", "用户:", "Assistant:", "<|endoftext|>", "###"],
                "num_predict": tokens
            }
        }

        for attempt in range(_RETRY_ATTEMPTS):
            try:
                async with self.client.stream("POST", OLLAMA_ENDPOINT_1, json=payload) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        try:
                            data  = json.loads(line)
                            token = data.get("response")
                            if token:
                                yield token
                            if data.get("done"):
                                return
                        except json.JSONDecodeError as e:
                            logger.debug("Stream JSON parse error (skipping line): %s", e)
                            continue
                return

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning("LLM stream error: %s (attempt %d)", e, attempt + 1)
                if attempt < _RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(_RETRY_BACKOFF[attempt])
                else:
                    raise RuntimeError(f"LLM stream unavailable: {e}") from e

            except httpx.HTTPStatusError as e:
                logger.error("LLM stream HTTP %s", e.response.status_code)
                raise

    async def chat_stream(self, messages: List[Dict], model: Optional[str] = None, tokens: int = 2000, temperature: float = 0.1):
        """Streaming chat — ใช้สำหรับ Insight / Conversation (ฉลาดกว่าเพราะมี Chat Template)"""
        url = OLLAMA_ENDPOINT_2
        payload = {
            "model": model or MODEL_NAME,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": tokens
            }
        }

        for attempt in range(_RETRY_ATTEMPTS):
            try:
                async with self.client.stream("POST", url, json=payload, timeout=LLM_TIMEOUT) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line: continue
                        data = json.loads(line)
                        if "message" in data:
                            yield data["message"].get("content", "")
                        if data.get("done"):
                            return
                return

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning("LLM chat_stream error: %s (attempt %d)", e, attempt + 1)
                if attempt < _RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(_RETRY_BACKOFF[attempt])
                else:
                    raise RuntimeError(f"LLM chat_stream unavailable: {e}") from e