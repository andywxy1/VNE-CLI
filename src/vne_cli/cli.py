"""CLI entry point for VNE-CLI.

All commands are defined here and delegate to the commands/ module for
orchestration logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from typing import Any as _Any

from vne_cli import __version__


def _tuples_to_lists(d: dict[str, _Any]) -> None:
    """Recursively convert tuple values to lists for TOML serialization."""
    for k, v in d.items():
        if isinstance(v, tuple):
            d[k] = list(v)
        elif isinstance(v, dict):
            _tuples_to_lists(v)

app = typer.Typer(
    name="vne",
    help="Generate complete VoidNovelEngine projects from novel text.",
    no_args_is_help=True,
    pretty_exceptions_enable=True,
)

config_app = typer.Typer(
    name="config",
    help="Manage VNE-CLI configuration.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"vne-cli {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(  # noqa: UP007
        None,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """VNE-CLI: Visual novel project generator."""


@app.command()
def extract(
    input_file: Path = typer.Argument(
        ...,
        help="Path to novel text file (.txt, .md, .epub).",
        exists=True,
        readable=True,
    ),
    output: Path = typer.Option(
        Path("story.json"),
        "--output",
        "-o",
        help="Output story.json path.",
    ),
    characters_only: bool = typer.Option(
        False,
        "--characters-only",
        help="Run only the character extraction pre-pass.",
    ),
    characters: Optional[Path] = typer.Option(  # noqa: UP007
        None,
        "--characters",
        help="Path to existing character registry to reuse.",
        exists=True,
    ),
    config: Optional[Path] = typer.Option(  # noqa: UP007
        None,
        "--config",
        help="Project config file override.",
        exists=True,
    ),
    max_chapters: Optional[int] = typer.Option(  # noqa: UP007
        None,
        "--max-chapters",
        help="Override max chapter count.",
    ),
    max_branch_depth: Optional[int] = typer.Option(  # noqa: UP007
        None,
        "--max-branch-depth",
        help="Override max branch depth.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate input and show extraction plan without calling LLM.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose/--no-verbose",
        help="Enable detailed logging.",
    ),
) -> None:
    """Parse novel text into structured story JSON."""
    from vne_cli.commands.extract import run_extract

    run_extract(
        input_file=input_file,
        output=output,
        characters_only=characters_only,
        characters=characters,
        config_path=config,
        max_chapters=max_chapters,
        max_branch_depth=max_branch_depth,
        dry_run=dry_run,
        verbose=verbose,
    )


@app.command(name="generate-assets")
def generate_assets(
    story_json: Path = typer.Argument(
        ...,
        help="Path to story.json from extract stage.",
        exists=True,
        readable=True,
    ),
    output: Path = typer.Option(
        Path("assets"),
        "--output",
        "-o",
        help="Output assets directory.",
    ),
    manifest: Optional[Path] = typer.Option(  # noqa: UP007
        None,
        "--manifest",
        help="Resume from existing asset manifest.",
        exists=True,
    ),
    characters_only: bool = typer.Option(
        False,
        "--characters-only",
        help="Generate only character sprites.",
    ),
    backgrounds_only: bool = typer.Option(
        False,
        "--backgrounds-only",
        help="Generate only backgrounds.",
    ),
    style: Optional[str] = typer.Option(  # noqa: UP007
        None,
        "--style",
        help="Override image style.",
    ),
    concurrency: int = typer.Option(
        3,
        "--concurrency",
        help="Max parallel API requests.",
    ),
    config: Optional[Path] = typer.Option(  # noqa: UP007
        None,
        "--config",
        help="Project config file override.",
        exists=True,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be generated without calling APIs.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose/--no-verbose",
        help="Enable detailed logging.",
    ),
) -> None:
    """Generate images for characters and backgrounds via pluggable API."""
    from vne_cli.commands.generate_assets import run_generate_assets

    run_generate_assets(
        story_json=story_json,
        output=output,
        manifest=manifest,
        characters_only=characters_only,
        backgrounds_only=backgrounds_only,
        style=style,
        concurrency=concurrency,
        config_path=config,
        dry_run=dry_run,
        verbose=verbose,
    )


@app.command()
def assemble(
    story_json: Path = typer.Argument(
        ...,
        help="Path to story.json from extract stage.",
        exists=True,
        readable=True,
    ),
    assets: Path = typer.Option(
        ...,
        "--assets",
        help="Assets directory from generate-assets stage.",
        exists=True,
    ),
    output: Path = typer.Option(
        Path("project"),
        "--output",
        "-o",
        help="Output project directory.",
    ),
    resolution: Optional[str] = typer.Option(  # noqa: UP007
        None,
        "--resolution",
        help="Game window resolution as WIDTHxHEIGHT (e.g. 1920x1080).",
    ),
    title: Optional[str] = typer.Option(  # noqa: UP007
        None,
        "--title",
        help="Override project title.",
    ),
    cinematic: bool = typer.Option(
        True,
        "--cinematic/--no-cinematic",
        help="Apply cinematic direction layer.",
    ),
    cinematic_tier: Optional[str] = typer.Option(  # noqa: UP007
        None,
        "--cinematic-tier",
        help='Cinematic tier: "base" or "full".',
    ),
    validate: bool = typer.Option(
        True,
        "--validate/--no-validate",
        help="Validate output before writing.",
    ),
    config: Optional[Path] = typer.Option(  # noqa: UP007
        None,
        "--config",
        help="Project config file override.",
        exists=True,
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose/--no-verbose",
        help="Enable detailed logging.",
    ),
) -> None:
    """Assemble story JSON and assets into a ready-to-run VNE project."""
    from vne_cli.commands.assemble import run_assemble

    # Parse resolution string.
    parsed_resolution = None
    if resolution is not None:
        try:
            w, h = resolution.lower().split("x")
            parsed_resolution = (int(w), int(h))
        except (ValueError, AttributeError):
            typer.echo(f"Error: Invalid resolution format '{resolution}'. Use WIDTHxHEIGHT.", err=True)
            raise typer.Exit(code=1)

    run_assemble(
        story_json=story_json,
        assets_dir=assets,
        output=output,
        cinematic=cinematic,
        cinematic_tier=cinematic_tier,
        validate_output=validate,
        config_path=config,
        verbose=verbose,
        title=title,
        resolution=parsed_resolution,
    )


@app.command()
def validate(
    file: Path = typer.Argument(
        ...,
        help="File to validate (story.json, .flow, project.vne, manifest).",
        exists=True,
        readable=True,
    ),
) -> None:
    """Validate any VNE-CLI intermediate file."""
    typer.echo(f"Validating {file}...")
    # TODO: Implement in WS3-T4
    typer.echo("Validation not yet implemented.")
    raise typer.Exit(code=1)


@config_app.command("show")
def config_show(
    resolved: bool = typer.Option(
        False,
        "--resolved",
        help="Show source annotations per key.",
    ),
) -> None:
    """Display resolved configuration from all layers."""
    from vne_cli.config.loader import load_config, resolve_config_sources

    if resolved:
        sources = resolve_config_sources()
        typer.echo("# Resolved config with source annotations")
        typer.echo("# Sources: [default] | [user] ~/.vne-cli/config.toml "
                    "| [project] ./vne-cli.toml | [env] VNE_CLI_*")
        typer.echo("")
        for key, (value, source) in sorted(sources.items()):
            typer.echo(f"{key} = {value!r}  # [{source}]")
    else:
        import tomli_w

        cfg = load_config()
        data = cfg.model_dump()
        # Convert tuples to lists for TOML serialization
        _tuples_to_lists(data)
        typer.echo("# Resolved VNE-CLI configuration")
        typer.echo(tomli_w.dumps(data))


@config_app.command("init")
def config_init(
    global_config: bool = typer.Option(
        False,
        "--global",
        help="Create user-level config at ~/.vne-cli/config.toml.",
    ),
) -> None:
    """Create a config file with defaults."""
    from vne_cli.config.loader import create_default_config

    create_default_config(global_config=global_config)
