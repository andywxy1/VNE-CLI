"""Tests for credential resolution."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from vne_cli.config.schema import CredentialsConfig
from vne_cli.config.credentials import resolve_credential, require_credential
from vne_cli.providers.errors import CredentialMissingError


class TestResolveCredential:
    """Test credential resolution from multiple sources."""

    def test_returns_none_when_not_found(self) -> None:
        creds = CredentialsConfig()
        result = resolve_credential("nonexistent_key", creds)
        assert result is None

    def test_resolves_from_env_var(self) -> None:
        creds = CredentialsConfig()
        with patch.dict(os.environ, {"VNE_CLI_OPENAI_API_KEY": "sk-from-env"}):
            result = resolve_credential("openai_api_key", creds)
        assert result == "sk-from-env"

    def test_resolves_from_config(self) -> None:
        creds = CredentialsConfig(extra={"openai_api_key": "sk-from-config"})
        result = resolve_credential("openai_api_key", creds)
        assert result == "sk-from-config"

    def test_env_var_takes_precedence_over_config(self) -> None:
        creds = CredentialsConfig(extra={"openai_api_key": "sk-from-config"})
        with patch.dict(os.environ, {"VNE_CLI_OPENAI_API_KEY": "sk-from-env"}):
            result = resolve_credential("openai_api_key", creds)
        assert result == "sk-from-env"

    def test_empty_env_var_falls_through(self) -> None:
        """An empty env var should not be treated as a value."""
        creds = CredentialsConfig(extra={"openai_api_key": "sk-from-config"})
        with patch.dict(os.environ, {"VNE_CLI_OPENAI_API_KEY": ""}):
            result = resolve_credential("openai_api_key", creds)
        assert result == "sk-from-config"


class TestRequireCredential:
    """Test require_credential raises appropriately."""

    def test_returns_value_when_found(self) -> None:
        creds = CredentialsConfig(extra={"my_key": "my_value"})
        result = require_credential("my_key", creds, provider_name="test")
        assert result == "my_value"

    def test_raises_when_missing(self) -> None:
        creds = CredentialsConfig()
        with pytest.raises(CredentialMissingError, match="Missing credential 'my_key'"):
            require_credential("my_key", creds)

    def test_error_includes_provider_name(self) -> None:
        creds = CredentialsConfig()
        with pytest.raises(CredentialMissingError, match="provider 'OpenAI'"):
            require_credential("api_key", creds, provider_name="OpenAI")

    def test_error_includes_env_var_hint(self) -> None:
        creds = CredentialsConfig()
        with pytest.raises(CredentialMissingError, match="VNE_CLI_OPENAI_API_KEY"):
            require_credential("openai_api_key", creds)
