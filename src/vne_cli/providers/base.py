"""Protocol definitions for pluggable providers.

Providers are external packages that implement these protocols. VNE-CLI
uses structural subtyping (typing.Protocol) so provider packages do not
need to import from vne_cli — they only need to match the interface.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Provider for large language model completions.

    Implementations must support both free-form text completion and
    structured output (returning validated Pydantic model instances).
    """

    @property
    def name(self) -> str:
        """Human-readable provider name."""
        ...

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Send a completion request.

        Args:
            prompt: The user prompt.
            system: Optional system prompt.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in response.
            response_format: Optional format hint (e.g. {"type": "json_object"}).

        Returns:
            The text response from the model.
        """
        ...

    async def complete_structured(
        self,
        prompt: str,
        schema: type,
        *,
        system: str | None = None,
        temperature: float = 0.3,
    ) -> Any:
        """Send a completion request expecting structured output.

        Args:
            prompt: The user prompt.
            schema: A Pydantic model class that defines the expected response shape.
            system: Optional system prompt.
            temperature: Sampling temperature (lower for structured output).

        Returns:
            A validated instance of the provided schema type.
        """
        ...

    async def close(self) -> None:
        """Release any held resources (HTTP connections, etc)."""
        ...


@runtime_checkable
class ImageProvider(Protocol):
    """Provider for image generation.

    Implementations handle API communication, rate limiting, and returning
    raw image bytes.
    """

    @property
    def name(self) -> str:
        """Human-readable provider name."""
        ...

    async def generate(
        self,
        prompt: str,
        *,
        width: int = 1024,
        height: int = 1024,
        style: str | None = None,
        negative_prompt: str | None = None,
    ) -> bytes:
        """Generate an image from a text prompt.

        Args:
            prompt: Image generation prompt.
            width: Desired image width in pixels.
            height: Desired image height in pixels.
            style: Optional style modifier.
            negative_prompt: Optional negative prompt (things to avoid).

        Returns:
            Raw image bytes (PNG format preferred).
        """
        ...

    async def close(self) -> None:
        """Release any held resources."""
        ...
