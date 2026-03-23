"""Tests for provider protocols, registry, and built-in stubs."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from vne_cli.providers.base import ImageProvider, LLMProvider
from vne_cli.providers.errors import (
    ProviderAuthError,
    ProviderNotFoundError,
)
from vne_cli.providers.image.dalle_provider import DallEImageProvider, create_image_provider
from vne_cli.providers.image.stable_diffusion_provider import (
    StableDiffusionImageProvider,
    create_image_provider as create_sd_provider,
)
from vne_cli.providers.llm.anthropic_provider import (
    AnthropicLLMProvider,
    create_llm_provider as create_anthropic_provider,
)
from vne_cli.providers.llm.openai_provider import (
    OpenAILLMProvider,
    create_llm_provider as create_openai_provider,
)
from vne_cli.providers.registry import _load_provider, load_image_provider, load_llm_provider
from vne_cli.config.schema import ProviderConfig


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------

class TestProtocolCompliance:
    """Verify that all built-in providers satisfy their respective protocols."""

    def test_openai_satisfies_llm_protocol(self) -> None:
        provider = OpenAILLMProvider(model="gpt-4o", api_key="test-key")
        assert isinstance(provider, LLMProvider)

    def test_anthropic_satisfies_llm_protocol(self) -> None:
        provider = AnthropicLLMProvider(
            model="claude-sonnet-4-20250514", api_key="test-key"
        )
        assert isinstance(provider, LLMProvider)

    def test_dalle_satisfies_image_protocol(self) -> None:
        provider = DallEImageProvider(model="dall-e-3", api_key="test-key")
        assert isinstance(provider, ImageProvider)

    def test_sd_satisfies_image_protocol(self) -> None:
        provider = StableDiffusionImageProvider(
            model="stable-diffusion-xl-1024-v1-0", api_key="test-key"
        )
        assert isinstance(provider, ImageProvider)


# ---------------------------------------------------------------------------
# Provider name property
# ---------------------------------------------------------------------------

class TestProviderNames:
    """Verify that provider name properties return expected values."""

    def test_openai_name(self) -> None:
        p = OpenAILLMProvider(model="gpt-4o", api_key="k")
        assert p.name == "openai/gpt-4o"

    def test_anthropic_name(self) -> None:
        p = AnthropicLLMProvider(model="claude-sonnet-4-20250514", api_key="k")
        assert p.name == "anthropic/claude-sonnet-4-20250514"

    def test_dalle_name(self) -> None:
        p = DallEImageProvider(model="dall-e-3", api_key="k")
        assert p.name == "dalle/dall-e-3"

    def test_sd_name(self) -> None:
        p = StableDiffusionImageProvider(
            model="stable-diffusion-xl-1024-v1-0", api_key="k"
        )
        assert p.name == "stability/stable-diffusion-xl-1024-v1-0"


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

class TestFactoryFunctions:
    """Test provider factory functions."""

    def test_openai_factory_requires_api_key(self) -> None:
        with pytest.raises(ProviderAuthError, match="API key is required"):
            create_openai_provider(model="gpt-4o", api_key="")

    def test_openai_factory_creates_provider(self) -> None:
        p = create_openai_provider(model="gpt-4o", api_key="sk-test")
        assert isinstance(p, OpenAILLMProvider)
        assert isinstance(p, LLMProvider)

    def test_anthropic_factory_requires_api_key(self) -> None:
        with pytest.raises(ProviderAuthError, match="API key is required"):
            create_anthropic_provider(model="claude-sonnet-4-20250514", api_key="")

    def test_anthropic_factory_creates_provider(self) -> None:
        p = create_anthropic_provider(
            model="claude-sonnet-4-20250514", api_key="sk-ant-test"
        )
        assert isinstance(p, AnthropicLLMProvider)
        assert isinstance(p, LLMProvider)

    def test_dalle_factory_requires_api_key(self) -> None:
        with pytest.raises(ProviderAuthError, match="API key is required"):
            create_image_provider(model="dall-e-3", api_key="")

    def test_dalle_factory_creates_provider(self) -> None:
        p = create_image_provider(model="dall-e-3", api_key="sk-test")
        assert isinstance(p, DallEImageProvider)
        assert isinstance(p, ImageProvider)

    def test_sd_factory_requires_api_key(self) -> None:
        with pytest.raises(ProviderAuthError, match="API key is required"):
            create_sd_provider(model="stable-diffusion-xl-1024-v1-0", api_key="")

    def test_sd_factory_creates_provider(self) -> None:
        p = create_sd_provider(
            model="stable-diffusion-xl-1024-v1-0", api_key="sk-test"
        )
        assert isinstance(p, StableDiffusionImageProvider)
        assert isinstance(p, ImageProvider)

    def test_factory_ignores_unknown_kwargs(self) -> None:
        """Factory functions should accept and ignore extra kwargs."""
        p = create_openai_provider(
            model="gpt-4o", api_key="sk-test", unknown_param="foo"
        )
        assert p.name == "openai/gpt-4o"


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------

class TestRegistryLoading:
    """Test the provider registry's importlib-based loading."""

    def test_load_provider_missing_package(self) -> None:
        config = ProviderConfig(package="", factory="create")
        with pytest.raises(ProviderNotFoundError, match="No provider package"):
            _load_provider(config)

    def test_load_provider_missing_factory(self) -> None:
        config = ProviderConfig(package="os", factory="")
        with pytest.raises(ProviderNotFoundError, match="No factory function"):
            _load_provider(config)

    def test_load_provider_package_not_installed(self) -> None:
        config = ProviderConfig(
            package="vne_cli_nonexistent_package_xyz", factory="create"
        )
        with pytest.raises(ProviderNotFoundError, match="Cannot import"):
            _load_provider(config)

    def test_load_provider_factory_not_found(self) -> None:
        config = ProviderConfig(
            package="os", factory="nonexistent_function_xyz"
        )
        with pytest.raises(ProviderNotFoundError, match="not found in"):
            _load_provider(config)

    def test_load_llm_provider_real_package(self) -> None:
        """Load the built-in OpenAI provider via registry."""
        config = ProviderConfig(
            package="vne_cli.providers.llm.openai_provider",
            factory="create_llm_provider",
            model="gpt-4o",
        )
        provider = load_llm_provider(config, api_key="sk-test")
        assert isinstance(provider, LLMProvider)
        assert provider.name == "openai/gpt-4o"

    def test_load_image_provider_real_package(self) -> None:
        """Load the built-in DALL-E provider via registry."""
        config = ProviderConfig(
            package="vne_cli.providers.image.dalle_provider",
            factory="create_image_provider",
            model="dall-e-3",
        )
        provider = load_image_provider(config, api_key="sk-test")
        assert isinstance(provider, ImageProvider)
        assert provider.name == "dalle/dall-e-3"

    def test_load_llm_provider_protocol_check(self) -> None:
        """Registry should reject objects that don't satisfy LLMProvider."""
        # builtins.dict() returns {} which is not an LLMProvider
        config = ProviderConfig(
            package="builtins",
            factory="dict",
            model="",
        )
        with pytest.raises(TypeError, match="does not satisfy the LLMProvider"):
            load_llm_provider(config)

    def test_load_image_provider_protocol_check(self) -> None:
        """Registry should reject objects that don't satisfy ImageProvider."""
        config = ProviderConfig(
            package="builtins",
            factory="dict",
            model="",
        )
        with pytest.raises(TypeError, match="does not satisfy the ImageProvider"):
            load_image_provider(config)

    def test_load_provider_passes_extra_kwargs(self) -> None:
        """Extra config kwargs should be forwarded to the factory."""
        config = ProviderConfig(
            package="vne_cli.providers.llm.openai_provider",
            factory="create_llm_provider",
            model="gpt-4o",
            extra={"timeout": 60.0},
        )
        provider = load_llm_provider(config, api_key="sk-test")
        # The provider should have been created successfully with the extra kwarg
        assert isinstance(provider, LLMProvider)


