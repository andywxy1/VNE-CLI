"""Tests for config loading, schema, and layered merging."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from vne_cli.config.loader import (
    _deep_merge,
    _env_overrides,
    _load_toml,
    load_config,
    resolve_config_sources,
)
from vne_cli.config.schema import (
    CredentialsConfig,
    ProviderConfig,
    VneConfig,
)


# ---------------------------------------------------------------------------
# Schema defaults
# ---------------------------------------------------------------------------

class TestVneConfigDefaults:
    """Test that VneConfig has sensible defaults."""

    def test_default_construction(self) -> None:
        cfg = VneConfig()
        assert cfg.project.name == "Untitled Visual Novel"
        assert cfg.project.resolution == (1920, 1080)

    def test_extraction_defaults(self) -> None:
        cfg = VneConfig()
        assert cfg.extraction.max_chapters == 50
        assert cfg.extraction.max_branch_depth == 3
        assert cfg.extraction.max_choices_per_branch == 3
        assert cfg.extraction.chunking.target_tokens == 8000

    def test_assets_defaults(self) -> None:
        cfg = VneConfig()
        assert cfg.assets.style == "anime"
        assert cfg.assets.background_size == (1920, 1080)
        assert cfg.assets.sprite_size == (800, 1200)

    def test_cinematic_defaults(self) -> None:
        cfg = VneConfig()
        assert cfg.cinematic.enabled is True
        assert cfg.cinematic.tier == "full"

    def test_providers_empty_by_default(self) -> None:
        cfg = VneConfig()
        assert cfg.providers.llm.package == ""
        assert cfg.providers.image.package == ""


# ---------------------------------------------------------------------------
# ProviderConfig extra field collection
# ---------------------------------------------------------------------------

class TestProviderConfigExtra:
    """Test that unknown keys in ProviderConfig go to extra."""

    def test_known_fields_stored_directly(self) -> None:
        pc = ProviderConfig(package="my_pkg", factory="create", model="gpt-4o")
        assert pc.package == "my_pkg"
        assert pc.factory == "create"
        assert pc.model == "gpt-4o"
        assert pc.extra == {}

    def test_unknown_fields_go_to_extra(self) -> None:
        pc = ProviderConfig(
            package="my_pkg",
            factory="create",
            model="gpt-4o",
            timeout=60,
            temperature=0.5,
        )
        assert pc.extra["timeout"] == 60
        assert pc.extra["temperature"] == 0.5

    def test_explicit_extra_preserved(self) -> None:
        pc = ProviderConfig(
            package="p", factory="f", model="m",
            extra={"a": 1},
            b=2,
        )
        assert pc.extra == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# CredentialsConfig extra field collection
# ---------------------------------------------------------------------------

class TestCredentialsConfigExtra:
    """Test that credential keys are collected into extra."""

    def test_keys_go_to_extra(self) -> None:
        cc = CredentialsConfig(openai_api_key="sk-123", dalle_api_key="sk-456")
        assert cc.extra["openai_api_key"] == "sk-123"
        assert cc.extra["dalle_api_key"] == "sk-456"

    def test_empty_by_default(self) -> None:
        cc = CredentialsConfig()
        assert cc.extra == {}


# ---------------------------------------------------------------------------
# Deep merge
# ---------------------------------------------------------------------------

class TestDeepMerge:
    """Test recursive dictionary merging."""

    def test_simple_override(self) -> None:
        base = {"a": 1, "b": 2}
        override = {"b": 3}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3}

    def test_nested_merge(self) -> None:
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99, "z": 100}}
        result = _deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 99, "z": 100}, "b": 3}

    def test_override_adds_new_keys(self) -> None:
        base = {"a": 1}
        override = {"b": 2}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 2}

    def test_base_unmodified(self) -> None:
        base = {"a": {"x": 1}}
        override = {"a": {"x": 2}}
        _deep_merge(base, override)
        assert base["a"]["x"] == 1  # original not mutated

    def test_non_dict_overrides_dict(self) -> None:
        base = {"a": {"x": 1}}
        override = {"a": "replaced"}
        result = _deep_merge(base, override)
        assert result == {"a": "replaced"}


# ---------------------------------------------------------------------------
# Environment variable parsing
# ---------------------------------------------------------------------------

class TestEnvOverrides:
    """Test VNE_CLI_* environment variable parsing."""

    def test_single_key(self) -> None:
        with patch.dict(os.environ, {"VNE_CLI_EXTRACTION_LANGUAGE": "ja"}, clear=False):
            result = _env_overrides()
        assert result["extraction"]["language"] == "ja"

    def test_nested_key(self) -> None:
        with patch.dict(
            os.environ,
            {"VNE_CLI_PROVIDERS_LLM_MODEL": "gpt-4o"},
            clear=False,
        ):
            result = _env_overrides()
        assert result["providers"]["llm"]["model"] == "gpt-4o"

    def test_ignores_non_prefixed(self) -> None:
        with patch.dict(os.environ, {"HOME": "/test", "PATH": "/usr/bin"}, clear=False):
            result = _env_overrides()
        # Should not contain HOME or PATH
        assert "home" not in result
        assert "path" not in result


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------

class TestLoadToml:
    """Test TOML file loading."""

    def test_nonexistent_file_returns_empty(self, tmp_path: Path) -> None:
        result = _load_toml(tmp_path / "nope.toml")
        assert result == {}

    def test_valid_toml_loaded(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "test.toml"
        toml_file.write_text('[project]\nname = "Test"\n')
        result = _load_toml(toml_file)
        assert result == {"project": {"name": "Test"}}


# ---------------------------------------------------------------------------
# Layered config loading
# ---------------------------------------------------------------------------

class TestLoadConfig:
    """Test the full layered config loading pipeline."""

    def test_defaults_when_no_files(self, tmp_path: Path) -> None:
        """Config should return defaults when no config files exist."""
        with patch(
            "vne_cli.config.loader.USER_CONFIG_PATH",
            tmp_path / "nonexistent" / "config.toml",
        ):
            cfg = load_config(project_path=tmp_path / "nonexistent.toml")
        assert cfg.project.name == "Untitled Visual Novel"
        assert cfg.extraction.max_chapters == 50

    def test_project_config_overrides_defaults(self, tmp_path: Path) -> None:
        """Project config should override default values."""
        project_toml = tmp_path / "vne-cli.toml"
        project_toml.write_text(
            '[project]\nname = "Custom Project"\n'
            "[extraction]\nmax_chapters = 10\n"
        )
        with patch(
            "vne_cli.config.loader.USER_CONFIG_PATH",
            tmp_path / "nonexistent" / "config.toml",
        ):
            cfg = load_config(project_path=project_toml)
        assert cfg.project.name == "Custom Project"
        assert cfg.extraction.max_chapters == 10
        # Other defaults should still be present
        assert cfg.extraction.max_branch_depth == 3

    def test_user_config_provides_providers(self, tmp_path: Path) -> None:
        """User config should set provider values."""
        user_toml = tmp_path / "config.toml"
        user_toml.write_text(
            '[providers.llm]\n'
            'package = "vne_cli.providers.llm.openai_provider"\n'
            'factory = "create_llm_provider"\n'
            'model = "gpt-4o"\n'
        )
        with patch("vne_cli.config.loader.USER_CONFIG_PATH", user_toml):
            cfg = load_config(project_path=tmp_path / "nonexistent.toml")
        assert cfg.providers.llm.package == "vne_cli.providers.llm.openai_provider"
        assert cfg.providers.llm.model == "gpt-4o"

    def test_project_overrides_user(self, tmp_path: Path) -> None:
        """Project config should override user config for overlapping keys."""
        user_toml = tmp_path / "user.toml"
        user_toml.write_text('[extraction]\nmax_chapters = 100\nlanguage = "en"\n')

        project_toml = tmp_path / "project.toml"
        project_toml.write_text('[extraction]\nmax_chapters = 20\n')

        with patch("vne_cli.config.loader.USER_CONFIG_PATH", user_toml):
            cfg = load_config(project_path=project_toml)
        assert cfg.extraction.max_chapters == 20
        assert cfg.extraction.language == "en"  # from user config

    def test_env_overrides_project(self, tmp_path: Path) -> None:
        """Environment variables should override project config."""
        project_toml = tmp_path / "vne-cli.toml"
        project_toml.write_text("[extraction]\nmax_chapters = 20\n")

        with patch(
            "vne_cli.config.loader.USER_CONFIG_PATH",
            tmp_path / "nonexistent" / "config.toml",
        ), patch.dict(
            os.environ,
            {"VNE_CLI_EXTRACTION_MAX_CHAPTERS": "5"},
            clear=False,
        ):
            cfg = load_config(project_path=project_toml)
        # Note: env vars come in as strings, Pydantic coerces to int
        assert cfg.extraction.max_chapters == 5

    def test_credentials_stripped_from_project_config(self, tmp_path: Path) -> None:
        """Credentials in project config must be ignored (security rule)."""
        project_toml = tmp_path / "vne-cli.toml"
        project_toml.write_text(
            '[project]\nname = "Test"\n'
            "[credentials]\nopenai_api_key = \"sk-leaked\"\n"
        )
        with patch(
            "vne_cli.config.loader.USER_CONFIG_PATH",
            tmp_path / "nonexistent" / "config.toml",
        ):
            cfg = load_config(project_path=project_toml)
        # Credentials from project config should NOT appear
        assert cfg.credentials.extra.get("openai_api_key") is None

    def test_credentials_loaded_from_user_config(self, tmp_path: Path) -> None:
        """Credentials in user config should be loaded."""
        user_toml = tmp_path / "config.toml"
        user_toml.write_text('[credentials]\nopenai_api_key = "sk-secret"\n')

        with patch("vne_cli.config.loader.USER_CONFIG_PATH", user_toml):
            cfg = load_config(project_path=tmp_path / "nonexistent.toml")
        assert cfg.credentials.extra.get("openai_api_key") == "sk-secret"

    def test_provider_extra_kwargs_collected(self, tmp_path: Path) -> None:
        """Provider-specific kwargs should be collected into extra."""
        user_toml = tmp_path / "config.toml"
        user_toml.write_text(
            '[providers.llm]\n'
            'package = "my_pkg"\n'
            'factory = "create"\n'
            'model = "gpt-4o"\n'
            'timeout = 60\n'
        )
        with patch("vne_cli.config.loader.USER_CONFIG_PATH", user_toml):
            cfg = load_config(project_path=tmp_path / "nonexistent.toml")
        assert cfg.providers.llm.extra.get("timeout") == 60


# ---------------------------------------------------------------------------
# Config source resolution
# ---------------------------------------------------------------------------

class TestResolveConfigSources:
    """Test the resolve_config_sources function for --resolved output."""

    def test_defaults_are_labeled(self, tmp_path: Path) -> None:
        with patch(
            "vne_cli.config.loader.USER_CONFIG_PATH",
            tmp_path / "nonexistent" / "config.toml",
        ):
            sources = resolve_config_sources(
                project_path=tmp_path / "nonexistent.toml"
            )
        assert sources["project.name"] == ("Untitled Visual Novel", "default")

    def test_user_config_labeled(self, tmp_path: Path) -> None:
        user_toml = tmp_path / "config.toml"
        user_toml.write_text('[extraction]\nlanguage = "ja"\n')
        with patch("vne_cli.config.loader.USER_CONFIG_PATH", user_toml):
            sources = resolve_config_sources(
                project_path=tmp_path / "nonexistent.toml"
            )
        assert sources["extraction.language"] == ("ja", "user")

    def test_project_config_labeled(self, tmp_path: Path) -> None:
        project_toml = tmp_path / "vne-cli.toml"
        project_toml.write_text('[project]\nname = "My VN"\n')
        with patch(
            "vne_cli.config.loader.USER_CONFIG_PATH",
            tmp_path / "nonexistent" / "config.toml",
        ):
            sources = resolve_config_sources(project_path=project_toml)
        assert sources["project.name"] == ("My VN", "project")

    def test_env_labeled(self, tmp_path: Path) -> None:
        with patch(
            "vne_cli.config.loader.USER_CONFIG_PATH",
            tmp_path / "nonexistent" / "config.toml",
        ), patch.dict(
            os.environ,
            {"VNE_CLI_ASSETS_STYLE": "watercolor"},
            clear=False,
        ):
            sources = resolve_config_sources(
                project_path=tmp_path / "nonexistent.toml"
            )
        assert sources["assets.style"] == ("watercolor", "env")
