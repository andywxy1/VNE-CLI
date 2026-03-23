# CLAUDE.md -- VNE-CLI

## What This Project Is

VNE-CLI is a Python CLI tool that converts novel text (plain text or markdown) into complete VoidNovelEngine visual novel projects. It uses a three-stage pipeline: (1) extract story structure from text using an LLM, (2) generate character sprites and background art using an image generation API, (3) assemble everything into a ready-to-run VNE project with `.flow` files, assets, and a `project.vne` manifest. The output is a directory you can open in the VNE editor or run directly in VoidNovelEngine.

## Quick Reference

- **Language**: Python 3.10+
- **CLI framework**: Typer
- **Build system**: Hatchling (pyproject.toml)
- **Entry point**: `vne` command, defined in `src/vne_cli/cli.py`
- **Package root**: `src/vne_cli/`
- **Config format**: TOML
- **Test runner**: pytest with pytest-asyncio
- **Linter**: ruff
- **Type checker**: mypy (strict mode)

## Installation

```bash
cd /Users/andy/VNE-CLI
pip install -e ".[dev]"
```

This installs the `vne` command and all dev dependencies (pytest, ruff, mypy).

## Provider Configuration

VNE-CLI requires two providers: an LLM provider (for text extraction) and an image provider (for asset generation). Providers are configured via TOML config files and authenticated via environment variables.

### Step 1: Set API keys as environment variables

```bash
# OpenAI (for GPT LLM + DALL-E images)
export VNE_CLI_OPENAI_API_KEY="sk-..."

# OR Anthropic (for Claude LLM)
export VNE_CLI_ANTHROPIC_API_KEY="sk-ant-..."

# OR Stability AI (for Stable Diffusion images)
export VNE_CLI_STABILITY_API_KEY="sk-..."
```

Alternatively, add keys to `~/.vne-cli/config.toml` under `[credentials]`:

```toml
[credentials]
openai_api_key = "sk-..."
```

Credentials are NEVER read from the project-level config (`./vne-cli.toml`). This is enforced by the config loader.

### Step 2: Create user-level config

Run `vne config init --global` to create `~/.vne-cli/config.toml`, then edit it:

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

