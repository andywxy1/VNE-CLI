"""Provider registry: loading and instantiation.

Providers are loaded from config via importlib. The config specifies:
  - package: The Python package to import (must be pip-installed)
  - factory: The callable name within the package that creates the provider
  - Additional kwargs passed to the factory
"""

from __future__ import annotations

import importlib
from typing import Any

from vne_cli.config.schema import ProviderConfig
from vne_cli.providers.base import ImageProvider, LLMProvider
from vne_cli.providers.errors import ProviderNotFoundError


def load_llm_provider(config: ProviderConfig, **kwargs: Any) -> LLMProvider:
    """Load and instantiate an LLM provider from config.

    Args:
        config: Provider configuration with package and factory names.
        **kwargs: Additional kwargs passed to the factory function.

    Returns:
        An instantiated LLM provider.

    Raises:
        ProviderNotFoundError: If the package or factory cannot be found.
        TypeError: If the returned object doesn't satisfy LLMProvider protocol.
    """
    provider = _load_provider(config, **kwargs)
    if not isinstance(provider, LLMProvider):
        msg = (
            f"Provider from {config.package}.{config.factory} does not "
            f"satisfy the LLMProvider protocol."
        )
        raise TypeError(msg)
    return provider


def load_image_provider(config: ProviderConfig, **kwargs: Any) -> ImageProvider:
    """Load and instantiate an image provider from config.

    Args:
        config: Provider configuration with package and factory names.
        **kwargs: Additional kwargs passed to the factory function.

    Returns:
        An instantiated image provider.

    Raises:
        ProviderNotFoundError: If the package or factory cannot be found.
        TypeError: If the returned object doesn't satisfy ImageProvider protocol.
    """
    provider = _load_provider(config, **kwargs)
    if not isinstance(provider, ImageProvider):
        msg = (
            f"Provider from {config.package}.{config.factory} does not "
            f"satisfy the ImageProvider protocol."
        )
        raise TypeError(msg)
    return provider


def _load_provider(config: ProviderConfig, **kwargs: Any) -> Any:
    """Load a provider via importlib.

    Args:
        config: Provider configuration.
        **kwargs: Additional kwargs merged with config.extra.

    Returns:
        The instantiated provider object.
    """
    if not config.package:
        msg = (
            "No provider package configured. "
            "Set [providers.llm] or [providers.image] in your config file."
        )
        raise ProviderNotFoundError(msg)

    if not config.factory:
        msg = f"No factory function specified for provider package '{config.package}'."
        raise ProviderNotFoundError(msg)

    try:
        module = importlib.import_module(config.package)
    except ImportError as e:
        msg = (
            f"Cannot import provider package '{config.package}'. "
            f"Is it installed? Try: pip install {config.package}\n"
            f"Original error: {e}"
        )
        raise ProviderNotFoundError(msg) from e

    factory = getattr(module, config.factory, None)
    if factory is None:
        msg = (
            f"Factory function '{config.factory}' not found in "
            f"package '{config.package}'."
        )
        raise ProviderNotFoundError(msg)

    merged_kwargs = {**config.extra, **kwargs}
    if config.model:
        merged_kwargs.setdefault("model", config.model)

    return factory(**merged_kwargs)
