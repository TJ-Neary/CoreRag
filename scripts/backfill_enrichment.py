#!/usr/bin/env python3
"""
Database Enrichment Backfill

Re-enriches existing chunks with LLM-powered quality enhancements that
were silently failing before the Session 26 bug fixes:

  Phase 1: Context prefixes (contextual retrieval — LLM)
  Phase 2: Re-embed chunks with context prefix + text
  Phase 3: Parent summaries (multi-resolution — LLM)
  Phase 4: Knowledge graph entity re-extraction (LLM)

Defaults to Gemini CLI (gemini-2.5-pro) but supports any configured provider.

All LLM calls are logged with timing, prompts, and responses so you can
watch what Gem does in real time. Logs go to both console and
~/.corerag/backfill.log.

Safeguards:
  - Quota detection: stops immediately on rate limit / quota exhaustion
  - Checkpointing: saves progress after each parent group so interrupted
    runs can resume with --resume (or automatically if checkpoint exists)

Usage:
    python scripts/backfill_enrichment.py                      # Full backfill (all 4 phases)
    python scripts/backfill_enrichment.py --resume              # Resume from checkpoint
    python scripts/backfill_enrichment.py --dry-run             # Preview without writing
    python scripts/backfill_enrichment.py --phases 1 3          # Only context + summaries
    python scripts/backfill_enrichment.py --phases 2            # Only re-embed (after phase 1)
    python scripts/backfill_enrichment.py --provider ollama     # Use local Ollama instead
    python scripts/backfill_enrichment.py --concurrency 4       # More parallel LLM calls
    python scripts/backfill_enrichment.py --no-resume           # Ignore checkpoint, start fresh
"""

import argparse
import asyncio
import gc
import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil
import pyarrow as pa

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.config import DB_PATH  # noqa: E402

# ── Logging Setup ───────────────────────────────────────────────────

LOG_FILE = Path(str(DB_PATH)).parent / "backfill.log"
CHECKPOINT_FILE = Path(str(DB_PATH)).parent / "backfill_checkpoint.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-5s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(LOG_FILE, mode="a"),
    ],
)
logger = logging.getLogger("backfill")

# Quota-related keywords in error messages
_QUOTA_KEYWORDS = ["quota", "rate limit", "rate_limit", "exhausted", "429", "capacity"]

# Memory safety thresholds (matches SafeProcessor conventions)
_MEMORY_PAUSE_PCT = 75  # Pause processing above this
_MEMORY_RESUME_PCT = 65  # Resume once below this
_MEMORY_CHECK_INTERVAL = 5  # Check every N parent groups


def _check_memory_safe() -> tuple[bool, float]:
    """Check if memory usage is below the pause threshold.

    Returns:
        (is_safe, memory_percent)
    """
    mem = psutil.virtual_memory()
    return mem.percent < _MEMORY_PAUSE_PCT, mem.percent


def _wait_for_memory(timeout: float = 120.0) -> bool:
    """Wait for memory to drop below resume threshold.

    Runs gc.collect() and sleeps in a loop.

    Returns:
        True if memory recovered, False if timeout.
    """
    start = time.time()
    while time.time() - start < timeout:
        gc.collect()
        mem = psutil.virtual_memory()
        if mem.percent < _MEMORY_RESUME_PCT:
            logger.info(f"Memory recovered to {mem.percent:.1f}% — resuming")
            return True
        logger.info(f"Memory at {mem.percent:.1f}%, waiting... ({_MEMORY_RESUME_PCT}% to resume)")
        time.sleep(5)
    return False


# ── Quota Error ─────────────────────────────────────────────────────


class QuotaExhaustedError(Exception):
    """Raised when the LLM provider's quota is exhausted."""

    pass


# ── Instrumented LLM Wrapper ───────────────────────────────────────


