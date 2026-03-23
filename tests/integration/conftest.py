"""Integration test fixtures: mock providers and test data builders.

Provides deterministic mock LLM and image providers that return
predefined structured output, enabling full pipeline testing
without real API calls.
"""

from __future__ import annotations

import json
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from vne_cli.config.schema import (
    AssemblyConfig,
    AssetsConfig,
    CinematicConfig,
    VneConfig,
)
from vne_cli.schemas.asset_manifest import (
    AssetEntry,
    AssetManifestSchema,
    AssetStatus,
    AssetSummary,
    AssetType,
)
from vne_cli.schemas.characters import Character, CharacterRegistry
from vne_cli.schemas.story import (
    Beat,
    BeatType,
    BranchInfo,
    BranchPoint,
    Chapter,
    CharacterRef,
    Choice,
    ChoiceOption,
    ExtractionMetadata,
    Scene,
    Story,
    StoryMetadata,
)

# ---------------------------------------------------------------------------
# Paths to fixture files
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def sample_novel_path() -> Path:
    return FIXTURES_DIR / "sample_novel.txt"


@pytest.fixture
def branching_novel_path() -> Path:
    return FIXTURES_DIR / "branching_novel.txt"


@pytest.fixture
def minimal_novel_path() -> Path:
    return FIXTURES_DIR / "minimal_novel.txt"


# ---------------------------------------------------------------------------
# Minimal valid PNG bytes (1x1 transparent pixel)
# ---------------------------------------------------------------------------

def make_minimal_png() -> bytes:
    """Create a minimal valid 1x1 transparent PNG (67 bytes)."""
    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
    raw = b"\x00\x00\x00\x00\x00"  # filter byte + 1 RGBA pixel
    idat = _chunk(b"IDAT", zlib.compress(raw))
    iend = _chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


MINIMAL_PNG = make_minimal_png()


# ---------------------------------------------------------------------------
# Mock LLM Provider
# ---------------------------------------------------------------------------

