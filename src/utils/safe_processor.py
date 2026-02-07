"""
Safe processing wrapper with automatic throttling and memory management.

Provides a high-level interface for processing workloads safely.

Key Features:
- Checks psutil.virtual_memory().percent before heavy jobs
- Pauses ingestion at >75% RAM usage
- Prioritizes user-facing queries over background indexing
"""

import gc
import logging
import threading
from contextlib import contextmanager
from enum import Enum
from typing import Any, Callable, Generator, Iterable, List, Optional, TypeVar

import psutil

from src.config import SAFE_MEMORY_PAUSE_PCT, SAFE_MEMORY_RESUME_PCT
from src.utils.hardware_monitor import HardwareMonitor, SystemStatus
from src.utils.throttle_controller import ThrottleController, ThrottleSettings

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class JobPriority(Enum):
    """Job priority levels for resource allocation."""

    USER_QUERY = 1  # Highest - user is waiting
    INTERACTIVE = 2  # User-initiated but not blocking
    BACKGROUND = 3  # Background indexing, sync
    MAINTENANCE = 4  # Cleanup, optimization


# Memory thresholds as percentages
MEMORY_PAUSE_THRESHOLD = SAFE_MEMORY_PAUSE_PCT
MEMORY_WARNING_THRESHOLD = 70  # Start reducing batch sizes
MEMORY_RESUME_THRESHOLD = SAFE_MEMORY_RESUME_PCT


class IngestionController:
    """
    Controls ingestion flow based on memory pressure.

    Pauses background indexing at >75% RAM to ensure:
    - User queries always get through
    - System remains responsive
    - No OOM crashes
    """

    def __init__(self):
        self._paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially
        self._lock = threading.Lock()
        self._active_user_queries = 0

    def check_memory_pressure(self) -> tuple[bool, float]:
        """
        Check current memory usage percentage.

        Returns:
            Tuple of (should_pause, memory_percent)
        """
        mem = psutil.virtual_memory()
        memory_percent = mem.percent
        should_pause = memory_percent > MEMORY_PAUSE_THRESHOLD
        return should_pause, memory_percent

    def should_pause_ingestion(self) -> bool:
        """
        Check if ingestion should be paused.

        Returns True if:
        - Memory usage >75%
        - User queries are active (priority)
        """
        should_pause, mem_pct = self.check_memory_pressure()

        with self._lock:
            # Always pause for user queries
            if self._active_user_queries > 0:
                if not self._paused:
                    logger.info(
                        f"Pausing ingestion: {self._active_user_queries} user queries active"
                    )
                    self._paused = True
                    self._pause_event.clear()
                return True

            # Pause for memory pressure
            if should_pause:
                if not self._paused:
                    logger.warning(
                        f"Pausing ingestion: Memory at {mem_pct:.1f}% (>{MEMORY_PAUSE_THRESHOLD}%)"
                    )
                    self._paused = True
                    self._pause_event.clear()
                return True

            # Resume if below threshold
            if self._paused and mem_pct < MEMORY_RESUME_THRESHOLD:
                logger.info(
                    f"Resuming ingestion: Memory at {mem_pct:.1f}% (<{MEMORY_RESUME_THRESHOLD}%)"
                )
                self._paused = False
                self._pause_event.set()

            return self._paused

    def wait_for_resume(self, timeout: float = 60.0) -> bool:
        """
        Wait for ingestion to be allowed to resume.

        Args:
            timeout: Maximum seconds to wait

        Returns:
            True if resumed, False if timeout
        """
        return self._pause_event.wait(timeout=timeout)

    @contextmanager
    def user_query_context(self):
        """
        Context manager for user-facing queries.

        Ensures background ingestion pauses while user queries run.
        """
        with self._lock:
            self._active_user_queries += 1

        try:
            yield
        finally:
            with self._lock:
                self._active_user_queries -= 1
                # Check if we can resume
                if self._active_user_queries == 0:
                    self.should_pause_ingestion()  # Re-evaluate

    @property
    def is_paused(self) -> bool:
        return self._paused

    def get_status(self) -> dict:
        """Get current ingestion controller status."""
        should_pause, mem_pct = self.check_memory_pressure()
        return {
            "paused": self._paused,
            "memory_percent": mem_pct,
            "active_user_queries": self._active_user_queries,
            "pause_threshold": MEMORY_PAUSE_THRESHOLD,
            "resume_threshold": MEMORY_RESUME_THRESHOLD,
        }


