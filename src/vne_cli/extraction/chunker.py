"""Smart text chunking for LLM context windows.

Splits novel text into chunks that fit within LLM token limits while
preserving narrative coherence (paragraph and chapter boundaries).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from vne_cli.config.schema import ChunkingConfig
from vne_cli.providers.errors import ChunkingError
from vne_cli.utils.logging import get_logger

logger = get_logger(__name__)

# Patterns that indicate chapter boundaries (case-insensitive)
CHAPTER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^#{1,3}\s+.+", re.MULTILINE),  # Markdown headers
    re.compile(
        r"^(?:chapter|part|book|prologue|epilogue|interlude|act)\s*[\d\w:.\-\u2014]+.*$",
        re.MULTILINE | re.IGNORECASE,
    ),
    re.compile(r"^[A-Z][A-Z\s]{5,}$", re.MULTILINE),  # ALL CAPS TITLES
]

# Default token multiplier: tokens ~ words * this factor
DEFAULT_TOKEN_MULTIPLIER = 1.3


@dataclass(frozen=True)
class TextChunk:
    """A chunk of text with metadata for tracking position in the source."""

    text: str
    index: int
    start_offset: int
    end_offset: int
    chapter_hint: str | None = None
    chapter_indices: list[int] = field(default_factory=list)
    estimated_tokens: int = 0

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def estimate_tokens(text: str, multiplier: float = DEFAULT_TOKEN_MULTIPLIER) -> int:
    """Estimate token count from text using a word-count heuristic.

    Args:
        text: The text to estimate tokens for.
        multiplier: Words-to-tokens ratio (default 1.3).

    Returns:
        Estimated token count.
    """
    word_count = len(text.split())
    return int(word_count * multiplier)


def detect_chapter_boundaries(text: str) -> list[tuple[int, str]]:
    """Find chapter boundary positions in the text.

    Returns a list of (offset, title) tuples sorted by offset.
    """
    boundaries: list[tuple[int, str]] = []
    seen_offsets: set[int] = set()

    for pattern in CHAPTER_PATTERNS:
        for match in pattern.finditer(text):
            offset = match.start()
            # Deduplicate overlapping matches
            if any(abs(offset - s) < 5 for s in seen_offsets):
                continue
            seen_offsets.add(offset)
            title = match.group(0).strip().strip("#").strip("*").strip("-").strip()
            if title:
                boundaries.append((offset, title))

    boundaries.sort(key=lambda x: x[0])
    return boundaries


def _split_into_chapters(text: str) -> list[tuple[str, str, int]]:
    """Split text into chapters based on detected boundaries.

    Returns list of (chapter_title, chapter_text, start_offset) tuples.
    """
    boundaries = detect_chapter_boundaries(text)

    if not boundaries:
        # No chapters detected: treat entire text as one chapter
        return [("Full Text", text, 0)]

    chapters: list[tuple[str, str, int]] = []

    # Text before first chapter boundary (preamble)
    if boundaries[0][0] > 0:
        preamble = text[: boundaries[0][0]].strip()
        if preamble:
            chapters.append(("Preamble", preamble, 0))

    for i, (offset, title) in enumerate(boundaries):
        if i + 1 < len(boundaries):
            end = boundaries[i + 1][0]
        else:
            end = len(text)
        chapter_text = text[offset:end].strip()
        if chapter_text:
            chapters.append((title, chapter_text, offset))

    return chapters


def _split_at_paragraphs(text: str, target_tokens: int) -> list[str]:
    """Split text at paragraph boundaries to fit within token limits.

    Args:
        text: Text to split.
        target_tokens: Target maximum tokens per chunk.

    Returns:
        List of text segments.
    """
    paragraphs = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return [text] if text.strip() else []

    segments: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = estimate_tokens(para)

        # If a single paragraph exceeds target, it becomes its own segment
        if para_tokens > target_tokens:
            if current_parts:
                segments.append("\n\n".join(current_parts))
                current_parts = []
                current_tokens = 0
            # Split long paragraph at sentence boundaries
            sentences = re.split(r"(?<=[.!?])\s+", para)
            sent_parts: list[str] = []
            sent_tokens = 0
            for sent in sentences:
                st = estimate_tokens(sent)
                if sent_tokens + st > target_tokens and sent_parts:
                    segments.append(" ".join(sent_parts))
                    sent_parts = []
                    sent_tokens = 0
                sent_parts.append(sent)
                sent_tokens += st
            if sent_parts:
                segments.append(" ".join(sent_parts))
            continue

        if current_tokens + para_tokens > target_tokens and current_parts:
            segments.append("\n\n".join(current_parts))
            current_parts = []
            current_tokens = 0

        current_parts.append(para)
        current_tokens += para_tokens

    if current_parts:
        segments.append("\n\n".join(current_parts))

    return segments


def chunk_text(
    text: str,
    config: ChunkingConfig,
) -> list[TextChunk]:
    """Split text into overlapping chunks sized for LLM context windows.

    Splits at chapter boundaries first, then at paragraph breaks within
    target_tokens. Adds overlap from the previous chunk for context continuity.

    Args:
        text: The full novel text.
        config: Chunking configuration (target size, overlap).

    Returns:
        Ordered list of TextChunks with overlap for context continuity.

    Raises:
        ChunkingError: If the text cannot be chunked.
    """
    if not text or not text.strip():
        raise ChunkingError("Input text is empty.")

    target_tokens = config.target_tokens
    overlap_tokens = config.overlap_tokens

    if target_tokens <= 0:
        raise ChunkingError(f"target_tokens must be positive, got {target_tokens}")
    if overlap_tokens < 0:
        raise ChunkingError(f"overlap_tokens must be non-negative, got {overlap_tokens}")
    if overlap_tokens >= target_tokens:
        raise ChunkingError(
            f"overlap_tokens ({overlap_tokens}) must be less than "
            f"target_tokens ({target_tokens})"
        )

    chapters = _split_into_chapters(text)
    chunks: list[TextChunk] = []
    chunk_index = 0
    previous_overlap_text = ""

    for chap_idx, (chap_title, chap_text, chap_offset) in enumerate(chapters):
        chap_tokens = estimate_tokens(chap_text)

        # If entire chapter fits in one chunk, use it directly
        if chap_tokens <= target_tokens:
            full_text = chap_text
            if previous_overlap_text:
                full_text = previous_overlap_text + "\n\n" + chap_text

            chunk = TextChunk(
                text=full_text,
                index=chunk_index,
                start_offset=chap_offset,
                end_offset=chap_offset + len(chap_text),
                chapter_hint=chap_title,
                chapter_indices=[chap_idx],
                estimated_tokens=estimate_tokens(full_text),
            )
            chunks.append(chunk)
            chunk_index += 1

            # Extract overlap for next chunk
            if overlap_tokens > 0:
                previous_overlap_text = _extract_tail(chap_text, overlap_tokens)
            else:
                previous_overlap_text = ""
            continue

        # Chapter is too large: split at paragraph boundaries
        effective_target = target_tokens - overlap_tokens  # leave room for overlap
        segments = _split_at_paragraphs(chap_text, effective_target)

        for seg in segments:
            full_text = seg
            if previous_overlap_text:
                full_text = previous_overlap_text + "\n\n" + seg

            seg_start = text.find(seg[:80], max(0, chap_offset - 10))
            if seg_start == -1:
                seg_start = chap_offset

            chunk = TextChunk(
                text=full_text,
                index=chunk_index,
                start_offset=seg_start,
                end_offset=seg_start + len(seg),
                chapter_hint=chap_title,
                chapter_indices=[chap_idx],
                estimated_tokens=estimate_tokens(full_text),
            )
            chunks.append(chunk)
            chunk_index += 1

            if overlap_tokens > 0:
                previous_overlap_text = _extract_tail(seg, overlap_tokens)
            else:
                previous_overlap_text = ""

    if not chunks:
        raise ChunkingError("Chunking produced no output chunks.")

    logger.info(
        "Chunked text into %d chunks (total ~%d tokens estimated)",
        len(chunks),
        sum(c.estimated_tokens for c in chunks),
    )

    return chunks


def _extract_tail(text: str, target_tokens: int) -> str:
    """Extract the tail of text that approximates target_tokens tokens.

    Splits at paragraph boundary when possible.
    """
    words = text.split()
    target_words = int(target_tokens / DEFAULT_TOKEN_MULTIPLIER)
    if len(words) <= target_words:
        return text

    tail_words = words[-target_words:]
    tail_text = " ".join(tail_words)

    # Try to start at a paragraph boundary
    para_break = tail_text.find("\n\n")
    if para_break != -1 and para_break < len(tail_text) // 2:
        return tail_text[para_break:].strip()

    return tail_text
