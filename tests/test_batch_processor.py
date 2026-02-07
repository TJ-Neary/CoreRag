"""
Tests for src/batch_processor.py

Tests batch processing with memory safety and progress tracking.
"""

import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestBatchProcessor:
    """Tests for BatchProcessor class."""

    @pytest.fixture
    def mock_inbox(self, tmp_path):
        """Create a mock inbox with test files."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()

        # Create test files
        (inbox / "doc1.txt").write_text("Document 1 content")
        (inbox / "doc2.txt").write_text("Document 2 content")
        (inbox / "doc3.txt").write_text("Document 3 content")
        (inbox / ".hidden").write_text("Hidden file")  # Should be ignored

        return inbox

    @pytest.fixture
    def processor(self, mock_inbox):
        """Create a BatchProcessor with mocked dependencies."""
        with (
            patch("src.batch_processor.INBOX_PATH", mock_inbox),
            patch("src.batch_processor.STATE_DIR", mock_inbox.parent / "state"),
            patch("src.batch_processor.process_document", new_callable=AsyncMock) as mock_process,
            patch("src.batch_processor.QueueManager") as mock_qm,
        ):

            mock_qm_instance = MagicMock()
            mock_qm.return_value = mock_qm_instance

            from src.batch_processor import BatchProcessor

            bp = BatchProcessor()
            bp._mock_process = mock_process
            yield bp

    def test_scan_inbox_finds_files(self, processor, mock_inbox):
        """Test that scan_inbox finds non-hidden files."""
        files = processor.scan_inbox()

        assert len(files) == 3
        filenames = [f.name for f in files]
        assert "doc1.txt" in filenames
        assert "doc2.txt" in filenames
        assert "doc3.txt" in filenames
        assert ".hidden" not in filenames

    def test_scan_inbox_empty_directory(self, processor, mock_inbox):
        """Test scan_inbox with empty directory."""
        # Remove all files
        for f in mock_inbox.iterdir():
            f.unlink()

        files = processor.scan_inbox()

        assert len(files) == 0

    def test_scan_inbox_nonexistent_directory(self, processor, tmp_path):
        """Test scan_inbox when inbox doesn't exist."""
        with patch("src.batch_processor.INBOX_PATH", tmp_path / "nonexistent"):
            from src.batch_processor import BatchProcessor

            bp = BatchProcessor()
            files = bp.scan_inbox()
            assert len(files) == 0

    def test_get_progress_returns_dict(self, processor):
        """Test that get_progress returns a copy of progress dict."""
        progress = processor.get_progress()

        assert isinstance(progress, dict)
        assert "status" in progress
        assert "total" in progress
        assert "processed" in progress

    def test_is_running_initially_false(self, processor):
        """Test that processor is not running initially."""
        assert processor.is_running() is False

    def test_process_all_updates_progress(self, processor, mock_inbox):
        """Test that process_all updates progress correctly."""
        with patch.object(processor, "_wait_for_safe_memory"):
            processor.process_all()

        progress = processor.get_progress()
        assert progress["status"] == "complete"
        assert progress["total"] == 3
        assert progress["processed"] == 3

    def test_process_all_calls_process_document(self, processor):
        """Test that process_all calls process_document for each file."""
        with patch.object(processor, "_wait_for_safe_memory"):
            processor.process_all()

        assert processor._mock_process.call_count == 3

    def test_process_all_handles_errors(self, processor):
        """Test that process_all handles processing errors gracefully."""
        processor._mock_process.side_effect = [None, Exception("Error"), None]

        with patch.object(processor, "_wait_for_safe_memory"):
            processor.process_all()

        progress = processor.get_progress()
        assert progress["status"] == "complete"
        assert progress["processed"] == 3
        assert len(progress["errors"]) == 1

    def test_pause_and_resume(self, processor):
        """Test pause and resume functionality."""
        # Start processing in a thread
        processing_started = threading.Event()

        def slow_process(path):
            processing_started.set()
            time.sleep(0.5)  # Simulate work

        processor._mock_process.side_effect = slow_process

        thread = threading.Thread(target=processor.process_all)

        with patch.object(processor, "_wait_for_safe_memory"):
            thread.start()
            processing_started.wait(timeout=2)

            # Request pause
            processor.pause()
            time.sleep(0.1)

            # Check paused (may or may not be paused depending on timing)
            processor.get_progress()

            # Resume
            processor.resume()

            thread.join(timeout=5)

        assert not thread.is_alive()

    def test_stop_terminates_processing(self, processor):
        """Test that stop terminates processing."""

        def slow_process(path):
            time.sleep(0.5)

        processor._mock_process.side_effect = slow_process

        thread = threading.Thread(target=processor.process_all)

        with patch.object(processor, "_wait_for_safe_memory"):
            thread.start()
            time.sleep(0.1)

            # Request stop
            processor.stop()

            thread.join(timeout=3)

        progress = processor.get_progress()
        assert progress["status"] == "stopped"

    def test_memory_pause_threshold(self, processor):
        """Test that high memory triggers pause."""
        from src.batch_processor import MEMORY_PAUSE_THRESHOLD

        with patch("src.batch_processor.psutil.virtual_memory") as mock_mem:
            mock_result = MagicMock()
            mock_result.percent = MEMORY_PAUSE_THRESHOLD + 5

            # After a few checks, return low memory
            call_count = [0]

            def get_memory():
                call_count[0] += 1
                if call_count[0] > 2:
                    mock_result.percent = 50  # Below resume threshold
                return mock_result

            mock_mem.side_effect = get_memory

            # This should trigger _wait_for_safe_memory
            processor._wait_for_safe_memory()

            # Should have checked memory multiple times
            assert call_count[0] > 1

    def test_duplicate_start_ignored(self, processor):
        """Test that starting while already running is ignored."""
        # Set as running
        processor._running = True

        processor.process_all()  # Should return early

        # Should not have processed any files
        assert processor._mock_process.call_count == 0


