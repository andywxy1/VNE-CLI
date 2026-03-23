"""Asset generation orchestration.

Coordinates the generation of all visual assets (backgrounds, character sprites)
via the configured image provider, with concurrency control and resume support.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from vne_cli.assets.downloader import save_background, save_sprite
from vne_cli.assets.manifest import AssetManifest, load_manifest, save_manifest
from vne_cli.assets.prompt_builder import AssetRequest, build_asset_requests
from vne_cli.config.schema import AssetsConfig
from vne_cli.providers.base import ImageProvider
from vne_cli.providers.errors import AssetGenerationError, ProviderError
from vne_cli.schemas.asset_manifest import AssetEntry, AssetStatus, AssetType
from vne_cli.schemas.story import Story
from vne_cli.utils.logging import get_logger
from vne_cli.utils.retry import retry_with_backoff

logger = get_logger(__name__)
console = Console()


def _init_manifest(
    story: Story,
    config: AssetsConfig,
    provider_name: str,
    requests: list[AssetRequest],
    existing: AssetManifest | None,
) -> AssetManifest:
    """Initialize or update a manifest with the current asset requests.

    If an existing manifest is provided, it is updated with any new assets
    while preserving the status of already-tracked assets.
    """
    if existing is not None:
        manifest = existing
    else:
        manifest = AssetManifest(
            generated_at=datetime.now(timezone.utc),
            provider=provider_name,
            style=config.style,
        )

    for req in requests:
        if req.asset_id in manifest.assets:
            # Already tracked -- keep existing status
            continue
        entry = AssetEntry(
            type=AssetType.BACKGROUND if req.asset_type == "background" else AssetType.SPRITE,
            character=req.character_id,
            expression=req.expression,
            prompt=req.prompt,
            status=AssetStatus.PENDING,
            width=req.width,
            height=req.height,
        )
        manifest.assets[req.asset_id] = entry

    manifest.recompute_summary()
    return manifest


def _get_pending_requests(
    manifest: AssetManifest,
    requests: list[AssetRequest],
    *,
    retry_failed: bool = True,
) -> list[AssetRequest]:
    """Filter requests down to only those that still need generation.

    Skips assets marked as 'complete'. Includes 'pending' and optionally
    're-tries failed' assets.
    """
    pending = []
    for req in requests:
        entry = manifest.assets.get(req.asset_id)
        if entry is None:
            pending.append(req)
            continue
        if entry.status == AssetStatus.COMPLETE:
            continue
        if entry.status == AssetStatus.FAILED and not retry_failed:
            continue
        pending.append(req)
    return pending


async def _generate_single_asset(
    req: AssetRequest,
    provider: ImageProvider,
    manifest: AssetManifest,
    output_dir: Path,
    config: AssetsConfig,
    manifest_path: Path,
    *,
    max_retries: int = 3,
) -> bool:
    """Generate a single asset with retry logic.

    Updates the manifest entry in place and saves the manifest after
    each generation (for crash recovery).

    Returns True if generation succeeded, False otherwise.
    """
    entry = manifest.assets[req.asset_id]

    try:
        # Generate image via provider with retry
        image_bytes = await retry_with_backoff(
            lambda: provider.generate(
                req.prompt,
                width=req.width,
                height=req.height,
                style=config.style,
                negative_prompt=req.negative_prompt,
            ),
            max_retries=max_retries,
            retryable_exceptions=(ProviderError, ConnectionError, TimeoutError),
        )

        # Save to disk
        if req.asset_type == "background":
            rel_path = save_background(
                image_bytes,
                req.asset_id,
                output_dir,
                width=req.width,
                height=req.height,
                output_format=config.output_format,
            )
        else:
            assert req.character_id is not None
            assert req.expression is not None
            rel_path = save_sprite(
                image_bytes,
                req.character_id,
                req.expression,
                output_dir,
                width=req.width,
                height=req.height,
                output_format=config.output_format,
            )

        # Update manifest entry
        entry.status = AssetStatus.COMPLETE
        entry.file = str(rel_path)
        entry.generated_at = datetime.now(timezone.utc)
        entry.error = None

    except Exception as e:
        entry.status = AssetStatus.FAILED
        entry.error = str(e)
        logger.error("Failed to generate %s: %s", req.asset_id, e)
        return False

    finally:
        # Save manifest after each asset for crash recovery
        manifest.recompute_summary()
        save_manifest(manifest, manifest_path)

    return True


async def run_asset_pipeline(
    story: Story,
    image_provider: ImageProvider,
    config: AssetsConfig,
    output_dir: Path,
    manifest: AssetManifest | None = None,
    *,
    characters_only: bool = False,
    backgrounds_only: bool = False,
    concurrency: int = 3,
    max_retries: int = 3,
    manifest_path: Path | None = None,
) -> AssetManifest:
    """Run the full asset generation pipeline.

    Args:
        story: Extracted story with character and scene descriptions.
        image_provider: Configured image generation provider.
        config: Asset generation settings.
        output_dir: Directory to write generated images.
        manifest: Existing manifest for resume (None for fresh start).
        characters_only: Generate only character sprites.
        backgrounds_only: Generate only backgrounds.
        concurrency: Max parallel generation requests.
        max_retries: Max retries per asset on failure.
        manifest_path: Where to save the manifest (defaults to output_dir/asset-manifest.json).

    Returns:
        Updated asset manifest with generation results.
    """
    if manifest_path is None:
        manifest_path = output_dir / "asset-manifest.json"

    # Build the full list of asset requests
    requests = build_asset_requests(
        story,
        style_prefix=config.style,
        background_size=config.background_size,
        sprite_size=config.sprite_size,
        characters_only=characters_only,
        backgrounds_only=backgrounds_only,
    )

    # Initialize manifest with all needed assets
    result_manifest = _init_manifest(
        story, config, image_provider.name, requests, manifest
    )

    # Filter to only pending/failed assets
    pending = _get_pending_requests(result_manifest, requests)
    skipped = len(requests) - len(pending)

    if skipped > 0:
        console.print(f"[dim]Skipping {skipped} already-completed assets[/dim]")

    if not pending:
        console.print("[green]All assets already generated. Nothing to do.[/green]")
        return result_manifest

    console.print(
        f"Generating {len(pending)} assets "
        f"({sum(1 for r in pending if r.asset_type == 'background')} backgrounds, "
        f"{sum(1 for r in pending if r.asset_type == 'sprite')} sprites) "
        f"with concurrency={concurrency}"
    )

    # Create output directories
    (output_dir / "backgrounds").mkdir(parents=True, exist_ok=True)
    (output_dir / "characters").mkdir(parents=True, exist_ok=True)

    # Generate assets with concurrency control
    semaphore = asyncio.Semaphore(concurrency)
    succeeded = 0
    failed = 0

    async def _bounded_generate(req: AssetRequest) -> bool:
        async with semaphore:
            return await _generate_single_asset(
                req,
                image_provider,
                result_manifest,
                output_dir,
                config,
                manifest_path,
                max_retries=max_retries,
            )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Generating assets...", total=len(pending))

        # Run all generations concurrently (bounded by semaphore)
        tasks = [_bounded_generate(req) for req in pending]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result:
                succeeded += 1
            else:
                failed += 1
            progress.advance(task)

    # Final manifest save
    result_manifest.recompute_summary()
    save_manifest(result_manifest, manifest_path)

    # Report
    console.print(f"\n[bold]Asset generation complete:[/bold]")
    console.print(f"  [green]Generated:[/green] {succeeded}")
    console.print(f"  [dim]Skipped (already done):[/dim] {skipped}")
    if failed > 0:
        console.print(f"  [red]Failed:[/red] {failed}")
    console.print(f"  [bold]Total in manifest:[/bold] {result_manifest.summary.total}")

    return result_manifest


def build_dry_run_plan(
    story: Story,
    config: AssetsConfig,
    *,
    characters_only: bool = False,
    backgrounds_only: bool = False,
    manifest: AssetManifest | None = None,
) -> list[AssetRequest]:
    """Build a generation plan without executing it.

    Returns the list of asset requests that would be generated.
    """
    requests = build_asset_requests(
        story,
        style_prefix=config.style,
        background_size=config.background_size,
        sprite_size=config.sprite_size,
        characters_only=characters_only,
        backgrounds_only=backgrounds_only,
    )

    if manifest is not None:
        requests = _get_pending_requests(manifest, requests)

    return requests
