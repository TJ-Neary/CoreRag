"""Tests for LLM Provider abstraction."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.exceptions import ProcessingError
from src.llm.provider import (
    AnthropicProvider,
    GeminiProvider,
    LLMConfig,
    OllamaProvider,
    create_llm_provider,
    get_default_provider,
    reset_default_provider,
)

# ── OllamaProvider Tests ─────────────────────────────────────────────────────


class TestOllamaProvider:
    @pytest.fixture
    def config(self):
        return LLMConfig(provider="ollama", model="qwen2.5:32b")

    async def test_generate_returns_response_text(self, config):
        provider = OllamaProvider(config)
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "Hello from Ollama"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await provider.generate("System", "User prompt")

        assert result == "Hello from Ollama"

    async def test_generate_combines_system_and_user(self, config):
        provider = OllamaProvider(config)
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "ok"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

            await provider.generate("Be helpful", "What is Python?")

            call_json = mock_client.post.call_args[1]["json"]
            assert "Be helpful" in call_json["prompt"]
            assert "What is Python?" in call_json["prompt"]

    async def test_generate_empty_system_prompt(self, config):
        provider = OllamaProvider(config)
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "ok"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

            await provider.generate("", "Just a user prompt")

            call_json = mock_client.post.call_args[1]["json"]
            assert call_json["prompt"] == "Just a user prompt"

    def test_provider_properties(self, config):
        provider = OllamaProvider(config)
        assert provider.provider_name == "ollama"
        assert provider.model_name == "qwen2.5:32b"


# ── GeminiProvider Tests ─────────────────────────────────────────────────────


class TestGeminiProvider:
    async def test_generate_calls_genai(self):
        config = LLMConfig(provider="gemini", model="gemini-2.0-flash")

        with patch.dict("sys.modules", {"google.generativeai": MagicMock()}):
            provider = GeminiProvider(config, api_key="test-key")

            mock_model = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "Gemini response"
            mock_model.generate_content.return_value = mock_response
            provider._genai.GenerativeModel.return_value = mock_model

            result = await provider.generate("System", "User")

        assert result == "Gemini response"


# ── AnthropicProvider Tests ──────────────────────────────────────────────────


class TestAnthropicProvider:
    async def test_generate_calls_anthropic(self):
        config = LLMConfig(provider="anthropic", model="claude-sonnet-4-20250514")

        with patch("anthropic.AsyncAnthropic") as mock_anthropic:
            mock_client = AsyncMock()
            mock_message = MagicMock()
            mock_content = MagicMock()
            mock_content.text = "Claude response"
            mock_message.content = [mock_content]
            mock_client.messages.create.return_value = mock_message
            mock_anthropic.return_value = mock_client

            provider = AnthropicProvider(config, api_key="test-key")
            result = await provider.generate("System", "User")

        assert result == "Claude response"


# ── Factory Tests ─────────────────────────────────────────────────────────────


class TestCreateProvider:
    def test_explicit_ollama(self):
        provider = create_llm_provider(provider="ollama", model="llama3:8b")
        assert provider.provider_name == "ollama"
        assert provider.model_name == "llama3:8b"

    def test_explicit_gemini(self):
        provider = create_llm_provider(
            provider="gemini", model="gemini-2.0-flash", api_key="fake-key"
        )
        assert provider.provider_name == "gemini"

    def test_explicit_anthropic(self):
        provider = create_llm_provider(
            provider="anthropic", model="claude-sonnet-4-20250514", api_key="fake-key"
        )
        assert provider.provider_name == "anthropic"

    def test_unknown_provider_raises(self):
        with pytest.raises(ProcessingError, match="Unknown LLM provider"):
            create_llm_provider(provider="openai")

    def test_anthropic_requires_key(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
            with pytest.raises(ProcessingError, match="ANTHROPIC_API_KEY"):
                create_llm_provider(provider="anthropic")

    def test_gemini_requires_key(self):
        with patch("src.llm.provider.GOOGLE_API_KEY", None):
            with pytest.raises(ProcessingError, match="GOOGLE_API_KEY"):
                create_llm_provider(provider="gemini")

    def test_auto_detect_ollama_when_no_keys(self):
        with patch("src.llm.provider.GOOGLE_API_KEY", None):
            provider = create_llm_provider()
            assert provider.provider_name == "ollama"

    def test_auto_detect_gemini_when_key_present(self):
        with patch("src.llm.provider.GOOGLE_API_KEY", "some-key"):
            provider = create_llm_provider()
            assert provider.provider_name == "gemini"

    def test_env_var_override(self):
        with patch.dict(
            os.environ,
            {"CORERAG_LLM_PROVIDER": "ollama", "CORERAG_LLM_MODEL": "llama3:8b"},
        ):
            provider = create_llm_provider()
            assert provider.provider_name == "ollama"
            assert provider.model_name == "llama3:8b"

    def test_custom_temperature_and_max_tokens(self):
        provider = create_llm_provider(provider="ollama", temperature=0.7, max_tokens=2048)
        assert provider.config.temperature == 0.7
        assert provider.config.max_tokens == 2048


# ── Singleton Tests ───────────────────────────────────────────────────────────


class TestDefaultProvider:
    def setup_method(self):
        reset_default_provider()

    def teardown_method(self):
        reset_default_provider()

    def test_get_default_returns_provider(self):
        with patch("src.llm.provider.GOOGLE_API_KEY", None):
            provider = get_default_provider()
            assert isinstance(provider, OllamaProvider)

    def test_get_default_is_cached(self):
        with patch("src.llm.provider.GOOGLE_API_KEY", None):
            p1 = get_default_provider()
            p2 = get_default_provider()
            assert p1 is p2

    def test_reset_clears_cache(self):
        with patch("src.llm.provider.GOOGLE_API_KEY", None):
            p1 = get_default_provider()
            reset_default_provider()
            p2 = get_default_provider()
            assert p1 is not p2
