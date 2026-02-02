"""
Job queue manager for large batch processing.

Manages prioritized work queues with rate limiting and monitoring.
"""

import heapq
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class Priority(Enum):
    """Job priority levels."""
    CRITICAL = 0  # Process immediately
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4  # Process when idle


class JobState(Enum):
    """Job execution state."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass(order=True)
class QueuedJob:
    """A job in the queue."""
    priority: int
    created_at: float = field(compare=False)
    job_id: str = field(compare=False)
    job_type: str = field(compare=False)
    payload: Dict[str, Any] = field(compare=False)
    state: JobState = field(default=JobState.QUEUED, compare=False)
    attempts: int = field(default=0, compare=False)
    max_attempts: int = field(default=3, compare=False)
    result: Optional[Any] = field(default=None, compare=False)
    error: Optional[str] = field(default=None, compare=False)
    started_at: Optional[float] = field(default=None, compare=False)
    completed_at: Optional[float] = field(default=None, compare=False)


class RateLimiter:
    """
    Rate limiter using token bucket algorithm.

    Controls the rate of job processing.
    """

    def __init__(
        self,
        rate: float = 10.0,  # tokens per second
        burst: int = 20  # maximum burst size
    ):
        """
        Initialize rate limiter.

        Args:
            rate: Tokens added per second
            burst: Maximum tokens (burst capacity)
        """
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last_update = time.time()
        self._lock = threading.Lock()

    def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            True if tokens acquired, False if rate limited
        """
        with self._lock:
            now = time.time()
            elapsed = now - self._last_update
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
            self._last_update = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait_for_token(self, tokens: int = 1, timeout: float = 60.0) -> bool:
        """
        Wait until tokens are available.

        Args:
            tokens: Number of tokens needed
            timeout: Maximum wait time

        Returns:
            True if tokens acquired, False if timeout
        """
        start = time.time()
        while time.time() - start < timeout:
            if self.acquire(tokens):
                return True
            time.sleep(0.1)
        return False