[credentials]
# Prefer env vars. Config values here are fallback only.
# openai_api_key = ""
```

### Built-in Provider Packages

| Provider | Package Path | Factory | Credential Env Var |
|---|---|---|---|
| OpenAI LLM | `vne_cli.providers.llm.openai_provider` | `create_llm_provider` | `VNE_CLI_OPENAI_API_KEY` |
| Anthropic LLM | `vne_cli.providers.llm.anthropic_provider` | `create_llm_provider` | `VNE_CLI_ANTHROPIC_API_KEY` |
| DALL-E Images | `vne_cli.providers.image.dalle_provider` | `create_image_provider` | `VNE_CLI_OPENAI_API_KEY` or `VNE_CLI_DALLE_API_KEY` |
| Stable Diffusion | `vne_cli.providers.image.stable_diffusion_provider` | `create_image_provider` | `VNE_CLI_STABILITY_API_KEY` |

### Step 3: Verify config

```bash
vne config show --resolved
```

## Full Pipeline Usage

### Stage 1: Extract story structure

```bash
vne extract novel.txt -o story.json
```

Reads the novel, chunks it for the LLM context window, extracts characters, scenes, dialogue, narration, branching choices, and cinematic annotations. Outputs `story.json`.

### Stage 2: Generate images

```bash
vne generate-assets story.json -o ./assets/
```

Reads `story.json`, builds image prompts for each character expression and unique background, calls the image provider API, and saves results to `assets/characters/` and `assets/backgrounds/`. Tracks progress in an asset manifest for crash recovery.

### Stage 3: Assemble VNE project

```bash
vne assemble story.json --assets ./assets/ -o ./project/
```

Combines `story.json` and generated assets into a complete VNE project directory with `.flow` files, `project.vne` manifest, `main.lua` entry point, and organized resource directories.

### Dry run (no API calls)

```bash
vne extract novel.txt --dry-run
vne generate-assets story.json --dry-run
```

## CLI Command Reference

### `vne extract <INPUT_FILE> [OPTIONS]`

Parse novel text into structured story JSON.

| Option | Type | Default | Description |
|---|---|---|---|
| `INPUT_FILE` | Path (positional) | required | Novel text file (.txt, .md) |
| `-o, --output` | Path | `./story.json` | Output story JSON path |
| `--characters-only` | flag | false | Run only the character extraction pre-pass |
| `--characters` | Path | none | Reuse an existing character registry JSON |
| `--config` | Path | none | Project config file override |
| `--max-chapters` | int | none | Override max chapter count |
| `--max-branch-depth` | int | none | Override max branch depth |
| `--dry-run` | flag | false | Show extraction plan without calling the LLM |
| `--verbose / --no-verbose` | flag | false | Enable detailed logging |

### `vne generate-assets <STORY_JSON> [OPTIONS]`

Generate character sprites and background images.

| Option | Type | Default | Description |
|---|---|---|---|
| `STORY_JSON` | Path (positional) | required | story.json from extract stage |
| `-o, --output` | Path | `./assets/` | Output assets directory |
| `--manifest` | Path | none | Resume from existing asset manifest |
| `--characters-only` | flag | false | Generate only character sprites |
| `--backgrounds-only` | flag | false | Generate only backgrounds |
| `--style` | string | none | Override image style (e.g. "watercolor", "anime") |
| `--concurrency` | int | 3 | Max parallel API requests |
| `--config` | Path | none | Project config file override |
| `--dry-run` | flag | false | Show what would be generated without calling APIs |
| `--verbose / --no-verbose` | flag | false | Enable detailed logging |

### `vne assemble <STORY_JSON> --assets <DIR> [OPTIONS]`

Assemble story JSON and assets into a VNE project.

| Option | Type | Default | Description |
|---|---|---|---|
| `STORY_JSON` | Path (positional) | required | story.json from extract stage |
| `--assets` | Path | required | Assets directory from generate-assets stage |
| `-o, --output` | Path | `./project/` | Output project directory |
| `--resolution` | string | none | Game window resolution as WIDTHxHEIGHT (e.g. "1920x1080") |
| `--title` | string | none | Override project title |
| `--cinematic / --no-cinematic` | flag | true | Apply cinematic direction layer |
| `--cinematic-tier` | string | none | "base" or "full" cinematic polish |
| `--validate / --no-validate` | flag | true | Validate output before writing |
| `--config` | Path | none | Project config file override |
| `--verbose / --no-verbose` | flag | false | Enable detailed logging |

### `vne validate <FILE>`

Validate any VNE-CLI intermediate file (story.json, .flow, project.vne). NOTE: This command is not yet implemented (exits with code 1).

### `vne config show [--resolved]`

Display the merged configuration as TOML. With `--resolved`, shows per-key source annotations indicating which layer (default, user, project, env) each value came from.

### `vne config init [--global]`

Create a config file with defaults. Without `--global`, creates `./vne-cli.toml` (project config). With `--global`, creates `~/.vne-cli/config.toml` (user config).

### `vne --version` / `vne -V`

Print the version and exit.

## Configuration System

Config is layered TOML with this precedence (highest wins):

1. CLI flags
2. Environment variables (`VNE_CLI_` prefix)
3. Project config (`./vne-cli.toml`)
4. User config (`~/.vne-cli/config.toml`)
5. Built-in defaults

Environment variable mapping: `VNE_CLI_` + section path in SCREAMING_SNAKE_CASE. Examples:
- `providers.llm.model` -> `VNE_CLI_PROVIDERS_LLM_MODEL`
- `extraction.max_branch_depth` -> `VNE_CLI_EXTRACTION_MAX_BRANCH_DEPTH`
- `assets.style` -> `VNE_CLI_ASSETS_STYLE`

### Example Project Config (vne-cli.toml)

This file is safe to commit. Place it in the project root.

```toml
[project]
name = "The Crystal Kingdom"
version = "1.0.0"
resolution = [1920, 1080]

