# Hardware Safety Monitoring

> **Status**: ✅ Implemented | See `src/utils/hardware_monitor.py, src/utils/safe_processor.py` for implementation

> Protect your M4 Max from overheating, memory exhaustion, and resource starvation.

---

## Overview

Running ML workloads locally can stress hardware. This framework provides:
- **Real-time monitoring** of CPU, GPU, memory, and temperature
- **Automatic throttling** when thresholds are exceeded
- **Graceful degradation** instead of crashes
- **Alerts** for dangerous conditions

---

## Safety Thresholds

### Memory Limits

| Level | Threshold | Action |
|-------|-----------|--------|
| Normal | < 32 GB | Continue normally |
| Warning | 32-40 GB | Log warning, reduce batch sizes |
| Critical | 40-44 GB | Pause new work, finish current |
| Emergency | > 44 GB | Stop all processing, free memory |

### CPU Temperature (Apple Silicon)

| Level | Threshold | Action |
|-------|-----------|--------|
| Normal | < 80°C | Continue normally |
| Warm | 80-90°C | Reduce parallelism |
| Hot | 90-100°C | Pause processing, cool down |
| Critical | > 100°C | Emergency stop |

### GPU Utilization

| Level | Threshold | Action |
|-------|-----------|--------|
| Normal | < 80% | Continue normally |
| High | 80-95% | Queue new work, don't overload |
| Saturated | > 95% | Wait for capacity |

---

## Monitoring Implementation

### Core Monitor Class

```python
# src/utils/hardware_monitor.py

import subprocess
import psutil
import threading
import time
from dataclasses import dataclass
from typing import Optional, Callable, List
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class SafetyLevel(Enum):
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
    warnings: List[str]
    timestamp: float


class HardwareMonitor:
    """
    Monitor hardware resources and enforce safety limits.

    Usage:
        monitor = HardwareMonitor()
        monitor.start()

        # Check before heavy operations
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
        on_warning: Optional[Callable[[SystemStatus], None]] = None,
        on_critical: Optional[Callable[[SystemStatus], None]] = None,
        on_emergency: Optional[Callable[[SystemStatus], None]] = None,
    ):
        self.check_interval = check_interval_seconds
        self.on_warning = on_warning
        self.on_critical = on_critical
        self.on_emergency = on_emergency

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._current_status: Optional[SystemStatus] = None
        self._lock = threading.Lock()

        # Callbacks for automatic throttling
        self._throttle_callbacks: List[Callable[[SafetyLevel], None]] = []

    def start(self):
        """Start background monitoring."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("Hardware monitor started")

    def stop(self):
        """Stop background monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        logger.info("Hardware monitor stopped")

    def get_status(self) -> SystemStatus:
        """Get current system status."""
        return self._check_system()

    def is_safe_to_proceed(self, require_level: SafetyLevel = SafetyLevel.WARNING) -> bool:
        """
        Check if it's safe to start new heavy work.

        Args:
            require_level: Minimum safety level required

        Returns:
            True if safe to proceed
        """
        status = self.get_status()

        level_order = [SafetyLevel.NORMAL, SafetyLevel.WARNING,
                       SafetyLevel.CRITICAL, SafetyLevel.EMERGENCY]

        current_idx = level_order.index(status.safety_level)
        required_idx = level_order.index(require_level)

        return current_idx <= required_idx

    def wait_for_safe(self, timeout_seconds: float = 300) -> bool:
        """
        Block until system is safe to proceed.

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

    def register_throttle_callback(self, callback: Callable[[SafetyLevel], None]):
        """Register callback for automatic throttling."""
        self._throttle_callbacks.append(callback)

    def _monitor_loop(self):
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
        warnings = []
        safety_level = SafetyLevel.NORMAL

        # Memory
        mem = psutil.virtual_memory()
        memory_used_gb = mem.used / (1024 ** 3)
        memory_total_gb = mem.total / (1024 ** 3)

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
            timestamp=time.time()
        )

    def _get_cpu_temp(self) -> Optional[float]:
        """Get CPU temperature on macOS."""
        try:
            # Use powermetrics (requires sudo) or osx-cpu-temp
            result = subprocess.run(
                ["sudo", "powermetrics", "-n", "1", "-i", "100", "--samplers", "smc"],
                capture_output=True,
                text=True,
                timeout=5
            )
            # Parse temperature from output
            for line in result.stdout.split("\n"):
                if "CPU die temperature" in line:
                    temp = float(line.split(":")[1].strip().replace(" C", ""))
                    return temp
        except Exception:
            pass

        # Fallback: try osx-cpu-temp if installed
        try:
            result = subprocess.run(
                ["osx-cpu-temp"],
                capture_output=True,
                text=True,
                timeout=2
            )
            return float(result.stdout.strip().replace("°C", ""))
        except Exception:
            return None

    def _get_gpu_utilization(self) -> Optional[float]:
        """Get GPU utilization on macOS (Apple Silicon)."""
        try:
            # Use powermetrics for GPU
            result = subprocess.run(
                ["sudo", "powermetrics", "-n", "1", "-i", "100", "--samplers", "gpu_power"],
                capture_output=True,
                text=True,
                timeout=5
            )
            for line in result.stdout.split("\n"):
                if "GPU Active" in line:
                    # Parse percentage
                    pct = float(line.split(":")[1].strip().replace("%", ""))
                    return pct
        except Exception:
            return None

    def _handle_level_change(self, old_level: SafetyLevel, status: SystemStatus):
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
```

