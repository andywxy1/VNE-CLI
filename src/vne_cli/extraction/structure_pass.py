"""Structure extraction: chapters, scenes, dialogue, and beats.

Extracts the narrative structure from text chunks using an LLM provider,
guided by the character registry from the character pre-pass. Also performs
cinematic annotation as part of the extraction.
"""

from __future__ import annotations

import json

from vne_cli.extraction.chunker import TextChunk
from vne_cli.providers.base import LLMProvider
from vne_cli.providers.errors import ExtractionError, ProviderResponseError
from vne_cli.schemas.characters import CharacterRegistry
from vne_cli.schemas.story import (
    Beat,
    BeatType,
    BranchInfo,
    Chapter,
    CharacterRef,
    CinematicAnnotation,
    CinematicAnnotations,
    ChoiceOption,
    GameVariable,
    Scene,
    Story,
    StoryMetadata,
)
from vne_cli.utils.logging import get_logger
from vne_cli.utils.retry import retry_with_backoff

logger = get_logger(__name__)


def _build_character_context(characters: CharacterRegistry) -> str:
    """Build a concise character summary for inclusion in LLM prompts."""
    if not characters.characters:
        return "No characters identified yet."

    lines: list[str] = []
    for char_id, char in characters.characters.items():
        aliases_str = ", ".join(char.aliases) if char.aliases else "none"
        role_str = f" ({char.role})" if char.role else ""
        lines.append(
            f"- {char_id}: {char.name} [aliases: {aliases_str}]{role_str}"
        )
    return "\n".join(lines)


STRUCTURE_SYSTEM = """\
You are a narrative structure analyst for a visual novel adaptation system.
You receive a passage from a novel along with a character registry. Your job
is to extract the narrative structure as JSON.

For the given passage, extract:

1. **Chapters**: If the text contains chapter boundaries, respect them.
   Otherwise, treat the passage as belonging to chapter "{chapter_hint}".

2. **Scenes**: Split at location changes or significant time jumps.
   Each scene needs:
   - id: format "ch_XXX_sc_YYY" (e.g. "ch_001_sc_001")
   - title: brief scene title
   - location: where the scene takes place
   - time_of_day: "morning", "afternoon", "evening", "night", or "unspecified"
   - background_description: visual description for background art generation
   - characters_present: list of character IDs from the registry

3. **Beats**: Within each scene, extract sequential events:
   - "dialogue": character speech (include character ID and expression)
   - "narration": descriptive text or internal monologue
   - "choice": decision points (include options with target scenes)
   - "transition": scene transitions
   - "direction": stage directions

4. **Cinematic cues**: For each scene, note cinematic annotations:
   - Sound effects: "a gunshot rang out" -> [SFX: gunshot]
   - Transitions: "the room went dark" -> [TRANSITION: fade_to_black]
   - Music: tense moments -> [MUSIC: tense_orchestral]
   - Camera: "she looked up" -> [CAMERA: pan_up]
   - Lighting: "shadows crept in" -> [LIGHTING: dim]

5. **Variables**: Identify story flags worth tracking (relationship changes,
   key decisions, item acquisitions).

CHARACTER REGISTRY:
{character_context}

IMPORTANT RULES:
- Use character IDs (char_001, etc.) from the registry, NOT character names
- Every dialogue beat MUST have a character ID
- Expression should be one of: neutral, happy, sad, angry, surprised, thoughtful,
  scared, determined, embarrassed, playful
- Generate unique beat IDs like "beat_001", "beat_002", etc.
- Scene IDs must follow the ch_XXX_sc_YYY format

Return a JSON object:
{{
  "title": "chapter or passage title",
  "synopsis": "brief synopsis",
  "scenes": [
    {{
      "id": "ch_001_sc_001",
      "title": "Scene Title",
      "location": "...",
      "time_of_day": "...",
      "background_description": "...",
      "characters_present": ["char_001"],
      "beats": [
        {{
          "id": "beat_001",
          "type": "dialogue",
          "character": "char_001",
          "expression": "neutral",
          "text": "..."
        }},
        {{
          "id": "beat_002",
          "type": "narration",
          "text": "..."
        }}
      ],
      "cinematic_annotations": [
        {{
          "cue_type": "sfx",
          "reference": "[SFX: door_creak]",
          "source_text": "the door creaked open",
          "beat_id": "beat_001"
        }}
      ]
    }}
  ],
  "variables": [
    {{
      "name": "met_marcus",
      "var_type": "bool",
      "default_value": "false",
      "description": "Whether the player has met Marcus"
    }}
  ]
}}
"""


