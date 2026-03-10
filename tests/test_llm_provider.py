"""Tests for LLM Provider abstraction."""

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.exceptions import ProcessingError
from src.llm.provider import (
    AnthropicProvider,
    ClaudeCliProvider,
    CodexCliProvider,
    GeminiCliProvider,
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
        return LLMConfig(provider="ollama", model="qwen3:32b")

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

    async def test_generate_strips_thinking_tags(self, config):
        """OllamaProvider must strip <think> blocks from qwen3 output."""
        provider = OllamaProvider(config)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": '<think>\nLet me analyze...\n</think>\n{"category": "Work"}'
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await provider.generate("System", "User prompt")

        assert "<think>" not in result
        assert '{"category": "Work"}' in result

    async def test_generate_handles_empty_think_block(self, config):
        provider = OllamaProvider(config)
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": "<think></think>clean output"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_async_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_async_client.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await provider.generate("", "prompt")

        assert result == "clean output"

    async def test_generate_no_think_tags_passes_through(self, config):
        """Output without <think> tags is unchanged."""
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

    def test_provider_properties(self, config):
        provider = OllamaProvider(config)
        assert provider.provider_name == "ollama"
        assert provider.model_name == "qwen3:32b"


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


# ── ClaudeCliProvider Tests ─────────────────────────────────────────────────


class TestClaudeCliProvider:
    @pytest.fixture
    def config(self):
        return LLMConfig(provider="claude-cli", model="sonnet", timeout=60.0)

    def test_model_map_resolves_short_names(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            provider = ClaudeCliProvider(config)
            assert provider._cli_model == "sonnet"

    def test_model_map_resolves_full_ids(self):
        config = LLMConfig(provider="claude-cli", model="claude-opus-4-6")
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            provider = ClaudeCliProvider(config)
            assert provider._cli_model == "opus"

    def test_raises_if_cli_not_found(self, config):
        with patch("shutil.which", return_value=None):
            with patch("os.path.isfile", return_value=False):
                with pytest.raises(ProcessingError, match="Claude CLI not found"):
                    ClaudeCliProvider(config)

    async def test_generate_parses_json_result(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            provider = ClaudeCliProvider(config)

        cli_response = json.dumps(
            {
                "result": '{"category": "Fitness", "summary": "A workout plan"}',
                "total_cost_usd": 0.003,
                "session_id": "abc123",
            }
        )

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (cli_response.encode(), b"", 0)
            result = await provider.generate("", "Analyze this document")

        assert "category" in result
        assert "Fitness" in result
        assert provider.last_cost_usd == 0.003

    async def test_generate_raises_on_cli_error(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            provider = ClaudeCliProvider(config)

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (b"", b"Authentication failed", 1)
            with pytest.raises(ProcessingError, match="Claude CLI failed"):
                await provider.generate("", "test")

    async def test_generate_raises_on_empty_output(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            provider = ClaudeCliProvider(config)

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (b"", b"", 0)
            with pytest.raises(ProcessingError, match="empty output"):
                await provider.generate("", "test")

    async def test_generate_handles_is_error_flag(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            provider = ClaudeCliProvider(config)

        cli_response = json.dumps({"is_error": True, "result": "Rate limited"})
        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (cli_response.encode(), b"", 0)
            with pytest.raises(ProcessingError, match="Rate limited"):
                await provider.generate("", "test")

    async def test_generate_handles_plain_text_fallback(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            provider = ClaudeCliProvider(config)

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (b"Just plain text response", b"", 0)
            result = await provider.generate("", "test")

        assert result == "Just plain text response"

    async def test_generate_passes_system_prompt(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            provider = ClaudeCliProvider(config)

        cli_response = json.dumps({"result": "ok"})
        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (cli_response.encode(), b"", 0)
            await provider.generate("Be a classifier", "doc text")

            args = mock_run.call_args[0][0]
            assert "--system-prompt" in args
            idx = args.index("--system-prompt")
            assert args[idx + 1] == "Be a classifier"

    async def test_generate_skips_empty_system_prompt(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            provider = ClaudeCliProvider(config)

        cli_response = json.dumps({"result": "ok"})
        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (cli_response.encode(), b"", 0)
            await provider.generate("", "doc text")

            args = mock_run.call_args[0][0]
            assert "--system-prompt" not in args

    def test_env_removes_claudecode(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            provider = ClaudeCliProvider(config)

        with patch.dict(os.environ, {"CLAUDECODE": "1"}):
            env = provider._build_env()
            assert "CLAUDECODE" not in env


# ── GeminiCliProvider Tests ───────────────────────────────────────────────────


class TestGeminiCliProvider:
    @pytest.fixture
    def config(self):
        return LLMConfig(provider="gemini-cli", model="gemini-2.5-pro", timeout=60.0)

    def test_model_map_resolves_known_models(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)
            assert provider._cli_model == "gemini-2.5-pro"

    def test_model_map_passes_through_unknown(self):
        config = LLMConfig(provider="gemini-cli", model="gemini-4-ultra")
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)
            assert provider._cli_model == "gemini-4-ultra"

    def test_raises_if_cli_not_found(self, config):
        with patch("shutil.which", return_value=None):
            with patch("os.path.isfile", return_value=False):
                with pytest.raises(ProcessingError, match="Gemini CLI not found"):
                    GeminiCliProvider(config)

    def test_fallback_path_if_which_fails(self, config):
        with patch("shutil.which", return_value=None):
            with patch("os.path.isfile", return_value=True):
                provider = GeminiCliProvider(config)
                assert "gemini" in provider._cli_path

    async def test_generate_parses_result_key(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)

        cli_response = json.dumps({"result": '{"category": "Work"}'})
        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (cli_response.encode(), b"", 0)
            result = await provider.generate("", "Analyze this document")

        assert "category" in result
        assert "Work" in result

    async def test_generate_parses_text_key(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)

        cli_response = json.dumps({"text": "The answer is 42"})
        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (cli_response.encode(), b"", 0)
            result = await provider.generate("", "test")

        assert result == "The answer is 42"

    async def test_generate_parses_response_key(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)

        cli_response = json.dumps({"response": "Generated text here"})
        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (cli_response.encode(), b"", 0)
            result = await provider.generate("", "test")

        assert result == "Generated text here"

    async def test_generate_raises_on_cli_error(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (b"", b"Authentication failed", 1)
            with pytest.raises(ProcessingError, match="Gemini CLI failed"):
                await provider.generate("", "test")

    async def test_generate_raises_on_empty_output(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (b"", b"", 0)
            with pytest.raises(ProcessingError, match="empty output"):
                await provider.generate("", "test")

    async def test_generate_handles_plain_text_fallback(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (b"Just plain text response", b"", 0)
            result = await provider.generate("", "test")

        assert result == "Just plain text response"

    async def test_generate_folds_system_prompt(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)

        cli_response = json.dumps({"result": "ok"})
        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (cli_response.encode(), b"", 0)
            await provider.generate("Be a classifier", "doc text")

            args = mock_run.call_args[0][0]
            p_idx = args.index("-p")
            combined = args[p_idx + 1]
            assert "Be a classifier" in combined
            assert "doc text" in combined

    async def test_generate_no_system_prompt(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)

        cli_response = json.dumps({"result": "ok"})
        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (cli_response.encode(), b"", 0)
            await provider.generate("", "just user text")

            args = mock_run.call_args[0][0]
            p_idx = args.index("-p")
            assert args[p_idx + 1] == "just user text"

    async def test_generate_uses_headless_mode(self, config):
        """Verify -p flag is used for non-interactive headless mode."""
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)

        cli_response = json.dumps({"result": "ok"})
        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (cli_response.encode(), b"", 0)
            await provider.generate("", "test")

            args = mock_run.call_args[0][0]
            assert "-p" in args
            assert "--output-format" in args

    async def test_generate_includes_model_flag(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)

        cli_response = json.dumps({"result": "ok"})
        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (cli_response.encode(), b"", 0)
            await provider.generate("", "test")

            args = mock_run.call_args[0][0]
            assert "-m" in args
            idx = args.index("-m")
            assert args[idx + 1] == "gemini-2.5-pro"

    async def test_generate_timeout(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = TimeoutError("timed out")
            with pytest.raises(ProcessingError, match="timed out"):
                await provider.generate("", "test")

    def test_provider_properties(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = GeminiCliProvider(config)
            assert provider.provider_name == "gemini-cli"
            assert provider.model_name == "gemini-2.5-pro"


# ── CodexCliProvider Tests ────────────────────────────────────────────────────


class TestCodexCliProvider:
    @pytest.fixture
    def config(self):
        return LLMConfig(provider="codex-cli", model="gpt-5.3-codex", timeout=60.0)

    def test_model_map_resolves_known_models(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            provider = CodexCliProvider(config)
            assert provider._cli_model == "gpt-5.3-codex"

    def test_model_map_passes_through_unknown(self):
        config = LLMConfig(provider="codex-cli", model="gpt-6-ultra")
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            provider = CodexCliProvider(config)
            assert provider._cli_model == "gpt-6-ultra"

    def test_raises_if_cli_not_found(self, config):
        with patch("shutil.which", return_value=None):
            with pytest.raises(ProcessingError, match="Codex CLI not found"):
                CodexCliProvider(config)

    async def test_generate_parses_jsonl_agent_message(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            provider = CodexCliProvider(config)

        jsonl_output = "\n".join(
            [
                '{"type":"thread.started","thread_id":"abc123"}',
                '{"type":"turn.started"}',
                '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"The answer is 42"}}',
                '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":10}}',
            ]
        )

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (jsonl_output.encode(), b"", 0)
            result = await provider.generate("", "What is the answer?")

        assert result == "The answer is 42"

    async def test_generate_parses_json_response(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            provider = CodexCliProvider(config)

        jsonl_output = "\n".join(
            [
                '{"type":"thread.started","thread_id":"abc123"}',
                '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"{\\"category\\": \\"Work\\"}"}}',
                '{"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":10}}',
            ]
        )

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (jsonl_output.encode(), b"", 0)
            result = await provider.generate("Classify.", "doc text")

        assert "category" in result
        assert "Work" in result

    async def test_generate_raises_on_cli_error(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            provider = CodexCliProvider(config)

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (b"", b"Model not supported", 1)
            with pytest.raises(ProcessingError, match="Codex CLI failed"):
                await provider.generate("", "test")

    async def test_generate_raises_on_empty_output(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            provider = CodexCliProvider(config)

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (b"", b"", 0)
            with pytest.raises(ProcessingError, match="empty output"):
                await provider.generate("", "test")

    async def test_generate_folds_system_prompt_into_stdin(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            provider = CodexCliProvider(config)

        jsonl_output = (
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"ok"}}'
        )
        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (jsonl_output.encode(), b"", 0)
            await provider.generate("Be a classifier", "doc text")

            input_data = mock_run.call_args[0][1]
            combined = input_data.decode()
            assert "Be a classifier" in combined
            assert "doc text" in combined

    async def test_generate_uses_exec_mode(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            provider = CodexCliProvider(config)

        jsonl_output = (
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"ok"}}'
        )
        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (jsonl_output.encode(), b"", 0)
            await provider.generate("", "test")

            args = mock_run.call_args[0][0]
            assert "exec" in args
            assert "--json" in args
            assert "--ephemeral" in args
            assert "--sandbox" in args
            assert "read-only" in args

    async def test_generate_includes_model_flag(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            provider = CodexCliProvider(config)

        jsonl_output = (
            '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"ok"}}'
        )
        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (jsonl_output.encode(), b"", 0)
            await provider.generate("", "test")

            args = mock_run.call_args[0][0]
            assert "-m" in args
            idx = args.index("-m")
            assert args[idx + 1] == "gpt-5.3-codex"

    async def test_generate_timeout(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            provider = CodexCliProvider(config)

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = TimeoutError("timed out")
            with pytest.raises(ProcessingError, match="timed out"):
                await provider.generate("", "test")

    async def test_generate_multiple_messages_concatenated(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            provider = CodexCliProvider(config)

        jsonl_output = "\n".join(
            [
                '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"Part 1"}}',
                '{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"Part 2"}}',
            ]
        )

        with patch.object(provider, "_run_process", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (jsonl_output.encode(), b"", 0)
            result = await provider.generate("", "test")

        assert "Part 1" in result
        assert "Part 2" in result

    def test_provider_properties(self, config):
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            provider = CodexCliProvider(config)
            assert provider.provider_name == "codex-cli"
            assert provider.model_name == "gpt-5.3-codex"


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

    def test_explicit_claude_cli(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            provider = create_llm_provider(provider="claude-cli", model="opus")
            assert provider.provider_name == "claude-cli"
            assert isinstance(provider, ClaudeCliProvider)

    def test_explicit_gemini_cli(self):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            provider = create_llm_provider(provider="gemini-cli", model="gemini-2.5-pro")
            assert provider.provider_name == "gemini-cli"
            assert isinstance(provider, GeminiCliProvider)

    def test_explicit_codex_cli(self):
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            provider = create_llm_provider(provider="codex-cli", model="gpt-5.3-codex")
            assert provider.provider_name == "codex-cli"
            assert isinstance(provider, CodexCliProvider)

    def test_codex_cli_default_model(self):
        with patch.dict(os.environ, {"CORERAG_LLM_MODEL": ""}, clear=False):
            with patch("shutil.which", return_value="/usr/local/bin/codex"):
                provider = create_llm_provider(provider="codex-cli")
                assert provider.model_name == "gpt-5.3-codex"

    def test_gemini_cli_default_model(self):
        with patch.dict(os.environ, {"CORERAG_LLM_MODEL": ""}, clear=False):
            with patch("shutil.which", return_value="/usr/local/bin/gemini"):
                provider = create_llm_provider(provider="gemini-cli")
                assert provider.model_name == "gemini-2.5-pro"

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
        with patch.dict(os.environ, {"CORERAG_LLM_PROVIDER": ""}, clear=False):
            with patch("src.llm.provider.GOOGLE_API_KEY", None):
                provider = create_llm_provider()
                assert provider.provider_name == "ollama"

    def test_auto_detect_gemini_when_key_present(self):
        with patch.dict(os.environ, {"CORERAG_LLM_PROVIDER": ""}, clear=False):
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
        with patch.dict(os.environ, {"CORERAG_LLM_PROVIDER": ""}, clear=False):
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
