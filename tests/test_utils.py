"""
Tests for utility modules.

Run with: pytest tests/test_utils.py -v
"""

import tempfile
from pathlib import Path

import pytest


class TestCheckpoint:
    """Tests for checkpoint module."""

    def test_create_job(self):
        """Should create a new job with correct state."""
        from src.utils.checkpoint import CheckpointManager, JobStatus

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CheckpointManager(checkpoint_dir=Path(tmpdir))

            files = [Path("/fake/file1.txt"), Path("/fake/file2.txt")]
            job = manager.create_job("test_job", files)

            assert job.job_type == "test_job"
            assert job.total_files == 2
            assert job.status == JobStatus.IN_PROGRESS
            assert job.processed == 0

    def test_get_remaining_files(self):
        """Should return files not yet processed."""
        from src.utils.checkpoint import CheckpointManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = CheckpointManager(checkpoint_dir=Path(tmpdir))

            files = [Path("/fake/file1.txt"), Path("/fake/file2.txt"), Path("/fake/file3.txt")]
            job = manager.create_job("test_job", files)

            # Mark one as completed
            manager.mark_file_completed(job.job_id, files[0], doc_id="doc_001")

            remaining = manager.get_remaining_files(job.job_id)
            assert len(remaining) == 2
            assert str(files[0]) not in remaining


class TestRetry:
    """Tests for retry module."""

    def test_successful_on_first_try(self):
        """Should return immediately on success."""
        from src.utils.retry import retry_with_backoff

        call_count = 0

        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = retry_with_backoff(successful_func, max_attempts=3)

        assert result == "success"
        assert call_count == 1

    def test_retry_on_failure(self):
        """Should retry on transient failures."""
        from src.utils.retry import retry_with_backoff

        call_count = 0

        def failing_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Transient failure")
            return "success"

        result = retry_with_backoff(failing_then_success, max_attempts=5, initial_delay=0.01)

        assert result == "success"
        assert call_count == 3

    def test_max_retries_exceeded(self):
        """Should raise after max retries."""
        from src.utils.retry import retry_with_backoff

        def always_fails():
            raise ConnectionError("Always fails")

        with pytest.raises(ConnectionError):
            retry_with_backoff(always_fails, max_attempts=2, initial_delay=0.01)


class TestPrivacyAudit:
    """Tests for privacy audit module."""

    def test_detect_email(self):
        """Should detect email addresses."""
        from src.utils.privacy_audit import PrivacyScanner, SensitiveDataType

        scanner = PrivacyScanner()
        result = scanner.scan("Contact me at test@example.com for details.")

        assert result.has_sensitive_data
        assert any(m.data_type == SensitiveDataType.EMAIL for m in result.matches)

    def test_detect_ssn(self):
        """Should detect SSN patterns."""
        from src.utils.privacy_audit import PrivacyScanner, PrivacyTier, SensitiveDataType

        scanner = PrivacyScanner()
        # Use a valid-format SSN (area number 078 is valid, unlike 123 which starts with 1)
        # Note: Presidio's US_SSN recognizer validates SSN format rules
        result = scanner.scan("SSN: 078-05-1120")

        assert result.has_sensitive_data
        assert any(m.data_type == SensitiveDataType.SSN for m in result.matches)
        assert result.privacy_tier == PrivacyTier.RESTRICTED

    def test_clean_content(self):
        """Should pass clean content."""
        from src.utils.privacy_audit import PrivacyScanner, PrivacyTier

        scanner = PrivacyScanner()
        result = scanner.scan("This is just a regular meeting note about project planning.")

        assert not result.has_sensitive_data
        assert result.privacy_tier == PrivacyTier.PUBLIC


class TestQueueManager:
    """Tests for queue manager module."""

    def test_add_job(self):
        """Should add job to queue."""
        from src.utils.queue_manager import QueueManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = QueueManager(state_dir=Path(tmpdir))

            job_id = manager.add_job("test_type", {"data": "value"})

            assert job_id is not None
            job = manager.get_job(job_id)
            assert job.job_type == "test_type"
            assert job.payload == {"data": "value"}

    def test_priority_ordering(self):
        """Higher priority jobs should be processed first."""
        from src.utils.queue_manager import Priority, QueueManager

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = QueueManager(state_dir=Path(tmpdir))

            # Add jobs with different priorities
            manager.add_job("low", {"order": 3}, priority=Priority.LOW)
            manager.add_job("high", {"order": 1}, priority=Priority.HIGH)
            manager.add_job("normal", {"order": 2}, priority=Priority.NORMAL)

            pending = manager.get_pending_jobs()

            # Should be ordered by priority
            assert pending[0].job_type == "high"
            assert pending[1].job_type == "normal"
            assert pending[2].job_type == "low"


# Run tests with: pytest tests/test_utils.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
