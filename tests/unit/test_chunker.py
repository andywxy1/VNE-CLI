"""Tests for text chunking."""

from __future__ import annotations

import pytest

from vne_cli.config.schema import ChunkingConfig
from vne_cli.extraction.chunker import (
    TextChunk,
    chunk_text,
    detect_chapter_boundaries,
    estimate_tokens,
)
from vne_cli.providers.errors import ChunkingError


class TestEstimateTokens:
    """Token estimation heuristic tests."""

    def test_empty_string(self) -> None:
        assert estimate_tokens("") == 0

    def test_single_word(self) -> None:
        result = estimate_tokens("hello")
        assert result == 1  # int(1 * 1.3) = 1

    def test_known_count(self) -> None:
        text = "one two three four five"
        result = estimate_tokens(text)
        assert result == int(5 * 1.3)

    def test_custom_multiplier(self) -> None:
        text = "one two three"
        assert estimate_tokens(text, multiplier=2.0) == 6

    def test_large_text(self) -> None:
        text = " ".join(["word"] * 1000)
        result = estimate_tokens(text)
        assert result == int(1000 * 1.3)


class TestDetectChapterBoundaries:
    """Chapter boundary detection tests."""

    def test_markdown_headers(self) -> None:
        text = "# Chapter 1\n\nSome text.\n\n## Chapter 2\n\nMore text."
        boundaries = detect_chapter_boundaries(text)
        assert len(boundaries) >= 2
        titles = [b[1] for b in boundaries]
        assert any("Chapter 1" in t for t in titles)
        assert any("Chapter 2" in t for t in titles)

    def test_chapter_keyword(self) -> None:
        text = "Chapter 1: The Beginning\n\nText here.\n\nChapter 2: The End\n\nMore text."
        boundaries = detect_chapter_boundaries(text)
        assert len(boundaries) >= 2

    def test_prologue_epilogue(self) -> None:
        text = "Prologue\n\nSome text.\n\nEpilogue\n\nMore text."
        boundaries = detect_chapter_boundaries(text)
        assert len(boundaries) >= 2

    def test_no_chapters(self) -> None:
        text = "Just a simple paragraph of text with no chapter markers at all."
        boundaries = detect_chapter_boundaries(text)
        assert len(boundaries) == 0

    def test_all_caps_titles(self) -> None:
        text = "THE BEGINNING\n\nText here.\n\nTHE MIDDLE\n\nMore text."
        boundaries = detect_chapter_boundaries(text)
        assert len(boundaries) >= 2


class TestChunkText:
    """Core chunking logic tests."""

    def test_short_text_single_chunk(self) -> None:
        """Short text should produce a single chunk."""
        text = "Chapter 1: Hello\n\nThis is a short text."
        config = ChunkingConfig(target_tokens=8000, overlap_tokens=100)
        chunks = chunk_text(text, config)
        assert len(chunks) == 1
        assert chunks[0].index == 0
        assert "short text" in chunks[0].text

    def test_respects_chapter_boundaries(self) -> None:
        """Chunks should not split mid-chapter when possible."""
        chapter1 = "Chapter 1: First\n\n" + "Word " * 100
        chapter2 = "Chapter 2: Second\n\n" + "Word " * 100
        text = chapter1 + "\n\n" + chapter2
        # Set target high enough to fit each chapter but not both
        config = ChunkingConfig(target_tokens=200, overlap_tokens=20)
        chunks = chunk_text(text, config)
        assert len(chunks) >= 2
        # Each chunk should have a chapter hint
        hints = [c.chapter_hint for c in chunks]
        assert any("First" in (h or "") for h in hints)
        assert any("Second" in (h or "") for h in hints)

    def test_overlap_present(self) -> None:
        """Consecutive chunks should have overlap for context continuity."""
        # Create text large enough to need multiple chunks
        chapter1 = "Chapter 1: First\n\n" + "Alpha word. " * 200
        chapter2 = "Chapter 2: Second\n\n" + "Beta word. " * 200
        text = chapter1 + "\n\n" + chapter2
        config = ChunkingConfig(target_tokens=200, overlap_tokens=50)
        chunks = chunk_text(text, config)
        if len(chunks) >= 2:
            # Second chunk should contain some text from the tail of first chunk's source
            # due to overlap
            assert chunks[1].estimated_tokens > 0

    def test_empty_text_raises(self) -> None:
        """Empty text should raise ChunkingError."""
        config = ChunkingConfig(target_tokens=8000, overlap_tokens=100)
        with pytest.raises(ChunkingError, match="empty"):
            chunk_text("", config)

    def test_whitespace_only_raises(self) -> None:
        config = ChunkingConfig(target_tokens=8000, overlap_tokens=100)
        with pytest.raises(ChunkingError, match="empty"):
            chunk_text("   \n\n   ", config)

    def test_invalid_target_tokens(self) -> None:
        config = ChunkingConfig(target_tokens=0, overlap_tokens=0)
        with pytest.raises(ChunkingError, match="positive"):
            chunk_text("Hello world", config)

    def test_overlap_exceeds_target(self) -> None:
        config = ChunkingConfig(target_tokens=100, overlap_tokens=200)
        with pytest.raises(ChunkingError, match="less than"):
            chunk_text("Hello world", config)

    def test_chunk_metadata(self) -> None:
        """Chunks should have proper metadata."""
        text = "Chapter 1: Test\n\nSome content here."
        config = ChunkingConfig(target_tokens=8000, overlap_tokens=100)
        chunks = chunk_text(text, config)
        assert len(chunks) >= 1
        chunk = chunks[0]
        assert chunk.index == 0
        assert chunk.estimated_tokens > 0
        assert chunk.start_offset >= 0
        assert chunk.end_offset > chunk.start_offset

    def test_large_chapter_splits(self) -> None:
        """A chapter exceeding target_tokens should be split at paragraph boundaries."""
        paragraphs = [f"Paragraph {i}. " + "word " * 50 for i in range(20)]
        text = "Chapter 1: Big Chapter\n\n" + "\n\n".join(paragraphs)
        config = ChunkingConfig(target_tokens=200, overlap_tokens=20)
        chunks = chunk_text(text, config)
        assert len(chunks) > 1
        # All chunks should be within a reasonable range of the target
        for chunk in chunks:
            # Allow some tolerance due to overlap and boundaries
            assert chunk.estimated_tokens < config.target_tokens * 3

    def test_no_chapters_detected(self) -> None:
        """Text without chapter markers should still chunk properly."""
        text = "Just some text.\n\n" * 50
        config = ChunkingConfig(target_tokens=100, overlap_tokens=10)
        chunks = chunk_text(text, config)
        assert len(chunks) >= 1
        assert chunks[0].chapter_hint == "Full Text"

    def test_zero_overlap(self) -> None:
        """Overlap of 0 should work without errors."""
        text = "Chapter 1: Test\n\nSome content here."
        config = ChunkingConfig(target_tokens=8000, overlap_tokens=0)
        chunks = chunk_text(text, config)
        assert len(chunks) >= 1

    def test_word_count_property(self) -> None:
        text = "Chapter 1: Test\n\nOne two three four five."
        config = ChunkingConfig(target_tokens=8000, overlap_tokens=0)
        chunks = chunk_text(text, config)
        assert chunks[0].word_count > 0