class QueueManager:
    """
    Manage prioritized job queues with workers.

    Features:
    - Priority-based job ordering
    - Rate limiting
    - Automatic retry with backoff
    - Persistent queue state
    - Worker pool management

    Usage:
        manager = QueueManager()

        # Register job handlers
        manager.register_handler("ingest_file", process_file)
        manager.register_handler("generate_embedding", generate_embedding)

        # Add jobs
        manager.add_job("ingest_file", {"path": "/path/to/file.md"})
        manager.add_job("generate_embedding", {"text": "..."}, priority=Priority.HIGH)

        # Start processing
        manager.start(workers=4)

        # Monitor
        stats = manager.get_stats()

        # Graceful shutdown
        manager.stop()
    """

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        rate_limit: float = 10.0,
        burst_limit: int = 20
    ):
        """
        Initialize queue manager.

        Args:
            state_dir: Directory for persistent state
            rate_limit: Jobs per second
            burst_limit: Maximum burst size
        """
        self.state_dir = state_dir or Path.home() / ".corerag" / "queue"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._queue: List[QueuedJob] = []
        self._jobs: Dict[str, QueuedJob] = {}
        self._handlers: Dict[str, Callable] = {}
        self._workers: List[threading.Thread] = []
        self._running = False
        self._paused = False

        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

        self.rate_limiter = RateLimiter(rate_limit, burst_limit)

        # Statistics
        self._stats = {
            "total_jobs": 0,
            "completed_jobs": 0,
            "failed_jobs": 0,
            "total_retries": 0
        }

        self._load_state()

    def register_handler(
        self,
        job_type: str,
        handler: Callable[[Dict[str, Any]], Any]
    ) -> None:
        """
        Register a handler for a job type.

        Args:
            job_type: Type of job this handler processes
            handler: Function that processes the job payload
        """
        self._handlers[job_type] = handler
        logger.info(f"Registered handler for job type: {job_type}")

    def add_job(
        self,
        job_type: str,
        payload: Dict[str, Any],
        priority: Priority = Priority.NORMAL,
        max_attempts: int = 3,
        job_id: Optional[str] = None
    ) -> str:
        """
        Add a job to the queue.

        Args:
            job_type: Type of job
            payload: Job data
            priority: Job priority
            max_attempts: Maximum retry attempts
            job_id: Optional custom job ID

        Returns:
            Job ID
        """
        job_id = job_id or str(uuid4())[:8]

        job = QueuedJob(
            priority=priority.value,
            created_at=time.time(),
            job_id=job_id,
            job_type=job_type,
            payload=payload,
            max_attempts=max_attempts
        )

        with self._condition:
            heapq.heappush(self._queue, job)
            self._jobs[job_id] = job
            self._stats["total_jobs"] += 1
            self._condition.notify()

        self._save_state()
        logger.debug(f"Added job {job_id} ({job_type}) with priority {priority.name}")

        return job_id

    def add_batch(
        self,
        job_type: str,
        payloads: List[Dict[str, Any]],
        priority: Priority = Priority.NORMAL
    ) -> List[str]:
        """
        Add multiple jobs efficiently.

        Args:
            job_type: Type of job
            payloads: List of job payloads
            priority: Priority for all jobs

        Returns:
            List of job IDs
        """
        job_ids = []

        with self._condition:
            for payload in payloads:
                job_id = str(uuid4())[:8]
                job = QueuedJob(
                    priority=priority.value,
                    created_at=time.time(),
                    job_id=job_id,
                    job_type=job_type,
                    payload=payload
                )
                heapq.heappush(self._queue, job)
                self._jobs[job_id] = job
                job_ids.append(job_id)

            self._stats["total_jobs"] += len(payloads)
            self._condition.notify_all()

        self._save_state()
        logger.info(f"Added batch of {len(payloads)} {job_type} jobs")

        return job_ids

    def get_job(self, job_id: str) -> Optional[QueuedJob]:
        """Get job by ID."""
        return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a pending job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.state == JobState.QUEUED:
                job.state = JobState.CANCELLED
                self._save_state()
                return True
        return False

    def start(self, workers: int = 4) -> None:
        """
        Start processing jobs.

        Args:
            workers: Number of worker threads
        """
        if self._running:
            return

        self._running = True
        self._paused = False

        for i in range(workers):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"QueueWorker-{i}",
                daemon=True
            )
            worker.start()
            self._workers.append(worker)

        logger.info(f"Queue manager started with {workers} workers")

    def stop(self, wait: bool = True, timeout: float = 30.0) -> None:
        """
        Stop processing.

        Args:
            wait: Whether to wait for current jobs to complete
            timeout: Maximum time to wait
        """
        self._running = False

        with self._condition:
            self._condition.notify_all()

        if wait:
            for worker in self._workers:
                worker.join(timeout=timeout / len(self._workers))

        self._workers.clear()
        self._save_state()
        logger.info("Queue manager stopped")

    def pause(self) -> None:
        """Pause processing (current jobs will complete)."""
        self._paused = True
        logger.info("Queue manager paused")

    def resume(self) -> None:
        """Resume processing."""
        self._paused = False
        with self._condition:
            self._condition.notify_all()
        logger.info("Queue manager resumed")

    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        with self._lock:
            pending = sum(1 for j in self._jobs.values() if j.state == JobState.QUEUED)
            running = sum(1 for j in self._jobs.values() if j.state == JobState.RUNNING)

            return {
                **self._stats,
                "pending_jobs": pending,
                "running_jobs": running,
                "queue_size": len(self._queue),
                "active_workers": sum(1 for w in self._workers if w.is_alive()),
                "paused": self._paused
            }

    def get_pending_jobs(self, job_type: Optional[str] = None) -> List[QueuedJob]:
        """Get list of pending jobs."""
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.state == JobState.QUEUED]
            if job_type:
                jobs = [j for j in jobs if j.job_type == job_type]
            return sorted(jobs, key=lambda j: (j.priority, j.created_at))

    def clear_completed(self) -> int:
        """Remove completed jobs from memory."""
        with self._lock:
            to_remove = [
                jid for jid, job in self._jobs.items()
                if job.state in (JobState.COMPLETED, JobState.CANCELLED)
            ]
            for jid in to_remove:
                del self._jobs[jid]
            return len(to_remove)

    def _worker_loop(self) -> None:
        """Worker thread main loop."""
        while self._running:
            job = self._get_next_job()

            if job is None:
                continue

            if self._paused:
                # Re-queue job if paused
                with self._condition:
                    job.state = JobState.QUEUED
                    heapq.heappush(self._queue, job)
                continue

            self._process_job(job)

    def _get_next_job(self) -> Optional[QueuedJob]:
        """Get next job from queue."""
        with self._condition:
            while self._running:
                # Wait for rate limit
                if not self.rate_limiter.acquire():
                    self._condition.wait(timeout=0.1)
                    continue

                # Get next non-cancelled job
                while self._queue:
                    job = heapq.heappop(self._queue)
                    if job.state == JobState.QUEUED:
                        job.state = JobState.RUNNING
                        job.started_at = time.time()
                        return job

                # Wait for new jobs
                self._condition.wait(timeout=1.0)

        return None

    def _process_job(self, job: QueuedJob) -> None:
        """Process a single job."""
        handler = self._handlers.get(job.job_type)

        if not handler:
            logger.error(f"No handler for job type: {job.job_type}")
            job.state = JobState.FAILED
            job.error = f"No handler for job type: {job.job_type}"
            self._stats["failed_jobs"] += 1
            return

        try:
            job.attempts += 1
            result = handler(job.payload)

            job.state = JobState.COMPLETED
            job.result = result
            job.completed_at = time.time()
            self._stats["completed_jobs"] += 1

            logger.debug(f"Job {job.job_id} completed")

        except Exception as e:
            logger.warning(f"Job {job.job_id} failed (attempt {job.attempts}): {e}")

            if job.attempts < job.max_attempts:
                # Retry
                job.state = JobState.QUEUED
                self._stats["total_retries"] += 1

                with self._condition:
                    # Add back with slight delay
                    job.priority += 1  # Lower priority for retry
                    heapq.heappush(self._queue, job)

            else:
                job.state = JobState.FAILED
                job.error = str(e)
                job.completed_at = time.time()
                self._stats["failed_jobs"] += 1
                logger.error(f"Job {job.job_id} failed permanently: {e}")

        self._save_state()

    def _load_state(self) -> None:
        """Load queue state from disk."""
        state_file = self.state_dir / "queue_state.json"
        if not state_file.exists():
            return

        try:
            with open(state_file) as f:
                data = json.load(f)

            # Restore pending jobs
            for job_data in data.get("jobs", []):
                if job_data["state"] in ("queued", "running"):
                    job = QueuedJob(
                        priority=job_data["priority"],
                        created_at=job_data["created_at"],
                        job_id=job_data["job_id"],
                        job_type=job_data["job_type"],
                        payload=job_data["payload"],
                        state=JobState.QUEUED,
                        attempts=job_data.get("attempts", 0),
                        max_attempts=job_data.get("max_attempts", 3)
                    )
                    heapq.heappush(self._queue, job)
                    self._jobs[job.job_id] = job

            self._stats = data.get("stats", self._stats)

            logger.info(f"Restored {len(self._queue)} pending jobs")

        except Exception as e:
            logger.error(f"Failed to load queue state: {e}")

    def _save_state(self) -> None:
        """Save queue state to disk."""
        state_file = self.state_dir / "queue_state.json"

        try:
            # Only save pending/running jobs
            jobs_to_save = []
            for job in self._jobs.values():
                if job.state in (JobState.QUEUED, JobState.RUNNING):
                    jobs_to_save.append({
                        "priority": job.priority,
                        "created_at": job.created_at,
                        "job_id": job.job_id,
                        "job_type": job.job_type,
                        "payload": job.payload,
                        "state": job.state.value,
                        "attempts": job.attempts,
                        "max_attempts": job.max_attempts
                    })

            data = {
                "jobs": jobs_to_save,
                "stats": self._stats,
                "updated_at": datetime.now().isoformat()
            }

            with open(state_file, "w") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to save queue state: {e}")


# Convenience function for quick job processing
def process_batch(
    items: List[Any],
    processor: Callable[[Any], Any],
    workers: int = 4,
    rate_limit: float = 10.0
) -> List[Any]:
    """
    Process a batch of items with rate limiting.

    Args:
        items: Items to process
        processor: Function to process each item
        workers: Number of workers
        rate_limit: Items per second

    Returns:
        List of results
    """
    manager = QueueManager(rate_limit=rate_limit)
    manager.register_handler("process", lambda p: processor(p["item"]))

    for item in items:
        manager.add_job("process", {"item": item})

    manager.start(workers=workers)

    # Wait for completion
    while True:
        stats = manager.get_stats()
        if stats["pending_jobs"] == 0 and stats["running_jobs"] == 0:
            break
        time.sleep(0.1)

    manager.stop()

    # Collect results
    results = []
    for job in manager._jobs.values():
        if job.state == JobState.COMPLETED:
            results.append(job.result)

    return results
