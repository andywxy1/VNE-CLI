"""Auto-detection of branching cues in novel text.

Identifies points where the narrative suggests player choices:
decision moments, diverging paths, moral dilemmas, etc.
Enforces branch depth and choice count caps from config.
"""

from __future__ import annotations

import re
import uuid

from vne_cli.config.schema import ExtractionConfig
from vne_cli.schemas.story import (
    Beat,
    BeatType,
    BranchInfo,
    BranchPoint,
    Chapter,
    Choice,
    ChoiceOption,
    Scene,
    Story,
)
from vne_cli.utils.logging import get_logger

logger = get_logger(__name__)

# Patterns for explicit branch cues in source text
EXPLICIT_BRANCH_PATTERNS: list[re.Pattern[str]] = [
    # [CHOICE: text] markers
    re.compile(r"\[CHOICE:\s*(.+?)\]", re.IGNORECASE),
    # [BRANCH: text] markers
    re.compile(r"\[BRANCH:\s*(.+?)\]", re.IGNORECASE),
    # [OPTION: text] markers
    re.compile(r"\[OPTION:\s*(.+?)\]", re.IGNORECASE),
    # [DECISION: text] markers
    re.compile(r"\[DECISION:\s*(.+?)\]", re.IGNORECASE),
]

# Patterns for implicit branch cues (narrative suggestions)
IMPLICIT_BRANCH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"you (?:could|can|might|must) (?:choose|decide|pick)", re.IGNORECASE),
    re.compile(r"the (?:reader|player) (?:could|can|might|must) choose", re.IGNORECASE),
    re.compile(r"(?:she|he|they) had to (?:choose|decide)", re.IGNORECASE),
    re.compile(r"(?:two|three|several) (?:options|choices|paths)", re.IGNORECASE),
    re.compile(r"you decide to", re.IGNORECASE),
    re.compile(r"what (?:should|would|will) .+ do\?", re.IGNORECASE),
    re.compile(r"faced with a (?:choice|decision|dilemma)", re.IGNORECASE),
]


def _short_uid() -> str:
    """Generate a short unique ID for branch elements."""
    return uuid.uuid4().hex[:8]


def scan_for_branch_cues(text: str) -> list[dict[str, str]]:
    """Scan text for explicit and implicit branching cues.

    Args:
        text: The text to scan.

    Returns:
        List of dicts with 'type' ('explicit'|'implicit'), 'text', and 'offset'.
    """
    cues: list[dict[str, str]] = []

    for pattern in EXPLICIT_BRANCH_PATTERNS:
        for match in pattern.finditer(text):
            cues.append({
                "type": "explicit",
                "text": match.group(1).strip() if match.lastindex else match.group(0),
                "offset": str(match.start()),
            })

    for pattern in IMPLICIT_BRANCH_PATTERNS:
        for match in pattern.finditer(text):
            cues.append({
                "type": "implicit",
                "text": match.group(0).strip(),
                "offset": str(match.start()),
            })

    # Sort by position in text
    cues.sort(key=lambda c: int(c["offset"]))
    return cues


def detect_and_apply_branches(
    story: Story,
    config: ExtractionConfig,
) -> Story:
    """Detect branching cues and add branch metadata to the story.

    Enforces:
    - max_branch_depth: Maximum nesting depth of branches
    - max_choices_per_branch: Maximum options per choice point
    - Chapter-scoped branching: branches converge by chapter end

    Args:
        story: Extracted story (may already have some branch hints from LLM).
        config: Extraction config with branch limits.

    Returns:
        Story with branch_info populated on relevant scenes.
    """
    max_depth = config.max_branch_depth
    max_choices = config.max_choices_per_branch

    logger.info(
        "Running branch detection (max_depth=%d, max_choices=%d)",
        max_depth,
        max_choices,
    )

    updated_chapters: list[Chapter] = []

    for chapter in story.chapters:
        updated_chapter = _process_chapter_branches(
            chapter, max_depth=max_depth, max_choices=max_choices
        )
        updated_chapters.append(updated_chapter)

    story_dict = story.model_dump(by_alias=True)
    story_dict["chapters"] = [ch.model_dump(by_alias=True) for ch in updated_chapters]
    return Story.model_validate(story_dict)