[extraction]
language = "en"
max_chapters = 30
max_branch_depth = 3
max_choices_per_branch = 3
protagonist_name = ""             # Leave empty for auto-detection

[extraction.chunking]
target_tokens = 8000
overlap_tokens = 500

[assets]
style = "anime"
background_size = [1920, 1080]
sprite_size = [800, 1200]
output_format = "png"

[assembly]
default_text_speed = 30
default_transition = "fade"
transition_duration_ms = 500

[cinematic]
enabled = true
tier = "full"                     # "base" for minimal, "full" for complete
```

### Example User Config (~/.vne-cli/config.toml)

This file should NOT be committed. It holds provider config and optional credential fallbacks.

```toml
[providers.llm]
package = "vne_cli.providers.llm.openai_provider"
factory = "create_llm_provider"
model = "gpt-4o"

[providers.image]
package = "vne_cli.providers.image.dalle_provider"
factory = "create_image_provider"
model = "dall-e-3"

[credentials]
# Prefer env vars. These are fallback only.
# openai_api_key = "sk-..."
```

## Project Structure

```
/Users/andy/VNE-CLI/
  pyproject.toml                    # Build config (hatchling), ruff, mypy, pytest settings
  README.md                         # Project README
  CLAUDE.md                         # This file
  docs/
    providers.md                    # Full provider guide with protocol reference
    flow-format.md                  # .flow file format specification
  examples/
    project-config.toml             # Example project config
    user-config.toml                # Example user config
  tests/                            # 254 tests (pytest + pytest-asyncio)
  src/vne_cli/
    __init__.py                     # Package init, exposes __version__
    cli.py                          # Typer CLI app, all command definitions
    commands/
      extract.py                    # Extract pipeline orchestration
      generate_assets.py            # Asset generation orchestration
      assemble.py                   # Project assembly orchestration
    config/
      loader.py                     # Layered TOML config loading + merging
      schema.py                     # Config Pydantic models
      credentials.py                # Credential resolution (env -> config -> keyring)
    extraction/
      chunker.py                    # Smart text chunking (respects chapter boundaries)
      character_pass.py             # Character registry extraction + deduplication
      structure_pass.py             # Chapter/scene/dialogue extraction
      branch_detector.py            # Branch detection (explicit markers + implicit cues)
      validator.py                  # Extraction output validation
    assets/
      pipeline.py                   # Asset generation orchestration with concurrency
      prompt_builder.py             # Image prompt construction from story data
      manifest.py                   # Asset manifest read/write for crash recovery
      downloader.py                 # Image saving and format conversion
    assembly/
      project_builder.py            # project.vne manifest generation
      flow_writer.py                # .flow file generation
      asset_organizer.py            # Asset copying into VNE directory layout
      validator.py                  # Assembled project validation
    flow/
      nodes.py                      # 50 VNE node type definitions
      pins.py                       # 13 pin type definitions
      graph.py                      # Flow graph construction
      serializer.py                 # Graph to .flow JSON serialization
      scene_compiler.py             # Scene data to flow graph compilation
      orchestrator.py               # Multi-scene flow orchestration
      cinematic.py                  # Cinematic direction layer (transitions, letterboxing, timing)
    providers/
      base.py                       # LLMProvider and ImageProvider Protocol definitions
      registry.py                   # Provider loading from config via importlib
      errors.py                     # ProviderAuthError, ProviderRateLimitError, ProviderResponseError, ProviderNotFoundError
      llm/                          # Built-in LLM providers (openai, anthropic)
      image/                        # Built-in image providers (dalle, stable_diffusion)
    schemas/                        # Pydantic models for all data formats (story.json, etc.)
    utils/                          # Logging, retry (exponential backoff + jitter), path helpers
