"""Layered configuration loader.

Precedence (last wins):
1. Built-in defaults (from schema.py)
2. User config: ~/.vne-cli/config.toml
3. Project config: ./vne-cli.toml (or --config flag)
4. Environment variables: VNE_CLI_* prefix
5. CLI flags (applied by callers after loading)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import typer

from vne_cli.config.schema import VneConfig

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

USER_CONFIG_DIR = Path.home() / ".vne-cli"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.toml"
PROJECT_CONFIG_NAME = "vne-cli.toml"
ENV_PREFIX = "VNE_CLI_"


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file and return its contents as a dict."""
    if tomllib is None:
        msg = "tomli is required on Python < 3.11. Install it: pip install tomli"
        raise RuntimeError(msg)
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base. Override wins on conflicts."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _collect_schema_paths(
    model: type, prefix: str = ""
) -> dict[str, list[str]]:
    """Walk a Pydantic model and collect all dotted field paths.

    Returns a dict mapping the SCREAMING_SNAKE_CASE env suffix (with
    dots replaced by underscores) to the dotted path segments, e.g.
    ``{"EXTRACTION_MAX_CHAPTERS": ["extraction", "max_chapters"]}``.
    """
    from pydantic import BaseModel

    paths: dict[str, list[str]] = {}
    for field_name, field_info in model.model_fields.items():
        dotted = f"{prefix}.{field_name}" if prefix else field_name
        segments = dotted.split(".")
        env_suffix = dotted.replace(".", "_").upper()
        annotation = field_info.annotation

        # Unwrap Optional / Union types to find the core type
        origin = getattr(annotation, "__origin__", None)
        if origin is type(None):
            continue
        # Check if annotation is itself a BaseModel subclass
        is_model = False
        try:
            is_model = isinstance(annotation, type) and issubclass(annotation, BaseModel)
        except TypeError:
            pass

        if is_model:
            nested = _collect_schema_paths(annotation, dotted)
            paths.update(nested)
        else:
            paths[env_suffix] = segments

    return paths


def _env_overrides() -> dict[str, Any]:
    """Extract VNE_CLI_* environment variables and convert to nested dict.

    Uses the VneConfig schema to correctly map env var names to nested keys.
    For example, ``VNE_CLI_EXTRACTION_MAX_CHAPTERS=5`` becomes
    ``{"extraction": {"max_chapters": "5"}}``, not
    ``{"extraction": {"max": {"chapters": "5"}}}``.

    Falls back to naive underscore splitting for keys not in the schema
    (e.g. provider-specific extra config).
    """
    known_paths = _collect_schema_paths(VneConfig)

    result: dict[str, Any] = {}
    for key, value in os.environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        suffix = key[len(ENV_PREFIX):]

        if suffix in known_paths:
            segments = known_paths[suffix]
        else:
            # Fallback: naive underscore splitting
            segments = suffix.lower().split("_")

        current = result
        for seg in segments[:-1]:
            current = current.setdefault(seg, {})
        current[segments[-1]] = value

    return result


def load_config(
    *,
    project_path: Path | None = None,
) -> VneConfig:
    """Load configuration from all layers and return a validated VneConfig.

    Args:
        project_path: Explicit path to project config file. If None,
                      looks for ./vne-cli.toml in the current directory.
    """
    # Layer 1: defaults (handled by Pydantic model defaults)
    merged: dict[str, Any] = {}

    # Layer 2: user config
    user_data = _load_toml(USER_CONFIG_PATH)
    merged = _deep_merge(merged, user_data)

    # Layer 3: project config
    if project_path is not None:
        project_data = _load_toml(project_path)
    else:
        project_data = _load_toml(Path.cwd() / PROJECT_CONFIG_NAME)
    # Strip credentials from project config (security rule)
    project_data.pop("credentials", None)
    merged = _deep_merge(merged, project_data)

    # Layer 4: environment variables
    env_data = _env_overrides()
    merged = _deep_merge(merged, env_data)

    # Validate and return
    return VneConfig(**merged)


def resolve_config_sources(
    *,
    project_path: Path | None = None,
) -> dict[str, tuple[Any, str]]:
    """Load config from all layers and track the source of each key.

    Returns a flat dict mapping dotted key paths to ``(value, source)`` tuples.
    Source is one of: ``default``, ``user``, ``project``, ``env``.

    Args:
        project_path: Explicit path to project config file.
    """
    defaults = VneConfig().model_dump()
    user_data = _load_toml(USER_CONFIG_PATH)
    if project_path is not None:
        project_data = _load_toml(project_path)
    else:
        project_data = _load_toml(Path.cwd() / PROJECT_CONFIG_NAME)
    project_data.pop("credentials", None)
    env_data = _env_overrides()

    result: dict[str, tuple[Any, str]] = {}

    def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
        flat: dict[str, Any] = {}
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                flat.update(_flatten(v, key))
            else:
                flat[key] = v
        return flat

    flat_defaults = _flatten(defaults)
    flat_user = _flatten(user_data)
    flat_project = _flatten(project_data)
    flat_env = _flatten(env_data)

    # Start with defaults, then layer on sources
    for key, value in flat_defaults.items():
        result[key] = (value, "default")
    for key, value in flat_user.items():
        result[key] = (value, "user")
    for key, value in flat_project.items():
        result[key] = (value, "project")
    for key, value in flat_env.items():
        result[key] = (value, "env")

    return result


def create_default_config(*, global_config: bool) -> None:
    """Create a config file with default values.

    Args:
        global_config: If True, creates ~/.vne-cli/config.toml.
                       If False, creates ./vne-cli.toml.
    """
    if global_config:
        path = USER_CONFIG_PATH
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        template = _user_config_template()
    else:
        path = Path.cwd() / PROJECT_CONFIG_NAME
        template = _project_config_template()

    if path.exists():
        typer.echo(f"Config already exists: {path}")
        raise typer.Exit(code=1)

    path.write_text(template)
    typer.echo(f"Created config: {path}")


def _user_config_template() -> str:
    return """\
# VNE-CLI User Configuration
# Location: ~/.vne-cli/config.toml

[providers.llm]
package = ""       # e.g. "vne_cli_openai"
factory = ""       # e.g. "create_llm_provider"
model = ""         # e.g. "gpt-4o"

[providers.image]
package = ""       # e.g. "vne_cli_dalle"
factory = ""       # e.g. "create_image_provider"
model = ""         # e.g. "dall-e-3"

[credentials]
# Prefer environment variables: VNE_CLI_OPENAI_API_KEY, etc.
# Values here are fallbacks only.
"""


def _project_config_template() -> str:
    return """\
# VNE-CLI Project Configuration
# Location: ./vne-cli.toml

[project]
name = "My Visual Novel"
version = "1.0.0"
resolution = [1920, 1080]

[extraction]
language = "en"
max_chapters = 50
max_branch_depth = 3
max_choices_per_branch = 3
protagonist_name = ""

[extraction.chunking]
target_tokens = 8000
overlap_tokens = 500

[assets]
style = "anime"
background_size = [1920, 1080]
sprite_size = [800, 1200]
output_format = "png"

[assembly]
default_text_speed = 30
default_transition = "fade"
transition_duration_ms = 500

[cinematic]
enabled = true
tier = "full"
"""
