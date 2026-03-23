"""Configuration schema definitions.

All config sections are defined as frozen Pydantic models with sensible defaults.
The top-level VneConfig aggregates all sections.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ProviderConfig(BaseModel):
    """Configuration for a single provider (LLM or image gen).

    Known fields (package, factory, model) are stored directly.
    Any additional provider-specific keys from TOML are captured in ``extra``.
    """

    package: str = ""
    factory: str = ""
    model: str = ""
    extra: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_extra(cls, values: dict[str, object]) -> dict[str, object]:
        """Move unknown keys into the ``extra`` dict."""
        if not isinstance(values, dict):
            return values
        known = {"package", "factory", "model", "extra"}
        extra = values.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}
        overflow = {k: v for k, v in values.items() if k not in known}
        for k in overflow:
            del values[k]
        extra.update(overflow)
        values["extra"] = extra
        return values


class ProvidersConfig(BaseModel):
    """All provider configurations."""

    llm: ProviderConfig = Field(default_factory=ProviderConfig)
    image: ProviderConfig = Field(default_factory=ProviderConfig)


class CredentialsConfig(BaseModel):
    """Credential configuration. Values here are fallbacks; env vars take precedence.

    All keys are provider-specific (e.g. ``openai_api_key``) and are
    collected into the ``extra`` dict automatically.
    """

    extra: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _collect_extra(cls, values: dict[str, object]) -> dict[str, object]:
        """Move all keys into the ``extra`` dict."""
        if not isinstance(values, dict):
            return values
        known = {"extra"}
        extra = values.get("extra", {})
        if not isinstance(extra, dict):
            extra = {}
        overflow = {k: v for k, v in values.items() if k not in known}
        for k in overflow:
            del values[k]
        extra.update(overflow)  # type: ignore[arg-type]
        values["extra"] = extra
        return values


class ChunkingConfig(BaseModel):
    """Text chunking configuration for LLM context windows."""

    target_tokens: int = 8000
    overlap_tokens: int = 500


class ExtractionConfig(BaseModel):
    """Configuration for the extract command."""

    language: str = "en"
    max_chapters: int = 50
    max_branch_depth: int = 3
    max_choices_per_branch: int = 3
    protagonist_name: str = ""
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)


class AssetsConfig(BaseModel):
    """Configuration for the generate-assets command."""

    style: str = "anime"
    background_size: tuple[int, int] = (1920, 1080)
    sprite_size: tuple[int, int] = (800, 1200)
    output_format: str = "png"


class AssemblyConfig(BaseModel):
    """Configuration for the assemble command."""

    default_text_speed: int = 30
    default_transition: str = "fade"
    transition_duration_ms: int = 500


class CinematicConfig(BaseModel):
    """Configuration for cinematic direction."""

    enabled: bool = True
    tier: str = "full"  # "base" | "full"


class ProjectConfig(BaseModel):
    """Project-level metadata."""

    name: str = "Untitled Visual Novel"
    version: str = "1.0.0"
    resolution: tuple[int, int] = (1920, 1080)


class VneConfig(BaseModel):
    """Top-level VNE-CLI configuration, aggregating all sections."""

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    credentials: CredentialsConfig = Field(default_factory=CredentialsConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    assets: AssetsConfig = Field(default_factory=AssetsConfig)
    assembly: AssemblyConfig = Field(default_factory=AssemblyConfig)
    cinematic: CinematicConfig = Field(default_factory=CinematicConfig)