# Global ingestion controller instance
_ingestion_controller: Optional[IngestionController] = None


def get_ingestion_controller() -> IngestionController:
    """Get or create the global ingestion controller."""
    global _ingestion_controller
    if _ingestion_controller is None:
        _ingestion_controller = IngestionController()
    return _ingestion_controller


class MemoryManager:
    """
    Proactive memory management for large processing jobs.
    """

    def __init__(self, monitor: HardwareMonitor):
        self.monitor = monitor
        self._tracked_objects: List[Any] = []
        self.ingestion = get_ingestion_controller()

    def track(self, obj: Any) -> None:
        """Track an object for later cleanup."""
        self._tracked_objects.append(obj)

    def cleanup(self, force: bool = False) -> None:
        """
        Clean up tracked objects and run garbage collection.

        Args:
            force: If True, cleanup regardless of memory pressure
        """
        status = self.monitor.get_status()
        mem = psutil.virtual_memory()

        # Cleanup if over 70% or absolute threshold
        if force or mem.percent > MEMORY_WARNING_THRESHOLD or status.memory_used_gb > 30:
            # Clear tracked objects
            self._tracked_objects.clear()

            # Force garbage collection
            gc.collect()

            # Try to clear GPU caches if available
            self._clear_gpu_cache()

            new_status = self.monitor.get_status()
            freed = status.memory_used_gb - new_status.memory_used_gb
            if freed > 0:
                logger.info(
                    f"Memory cleanup freed {freed:.1f}GB. "
                    f"Now at {new_status.memory_used_gb:.1f}GB"
                )

    def _clear_gpu_cache(self) -> None:
        """Clear GPU/MPS cache if PyTorch is available."""
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except ImportError:
            pass


