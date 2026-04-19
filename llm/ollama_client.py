"""
Ollama Client
- generate() / stream()  → ENDPOINT_1
- chat_stream()          → ENDPOINT_2 (พร้อม fallback ไป ENDPOINT_1)
- Retry + exponential backoff ทั้งสาม method
- Fix: else ที่อยู่ใน except block เดิม → ย้ายออกมาถูกที่
"""

import httpx
import json
import asyncio
import logging
from typing import Optional, List, Dict, AsyncGenerator

from config import OLLAMA_ENDPOINT_1, OLLAMA_ENDPOINT_2, MODEL_NAME, SQL_MODEL, LLM_TIMEOUT
from core.exceptions import LLMError

logger = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF  = [1.0, 2.0, 4.0]


def _build_options(
    temperature: float,
    top_p: float,
    top_k: int,
    repeat_penalty: float,
    tokens: int,
    stop: Optional[List[str]] = None,
) -> dict:
    return {
        "temperature":    temperature,
        "top_p":          top_p,
        "top_k":          top_k,
        "repeat_penalty": repeat_penalty,
        "num_predict":    tokens,
        "stop":           stop or ["\n\nUser:", "用户:", "Assistant:"],
    }


class OllamaClient:

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=LLM_TIMEOUT)

    # ── Non-streaming generate ────────────────────────────────────────────────
    async def generate(
        self,
        prompt: str,
        tokens: int = 300,
        model: Optional[str] = None,
        temperature: float = 0.3,
        top_p: float = 0.9,
        top_k: int = 40,
        repeat_penalty: float = 1.1,
    ) -> str:
        payload = {
            "model":   model or MODEL_NAME,
            "prompt":  prompt,
            "stream":  False,
            "options": _build_options(temperature, top_p, top_k, repeat_penalty, tokens),
        }
        last_error: Optional[Exception] = None
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                r = await self.client.post(OLLAMA_ENDPOINT_1, json=payload)
                r.raise_for_status()
                return r.json().get("response", "")
            except httpx.HTTPStatusError as e:
                logger.warning("generate HTTP %s (attempt %d)", e.response.status_code, attempt + 1)
                last_error = e
                if e.response.status_code < 500:
                    break
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning("generate conn error: %s (attempt %d)", e, attempt + 1)
                last_error = e
            if attempt < _RETRY_ATTEMPTS - 1:
                await asyncio.sleep(_RETRY_BACKOFF[attempt])
        raise LLMError(f"Ollama ไม่พร้อมหลังพยายาม {_RETRY_ATTEMPTS} ครั้ง", details=str(last_error))

    # ── Streaming generate ────────────────────────────────────────────────────
    async def stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        tokens: int = 500,
        stop: Optional[List[str]] = None,
        temperature: float = 0.3,
        top_p: float = 0.8,
        top_k: int = 40,
        repeat_penalty: float = 1.1,
    ) -> AsyncGenerator[str, None]:
        payload = {
            "model":   model or MODEL_NAME,
            "prompt":  prompt,
            "stream":  True,
            "options": _build_options(
                temperature, top_p, top_k, repeat_penalty, tokens,
                stop=stop or ["\n\nUser:", "用户:", "Assistant:", "<|endoftext|>", "###"],
            ),
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
                        except json.JSONDecodeError:
                            continue
                return
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning("stream conn error: %s (attempt %d)", e, attempt + 1)
                if attempt < _RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(_RETRY_BACKOFF[attempt])
                else:
                    raise LLMError(f"Ollama Stream ขาดหาย: {e}") from e
            except httpx.HTTPStatusError as e:
                raise LLMError(f"Ollama ตอบ HTTP {e.response.status_code}") from e

    # ── Streaming chat ────────────────────────────────────────────────────────
    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        tokens: int = 2000,
        temperature: float = 0.1,
    ) -> AsyncGenerator[str, None]:
        """
        ใช้ ENDPOINT_2 เป็นหลัก  fallback ไป ENDPOINT_1 ถ้าเชื่อมต่อไม่ได้
        (Fix: else clause ที่อยู่ใน except block เดิม)
        """
        payload = {
            "model":    model or MODEL_NAME,
            "messages": messages,
            "stream":   True,
            "options":  {"temperature": temperature, "num_predict": tokens},
        }
        endpoints = [ep for ep in [OLLAMA_ENDPOINT_2, OLLAMA_ENDPOINT_1] if ep]
        last_error: Optional[Exception] = None

        for attempt in range(_RETRY_ATTEMPTS):
            url = endpoints[attempt % len(endpoints)]
            try:
                async with self.client.stream("POST", url, json=payload, timeout=LLM_TIMEOUT) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        if "message" in data:
                            yield data["message"].get("content", "")
                        if data.get("done"):
                            return
                return
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning("chat_stream error on %s: %s (attempt %d)", url, e, attempt + 1)
                last_error = e
                if attempt < _RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(_RETRY_BACKOFF[attempt])
            except httpx.HTTPStatusError as e:
                raise LLMError(f"Ollama Chat HTTP {e.response.status_code}") from e

        raise LLMError(f"Ollama Chat ไม่พร้อมหลังพยายาม {_RETRY_ATTEMPTS} ครั้ง", details=str(last_error))
