"""Tests for branch detection."""

from __future__ import annotations

import pytest

from vne_cli.config.schema import ExtractionConfig
from vne_cli.extraction.branch_detector import (
    detect_and_apply_branches,
    detect_explicit_cues_in_text,
    scan_for_branch_cues,
)
from vne_cli.schemas.story import (
    Beat,
    BeatType,
    BranchInfo,
    Chapter,
    ChoiceOption,
    Scene,
    Story,
    StoryMetadata,
)


def _make_story(chapters: list[Chapter]) -> Story:
    """Helper to build a minimal Story for testing."""
    return Story(
        metadata=StoryMetadata(title="Test"),
        chapters=chapters,
    )


def _make_scene(scene_id: str, beats: list[Beat] | None = None) -> Scene:
    """Helper to build a minimal Scene."""
    return Scene(
        id=scene_id,
        title=f"Scene {scene_id}",
        beats=beats or [],
    )


def _make_choice_beat(
    beat_id: str = "beat_001",
    prompt: str = "What do you do?",
    options: list[ChoiceOption] | None = None,
) -> Beat:
    """Helper to build a choice beat."""
    return Beat(
        id=beat_id,
        type=BeatType.CHOICE,
        text=prompt,
        options=options or [
            ChoiceOption(text="Option A", target_scene="sc_a", consequence_tag="chose_a"),
            ChoiceOption(text="Option B", target_scene="sc_b", consequence_tag="chose_b"),
        ],
    )


class TestScanForBranchCues:
    """Test raw text scanning for branch cues."""

    def test_explicit_choice_marker(self) -> None:
        text = "She paused. [CHOICE: Fight or flee] The wind howled."
        cues = scan_for_branch_cues(text)
        explicit = [c for c in cues if c["type"] == "explicit"]
        assert len(explicit) >= 1
        assert "Fight or flee" in explicit[0]["text"]

    def test_explicit_branch_marker(self) -> None:
        text = "The path split. [BRANCH: left or right]"
        cues = scan_for_branch_cues(text)
        explicit = [c for c in cues if c["type"] == "explicit"]
        assert len(explicit) >= 1

    def test_explicit_decision_marker(self) -> None:
        text = "He stood frozen. [DECISION: help the stranger or walk away]"
        cues = scan_for_branch_cues(text)
        explicit = [c for c in cues if c["type"] == "explicit"]
        assert len(explicit) >= 1

    def test_implicit_you_decide(self) -> None:
        text = "Looking at the map, you decide to head north."
        cues = scan_for_branch_cues(text)
        implicit = [c for c in cues if c["type"] == "implicit"]
        assert len(implicit) >= 1

    def test_implicit_could_choose(self) -> None:
        text = "You could choose to stay or leave."
        cues = scan_for_branch_cues(text)
        implicit = [c for c in cues if c["type"] == "implicit"]
        assert len(implicit) >= 1

    def test_implicit_what_should(self) -> None:
        text = 'What should Elena do?'
        cues = scan_for_branch_cues(text)
        implicit = [c for c in cues if c["type"] == "implicit"]
        assert len(implicit) >= 1

    def test_no_cues(self) -> None:
        text = "The sun rose over the quiet village. Birds sang in the trees."
        cues = scan_for_branch_cues(text)
        assert len(cues) == 0

    def test_multiple_cues_sorted(self) -> None:
        text = "[CHOICE: A] some text [CHOICE: B] more text [CHOICE: C]"
        cues = scan_for_branch_cues(text)
        offsets = [int(c["offset"]) for c in cues]
        assert offsets == sorted(offsets)


class TestDetectExplicitCues:
    """Test explicit-only cue detection."""

    def test_filters_implicit(self) -> None:
        text = "[CHOICE: fight] and you decide to run"
        cues = detect_explicit_cues_in_text(text)
        assert len(cues) == 1
        assert cues[0]["type"] == "explicit"


