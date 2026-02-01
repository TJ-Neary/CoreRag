"""
Health checks and status dashboard for PKM.

Provides system monitoring, diagnostics, and status reporting.
"""

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Component health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """Result of a health check."""
    name: str
    status: HealthStatus
    message: str
    latency_ms: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    details: Dict = field(default_factory=dict)


@dataclass
class SystemStatus:
    """Overall system status."""
    status: HealthStatus
    checks: List[HealthCheck]
    uptime_seconds: float
    version: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status.value,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "latency_ms": c.latency_ms,
                    "details": c.details
                }
                for c in self.checks
            ],
            "uptime_seconds": self.uptime_seconds,
            "version": self.version,
            "timestamp": self.timestamp
        }


class HealthChecker:
    """
    Run health checks on system components.

    Checks:
    - Vector database connectivity
    - Embedding model availability
    - Storage space
    - Memory usage
    - Background jobs
    - File system access
    """

    VERSION = "0.1.0"

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        state_dir: Optional[Path] = None
    ):
        """
        Initialize health checker.

        Args:
            data_dir: Data directory to check
            state_dir: State directory for health logs
        """
        self.data_dir = data_dir or Path.home() / ".pkm" / "data"
        self.state_dir = state_dir or Path.home() / ".pkm" / "health"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._start_time = time.time()
        self._check_registry: Dict[str, Callable] = {}

        # Register default checks
        self._register_default_checks()

    def register_check(
        self,
        name: str,
        check_func: Callable[[], HealthCheck]
    ) -> None:
        """Register a custom health check."""
        self._check_registry[name] = check_func

    def run_all_checks(self) -> SystemStatus:
        """Run all registered health checks."""
        checks = []
        overall_status = HealthStatus.HEALTHY

        for name, check_func in self._check_registry.items():
            try:
                result = check_func()
                checks.append(result)

                # Update overall status
                if result.status == HealthStatus.UNHEALTHY:
                    overall_status = HealthStatus.UNHEALTHY
                elif result.status == HealthStatus.DEGRADED and overall_status == HealthStatus.HEALTHY:
                    overall_status = HealthStatus.DEGRADED

            except Exception as e:
                checks.append(HealthCheck(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Check failed: {str(e)}",
                    latency_ms=0
                ))
                overall_status = HealthStatus.UNHEALTHY

        status = SystemStatus(
            status=overall_status,
            checks=checks,
            uptime_seconds=time.time() - self._start_time,
            version=self.VERSION
        )

        # Log status
        self._log_status(status)

        return status

    def run_check(self, name: str) -> HealthCheck:
        """Run a specific health check."""
        if name not in self._check_registry:
            return HealthCheck(
                name=name,
                status=HealthStatus.UNKNOWN,
                message=f"Check '{name}' not found",
                latency_ms=0
            )

        return self._check_registry[name]()

    def get_status_summary(self) -> str:
        """Get human-readable status summary."""
        status = self.run_all_checks()

        lines = [
            f"PKM System Status: {status.status.value.upper()}",
            f"Version: {status.version}",
            f"Uptime: {self._format_uptime(status.uptime_seconds)}",
            "",
            "Component Status:"
        ]

        for check in status.checks:
            icon = {
                HealthStatus.HEALTHY: "✅",
                HealthStatus.DEGRADED: "⚠️",
                HealthStatus.UNHEALTHY: "❌",
                HealthStatus.UNKNOWN: "❓"
            }[check.status]

            lines.append(f"  {icon} {check.name}: {check.message} ({check.latency_ms:.0f}ms)")

        return "\n".join(lines)

    def _register_default_checks(self) -> None:
        """Register default health checks."""
        self.register_check("database", self._check_database)
        self.register_check("storage", self._check_storage)
        self.register_check("memory", self._check_memory)
        self.register_check("embedding_model", self._check_embedding_model)
        self.register_check("file_access", self._check_file_access)
        self.register_check("background_jobs", self._check_background_jobs)

    def _check_database(self) -> HealthCheck:
        """Check vector database health."""
        start = time.time()

        try:
            import lancedb

            db_path = self.data_dir / "lancedb"
            if not db_path.exists():
                return HealthCheck(
                    name="database",
                    status=HealthStatus.DEGRADED,
                    message="Database not initialized",
                    latency_ms=(time.time() - start) * 1000
                )

            db = lancedb.connect(str(db_path))
            tables = db.table_names()

            return HealthCheck(
                name="database",
                status=HealthStatus.HEALTHY,
                message=f"Connected, {len(tables)} tables",
                latency_ms=(time.time() - start) * 1000,
                details={"tables": tables}
            )

        except ImportError:
            return HealthCheck(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message="LanceDB not installed",
                latency_ms=(time.time() - start) * 1000
            )
        except Exception as e:
            return HealthCheck(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=f"Connection failed: {str(e)}",
                latency_ms=(time.time() - start) * 1000
            )

    def _check_storage(self) -> HealthCheck:
        """Check storage space."""
        start = time.time()

        try:
            total, used, free = shutil.disk_usage(self.data_dir)
            free_gb = free / (1024 ** 3)
            used_percent = (used / total) * 100

            if free_gb < 5:
                status = HealthStatus.UNHEALTHY
                message = f"Critical: Only {free_gb:.1f} GB free"
            elif free_gb < 20:
                status = HealthStatus.DEGRADED
                message = f"Warning: {free_gb:.1f} GB free"
            else:
                status = HealthStatus.HEALTHY
                message = f"{free_gb:.1f} GB free ({used_percent:.0f}% used)"

            return HealthCheck(
                name="storage",
                status=status,
                message=message,
                latency_ms=(time.time() - start) * 1000,
                details={
                    "total_gb": total / (1024 ** 3),
                    "used_gb": used / (1024 ** 3),
                    "free_gb": free_gb,
                    "used_percent": used_percent
                }
            )

        except Exception as e:
            return HealthCheck(
                name="storage",
                status=HealthStatus.UNKNOWN,
                message=f"Check failed: {str(e)}",
                latency_ms=(time.time() - start) * 1000
            )

    def _check_memory(self) -> HealthCheck:
        """Check memory usage."""
        start = time.time()

        try:
            import psutil

            memory = psutil.virtual_memory()
            available_gb = memory.available / (1024 ** 3)
            used_percent = memory.percent

            if available_gb < 4:
                status = HealthStatus.UNHEALTHY
                message = f"Critical: {available_gb:.1f} GB available"
            elif available_gb < 8:
                status = HealthStatus.DEGRADED
                message = f"Warning: {available_gb:.1f} GB available"
            else:
                status = HealthStatus.HEALTHY
                message = f"{available_gb:.1f} GB available ({used_percent:.0f}% used)"

            return HealthCheck(
                name="memory",
                status=status,
                message=message,
                latency_ms=(time.time() - start) * 1000,
                details={
                    "total_gb": memory.total / (1024 ** 3),
                    "available_gb": available_gb,
                    "used_percent": used_percent
                }
            )

        except ImportError:
            return HealthCheck(
                name="memory",
                status=HealthStatus.UNKNOWN,
                message="psutil not installed",
                latency_ms=(time.time() - start) * 1000
            )

    def _check_embedding_model(self) -> HealthCheck:
        """Check embedding model availability."""
        start = time.time()

        try:
            # Check if model files exist
            model_dir = Path.home() / ".cache" / "huggingface" / "hub"
            nomic_dirs = list(model_dir.glob("*nomic*"))

            if nomic_dirs:
                return HealthCheck(
                    name="embedding_model",
                    status=HealthStatus.HEALTHY,
                    message="Model cached locally",
                    latency_ms=(time.time() - start) * 1000,
                    details={"model_paths": [str(d) for d in nomic_dirs[:3]]}
                )
            else:
                return HealthCheck(
                    name="embedding_model",
                    status=HealthStatus.DEGRADED,
                    message="Model not cached, will download on first use",
                    latency_ms=(time.time() - start) * 1000
                )

        except Exception as e:
            return HealthCheck(
                name="embedding_model",
                status=HealthStatus.UNKNOWN,
                message=f"Check failed: {str(e)}",
                latency_ms=(time.time() - start) * 1000
            )

    def _check_file_access(self) -> HealthCheck:
        """Check file system access."""
        start = time.time()

        try:
            # Test write access
            test_file = self.state_dir / ".health_check_test"
            test_file.write_text("test")
            test_file.unlink()

            return HealthCheck(
                name="file_access",
                status=HealthStatus.HEALTHY,
                message="Read/write access OK",
                latency_ms=(time.time() - start) * 1000
            )

        except PermissionError:
            return HealthCheck(
                name="file_access",
                status=HealthStatus.UNHEALTHY,
                message="Permission denied",
                latency_ms=(time.time() - start) * 1000
            )
        except Exception as e:
            return HealthCheck(
                name="file_access",
                status=HealthStatus.UNHEALTHY,
                message=f"Access failed: {str(e)}",
                latency_ms=(time.time() - start) * 1000
            )

    def _check_background_jobs(self) -> HealthCheck:
        """Check background job status."""
        start = time.time()

        try:
            # Check checkpoint files for stuck jobs
            checkpoint_dir = self.state_dir.parent / "checkpoints"
            if not checkpoint_dir.exists():
                return HealthCheck(
                    name="background_jobs",
                    status=HealthStatus.HEALTHY,
                    message="No active jobs",
                    latency_ms=(time.time() - start) * 1000
                )

            active_jobs = list(checkpoint_dir.glob("*.json"))
            stuck_jobs = []

            for job_file in active_jobs:
                try:
                    with open(job_file) as f:
                        job_data = json.load(f)

                    if job_data.get("status") == "in_progress":
                        updated = datetime.fromisoformat(job_data.get("updated_at", ""))
                        if datetime.now() - updated > timedelta(hours=1):
                            stuck_jobs.append(job_file.stem)
                except:
                    pass

            if stuck_jobs:
                return HealthCheck(
                    name="background_jobs",
                    status=HealthStatus.DEGRADED,
                    message=f"{len(stuck_jobs)} stuck jobs",
                    latency_ms=(time.time() - start) * 1000,
                    details={"stuck_jobs": stuck_jobs}
                )

            return HealthCheck(
                name="background_jobs",
                status=HealthStatus.HEALTHY,
                message=f"{len(active_jobs)} active jobs",
                latency_ms=(time.time() - start) * 1000
            )

        except Exception as e:
            return HealthCheck(
                name="background_jobs",
                status=HealthStatus.UNKNOWN,
                message=f"Check failed: {str(e)}",
                latency_ms=(time.time() - start) * 1000
            )

    def _log_status(self, status: SystemStatus) -> None:
        """Log status to file."""
        log_file = self.state_dir / "health.log"

        entry = {
            "timestamp": status.timestamp,
            "status": status.status.value,
            "uptime_seconds": status.uptime_seconds,
            "checks": {
                c.name: c.status.value for c in status.checks
            }
        }

        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        """Format uptime as human-readable string."""
        if seconds < 60:
            return f"{seconds:.0f} seconds"
        elif seconds < 3600:
            return f"{seconds / 60:.0f} minutes"
        elif seconds < 86400:
            return f"{seconds / 3600:.1f} hours"
        else:
            return f"{seconds / 86400:.1f} days"


