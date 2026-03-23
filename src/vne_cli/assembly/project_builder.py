"""Generate the project.vne JSON config and organize output directory structure.

The project.vne file is the VNE engine's project manifest. It tells the engine
where to find flows, assets, and project metadata.

Output structure:
  output_project/
  +-- project.vne
  +-- main.lua
  +-- application/
      +-- flow/
      |   +-- entry.flow
      |   +-- ch_001_sc_001.flow
      |   +-- ...
      +-- resources/
      |   +-- characters/
      |   +-- backgrounds/
      |   +-- audio/
      |   +-- fonts/
      +-- icon/
          +-- icon.png
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from vne_cli.schemas.story import Story

logger = logging.getLogger("vne_cli.assembly.project_builder")


def build_project_config(
    story: Story,
    entry_flow_path: str,
    *,
    title: str | None = None,
    developer: str = "VNE-CLI",
    width: int = 1920,
    height: int = 1080,
    fullscreen: bool = False,
) -> dict[str, Any]:
    """Build the project.vne config dictionary.

    Args:
        story: The story data for metadata extraction.
        entry_flow_path: Relative path to the entry flow file from the project root.
            Must use forward slashes (VNE convention).
        title: Override title. Falls back to story metadata title.
        developer: Developer name for the project manifest.
        width: Game window width in pixels.
        height: Game window height in pixels.
        fullscreen: Whether to launch in fullscreen mode.

    Returns:
        A dict representing the project.vne JSON content.
    """
    resolved_title = title or story.metadata.title or "Untitled Visual Novel"
    # Normalize entry_flow_path to use forward slashes.
    entry_flow_path = entry_flow_path.replace("\\", "/")

    return {
        "title": resolved_title,
        "release_version": "1.0.0",
        "project_version": "dev",
        "developer": developer,
        "width_game_window": width,
        "height_game_window": height,
        "default_fullscreen": fullscreen,
        "entry_flow": entry_flow_path,
        "icon_path": "application/icon/icon.png",
        "is_show_debug_fps": False,
        "release_mode": False,
        "editor_zoom_ratio": 1.0,
    }


def write_project_vne(
    config: dict[str, Any],
    output_dir: Path,
) -> Path:
    """Write the project.vne JSON file to the output directory.

    Args:
        config: The project config dict from build_project_config().
        output_dir: Root of the VNE project directory.

    Returns:
        Path to the written project.vne file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    project_vne_path = output_dir / "project.vne"
    project_vne_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Wrote project.vne to %s", project_vne_path)
    return project_vne_path


def create_directory_structure(output_dir: Path) -> None:
    """Create the standard VNE project directory skeleton.

    Creates all required directories even if they will be empty,
    so the VNE editor can find them.

    Args:
        output_dir: Root of the VNE project directory.
    """
    dirs = [
        output_dir / "application" / "flow",
        output_dir / "application" / "resources" / "characters",
        output_dir / "application" / "resources" / "backgrounds",
        output_dir / "application" / "resources" / "audio",
        output_dir / "application" / "resources" / "fonts",
        output_dir / "application" / "icon",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    logger.info("Created project directory structure at %s", output_dir)


def write_main_lua(output_dir: Path) -> Path:
    """Write a minimal main.lua entry point for the VNE engine.

    The VNE engine requires a main.lua at the project root. This generates
    a minimal bootstrap that loads the entry flow from project.vne.

    Args:
        output_dir: Root of the VNE project directory.

    Returns:
        Path to the written main.lua file.
    """
    main_lua_content = """\
-- VNE-CLI generated main.lua
-- This file is the entry point for the VoidNovelEngine runtime.
-- It reads project.vne and launches the entry flow.

-- VNE engine handles project loading automatically when project.vne exists.
-- This file is a placeholder for custom initialization logic.
"""
    main_lua_path = output_dir / "main.lua"
    main_lua_path.write_text(main_lua_content, encoding="utf-8")
    logger.info("Wrote main.lua to %s", main_lua_path)
    return main_lua_path


def create_default_icon(output_dir: Path) -> Path:
    """Create a default icon.png placeholder in the icon directory.

    Generates a minimal 1x1 transparent PNG to satisfy the icon_path
    reference in project.vne. Users should replace this with their own icon.

    Args:
        output_dir: Root of the VNE project directory.

    Returns:
        Path to the created icon file.
    """
    icon_dir = output_dir / "application" / "icon"
    icon_dir.mkdir(parents=True, exist_ok=True)
    icon_path = icon_dir / "icon.png"

    if not icon_path.exists():
        # Minimal valid 1x1 transparent PNG (67 bytes).
        # This avoids requiring Pillow as a runtime dependency for assembly.
        import struct
        import zlib

        def _make_png_chunk(chunk_type: bytes, data: bytes) -> bytes:
            chunk = chunk_type + data
            crc = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
            return struct.pack(">I", len(data)) + chunk + crc

        signature = b"\x89PNG\r\n\x1a\n"
        ihdr_data = struct.pack(">IIBBBBB", 64, 64, 8, 6, 0, 0, 0)
        ihdr = _make_png_chunk(b"IHDR", ihdr_data)

        # 64x64 transparent pixels: each row is filter_byte(0) + 4 bytes * 64 pixels
        raw_row = b"\x00" + (b"\x00\x00\x00\x00" * 64)
        raw_data = raw_row * 64
        compressed = zlib.compress(raw_data)
        idat = _make_png_chunk(b"IDAT", compressed)
        iend = _make_png_chunk(b"IEND", b"")

        icon_path.write_bytes(signature + ihdr + idat + iend)
        logger.info("Created default icon at %s", icon_path)

    return icon_path