class MockLLMProvider:
    """Deterministic LLM provider that returns predefined structured output.

    For character extraction, returns a two-character registry (Elena, Marcus).
    For structure extraction, returns a single chapter with two scenes and dialogue.
    """

    def __init__(self, *, branching: bool = False) -> None:
        self._branching = branching
        self._calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "mock-llm"

    @property
    def calls(self) -> list[dict[str, Any]]:
        return list(self._calls)

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
            "prompt": prompt[:200],
            "system": (system or "")[:100],
            "temperature": temperature,
        })

        # Determine what kind of extraction this is by inspecting the system prompt.
        # Order matters: check more specific patterns first to avoid false matches.
        sys_lower = (system or "").lower()
        prompt_lower = prompt.lower()

        if "entity resolution" in sys_lower or "merge and deduplicate" in prompt_lower:
            return self._character_merge_response()
        elif "extract all characters" in sys_lower:
            return self._character_response()
        elif "narrative structure" in sys_lower or "structure analyst" in sys_lower:
            return self._structure_response()
        else:
            return "{}"

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

    def _character_response(self) -> str:
        return json.dumps({
            "characters": [
                {
                    "name": "Elena",
                    "aliases": ["Princess Elena", "Lena"],
                    "is_protagonist": True,
                    "physical_description": "Tall with silver hair, blue eyes",
                    "clothing_default": "Royal blue gown",
                    "personality_traits": ["determined", "compassionate"],
                    "role": "protagonist",
                },
                {
                    "name": "Marcus",
                    "aliases": ["Captain Marcus"],
                    "is_protagonist": False,
                    "physical_description": "Tall, dark eyes, broad shoulders",
                    "clothing_default": "Guard uniform",
                    "personality_traits": ["loyal", "cautious"],
                    "role": "supporting",
                },
            ]
        })

    def _character_merge_response(self) -> str:
        return json.dumps({
            "protagonist_id": "char_001",
            "characters": [
                {
                    "id": "char_001",
                    "name": "Elena",
                    "aliases": ["Princess Elena", "Lena"],
                    "is_protagonist": True,
                    "physical_description": "Tall with silver hair, blue eyes",
                    "clothing_default": "Royal blue gown",
                    "personality_traits": ["determined", "compassionate"],
                    "role": "protagonist",
                    "relationships": {"char_002": "childhood friend"},
                    "sprite_expressions": ["neutral", "happy", "sad", "angry", "surprised"],
                },
                {
                    "id": "char_002",
                    "name": "Marcus",
                    "aliases": ["Captain Marcus"],
                    "is_protagonist": False,
                    "physical_description": "Tall, dark eyes, broad shoulders",
                    "clothing_default": "Guard uniform",
                    "personality_traits": ["loyal", "cautious"],
                    "role": "supporting",
                    "relationships": {"char_001": "childhood friend"},
                    "sprite_expressions": ["neutral", "happy", "angry"],
                },
            ],
        })

    def _structure_response(self) -> str:
        scenes = [
            {
                "id": "ch_001_sc_001",
                "title": "The Library",
                "location": "Castle Library",
                "time_of_day": "afternoon",
                "background_description": "Ornate castle library with tall shelves and golden light",
                "characters_present": ["char_001", "char_002"],
                "beats": [
                    {
                        "id": "beat_001",
                        "type": "narration",
                        "text": "Elena walked into the grand library of Thornwood Castle.",
                    },
                    {
                        "id": "beat_002",
                        "type": "dialogue",
                        "character": "char_001",
                        "expression": "surprised",
                        "text": "I never expected to find this here.",
                    },
                    {
                        "id": "beat_003",
                        "type": "dialogue",
                        "character": "char_002",
                        "expression": "neutral",
                        "text": "That's your father's crest. We should be careful.",
                    },
                ],
                "cinematic_annotations": [
                    {
                        "cue_type": "sfx",
                        "reference": "[SFX: page_turn]",
                        "source_text": "pulling a yellowed envelope",
                        "beat_id": "beat_002",
                    }
                ],
            },
            {
                "id": "ch_001_sc_002",
                "title": "The Decision",
                "location": "Castle Library",
                "time_of_day": "afternoon",
                "background_description": "Ornate castle library with tall shelves and golden light",
                "characters_present": ["char_001", "char_002"],
                "beats": [
                    {
                        "id": "beat_004",
                        "type": "narration",
                        "text": "Elena held up the letter, her blue eyes scanning the faded ink.",
                    },
                    {
                        "id": "beat_005",
                        "type": "dialogue",
                        "character": "char_001",
                        "expression": "determined",
                        "text": "I have to decide what to do.",
                    },
                ],
                "cinematic_annotations": [],
            },
        ]

        # If branching mode, add a choice beat to scene 2
        if self._branching:
            scenes[1]["beats"].append({
                "id": "beat_006",
                "type": "choice",
                "text": "What should Elena do?",
                "options": [
                    {
                        "text": "Read the letter aloud",
                        "target_scene": "ch_001_sc_003a",
                        "consequence_tag": "trusting",
                    },
                    {
                        "text": "Hide the letter",
                        "target_scene": "ch_001_sc_003b",
                        "consequence_tag": "cautious",
                    },
                ],
            })

        return json.dumps({
            "title": "The Hidden Letter",
            "synopsis": "Elena discovers a hidden letter in the castle library.",
            "scenes": scenes,
            "variables": [
                {
                    "name": "found_letter",
                    "var_type": "bool",
                    "default_value": "false",
                    "description": "Whether Elena found the hidden letter",
                }
            ],
        })


# ---------------------------------------------------------------------------
# Mock Image Provider
# ---------------------------------------------------------------------------

class MockImageProvider:
    """Deterministic image provider that returns a minimal valid PNG."""

    def __init__(self) -> None:
        self._calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "mock-image"

    @property
    def calls(self) -> list[dict[str, Any]]:
        return list(self._calls)

    async def generate(
        self,
        prompt: str,
        *,
        width: int = 1024,
        height: int = 1024,
        style: str | None = None,
        negative_prompt: str | None = None,
    ) -> bytes:
        self._calls.append({
            "prompt": prompt[:100],
            "width": width,
            "height": height,
            "style": style,
        })
        return MINIMAL_PNG

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm() -> MockLLMProvider:
    """A mock LLM provider returning linear (non-branching) output."""
    return MockLLMProvider(branching=False)


@pytest.fixture
def mock_llm_branching() -> MockLLMProvider:
    """A mock LLM provider returning branching output."""
    return MockLLMProvider(branching=True)


@pytest.fixture
def mock_image_provider() -> MockImageProvider:
    return MockImageProvider()


