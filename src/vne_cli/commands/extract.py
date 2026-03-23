"""Extract command: parse novel text into structured story JSON.

Orchestrates the extraction pipeline:
1. Load and validate input text
2. Run character pre-pass (or load existing registry)
3. Chunk text for LLM context windows
4. Extract structure (chapters, scenes, beats, branches)
5. Detect and enforce branches
6. Validate and write story.json
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from vne_cli import __version__
from vne_cli.config.loader import load_config
from vne_cli.config.schema import VneConfig
from vne_cli.extraction.branch_detector import (
    detect_and_apply_branches,
    detect_explicit_cues_in_text,
)
from vne_cli.extraction.character_pass import extract_characters
from vne_cli.extraction.chunker import chunk_text, estimate_tokens
from vne_cli.extraction.structure_pass import extract_structure
from vne_cli.extraction.validator import validate_story
from vne_cli.providers.errors import (
    ExtractionError,
    ProviderNotFoundError,
    StructureValidationError,
    VneCliError,
)
from vne_cli.providers.registry import load_llm_provider
from vne_cli.schemas.characters import CharacterRegistry
from vne_cli.schemas.story import ExtractionMetadata
from vne_cli.utils.logging import setup_logging

console = Console()


def run_extract(
    *,
    input_file: Path,
    output: Path,
    characters_only: bool,
    characters: Path | None,
    config_path: Path | None,
    max_chapters: int | None,
    max_branch_depth: int | None,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Execute the extract pipeline."""
    setup_logging(verbose=verbose)
    cfg = load_config(project_path=config_path)

    # Apply CLI overrides
    if max_chapters is not None:
        cfg.extraction.max_chapters = max_chapters
    if max_branch_depth is not None:
        cfg.extraction.max_branch_depth = max_branch_depth

    console.print(f"[bold]VNE-CLI Extract[/bold] v{__version__}")
    console.print(f"  Input:  {input_file}")
    console.print(f"  Output: {output}")
    console.print()

    # Read and validate input
    try:
        text = _read_input(input_file)
    except ExtractionError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    total_tokens = estimate_tokens(text)
    console.print(f"  Input size: {len(text):,} chars, ~{total_tokens:,} tokens estimated")

    # Pre-scan for explicit branch cues
    explicit_cues = detect_explicit_cues_in_text(text)
    if explicit_cues:
        console.print(
            f"  Found {len(explicit_cues)} explicit branch cue(s) in source text"
        )

    if dry_run:
        _show_dry_run(text, cfg, explicit_cues)
        return

    # Run the async pipeline
    try:
        asyncio.run(_run_pipeline(
            text=text,
            cfg=cfg,
            input_file=input_file,
            output=output,
            characters_only=characters_only,
            characters_path=characters,
        ))
    except ProviderNotFoundError as e:
        console.print(f"\n[red]Provider Error:[/red] {e}")
        console.print(
            "[dim]Configure your LLM provider in ~/.vne-cli/config.toml "
            "or set VNE_CLI_PROVIDERS_LLM_PACKAGE[/dim]"
        )
        raise typer.Exit(code=1)
    except StructureValidationError as e:
        console.print(f"\n[red]Validation Error:[/red] {e}")
        raise typer.Exit(code=1)
    except ExtractionError as e:
        console.print(f"\n[red]Extraction Error:[/red] {e}")
        raise typer.Exit(code=1)
    except VneCliError as e:
        console.print(f"\n[red]Error:[/red] {e}")
        raise typer.Exit(code=1)