class TestDetectAndApplyBranches:
    """Test branch enforcement on story structure."""

    def test_respects_max_branch_depth(self) -> None:
        """Branch depth should not exceed configured maximum."""
        # Create a chapter with multiple choice beats
        beats1 = [_make_choice_beat("b1", "Choice 1")]
        beats2 = [_make_choice_beat("b2", "Choice 2")]
        beats3 = [_make_choice_beat("b3", "Choice 3")]

        scenes = [
            _make_scene("ch_001_sc_001", beats1),
            _make_scene("ch_001_sc_002", beats2),
            _make_scene("ch_001_sc_003", beats3),
            _make_scene("ch_001_sc_004"),  # convergence
        ]
        chapter = Chapter(id="ch_001", index=0, title="Test", scenes=scenes)
        story = _make_story([chapter])

        config = ExtractionConfig(max_branch_depth=2, max_choices_per_branch=3)
        result = detect_and_apply_branches(story, config)

        # With max_depth=2, only 2 choice beats should remain as choices
        ch = result.chapters[0]
        choice_count = sum(
            1 for scene in ch.scenes
            for beat in scene.beats
            if beat.type == BeatType.CHOICE
        )
        assert choice_count <= 2

    def test_respects_max_choices(self) -> None:
        """Choice count per branch should be capped."""
        many_options = [
            ChoiceOption(text=f"Option {i}", target_scene=f"sc_{i}")
            for i in range(10)
        ]
        beat = Beat(
            id="b1", type=BeatType.CHOICE, text="Choose", options=many_options
        )
        scenes = [
            _make_scene("ch_001_sc_001", [beat]),
            _make_scene("ch_001_sc_002"),
        ]
        chapter = Chapter(id="ch_001", index=0, title="Test", scenes=scenes)
        story = _make_story([chapter])

        config = ExtractionConfig(max_choices_per_branch=3)
        result = detect_and_apply_branches(story, config)

        ch = result.chapters[0]
        for scene in ch.scenes:
            for b in scene.beats:
                if b.type == BeatType.CHOICE:
                    assert len(b.options) <= 3

    def test_chapter_scoped_convergence(self) -> None:
        """Branches should converge by end of chapter."""
        beat = _make_choice_beat("b1")
        scenes = [
            _make_scene("ch_001_sc_001", [beat]),
            _make_scene("ch_001_sc_002"),
            _make_scene("ch_001_sc_003"),
        ]
        chapter = Chapter(id="ch_001", index=0, title="Test", scenes=scenes)
        story = _make_story([chapter])

        config = ExtractionConfig()
        result = detect_and_apply_branches(story, config)

        ch = result.chapters[0]
        # Branch convergence should point to the last scene
        assert ch.branch_convergence == "ch_001_sc_003"

    def test_branch_points_created(self) -> None:
        """BranchPoint entries should be created for choice beats."""
        beat = _make_choice_beat("b1")
        scenes = [
            _make_scene("ch_001_sc_001", [beat]),
            _make_scene("ch_001_sc_002"),
        ]
        chapter = Chapter(id="ch_001", index=0, title="Test", scenes=scenes)
        story = _make_story([chapter])

        config = ExtractionConfig()
        result = detect_and_apply_branches(story, config)

        ch = result.chapters[0]
        assert len(ch.branch_points) >= 1
        bp = ch.branch_points[0]
        assert bp.convergence_scene_id == "ch_001_sc_002"
        assert len(bp.choices) == 2

    def test_empty_chapter(self) -> None:
        """Chapters with no scenes should pass through safely."""
        chapter = Chapter(id="ch_001", index=0, title="Empty")
        story = _make_story([chapter])
        config = ExtractionConfig()
        result = detect_and_apply_branches(story, config)
        assert len(result.chapters) == 1
        assert len(result.chapters[0].scenes) == 0

    def test_no_choices_passthrough(self) -> None:
        """Chapters without choices should pass through unchanged."""
        narration = Beat(id="b1", type=BeatType.NARRATION, text="Hello world")
        scenes = [_make_scene("ch_001_sc_001", [narration])]
        chapter = Chapter(id="ch_001", index=0, title="Test", scenes=scenes)
        story = _make_story([chapter])

        config = ExtractionConfig()
        result = detect_and_apply_branches(story, config)

        ch = result.chapters[0]
        assert len(ch.branch_points) == 0
        assert ch.scenes[0].beats[0].type == BeatType.NARRATION

    def test_branch_info_set_on_choice_scene(self) -> None:
        """Scenes with choices should have branch_info.is_branch = True."""
        beat = _make_choice_beat("b1")
        scenes = [
            _make_scene("ch_001_sc_001", [beat]),
            _make_scene("ch_001_sc_002"),
        ]
        chapter = Chapter(id="ch_001", index=0, title="Test", scenes=scenes)
        story = _make_story([chapter])

        config = ExtractionConfig()
        result = detect_and_apply_branches(story, config)

        ch = result.chapters[0]
        assert ch.scenes[0].branch_info.is_branch is True
        assert ch.scenes[0].branch_info.converges_at == "ch_001_sc_002"
