"""
Hardware monitoring for CoreRag.

Monitors CPU, memory, and temperature to ensure safe operation
on Apple Silicon M4 Max.
"""

import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

import psutil

logger = logging.getLogger(__name__)


class SafetyLevel(Enum):
    """System safety levels."""

    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


@dataclass
class SystemStatus:
    """Current system resource status."""

    memory_used_gb: float
    memory_total_gb: float
    memory_percent: float
    cpu_percent: float
    cpu_temp_celsius: Optional[float]
    gpu_utilization: Optional[float]
    safety_level: SafetyLevel
    warnings: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class HardwareMonitor:
    """
    Monitor hardware resources and enforce safety limits.

    Designed for Apple Silicon M4 Max with 48GB unified memory.

    Usage:
        monitor = HardwareMonitor()
        monitor.start()

        if monitor.is_safe_to_proceed():
            do_heavy_work()
        else:
            wait_or_reduce_load()

        monitor.stop()
    """

    # Thresholds (GB for memory, Celsius for temp)
    MEMORY_WARNING_GB = 32
    MEMORY_CRITICAL_GB = 40
    MEMORY_EMERGENCY_GB = 44

    TEMP_WARM_C = 80
    TEMP_HOT_C = 90
    TEMP_CRITICAL_C = 100

    def __init__(
        self,
        check_interval_seconds: float = 5.0,
        on_warning: Optional[Callable[["SystemStatus"], None]] = None,
        on_critical: Optional[Callable[["SystemStatus"], None]] = None,
        on_emergency: Optional[Callable[["SystemStatus"], None]] = None,
    ):
        """
        Initialize hardware monitor.

        Args:
            check_interval_seconds: How often to check system status
            on_warning: Callback for warning level
            on_critical: Callback for critical level
            on_emergency: Callback for emergency level
        """
        self.check_interval = check_interval_seconds
        self.on_warning = on_warning
        self.on_critical = on_critical
        self.on_emergency = on_emergency

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._current_status: Optional[SystemStatus] = None
        self._lock = threading.Lock()
        self._throttle_callbacks: List[Callable[[SafetyLevel], None]] = []

    def start(self) -> None:
        """Start background monitoring."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("Hardware monitor started")

    def stop(self) -> None:
        """Stop background monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("Hardware monitor stopped")

    def get_status(self) -> SystemStatus:
        """Get current system status (performs a fresh check)."""
        return self._check_system()

    def is_safe_to_proceed(self, require_level: SafetyLevel = SafetyLevel.WARNING) -> bool:
        """
        Check if it's safe to start new heavy work.

        Args:
            require_level: Minimum safety level required (WARNING allows warning state)

        Returns:
            True if safe to proceed
        """
        status = self.get_status()

        level_order = [
            SafetyLevel.NORMAL,
            SafetyLevel.WARNING,
            SafetyLevel.CRITICAL,
            SafetyLevel.EMERGENCY,
        ]

        current_idx = level_order.index(status.safety_level)
        required_idx = level_order.index(require_level)

        return current_idx <= required_idx

    def wait_for_safe(self, timeout_seconds: float = 300) -> bool:
        """
        Block until system is safe to proceed.

        Args:
            timeout_seconds: Maximum time to wait

        Returns:
            True if became safe, False if timeout
        """
        start = time.time()
        while time.time() - start < timeout_seconds:
            if self.is_safe_to_proceed():
                return True
            time.sleep(5)
            logger.info("Waiting for system resources to free up...")
        return False

    def register_throttle_callback(self, callback: Callable[[SafetyLevel], None]) -> None:
        """Register callback for automatic throttling on level changes."""
        self._throttle_callbacks.append(callback)

    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        last_level = SafetyLevel.NORMAL

        while self._running:
            try:
                status = self._check_system()

                with self._lock:
                    self._current_status = status

                # Trigger callbacks on level changes
                if status.safety_level != last_level:
                    self._handle_level_change(last_level, status)
                    last_level = status.safety_level

                # Log warnings
                for warning in status.warnings:
                    logger.warning(warning)

            except Exception as e:
                logger.error(f"Monitor error: {e}")

            time.sleep(self.check_interval)

    def _check_system(self) -> SystemStatus:
        """Check all system metrics."""
        warnings: List[str] = []
        safety_level = SafetyLevel.NORMAL

        # Memory
        mem = psutil.virtual_memory()
        memory_used_gb = mem.used / (1024**3)
        memory_total_gb = mem.total / (1024**3)

        if memory_used_gb > self.MEMORY_EMERGENCY_GB:
            safety_level = SafetyLevel.EMERGENCY
            warnings.append(f"EMERGENCY: Memory at {memory_used_gb:.1f}GB")
        elif memory_used_gb > self.MEMORY_CRITICAL_GB:
            safety_level = SafetyLevel.CRITICAL
            warnings.append(f"CRITICAL: Memory at {memory_used_gb:.1f}GB")
        elif memory_used_gb > self.MEMORY_WARNING_GB:
            safety_level = SafetyLevel.WARNING
            warnings.append(f"WARNING: Memory at {memory_used_gb:.1f}GB")

        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)

        # Temperature (macOS specific)
        cpu_temp = self._get_cpu_temp()
        if cpu_temp:
            if cpu_temp > self.TEMP_CRITICAL_C:
                safety_level = SafetyLevel.EMERGENCY
                warnings.append(f"EMERGENCY: CPU temp at {cpu_temp}°C")
            elif cpu_temp > self.TEMP_HOT_C:
                if safety_level.value < SafetyLevel.CRITICAL.value:
                    safety_level = SafetyLevel.CRITICAL
                warnings.append(f"CRITICAL: CPU temp at {cpu_temp}°C - cooling down")
            elif cpu_temp > self.TEMP_WARM_C:
                if safety_level.value < SafetyLevel.WARNING.value:
                    safety_level = SafetyLevel.WARNING
                warnings.append(f"WARNING: CPU temp at {cpu_temp}°C")

        # GPU utilization (if available)
        gpu_util = self._get_gpu_utilization()

        return SystemStatus(
            memory_used_gb=memory_used_gb,
            memory_total_gb=memory_total_gb,
            memory_percent=mem.percent,
            cpu_percent=cpu_percent,
            cpu_temp_celsius=cpu_temp,
            gpu_utilization=gpu_util,
            safety_level=safety_level,
            warnings=warnings,
            timestamp=time.time(),
        )

    def _get_cpu_temp(self) -> Optional[float]:
        """Get CPU temperature on macOS."""
        # Try osx-cpu-temp first (doesn't require sudo)
        try:
            result = subprocess.run(
                ["osx-cpu-temp"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                return float(result.stdout.strip().replace("°C", ""))
        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            pass

        # Fallback: try powermetrics (requires sudo, may not work)
        try:
            result = subprocess.run(
                [
                    "sudo",
                    "powermetrics",
                    "-n",
                    "1",
                    "-i",
                    "100",
                    "--samplers",
                    "smc",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.split("\n"):
                if "CPU die temperature" in line:
                    temp = float(line.split(":")[1].strip().replace(" C", ""))
                    return temp
        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            pass

        return None

    def _get_gpu_utilization(self) -> Optional[float]:
        """Get GPU utilization on macOS (Apple Silicon)."""
        # This is harder to get without sudo
        # For now, return None - can be enhanced later
        return None

    def _handle_level_change(self, old_level: SafetyLevel, status: SystemStatus) -> None:
        """Handle safety level changes."""
        new_level = status.safety_level

        logger.warning(f"Safety level changed: {old_level.value} -> {new_level.value}")

        # Notify throttle callbacks
        for callback in self._throttle_callbacks:
            try:
                callback(new_level)
            except Exception as e:
                logger.error(f"Throttle callback error: {e}")

        # Call registered handlers
        if new_level == SafetyLevel.WARNING and self.on_warning:
            self.on_warning(status)
        elif new_level == SafetyLevel.CRITICAL and self.on_critical:
            self.on_critical(status)
        elif new_level == SafetyLevel.EMERGENCY and self.on_emergency:
            self.on_emergency(status)
