"""Tests for story validation."""

from __future__ import annotations

import pytest

from vne_cli.extraction.validator import validate_story
from vne_cli.providers.errors import StructureValidationError
from vne_cli.schemas.story import (
    Beat,
    BeatType,
    BranchInfo,
    BranchPoint,
    Chapter,
    CharacterRef,
    Choice,
    ChoiceOption,
    Scene,
    Story,
    StoryMetadata,
)


def _make_story(
    characters: dict[str, CharacterRef] | None = None,
    chapters: list[Chapter] | None = None,
) -> Story:
    return Story(
        metadata=StoryMetadata(title="Test"),
        characters=characters or {},
        chapters=chapters or [],
    )


def _make_char(char_id: str, name: str) -> CharacterRef:
    return CharacterRef(id=char_id, name=name)


class TestValidateCharacterReferences:
    """Test character reference validation."""

    def test_valid_references(self) -> None:
        """Story with correct character references should pass."""
        chars = {"char_001": _make_char("char_001", "Elena")}
        scene = Scene(
            id="ch_001_sc_001",
            characters_present=["char_001"],
            beats=[
                Beat(
                    id="b1",
                    type=BeatType.DIALOGUE,
                    character="char_001",
                    text="Hello",
                ),
            ],
        )
        chapter = Chapter(id="ch_001", scenes=[scene])
        story = _make_story(characters=chars, chapters=[chapter])
        warnings = validate_story(story)
        # Should not raise, may have warnings but no errors
        assert isinstance(warnings, list)

    def test_unknown_character_in_scene(self) -> None:
        """Reference to unknown character should raise error."""
        chars = {"char_001": _make_char("char_001", "Elena")}
        scene = Scene(
            id="ch_001_sc_001",
            characters_present=["char_999"],  # unknown
            beats=[],
        )
        chapter = Chapter(id="ch_001", scenes=[scene])
        story = _make_story(characters=chars, chapters=[chapter])
        with pytest.raises(StructureValidationError, match="unknown character"):
            validate_story(story)

    def test_unknown_character_in_dialogue(self) -> None:
        """Dialogue referencing unknown character should raise error."""
        chars = {"char_001": _make_char("char_001", "Elena")}
        scene = Scene(
            id="ch_001_sc_001",
            beats=[
                Beat(
                    id="b1",
                    type=BeatType.DIALOGUE,
                    character="char_999",
                    text="Hello",
                ),
            ],
        )
        chapter = Chapter(id="ch_001", scenes=[scene])
        story = _make_story(characters=chars, chapters=[chapter])
        with pytest.raises(StructureValidationError, match="unknown character"):
            validate_story(story)

    def test_dialogue_without_attribution(self) -> None:
        """Dialogue without character ID should raise error."""
        scene = Scene(
            id="ch_001_sc_001",
            beats=[
                Beat(id="b1", type=BeatType.DIALOGUE, text="Hello"),
            ],
        )
        chapter = Chapter(id="ch_001", scenes=[scene])
        story = _make_story(chapters=[chapter])
        with pytest.raises(StructureValidationError, match="no character attribution"):
            validate_story(story)


class TestValidateBranchTargets:
    """Test branch target validation."""

    def test_valid_branch_targets(self) -> None:
        """Choice targeting existing scene should pass."""
        chars = {"char_001": _make_char("char_001", "Elena")}
        scene1 = Scene(
            id="ch_001_sc_001",
            beats=[
                Beat(
                    id="b1",
                    type=BeatType.CHOICE,
                    text="Choose",
                    options=[
                        ChoiceOption(
                            text="Go left",
                            target_scene="ch_001_sc_002",
                        ),
                    ],
                ),
            ],
        )
        scene2 = Scene(id="ch_001_sc_002")
        chapter = Chapter(id="ch_001", scenes=[scene1, scene2])
        story = _make_story(characters=chars, chapters=[chapter])
        warnings = validate_story(story)
        # No errors about branch targets
        assert not any("targets unknown" in w for w in warnings)

    def test_invalid_branch_target_warns(self) -> None:
        """Choice targeting nonexistent scene should produce warning."""
        scene = Scene(
            id="ch_001_sc_001",
            beats=[
                Beat(
                    id="b1",
                    type=BeatType.CHOICE,
                    text="Choose",
                    options=[
                        ChoiceOption(
                            text="Go left",
                            target_scene="nonexistent_scene",
                        ),
                    ],
                ),
            ],
        )
        chapter = Chapter(id="ch_001", scenes=[scene])
        story = _make_story(chapters=[chapter])
        warnings = validate_story(story)
        assert any("targets unknown scene" in w for w in warnings)