```

### Dependency Flow

Dependencies flow inward: `cli -> commands -> {extraction, assets, assembly} -> {providers, flow, schemas} -> utils`. No cycles. `schemas/` and `providers/` never import from `extraction/`, `assets/`, or `assembly/`.

## Testing

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run with coverage
python3 -m pytest tests/ --cov=vne_cli

# Run a specific test file
python3 -m pytest tests/test_chunker.py -v
```

The test suite has 254 tests covering config loading, provider protocols, text chunking, branch detection, extraction validation, asset generation, flow graph construction, and project assembly. Tests use `asyncio_mode = "auto"` so async tests do not need explicit markers.

### Linting and Type Checking

```bash
# Lint
ruff check src/

# Type check
mypy src/vne_cli/
```

Ruff is configured for Python 3.10 target with 100-character line length. Mypy runs in strict mode.

## The .flow Format

Generated `.flow` files are UTF-8 JSON with this top-level structure:

```json
{
  "max_uid": 42,
  "node_pool": [ ... ],
  "link_pool": [ ... ],
  "is_open": true
}
```

Each file represents one scene. Nodes have typed input/output pins connected by links. Key node types: `entry` (flow start), `show_dialog_box` (dialogue), `show_choice_button` (branching choices with up to 5 options), `switch_background` (background changes), `add_foreground`/`remove_foreground` (character sprites), `switch_scene` (scene transitions), `transition_fade_in`/`transition_fade_out` (fades).

IMPORTANT: Link field naming is counterintuitive. In a link object, `input_pin_id` is the SOURCE (an output pin on a node) and `output_pin_id` is the DESTINATION (an input pin on a node). Data flows from `input_pin_id` to `output_pin_id`.

All IDs (nodes, pins, links) share one monotonically increasing counter per file. `max_uid` must equal the highest assigned ID.

For the full node type reference, pin types, connection rules, and editing instructions, see `docs/flow-format.md`.

## Writing Custom Providers

Providers use `typing.Protocol` (structural subtyping). Your provider does NOT need to import from or inherit anything in vne-cli. It only needs methods with matching signatures.

### LLMProvider Protocol

```python
class YourLLMProvider:
    @property
    def name(self) -> str: ...

    async def complete(self, prompt: str, *, system: str | None = None,
                       temperature: float = 0.7, max_tokens: int = 4096,
                       response_format: dict | None = None) -> str: ...

    async def complete_structured(self, prompt: str, schema: type, *,
                                  system: str | None = None,
                                  temperature: float = 0.3) -> Any: ...

    async def close(self) -> None: ...
```

- `complete` returns plain text.
- `complete_structured` returns a validated Pydantic model instance matching the provided `schema` class.

### ImageProvider Protocol

```python
class YourImageProvider:
    @property
    def name(self) -> str: ...

    async def generate(self, prompt: str, *, width: int = 1024, height: int = 1024,
                       style: str | None = None,
                       negative_prompt: str | None = None) -> bytes: ...

    async def close(self) -> None: ...
```

- `generate` returns raw PNG bytes.

### Factory Function

Each provider needs a factory function that VNE-CLI calls to instantiate the provider:

```python
def create_llm_provider(*, api_key: str, model: str = "default", **kwargs):
    return YourLLMProvider(api_key=api_key, model=model)
```

Any TOML keys beyond `package` and `factory` in the provider config section are passed as `**kwargs` to the factory.

### Register in Config

```toml
[providers.llm]
package = "my_llm_provider"          # Must be importable via importlib.import_module()
factory = "create_llm_provider"      # Factory function name in that module
model = "my-model-v2"                # Passed as kwarg
base_url = "https://my-api.com"      # Any extra keys are passed as **kwargs
```

### Provider Error Types

Providers should raise errors from `vne_cli.providers.errors`:

| Error | When |
|---|---|
| `ProviderAuthError` | API key missing, invalid, or expired (HTTP 401/403) |
| `ProviderRateLimitError` | Rate limit exceeded (HTTP 429); include `retry_after` if available |
| `ProviderResponseError` | Unexpected response format, server error (5xx), timeout |
| `ProviderNotFoundError` | Package not installed or factory function not found |

