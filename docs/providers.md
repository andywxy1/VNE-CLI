# Provider Guide

VNE-CLI uses a plugin system for LLM and image generation backends. You can use the built-in providers (OpenAI, Anthropic, DALL-E, Stable Diffusion) or write your own.

## How the Plugin System Works

Providers are standard Python packages that implement a known interface. VNE-CLI uses `typing.Protocol` for structural subtyping -- your provider class does not need to import from or inherit anything in `vne-cli`. It only needs to have methods with matching signatures.

The loading process works like this:

1. You specify a provider in your config TOML (package name + factory function name)
2. VNE-CLI calls `importlib.import_module(package)` to load your package
3. It calls the factory function with any extra config keys as keyword arguments
4. It verifies the returned object satisfies the `LLMProvider` or `ImageProvider` protocol via `isinstance()` (enabled by `@runtime_checkable`)
5. If the check passes, the provider is ready to use

## Built-in Providers

### OpenAI LLM Provider

Uses the OpenAI Chat Completions API.

**Package**: `vne_cli_openai` (built into `src/vne_cli/providers/llm/openai_provider.py`)

**Config**:

```toml
[providers.llm]
package = "vne_cli.providers.llm.openai_provider"
factory = "create_llm_provider"
model = "gpt-4o"
```

**Credential**: Set `VNE_CLI_OPENAI_API_KEY` as an environment variable or add `openai_api_key` under `[credentials]` in your user config.

**Features**:

- Free-form text completion via `/chat/completions`
- Structured output via JSON mode + Pydantic validation
- Connection pooling via `httpx.AsyncClient`
- Error mapping: HTTP 401/403 to `ProviderAuthError`, HTTP 429 to `ProviderRateLimitError`

### Anthropic LLM Provider

Uses the Anthropic Messages API.

**Package**: `vne_cli_anthropic` (built into `src/vne_cli/providers/llm/anthropic_provider.py`)

**Config**:

```toml
[providers.llm]
package = "vne_cli.providers.llm.anthropic_provider"
factory = "create_llm_provider"
model = "claude-sonnet-4-20250514"
```

**Credential**: Set `VNE_CLI_ANTHROPIC_API_KEY` as an environment variable.

**Features**:

- Uses `/v1/messages` with `x-api-key` authentication
- Handles Anthropic's content block response format
- Structured output via schema injection into system prompt with markdown fence stripping

### DALL-E Image Provider

Uses the OpenAI Images API.

**Package**: `vne_cli_dalle` (built into `src/vne_cli/providers/image/dalle_provider.py`)

**Config**:

```toml
[providers.image]
package = "vne_cli.providers.image.dalle_provider"
factory = "create_image_provider"
model = "dall-e-3"
```

**Credential**: Set `VNE_CLI_OPENAI_API_KEY` or `VNE_CLI_DALLE_API_KEY` as an environment variable.

**Features**:

- Supports DALL-E 2 and DALL-E 3
- Automatic size snapping to DALL-E supported dimensions (1024x1024, 1024x1792, 1792x1024) based on aspect ratio
- Base64 response format for reliable binary transfer
- Quality and style parameters for DALL-E 3

### Stable Diffusion Image Provider

Uses the Stability AI REST API.

**Package**: `vne_cli_sd` (built into `src/vne_cli/providers/image/stable_diffusion_provider.py`)

**Config**:

```toml
[providers.image]
package = "vne_cli.providers.image.stable_diffusion_provider"
factory = "create_image_provider"
model = "stable-diffusion-xl-1024-v1-0"
```

**Credential**: Set `VNE_CLI_STABILITY_API_KEY` as an environment variable.

**Features**:

- Uses `/v1/generation/{engine}/text-to-image` endpoint
- Automatic dimension clamping to multiples of 64, within 512-2048 range
- Supports `cfg_scale`, `steps`, and negative prompts via weighted text prompts

## Setting Up Each Provider

### Step 1: Install Dependencies

The built-in providers use `httpx` for HTTP requests, which is already a dependency of VNE-CLI. No additional packages are needed.