class MetricsCollector:
    """
    Collect and store system metrics over time.

    For dashboards and trend analysis.
    """

    def __init__(self, state_dir: Optional[Path] = None):
        """Initialize metrics collector."""
        self.state_dir = state_dir or Path.home() / ".pkm" / "metrics"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def record_metric(
        self,
        name: str,
        value: float,
        tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Record a metric value."""
        metric = {
            "timestamp": datetime.now().isoformat(),
            "name": name,
            "value": value,
            "tags": tags or {}
        }

        # Append to daily file
        date_str = datetime.now().strftime("%Y-%m-%d")
        metric_file = self.state_dir / f"metrics_{date_str}.jsonl"

        with open(metric_file, "a") as f:
            f.write(json.dumps(metric) + "\n")

    def get_metrics(
        self,
        name: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None
    ) -> List[Dict]:
        """Retrieve metrics for a given name."""
        metrics = []

        since = since or datetime.now() - timedelta(days=7)
        until = until or datetime.now()

        current = since
        while current <= until:
            date_str = current.strftime("%Y-%m-%d")
            metric_file = self.state_dir / f"metrics_{date_str}.jsonl"

            if metric_file.exists():
                with open(metric_file) as f:
                    for line in f:
                        try:
                            metric = json.loads(line)
                            if metric["name"] == name:
                                metrics.append(metric)
                        except:
                            pass

            current += timedelta(days=1)

        return metrics

    def get_summary(self, name: str, days: int = 7) -> Dict:
        """Get summary statistics for a metric."""
        since = datetime.now() - timedelta(days=days)
        metrics = self.get_metrics(name, since=since)

        if not metrics:
            return {"message": "No data"}

        values = [m["value"] for m in metrics]

        return {
            "name": name,
            "period_days": days,
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "latest": values[-1] if values else None
        }
