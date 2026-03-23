"""Stable Diffusion image provider implementation.

Implements the ImageProvider protocol using the Stability AI REST API
via httpx. Supports Stable Diffusion XL and SD3 models.

Usage via config:
    [providers.image]
    package = "vne_cli.providers.image.stable_diffusion_provider"
    factory = "create_image_provider"
    model = "stable-diffusion-xl-1024-v1-0"
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

STABILITY_API_BASE = "https://api.stability.ai"


def _clamp_dimensions(width: int, height: int) -> tuple[int, int]:
    """Clamp dimensions to multiples of 64 within Stability API limits.

    The Stability API requires dimensions to be multiples of 64, and
    within certain min/max bounds depending on the model.

    Args:
        width: Requested width.
        height: Requested height.

    Returns:
        A (width, height) tuple clamped to valid values.
    """
    w = max(512, min(width, 2048))
    h = max(512, min(height, 2048))
    # Round to nearest multiple of 64
    w = round(w / 64) * 64
    h = round(h / 64) * 64
    return w, h


class StableDiffusionImageProvider:
    """Image provider backed by the Stability AI REST API.

    This class satisfies the ``ImageProvider`` protocol defined in
    ``vne_cli.providers.base`` via structural subtyping.

    Attributes:
        _model: The Stable Diffusion engine identifier.
        _api_key: The Stability AI API key.
        _client: An ``httpx.AsyncClient`` for connection pooling.
        _cfg_scale: Classifier-free guidance scale (how closely to follow prompt).
        _steps: Number of diffusion steps.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = STABILITY_API_BASE,
        timeout: float = 180.0,
        cfg_scale: float = 7.0,
        steps: int = 30,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._cfg_scale = cfg_scale
        self._steps = steps
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(timeout),
        )

    @property
    def name(self) -> str:
        """Human-readable provider name."""
        return f"stability/{self._model}"

    async def generate(
        self,
        prompt: str,
        *,
        width: int = 1024,
        height: int = 1024,
        style: str | None = None,
        negative_prompt: str | None = None,
    ) -> bytes:
        """Generate an image via the Stability AI text-to-image endpoint.

        Args:
            prompt: The image generation prompt.
            width: Desired width (clamped to API limits, multiple of 64).
            height: Desired height (clamped to API limits, multiple of 64).
            style: Optional style modifier prepended to the prompt.
            negative_prompt: Things to avoid in the generated image.

        Returns:
            Raw PNG image bytes.

        Raises:
            ProviderAuthError: On 401/403 responses.
            ProviderRateLimitError: On 429 responses.
            ProviderResponseError: On other API errors.
        """
        clamped_w, clamped_h = _clamp_dimensions(width, height)

        effective_prompt = prompt
        if style:
            effective_prompt = f"{style} style. {effective_prompt}"

        text_prompts: list[dict[str, Any]] = [
            {"text": effective_prompt, "weight": 1.0},
        ]
        if negative_prompt:
            text_prompts.append({"text": negative_prompt, "weight": -1.0})

        payload: dict[str, Any] = {
            "text_prompts": text_prompts,
            "cfg_scale": self._cfg_scale,
            "width": clamped_w,
            "height": clamped_h,
            "steps": self._steps,
            "samples": 1,
        }

        endpoint = f"/v1/generation/{self._model}/text-to-image"

        logger.debug(
            "Generating image: model=%s size=%dx%d steps=%d cfg=%.1f",
            self._model,
            clamped_w,
            clamped_h,
            self._steps,
            self._cfg_scale,
        )

        response = await self._client.post(endpoint, json=payload)
        self._check_response(response)

        data = response.json()
        artifacts = data.get("artifacts", [])
        if not artifacts:
            raise ProviderResponseError(
                "Stability API returned no image artifacts."
            )

        b64_data = artifacts[0]["base64"]
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
            error_msg = body.get("message", response.text)
        except Exception:
            error_msg = response.text

        if status in (401, 403):
            raise ProviderAuthError(
                f"Stability AI authentication failed ({status}): {error_msg}"
            )
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            raise ProviderRateLimitError(
                f"Stability AI rate limit exceeded: {error_msg}",
                retry_after=float(retry_after) if retry_after else None,
            )
        raise ProviderResponseError(
            f"Stability AI API error ({status}): {error_msg}"
        )


def create_image_provider(
    *,
    model: str = "stable-diffusion-xl-1024-v1-0",
    api_key: str = "",
    base_url: str = STABILITY_API_BASE,
    timeout: float = 180.0,
    cfg_scale: float = 7.0,
    steps: int = 30,
    **_kwargs: Any,
) -> StableDiffusionImageProvider:
    """Factory function for creating a Stable Diffusion image provider.

    This is the entry point referenced in config TOML:
        [providers.image]
        package = "vne_cli.providers.image.stable_diffusion_provider"
        factory = "create_image_provider"
        model = "stable-diffusion-xl-1024-v1-0"

    Args:
        model: Stability AI engine identifier.
        api_key: Stability AI API key. Resolved via credentials system.
        base_url: API base URL.
        timeout: HTTP request timeout in seconds.
        cfg_scale: Classifier-free guidance scale (1.0 - 35.0).
        steps: Number of diffusion steps (10 - 150).

    Returns:
        A ``StableDiffusionImageProvider`` satisfying ``ImageProvider`` protocol.
    """
    if not api_key:
        raise ProviderAuthError(
            "Stability AI API key is required. Set VNE_CLI_STABILITY_API_KEY "
            "environment variable or configure it in ~/.vne-cli/config.toml [credentials]."
        )
    return StableDiffusionImageProvider(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        cfg_scale=cfg_scale,
        steps=steps,
    )