For full examples with working code, see `docs/providers.md`.

## Common Workflows

### "User gives me a novel, generate a VNE project"

1. Ensure providers are configured (see Provider Configuration above).
2. Run the full pipeline:

```bash
vne extract /path/to/novel.txt -o story.json --verbose
vne generate-assets story.json -o ./assets/ --verbose
vne assemble story.json --assets ./assets/ -o ./project/ --verbose
```

3. The output at `./project/` is a complete VNE project. It contains `project.vne`, `main.lua`, `.flow` files in `application/flow/`, and images in `application/resources/`.

### "User wants to customize the art style"

Option A -- set style globally in project config (`vne-cli.toml`):

```toml
[assets]
style = "watercolor"
```

Option B -- override per-run via CLI flag:

```bash
vne generate-assets story.json -o ./assets/ --style "watercolor"
```

Option C -- override via environment variable:

```bash
export VNE_CLI_ASSETS_STYLE="pixel-art"
vne generate-assets story.json -o ./assets/
```

The style string is passed to the image provider's `generate()` method as the `style` parameter. Supported values depend on the image provider.

### "User wants to edit generated flows"

1. Generated `.flow` files live in the assembled project at `./project/application/flow/`.
2. Each scene has its own file named by scene ID (e.g., `ch_001_sc_001.flow`). The entry point is `entry.flow`.
3. To edit dialogue: find the `show_dialog_box` node. The first string pin (index 1) is the character name, the second (index 2) is the dialogue text. Edit the `val` field.
4. To add a choice: insert a `show_choice_button` node with up to 5 string input pins for choice texts. Connect each output flow pin to the appropriate branch.
5. To change a background: find the `switch_background` node and update the `texture` pin's `val` to match a filename (without extension) in `application/resources/backgrounds/`.
6. After editing, ensure `max_uid` >= the highest ID in the file and all IDs are unique.
7. Validate with `vne validate yourfile.flow` (once implemented).
8. Full format reference: `docs/flow-format.md`.

### "User wants to add a new LLM/image provider"

1. Create a Python module with a class matching the `LLMProvider` or `ImageProvider` protocol (see Writing Custom Providers above).
2. Add a factory function (e.g., `create_llm_provider(*, api_key, model, **kwargs)`).
3. Make the module importable (either on `PYTHONPATH` or `pip install` it).
4. Register it in `~/.vne-cli/config.toml`:

```toml
[providers.llm]
package = "my_provider_module"
factory = "create_llm_provider"
model = "my-model"
custom_option = "value"    # passed as **kwargs to factory
```

5. Set the API key: `export VNE_CLI_MY_PROVIDER_API_KEY="..."` (or add to `[credentials]` in user config).
6. Verify: `vne config show --resolved`.

## Output Directory Layout

The assembled VNE project has this structure:

```
project/
  project.vne              # Engine project manifest (JSON)
  main.lua                 # Engine entry point
  application/
    flow/
      entry.flow           # Entry flow (fade-in, first scene transition)
      ch_001_sc_001.flow   # Scene flow files
      ch_001_sc_002.flow
      ...
    resources/
      characters/          # Character sprite PNGs
      backgrounds/         # Background PNGs
      audio/               # Audio files
      fonts/               # Font files
    icon/
      icon.png             # Default 64x64 icon
```

## Supported Input Formats

| Format | Extension | Notes |
|---|---|---|
| Plain text | `.txt` | One continuous narrative |
| Markdown | `.md` | Chapter headers detected via `#` headings |

Explicit branching markup (works in any format):

```
[CHOICE: What should Elena do?]
[OPTION: Read the letter immediately]
[OPTION: Hide it and read later]
```

The parser also detects implicit branching cues from narrative patterns. EPUB support is declared in the CLI interface but not yet implemented.