# ---------------------------------------------------------------------------
# DALL-E size snapping
# ---------------------------------------------------------------------------

class TestDalleSizeSnapping:
    """Test the DALL-E size snapping logic."""

    def test_square_snaps_to_1024(self) -> None:
        from vne_cli.providers.image.dalle_provider import _snap_to_supported_size

        assert _snap_to_supported_size(1024, 1024, "dall-e-3") == "1024x1024"

    def test_landscape_snaps_to_1792x1024(self) -> None:
        from vne_cli.providers.image.dalle_provider import _snap_to_supported_size

        assert _snap_to_supported_size(1920, 1080, "dall-e-3") == "1792x1024"

    def test_portrait_snaps_to_1024x1792(self) -> None:
        from vne_cli.providers.image.dalle_provider import _snap_to_supported_size

        assert _snap_to_supported_size(800, 1200, "dall-e-3") == "1024x1792"

    def test_dalle2_always_1024(self) -> None:
        from vne_cli.providers.image.dalle_provider import _snap_to_supported_size

        assert _snap_to_supported_size(1920, 1080, "dall-e-2") == "1024x1024"


# ---------------------------------------------------------------------------
# SD dimension clamping
# ---------------------------------------------------------------------------

class TestSDDimensionClamping:
    """Test Stable Diffusion dimension clamping logic."""

    def test_clamps_to_multiples_of_64(self) -> None:
        from vne_cli.providers.image.stable_diffusion_provider import _clamp_dimensions

        w, h = _clamp_dimensions(1000, 1000)
        assert w % 64 == 0
        assert h % 64 == 0

    def test_clamps_minimum(self) -> None:
        from vne_cli.providers.image.stable_diffusion_provider import _clamp_dimensions

        w, h = _clamp_dimensions(100, 100)
        assert w >= 512
        assert h >= 512

    def test_clamps_maximum(self) -> None:
        from vne_cli.providers.image.stable_diffusion_provider import _clamp_dimensions

        w, h = _clamp_dimensions(5000, 5000)
        assert w <= 2048
        assert h <= 2048

    def test_normal_dimensions_unchanged(self) -> None:
        from vne_cli.providers.image.stable_diffusion_provider import _clamp_dimensions

        w, h = _clamp_dimensions(1024, 1024)
        assert (w, h) == (1024, 1024)
