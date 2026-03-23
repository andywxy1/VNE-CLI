"""Asset generation pipeline: image creation, manifest management, file organization."""

from vne_cli.assets.manifest import AssetManifest, load_manifest, save_manifest
from vne_cli.assets.pipeline import build_dry_run_plan, run_asset_pipeline
from vne_cli.assets.prompt_builder import AssetRequest, build_asset_requests

__all__ = [
    "AssetManifest",
    "AssetRequest",
    "build_asset_requests",
    "build_dry_run_plan",
    "load_manifest",
    "run_asset_pipeline",
    "save_manifest",
]
