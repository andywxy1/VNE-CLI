"""Build image generation prompts from story data.

Takes character descriptions and scene locations from the extracted story
and constructs consistent, detailed prompts for the image generation provider.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from vne_cli.schemas.story import CharacterRef, Scene, Story


# Default style components applied to all prompts for consistency
DEFAULT_STYLE_PREFIX = (
    "anime style, visual novel art, consistent lighting, high quality, detailed"
)

# Negative prompt applied to all generations
DEFAULT_NEGATIVE_PROMPT = (
    "blurry, low quality, distorted, deformed, watermark, text, signature, "
    "3d render, photograph, realistic"
)


@dataclass(frozen=True)
class AssetRequest:
    """A request to generate a single asset."""

    asset_id: str
    asset_type: str  # "background" or "sprite"
    prompt: str
    negative_prompt: str
    width: int
    height: int
    # Metadata for manifest
    character_id: str | None = None
    expression: str | None = None
    location_key: str | None = None


def _make_location_key(location: str, time_of_day: str) -> str:
    """Create a stable, unique key for a location + time_of_day combo.

    Uses a hash to create filesystem-safe identifiers while maintaining
    deterministic output for the same inputs.
    """
    raw = f"{location.strip().lower()}|{time_of_day.strip().lower()}"
    short_hash = hashlib.sha256(raw.encode()).hexdigest()[:12]
    return f"bg_{short_hash}"


def build_sprite_prompt(
    character: CharacterRef,
    expression: str,
    style_prefix: str,
) -> str:
    """Build a prompt for a character sprite.

    Args:
        character: Character reference with description info.
        expression: The expression/emotion for this sprite variant.
        style_prefix: Style prefix for consistency across all assets.

    Returns:
        A complete image generation prompt.
    """
    parts = []

    # Physical description
    if character.description:
        parts.append(character.description.rstrip("."))

    # Expression
    parts.append(f"{expression} expression")

    # Sprite-specific directives
    parts.append("front-facing portrait")
    parts.append("transparent background")
    parts.append("character sprite for visual novel")

    # Style
    parts.append(style_prefix)

    return ", ".join(parts)


def build_background_prompt(
    scene: Scene,
    style_prefix: str,
) -> str:
    """Build a prompt for a scene background.

    Args:
        scene: Scene with background_description, location, time_of_day.
        style_prefix: Style prefix for consistency across all assets.

    Returns:
        A complete image generation prompt.
    """
    parts = []

    # Use background_description if available, otherwise fall back to location
    if scene.background_description:
        parts.append(scene.background_description.rstrip("."))
    elif scene.location:
        parts.append(scene.location)

    # Time of day affects lighting
    if scene.time_of_day:
        tod = scene.time_of_day.lower()
        lighting_map = {
            "morning": "soft morning light, warm golden hour",
            "dawn": "soft morning light, warm golden hour",
            "afternoon": "bright afternoon sunlight, clear sky",
            "day": "bright daylight",
            "evening": "warm evening light, orange and purple sky",
            "dusk": "warm evening light, orange and purple sky",
            "sunset": "warm sunset light, orange and purple sky",
            "night": "moonlight, dark atmosphere, stars",
            "midnight": "deep night, moonlight, dark atmosphere",
        }
        lighting = lighting_map.get(tod, f"{tod} lighting")
        parts.append(lighting)

    # Background-specific directives
    parts.append("wide landscape view")
    parts.append("no characters or people")
    parts.append("atmospheric")
    parts.append("background for visual novel")

    # Style
    parts.append(style_prefix)

    return ", ".join(parts)


def build_asset_requests(
    story: Story,
    *,
    style_prefix: str = DEFAULT_STYLE_PREFIX,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    background_size: tuple[int, int] = (1920, 1080),
    sprite_size: tuple[int, int] = (800, 1200),
    characters_only: bool = False,
    backgrounds_only: bool = False,
) -> list[AssetRequest]:
    """Build the complete list of asset generation requests from a story.

    Deduplicates backgrounds by location+time_of_day combo.
    Generates one sprite per character (using the "neutral" expression
    as the default, plus any additional sprite_variants listed).

    Args:
        story: The extracted story data.
        style_prefix: Style prefix for prompt consistency.
        negative_prompt: Negative prompt for all generations.
        background_size: Target background dimensions (width, height).
        sprite_size: Target sprite dimensions (width, height).
        characters_only: Only generate character sprites.
        backgrounds_only: Only generate backgrounds.

    Returns:
        List of AssetRequest objects, deduplicated.
    """
    requests: list[AssetRequest] = []
    seen_backgrounds: set[str] = set()

    # --- Backgrounds ---
    if not characters_only:
        for chapter in story.chapters:
            for scene in chapter.scenes:
                # Need either background_description or location
                if not scene.background_description and not scene.location:
                    continue

                location_key = _make_location_key(
                    scene.background_description or scene.location,
                    scene.time_of_day,
                )

                if location_key in seen_backgrounds:
                    continue
                seen_backgrounds.add(location_key)

                prompt = build_background_prompt(scene, style_prefix)
                requests.append(
                    AssetRequest(
                        asset_id=location_key,
                        asset_type="background",
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        width=background_size[0],
                        height=background_size[1],
                        location_key=location_key,
                    )
                )

            # Also check branch point scenes
            for bp in chapter.branch_points:
                for choice in bp.choices:
                    for scene in choice.scenes:
                        if not scene.background_description and not scene.location:
                            continue
                        location_key = _make_location_key(
                            scene.background_description or scene.location,
                            scene.time_of_day,
                        )
                        if location_key in seen_backgrounds:
                            continue
                        seen_backgrounds.add(location_key)
                        prompt = build_background_prompt(scene, style_prefix)
                        requests.append(
                            AssetRequest(
                                asset_id=location_key,
                                asset_type="background",
                                prompt=prompt,
                                negative_prompt=negative_prompt,
                                width=background_size[0],
                                height=background_size[1],
                                location_key=location_key,
                            )
                        )

    # --- Character sprites ---
    if not backgrounds_only:
        for char_id, char_ref in story.characters.items():
            # Use sprite_variants if available, otherwise default to ["neutral"]
            expressions = char_ref.sprite_variants if char_ref.sprite_variants else ["neutral"]
            for expression in expressions:
                asset_id = f"sprite_{char_id}_{expression}"
                prompt = build_sprite_prompt(char_ref, expression, style_prefix)
                requests.append(
                    AssetRequest(
                        asset_id=asset_id,
                        asset_type="sprite",
                        prompt=prompt,
                        negative_prompt=negative_prompt,
                        width=sprite_size[0],
                        height=sprite_size[1],
                        character_id=char_id,
                        expression=expression,
                    )
                )

    return requests
