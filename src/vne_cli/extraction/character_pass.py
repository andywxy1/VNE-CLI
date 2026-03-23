"""Character registry extraction pre-pass.

Runs before structure extraction to build a complete character registry.
This gives the structure pass consistent character IDs and descriptions.
"""

from __future__ import annotations

import json

from vne_cli.extraction.chunker import TextChunk
from vne_cli.providers.base import LLMProvider
from vne_cli.providers.errors import ExtractionError, ProviderResponseError
from vne_cli.schemas.characters import Character, CharacterRegistry
from vne_cli.utils.logging import get_logger
from vne_cli.utils.retry import retry_with_backoff

logger = get_logger(__name__)

CHARACTER_EXTRACTION_SYSTEM = """\
You are a literary analysis assistant. Your job is to extract ALL characters
mentioned in the provided text passage. For each character, provide:

- name: The character's primary name
- aliases: Any other names, titles, or references used for this character
- is_protagonist: true if this appears to be a main/POV character
- physical_description: Physical appearance details mentioned in the text
- clothing_default: Default clothing/outfit described
- personality_traits: List of personality characteristics shown or described
- role: Their role in the story (protagonist, antagonist, mentor, love_interest,
  supporting, minor)
- voice_characteristics: How they speak (formal, casual, accent, etc.)

Return a JSON object with this exact structure:
{
  "characters": [
    {
      "name": "...",
      "aliases": ["..."],
      "is_protagonist": false,
      "physical_description": "...",
      "clothing_default": "...",
      "personality_traits": ["..."],
      "role": "...",
      "voice_characteristics": "..."
    }
  ]
}

Only include characters that are clearly identifiable as people (not objects,
places, or abstract concepts). Include characters who are mentioned by name
or by a clear identifying reference (like "the captain" or "her mother").
"""

MERGE_SYSTEM = """\
You are a literary analysis assistant performing entity resolution on characters.
You will receive a list of character entries extracted from different parts of a novel.
Many entries may refer to the same character under different names or aliases.

Your job is to:
1. Merge entries that refer to the same character into a single entry
2. Combine their aliases, descriptions, and traits
3. Pick the most complete/canonical name as the primary name
4. Resolve relationship references between characters
5. Assign a unique ID in the format "char_001", "char_002", etc.
6. Determine the protagonist (the primary POV character)

Return a JSON object:
{
  "protagonist_id": "char_001",
  "characters": [
    {
      "id": "char_001",
      "name": "...",
      "aliases": ["..."],
      "is_protagonist": true,
      "physical_description": "...",
      "clothing_default": "...",
      "personality_traits": ["..."],
      "role": "protagonist",
      "relationships": {"char_002": "childhood friend"},
      "sprite_expressions": ["neutral", "happy", "sad", "angry", "surprised"]
    }
  ]
}

Merge aggressively: "the captain", "Captain Elena", and "Elena" are likely the
same character. Use context clues from descriptions and relationships.
"""


async def extract_characters(
    chunks: list[TextChunk],
    llm: LLMProvider,
    *,
    source_file: str = "",
) -> CharacterRegistry:
    """Extract character registry from text chunks via LLM.

    Performs a dedicated pre-pass that:
    1. Sends each chunk to the LLM for character identification
    2. Collects all character mentions across chunks
    3. Runs a merge/deduplication pass via LLM
    4. Returns a validated CharacterRegistry

    Args:
        chunks: Text chunks from the chunker.
        llm: Configured LLM provider.
        source_file: Path to the source file (for metadata).

    Returns:
        A validated CharacterRegistry.
    """
    if not chunks:
        raise ExtractionError("No text chunks provided for character extraction.")

    logger.info("Starting character extraction across %d chunks", len(chunks))

    # Phase 1: Extract characters from each chunk
    all_raw_characters: list[dict[str, object]] = []

    for chunk in chunks:
        raw_chars = await _extract_from_chunk(chunk, llm)
        all_raw_characters.extend(raw_chars)
        logger.debug(
            "Chunk %d yielded %d character entries",
            chunk.index,
            len(raw_chars),
        )

    if not all_raw_characters:
        logger.warning("No characters found in any chunk")
        return CharacterRegistry(source_file=source_file)

    logger.info(
        "Collected %d raw character entries, starting merge pass",
        len(all_raw_characters),
    )

    # Phase 2: Merge and deduplicate via LLM
    registry = await _merge_characters(all_raw_characters, llm, source_file=source_file)

    logger.info(
        "Character extraction complete: %d characters, protagonist=%s",
        len(registry.characters),
        registry.protagonist,
    )

    return registry


