"""
Automatic throttling based on system load.

Adjusts batch sizes and worker counts when system is under stress.
"""

import logging
from dataclasses import dataclass

from src.utils.hardware_monitor import HardwareMonitor, SafetyLevel

logger = logging.getLogger(__name__)


@dataclass
class ThrottleSettings:
    """Current throttle settings."""

    embedding_batch_size: int
    max_workers: int
    chunk_buffer_size: int
    safety_level: str


class ThrottleController:
    """
    Automatically adjust processing parameters based on system load.

    Registers with HardwareMonitor and adjusts settings when
    safety levels change.
    """

    def __init__(
        self,
        monitor: HardwareMonitor,
        base_embedding_batch: int = 32,
        base_workers: int = 8,
        base_chunk_buffer: int = 1000,
    ):
        """
        Initialize throttle controller.

        Args:
            monitor: HardwareMonitor instance
            base_embedding_batch: Normal embedding batch size
            base_workers: Normal worker count
            base_chunk_buffer: Normal chunk buffer size
        """
        self.monitor = monitor

        # Base settings (full speed)
        self.base_embedding_batch = base_embedding_batch
        self.base_workers = base_workers
        self.base_chunk_buffer = base_chunk_buffer

        # Current settings (adjusted by throttling)
        self.embedding_batch_size = base_embedding_batch
        self.max_workers = base_workers
        self.chunk_buffer_size = base_chunk_buffer

        # Register for automatic updates
        monitor.register_throttle_callback(self._on_level_change)

    def _on_level_change(self, level: SafetyLevel) -> None:
        """Adjust settings based on safety level."""

        if level == SafetyLevel.NORMAL:
            # Full speed
            self.embedding_batch_size = self.base_embedding_batch
            self.max_workers = self.base_workers
            self.chunk_buffer_size = self.base_chunk_buffer

        elif level == SafetyLevel.WARNING:
            # Reduce by 25%
            self.embedding_batch_size = int(self.base_embedding_batch * 0.75)
            self.max_workers = max(4, int(self.base_workers * 0.75))
            self.chunk_buffer_size = int(self.base_chunk_buffer * 0.75)

        elif level == SafetyLevel.CRITICAL:
            # Reduce by 50%
            self.embedding_batch_size = int(self.base_embedding_batch * 0.5)
            self.max_workers = max(2, int(self.base_workers * 0.5))
            self.chunk_buffer_size = int(self.base_chunk_buffer * 0.5)

        elif level == SafetyLevel.EMERGENCY:
            # Minimal processing
            self.embedding_batch_size = 8
            self.max_workers = 1
            self.chunk_buffer_size = 100

        logger.info(
            f"Throttle adjusted to {level.value}: "
            f"batch={self.embedding_batch_size}, "
            f"workers={self.max_workers}, "
            f"buffer={self.chunk_buffer_size}"
        )

    def get_settings(self) -> ThrottleSettings:
        """Get current throttled settings."""
        return ThrottleSettings(
            embedding_batch_size=self.embedding_batch_size,
            max_workers=self.max_workers,
            chunk_buffer_size=self.chunk_buffer_size,
            safety_level=self.monitor.get_status().safety_level.value,
        )

    def reset_to_base(self) -> None:
        """Reset to base settings (for testing or manual override)."""
        self.embedding_batch_size = self.base_embedding_batch
        self.max_workers = self.base_workers
        self.chunk_buffer_size = self.base_chunk_buffer
        logger.info("Throttle reset to base settings")
