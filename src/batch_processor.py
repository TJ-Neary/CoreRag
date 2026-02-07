import asyncio
import gc
import logging
import threading
import time
from pathlib import Path

import psutil

from src.config import INBOX_PATH, STATE_DIR
from src.processor import process_document
from src.utils.queue_manager import Priority, QueueManager

logger = logging.getLogger(__name__)

MEMORY_PAUSE_THRESHOLD = 92  # Pause at this % RAM
MEMORY_RESUME_THRESHOLD = 88  # Resume when below this %
MEMORY_CHECK_INTERVAL = 2  # Seconds between checks while paused


class BatchProcessor:
    """Processes all files in the inbox as a single batch with progress tracking."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._pause_requested = False
        self._stop_requested = False
        self._progress = {
            "status": "idle",
            "total": 0,
            "processed": 0,
            "current_file": "",
            "errors": [],
            "memory_pct": 0,
            "paused_reason": "",
        }

        # QueueManager for persistent job tracking and retry support
        self._queue_manager = QueueManager(
            state_dir=STATE_DIR / "queue",
            rate_limit=5.0,
            burst_limit=10,
        )
        self._queue_manager.register_handler("ingest", self._handle_ingest_job)

    def get_progress(self) -> dict:
        with self._lock:
            return dict(self._progress)

    def scan_inbox(self) -> list[Path]:
        """Lists all non-hidden files in INBOX_PATH."""
        if not INBOX_PATH.exists():
            return []
        return sorted(f for f in INBOX_PATH.iterdir() if f.is_file() and not f.name.startswith("."))

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def pause(self) -> None:
        with self._lock:
            if self._running:
                self._pause_requested = True
                logger.info("Batch pause requested by user.")

    def resume(self) -> None:
        with self._lock:
            self._pause_requested = False
            logger.info("Batch resume requested by user.")

    def stop(self) -> None:
        with self._lock:
            if self._running:
                self._stop_requested = True
                self._pause_requested = False  # Unpause so the loop can exit
                logger.info("Batch stop requested by user.")

    def process_all(self) -> None:
        """Iterates inbox files, processes each, and updates progress counters."""
        with self._lock:
            if self._running:
                logger.warning("Batch already running, ignoring duplicate start.")
                return
            self._running = True
            self._pause_requested = False
            self._stop_requested = False

        files = self.scan_inbox()

        with self._lock:
            self._progress = {
                "status": "processing",
                "total": len(files),
                "processed": 0,
                "current_file": "",
                "errors": [],
                "memory_pct": psutil.virtual_memory().percent,
                "paused_reason": "",
            }

        if not files:
            with self._lock:
                self._progress["status"] = "complete"
                self._running = False
            return

        for i, file_path in enumerate(files):
            # Check for stop request
            with self._lock:
                if self._stop_requested:
                    self._progress["status"] = "stopped"
                    self._progress["current_file"] = ""
                    self._progress["paused_reason"] = (
                        f"Stopped by user after {i} of {len(files)} files"
                    )
                    self._running = False
                    logger.info(f"Batch stopped by user after {i} files.")
                    return

            # Check for user-requested pause
            while True:
                with self._lock:
                    if self._stop_requested:
                        break
                    if not self._pause_requested:
                        break
                    self._progress["status"] = "paused"
                    self._progress["paused_reason"] = "Paused by user"
                    self._progress["memory_pct"] = psutil.virtual_memory().percent
                time.sleep(1)

            # Re-check stop after coming out of pause
            with self._lock:
                if self._stop_requested:
                    self._progress["status"] = "stopped"
                    self._progress["current_file"] = ""
                    self._progress["paused_reason"] = (
                        f"Stopped by user after {i} of {len(files)} files"
                    )
                    self._running = False
                    logger.info(f"Batch stopped by user after {i} files.")
                    return
                self._progress["status"] = "processing"
                self._progress["paused_reason"] = ""

            # Memory safety check before each file
            mem = psutil.virtual_memory().percent
            with self._lock:
                self._progress["memory_pct"] = mem

            if mem > MEMORY_PAUSE_THRESHOLD:
                self._wait_for_safe_memory()

            with self._lock:
                self._progress["current_file"] = file_path.name

            logger.info(f"Batch [{i + 1}/{len(files)}]: {file_path.name}")

            try:
                asyncio.run(process_document(file_path))
            except Exception as e:
                logger.error(f"Error processing {file_path.name}: {e}", exc_info=True)
                with self._lock:
                    self._progress["errors"].append({"file": file_path.name, "error": str(e)})

            with self._lock:
                self._progress["processed"] = i + 1
                self._progress["memory_pct"] = psutil.virtual_memory().percent

            # Free extraction buffers between files
            gc.collect()

        with self._lock:
            self._progress["status"] = "complete"
            self._progress["current_file"] = ""
            self._progress["memory_pct"] = psutil.virtual_memory().percent
            self._progress["paused_reason"] = ""
            self._running = False

        logger.info("Batch processing complete.")

    def _wait_for_safe_memory(self) -> None:
        """Block until memory drops below resume threshold or stop is requested."""
        while psutil.virtual_memory().percent > MEMORY_RESUME_THRESHOLD:
            with self._lock:
                if self._stop_requested:
                    return
                mem = psutil.virtual_memory().percent
                self._progress["status"] = "paused"
                self._progress["paused_reason"] = (
                    f"Memory at {mem:.0f}%, waiting for <{MEMORY_RESUME_THRESHOLD}%"
                )
                self._progress["memory_pct"] = mem
            logger.warning(f"Analysis paused: memory at {mem:.0f}%")
            gc.collect()
            time.sleep(MEMORY_CHECK_INTERVAL)

        with self._lock:
            self._progress["status"] = "processing"
            self._progress["paused_reason"] = ""

    def _handle_ingest_job(self, payload: dict) -> dict:
        """Handler for QueueManager ingest jobs. Wraps process_document with memory safety."""
        file_path = Path(payload["file_path"])
        if not file_path.exists():
            return {"status": "skipped", "reason": "file not found"}

        # Memory safety check
        mem = psutil.virtual_memory().percent
        if mem > MEMORY_PAUSE_THRESHOLD:
            self._wait_for_safe_memory()

        asyncio.run(process_document(file_path))
        gc.collect()
        return {"status": "completed", "file": file_path.name}

    def process_queued(self, workers: int = 2) -> None:
        """
        Process inbox files using QueueManager for persistent state and retry.

        Alternative to process_all() — adds:
        - Persistent job state (survives crashes)
        - Automatic retry with backoff (up to 3 attempts)
        - Priority-based ordering
        - Rate limiting (5 files/sec)
        """
        files = self.scan_inbox()
        if not files:
            logger.info("No files to process.")
            return

        for f in files:
            self._queue_manager.add_job(
                job_type="ingest",
                payload={"file_path": str(f)},
                priority=Priority.NORMAL,
                max_attempts=3,
            )

        logger.info(f"Queued {len(files)} files for processing with {workers} workers")
        self._queue_manager.start(workers=workers)

    def stop_queued(self) -> None:
        """Stop queued processing gracefully."""
        self._queue_manager.stop(wait=True, timeout=30.0)

    def get_queue_stats(self) -> dict:
        """Get QueueManager statistics."""
        return self._queue_manager.get_stats()
