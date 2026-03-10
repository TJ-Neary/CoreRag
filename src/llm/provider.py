"""
Multi-LLM Provider abstraction for CoreRag.

Unified async interface for Ollama, Gemini, Anthropic Claude, Claude CLI,
Gemini CLI, and Codex CLI. Provider selection via CORERAG_LLM_PROVIDER env var,
with auto-detection fallback (Gemini if GOOGLE_API_KEY set, else Ollama).

Usage:
    from src.llm.provider import get_default_provider

    provider = get_default_provider()
    result = await provider.generate("Be helpful.", "What is Python?")
"""

import asyncio
import json
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
    "ollama": "qwen3:32b",
    "gemini": "gemini-2.0-flash",
    "anthropic": "claude-sonnet-4-20250514",
    "claude-cli": "sonnet",
    "gemini-cli": "gemini-2.5-pro",
    "codex-cli": "gpt-5.3-codex",
}


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class LLMConfig:
    """Configuration for an LLM provider."""

    provider: str  # "ollama", "gemini", "anthropic", "claude-cli", "gemini-cli", "codex-cli"
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


# ── Utility ───────────────────────────────────────────────────────────────────


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks from qwen3-style reasoning output.

    No-op for models that don't emit thinking tags (e.g., qwen2.5).
    """
    import re

    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


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
            raw = resp.json().get("response", "")
            return _strip_thinking_tags(raw)


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


class ClaudeCliProvider(LLMProvider):
    """Claude CLI subprocess provider.

    Uses `claude -p --output-format json` to run inference through the
    authenticated Claude Code CLI. No API key required — uses the active
    CLI session (Pro Max plan).

    Based on the proven pattern from Kendra (core/claude_bridge.py) and
    ResumePRO (src/resumepro/llm/claude_bridge.py).
    """

    # Map full model IDs to CLI short names
    _MODEL_MAP: dict[str, str] = {
        "claude-sonnet-4-20250514": "sonnet",
        "claude-sonnet-4-6": "sonnet",
        "claude-opus-4-6": "opus",
        "claude-haiku-4-5-20251001": "haiku",
        "sonnet": "sonnet",
        "opus": "opus",
        "haiku": "haiku",
    }

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        import shutil

        self._cli_path = shutil.which("claude")
        if not self._cli_path:
            # Fallback to known location
            fallback = os.path.expanduser("~/.local/bin/claude")
            if os.path.isfile(fallback):
                self._cli_path = fallback
            else:
                raise ProcessingError(
                    "Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code"
                )

        self._cli_model = self._MODEL_MAP.get(config.model, config.model)
        self._last_cost_usd: float = 0.0
        logger.info(f"Claude CLI provider initialized: model={self._cli_model}")

    def _build_env(self) -> dict[str, str]:
        """Build subprocess environment, removing CLAUDECODE to allow nesting."""
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        return env

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate text via Claude CLI subprocess.

        Args:
            system_prompt: System instructions (passed via --system-prompt)
            user_prompt: User message (passed via stdin)

        Returns:
            Generated text response

        Raises:
            ProcessingError: If CLI call fails
        """
        args = [
            self._cli_path,
            "-p",
            "--output-format",
            "json",
            "--model",
            self._cli_model,
            "--max-turns",
            "1",
            "--no-session-persistence",
            "--tools",
            "",  # No tool use for batch processing
        ]

        if system_prompt:
            args.extend(["--system-prompt", system_prompt])

        try:
            stdout, stderr, returncode = await self._run_process(
                args, user_prompt.encode(), timeout=self.config.timeout
            )

            if returncode != 0:
                error = stderr.decode().strip() if stderr else "Unknown error"
                logger.error(f"Claude CLI exited with code {returncode}: {error}")
                raise ProcessingError(f"Claude CLI failed: {error}")

            output = stdout.decode().strip()
            if not output:
                raise ProcessingError("Claude CLI returned empty output")

            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                # Treat non-JSON output as plain text
                return output

            self._last_cost_usd = data.get("total_cost_usd", 0.0)

            if data.get("is_error"):
                error_msg = data.get("result", "Unknown error")
                raise ProcessingError(f"Claude CLI error: {error_msg}")

            result = data.get("result", "").strip()
            if not result:
                # Some CLI versions use different keys
                result = data.get("text", data.get("content", "")).strip()

            return result

        except ProcessingError:
            raise
        except TimeoutError:
            raise ProcessingError(f"Claude CLI timed out after {self.config.timeout}s")
        except Exception as e:
            raise ProcessingError(f"Claude CLI error: {e}") from e

    async def _run_process(
        self,
        args: list[str],
        input_data: bytes,
        timeout: float,
    ) -> tuple[bytes, bytes, int]:
        """Run subprocess with Python 3.13 event loop compatibility.

        Falls back to subprocess.run() in a thread when asyncio subprocess
        creation raises NotImplementedError.
        """
        import subprocess as sp

        env = self._build_env()

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input_data), timeout=timeout
            )
            return stdout or b"", stderr or b"", process.returncode or 0

        except NotImplementedError:
            # Python 3.13+ fallback: child watchers removed
            def _run() -> tuple[bytes, bytes, int]:
                try:
                    result = sp.run(
                        args,
                        input=input_data,
                        capture_output=True,
                        env=env,
                        timeout=timeout,
                    )
                    return result.stdout or b"", result.stderr or b"", result.returncode
                except sp.TimeoutExpired as exc:
                    raise TimeoutError(str(exc)) from exc

            return await asyncio.to_thread(_run)

    @property
    def last_cost_usd(self) -> float:
        """Cost of the last CLI call."""
        return self._last_cost_usd