### Step 2: Get an API Key

| Provider | Where to Get a Key |
|---|---|
| OpenAI (GPT + DALL-E) | https://platform.openai.com/api-keys |
| Anthropic (Claude) | https://console.anthropic.com/settings/keys |
| Stability AI (Stable Diffusion) | https://platform.stability.ai/account/keys |

### Step 3: Set Environment Variables

```bash
# For OpenAI LLM + DALL-E
export VNE_CLI_OPENAI_API_KEY="sk-..."

# For Anthropic
export VNE_CLI_ANTHROPIC_API_KEY="sk-ant-..."

# For Stability AI
export VNE_CLI_STABILITY_API_KEY="sk-..."
```

Alternatively, add keys to `~/.vne-cli/config.toml` under `[credentials]`:

```toml
[credentials]
openai_api_key = "sk-..."
anthropic_api_key = "sk-ant-..."
stability_api_key = "sk-..."
```

Credentials are never read from project-level config (`./vne-cli.toml`). This is enforced by the config loader.

### Step 4: Configure in TOML

```toml
# ~/.vne-cli/config.toml

[providers.llm]
package = "vne_cli.providers.llm.openai_provider"
factory = "create_llm_provider"
model = "gpt-4o"

[providers.image]
package = "vne_cli.providers.image.dalle_provider"
factory = "create_image_provider"
model = "dall-e-3"
```

### Step 5: Verify

```bash
vne config show --resolved
```

Look for your provider settings in the output.

## Writing a Custom Provider

### LLM Provider Example

Create a Python file or package with a class that matches the `LLMProvider` protocol and a factory function:

```python
"""my_llm_provider.py -- Custom LLM provider for VNE-CLI."""

import json
import httpx


class MyLLMProvider:
    """LLM provider using a custom API."""

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.example.com"):
        self._api_key = api_key
        self._model = model
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120.0,
        )

    @property
    def name(self) -> str:
        return f"my-provider/{self._model}"

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str:
        """Send a completion request. Returns the text response."""
        payload = {
            "model": self._model,
            "prompt": prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system:
            payload["system"] = system

        response = await self._client.post("/v1/completions", json=payload)
        response.raise_for_status()
        return response.json()["text"]

    async def complete_structured(
        self,
        prompt: str,
        schema: type,
        *,
        system: str | None = None,
        temperature: float = 0.3,
    ):
        """Send a completion request expecting structured output.

        Returns a validated instance of the provided Pydantic model.
        """
        # Inject schema into the prompt
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        full_system = (system or "") + f"\n\nRespond with JSON matching this schema:\n{schema_json}"

        raw = await self.complete(
            prompt,
            system=full_system,
            temperature=temperature,
            response_format={"type": "json_object"},
        )

        # Parse and validate against the Pydantic model
        return schema.model_validate_json(raw)

    async def close(self) -> None:
        """Release HTTP client resources."""
        await self._client.aclose()


def create_llm_provider(*, api_key: str, model: str = "default", **kwargs):
    """Factory function called by VNE-CLI's provider registry.

    Args:
        api_key: API key for authentication.
        model: Model identifier.
        **kwargs: Additional config keys from TOML are passed here.
    """
    if not api_key:
        from vne_cli.providers.errors import ProviderAuthError
        raise ProviderAuthError("my-provider", "API key is required")
    return MyLLMProvider(api_key=api_key, model=model, **kwargs)
```

### Image Provider Example

