"""Organize generated assets into the VNE project directory structure.

Copies assets from the generation output directory into the standard VNE
project layout, mapping asset types to their expected subdirectories.

Target structure:
  application/
  +-- resources/
      +-- characters/    <- character sprite PNGs
      +-- backgrounds/   <- background PNGs
      +-- audio/         <- audio files (placeholder)
      +-- fonts/         <- font files (placeholder or default)
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger("vne_cli.assembly.asset_organizer")


def organize_assets(
    assets_dir: Path,
    output_dir: Path,
    flow_dir: Path | None = None,
) -> AssetReport:
    """Copy and organize assets from the source directory into the VNE project.

    Scans the assets directory for known asset patterns and copies them
    into the correct subdirectory under ``output_dir/application/resources/``.

    Args:
        assets_dir: Source directory containing generated assets.
        output_dir: Root of the VNE project directory.
        flow_dir: Directory containing .flow files for reference validation.
            If provided, checks that asset references in flows resolve to files.

    Returns:
        An AssetReport with details on copied files and any warnings.
    """
    resources_dir = output_dir / "application" / "resources"
    report = AssetReport()

    if not assets_dir.exists():
        report.add_warning(f"Assets directory does not exist: {assets_dir}")
        return report

    # Map source subdirectory patterns to destination directories.
    mapping = _build_asset_mapping(assets_dir, resources_dir)

    for src_subdir, dest_subdir, asset_type in mapping:
        if src_subdir.exists() and src_subdir.is_dir():
            dest_subdir.mkdir(parents=True, exist_ok=True)
            for src_file in src_subdir.iterdir():
                if src_file.is_file() and not src_file.name.startswith("."):
                    dest_file = dest_subdir / src_file.name
                    shutil.copy2(src_file, dest_file)
                    report.add_copied(src_file, dest_file, asset_type)
                    logger.debug("Copied %s -> %s", src_file, dest_file)

    # Also copy any loose image files at the root of assets_dir.
    _copy_loose_assets(assets_dir, resources_dir, report)

    # Validate references if flow_dir is provided.
    if flow_dir is not None and flow_dir.exists():
        _validate_asset_references(flow_dir, output_dir, report)

    logger.info(
        "Organized %d assets (%d characters, %d backgrounds, %d other)",
        report.total_copied,
        report.characters_copied,
        report.backgrounds_copied,
        report.other_copied,
    )
    if report.warnings:
        for w in report.warnings:
            logger.warning(w)

    return report


class AssetReport:
    """Report on asset organization results."""

    def __init__(self) -> None:
        self.copied: list[dict[str, str]] = []
        self.warnings: list[str] = []
        self.missing_references: list[str] = []
        self.orphaned_assets: list[str] = []

    def add_copied(self, src: Path, dest: Path, asset_type: str) -> None:
        self.copied.append({
            "source": str(src),
            "destination": str(dest),
            "type": asset_type,
        })

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def total_copied(self) -> int:
        return len(self.copied)

    @property
    def characters_copied(self) -> int:
        return sum(1 for c in self.copied if c["type"] == "character")

    @property
    def backgrounds_copied(self) -> int:
        return sum(1 for c in self.copied if c["type"] == "background")

    @property
    def other_copied(self) -> int:
        return sum(1 for c in self.copied if c["type"] not in ("character", "background"))

    @property
    def has_errors(self) -> bool:
        return len(self.missing_references) > 0


def _build_asset_mapping(
    assets_dir: Path,
    resources_dir: Path,
) -> list[tuple[Path, Path, str]]:
    """Build the source-to-destination mapping for asset directories.

    Returns:
        List of (source_dir, dest_dir, asset_type) tuples.
    """
    return [
        (assets_dir / "characters", resources_dir / "characters", "character"),
        (assets_dir / "sprites", resources_dir / "characters", "character"),
        (assets_dir / "backgrounds", resources_dir / "backgrounds", "background"),
        (assets_dir / "audio", resources_dir / "audio", "audio"),
        (assets_dir / "music", resources_dir / "audio", "audio"),
        (assets_dir / "fonts", resources_dir / "fonts", "font"),
    ]


def _copy_loose_assets(
    assets_dir: Path,
    resources_dir: Path,
    report: AssetReport,
) -> None:
    """Copy image files at the root of assets_dir into appropriate subdirectories.

    Uses filename heuristics: files starting with 'bg_' or containing 'background'
    go to backgrounds/; files starting with 'char_' or 'sprite_' go to characters/.
    """
    image_extensions = {".png", ".jpg", ".jpeg", ".webp"}
    for f in assets_dir.iterdir():
        if not f.is_file() or f.suffix.lower() not in image_extensions:
            continue
        if f.name.startswith("."):
            continue

        name_lower = f.name.lower()
        if name_lower.startswith("bg_") or "background" in name_lower:
            dest_dir = resources_dir / "backgrounds"
            asset_type = "background"
        elif (
            name_lower.startswith("char_")
            or name_lower.startswith("sprite_")
            or "character" in name_lower
        ):
            dest_dir = resources_dir / "characters"
            asset_type = "character"
        else:
            # Default: put in backgrounds (most common loose asset type).
            dest_dir = resources_dir / "backgrounds"
            asset_type = "background"

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / f.name
        shutil.copy2(f, dest_file)
        report.add_copied(f, dest_file, asset_type)
        logger.debug("Copied loose asset %s -> %s", f, dest_file)


def _validate_asset_references(
    flow_dir: Path,
    project_dir: Path,
    report: AssetReport,
) -> None:
    """Check that texture/audio/video references in .flow files resolve to actual files.

    Scans all .flow files for pin values that look like asset paths and checks
    whether the referenced file exists in the project directory.
    """
    referenced_assets: set[str] = set()
    actual_assets: set[str] = set()

    # Collect all asset references from .flow files.
    for flow_file in flow_dir.glob("*.flow"):
        try:
            data = json.loads(flow_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            report.add_warning(f"Could not read flow file: {flow_file}")
            continue

        for node in data.get("node_pool", []):
            for pin_list_key in ("input_pin_list", "output_pin_list"):
                for pin in node.get(pin_list_key, []):
                    pin_type = pin.get("type_id", "")
                    val = pin.get("val", "")
                    if pin_type in ("texture", "audio", "video", "font") and val:
                        referenced_assets.add(val)

    # Collect actual asset files in the project.
    resources_dir = project_dir / "application" / "resources"
    if resources_dir.exists():
        for f in resources_dir.rglob("*"):
            if f.is_file():
                # Build relative path from project root using forward slashes.
                rel = f.relative_to(project_dir)
                actual_assets.add(str(rel).replace("\\", "/"))
                # Also add just the filename stem for flexible matching.
                actual_assets.add(f.stem)
                actual_assets.add(f.name)

    # Check for missing references.
    for ref in sorted(referenced_assets):
        # Asset references in .flow files may be bare IDs (no extension/path).
        # Check if any actual asset matches by stem.
        if ref and ref not in actual_assets:
            report.missing_references.append(ref)
            report.add_warning(f"Asset reference not found: {ref}")

    # Check for orphaned assets (files not referenced by any flow).
    if resources_dir.exists():
        for f in resources_dir.rglob("*"):
            if f.is_file():
                stem = f.stem
                name = f.name
                rel = str(f.relative_to(project_dir)).replace("\\", "/")
                if (
                    stem not in referenced_assets
                    and name not in referenced_assets
                    and rel not in referenced_assets
                ):
                    report.orphaned_assets.append(str(f))
