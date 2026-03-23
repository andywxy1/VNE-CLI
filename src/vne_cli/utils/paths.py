"""Path resolution helpers."""

from __future__ import annotations

from pathlib import Path


def ensure_dir(path: Path) -> Path:
    """Create a directory and all parents if they don't exist.

    Args:
        path: Directory path to create.

    Returns:
        The same path, guaranteed to exist.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_output_path(output: Path, default_name: str) -> Path:
    """Resolve an output path, using a default filename if output is a directory.

    Args:
        output: The user-provided output path.
        default_name: Fallback filename if output is a directory.

    Returns:
        Resolved file path.
    """
    if output.is_dir():
        return output / default_name
    return output


def project_assets_structure(base: Path) -> dict[str, Path]:
    """Return the standard VNE project asset directory structure.

    Args:
        base: Project root directory.

    Returns:
        Dict mapping asset category to directory path.
    """
    return {
        "textures": base / "assets" / "textures",
        "backgrounds": base / "assets" / "textures" / "backgrounds",
        "sprites": base / "assets" / "textures" / "sprites",
        "audio": base / "assets" / "audio",
        "fonts": base / "assets" / "fonts",
        "flows": base / "flows",
    }
