"""Shared pytest fixtures for VNE-CLI tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vne_cli.config.schema import ChunkingConfig, ExtractionConfig, VneConfig


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    return tmp_path / "test-project"


@pytest.fixture
def default_config() -> VneConfig:
    """Return a VneConfig with all defaults."""
    return VneConfig()


@pytest.fixture
def default_chunking_config() -> ChunkingConfig:
    """Return a ChunkingConfig with all defaults."""
    return ChunkingConfig()


@pytest.fixture
def default_extraction_config() -> ExtractionConfig:
    """Return an ExtractionConfig with all defaults."""
    return ExtractionConfig()


@pytest.fixture
def sample_novel_text() -> str:
    """Return minimal sample novel text for testing."""
    return (
        "Chapter 1: The Beginning\n\n"
        'Elena walked into the library. "I never expected to find this here," '
        "she said.\n\n"
        "The dust motes drifted through the amber light.\n\n"
        '"What did you find?" asked Marcus, stepping closer.\n\n'
        "Elena held up the letter. She had to decide what to do.\n"
    )


@pytest.fixture
def multi_chapter_novel_text() -> str:
    """Return a longer novel text with multiple chapters."""
    chapters: list[str] = []
    for i in range(1, 4):
        paragraphs = [
            f"Chapter {i}: The {'Beginning' if i == 1 else 'Middle' if i == 2 else 'End'}",
            "",
        ]
        for j in range(5):
            paragraphs.append(
                f"Paragraph {j + 1} of chapter {i}. "
                + "This is some filler text to make the paragraph longer. " * 5
            )
            paragraphs.append("")
        chapters.append("\n".join(paragraphs))
    return "\n\n".join(chapters)


class MockLLMProvider:
    """A mock LLM provider for testing without real API calls."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = responses or []
        self._call_count = 0
        self._calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "mock-llm"

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        self._calls.append({
            "prompt": prompt,
            "system": system,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        if self._call_count < len(self._responses):
            response = self._responses[self._call_count]
        else:
            response = "{}"
        self._call_count += 1
        return response

    async def complete_structured(
        self,
        prompt: str,
        schema: type,
        *,
        system: str | None = None,
        temperature: float = 0.3,
    ) -> Any:
        return await self.complete(prompt, system=system, temperature=temperature)

    async def close(self) -> None:
        pass


@pytest.fixture
def mock_llm() -> MockLLMProvider:
    """Return a mock LLM provider."""
    return MockLLMProvider()