---

## Automatic Throttling

### Batch Size Controller

```python
# src/utils/throttle_controller.py

from src.utils.hardware_monitor import HardwareMonitor, SafetyLevel


class ThrottleController:
    """
    Automatically adjust batch sizes based on system load.
    """

    def __init__(self, monitor: HardwareMonitor):
        self.monitor = monitor

        # Base settings
        self.base_embedding_batch = 32
        self.base_workers = 8
        self.base_chunk_buffer = 1000

        # Current settings (adjusted by throttling)
        self.embedding_batch_size = self.base_embedding_batch
        self.max_workers = self.base_workers
        self.chunk_buffer_size = self.base_chunk_buffer

        # Register for automatic updates
        monitor.register_throttle_callback(self._on_level_change)

    def _on_level_change(self, level: SafetyLevel):
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
            f"Throttle adjusted: batch={self.embedding_batch_size}, "
            f"workers={self.max_workers}, buffer={self.chunk_buffer_size}"
        )

    def get_current_settings(self) -> dict:
        """Get current throttled settings."""
        return {
            "embedding_batch_size": self.embedding_batch_size,
            "max_workers": self.max_workers,
            "chunk_buffer_size": self.chunk_buffer_size,
            "safety_level": self.monitor.get_status().safety_level.value
        }
```

---

## Memory Management

### Proactive Cleanup

```python
# src/utils/memory_manager.py

import gc
import sys
from typing import Any, List


class MemoryManager:
    """
    Proactive memory management for large processing jobs.
    """

    def __init__(self, monitor: HardwareMonitor):
        self.monitor = monitor
        self._tracked_objects: List[Any] = []

    def track(self, obj: Any):
        """Track an object for later cleanup."""
        self._tracked_objects.append(obj)

    def cleanup(self, force: bool = False):
        """
        Clean up tracked objects and run garbage collection.

        Args:
            force: If True, cleanup regardless of memory pressure
        """
        status = self.monitor.get_status()

        if force or status.memory_used_gb > 30:
            # Clear tracked objects
            self._tracked_objects.clear()

            # Force garbage collection
            gc.collect()

            # For PyTorch/MLX, clear caches
            try:
                import torch
                if torch.backends.mps.is_available():
                    torch.mps.empty_cache()
            except ImportError:
                pass

            logger.info(f"Memory cleanup complete. Now at {self.monitor.get_status().memory_used_gb:.1f}GB")

    def with_cleanup(self, func):
        """Decorator to cleanup after function execution."""
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            finally:
                self.cleanup()
        return wrapper


# Context manager for scoped cleanup
class MemoryScope:
    """Context manager for automatic memory cleanup."""

    def __init__(self, manager: MemoryManager):
        self.manager = manager

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.manager.cleanup()
        return False


# Usage example:
# with MemoryScope(memory_manager):
#     process_large_batch(files)
# # Memory automatically cleaned up
```

---

## Integration with Pipeline

### Safe Processing Wrapper