@pytest.fixture
def test_config() -> VneConfig:
    """VneConfig with defaults suitable for integration testing."""
    return VneConfig()


# ---------------------------------------------------------------------------
# Pre-built story data fixtures (bypass LLM entirely)
# ---------------------------------------------------------------------------

def build_linear_story() -> Story:
    """Build a simple linear story with 1 chapter, 2 scenes, 2 characters."""
    return Story(
        metadata=StoryMetadata(
            title="Test Story",
            author="Test Author",
            source_file="test.txt",
            extracted_at=datetime(2026, 3, 22, tzinfo=timezone.utc),
            vne_cli_version="0.1.0",
            language="en",
        ),
        characters={
            "char_001": CharacterRef(
                id="char_001",
                name="Elena",
                aliases=["Princess Elena"],
                is_protagonist=True,
                description="Tall with silver hair, blue eyes",
                personality="determined, compassionate",
                sprite_variants=["neutral", "happy", "sad"],
                first_appearance="ch_001_sc_001",
            ),
            "char_002": CharacterRef(
                id="char_002",
                name="Marcus",
                aliases=["Captain Marcus"],
                is_protagonist=False,
                description="Tall, dark eyes, broad shoulders",
                personality="loyal, cautious",
                sprite_variants=["neutral", "angry"],
                first_appearance="ch_001_sc_001",
            ),
        },
        chapters=[
            Chapter(
                id="ch_001",
                index=0,
                title="The Library",
                synopsis="Elena discovers a hidden letter.",
                scenes=[
                    Scene(
                        id="ch_001_sc_001",
                        title="Discovery",
                        location="Castle Library",
                        time_of_day="afternoon",
                        background_description="Ornate castle library with tall shelves",
                        characters_present=["char_001", "char_002"],
                        beats=[
                            Beat(
                                id="beat_001",
                                type=BeatType.NARRATION,
                                text="Elena walked into the grand library.",
                            ),
                            Beat(
                                id="beat_002",
                                type=BeatType.DIALOGUE,
                                character="char_001",
                                expression="surprised",
                                text="I never expected to find this here.",
                            ),
                            Beat(
                                id="beat_003",
                                type=BeatType.DIALOGUE,
                                character="char_002",
                                expression="neutral",
                                text="That is your father's crest.",
                            ),
                        ],
                    ),
                    Scene(
                        id="ch_001_sc_002",
                        title="The Decision",
                        location="Castle Library",
                        time_of_day="afternoon",
                        background_description="Ornate castle library with tall shelves",
                        characters_present=["char_001", "char_002"],
                        beats=[
                            Beat(
                                id="beat_004",
                                type=BeatType.NARRATION,
                                text="Elena held up the letter.",
                            ),
                            Beat(
                                id="beat_005",
                                type=BeatType.DIALOGUE,
                                character="char_001",
                                expression="determined",
                                text="I have to decide what to do.",
                            ),
                        ],
                    ),
                ],
            ),
        ],
        extraction_metadata=ExtractionMetadata(
            extractor_version="0.1.0",
            llm_provider="mock-llm",
            total_chunks=1,
        ),
    )


