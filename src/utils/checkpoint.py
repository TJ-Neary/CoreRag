"""
Checkpoint system for resumable processing.

Enables long-running jobs to be interrupted and resumed without losing progress.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid
import shutil

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Status of a processing job."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FileStatus(Enum):
    """Status of a file within a job."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class FileProgress:
    """Progress tracking for a single file."""
    path: str
    status: FileStatus = FileStatus.PENDING
    doc_id: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass
class JobCheckpoint:
    """Checkpoint for a processing job."""
    job_id: str
    job_type: str
    status: JobStatus = JobStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Source information
    source_paths: List[str] = field(default_factory=list)

    # Progress tracking
    total_files: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    current_file: Optional[str] = None

    # File-level tracking
    files: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # Error log
    errors: List[Dict[str, Any]] = field(default_factory=list)

    # Job configuration (for resume)
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["status"] = self.status.value
        # Convert FileProgress objects
        for path, file_data in data["files"].items():
            if isinstance(file_data.get("status"), FileStatus):
                file_data["status"] = file_data["status"].value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "JobCheckpoint":
        """Create from dictionary."""
        data["status"] = JobStatus(data["status"])
        return cls(**data)


class CheckpointManager:
    """
    Manages job checkpoints for resumable processing.

    Usage:
        manager = CheckpointManager()

        # Start a new job
        job = manager.create_job("bulk_ingestion", files)

        # Process with checkpointing
        for file in files:
            manager.mark_file_processing(job.job_id, file)
            try:
                result = process_file(file)
                manager.mark_file_completed(job.job_id, file, doc_id=result.id)
            except Exception as e:
                manager.mark_file_failed(job.job_id, file, str(e))

        manager.complete_job(job.job_id)

        # Resume interrupted job
        job = manager.get_job("job_id")
        remaining = manager.get_remaining_files(job.job_id)
    """

    def __init__(self, checkpoint_dir: Optional[Path] = None):
        """
        Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory to store checkpoints
        """
        self.checkpoint_dir = checkpoint_dir or Path.home() / ".corerag" / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.completed_dir = self.checkpoint_dir / "completed"
        self.completed_dir.mkdir(exist_ok=True)

    def create_job(
        self,
        job_type: str,
        files: List[Path],
        config: Optional[Dict[str, Any]] = None
    ) -> JobCheckpoint:
        """
        Create a new processing job.

        Args:
            job_type: Type of job (e.g., "bulk_ingestion", "reindex")
            files: List of files to process
            config: Job configuration to preserve for resume

        Returns:
            New JobCheckpoint
        """
        job_id = str(uuid.uuid4())[:8]

        checkpoint = JobCheckpoint(
            job_id=job_id,
            job_type=job_type,
            status=JobStatus.IN_PROGRESS,
            source_paths=[str(f) for f in files],
            total_files=len(files),
            config=config or {},
            files={str(f): {"status": FileStatus.PENDING.value} for f in files}
        )

        self._save(checkpoint)
        logger.info(f"Created job {job_id} with {len(files)} files")

        return checkpoint

    def get_job(self, job_id: str) -> Optional[JobCheckpoint]:
        """Get a job checkpoint by ID."""
        path = self._get_path(job_id)
        if not path.exists():
            # Check completed
            path = self.completed_dir / f"job_{job_id}.json"
            if not path.exists():
                return None

        return self._load(path)

    def list_jobs(self, include_completed: bool = False) -> List[JobCheckpoint]:
        """List all jobs."""
        jobs = []

        # Active jobs
        for path in self.checkpoint_dir.glob("job_*.json"):
            jobs.append(self._load(path))

        # Completed jobs
        if include_completed:
            for path in self.completed_dir.glob("job_*.json"):
                jobs.append(self._load(path))

        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def get_remaining_files(self, job_id: str) -> List[str]:
        """Get list of files not yet processed."""
        job = self.get_job(job_id)
        if not job:
            return []

        remaining = []
        for path, data in job.files.items():
            status = data.get("status", "pending")
            if status in [FileStatus.PENDING.value, "pending"]:
                remaining.append(path)

        return remaining

    def mark_file_processing(self, job_id: str, file_path: Path) -> None:
        """Mark a file as currently being processed."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        path_str = str(file_path)
        job.files[path_str] = {
            "status": FileStatus.PROCESSING.value,
            "started_at": datetime.now().isoformat()
        }
        job.current_file = path_str
        job.updated_at = datetime.now().isoformat()

        self._save(job)

    def mark_file_completed(
        self,
        job_id: str,
        file_path: Path,
        doc_id: Optional[str] = None
    ) -> None:
        """Mark a file as successfully processed."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        path_str = str(file_path)
        job.files[path_str] = {
            "status": FileStatus.COMPLETED.value,
            "doc_id": doc_id,
            "completed_at": datetime.now().isoformat()
        }
        job.processed += 1
        job.succeeded += 1
        job.current_file = None
        job.updated_at = datetime.now().isoformat()

        self._save(job)

    def mark_file_failed(
        self,
        job_id: str,
        file_path: Path,
        error: str
    ) -> None:
        """Mark a file as failed."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        path_str = str(file_path)
        job.files[path_str] = {
            "status": FileStatus.FAILED.value,
            "error": error,
            "completed_at": datetime.now().isoformat()
        }
        job.processed += 1
        job.failed += 1
        job.current_file = None
        job.errors.append({
            "file": path_str,
            "error": error,
            "timestamp": datetime.now().isoformat()
        })
        job.updated_at = datetime.now().isoformat()

        self._save(job)
        logger.warning(f"File failed: {path_str}: {error}")

    def mark_file_skipped(
        self,
        job_id: str,
        file_path: Path,
        reason: str
    ) -> None:
        """Mark a file as skipped (e.g., duplicate)."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        path_str = str(file_path)
        job.files[path_str] = {
            "status": FileStatus.SKIPPED.value,
            "reason": reason,
            "completed_at": datetime.now().isoformat()
        }
        job.processed += 1
        job.skipped += 1
        job.updated_at = datetime.now().isoformat()

        self._save(job)

    def complete_job(self, job_id: str) -> None:
        """Mark a job as completed and archive it."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job.status = JobStatus.COMPLETED
        job.updated_at = datetime.now().isoformat()

        # Move to completed directory
        old_path = self._get_path(job_id)
        new_path = self.completed_dir / f"job_{job_id}.json"

        self._save(job)
        if old_path.exists():
            shutil.move(str(old_path), str(new_path))

        logger.info(
            f"Job {job_id} completed: "
            f"{job.succeeded} succeeded, {job.failed} failed, {job.skipped} skipped"
        )

    def fail_job(self, job_id: str, error: str) -> None:
        """Mark a job as failed."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job.status = JobStatus.FAILED
        job.updated_at = datetime.now().isoformat()
        job.errors.append({
            "type": "job_failure",
            "error": error,
            "timestamp": datetime.now().isoformat()
        })

        self._save(job)
        logger.error(f"Job {job_id} failed: {error}")

    def get_progress(self, job_id: str) -> Dict[str, Any]:
        """Get progress summary for a job."""
        job = self.get_job(job_id)
        if not job:
            return {}

        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "total": job.total_files,
            "processed": job.processed,
            "succeeded": job.succeeded,
            "failed": job.failed,
            "skipped": job.skipped,
            "remaining": job.total_files - job.processed,
            "percent_complete": (job.processed / job.total_files * 100) if job.total_files > 0 else 0,
            "current_file": job.current_file,
        }

    def _get_path(self, job_id: str) -> Path:
        """Get checkpoint file path for a job."""
        return self.checkpoint_dir / f"job_{job_id}.json"

    def _save(self, job: JobCheckpoint) -> None:
        """Save checkpoint to disk."""
        path = self._get_path(job.job_id)
        with open(path, "w") as f:
            json.dump(job.to_dict(), f, indent=2)

    def _load(self, path: Path) -> JobCheckpoint:
        """Load checkpoint from disk."""
        with open(path) as f:
            data = json.load(f)
        return JobCheckpoint.from_dict(data)