class SafeProcessor:
    """
    High-level wrapper for safe processing with automatic throttling.

    Combines hardware monitoring, throttling, and memory management
    into a simple interface.

    Key Features:
    - Checks psutil.virtual_memory().percent before heavy jobs
    - Pauses ingestion at >75% RAM
    - Prioritizes user-facing queries over background work

    Usage:
        processor = SafeProcessor()

        # For background ingestion (will pause at >75% RAM):
        for result in processor.process_safely(files, process_file):
            db.add(result)

        # For user queries (always allowed, pauses background work):
        with processor.user_query() as settings:
            results = search(query)

        # Or with context manager:
        with processor.safe_batch() as settings:
            results = process_with_settings(data, settings)
    """

    def __init__(
        self,
        base_batch_size: int = 32,
        base_workers: int = 8,
        auto_start: bool = True,
    ):
        """
        Initialize safe processor.

        Args:
            base_batch_size: Normal batch size for embeddings
            base_workers: Normal worker count
            auto_start: Whether to start monitoring immediately
        """
        self.monitor = HardwareMonitor(
            on_warning=self._on_warning,
            on_critical=self._on_critical,
            on_emergency=self._on_emergency,
        )
        self.throttle = ThrottleController(
            self.monitor,
            base_embedding_batch=base_batch_size,
            base_workers=base_workers,
        )
        self.memory = MemoryManager(self.monitor)
        self.ingestion = get_ingestion_controller()

        if auto_start:
            self.monitor.start()

    def __del__(self):
        """Stop monitoring on cleanup."""
        self.stop()

    def stop(self) -> None:
        """Stop the processor and monitoring."""
        self.monitor.stop()

    def get_status(self) -> SystemStatus:
        """Get current system status."""
        return self.monitor.get_status()

    def get_settings(self) -> ThrottleSettings:
        """Get current throttled settings."""
        return self.throttle.get_settings()

    def is_safe(self) -> bool:
        """Check if it's safe to proceed with heavy work."""
        # Check both hardware monitor and percentage-based threshold
        mem = psutil.virtual_memory()
        if mem.percent > MEMORY_PAUSE_THRESHOLD:
            return False
        return self.monitor.is_safe_to_proceed()

    def is_safe_for_ingestion(self) -> bool:
        """
        Check if it's safe to proceed with background ingestion.

        More strict than is_safe() - also checks for active user queries.
        """
        if self.ingestion.should_pause_ingestion():
            return False
        return self.is_safe()

    def wait_for_safe(self, timeout_seconds: float = 60) -> bool:
        """Wait until system is safe to proceed."""
        return self.monitor.wait_for_safe(timeout_seconds)

    def wait_for_ingestion_safe(self, timeout_seconds: float = 60) -> bool:
        """Wait until it's safe to resume background ingestion."""
        start = __import__("time").time()
        while __import__("time").time() - start < timeout_seconds:
            if self.is_safe_for_ingestion():
                return True
            self.ingestion.wait_for_resume(timeout=5.0)
        return False

    @contextmanager
    def user_query(self):
        """
        Context manager for user-facing queries.

        User queries always get priority - background ingestion pauses.

        Usage:
            with processor.user_query():
                results = search(query)  # Guaranteed resources
        """
        with self.ingestion.user_query_context():
            yield self.throttle.get_settings()

    @contextmanager
    def safe_batch(self, priority: JobPriority = JobPriority.BACKGROUND):
        """
        Context manager for safe batch processing.

        Yields current throttle settings and cleans up memory after.

        Args:
            priority: Job priority level (USER_QUERY bypasses pause)

        Usage:
            with processor.safe_batch() as settings:
                batch_size = settings.embedding_batch_size
                results = embed(data, batch_size=batch_size)
        """
        # Check memory percentage before starting
        mem = psutil.virtual_memory()
        if mem.percent > MEMORY_PAUSE_THRESHOLD and priority != JobPriority.USER_QUERY:
            logger.warning(
                f"Memory at {mem.percent:.1f}% (>{MEMORY_PAUSE_THRESHOLD}%), "
                f"waiting for resources..."
            )
            if not self.wait_for_ingestion_safe(timeout_seconds=60):
                logger.error("System did not recover, proceeding carefully")

        # Wait if system is stressed
        if not self.monitor.is_safe_to_proceed():
            logger.warning("System under load, waiting...")
            if not self.monitor.wait_for_safe(timeout_seconds=60):
                logger.error("System did not recover, proceeding carefully")

        try:
            yield self.throttle.get_settings()
        finally:
            self.memory.cleanup()

    def process_safely(
        self,
        items: Iterable[T],
        process_func: Callable[[List[T]], Iterable[R]],
        batch_size: Optional[int] = None,
        priority: JobPriority = JobPriority.BACKGROUND,
    ) -> Generator[R, None, None]:
        """
        Process items with automatic throttling and safety checks.

        Respects memory pressure thresholds:
        - Pauses at >75% RAM usage
        - Resumes at <65% RAM usage
        - User queries always take priority

        Args:
            items: Items to process
            process_func: Function that processes a batch and returns results
            batch_size: Override batch size (or use throttled value)
            priority: Job priority (USER_QUERY bypasses pause)

        Yields:
            Results from process_func
        """
        current_batch: List[T] = []

        for item in items:
            # Check memory pressure between items for background jobs
            if priority != JobPriority.USER_QUERY:
                if self.ingestion.should_pause_ingestion():
                    logger.info("Ingestion paused, waiting for resources...")
                    self.ingestion.wait_for_resume(timeout=60)

            current_batch.append(item)

            # Get current throttled batch size
            effective_batch_size = batch_size or self.throttle.embedding_batch_size

            if len(current_batch) >= effective_batch_size:
                # Process this batch safely
                with self.safe_batch(priority=priority) as settings:
                    actual_size = min(len(current_batch), settings.embedding_batch_size)
                    batch_to_process = current_batch[:actual_size]

                    yield from process_func(batch_to_process)

                    current_batch = current_batch[actual_size:]

        # Process remaining items
        if current_batch:
            with self.safe_batch(priority=priority):
                yield from process_func(current_batch)

    def _on_warning(self, status: SystemStatus) -> None:
        """Handle warning level."""
        logger.warning(
            f"System warning: Memory at {status.memory_used_gb:.1f}GB. " "Reducing batch sizes."
        )
        self._send_notification(
            "CoreRag Warning",
            f"Memory at {status.memory_used_gb:.1f}GB - reducing load",
        )

    def _on_critical(self, status: SystemStatus) -> None:
        """Handle critical level."""
        logger.error(
            f"System critical: Memory at {status.memory_used_gb:.1f}GB. " "Pausing new work."
        )
        self._send_notification(
            "CoreRag Critical",
            "High resource usage - processing paused",
        )

    def _on_emergency(self, status: SystemStatus) -> None:
        """Handle emergency level."""
        logger.critical(
            f"System emergency: Memory at {status.memory_used_gb:.1f}GB! "
            "Stopping all processing."
        )
        self.memory.cleanup(force=True)
        self._send_notification(
            "CoreRag EMERGENCY",
            "Critical resource usage - stopping all work",
        )

    def _send_notification(self, title: str, message: str) -> None:
        """Send macOS desktop notification."""
        try:
            import subprocess

            script = f'display notification "{message}" with title "{title}" sound name "Ping"'
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=2,
            )
        except Exception as e:
            logger.debug(f"Could not send notification: {e}")