async def extract_structure(
    chunks: list[TextChunk],
    characters: CharacterRegistry,
    llm: LLMProvider,
    *,
    source_file: str = "",
    cinematic_enabled: bool = True,
) -> Story:
    """Extract narrative structure from text via LLM.

    Uses the character registry for consistent character references.
    Processes chunks sequentially, maintaining cross-chunk state for
    continuity.

    Args:
        chunks: Text chunks from the chunker.
        characters: Pre-extracted character registry.
        llm: Configured LLM provider.
        source_file: Path to the source file (for metadata).
        cinematic_enabled: Whether to include cinematic annotations.

    Returns:
        A validated Story model (the story.json schema).
    """
    if not chunks:
        raise ExtractionError("No text chunks provided for structure extraction.")

    logger.info("Starting structure extraction across %d chunks", len(chunks))

    character_context = _build_character_context(characters)
    all_chapters: list[Chapter] = []
    all_variables: list[GameVariable] = []
    chapter_counter = 0
    story_title = ""

    for chunk in chunks:
        chunk_result = await _extract_chunk_structure(
            chunk,
            character_context=character_context,
            llm=llm,
            chapter_offset=chapter_counter,
            cinematic_enabled=cinematic_enabled,
        )

        if chunk_result is None:
            logger.warning("Structure extraction returned nothing for chunk %d", chunk.index)
            continue

        chapters, variables, title = chunk_result
        all_chapters.extend(chapters)
        all_variables.extend(variables)
        chapter_counter += len(chapters)

        if not story_title and title:
            story_title = title

    # Build character refs from the registry
    char_refs: dict[str, CharacterRef] = {}
    for char_id, char in characters.characters.items():
        char_refs[char_id] = CharacterRef(
            id=char_id,
            name=char.name,
            aliases=char.aliases,
            is_protagonist=char.is_protagonist,
            description=char.physical_description,
            personality=", ".join(char.personality_traits),
            sprite_variants=char.sprite_expressions,
            first_appearance=_find_first_appearance(char_id, all_chapters),
        )

    # Deduplicate variables by name
    seen_vars: set[str] = set()
    unique_vars: list[GameVariable] = []
    for var in all_variables:
        if var.name not in seen_vars:
            seen_vars.add(var.name)
            unique_vars.append(var)

    story = Story(
        metadata=StoryMetadata(
            title=story_title or "Untitled",
            source_file=source_file,
            language="en",
        ),
        characters=char_refs,
        chapters=all_chapters,
        global_variables=unique_vars,
    )

    logger.info(
        "Structure extraction complete: %d chapters, %d total scenes",
        len(all_chapters),
        sum(len(ch.scenes) for ch in all_chapters),
    )

    return story