class GeminiCliProvider(LLMProvider):
    """Gemini CLI subprocess provider.

    Uses `gemini -p "prompt" --output-format json` to run inference through the
    authenticated Gemini CLI. No API key required — uses the active CLI session.

    Part of TJ's multi-agent ecosystem: Gem handles large-context ingestion
    tasks with its 1M+ token context window.
    """

    _MODEL_MAP: dict[str, str] = {
        "gemini-2.5-pro": "gemini-2.5-pro",
        "gemini-2.5-flash": "gemini-2.5-flash",
        "gemini-3-flash-preview": "gemini-3-flash-preview",
        "gemini-3-pro-preview": "gemini-3-pro-preview",
        "gemini-2.0-flash": "gemini-2.0-flash",
    }

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        import shutil

        self._cli_path = shutil.which("gemini")
        if not self._cli_path:
            fallback = os.path.expanduser("~/.local/bin/gemini")
            if os.path.isfile(fallback):
                self._cli_path = fallback
            else:
                raise ProcessingError(
                    "Gemini CLI not found. Install with: npm install -g @anthropic-ai/gemini-cli"
                )

        self._cli_model = self._MODEL_MAP.get(config.model, config.model)
        logger.info(f"Gemini CLI provider initialized: model={self._cli_model}")

    def _build_env(self) -> dict[str, str]:
        """Build subprocess environment."""
        env = os.environ.copy()
        return env

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate text via Gemini CLI subprocess.

        Args:
            system_prompt: System instructions (folded into user prompt since
                           Gemini CLI has no --system-prompt flag).
            user_prompt: User message (passed via -p argument).

        Returns:
            Generated text response

        Raises:
            ProcessingError: If CLI call fails
        """
        if system_prompt:
            combined_prompt = f"{system_prompt}\n\n{user_prompt}"
        else:
            combined_prompt = user_prompt

        args = [
            self._cli_path,
            "-p",
            combined_prompt,
            "--output-format",
            "json",
            "-m",
            self._cli_model,
        ]

        try:
            stdout, stderr, returncode = await self._run_process(args, timeout=self.config.timeout)

            if returncode != 0:
                error = stderr.decode().strip() if stderr else "Unknown error"
                logger.error(f"Gemini CLI exited with code {returncode}: {error}")
                raise ProcessingError(f"Gemini CLI failed: {error}")

            output = stdout.decode().strip()
            if not output:
                raise ProcessingError("Gemini CLI returned empty output")

            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                return output

            # Adaptive JSON parsing — Gemini CLI format not fully documented
            for key in ("result", "text", "content", "response", "message"):
                val = data.get(key)
                if val and isinstance(val, str):
                    return val.strip()

            # Fallback: single-key dict or re-serialize
            if isinstance(data, dict) and len(data) == 1:
                return str(next(iter(data.values()))).strip()
            return json.dumps(data)

        except ProcessingError:
            raise
        except TimeoutError:
            raise ProcessingError(f"Gemini CLI timed out after {self.config.timeout}s")
        except Exception as e:
            raise ProcessingError(f"Gemini CLI error: {e}") from e

    async def _run_process(
        self,
        args: list[str],
        timeout: float,
    ) -> tuple[bytes, bytes, int]:
        """Run subprocess with Python 3.13 event loop compatibility.

        Gemini CLI takes the prompt via -p argument (not stdin),
        so stdin is DEVNULL.
        """
        import subprocess as sp

        env = self._build_env()

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return stdout or b"", stderr or b"", process.returncode or 0

        except NotImplementedError:
            # Python 3.13+ fallback: child watchers removed
            def _run() -> tuple[bytes, bytes, int]:
                try:
                    result = sp.run(
                        args,
                        stdin=sp.DEVNULL,
                        capture_output=True,
                        env=env,
                        timeout=timeout,
                    )
                    return result.stdout or b"", result.stderr or b"", result.returncode
                except sp.TimeoutExpired as exc:
                    raise TimeoutError(str(exc)) from exc

            return await asyncio.to_thread(_run)


class CodexCliProvider(LLMProvider):
    """OpenAI Codex CLI subprocess provider.

    Uses `codex exec --json -` to run inference through the authenticated
    Codex CLI. No API key required — uses the active ChatGPT+ subscription.

    Output format is JSONL on stdout. We parse for `item.completed` events
    with `type: agent_message` and extract the text field.
    """

    _MODEL_MAP: dict[str, str] = {
        "gpt-5.3-codex": "gpt-5.3-codex",
        "gpt-5.2-codex": "gpt-5.2-codex",
        "o4-mini": "o4-mini",
        "o3": "o3",
    }

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        import shutil

        self._cli_path = shutil.which("codex")
        if not self._cli_path:
            raise ProcessingError("Codex CLI not found. Install with: npm install -g @openai/codex")

        self._cli_model = self._MODEL_MAP.get(config.model, config.model)
        logger.info(f"Codex CLI provider initialized: model={self._cli_model}")

    def _build_env(self) -> dict[str, str]:
        """Build subprocess environment."""
        env = os.environ.copy()
        return env

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate text via Codex CLI subprocess.

        Args:
            system_prompt: System instructions (folded into user prompt since
                           Codex CLI has no --system-prompt flag).
            user_prompt: User message (passed via stdin).

        Returns:
            Generated text response

        Raises:
            ProcessingError: If CLI call fails
        """
        if system_prompt:
            combined_prompt = f"{system_prompt}\n\n{user_prompt}"
        else:
            combined_prompt = user_prompt

        args = [
            self._cli_path,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--json",
            "-m",
            self._cli_model,
            "-",  # Read prompt from stdin
        ]

        try:
            stdout, stderr, returncode = await self._run_process(
                args, combined_prompt.encode(), timeout=self.config.timeout
            )

            if returncode != 0:
                error = stderr.decode().strip() if stderr else "Unknown error"
                logger.error(f"Codex CLI exited with code {returncode}: {error}")
                raise ProcessingError(f"Codex CLI failed: {error}")

            output = stdout.decode().strip()
            if not output:
                raise ProcessingError("Codex CLI returned empty output")

            return self._parse_jsonl_output(output)

        except ProcessingError:
            raise
        except TimeoutError:
            raise ProcessingError(f"Codex CLI timed out after {self.config.timeout}s")
        except Exception as e:
            raise ProcessingError(f"Codex CLI error: {e}") from e

    def _parse_jsonl_output(self, output: str) -> str:
        """Parse JSONL output from codex exec --json.

        Looks for item.completed events with agent_message type.
        Concatenates all message texts in order.
        """
        messages: list[str] = []
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message":
                    text = item.get("text", "").strip()
                    if text:
                        messages.append(text)

        if messages:
            return "\n".join(messages)

        # Fallback: try to find any text in the JSONL events
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                for key in ("text", "result", "content", "message"):
                    val = event.get(key)
                    if val and isinstance(val, str):
                        return val.strip()
            except json.JSONDecodeError:
                continue

        # Last resort: return raw output
        return output

    async def _run_process(
        self,
        args: list[str],
        input_data: bytes,
        timeout: float,
    ) -> tuple[bytes, bytes, int]:
        """Run subprocess with Python 3.13 event loop compatibility."""
        import subprocess as sp

        env = self._build_env()

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input_data), timeout=timeout
            )
            return stdout or b"", stderr or b"", process.returncode or 0

        except NotImplementedError:
            # Python 3.13+ fallback: child watchers removed
            def _run() -> tuple[bytes, bytes, int]:
                try:
                    result = sp.run(
                        args,
                        input=input_data,
                        capture_output=True,
                        env=env,
                        timeout=timeout,
                    )
                    return result.stdout or b"", result.stderr or b"", result.returncode
                except sp.TimeoutExpired as exc:
                    raise TimeoutError(str(exc)) from exc

            return await asyncio.to_thread(_run)


# ── Factory ───────────────────────────────────────────────────────────────────


def create_llm_provider(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs: object,
) -> LLMProvider:
    """Factory function to create an LLM provider.

    Args:
        provider: Provider name ("ollama", "gemini", "anthropic", "claude-cli",
                  "gemini-cli", "codex-cli"). Defaults to CORERAG_LLM_PROVIDER env var,
                  then auto-detection.
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

    elif provider == "claude-cli":
        return ClaudeCliProvider(config)

    elif provider == "gemini-cli":
        return GeminiCliProvider(config)

    elif provider == "codex-cli":
        return CodexCliProvider(config)

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
