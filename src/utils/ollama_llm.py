"""
Ollama LLM wrapper for PKM components that need a .generate() async interface.

Used by EntityExtractor, FactExtractor, and other modules that accept an optional
LLM parameter with the signature: await llm.generate(prompt, max_tokens=...) -> str
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class OllamaLLM:
    """Async LLM interface wrapping Ollama's /api/generate endpoint."""

    def __init__(
        self,
        model: Optional[str] = None,
        host: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:32b")
        self.host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.timeout = timeout

    async def generate(self, prompt: str, max_tokens: int = 1000) -> str:
        """Generate text from a prompt via Ollama's /api/generate endpoint."""
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": max_tokens},
                },
            )
            resp.raise_for_status()
            return resp.json().get("response", "")