class LoggingLLMProvider:
    """Wraps any LLMProvider with call logging and quota detection.

    Every generate() call logs: prompt preview, response preview, timing.
    Detects consecutive failures that indicate quota exhaustion and raises
    QuotaExhaustedError to stop burning through doomed calls.
    """

    CONSECUTIVE_FAILURE_THRESHOLD = 5

    def __init__(self, provider):
        self._provider = provider
        self.call_count = 0
        self.total_time = 0.0
        self.failures = 0
        self._consecutive_failures = 0
        self.quota_exhausted = False

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self.quota_exhausted:
            raise QuotaExhaustedError("Quota already exhausted — skipping call")

        self.call_count += 1
        call_num = self.call_count

        # Show what we're asking
        prompt_preview = user_prompt[:200].replace("\n", " ").strip()
        logger.info(f"  >> LLM #{call_num}: {prompt_preview}...")

        start = time.time()
        try:
            result = await self._provider.generate(system_prompt, user_prompt)
            elapsed = time.time() - start
            self.total_time += elapsed
            self._consecutive_failures = 0  # Reset on success

            result_preview = result[:150].replace("\n", " ").strip() if result else "(empty)"
            logger.info(f"  << LLM #{call_num} OK ({elapsed:.1f}s): {result_preview}")
            return result
        except Exception as e:
            elapsed = time.time() - start
            self.total_time += elapsed
            self.failures += 1
            self._consecutive_failures += 1

            error_str = str(e).lower()
            is_quota = any(kw in error_str for kw in _QUOTA_KEYWORDS)

            if is_quota:
                self.quota_exhausted = True
                logger.error(f"  << LLM #{call_num} QUOTA EXHAUSTED ({elapsed:.1f}s): {e}")
                raise QuotaExhaustedError(str(e)) from e

            if self._consecutive_failures >= self.CONSECUTIVE_FAILURE_THRESHOLD:
                self.quota_exhausted = True
                logger.error(
                    f"  << LLM #{call_num} FAILED ({elapsed:.1f}s): {e}\n"
                    f"  {self._consecutive_failures} consecutive failures — "
                    f"assuming quota exhausted, stopping."
                )
                raise QuotaExhaustedError(
                    f"{self._consecutive_failures} consecutive failures"
                ) from e

            logger.error(f"  << LLM #{call_num} FAILED ({elapsed:.1f}s): {e}")
            raise


class LLMProviderAdapter:
    """Adapts LLMProvider interface to OllamaLLM interface for EntityExtractor.

    EntityExtractor expects: llm.generate(prompt, max_tokens=1000)
    LLMProvider provides:    provider.generate(system_prompt, user_prompt)
    """

    def __init__(self, logging_provider: LoggingLLMProvider):
        self._provider = logging_provider

    async def generate(self, prompt: str, max_tokens: int = 1000) -> str:
        return await self._provider.generate("", prompt)


# ── Checkpoint Management ───────────────────────────────────────────


def _save_checkpoint(
    context_prefixes: list[str] | None = None,
    summaries: list[str] | None = None,
    phase: int = 1,
    stats_dict: dict | None = None,
) -> None:
    """Save progress to checkpoint file."""
    data: dict = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "phase": phase,
    }
    if context_prefixes is not None:
        data["context_prefixes"] = context_prefixes
    if summaries is not None:
        data["summaries"] = summaries
    if stats_dict:
        data["stats"] = stats_dict

    CHECKPOINT_FILE.write_text(json.dumps(data))
    filled = 0
    if context_prefixes:
        filled = sum(1 for c in context_prefixes if c)
    elif summaries:
        filled = sum(1 for s in summaries if s)
    logger.info(f"  Checkpoint saved ({filled} items) -> {CHECKPOINT_FILE.name}")


def _load_checkpoint() -> dict | None:
    """Load checkpoint if it exists."""
    if not CHECKPOINT_FILE.exists():
        return None
    try:
        data = json.loads(CHECKPOINT_FILE.read_text())
        logger.info(
            f"Checkpoint found from {data.get('timestamp', '?')} "
            f"(phase {data.get('phase', '?')})"
        )
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Checkpoint file corrupt, ignoring: {e}")
        return None


def _clear_checkpoint() -> None:
    """Remove checkpoint file after successful completion."""
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        logger.info("Checkpoint cleared (backfill complete)")


# ── Statistics Tracker ──────────────────────────────────────────────