```python
"""my_image_provider.py -- Custom image provider for VNE-CLI."""

import httpx


class MyImageProvider:
    """Image provider using a custom generation API."""

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model
        self._client = httpx.AsyncClient(
            base_url="https://api.example.com",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=300.0,
        )

    @property
    def name(self) -> str:
        return f"my-image-provider/{self._model}"

    async def generate(
        self,
        prompt: str,
        *,
        width: int = 1024,
        height: int = 1024,
        style: str | None = None,
        negative_prompt: str | None = None,
    ) -> bytes:
        """Generate an image. Returns raw PNG bytes."""
        payload = {
            "model": self._model,
            "prompt": prompt,
            "width": width,
            "height": height,
        }
        if style:
            payload["style"] = style
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        response = await self._client.post("/v1/images/generate", json=payload)
        response.raise_for_status()

        # Return raw image bytes
        image_url = response.json()["image_url"]
        image_response = await self._client.get(image_url)
        return image_response.content

    async def close(self) -> None:
        await self._client.aclose()


def create_image_provider(*, api_key: str, model: str = "default", **kwargs):
    """Factory function for VNE-CLI provider registry."""
    if not api_key:
        from vne_cli.providers.errors import ProviderAuthError
        raise ProviderAuthError("my-image-provider", "API key is required")
    return MyImageProvider(api_key=api_key, model=model)
```

### Registering Your Provider

Add to your `~/.vne-cli/config.toml`:

```toml
[providers.llm]
package = "my_llm_provider"          # Python module/package name (importable)
factory = "create_llm_provider"      # Factory function name in that module
model = "my-model-v2"                # Passed as kwarg to factory
base_url = "https://my-api.com"      # Any extra keys are passed as **kwargs
```

The `package` value must be importable via `importlib.import_module()`. This means either:

- A Python file on your `PYTHONPATH` (e.g., `my_llm_provider.py`)
- An installed package (e.g., `pip install my-llm-provider` that provides `my_llm_provider`)
- A built-in provider path (e.g., `vne_cli.providers.llm.openai_provider`)

Any TOML keys beyond `package` and `factory` are collected and passed as keyword arguments to the factory function.

## Provider Protocol Reference

### LLMProvider

```python
@runtime_checkable
class LLMProvider(Protocol):
    @property
    def name(self) -> str:
        """Human-readable provider name (e.g., 'openai/gpt-4o')."""
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
            prompt: The user prompt text.
            system: Optional system prompt for model instructions.
            temperature: Sampling temperature (0.0 = deterministic, 1.0+ = creative).
            max_tokens: Maximum tokens in the response.
            response_format: Optional format hint, e.g., {"type": "json_object"}.

        Returns:
            The model's text response.
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
            prompt: The user prompt text.
            schema: A Pydantic model class defining the expected response shape.
            system: Optional system prompt.
            temperature: Sampling temperature (lower for structured output).

        Returns:
            A validated instance of the provided Pydantic model.

        Raises:
            pydantic.ValidationError: If the model response does not match the schema.
        """
        ...

    async def close(self) -> None:
        """Release any held resources (HTTP connections, file handles)."""
        ...
```

### ImageProvider

```python
@runtime_checkable
class ImageProvider(Protocol):
    @property
    def name(self) -> str:
        """Human-readable provider name (e.g., 'dall-e-3')."""
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
            prompt: Image generation prompt describing the desired image.
            width: Desired image width in pixels.
            height: Desired image height in pixels.
            style: Optional style modifier (e.g., "anime", "watercolor").
            negative_prompt: Optional negative prompt (things to avoid in the image).

        Returns:
            Raw image bytes in PNG format (preferred) or JPEG.
        """
        ...

    async def close(self) -> None:
        """Release any held resources."""
        ...
```

### Error Types

Provider implementations should raise these error types from `vne_cli.providers.errors` when appropriate:

| Error | When to Raise |
|---|---|
| `ProviderAuthError` | API key is missing, invalid, or expired (HTTP 401/403) |
| `ProviderRateLimitError` | Rate limit exceeded (HTTP 429). Include `retry_after` if available. |
| `ProviderResponseError` | Unexpected response format, server error (HTTP 5xx), or timeout |
| `ProviderNotFoundError` | Package not installed or factory function not found |

VNE-CLI's retry logic (`utils/retry.py`) uses exponential backoff with jitter for transient failures:

- Max retries: 3 (configurable)
- Base delay: 1 second
- Max delay: 30 seconds
- Rate limit errors: respect `Retry-After` header when present
