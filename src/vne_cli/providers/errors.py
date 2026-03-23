"""Provider-specific error types."""

from __future__ import annotations


class VneCliError(Exception):
    """Base exception for all VNE-CLI errors."""


class ConfigError(VneCliError):
    """Base for configuration errors."""


class ConfigNotFoundError(ConfigError):
    """A required config file was not found."""


class ConfigValidationError(ConfigError):
    """Config file contents are invalid."""


class CredentialMissingError(ConfigError):
    """A required credential could not be resolved from any source."""


class ProviderError(VneCliError):
    """Base for provider errors."""


class ProviderNotFoundError(ProviderError):
    """Provider package or factory could not be loaded."""


class ProviderAuthError(ProviderError):
    """Authentication with provider failed."""


class ProviderRateLimitError(ProviderError):
    """Provider rate limit exceeded."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderResponseError(ProviderError):
    """Provider returned an unexpected or invalid response."""


class ExtractionError(VneCliError):
    """Base for extraction errors."""


class InputFormatError(ExtractionError):
    """Input file format is unsupported or unreadable."""


class ChunkingError(ExtractionError):
    """Text chunking failed."""


class StructureValidationError(ExtractionError):
    """Extracted structure failed validation."""


class AssetError(VneCliError):
    """Base for asset generation errors."""


class AssetGenerationError(AssetError):
    """Image generation failed for a specific asset."""


class ManifestError(AssetError):
    """Asset manifest is invalid or corrupted."""


class AssemblyError(VneCliError):
    """Base for assembly errors."""


class FlowGenerationError(AssemblyError):
    """Flow graph generation failed."""


class MissingAssetError(AssemblyError):
    """A required asset file is missing from the assets directory."""


class ProjectValidationError(AssemblyError):
    """Assembled project failed validation."""