async def _run_pipeline(
    *,
    text: str,
    cfg: VneConfig,
    input_file: Path,
    output: Path,
    characters_only: bool,
    characters_path: Path | None,
) -> None:
    """Run the full extraction pipeline."""
    start_time = time.monotonic()

    # Load LLM provider
    llm = load_llm_provider(cfg.providers.llm)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            # Step 1: Chunk text
            task = progress.add_task("Chunking text...", total=None)
            chunks = chunk_text(text, cfg.extraction.chunking)
            progress.update(task, description=f"Chunked into {len(chunks)} pieces")
            progress.remove_task(task)

            # Step 2: Character extraction
            if characters_path:
                task = progress.add_task("Loading character registry...", total=None)
                character_registry = _load_character_registry(characters_path)
                progress.update(
                    task,
                    description=(
                        f"Loaded {len(character_registry.characters)} characters"
                    ),
                )
                progress.remove_task(task)
            else:
                task = progress.add_task(
                    "Extracting characters (LLM pass)...", total=None
                )
                character_registry = await extract_characters(
                    chunks, llm, source_file=str(input_file)
                )
                progress.update(
                    task,
                    description=(
                        f"Extracted {len(character_registry.characters)} characters"
                    ),
                )
                progress.remove_task(task)

            # If characters-only, write and exit
            if characters_only:
                _write_characters(character_registry, output)
                console.print(
                    f"\n[green]Character registry written to {output}[/green]"
                )
                return

            # Step 3: Structure extraction
            task = progress.add_task(
                "Extracting story structure (LLM pass)...", total=None
            )
            story = await extract_structure(
                chunks,
                character_registry,
                llm,
                source_file=str(input_file),
                cinematic_enabled=cfg.cinematic.enabled,
            )
            progress.update(
                task,
                description=(
                    f"Extracted {len(story.chapters)} chapters, "
                    f"{sum(len(ch.scenes) for ch in story.chapters)} scenes"
                ),
            )
            progress.remove_task(task)

            # Step 4: Branch detection and enforcement
            task = progress.add_task("Detecting and enforcing branches...", total=None)
            story = detect_and_apply_branches(story, cfg.extraction)
            bp_count = sum(len(ch.branch_points) for ch in story.chapters)
            progress.update(
                task,
                description=f"Applied {bp_count} branch point(s)",
            )
            progress.remove_task(task)

            # Step 5: Validation
            task = progress.add_task("Validating story structure...", total=None)
            warnings = validate_story(story)
            progress.update(
                task,
                description=f"Validation passed ({len(warnings)} warnings)",
            )
            progress.remove_task(task)

        # Populate extraction metadata
        elapsed = time.monotonic() - start_time
        story.metadata.extracted_at = datetime.now(timezone.utc)
        story.metadata.vne_cli_version = __version__
        story.extraction_metadata = ExtractionMetadata(
            extractor_version=__version__,
            llm_provider=llm.name,
            total_chunks=len(chunks),
            total_tokens_estimated=sum(c.estimated_tokens for c in chunks),
            extraction_duration_seconds=round(elapsed, 2),
        )

        # Step 6: Write output
        _write_story(story, output)

        console.print()
        console.print(f"[green bold]Extraction complete![/green bold]")
        console.print(f"  Output: {output}")
        console.print(f"  Chapters: {len(story.chapters)}")
        console.print(
            f"  Scenes: {sum(len(ch.scenes) for ch in story.chapters)}"
        )
        console.print(f"  Characters: {len(story.characters)}")
        console.print(f"  Branch points: {bp_count}")
        console.print(f"  Duration: {elapsed:.1f}s")

        if warnings:
            console.print(f"\n[yellow]Warnings ({len(warnings)}):[/yellow]")
            for w in warnings[:10]:
                console.print(f"  [dim]- {w}[/dim]")
            if len(warnings) > 10:
                console.print(f"  [dim]... and {len(warnings) - 10} more[/dim]")

    finally:
        await llm.close()


def _read_input(path: Path) -> str:
    """Read and validate the input file."""
    if not path.exists():
        raise ExtractionError(f"Input file not found: {path}")

    suffix = path.suffix.lower()
    if suffix not in (".txt", ".md", ".text", ".markdown"):
        raise ExtractionError(
            f"Unsupported file format '{suffix}'. "
            f"Supported: .txt, .md, .text, .markdown"
        )

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="latin-1")
        except Exception as e:
            raise ExtractionError(f"Cannot read input file: {e}") from e

    if not text.strip():
        raise ExtractionError("Input file is empty.")

    return text


def _load_character_registry(path: Path) -> CharacterRegistry:
    """Load an existing character registry from JSON."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return CharacterRegistry.model_validate(data)
    except Exception as e:
        raise ExtractionError(f"Failed to load character registry from {path}: {e}") from e


def _write_story(story: Story, output: Path) -> None:
    """Write the story to a JSON file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    data = story.model_dump(by_alias=True, mode="json")
    output.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _write_characters(registry: CharacterRegistry, output: Path) -> None:
    """Write the character registry to a JSON file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    data = registry.model_dump(by_alias=True, mode="json")
    output.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def _show_dry_run(
    text: str,
    cfg: VneConfig,
    explicit_cues: list[dict[str, str]],
) -> None:
    """Show extraction plan without running LLM calls."""
    from vne_cli.extraction.chunker import (
        chunk_text,
        detect_chapter_boundaries,
    )

    console.print("\n[yellow][dry-run] Extraction plan:[/yellow]")

    # Show chapter detection
    boundaries = detect_chapter_boundaries(text)
    if boundaries:
        console.print(f"\n  Detected {len(boundaries)} chapter(s):")
        for offset, title in boundaries[:20]:
            console.print(f"    - {title} (offset {offset})")
        if len(boundaries) > 20:
            console.print(f"    ... and {len(boundaries) - 20} more")
    else:
        console.print("\n  No chapter boundaries detected (will treat as single chapter)")

    # Show chunking plan
    try:
        chunks = chunk_text(text, cfg.extraction.chunking)
        console.print(f"\n  Would produce {len(chunks)} chunk(s):")
        for chunk in chunks[:10]:
            console.print(
                f"    - Chunk {chunk.index}: ~{chunk.estimated_tokens} tokens"
                f" (chapter: {chunk.chapter_hint})"
            )
        if len(chunks) > 10:
            console.print(f"    ... and {len(chunks) - 10} more")
    except Exception as e:
        console.print(f"\n  [red]Chunking would fail: {e}[/red]")

    # Show branch cues
    if explicit_cues:
        console.print(f"\n  Explicit branch cues found: {len(explicit_cues)}")
        for cue in explicit_cues[:5]:
            console.print(f'    - [{cue["type"]}] {cue["text"]}')

    console.print(f"\n  Config:")
    console.print(f"    max_chapters: {cfg.extraction.max_chapters}")
    console.print(f"    max_branch_depth: {cfg.extraction.max_branch_depth}")
    console.print(f"    max_choices_per_branch: {cfg.extraction.max_choices_per_branch}")
    console.print(f"    target_tokens: {cfg.extraction.chunking.target_tokens}")
    console.print(f"    cinematic: {cfg.cinematic.enabled} (tier: {cfg.cinematic.tier})")
    console.print("\n[yellow]No LLM calls were made.[/yellow]")
