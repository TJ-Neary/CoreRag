"""Tests for content hash deduplication logic."""

import hashlib


class TestContentHash:
    """Tests for SHA256 content hash generation and dedup logic."""

    def test_hash_deterministic(self):
        text = "This is a test chunk."
        h1 = hashlib.sha256(text.encode()).hexdigest()
        h2 = hashlib.sha256(text.encode()).hexdigest()
        assert h1 == h2

    def test_different_text_different_hash(self):
        h1 = hashlib.sha256("chunk one".encode()).hexdigest()
        h2 = hashlib.sha256("chunk two".encode()).hexdigest()
        assert h1 != h2

    def test_hash_length(self):
        h = hashlib.sha256("test".encode()).hexdigest()
        assert len(h) == 64

    def test_empty_text_hash(self):
        h = hashlib.sha256("".encode()).hexdigest()
        assert isinstance(h, str)
        assert len(h) == 64

    def test_unicode_text_hash(self):
        h = hashlib.sha256("Ünïcödé tëxt 日本語".encode()).hexdigest()
        assert isinstance(h, str)

    def test_dedup_logic(self):
        """Simulate content hash dedup: skip if hash already exists."""
        existing_hashes = set()
        chunks = ["chunk a", "chunk b", "chunk a", "chunk c", "chunk b"]
        inserted = []

        for chunk in chunks:
            h = hashlib.sha256(chunk.encode()).hexdigest()
            if h not in existing_hashes:
                existing_hashes.add(h)
                inserted.append(chunk)

        assert len(inserted) == 3
        assert inserted == ["chunk a", "chunk b", "chunk c"]
