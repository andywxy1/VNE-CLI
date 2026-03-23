"""Integration tests for the full pipeline.

These tests require provider configuration and are intended for
WS4-T1 (E2E testing).
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Integration tests pending WS4-T1")
class TestFullPipeline:
    """End-to-end pipeline tests."""

    def test_extract_to_assemble(self) -> None:
        """Full pipeline: novel.txt -> extract -> generate-assets -> assemble."""

    def test_resume_asset_generation(self) -> None:
        """Asset generation should resume from manifest on re-run."""
