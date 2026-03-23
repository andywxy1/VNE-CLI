"""Anthropic LLM provider implementation.

Implements the LLMProvider protocol using the Anthropic Messages API
via httpx. Supports both free-form and structured completions.

Usage via config:
    [providers.llm]
    package = "vne_cli.providers.llm.anthropic_provider"
    factory = "create_llm_provider"
    model = "claude-sonnet-4-20250514"
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from vne_cli.providers.errors import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderResponseError,
)

logger = logging.getLogger(__name__)

ANTHROPIC_API_BASE = "https://api.anthropic.com"
ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicLLMProvider:
    """LLM provider backed by the Anthropic Messages API.

    This class satisfies the ``LLMProvider`` protocol defined in
    ``vne_cli.providers.base`` via structural subtyping.

    Attributes:
        _model: The Anthropic model identifier (e.g. ``claude-sonnet-4-20250514``).
        _api_key: The API key for authentication.
        _client: An ``httpx.AsyncClient`` for connection pooling.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = ANTHROPIC_API_BASE,
        timeout: float = 120.0,
        max_tokens_default: int = 4096,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_tokens_default = max_tokens_default
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout),
        )

    @property
    def name(self) -> str:
        """Human-readable provider name."""
        return f"anthropic/{self._model}"

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Send a messages request to the Anthropic API.

        Args:
            prompt: The user message content.
            system: Optional system prompt.
            temperature: Sampling temperature (0.0 - 1.0 for Anthropic).
            max_tokens: Maximum tokens in the response.
            response_format: Ignored for Anthropic (included for protocol compat).

        Returns:
            The assistant's text response.

        Raises:
            ProviderAuthError: On 401/403 responses.
            ProviderRateLimitError: On 429 responses.
            ProviderResponseError: On other API errors.
        """
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system is not None:
            payload["system"] = system

        response = await self._client.post("/v1/messages", json=payload)
        self._check_response(response)

        data = response.json()
        # Anthropic returns content as a list of blocks
        content_blocks = data.get("content", [])
        text_parts = [
            block["text"] for block in content_blocks if block.get("type") == "text"
        ]
        return "".join(text_parts)

    async def complete_structured(
        self,
        prompt: str,
        schema: type,
        *,
        system: str | None = None,
        temperature: float = 0.3,
    ) -> Any:
        """Request a structured completion matching a Pydantic model.

        Instructs the model to respond with JSON matching the provided schema,
        then validates the response.

        Args:
            prompt: The user message describing the desired output.
            schema: A Pydantic model class defining the expected shape.
            system: Optional system prompt.
            temperature: Sampling temperature.

        Returns:
            A validated instance of ``schema``.
        """
        schema_json = schema.model_json_schema()  # type: ignore[attr-defined]
        augmented_system = (
            (system or "")
            + "\n\nYou must respond with valid JSON matching this schema. "
            "Do not include any text outside the JSON object.\n"
            f"Schema:\n```json\n{json.dumps(schema_json, indent=2)}\n```"
        ).strip()

        raw = await self.complete(
            prompt,
            system=augmented_system,
            temperature=temperature,
        )

        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (fences)
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            text = "\n".join(lines)

        parsed = json.loads(text)
        return schema.model_validate(parsed)  # type: ignore[attr-defined]

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
                f"Anthropic authentication failed ({status}): {error_msg}"
            )
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            raise ProviderRateLimitError(
                f"Anthropic rate limit exceeded: {error_msg}",
                retry_after=float(retry_after) if retry_after else None,
            )
        raise ProviderResponseError(
            f"Anthropic API error ({status}): {error_msg}"
        )


def create_llm_provider(
    *,
    model: str = "claude-sonnet-4-20250514",
    api_key: str = "",
    base_url: str = ANTHROPIC_API_BASE,
    timeout: float = 120.0,
    **_kwargs: Any,
) -> AnthropicLLMProvider:
    """Factory function for creating an Anthropic LLM provider.

    This is the entry point referenced in config TOML:
        [providers.llm]
        package = "vne_cli.providers.llm.anthropic_provider"
        factory = "create_llm_provider"
        model = "claude-sonnet-4-20250514"

    Args:
        model: Anthropic model identifier.
        api_key: API key. Should be resolved via credentials, not hardcoded.
        base_url: API base URL.
        timeout: HTTP request timeout in seconds.

    Returns:
        An ``AnthropicLLMProvider`` instance satisfying the ``LLMProvider`` protocol.
    """
    if not api_key:
        raise ProviderAuthError(
            "Anthropic API key is required. Set VNE_CLI_ANTHROPIC_API_KEY environment "
            "variable or configure it in ~/.vne-cli/config.toml [credentials]."
        )
    return AnthropicLLMProvider(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
    )