async def _extract_from_chunk(
    chunk: TextChunk,
    llm: LLMProvider,
) -> list[dict[str, object]]:
    """Extract character entries from a single text chunk."""

    prompt = (
        f"Analyze this passage and extract all characters:\n\n"
        f"---\n{chunk.text}\n---"
    )

    async def _call() -> str:
        return await llm.complete(
            prompt,
            system=CHARACTER_EXTRACTION_SYSTEM,
            temperature=0.3,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )

    try:
        response = await retry_with_backoff(
            _call,
            max_retries=2,
            retryable_exceptions=(ProviderResponseError, Exception),
        )
    except Exception as e:
        logger.warning("Character extraction failed for chunk %d: %s", chunk.index, e)
        return []

    try:
        data = json.loads(response)
        characters = data.get("characters", [])
        if not isinstance(characters, list):
            return []
        return characters
    except (json.JSONDecodeError, AttributeError) as e:
        logger.warning("Failed to parse LLM response for chunk %d: %s", chunk.index, e)
        return []


async def _merge_characters(
    raw_characters: list[dict[str, object]],
    llm: LLMProvider,
    *,
    source_file: str = "",
) -> CharacterRegistry:
    """Merge and deduplicate character entries via LLM."""

    # Limit the payload size for the merge prompt
    char_summary = json.dumps(raw_characters, indent=2, default=str)

    # If too large, truncate intelligently
    if len(char_summary) > 50000:
        # Deduplicate by name first to reduce size
        seen_names: set[str] = set()
        deduped: list[dict[str, object]] = []
        for char in raw_characters:
            name = str(char.get("name", "")).lower().strip()
            if name and name not in seen_names:
                seen_names.add(name)
                deduped.append(char)
        char_summary = json.dumps(deduped, indent=2, default=str)

    prompt = (
        f"Merge and deduplicate these character entries extracted from a novel.\n"
        f"The entries come from different parts of the text and may refer to "
        f"the same characters under different names:\n\n"
        f"```json\n{char_summary}\n```"
    )

    async def _call() -> str:
        return await llm.complete(
            prompt,
            system=MERGE_SYSTEM,
            temperature=0.2,
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
        logger.error("Character merge failed: %s", e)
        raise ExtractionError(f"Character merge LLM call failed: {e}") from e

    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        raise ExtractionError(f"Failed to parse character merge response: {e}") from e

    # Build the registry from the merged data
    protagonist_id = data.get("protagonist_id", "")
    characters_data = data.get("characters", [])

    characters: dict[str, Character] = {}
    for char_data in characters_data:
        char_id = char_data.get("id", "")
        if not char_id:
            continue
        character = Character(
            id=char_id,
            name=char_data.get("name", "Unknown"),
            aliases=char_data.get("aliases", []),
            is_protagonist=char_data.get("is_protagonist", False),
            physical_description=char_data.get("physical_description", ""),
            clothing_default=char_data.get("clothing_default", ""),
            personality_traits=char_data.get("personality_traits", []),
            role=char_data.get("role", ""),
            relationships=char_data.get("relationships", {}),
            sprite_expressions=char_data.get(
                "sprite_expressions",
                ["neutral", "happy", "sad", "angry", "surprised"],
            ),
        )
        characters[char_id] = character

    return CharacterRegistry(
        source_file=source_file,
        protagonist=protagonist_id,
        characters=characters,
    )