```python
# src/utils/safe_processor.py

from contextlib import contextmanager
from typing import Generator, TypeVar, Iterable

T = TypeVar('T')


class SafeProcessor:
    """
    Wrapper for safe processing with automatic throttling.
    """

    def __init__(self):
        self.monitor = HardwareMonitor()
        self.throttle = ThrottleController(self.monitor)
        self.memory = MemoryManager(self.monitor)
        self.monitor.start()

    def __del__(self):
        self.monitor.stop()

    @contextmanager
    def safe_batch(self):
        """Context manager for safe batch processing."""
        # Wait if system is stressed
        if not self.monitor.is_safe_to_proceed():
            logger.warning("System under load, waiting...")
            self.monitor.wait_for_safe(timeout_seconds=60)

        try:
            yield self.throttle.get_current_settings()
        finally:
            self.memory.cleanup()

    def process_with_throttling(
        self,
        items: Iterable[T],
        process_func,
        batch_size: int = None
    ) -> Generator[T, None, None]:
        """
        Process items with automatic throttling and safety checks.
        """
        batch_size = batch_size or self.throttle.embedding_batch_size
        batch = []

        for item in items:
            # Check safety before each batch
            if len(batch) >= batch_size:
                with self.safe_batch() as settings:
                    # Use throttled batch size
                    actual_batch_size = settings["embedding_batch_size"]
                    for result in process_func(batch[:actual_batch_size]):
                        yield result
                    batch = batch[actual_batch_size:]

            batch.append(item)

        # Process remaining
        if batch:
            with self.safe_batch():
                yield from process_func(batch)


# Usage in main code:
#
# processor = SafeProcessor()
#
# for result in processor.process_with_throttling(files, embed_files):
#     save_to_db(result)
```

---

## Alerting

### Desktop Notifications (macOS)

```python
# src/utils/alerts.py

import subprocess
from typing import Optional


def send_notification(
    title: str,
    message: str,
    sound: bool = True,
    subtitle: Optional[str] = None
):
    """Send macOS desktop notification."""
    script = f'''
    display notification "{message}" with title "{title}"
    '''
    if subtitle:
        script = f'''
        display notification "{message}" with title "{title}" subtitle "{subtitle}"
        '''
    if sound:
        script += ' sound name "Ping"'

    subprocess.run(["osascript", "-e", script], capture_output=True)


def alert_on_critical(status: SystemStatus):
    """Alert handler for critical status."""
    send_notification(
        title="PKM System Warning",
        message=f"Memory at {status.memory_used_gb:.1f}GB - reducing load",
        subtitle="Processing paused"
    )


def alert_on_emergency(status: SystemStatus):
    """Alert handler for emergency status."""
    send_notification(
        title="PKM System EMERGENCY",
        message="System resources critical - stopping all processing",
        sound=True
    )


# Register with monitor:
# monitor = HardwareMonitor(
#     on_critical=alert_on_critical,
#     on_emergency=alert_on_emergency
# )
```

---

## Logging & Metrics

### Resource Usage Log

```python
# src/utils/resource_logger.py

import json
from pathlib import Path
from datetime import datetime


class ResourceLogger:
    """Log resource usage over time."""

    def __init__(self, log_dir: Path = Path.home() / ".pkm" / "logs"):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = log_dir / f"resources_{datetime.now():%Y%m%d}.jsonl"

    def log(self, status: SystemStatus, operation: str = ""):
        """Log current status."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "memory_gb": status.memory_used_gb,
            "memory_pct": status.memory_percent,
            "cpu_pct": status.cpu_percent,
            "cpu_temp": status.cpu_temp_celsius,
            "gpu_pct": status.gpu_utilization,
            "safety_level": status.safety_level.value
        }

        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def get_summary(self, hours: int = 24) -> dict:
        """Get summary of recent resource usage."""
        # Read recent entries and calculate stats
        # (Implementation details...)
        pass
```

---

## Quick Reference

### Before Heavy Processing

```python
from src.utils.safe_processor import SafeProcessor

processor = SafeProcessor()

# This automatically:
# - Checks system safety
# - Waits if needed
# - Throttles batch sizes
# - Cleans up memory
# - Sends alerts on problems

for result in processor.process_with_throttling(files, process_file):
    db.add(result)
```

### Manual Checks

```python
from src.utils.hardware_monitor import HardwareMonitor

monitor = HardwareMonitor()
status = monitor.get_status()

print(f"Memory: {status.memory_used_gb:.1f} / {status.memory_total_gb:.1f} GB")
print(f"CPU: {status.cpu_percent}%")
print(f"Safety: {status.safety_level.value}")

if not monitor.is_safe_to_proceed():
    print("System stressed - wait before processing")
```

---

## Installation Requirements

```bash
# For temperature monitoring (optional)
brew install osx-cpu-temp

# For detailed metrics (requires sudo)
# powermetrics is built into macOS
```

---

*Hardware safety is non-negotiable. Always use SafeProcessor for heavy workloads.*
