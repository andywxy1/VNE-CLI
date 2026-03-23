"""Download and organize generated images into the asset directory structure.

Handles:
- Writing raw image bytes to properly named files
- Organizing into backgrounds/ and characters/ subdirectories
- Image format conversion (JPEG -> PNG for transparency support)
- Image resizing via Pillow when provider output doesn't match target size
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from vne_cli.utils.logging import get_logger

logger = get_logger(__name__)


def save_image(
    image_bytes: bytes,
    output_path: Path,
    *,
    target_width: int | None = None,
    target_height: int | None = None,
    output_format: str = "PNG",
) -> Path:
    """Save image bytes to disk, optionally resizing and converting format.

    Args:
        image_bytes: Raw image bytes from the provider.
        output_path: Full path to write the file.
        target_width: If set, resize to this width.
        target_height: If set, resize to this height.
        output_format: Output format (PNG, JPEG, etc.).

    Returns:
        The path the image was written to.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.open(io.BytesIO(image_bytes))

    # Convert to RGBA for PNG transparency support
    if output_format.upper() == "PNG" and img.mode != "RGBA":
        img = img.convert("RGBA")
    elif output_format.upper() in ("JPEG", "JPG") and img.mode == "RGBA":
        # JPEG doesn't support transparency
        img = img.convert("RGB")

    # Resize if target dimensions specified and different from current
    if target_width and target_height:
        if img.size != (target_width, target_height):
            img = img.resize(
                (target_width, target_height),
                Image.Resampling.LANCZOS,
            )
            logger.debug(
                "Resized image from %s to %dx%d",
                img.size,
                target_width,
                target_height,
            )

    img.save(str(output_path), format=output_format.upper())
    logger.debug("Saved image: %s", output_path)
    return output_path


def save_background(
    image_bytes: bytes,
    asset_id: str,
    output_dir: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    output_format: str = "png",
) -> Path:
    """Save a background image to the assets directory.

    Args:
        image_bytes: Raw image bytes from the provider.
        asset_id: Background asset identifier for the filename.
        output_dir: Root assets directory.
        width: Target width.
        height: Target height.
        output_format: Image format extension.

    Returns:
        Path to the saved file, relative to output_dir.
    """
    filename = f"{asset_id}.{output_format.lower()}"
    output_path = output_dir / "backgrounds" / filename
    save_image(
        image_bytes,
        output_path,
        target_width=width,
        target_height=height,
        output_format=output_format,
    )
    return Path("backgrounds") / filename


def save_sprite(
    image_bytes: bytes,
    character_id: str,
    expression: str,
    output_dir: Path,
    *,
    width: int = 800,
    height: int = 1200,
    output_format: str = "png",
) -> Path:
    """Save a character sprite to the assets directory.

    Args:
        image_bytes: Raw image bytes from the provider.
        character_id: Character identifier.
        expression: Expression variant name.
        output_dir: Root assets directory.
        width: Target width.
        height: Target height.
        output_format: Image format extension.

    Returns:
        Path to the saved file, relative to output_dir.
    """
    filename = f"{character_id}_{expression}.{output_format.lower()}"
    output_path = output_dir / "characters" / filename
    save_image(
        image_bytes,
        output_path,
        target_width=width,
        target_height=height,
        output_format=output_format,
    )
    return Path("characters") / filename
