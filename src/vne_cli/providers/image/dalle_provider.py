"""DALL-E image provider implementation.

Implements the ImageProvider protocol using the OpenAI Images API
via httpx. Supports DALL-E 2 and DALL-E 3.

Usage via config:
    [providers.image]
    package = "vne_cli.providers.image.dalle_provider"
    factory = "create_image_provider"
    model = "dall-e-3"
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from vne_cli.providers.errors import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponseError,
)

logger = logging.getLogger(__name__)

OPENAI_API_BASE = "https://api.openai.com/v1"

# DALL-E 3 supported sizes
DALLE3_SIZES = {"1024x1024", "1024x1792", "1792x1024"}
# DALL-E 2 supported sizes
DALLE2_SIZES = {"256x256", "512x512", "1024x1024"}


def _snap_to_supported_size(
    width: int, height: int, model: str
) -> str:
    """Map requested dimensions to the closest supported DALL-E size string.

    DALL-E does not support arbitrary sizes. This function picks the best
    match from the model's supported sizes based on aspect ratio.

    Args:
        width: Requested width in pixels.
        height: Requested height in pixels.
        model: The DALL-E model identifier.

    Returns:
        A size string like ``"1024x1024"``.
    """
    if model == "dall-e-3":
        aspect = width / height if height > 0 else 1.0
        if aspect > 1.3:
            return "1792x1024"  # landscape
        if aspect < 0.77:
            return "1024x1792"  # portrait
        return "1024x1024"  # square
    # DALL-E 2 default
    return "1024x1024"


class DallEImageProvider:
    """Image provider backed by the OpenAI Images API (DALL-E).

    This class satisfies the ``ImageProvider`` protocol defined in
    ``vne_cli.providers.base`` via structural subtyping.

    Attributes:
        _model: The DALL-E model identifier (``dall-e-2`` or ``dall-e-3``).
        _api_key: The OpenAI API key.
        _client: An ``httpx.AsyncClient`` for connection pooling.
        _quality: Image quality setting (``standard`` or ``hd``).
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = OPENAI_API_BASE,
        timeout: float = 180.0,
        quality: str = "standard",
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._quality = quality
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout),
        )

    @property
    def name(self) -> str:
        """Human-readable provider name."""
        return f"dalle/{self._model}"

    async def generate(
        self,
        prompt: str,
        *,
        width: int = 1024,
        height: int = 1024,
        style: str | None = None,
        negative_prompt: str | None = None,
    ) -> bytes:
        """Generate an image from a text prompt via the DALL-E API.

        Args:
            prompt: The image generation prompt.
            width: Desired width (snapped to nearest supported size).
            height: Desired height (snapped to nearest supported size).
            style: Optional style modifier. For DALL-E 3, can be ``vivid``
                   or ``natural``. Other values are prepended to the prompt.
            negative_prompt: Things to avoid. Prepended as guidance in the
                             prompt since DALL-E has no native negative prompt.

        Returns:
            Raw PNG image bytes.

        Raises:
            ProviderAuthError: On 401/403 responses.
            ProviderRateLimitError: On 429 responses.
            ProviderResponseError: On other API errors.
        """
        size = _snap_to_supported_size(width, height, self._model)

        # Build the effective prompt
        effective_prompt = prompt
        if style and style not in ("vivid", "natural"):
            effective_prompt = f"{style} style. {effective_prompt}"
        if negative_prompt:
            effective_prompt += f" Avoid: {negative_prompt}."

        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": effective_prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
        }

        # DALL-E 3 specific parameters
        if self._model == "dall-e-3":
            payload["quality"] = self._quality
            if style in ("vivid", "natural"):
                payload["style"] = style

        logger.debug(
            "Generating image: model=%s size=%s quality=%s",
            self._model,
            size,
            self._quality,
        )

        response = await self._client.post("/images/generations", json=payload)
        self._check_response(response)

        data = response.json()
        b64_data = data["data"][0]["b64_json"]
        return base64.b64decode(b64_data)

    async def close(self) -> None:
        """Close the underlying HTTP client and release connections."""
        await self._client.aclose()

    def _check_response(self, response: httpx.Response) -> None:
        """Raise provider-specific errors for non-2xx responses."""
        if response.is_success:
            return

        status = response.status_code
        try:
            body = response.json()
            error_msg = body.get("error", {}).get("message", response.text)
        except Exception:
            error_msg = response.text

        if status in (401, 403):
            raise ProviderAuthError(
                f"OpenAI authentication failed ({status}): {error_msg}"
            )
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            raise ProviderRateLimitError(
                f"DALL-E rate limit exceeded: {error_msg}",
                retry_after=float(retry_after) if retry_after else None,
            )
        raise ProviderResponseError(
            f"DALL-E API error ({status}): {error_msg}"
        )


def create_image_provider(
    *,
    model: str = "dall-e-3",
    api_key: str = "",
    base_url: str = OPENAI_API_BASE,
    timeout: float = 180.0,
    quality: str = "standard",
    **_kwargs: Any,
) -> DallEImageProvider:
    """Factory function for creating a DALL-E image provider.

    This is the entry point referenced in config TOML:
        [providers.image]
        package = "vne_cli.providers.image.dalle_provider"
        factory = "create_image_provider"
        model = "dall-e-3"

    Args:
        model: DALL-E model identifier (``dall-e-2`` or ``dall-e-3``).
        api_key: OpenAI API key. Resolved via credentials system.
        base_url: API base URL.
        timeout: HTTP request timeout in seconds.
        quality: Image quality (``standard`` or ``hd``).

    Returns:
        A ``DallEImageProvider`` instance satisfying the ``ImageProvider`` protocol.
    """
    if not api_key:
        raise ProviderAuthError(
            "OpenAI API key is required for DALL-E. Set VNE_CLI_OPENAI_API_KEY "
            "environment variable or configure it in ~/.vne-cli/config.toml [credentials]."
        )
    return DallEImageProvider(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        quality=quality,
    )