@dataclass
class BackfillStats:
    context_generated: int = 0
    context_skipped: int = 0
    context_failed: int = 0
    summaries_generated: int = 0
    summaries_skipped: int = 0
    summaries_failed: int = 0
    entities_extracted: int = 0
    relationships_extracted: int = 0
    chunks_reembedded: int = 0
    start_time: float = field(default_factory=time.time)

    def elapsed(self) -> float:
        return time.time() - self.start_time

    def to_dict(self) -> dict:
        return {
            "context_generated": self.context_generated,
            "context_skipped": self.context_skipped,
            "context_failed": self.context_failed,
            "summaries_generated": self.summaries_generated,
            "summaries_skipped": self.summaries_skipped,
            "summaries_failed": self.summaries_failed,
            "entities_extracted": self.entities_extracted,
            "relationships_extracted": self.relationships_extracted,
            "chunks_reembedded": self.chunks_reembedded,
        }

    def summary(self) -> str:
        return (
            f"Context: {self.context_generated} generated, "
            f"{self.context_skipped} skipped, {self.context_failed} failed\n"
            f"Summaries: {self.summaries_generated} generated, "
            f"{self.summaries_skipped} skipped, {self.summaries_failed} failed\n"
            f"Re-embedded: {self.chunks_reembedded} chunks\n"
            f"Knowledge graph: {self.entities_extracted} entities, "
            f"{self.relationships_extracted} relationships\n"
            f"Elapsed: {self.elapsed():.1f}s"
        )


# ── Main Backfill Logic ────────────────────────────────────────────


_BACKFILL_MODEL_DEFAULTS: dict[str, str] = {
    "ollama": "qwen3:32b",
    "gemini-cli": "gemini-2.5-pro",
    "claude-cli": "sonnet",
    "codex-cli": "gpt-5.3-codex",
}


def _create_provider(provider_name: str, model: str | None) -> LoggingLLMProvider:
    """Create an LLM provider wrapped with logging.

    When model is None, uses backfill-specific defaults instead of the global
    CORERAG_LLM_MODEL env var (which may be set for a different provider).
    """
    from src.llm.provider import create_llm_provider

    resolved_model = model or _BACKFILL_MODEL_DEFAULTS.get(provider_name)
    raw_provider = create_llm_provider(provider=provider_name, model=resolved_model)
    logger.info(
        f"LLM provider: {raw_provider.__class__.__name__} " f"(model: {raw_provider.config.model})"
    )
    return LoggingLLMProvider(raw_provider)


