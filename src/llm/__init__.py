"""LLM Provider abstraction for CoreRag.

Supports Ollama (local, default), Google Gemini, and Anthropic Claude
with a unified async interface.
"""

from src.llm.provider import LLMProvider, create_llm_provider, get_default_provider

__all__ = ["LLMProvider", "create_llm_provider", "get_default_provider"]
