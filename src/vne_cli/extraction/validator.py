"""Validation for extraction output.

Validates the extracted story structure for internal consistency:
- All character references resolve to the registry
- All branch targets reference existing scenes
- Branch convergence points exist
- No orphaned scenes
"""

from __future__ import annotations

from vne_cli.providers.errors import StructureValidationError
from vne_cli.schemas.story import BeatType, Story
from vne_cli.utils.logging import get_logger

logger = get_logger(__name__)


def validate_story(story: Story) -> list[str]:
    """Validate extracted story for internal consistency.

    Args:
        story: The extracted story to validate.

    Returns:
        List of warning messages (non-fatal issues).

    Raises:
        StructureValidationError: If fatal inconsistencies are found.
    """
    warnings: list[str] = []
    errors: list[str] = []

    # Collect all known scene IDs
    all_scene_ids: set[str] = set()
    for chapter in story.chapters:
        for scene in chapter.scenes:
            all_scene_ids.add(scene.id)
            # Also collect scenes from branch choices
            for bp in chapter.branch_points:
                for choice in bp.choices:
                    for branch_scene in choice.scenes:
                        all_scene_ids.add(branch_scene.id)

    # Collect all known character IDs
    all_character_ids = set(story.characters.keys())

    # 1. Validate character references
    char_warnings, char_errors = _validate_character_references(
        story, all_character_ids
    )
    warnings.extend(char_warnings)
    errors.extend(char_errors)

    # 2. Validate branch targets
    branch_warnings, branch_errors = _validate_branch_targets(
        story, all_scene_ids
    )
    warnings.extend(branch_warnings)
    errors.extend(branch_errors)

    # 3. Validate branch convergence
    conv_warnings, conv_errors = _validate_convergence(story, all_scene_ids)
    warnings.extend(conv_warnings)
    errors.extend(conv_errors)

    # 4. Check for orphaned scenes
    orphan_warnings = _check_orphaned_scenes(story, all_scene_ids)
    warnings.extend(orphan_warnings)

    # 5. Check for empty chapters
    for chapter in story.chapters:
        if not chapter.scenes:
            warnings.append(f"Chapter '{chapter.id}' has no scenes.")

    # 6. Check dialogue attribution
    attr_warnings, attr_errors = _validate_dialogue_attribution(
        story, all_character_ids
    )
    warnings.extend(attr_warnings)
    errors.extend(attr_errors)

    # Log results
    if errors:
        logger.error("Validation found %d fatal errors", len(errors))
        for err in errors:
            logger.error("  FATAL: %s", err)

    if warnings:
        logger.warning("Validation found %d warnings", len(warnings))
        for warn in warnings:
            logger.warning("  WARN: %s", warn)

    if errors:
        raise StructureValidationError(
            f"Story validation failed with {len(errors)} error(s):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    logger.info("Validation passed with %d warnings", len(warnings))
    return warnings


def _validate_character_references(
    story: Story,
    known_characters: set[str],
) -> tuple[list[str], list[str]]:
    """Check that all character references in scenes resolve to the registry."""
    warnings: list[str] = []
    errors: list[str] = []

    for chapter in story.chapters:
        for scene in chapter.scenes:
            for char_id in scene.characters_present:
                if char_id not in known_characters:
                    errors.append(
                        f"Scene '{scene.id}' references unknown character '{char_id}'"
                    )

            for beat in scene.beats:
                if beat.character and beat.character not in known_characters:
                    if beat.type == BeatType.DIALOGUE:
                        errors.append(
                            f"Dialogue beat '{beat.id}' in scene '{scene.id}' "
                            f"references unknown character '{beat.character}'"
                        )
                    else:
                        warnings.append(
                            f"Beat '{beat.id}' in scene '{scene.id}' "
                            f"references unknown character '{beat.character}'"
                        )

    return warnings, errors


def _validate_branch_targets(
    story: Story,
    known_scenes: set[str],
) -> tuple[list[str], list[str]]:
    """Check that all branch choice targets reference existing scenes."""
    warnings: list[str] = []
    errors: list[str] = []

    for chapter in story.chapters:
        for scene in chapter.scenes:
            for beat in scene.beats:
                if beat.type == BeatType.CHOICE:
                    for option in beat.options:
                        if option.target_scene and option.target_scene not in known_scenes:
                            warnings.append(
                                f"Choice option '{option.text}' in scene '{scene.id}' "
                                f"targets unknown scene '{option.target_scene}'"
                            )

        for bp in chapter.branch_points:
            if bp.convergence_scene_id and bp.convergence_scene_id not in known_scenes:
                warnings.append(
                    f"Branch point in chapter '{chapter.id}' has convergence "
                    f"target '{bp.convergence_scene_id}' that doesn't exist"
                )

    return warnings, errors


def _validate_convergence(
    story: Story,
    known_scenes: set[str],
) -> tuple[list[str], list[str]]:
    """Check that branch convergence points exist."""
    warnings: list[str] = []
    errors: list[str] = []

    for chapter in story.chapters:
        if chapter.branch_convergence:
            if chapter.branch_convergence not in known_scenes:
                warnings.append(
                    f"Chapter '{chapter.id}' has convergence scene "
                    f"'{chapter.branch_convergence}' that doesn't exist"
                )

        # Check that all branches within a chapter converge
        has_branches = any(
            scene.branch_info.is_branch for scene in chapter.scenes
        )
        if has_branches and not chapter.branch_convergence:
            warnings.append(
                f"Chapter '{chapter.id}' has branch scenes but no "
                f"convergence point defined"
            )

    return warnings, errors


def _check_orphaned_scenes(
    story: Story,
    all_scene_ids: set[str],
) -> list[str]:
    """Check for scenes that are not reachable from the main flow.

    A scene is considered reachable if it either:
    - Is the first scene in a chapter
    - Is referenced as a target by a choice option
    - Is listed as a convergence point
    """
    warnings: list[str] = []

    # Collect all referenced scene IDs
    referenced: set[str] = set()

    for chapter in story.chapters:
        # First scene in each chapter is always reachable
        if chapter.scenes:
            referenced.add(chapter.scenes[0].id)

        # Convergence scenes are reachable
        if chapter.branch_convergence:
            referenced.add(chapter.branch_convergence)

        for scene in chapter.scenes:
            # Scenes referenced by choices
            for beat in scene.beats:
                if beat.type == BeatType.CHOICE:
                    for option in beat.options:
                        if option.target_scene:
                            referenced.add(option.target_scene)

            # Scenes referenced by branch info
            if scene.branch_info.converges_at:
                referenced.add(scene.branch_info.converges_at)

        for bp in chapter.branch_points:
            if bp.convergence_scene_id:
                referenced.add(bp.convergence_scene_id)

    # For sequential scenes, the next scene after a non-branching scene is reachable
    for chapter in story.chapters:
        for i, scene in enumerate(chapter.scenes):
            if i > 0:
                prev = chapter.scenes[i - 1]
                # If previous scene has no branches, this scene is sequentially next
                has_choice = any(b.type == BeatType.CHOICE for b in prev.beats)
                if not has_choice:
                    referenced.add(scene.id)

    # Find orphans
    for scene_id in all_scene_ids:
        if scene_id not in referenced:
            warnings.append(f"Scene '{scene_id}' appears to be orphaned (not reachable)")

    return warnings


def _validate_dialogue_attribution(
    story: Story,
    known_characters: set[str],
) -> tuple[list[str], list[str]]:
    """Check that all dialogue beats have valid character attribution."""
    warnings: list[str] = []
    errors: list[str] = []

    for chapter in story.chapters:
        for scene in chapter.scenes:
            for beat in scene.beats:
                if beat.type == BeatType.DIALOGUE:
                    if not beat.character:
                        errors.append(
                            f"Dialogue beat '{beat.id}' in scene '{scene.id}' "
                            f"has no character attribution"
                        )
                    elif beat.character not in known_characters:
                        # Already caught in character reference check, skip duplicate
                        pass

    return warnings, errors
