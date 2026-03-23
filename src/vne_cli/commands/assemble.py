"""Assemble command: build a ready-to-run VNE project.

Orchestrates the assembly pipeline:
1. Load story.json
2. Generate .flow files for each scene
3. Apply cinematic direction layer (optional)
4. Organize assets into project structure
5. Generate project.vne manifest
6. Validate assembled project
7. Report results
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

from vne_cli.config.loader import load_config
from vne_cli.utils.logging import setup_logging

logger = logging.getLogger("vne_cli.commands.assemble")


def run_assemble(
    *,
    story_json: Path,
    assets_dir: Path,
    output: Path,
    cinematic: bool,
    cinematic_tier: str | None,
    validate_output: bool,
    config_path: Path | None,
    verbose: bool,
    title: str | None = None,
    resolution: tuple[int, int] | None = None,
) -> None:
    """Execute the assembly pipeline.

    Args:
        story_json: Path to the story.json file.
        assets_dir: Path to the assets directory from generate-assets.
        output: Output project directory.
        cinematic: Whether to apply cinematic direction.
        cinematic_tier: Cinematic tier override ("base" or "full").
        validate_output: Whether to validate the output after assembly.
        config_path: Optional project config file override.
        verbose: Enable verbose logging.
        title: Optional title override for the project.
        resolution: Optional resolution override as (width, height).
    """
    setup_logging(verbose=verbose)
    cfg = load_config(project_path=config_path)

    # Apply overrides.
    if cinematic_tier is not None:
        cfg.cinematic.tier = cinematic_tier
    if not cinematic:
        cfg.cinematic.enabled = False

    typer.echo(f"Assembling project from: {story_json}")
    typer.echo(f"Assets directory: {assets_dir}")
    typer.echo(f"Output directory: {output}")

    # 1. Load story.json.
    typer.echo("Loading story data...")
    from vne_cli.schemas.story import Story

    try:
        raw = json.loads(story_json.read_text(encoding="utf-8"))
        story = Story.model_validate(raw)
    except json.JSONDecodeError as e:
        typer.echo(f"Error: story.json is not valid JSON: {e}", err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"Error: Failed to parse story.json: {e}", err=True)
        raise typer.Exit(code=1)

    scene_count = sum(len(ch.scenes) for ch in story.chapters)
    typer.echo(
        f"Loaded story: '{story.metadata.title}' "
        f"({len(story.chapters)} chapters, {scene_count} scenes, "
        f"{len(story.characters)} characters)"
    )

    # 2. Create project directory structure.
    from vne_cli.assembly.project_builder import (
        create_default_icon,
        create_directory_structure,
        write_main_lua,
    )

    create_directory_structure(output)

    # 3. Generate .flow files.
    typer.echo("Generating flow files...")
    from vne_cli.assembly.flow_writer import generate_flows

    flow_dir = output / "application" / "flow"
    flow_files = generate_flows(
        story=story,
        output_dir=flow_dir,
        assembly_config=cfg.assembly,
        cinematic_config=cfg.cinematic,
    )
    typer.echo(f"Generated {len(flow_files)} .flow files")

    # 4. Organize assets.
    typer.echo("Organizing assets...")
    from vne_cli.assembly.asset_organizer import organize_assets

    asset_report = organize_assets(
        assets_dir=assets_dir,
        output_dir=output,
        flow_dir=flow_dir,
    )
    typer.echo(f"Copied {asset_report.total_copied} assets")
    for w in asset_report.warnings:
        typer.echo(f"  Warning: {w}", err=True)

    # 5. Generate project.vne.
    typer.echo("Writing project.vne...")
    from vne_cli.assembly.project_builder import build_project_config, write_project_vne

    width = cfg.project.resolution[0]
    height = cfg.project.resolution[1]
    if resolution is not None:
        width, height = resolution

    entry_flow_path = "application/flow/entry.flow"
    project_config = build_project_config(
        story=story,
        entry_flow_path=entry_flow_path,
        title=title or cfg.project.name,
        developer="VNE-CLI",
        width=width,
        height=height,
    )
    write_project_vne(project_config, output)

    # 6. Write main.lua and default icon.
    write_main_lua(output)
    create_default_icon(output)

    # 7. Validate if requested.
    if validate_output:
        typer.echo("Validating assembled project...")
        from vne_cli.assembly.validator import validate_project

        validation = validate_project(output)
        typer.echo(validation.summary())

        if not validation.is_valid:
            typer.echo("Assembly completed with validation errors.", err=True)
            raise typer.Exit(code=1)
    else:
        typer.echo("Skipping validation (--no-validate).")

    typer.echo("")
    typer.echo(f"Project assembled successfully at: {output}")
    typer.echo(f"  project.vne:  {output / 'project.vne'}")
    typer.echo(f"  Flow files:   {len(flow_files)} in application/flow/")
    typer.echo(f"  Assets:       {asset_report.total_copied} copied")
