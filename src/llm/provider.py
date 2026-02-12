"""
Multi-LLM Provider abstraction for CoreRag.

Unified async interface for Ollama, Gemini, and Anthropic Claude.
Provider selection via CORERAG_LLM_PROVIDER env var, with auto-detection
fallback (Gemini if GOOGLE_API_KEY set, else Ollama).

Usage:
    from src.llm.provider import get_default_provider

    provider = get_default_provider()
    result = await provider.generate("Be helpful.", "What is Python?")
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import httpx

from src.config import GOOGLE_API_KEY, OLLAMA_HOST, OLLAMA_MODEL
from src.exceptions import ProcessingError
from src.utils.retry import RetryStrategies, with_retry

logger = logging.getLogger(__name__)

# ── Provider defaults ─────────────────────────────────────────────────────────

_PROVIDER_DEFAULTS: dict[str, str] = {
    "ollama": "qwen2.5:32b",
    "gemini": "gemini-2.0-flash",
    "anthropic": "claude-sonnet-4-20250514",
}


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class LLMConfig:
    """Configuration for an LLM provider."""

    provider: str  # "ollama", "gemini", "anthropic"
    model: str
    temperature: float = 0.1
    max_tokens: int = 1024
    timeout: float = 300.0


# ── Abstract base ─────────────────────────────────────────────────────────────


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    All methods are async. Implementations handle their own
    connection management, retry logic, and error translation.
    """

    def __init__(self, config: LLMConfig):
        self.config = config

    @abstractmethod
    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate text from system + user prompts.

        Args:
            system_prompt: System/role instructions
            user_prompt: User message / document content

        Returns:
            Generated text response

        Raises:
            ProcessingError: If generation fails after retries
        """
        ...

    @property
    def provider_name(self) -> str:
        return self.config.provider

    @property
    def model_name(self) -> str:
        return self.config.model


# ── Concrete providers ────────────────────────────────────────────────────────


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider (default)."""

    def __init__(self, config: LLMConfig, host: str = "http://localhost:11434"):
        super().__init__(config)
        self.host = host
        self.num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
        self.num_predict = config.max_tokens

    @with_retry(**RetryStrategies.ollama_call())
    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        prompt = f"{system_prompt}\n\n{user_prompt}" if system_prompt else user_prompt
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.config.timeout)) as client:
            resp = await client.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.config.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_ctx": self.num_ctx,
                        "num_predict": self.num_predict,
                        "temperature": self.config.temperature,
                    },
                },
            )
            resp.raise_for_status()
            return resp.json().get("response", "")


class GeminiProvider(LLMProvider):
    """Google Gemini API provider."""

    def __init__(self, config: LLMConfig, api_key: str):
        super().__init__(config)
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self._genai = genai

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        model = self._genai.GenerativeModel(
            self.config.model,
            system_instruction=system_prompt if system_prompt else None,
        )
        response = await asyncio.to_thread(model.generate_content, user_prompt)
        return response.text


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    def __init__(self, config: LLMConfig, api_key: str):
        super().__init__(config)
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        message = await self._client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=system_prompt if system_prompt else "",
            messages=[{"role": "user", "content": user_prompt}],
            temperature=self.config.temperature,
        )
        return message.content[0].text  # type: ignore[union-attr]


# ── Factory ───────────────────────────────────────────────────────────────────


def create_llm_provider(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs: object,
) -> LLMProvider:
    """Factory function to create an LLM provider.

    Args:
        provider: Provider name ("ollama", "gemini", "anthropic").
                  Defaults to CORERAG_LLM_PROVIDER env var, then auto-detection.
        model: Model name. Defaults to CORERAG_LLM_MODEL env var,
               then provider-specific default.
        **kwargs: Additional config (temperature, max_tokens, timeout, host, api_key).
    """
    # Resolve provider
    if provider is None:
        provider = os.getenv("CORERAG_LLM_PROVIDER", "").lower()
    if not provider:
        # Auto-detect: Gemini if key present, else Ollama
        if GOOGLE_API_KEY:
            provider = "gemini"
        else:
            provider = "ollama"

    # Resolve model
    if model is None:
        model = os.getenv("CORERAG_LLM_MODEL", "")
    if not model:
        model = _PROVIDER_DEFAULTS.get(provider, "")
        if provider == "ollama":
            model = OLLAMA_MODEL  # Respect legacy env var

    config = LLMConfig(
        provider=provider,
        model=model,
        temperature=float(kwargs.get("temperature", 0.1)),  # type: ignore[arg-type]
        max_tokens=int(kwargs.get("max_tokens", 1024)),  # type: ignore[call-overload]
        timeout=float(kwargs.get("timeout", 300.0)),  # type: ignore[arg-type]
    )

    if provider == "ollama":
        host = str(kwargs.get("host", "")) or OLLAMA_HOST
        return OllamaProvider(config, host=host)

    elif provider == "gemini":
        api_key = str(kwargs.get("api_key", "")) or GOOGLE_API_KEY
        if not api_key:
            raise ProcessingError("GOOGLE_API_KEY required for Gemini provider")
        return GeminiProvider(config, api_key=api_key)

    elif provider == "anthropic":
        api_key = str(kwargs.get("api_key", "")) or os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ProcessingError("ANTHROPIC_API_KEY required for Anthropic provider")
        return AnthropicProvider(config, api_key=api_key)

    else:
        raise ProcessingError(f"Unknown LLM provider: {provider}")


# ── Singleton ─────────────────────────────────────────────────────────────────

_default_provider: Optional[LLMProvider] = None


def get_default_provider() -> LLMProvider:
    """Get or create the default LLM provider (cached singleton)."""
    global _default_provider
    if _default_provider is None:
        _default_provider = create_llm_provider()
        logger.info(
            f"LLM provider initialized: {_default_provider.provider_name}"
            f" ({_default_provider.model_name})"
        )
    return _default_provider


def reset_default_provider() -> None:
    """Reset the cached singleton (for testing)."""
    global _default_provider
    _default_provider = None