def _process_chapter_branches(
    chapter: Chapter,
    *,
    max_depth: int,
    max_choices: int,
) -> Chapter:
    """Process branch points within a single chapter.

    Ensures all branches converge at the chapter's last scene.
    Caps choice counts and branch depth.
    """
    if not chapter.scenes:
        return chapter

    # Determine convergence scene (last scene in chapter)
    convergence_scene_id = chapter.scenes[-1].id
    if chapter.branch_convergence:
        convergence_scene_id = chapter.branch_convergence

    # Scan existing choice beats for branch enforcement
    updated_scenes: list[Scene] = []
    branch_points: list[BranchPoint] = list(chapter.branch_points)
    current_depth = 0

    for scene in chapter.scenes:
        updated_beats: list[Beat] = []
        scene_has_branch = False

        for beat in scene.beats:
            if beat.type == BeatType.CHOICE:
                scene_has_branch = True

                # Cap choices
                options = beat.options[:max_choices]

                # Enforce depth limit
                if current_depth >= max_depth:
                    logger.debug(
                        "Branch depth limit reached at scene %s, removing choice",
                        scene.id,
                    )
                    # Convert to narration about the decision
                    updated_beats.append(Beat(
                        id=beat.id or f"beat_{_short_uid()}",
                        type=BeatType.NARRATION,
                        text=f"[Decision: {beat.text}]" if beat.text else "",
                    ))
                    continue

                # Cap the options and ensure convergence targets exist
                capped_options: list[ChoiceOption] = []
                for opt in options:
                    capped_options.append(ChoiceOption(
                        text=opt.text,
                        target_scene=opt.target_scene or convergence_scene_id,
                        consequence_tag=opt.consequence_tag,
                    ))

                updated_beats.append(Beat(
                    id=beat.id or f"beat_{_short_uid()}",
                    type=BeatType.CHOICE,
                    text=beat.text,
                    options=capped_options,
                ))

                # Create or update branch point
                bp = BranchPoint(
                    trigger_event_id=beat.id or f"beat_{_short_uid()}",
                    prompt_text=beat.text,
                    choices=[
                        Choice(
                            label=opt.text,
                            consequence_flag=opt.consequence_tag,
                        )
                        for opt in capped_options
                    ],
                    convergence_scene_id=convergence_scene_id,
                )
                branch_points.append(bp)
                current_depth += 1
            else:
                updated_beats.append(beat)

        # Update scene branch info
        branch_info = scene.branch_info
        if scene_has_branch:
            branch_info = BranchInfo(
                is_branch=True,
                branch_source=scene.id,
                converges_at=convergence_scene_id,
            )

        updated_scene = scene.model_copy(update={
            "beats": updated_beats,
            "branch_info": branch_info,
        })
        updated_scenes.append(updated_scene)

    # Set convergence on the last scene
    if updated_scenes:
        last_scene = updated_scenes[-1]
        if any(bp.convergence_scene_id == last_scene.id for bp in branch_points):
            updated_scenes[-1] = last_scene.model_copy(update={
                "branch_info": BranchInfo(
                    is_branch=False,
                    branch_source=None,
                    converges_at=None,
                ),
            })

    return chapter.model_copy(update={
        "scenes": updated_scenes,
        "branch_points": branch_points,
        "branch_convergence": convergence_scene_id,
    })


def detect_explicit_cues_in_text(text: str) -> list[dict[str, str]]:
    """Detect only explicit branching markers in raw text.

    Useful for the pre-scan phase before LLM processing to inform
    the structure pass about author-intended branch points.

    Args:
        text: Raw novel text.

    Returns:
        List of explicit branch cue dicts.
    """
    return [c for c in scan_for_branch_cues(text) if c["type"] == "explicit"]