def build_branching_story() -> Story:
    """Build a story with a branch point and convergence."""
    story = build_linear_story()
    story.metadata.title = "Test Branching Story"

    # Add choice beat to second scene
    story.chapters[0].scenes[1].beats.append(
        Beat(
            id="beat_006",
            type=BeatType.CHOICE,
            text="What should Elena do?",
            options=[
                ChoiceOption(
                    text="Read the letter aloud",
                    target_scene="ch_001_sc_003a",
                    consequence_tag="trusting",
                ),
                ChoiceOption(
                    text="Hide the letter",
                    target_scene="ch_001_sc_003b",
                    consequence_tag="cautious",
                ),
            ],
        )
    )

    # Add branch scenes
    story.chapters[0].scenes.extend([
        Scene(
            id="ch_001_sc_003a",
            title="Read Aloud",
            location="Castle Library",
            background_description="Ornate castle library with tall shelves",
            characters_present=["char_001", "char_002"],
            beats=[
                Beat(
                    id="beat_007",
                    type=BeatType.DIALOGUE,
                    character="char_001",
                    expression="neutral",
                    text="Listen to this, Marcus.",
                ),
            ],
            branch_info=BranchInfo(
                is_branch=True,
                branch_source="ch_001_sc_002",
                converges_at="ch_001_sc_004",
            ),
        ),
        Scene(
            id="ch_001_sc_003b",
            title="Hide Letter",
            location="Castle Library",
            background_description="Ornate castle library with tall shelves",
            characters_present=["char_001"],
            beats=[
                Beat(
                    id="beat_008",
                    type=BeatType.NARRATION,
                    text="Elena tucked the letter into her sleeve.",
                ),
            ],
            branch_info=BranchInfo(
                is_branch=True,
                branch_source="ch_001_sc_002",
                converges_at="ch_001_sc_004",
            ),
        ),
        Scene(
            id="ch_001_sc_004",
            title="Convergence",
            location="Castle Library",
            background_description="Ornate castle library with tall shelves",
            characters_present=["char_001", "char_002"],
            beats=[
                Beat(
                    id="beat_009",
                    type=BeatType.NARRATION,
                    text="The sun began to set outside the library windows.",
                ),
            ],
        ),
    ])

    # Add branch point metadata
    story.chapters[0].branch_points.append(
        BranchPoint(
            trigger_event_id="beat_006",
            prompt_text="What should Elena do?",
            choices=[
                Choice(label="Read aloud", consequence_flag="trusting"),
                Choice(label="Hide letter", consequence_flag="cautious"),
            ],
            convergence_scene_id="ch_001_sc_004",
        )
    )
    story.chapters[0].branch_convergence = "ch_001_sc_004"

    return story


def build_minimal_story() -> Story:
    """Build a minimal single-scene, two-character story."""
    return Story(
        metadata=StoryMetadata(
            title="Minimal Story",
            source_file="minimal.txt",
            extracted_at=datetime(2026, 3, 22, tzinfo=timezone.utc),
            vne_cli_version="0.1.0",
        ),
        characters={
            "char_001": CharacterRef(
                id="char_001",
                name="Anna",
                is_protagonist=True,
                description="Young woman with brown hair",
                sprite_variants=["neutral"],
                first_appearance="ch_001_sc_001",
            ),
            "char_002": CharacterRef(
                id="char_002",
                name="Luca",
                is_protagonist=False,
                description="Young man with dark hair",
                sprite_variants=["neutral"],
                first_appearance="ch_001_sc_001",
            ),
        },
        chapters=[
            Chapter(
                id="ch_001",
                index=0,
                title="A Brief Encounter",
                scenes=[
                    Scene(
                        id="ch_001_sc_001",
                        title="The Cafe",
                        location="Cafe",
                        background_description="Small cafe with rain-streaked windows",
                        characters_present=["char_001", "char_002"],
                        beats=[
                            Beat(
                                id="beat_001",
                                type=BeatType.DIALOGUE,
                                character="char_002",
                                expression="neutral",
                                text="You came.",
                            ),
                            Beat(
                                id="beat_002",
                                type=BeatType.DIALOGUE,
                                character="char_001",
                                expression="neutral",
                                text="I almost didn't.",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def linear_story() -> Story:
    return build_linear_story()


@pytest.fixture
def branching_story() -> Story:
    return build_branching_story()


@pytest.fixture
def minimal_story() -> Story:
    return build_minimal_story()


def populate_assets_dir(story: Story, assets_dir: Path) -> None:
    """Create fake asset files (minimal PNGs) for a story in the given directory.

    Creates backgrounds/ and characters/ subdirectories with appropriately
    named files so the assembler can find and organize them.
    """
    bg_dir = assets_dir / "backgrounds"
    char_dir = assets_dir / "characters"
    bg_dir.mkdir(parents=True, exist_ok=True)
    char_dir.mkdir(parents=True, exist_ok=True)

    # Create background images for each unique location
    seen_locations: set[str] = set()
    for chapter in story.chapters:
        for scene in chapter.scenes:
            loc = scene.background_description or scene.location
            if loc and loc not in seen_locations:
                seen_locations.add(loc)
                filename = f"bg_{scene.id}.png"
                (bg_dir / filename).write_bytes(MINIMAL_PNG)

    # Create character sprites
    for char_id, char_ref in story.characters.items():
        expressions = char_ref.sprite_variants or ["neutral"]
        for expr in expressions:
            filename = f"{char_id}_{expr}.png"
            (char_dir / filename).write_bytes(MINIMAL_PNG)