# Convenience function for one-off status checks
def check_system() -> SystemStatus:
    """Quick system status check without starting a monitor."""
    monitor = HardwareMonitor()
    return monitor.get_status()


def check_memory_before_job() -> tuple[bool, str]:
    """
    Check memory before starting a heavy job.

    Returns:
        Tuple of (is_safe, message)
    """
    mem = psutil.virtual_memory()
    mem_pct = mem.percent

    if mem_pct > MEMORY_PAUSE_THRESHOLD:
        return (
            False,
            f"Memory at {mem_pct:.1f}% - above {MEMORY_PAUSE_THRESHOLD}% threshold. Wait for resources.",
        )
    elif mem_pct > MEMORY_WARNING_THRESHOLD:
        return True, f"Memory at {mem_pct:.1f}% - approaching threshold. Consider smaller batches."
    else:
        return True, f"Memory at {mem_pct:.1f}% - safe to proceed."


def print_status() -> None:
    """Print current system status to console."""
    status = check_system()
    mem = psutil.virtual_memory()

    print(
        f"Memory: {status.memory_used_gb:.1f} / {status.memory_total_gb:.1f} GB ({mem.percent:.1f}%)"
    )
    print(f"  Pause Threshold: {MEMORY_PAUSE_THRESHOLD}%")
    print(f"  Resume Threshold: {MEMORY_RESUME_THRESHOLD}%")
    print(f"CPU: {status.cpu_percent}%")
    if status.cpu_temp_celsius:
        print(f"CPU Temp: {status.cpu_temp_celsius}°C")
    print(f"Safety Level: {status.safety_level.value}")

    # Check ingestion status
    ingestion = get_ingestion_controller()
    ing_status = ingestion.get_status()
    print(f"Ingestion: {'PAUSED' if ing_status['paused'] else 'RUNNING'}")
    if ing_status["active_user_queries"] > 0:
        print(f"  Active User Queries: {ing_status['active_user_queries']}")

    if status.warnings:
        for warning in status.warnings:
            print(f"  ⚠️  {warning}")