async def _extract_chunk_structure(
    chunk: TextChunk,
    *,
    character_context: str,
    llm: LLMProvider,
    chapter_offset: int,
    cinematic_enabled: bool,
) -> tuple[list[Chapter], list[GameVariable], str] | None:
    """Extract structure from a single chunk via LLM."""

    chapter_hint = chunk.chapter_hint or f"Chapter {chapter_offset + 1}"

    system_prompt = STRUCTURE_SYSTEM.format(
        chapter_hint=chapter_hint,
        character_context=character_context,
    )

    prompt = (
        f"Extract the narrative structure from this passage:\n\n"
        f"---\n{chunk.text}\n---"
    )

    async def _call() -> str:
        return await llm.complete(
            prompt,
            system=system_prompt,
            temperature=0.3,
            max_tokens=8192,
            response_format={"type": "json_object"},
        )

    try:
        response = await retry_with_backoff(
            _call,
            max_retries=2,
            retryable_exceptions=(ProviderResponseError, Exception),
        )
    except Exception as e:
        logger.error("Structure extraction failed for chunk %d: %s", chunk.index, e)
        return None

    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse structure response for chunk %d: %s", chunk.index, e)
        return None

    title = data.get("title", "")
    chapter_id = f"ch_{chapter_offset + 1:03d}"

    scenes: list[Scene] = []
    raw_scenes = data.get("scenes", [])

    for sc_data in raw_scenes:
        beats = _parse_beats(sc_data.get("beats", []))
        cinematic = None
        if cinematic_enabled:
            cinematic = _parse_cinematic(sc_data.get("cinematic_annotations", []))

        scene = Scene(
            id=sc_data.get("id", f"{chapter_id}_sc_{len(scenes) + 1:03d}"),
            title=sc_data.get("title", ""),
            location=sc_data.get("location", ""),
            time_of_day=sc_data.get("time_of_day", "unspecified"),
            background_description=sc_data.get("background_description", ""),
            characters_present=sc_data.get("characters_present", []),
            beats=beats,
            branch_info=BranchInfo(),
            cinematic=cinematic,
        )
        scenes.append(scene)

    # Parse variables
    variables: list[GameVariable] = []
    for var_data in data.get("variables", []):
        variables.append(GameVariable(
            name=var_data.get("name", ""),
            var_type=var_data.get("var_type", "bool"),
            default_value=var_data.get("default_value", "false"),
            description=var_data.get("description", ""),
        ))

    chapter = Chapter(
        id=chapter_id,
        index=chapter_offset,
        title=data.get("title", chapter_hint),
        synopsis=data.get("synopsis", ""),
        scenes=scenes,
    )

    return [chapter], variables, title


def _parse_beats(raw_beats: list[dict[str, object]]) -> list[Beat]:
    """Parse raw beat data into Beat models."""
    beats: list[Beat] = []

    for bd in raw_beats:
        beat_type_str = str(bd.get("type", "narration")).lower()
        try:
            beat_type = BeatType(beat_type_str)
        except ValueError:
            beat_type = BeatType.NARRATION

        options: list[ChoiceOption] = []
        if beat_type == BeatType.CHOICE:
            for opt in bd.get("options", []):
                if isinstance(opt, dict):
                    options.append(ChoiceOption(
                        text=str(opt.get("text", "")),
                        target_scene=str(opt.get("target_scene", "")),
                        consequence_tag=str(opt.get("consequence_tag", "")),
                    ))

        beat = Beat(
            id=str(bd.get("id", "")),
            type=beat_type,
            character=bd.get("character") if bd.get("character") else None,
            expression=bd.get("expression") if bd.get("expression") else None,
            text=str(bd.get("text", "")),
            options=options,
            style=bd.get("style") if bd.get("style") else None,
            duration_ms=bd.get("duration_ms") if bd.get("duration_ms") else None,
        )
        beats.append(beat)

    return beats


def _parse_cinematic(raw_annotations: list[dict[str, object]]) -> CinematicAnnotations | None:
    """Parse raw cinematic annotation data."""
    if not raw_annotations:
        return None

    annotations: list[CinematicAnnotation] = []
    for ann in raw_annotations:
        annotations.append(CinematicAnnotation(
            cue_type=str(ann.get("cue_type", "")),
            reference=str(ann.get("reference", "")),
            source_text=str(ann.get("source_text", "")),
            beat_id=str(ann.get("beat_id", "")),
        ))

    return CinematicAnnotations(annotations=annotations, enabled=True)


def _find_first_appearance(char_id: str, chapters: list[Chapter]) -> str:
    """Find the first scene where a character appears."""
    for chapter in chapters:
        for scene in chapter.scenes:
            if char_id in scene.characters_present:
                return scene.id
    return ""
