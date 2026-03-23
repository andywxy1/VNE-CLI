"""OpenAI LLM provider implementation.

Implements the LLMProvider protocol using the OpenAI Chat Completions API
via httpx. Supports both free-form and structured (JSON mode) completions.

Usage via config:
    [providers.llm]
    package = "vne_cli.providers.llm.openai_provider"
    factory = "create_llm_provider"
    model = "gpt-4o"
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

OPENAI_API_BASE = "https://api.openai.com/v1"


class OpenAILLMProvider:
    """LLM provider backed by the OpenAI Chat Completions API.

    This class satisfies the ``LLMProvider`` protocol defined in
    ``vne_cli.providers.base`` via structural subtyping -- it does not
    need to inherit from or import the protocol.

    Attributes:
        _model: The OpenAI model identifier (e.g. ``gpt-4o``).
        _api_key: The API key for authentication.
        _client: An ``httpx.AsyncClient`` for connection pooling.
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = OPENAI_API_BASE,
        timeout: float = 120.0,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
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
        return f"openai/{self._model}"

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Send a chat completion request to OpenAI.

        Args:
            prompt: The user message content.
            system: Optional system message.
            temperature: Sampling temperature (0.0 - 2.0).
            max_tokens: Maximum tokens in the response.
            response_format: Optional format hint, e.g. ``{"type": "json_object"}``.

        Returns:
            The assistant's text response.

        Raises:
            ProviderAuthError: On 401/403 responses.
            ProviderRateLimitError: On 429 responses.
            ProviderResponseError: On other API errors.
        """
        messages: list[dict[str, str]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        response = await self._client.post("/chat/completions", json=payload)
        self._check_response(response)

        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def complete_structured(
        self,
        prompt: str,
        schema: type,
        *,
        system: str | None = None,
        temperature: float = 0.3,
    ) -> Any:
        """Request a structured completion matching a Pydantic model.

        Uses OpenAI's JSON mode to ensure the response is valid JSON, then
        validates and parses it against the provided Pydantic schema.

        Args:
            prompt: The user message, which should describe the desired output.
            schema: A Pydantic model class defining the expected shape.
            system: Optional system message.
            temperature: Sampling temperature (lower is more deterministic).

        Returns:
            A validated instance of ``schema``.
        """
        schema_json = schema.model_json_schema()  # type: ignore[attr-defined]
        augmented_prompt = (
            f"{prompt}\n\n"
            f"Respond with JSON matching this schema:\n"
            f"```json\n{json.dumps(schema_json, indent=2)}\n```"
        )

        raw = await self.complete(
            augmented_prompt,
            system=system,
            temperature=temperature,
            response_format={"type": "json_object"},
        )

        parsed = json.loads(raw)
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
                f"OpenAI authentication failed ({status}): {error_msg}"
            )
        if status == 429:
            retry_after = response.headers.get("Retry-After")
            raise ProviderRateLimitError(
                f"OpenAI rate limit exceeded: {error_msg}",
                retry_after=float(retry_after) if retry_after else None,
            )
        raise ProviderResponseError(
            f"OpenAI API error ({status}): {error_msg}"
        )


def create_llm_provider(
    *,
    model: str = "gpt-4o",
    api_key: str = "",
    base_url: str = OPENAI_API_BASE,
    timeout: float = 120.0,
    **_kwargs: Any,
) -> OpenAILLMProvider:
    """Factory function for creating an OpenAI LLM provider.

    This is the entry point referenced in config TOML:
        [providers.llm]
        package = "vne_cli.providers.llm.openai_provider"
        factory = "create_llm_provider"
        model = "gpt-4o"

    Args:
        model: OpenAI model identifier.
        api_key: API key. Should be resolved via credentials, not hardcoded.
        base_url: API base URL (override for proxies or compatible APIs).
        timeout: HTTP request timeout in seconds.

    Returns:
        An ``OpenAILLMProvider`` instance satisfying the ``LLMProvider`` protocol.
    """
    if not api_key:
        raise ProviderAuthError(
            "OpenAI API key is required. Set VNE_CLI_OPENAI_API_KEY environment "
            "variable or configure it in ~/.vne-cli/config.toml [credentials]."
        )
    return OpenAILLMProvider(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
    )