class TestValidateConvergence:
    """Test branch convergence validation."""

    def test_valid_convergence(self) -> None:
        """Chapter with valid convergence scene should pass."""
        scene1 = Scene(
            id="ch_001_sc_001",
            branch_info=BranchInfo(
                is_branch=True, converges_at="ch_001_sc_002"
            ),
        )
        scene2 = Scene(id="ch_001_sc_002")
        chapter = Chapter(
            id="ch_001",
            scenes=[scene1, scene2],
            branch_convergence="ch_001_sc_002",
        )
        story = _make_story(chapters=[chapter])
        warnings = validate_story(story)
        assert not any("convergence" in w.lower() for w in warnings)

    def test_missing_convergence_scene_warns(self) -> None:
        """Convergence pointing to nonexistent scene should warn."""
        scene = Scene(id="ch_001_sc_001")
        chapter = Chapter(
            id="ch_001",
            scenes=[scene],
            branch_convergence="nonexistent",
        )
        story = _make_story(chapters=[chapter])
        warnings = validate_story(story)
        assert any("convergence" in w.lower() for w in warnings)

    def test_branches_without_convergence_warns(self) -> None:
        """Chapter with branches but no convergence point should warn."""
        scene = Scene(
            id="ch_001_sc_001",
            branch_info=BranchInfo(is_branch=True),
        )
        chapter = Chapter(id="ch_001", scenes=[scene])
        story = _make_story(chapters=[chapter])
        warnings = validate_story(story)
        assert any("no convergence" in w.lower() for w in warnings)


class TestCheckOrphanedScenes:
    """Test orphaned scene detection."""

    def test_sequential_scenes_not_orphaned(self) -> None:
        """Sequential scenes in a chapter should not be flagged."""
        scenes = [
            Scene(id="ch_001_sc_001"),
            Scene(id="ch_001_sc_002"),
            Scene(id="ch_001_sc_003"),
        ]
        chapter = Chapter(id="ch_001", scenes=scenes)
        story = _make_story(chapters=[chapter])
        warnings = validate_story(story)
        assert not any("orphaned" in w for w in warnings)

    def test_empty_story(self) -> None:
        """Empty story should pass validation."""
        story = _make_story()
        warnings = validate_story(story)
        assert isinstance(warnings, list)

    def test_empty_chapter_warns(self) -> None:
        """Chapter with no scenes should produce warning."""
        chapter = Chapter(id="ch_001")
        story = _make_story(chapters=[chapter])
        warnings = validate_story(story)
        assert any("no scenes" in w for w in warnings)


class TestNarrationPassesCleanly:
    """Narration-only stories should pass all validation."""

    def test_narration_only(self) -> None:
        scene = Scene(
            id="ch_001_sc_001",
            beats=[
                Beat(id="b1", type=BeatType.NARRATION, text="The sun set."),
                Beat(id="b2", type=BeatType.NARRATION, text="Night fell."),
            ],
        )
        chapter = Chapter(id="ch_001", scenes=[scene])
        story = _make_story(chapters=[chapter])
        warnings = validate_story(story)
        assert not any("error" in w.lower() for w in warnings)