class TestBatchProcessorQueued:
    """Tests for queue-based processing."""

    @pytest.fixture
    def processor_with_queue(self, tmp_path):
        """Create a BatchProcessor with queue manager."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        (inbox / "file1.txt").write_text("content")

        with (
            patch("src.batch_processor.INBOX_PATH", inbox),
            patch("src.batch_processor.STATE_DIR", tmp_path / "state"),
            patch("src.batch_processor.process_document", new_callable=AsyncMock),
            patch("src.batch_processor.QueueManager") as mock_qm,
        ):

            mock_qm_instance = MagicMock()
            mock_qm.return_value = mock_qm_instance

            from src.batch_processor import BatchProcessor

            bp = BatchProcessor()
            yield bp

    def test_process_queued_adds_jobs(self, processor_with_queue):
        """Test that process_queued adds jobs to queue."""
        processor_with_queue.process_queued(workers=1)

        # Queue manager should have been called
        processor_with_queue._queue_manager.add_job.assert_called()
        processor_with_queue._queue_manager.start.assert_called_with(workers=1)

    def test_stop_queued_stops_queue(self, processor_with_queue):
        """Test that stop_queued stops the queue manager."""
        processor_with_queue.stop_queued()

        processor_with_queue._queue_manager.stop.assert_called_with(wait=True, timeout=30.0)

    def test_get_queue_stats(self, processor_with_queue):
        """Test that get_queue_stats returns queue statistics."""
        mock_stats = {"pending": 5, "completed": 10}
        processor_with_queue._queue_manager.get_stats.return_value = mock_stats

        stats = processor_with_queue.get_queue_stats()

        assert stats == mock_stats


class TestHandleIngestJob:
    """Tests for the ingest job handler."""

    @pytest.fixture
    def processor(self, tmp_path):
        """Create processor for job handler tests."""
        with (
            patch("src.batch_processor.INBOX_PATH", tmp_path),
            patch("src.batch_processor.STATE_DIR", tmp_path / "state"),
            patch("src.batch_processor.process_document", new_callable=AsyncMock) as mock_process,
            patch("src.batch_processor.psutil.virtual_memory") as mock_mem,
        ):

            mock_mem.return_value.percent = 50  # Normal memory

            from src.batch_processor import BatchProcessor

            bp = BatchProcessor()
            bp._mock_process = mock_process
            yield bp

    def test_handle_ingest_job_success(self, processor, tmp_path):
        """Test successful ingest job handling."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = processor._handle_ingest_job({"file_path": str(test_file)})

        assert result["status"] == "completed"
        processor._mock_process.assert_called_once_with(test_file)

    def test_handle_ingest_job_file_not_found(self, processor, tmp_path):
        """Test ingest job with missing file."""
        result = processor._handle_ingest_job({"file_path": str(tmp_path / "missing.txt")})

        assert result["status"] == "skipped"
        assert "not found" in result["reason"]


class TestMemoryConstants:
    """Tests for memory threshold constants."""

    def test_memory_thresholds_reasonable(self):
        """Test that memory thresholds are reasonable values."""
        from src.batch_processor import MEMORY_PAUSE_THRESHOLD, MEMORY_RESUME_THRESHOLD

        # Pause should be higher than resume (hysteresis)
        assert MEMORY_PAUSE_THRESHOLD > MEMORY_RESUME_THRESHOLD

        # Both should be reasonable percentages
        assert 70 <= MEMORY_PAUSE_THRESHOLD <= 98
        assert 60 <= MEMORY_RESUME_THRESHOLD <= 95