def backfill_enrichment(
    provider_name: str = "gemini-cli",
    model: str = "gemini-2.5-pro",
    dry_run: bool = False,
    phases: list[int] | None = None,
    concurrency: int = 2,
    batch_size: int = 32,
    resume: bool = True,
    max_chunks_per_call: int | None = None,
) -> dict:
    """Run the full enrichment backfill.

    Args:
        provider_name: LLM provider to use (gemini-cli, ollama, claude-cli, etc.)
        model: Model name for the provider.
        dry_run: Preview without writing to database.
        phases: Which phases to run (1-4). Default: all.
        concurrency: Max concurrent LLM calls per batch.
        batch_size: Embedding batch size.
        max_chunks_per_call: Max chunks per batched LLM call. Default: 50 for
            cloud providers (gemini-cli, claude-cli), 5 for local (ollama).
        resume: Whether to resume from checkpoint if available.

    Returns:
        Statistics dict.
    """
    import lancedb

    phases = phases or [1, 2, 3, 4]
    stats = BackfillStats()
    quota_hit = False

    # Set max_chunks_per_call based on provider if not specified
    if max_chunks_per_call is None:
        if provider_name in ("ollama",):
            max_chunks_per_call = 5  # Local models struggle with large JSON arrays
        else:
            max_chunks_per_call = 50  # Cloud models (Gemini, Claude) handle large batches

    logger.info("=" * 65)
    logger.info("CORERAG ENRICHMENT BACKFILL")
    logger.info("=" * 65)
    logger.info(f"Provider: {provider_name} / {model}")
    logger.info(f"Phases: {phases}")
    logger.info(f"Concurrency: {concurrency}")
    logger.info(f"Max chunks/call: {max_chunks_per_call}")
    logger.info(f"Log file: {LOG_FILE}")

    # Check for checkpoint
    checkpoint = _load_checkpoint() if resume else None
    if checkpoint:
        cp_ctx = checkpoint.get("context_prefixes")
        cp_sum = checkpoint.get("summaries")
        ctx_count = sum(1 for c in cp_ctx if c) if cp_ctx else 0
        sum_count = sum(1 for s in cp_sum if s) if cp_sum else 0
        logger.info(
            f"Resuming: {ctx_count} context prefixes, {sum_count} summaries from checkpoint"
        )

    # Create instrumented LLM provider
    logged_provider = _create_provider(provider_name, model)

    # Open database
    db = lancedb.connect(str(DB_PATH))
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        tables = db.table_names()

    if "child_chunks" not in tables:
        logger.error("No child_chunks table — nothing to backfill.")
        return {"status": "skipped", "reason": "no_data"}

    # ── Read all data into memory ───────────────────────────────────
    logger.info("Reading database into memory...")
    child_table = db.open_table("child_chunks")
    all_children = child_table.to_arrow().to_pydict()
    total_children = len(all_children["content"])

    has_parents = "parent_chunks" in tables
    all_parents = {}
    total_parents = 0
    if has_parents:
        parent_table = db.open_table("parent_chunks")
        all_parents = parent_table.to_arrow().to_pydict()
        total_parents = len(all_parents["content"])

    logger.info(f"Loaded: {total_children} child chunks, {total_parents} parent chunks")
    logger.info(f"Child columns: {sorted(all_children.keys())}")
    if has_parents:
        logger.info(f"Parent columns: {sorted(all_parents.keys())}")

    # Build parent -> children index
    parent_ids = all_children.get("parent_id", [""] * total_children)
    parent_children_map: dict[str, list[int]] = {}
    for i, pid in enumerate(parent_ids):
        if pid:
            parent_children_map.setdefault(pid, []).append(i)

    # Build parent content lookup
    parent_content_map: dict[str, str] = {}
    if has_parents:
        for i in range(total_parents):
            parent_content_map[all_parents["id"][i]] = all_parents["content"][i]

    # ── Dry run analysis ────────────────────────────────────────────
    ctx_col = all_children.get("context_prefix", [""] * total_children)
    # Apply checkpoint data for accurate dry-run counts
    if checkpoint and checkpoint.get("context_prefixes"):
        ctx_col = checkpoint["context_prefixes"]
    needs_context = sum(1 for c in ctx_col if not c)

    sum_col = all_parents.get("summary", [""] * total_parents) if has_parents else []
    if checkpoint and checkpoint.get("summaries"):
        sum_col = checkpoint["summaries"]
    needs_summary = sum(1 for s in sum_col if not s)

    logger.info(f"Chunks needing context prefix: {needs_context}/{total_children}")
    logger.info(f"Parents needing summary: {needs_summary}/{total_parents}")

    if dry_run:
        logger.info("[DRY RUN] No changes will be written.")
        # Batched: ~1 call per parent group (+ sub-batches for large groups)
        est_phase1_calls = len(parent_children_map)
        large_groups = sum(1 for indices in parent_children_map.values() if len(indices) > 50)
        if large_groups:
            est_phase1_calls += large_groups  # Rough extra for sub-batching
        logger.info(
            f"  Phase 1 would generate ~{needs_context} context prefixes "
            f"in ~{est_phase1_calls} batched LLM calls"
        )
        logger.info(f"  Phase 2 would re-embed {total_children} chunks")
        logger.info(f"  Phase 3 would generate ~{needs_summary} parent summaries")
        logger.info(f"  Phase 4 would re-extract entities from {total_parents} parents")
        est_llm_calls = est_phase1_calls + needs_summary + total_parents
        logger.info(f"  Estimated LLM calls: ~{est_llm_calls} (batched Phase 1)")
        return {
            "status": "dry_run",
            "needs_context": needs_context,
            "needs_summary": needs_summary,
            "total_children": total_children,
            "total_parents": total_parents,
        }

    # ── Phase 1: Context Prefixes (Batched Multi-Chunk) ─────────────
    if 1 in phases and not quota_hit:
        logger.info("")
        logger.info("=" * 65)
        logger.info("PHASE 1: Context Prefix Generation (Batched Multi-Chunk)")
        logger.info("=" * 65)

        from src.chunking.context_generator import ContextGenerator

        # Load from checkpoint or database
        if checkpoint and checkpoint.get("context_prefixes"):
            context_prefixes = list(checkpoint["context_prefixes"])
            restored = sum(1 for c in context_prefixes if c)
            logger.info(f"Restored {restored} context prefixes from checkpoint")
        else:
            context_prefixes = list(all_children.get("context_prefix", [""] * total_children))

        # Pad if column was shorter than data
        while len(context_prefixes) < total_children:
            context_prefixes.append("")

        ctx_gen = ContextGenerator(llm_provider=logged_provider, max_doc_chars=8000)

        # Process by parent group — each group shares a document context
        parent_groups = sorted(parent_children_map.items())
        groups_processed = 0
        groups_with_work = 0

        for group_idx, (pid, child_indices) in enumerate(parent_groups):
            # Memory safety: check every N groups
            if groups_processed > 0 and groups_processed % _MEMORY_CHECK_INTERVAL == 0:
                is_safe, mem_pct = _check_memory_safe()
                if not is_safe:
                    logger.warning(
                        f"Memory at {mem_pct:.1f}% (>{_MEMORY_PAUSE_PCT}%) — "
                        f"pausing to recover..."
                    )
                    if not _wait_for_memory(timeout=120):
                        logger.error("Memory did not recover — saving checkpoint and stopping")
                        quota_hit = True  # Reuse flag to trigger clean exit
                        break

            # Use parent content as the "document" for context generation
            doc_text = parent_content_map.get(pid, "")
            if not doc_text:
                doc_text = "\n".join(all_children["content"][ci] for ci in child_indices)

            # Find children that still need context
            needs_ctx = [
                (ci, all_children["content"][ci])
                for ci in child_indices
                if not context_prefixes[ci]
            ]

            if not needs_ctx:
                stats.context_skipped += len(child_indices)
                continue

            groups_with_work += 1
            source = all_children.get("source_path", [""] * total_children)[child_indices[0]]
            source_short = Path(source).name if source else pid[:12]
            logger.info(
                f"Parent {group_idx + 1}/{len(parent_groups)} [{source_short}]: "
                f"{len(needs_ctx)} chunks need context (batched)"
            )

            # Generate contexts — batched multi-chunk (1 call per parent group)
            chunk_texts = [ct for _, ct in needs_ctx]
            loop = asyncio.new_event_loop()
            try:
                results = loop.run_until_complete(
                    ctx_gen.generate_contexts_batch_multi(
                        doc_text, chunk_texts, max_chunks_per_call=max_chunks_per_call
                    )
                )
            finally:
                loop.close()

            for (ci, _), ctx in zip(needs_ctx, results):
                if ctx:
                    context_prefixes[ci] = ctx
                    stats.context_generated += 1
                else:
                    stats.context_failed += 1

            succeeded = sum(1 for r in results if r)
            logger.info(f"  Batch done: {succeeded}/{len(results)} succeeded")
            groups_processed += 1

            # Checkpoint after every 5 parent groups
            if groups_processed % 5 == 0:
                _save_checkpoint(
                    context_prefixes=context_prefixes,
                    phase=1,
                    stats_dict=stats.to_dict(),
                )

            gc.collect()

            # Check quota
            if logged_provider.quota_exhausted:
                logger.warning("Quota exhausted — saving checkpoint and stopping Phase 1")
                quota_hit = True
                break

        all_children["context_prefix"] = context_prefixes

        # Save checkpoint with final Phase 1 state
        _save_checkpoint(
            context_prefixes=context_prefixes,
            phase=2 if not quota_hit else 1,
            stats_dict=stats.to_dict(),
        )

        logger.info(
            f"Phase 1 {'INTERRUPTED' if quota_hit else 'complete'}: "
            f"{stats.context_generated} generated, "
            f"{stats.context_skipped} already had context, "
            f"{stats.context_failed} failed"
        )

    # ── Phase 2: Re-embed with Context ──────────────────────────────
    if 2 in phases and not quota_hit:
        logger.info("")
        logger.info("=" * 65)
        logger.info("PHASE 2: Re-embedding Chunks (context + content)")
        logger.info("=" * 65)

        from src.embeddings.embedding_service import create_embedding_service

        embedder = create_embedding_service(batch_size=batch_size)
        context_prefixes = all_children.get("context_prefix", [""] * total_children)

        with_context = sum(1 for ctx in context_prefixes if ctx)
        logger.info(f"{with_context}/{total_children} chunks have context prefixes")
        logger.info(f"Embedding model: {embedder.model_name} ({embedder.dimension}d)")

        # Build embed texts: context + content (truncated for embedding)
        max_embed_chars = 2000
        embed_texts = []
        for i in range(total_children):
            ctx = context_prefixes[i] if i < len(context_prefixes) else ""
            content = all_children["content"][i]
            combined = f"{ctx}\n\n{content}" if ctx else content
            embed_texts.append(
                combined[:max_embed_chars] if len(combined) > max_embed_chars else combined
            )

        long_count = sum(
            1
            for i in range(total_children)
            if len(
                (context_prefixes[i] + "\n\n" + all_children["content"][i])
                if context_prefixes[i]
                else all_children["content"][i]
            )
            > max_embed_chars
        )
        if long_count:
            logger.info(f"Truncated {long_count} chunks > {max_embed_chars} chars for embedding")

        new_embeddings = []
        embed_start = time.time()
        for i in range(0, len(embed_texts), batch_size):
            batch = embed_texts[i : i + batch_size]
            batch_embs = embedder.embed_documents(batch, show_progress=False)
            new_embeddings.extend(batch_embs)

            done = min(i + batch_size, total_children)
            elapsed = time.time() - embed_start
            rate = done / elapsed if elapsed > 0 else 0
            logger.info(f"  Embedded {done}/{total_children} ({rate:.0f} chunks/sec)")
            gc.collect()

        all_children["vector"] = new_embeddings
        stats.chunks_reembedded = total_children
        embedder.save_cache()
        logger.info(f"Phase 2 complete: {total_children} chunks re-embedded")

    # ── Phase 3: Parent Summaries ───────────────────────────────────
    if 3 in phases and has_parents and not quota_hit:
        logger.info("")
        logger.info("=" * 65)
        logger.info("PHASE 3: Parent Summary Generation (Multi-Resolution)")
        logger.info("=" * 65)

        from src.chunking.summarizer import MultiResolutionSummarizer

        # Load from checkpoint or database
        if checkpoint and checkpoint.get("summaries"):
            summaries = list(checkpoint["summaries"])
            restored = sum(1 for s in summaries if s)
            logger.info(f"Restored {restored} summaries from checkpoint")
        else:
            summaries = list(all_parents.get("summary", [""] * total_parents))

        while len(summaries) < total_parents:
            summaries.append("")

        summarizer = MultiResolutionSummarizer(llm_provider=logged_provider)

        for i in range(total_parents):
            if summaries[i]:
                stats.summaries_skipped += 1
                continue

            # Memory safety check every 10 parents
            if i > 0 and i % 10 == 0:
                is_safe, mem_pct = _check_memory_safe()
                if not is_safe:
                    logger.warning(f"Memory at {mem_pct:.1f}% — pausing Phase 3...")
                    if not _wait_for_memory(timeout=120):
                        logger.error("Memory did not recover — stopping Phase 3")
                        quota_hit = True
                        break

            parent_text = all_parents["content"][i]
            pid = all_parents["id"][i]
            source = all_parents.get("source_path", [""] * total_parents)[i]
            source_short = Path(source).name if source else pid[:12]

            logger.info(f"Parent {i + 1}/{total_parents} [{source_short}]")

            loop = asyncio.new_event_loop()
            try:
                summary = loop.run_until_complete(summarizer.summarize_parent(parent_text))
            except QuotaExhaustedError:
                logger.warning("Quota exhausted — saving checkpoint and stopping Phase 3")
                quota_hit = True
                break
            except Exception:
                stats.summaries_failed += 1
                continue
            finally:
                loop.close()

            if summary:
                summaries[i] = summary
                stats.summaries_generated += 1
            else:
                stats.summaries_failed += 1

            # Checkpoint every 10 parents
            if (i + 1) % 10 == 0:
                _save_checkpoint(
                    context_prefixes=all_children.get("context_prefix"),
                    summaries=summaries,
                    phase=3,
                    stats_dict=stats.to_dict(),
                )
                logger.info(
                    f"  Progress: {i + 1}/{total_parents} "
                    f"({stats.summaries_generated} generated, {stats.summaries_failed} failed)"
                )
                gc.collect()

            # Check quota
            if logged_provider.quota_exhausted:
                logger.warning("Quota exhausted — saving checkpoint and stopping Phase 3")
                quota_hit = True
                break

        all_parents["summary"] = summaries

        # Save checkpoint with final Phase 3 state
        _save_checkpoint(
            context_prefixes=all_children.get("context_prefix"),
            summaries=summaries,
            phase=4 if not quota_hit else 3,
            stats_dict=stats.to_dict(),
        )

        logger.info(
            f"Phase 3 {'INTERRUPTED (quota)' if quota_hit else 'complete'}: "
            f"{stats.summaries_generated} generated, "
            f"{stats.summaries_skipped} already had summaries, "
            f"{stats.summaries_failed} failed"
        )

    # ── Phase 4: Knowledge Graph Re-extraction ──────────────────────
    if 4 in phases and not quota_hit:
        logger.info("")
        logger.info("=" * 65)
        logger.info("PHASE 4: Knowledge Graph Entity Re-extraction")
        logger.info("=" * 65)

        from src.graph.knowledge_graph import EntityExtractor, KnowledgeGraph

        graph_db_path = Path(str(DB_PATH)).parent / "knowledge_graph.db"
        graph = KnowledgeGraph(graph_db_path)

        stats_before = graph.get_stats()
        logger.info(
            f"Graph before: {stats_before['total_entities']} entities, "
            f"{stats_before['total_relationships']} relationships"
        )

        # Wrap provider for EntityExtractor's OllamaLLM-style interface
        adapter = LLMProviderAdapter(logged_provider)
        extractor = EntityExtractor(llm=adapter)

        # Process parent chunks as representative documents
        source_texts = all_parents.get("content", []) if has_parents else all_children["content"]
        source_paths = (
            all_parents.get("source_path", [""] * len(source_texts))
            if has_parents
            else all_children.get("source_path", [""] * len(source_texts))
        )

        for i in range(len(source_texts)):
            # Memory safety check every 25 documents
            if i > 0 and i % 25 == 0:
                is_safe, mem_pct = _check_memory_safe()
                if not is_safe:
                    logger.warning(f"Memory at {mem_pct:.1f}% — pausing Phase 4...")
                    if not _wait_for_memory(timeout=120):
                        logger.error("Memory did not recover — stopping Phase 4")
                        quota_hit = True
                        break

            text = source_texts[i][:10000]
            doc_id = hashlib.sha256(text[:5000].encode()).hexdigest()[:16]
            source_short = Path(source_paths[i]).name if source_paths[i] else doc_id[:12]

            logger.info(f"Document {i + 1}/{len(source_texts)} [{source_short}]")

            loop = asyncio.new_event_loop()
            try:
                entities, relationships = loop.run_until_complete(extractor.extract(text, doc_id))
            except QuotaExhaustedError:
                logger.warning("Quota exhausted — stopping Phase 4")
                quota_hit = True
                break
            except Exception as e:
                logger.warning(f"  LLM extraction failed: {e} — falling back to regex")
                entities, relationships = extractor._extract_with_patterns(text, doc_id)
            finally:
                loop.close()

            if entities or relationships:
                graph.add_from_extraction(entities, relationships)
                stats.entities_extracted += len(entities)
                stats.relationships_extracted += len(relationships)

                ent_names = [e.name for e in entities[:5]]
                logger.info(
                    f"  Found {len(entities)} entities, "
                    f"{len(relationships)} rels: {', '.join(ent_names)}"
                )
            else:
                logger.info("  No entities found")

            if (i + 1) % 25 == 0:
                gc.collect()

            # Check quota
            if logged_provider.quota_exhausted:
                logger.warning("Quota exhausted — stopping Phase 4")
                quota_hit = True
                break

        if not quota_hit:
            stats_after = graph.get_stats()
            logger.info(
                f"Phase 4 complete: +{stats.entities_extracted} entities, "
                f"+{stats.relationships_extracted} relationships"
            )
            logger.info(
                f"Graph now: {stats_after['total_entities']} entities, "
                f"{stats_after['total_relationships']} relationships"
            )

    # ── Write Back to LanceDB ───────────────────────────────────────
    # Always write partial progress — don't lose successful work
    has_changes = (
        stats.context_generated > 0 or stats.summaries_generated > 0 or stats.chunks_reembedded > 0
    )

    if has_changes:
        logger.info("")
        logger.info("=" * 65)
        logger.info("WRITING BACK TO DATABASE")
        logger.info("=" * 65)

        if any(p in phases for p in [1, 2]):
            logger.info("Swapping child_chunks table...")
            child_arrow = pa.table(all_children)
            logger.info(f"  {child_arrow.num_rows} rows, {child_arrow.num_columns} columns")
            db.drop_table("child_chunks")
            db.create_table("child_chunks", child_arrow)

            # Rebuild FTS index
            try:
                db.open_table("child_chunks").create_fts_index("content", replace=True)
                logger.info("  FTS index rebuilt on child_chunks")
            except Exception as e:
                logger.warning(f"  FTS rebuild failed (non-fatal): {e}")

        if 3 in phases and has_parents and stats.summaries_generated > 0:
            logger.info("Swapping parent_chunks table...")
            parent_arrow = pa.table(all_parents)
            logger.info(f"  {parent_arrow.num_rows} rows, {parent_arrow.num_columns} columns")
            db.drop_table("parent_chunks")
            db.create_table("parent_chunks", parent_arrow)
            logger.info("  Parent chunks updated")
    else:
        logger.info("No changes to write (no successful LLM calls)")

    # ── Final Report ────────────────────────────────────────────────
    status = "complete" if not quota_hit else "interrupted_quota"

    logger.info("")
    logger.info("=" * 65)
    logger.info(f"BACKFILL {'COMPLETE' if not quota_hit else 'INTERRUPTED (quota exhausted)'}")
    logger.info("=" * 65)
    logger.info(stats.summary())
    logger.info(
        f"LLM calls: {logged_provider.call_count} total, "
        f"{logged_provider.failures} failed, "
        f"{logged_provider.total_time:.1f}s total LLM time"
    )
    if quota_hit:
        logger.info("Run again with --resume after quota resets to continue.")
    logger.info(f"Full log: {LOG_FILE}")
    logger.info("=" * 65)

    # Clear checkpoint only on full success
    if not quota_hit:
        _clear_checkpoint()

    return {
        "status": status,
        "elapsed_seconds": round(stats.elapsed(), 1),
        "context_generated": stats.context_generated,
        "context_failed": stats.context_failed,
        "summaries_generated": stats.summaries_generated,
        "summaries_failed": stats.summaries_failed,
        "chunks_reembedded": stats.chunks_reembedded,
        "entities_extracted": stats.entities_extracted,
        "relationships_extracted": stats.relationships_extracted,
        "llm_calls": logged_provider.call_count,
        "llm_failures": logged_provider.failures,
        "llm_total_time": round(logged_provider.total_time, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-enrich CoreRag database with LLM-powered quality enhancements"
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="gemini-cli",
        help="LLM provider (default: gemini-cli)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model name (default: auto per provider — qwen3:32b for ollama, gemini-2.5-pro for gemini-cli)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument(
        "--phases",
        type=int,
        nargs="+",
        choices=[1, 2, 3, 4],
        default=None,
        help="Phases to run (1=context, 2=embed, 3=summaries, 4=graph). Default: all",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Max concurrent LLM calls (default: 2)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Embedding batch size (default: 32)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Resume from checkpoint if available (default: true)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore checkpoint and start fresh",
    )
    parser.add_argument(
        "--max-chunks-per-call",
        type=int,
        default=None,
        help="Max chunks per batched LLM call (default: 50 cloud, 5 local)",
    )
    args = parser.parse_args()

    result = backfill_enrichment(
        provider_name=args.provider,
        model=args.model,
        dry_run=args.dry_run,
        phases=args.phases,
        concurrency=args.concurrency,
        batch_size=args.batch_size,
        resume=not args.no_resume,
        max_chunks_per_call=args.max_chunks_per_call,
    )

    if result["status"] in ("complete", "interrupted_quota"):
        logger.info(f"Result: {result}")


if __name__ == "__main__":
    main()
