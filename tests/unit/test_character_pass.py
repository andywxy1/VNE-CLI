"""Tests for character extraction pre-pass."""

from __future__ import annotations

import json

import pytest

from vne_cli.extraction.character_pass import extract_characters
from vne_cli.extraction.chunker import TextChunk
from vne_cli.providers.errors import ExtractionError


def _make_mock_llm(responses: list[str] | None = None):  # type: ignore[no-untyped-def]
    """Create a mock LLM inline to avoid import issues."""
    from tests.conftest import MockLLMProvider
    return MockLLMProvider(responses=responses)


def _make_chunk(text: str, index: int = 0) -> TextChunk:
    return TextChunk(
        text=text,
        index=index,
        start_offset=0,
        end_offset=len(text),
        chapter_hint="Test Chapter",
        estimated_tokens=len(text.split()),
    )


class TestExtractCharacters:
    """Tests for character extraction using mock LLM."""

    @pytest.mark.asyncio
    async def test_extracts_characters(self) -> None:
        """Should extract characters from chunk via LLM."""
        chunk_response = json.dumps({
            "characters": [
                {
                    "name": "Elena",
                    "aliases": ["Princess Elena", "Lena"],
                    "is_protagonist": True,
                    "physical_description": "Silver hair, blue eyes",
                    "personality_traits": ["brave", "kind"],
                    "role": "protagonist",
                },
                {
                    "name": "Marcus",
                    "aliases": [],
                    "is_protagonist": False,
                    "physical_description": "Tall, dark hair",
                    "personality_traits": ["loyal"],
                    "role": "supporting",
                },
            ]
        })
        merge_response = json.dumps({
            "protagonist_id": "char_001",
            "characters": [
                {
                    "id": "char_001",
                    "name": "Elena",
                    "aliases": ["Princess Elena", "Lena"],
                    "is_protagonist": True,
                    "physical_description": "Silver hair, blue eyes",
                    "personality_traits": ["brave", "kind"],
                    "role": "protagonist",
                    "relationships": {"char_002": "friend"},
                    "sprite_expressions": ["neutral", "happy", "sad"],
                },
                {
                    "id": "char_002",
                    "name": "Marcus",
                    "aliases": [],
                    "is_protagonist": False,
                    "physical_description": "Tall, dark hair",
                    "personality_traits": ["loyal"],
                    "role": "supporting",
                    "relationships": {"char_001": "friend"},
                    "sprite_expressions": ["neutral", "happy"],
                },
            ],
        })

        llm = _make_mock_llm(responses=[chunk_response, merge_response])
        chunks = [_make_chunk("Elena walked in. Marcus followed.")]

        registry = await extract_characters(chunks, llm)

        assert len(registry.characters) == 2
        assert registry.protagonist == "char_001"
        assert "char_001" in registry.characters
        assert registry.characters["char_001"].name == "Elena"
        assert "char_002" in registry.characters

    @pytest.mark.asyncio
    async def test_empty_chunks_raises(self) -> None:
        """Empty chunk list should raise ExtractionError."""
        llm = _make_mock_llm()
        with pytest.raises(ExtractionError, match="No text chunks"):
            await extract_characters([], llm)

    @pytest.mark.asyncio
    async def test_no_characters_found(self) -> None:
        """When LLM finds no characters, should return empty registry."""
        chunk_response = json.dumps({"characters": []})
        llm = _make_mock_llm(responses=[chunk_response])
        chunks = [_make_chunk("The wind blew across the empty plain.")]

        registry = await extract_characters(chunks, llm)
        assert len(registry.characters) == 0

    @pytest.mark.asyncio
    async def test_deduplicates_across_chunks(self) -> None:
        """Characters from multiple chunks should be merged."""
        chunk1_response = json.dumps({
            "characters": [
                {"name": "Elena", "aliases": ["Lena"], "role": "protagonist"}
            ]
        })
        chunk2_response = json.dumps({
            "characters": [
                {"name": "Princess Elena", "aliases": ["Elena"], "role": "protagonist"}
            ]
        })
        merge_response = json.dumps({
            "protagonist_id": "char_001",
            "characters": [
                {
                    "id": "char_001",
                    "name": "Elena",
                    "aliases": ["Lena", "Princess Elena"],
                    "is_protagonist": True,
                    "role": "protagonist",
                }
            ],
        })

        llm = _make_mock_llm(responses=[
            chunk1_response, chunk2_response, merge_response
        ])
        chunks = [
            _make_chunk("Elena spoke softly.", 0),
            _make_chunk("Princess Elena entered.", 1),
        ]

        registry = await extract_characters(chunks, llm)
        assert len(registry.characters) == 1
        assert "Lena" in registry.characters["char_001"].aliases

    @pytest.mark.asyncio
    async def test_handles_malformed_llm_response(self) -> None:
        """Malformed LLM response for a chunk should not crash."""
        bad_response = "not valid json at all"
        merge_response = json.dumps({
            "protagonist_id": "",
            "characters": [],
        })
        # Bad chunk response -> no chars found -> merge never called -> empty registry
        llm = _make_mock_llm(responses=[bad_response, merge_response])
        chunks = [_make_chunk("Some text")]

        registry = await extract_characters(chunks, llm)
        assert len(registry.characters) == 0

    @pytest.mark.asyncio
    async def test_source_file_preserved(self) -> None:
        """source_file metadata should be passed through."""
        chunk_response = json.dumps({"characters": []})
        llm = _make_mock_llm(responses=[chunk_response])
        chunks = [_make_chunk("Text")]

        registry = await extract_characters(
            chunks, llm, source_file="novel.txt"
        )
        assert registry.source_file == "novel.txt"
