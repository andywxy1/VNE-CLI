"""Credential resolution.

Resolves credentials from multiple sources in order:
1. Environment variables (VNE_CLI_<PROVIDER>_API_KEY)
2. User config file (~/.vne-cli/config.toml [credentials] section)
3. System keyring (optional, if keyring package is installed)
"""

from __future__ import annotations

import os
from typing import Any

from vne_cli.config.schema import CredentialsConfig

ENV_PREFIX = "VNE_CLI_"


def resolve_credential(
    key: str,
    credentials_config: CredentialsConfig,
) -> str | None:
    """Resolve a single credential by key.

    Args:
        key: Credential key, e.g. "openai_api_key".
        credentials_config: Credentials section from loaded config.

    Returns:
        The credential value, or None if not found in any source.
    """
    # Source 1: Environment variable
    env_key = f"{ENV_PREFIX}{key.upper()}"
    env_value = os.environ.get(env_key)
    if env_value:
        return env_value

    # Source 2: Config file
    config_value = credentials_config.extra.get(key)
    if config_value:
        return config_value

    # Source 3: System keyring (optional)
    keyring_value = _try_keyring(key)
    if keyring_value:
        return keyring_value

    return None


def _try_keyring(key: str) -> str | None:
    """Attempt to read from system keyring. Returns None if keyring not available."""
    try:
        import keyring  # type: ignore[import-untyped]

        return keyring.get_password("vne-cli", key)
    except (ImportError, Exception):
        return None


def require_credential(
    key: str,
    credentials_config: CredentialsConfig,
    provider_name: str = "",
) -> str:
    """Resolve a credential or raise with a helpful error message.

    Args:
        key: Credential key, e.g. "openai_api_key".
        credentials_config: Credentials section from loaded config.
        provider_name: Human-readable provider name for error messages.

    Raises:
        CredentialMissingError: If the credential cannot be resolved.
    """
    from vne_cli.providers.errors import CredentialMissingError

    value = resolve_credential(key, credentials_config)
    if value is None:
        env_key = f"{ENV_PREFIX}{key.upper()}"
        msg = (
            f"Missing credential '{key}'"
            + (f" for provider '{provider_name}'" if provider_name else "")
            + f". Set environment variable {env_key} or add it to ~/.vne-cli/config.toml"
        )
        raise CredentialMissingError(msg)
    return value
