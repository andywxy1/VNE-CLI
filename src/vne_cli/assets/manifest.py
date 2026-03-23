"""Asset manifest read/write.

The manifest tracks the generation state of every asset for resume capability.
"""

from __future__ import annotations

import json
from pathlib import Path

from vne_cli.schemas.asset_manifest import AssetManifestSchema


def load_manifest(path: Path) -> AssetManifestSchema:
    """Load an asset manifest from disk.

    Args:
        path: Path to the asset-manifest.json file.

    Returns:
        Validated asset manifest.

    Raises:
        ManifestError: If the file is invalid or corrupted.
    """
    from vne_cli.providers.errors import ManifestError

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AssetManifestSchema.model_validate(data)
    except (json.JSONDecodeError, ValueError) as e:
        msg = f"Invalid asset manifest at {path}: {e}"
        raise ManifestError(msg) from e


def save_manifest(manifest: AssetManifestSchema, path: Path) -> None:
    """Save an asset manifest to disk.

    Args:
        manifest: The manifest to save.
        path: Output file path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )


# Re-export for convenience
AssetManifest = AssetManifestSchema
