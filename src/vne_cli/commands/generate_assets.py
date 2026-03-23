"""Generate-assets command: produce images via pluggable API providers.

Orchestrates the asset generation pipeline:
1. Load story.json and validate
2. Load or create asset manifest
3. Build generation plan (skip completed assets)
4. Generate images via configured provider
5. Download and organize into asset directory
6. Update manifest with results
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from vne_cli.assets.manifest import load_manifest, save_manifest
from vne_cli.assets.pipeline import build_dry_run_plan, run_asset_pipeline
from vne_cli.config.loader import load_config
from vne_cli.providers.errors import ManifestError, ProviderNotFoundError
from vne_cli.providers.registry import load_image_provider
from vne_cli.schemas.asset_manifest import AssetManifestSchema
from vne_cli.schemas.story import Story
from vne_cli.utils.logging import get_logger, setup_logging

logger = get_logger(__name__)
console = Console()


def _load_story(story_json: Path) -> Story:
    """Load and validate story.json.

    Raises:
        typer.Exit: If the file cannot be loaded or validated.
    """
    try:
        data = json.loads(story_json.read_text(encoding="utf-8"))
        return Story.model_validate(data)
    except (json.JSONDecodeError, ValueError) as e:
        console.print(f"[red]Error loading story.json: {e}[/red]")
        raise typer.Exit(code=1) from e


def _load_or_create_manifest(
    manifest_path: Path | None,
    output_dir: Path,
) -> AssetManifestSchema | None:
    """Load an existing manifest or return None for fresh start.

    If manifest_path is provided explicitly, load from that path.
    Otherwise, check for asset-manifest.json in the output directory.
    """
    # Explicit manifest path
    if manifest_path is not None:
        try:
            manifest = load_manifest(manifest_path)
            console.print(
                f"[dim]Resuming from manifest: {manifest_path} "
                f"({manifest.summary.complete} complete, "
                f"{manifest.summary.pending} pending, "
                f"{manifest.summary.failed} failed)[/dim]"
            )
            return manifest
        except ManifestError as e:
            console.print(f"[red]Error loading manifest: {e}[/red]")
            raise typer.Exit(code=1) from e

    # Check default location
    default_path = output_dir / "asset-manifest.json"
    if default_path.exists():
        try:
            manifest = load_manifest(default_path)
            console.print(
                f"[dim]Found existing manifest: {default_path} "
                f"({manifest.summary.complete} complete, "
                f"{manifest.summary.pending} pending, "
                f"{manifest.summary.failed} failed)[/dim]"
            )
            return manifest
        except ManifestError:
            logger.warning(
                "Existing manifest at %s is corrupted, starting fresh", default_path
            )

    return None


def _print_dry_run(requests: list) -> None:
    """Print the generation plan for dry-run mode."""
    if not requests:
        console.print("[green]No assets to generate.[/green]")
        return

    bg_count = sum(1 for r in requests if r.asset_type == "background")
    sprite_count = sum(1 for r in requests if r.asset_type == "sprite")

    console.print(f"\n[bold]Dry-run generation plan:[/bold]")
    console.print(f"  Backgrounds: {bg_count}")
    console.print(f"  Sprites: {sprite_count}")
    console.print(f"  Total: {len(requests)}")

    table = Table(title="Assets to Generate", show_lines=True)
    table.add_column("Asset ID", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Dimensions")
    table.add_column("Prompt", max_width=60)

    for req in requests:
        table.add_row(
            req.asset_id,
            req.asset_type,
            f"{req.width}x{req.height}",
            req.prompt[:57] + "..." if len(req.prompt) > 60 else req.prompt,
        )

    console.print(table)


def run_generate_assets(
    *,
    story_json: Path,
    output: Path,
    manifest: Path | None,
    characters_only: bool,
    backgrounds_only: bool,
    style: str | None,
    concurrency: int,
    config_path: Path | None,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Execute the asset generation pipeline."""
    setup_logging(verbose=verbose)
    cfg = load_config(project_path=config_path)

    if style is not None:
        # Override style from CLI flag
        cfg = cfg.model_copy(
            update={"assets": cfg.assets.model_copy(update={"style": style})}
        )

    console.print("[bold]VNE-CLI Asset Generator[/bold]")
    console.print(f"  Story: {story_json}")
    console.print(f"  Output: {output}")
    console.print(f"  Style: {cfg.assets.style}")
    console.print()

    # 1. Load story
    story = _load_story(story_json)
    console.print(
        f"Loaded story: [cyan]{story.metadata.title or 'Untitled'}[/cyan] "
        f"({len(story.characters)} characters, {len(story.chapters)} chapters)"
    )

    # 2. Load or create manifest
    existing_manifest = _load_or_create_manifest(manifest, output)

    # 3. Dry-run mode: show plan and exit
    if dry_run:
        plan = build_dry_run_plan(
            story,
            cfg.assets,
            characters_only=characters_only,
            backgrounds_only=backgrounds_only,
            manifest=existing_manifest,
        )
        _print_dry_run(plan)
        return

    # 4. Load image provider
    if not cfg.providers.image.package:
        console.print(
            "[red]No image provider configured.[/red]\n"
            "Set [providers.image] in your config file or use:\n"
            "  vne config init"
        )
        raise typer.Exit(code=1)

    try:
        image_provider = load_image_provider(cfg.providers.image)
    except (ProviderNotFoundError, TypeError) as e:
        console.print(f"[red]Failed to load image provider: {e}[/red]")
        raise typer.Exit(code=1) from e

    # 5. Run pipeline
    try:
        result_manifest = asyncio.run(
            run_asset_pipeline(
                story=story,
                image_provider=image_provider,
                config=cfg.assets,
                output_dir=output,
                manifest=existing_manifest,
                characters_only=characters_only,
                backgrounds_only=backgrounds_only,
                concurrency=concurrency,
                manifest_path=output / "asset-manifest.json",
            )
        )
    finally:
        # Ensure provider resources are released
        asyncio.run(image_provider.close())

    # 6. Final report
    summary = result_manifest.summary
    if summary.failed > 0:
        console.print(
            f"\n[yellow]Warning: {summary.failed} assets failed. "
            f"Re-run to retry failed assets.[/yellow]"
        )
