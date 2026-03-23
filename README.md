# VNE-CLI

Generate complete [VoidNovelEngine](https://github.com/VoidmatrixHeathcliff/VoidNovelEngine) visual novel projects from novel text using AI.

VNE-CLI reads a novel (plain text or markdown), uses LLM providers to extract characters, scenes, dialogue, and branching choices, generates character sprites and background art via image generation APIs, and assembles everything into a ready-to-run VNE project with `.flow` files, assets, and a `project.vne` manifest.

## Features

- **Three-stage pipeline**: Extract structure, generate assets, assemble project -- each stage is independent and resumable
- **Pluggable providers**: Use OpenAI, Anthropic, DALL-E, Stable Diffusion, or write your own
- **Smart text chunking**: Respects chapter boundaries and maintains context overlap across chunks
- **Character extraction**: Automatic character identification, deduplication, and expression variant detection
- **Branch detection**: Finds explicit choice markers and implicit narrative branching cues
- **Cinematic direction**: Automatically adds transitions, letterboxing, and timing from prose cues
- **Asset resume**: Image generation tracks progress per-asset; resume after failures without re-generating
- **Layered configuration**: Global user config, per-project config, environment variables, and CLI flags

## Installation

**Requirements**: Python 3.10 or later

```bash
pip install vne-cli
```

For development:

```bash
git clone <repo-url> && cd VNE-CLI
pip install -e ".[dev]"
```

## Quick Start

Transform a novel into a playable visual novel in three commands:

```bash
# 1. Extract story structure (characters, scenes, dialogue, choices)
vne extract novel.txt -o story.json

# 2. Generate character sprites and scene backgrounds
vne generate-assets story.json -o ./assets/

# 3. Assemble into a VNE project
vne assemble story.json --assets ./assets/ -o ./my-vn-project/
```

The output at `./my-vn-project/` is a complete VoidNovelEngine project you can open in the VNE editor or run directly.

### Dry Run

Preview what each stage will do without making API calls:

```bash
vne extract novel.txt --dry-run
vne generate-assets story.json --dry-run
```

## Configuration

VNE-CLI uses layered TOML configuration with this precedence (highest wins):

1. CLI flags
2. Environment variables (`VNE_CLI_*` prefix)
3. Project config (`./vne-cli.toml` in your working directory)
4. User config (`~/.vne-cli/config.toml`)
5. Built-in defaults

### Setting Up Providers

Create a user-level config for your API keys and preferred providers:

```bash
vne config init --global
```

This creates `~/.vne-cli/config.toml`. Edit it to configure your providers:

```toml
[providers.llm]
package = "vne_cli_openai"
factory = "create_llm_provider"
model = "gpt-4o"

[providers.image]
package = "vne_cli_dalle"
factory = "create_image_provider"
model = "dall-e-3"

[credentials]
# Prefer env vars over config values:
#   export VNE_CLI_OPENAI_API_KEY="sk-..."
#   export VNE_CLI_DALLE_API_KEY="sk-..."
```

### Project Configuration

Create a per-project config in your project root:

```bash
vne config init
```

This creates `./vne-cli.toml`. This file is safe to commit to version control (no credentials):

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
protagonist_name = ""  # Leave empty for auto-detection

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
tier = "full"  # "base" for minimal, "full" for complete
```

### Environment Variables

All config keys map to environment variables via `VNE_CLI_` + section path in `SCREAMING_SNAKE_CASE`:

| Config Key | Environment Variable |
|---|---|
| `providers.llm.model` | `VNE_CLI_PROVIDERS_LLM_MODEL` |
| `extraction.max_branch_depth` | `VNE_CLI_EXTRACTION_MAX_BRANCH_DEPTH` |
| `assets.style` | `VNE_CLI_ASSETS_STYLE` |

Credentials are resolved in order: environment variable, user config file, system keyring (if the `keyring` package is installed).

### Viewing Resolved Config

```bash
# Show merged config as TOML
vne config show

# Show with source annotations (which layer each value came from)
vne config show --resolved
```

## Command Reference

### `vne extract`

Parse novel text into structured story JSON.

```
vne extract <INPUT_FILE> [OPTIONS]
```

| Argument / Option | Description |
|---|---|
| `INPUT_FILE` | Path to novel text file (`.txt`, `.md`) |
| `-o, --output PATH` | Output story.json path (default: `./story.json`) |
| `--characters-only` | Run only the character extraction pre-pass |
| `--characters PATH` | Reuse an existing character registry JSON |
| `--config PATH` | Project config file override |
| `--max-chapters INT` | Override max chapter count |
| `--max-branch-depth INT` | Override max branch depth |
| `--dry-run` | Show extraction plan without calling the LLM |
| `--verbose / --no-verbose` | Enable detailed logging |

**What it does**:

1. Reads the input file and detects chapter boundaries
2. Chunks text to fit within the LLM's context window (respecting chapter boundaries)
3. Runs a character extraction pre-pass across all chunks, then merges/deduplicates
4. Extracts chapters, scenes, dialogue, narration, and cinematic annotations
5. Detects branching cues (explicit `[CHOICE: ...]` markers and implicit narrative patterns)
6. Enforces branch depth and choice count limits
7. Validates the output (character references, branch targets, orphaned scenes)
8. Writes `story.json`

### `vne generate-assets`

Generate images for characters and backgrounds via a pluggable image generation API.

```
vne generate-assets <STORY_JSON> [OPTIONS]
```

| Argument / Option | Description |
|---|---|
| `STORY_JSON` | Path to story.json from the extract stage |
| `-o, --output PATH` | Output assets directory (default: `./assets/`) |
| `--manifest PATH` | Resume from an existing asset manifest |
| `--characters-only` | Generate only character sprites |
| `--backgrounds-only` | Generate only backgrounds |
| `--style TEXT` | Override image style (e.g. `"watercolor"`) |
| `--concurrency INT` | Max parallel API requests (default: `3`) |
| `--config PATH` | Project config file override |
| `--dry-run` | Show what would be generated without calling APIs |
| `--verbose / --no-verbose` | Enable detailed logging |

**What it does**:

1. Reads story.json and builds asset requests (one per character expression + one per unique background)
2. Deduplicates backgrounds by location and time-of-day
3. Initializes or loads an asset manifest for resume tracking
4. Generates images concurrently with a configurable semaphore bound
5. Saves the manifest after each asset for crash recovery
6. Outputs to `assets/characters/` and `assets/backgrounds/`

### `vne assemble`

Assemble story JSON and assets into a ready-to-run VNE project.

```
vne assemble <STORY_JSON> --assets <DIR> [OPTIONS]
```

| Argument / Option | Description |
|---|---|
| `STORY_JSON` | Path to story.json from the extract stage |
| `--assets PATH` | Assets directory from the generate-assets stage (required) |
| `-o, --output PATH` | Output project directory (default: `./project/`) |
| `--resolution WxH` | Game window resolution (e.g. `1920x1080`) |
| `--title TEXT` | Override project title |
| `--cinematic / --no-cinematic` | Apply cinematic direction layer (default: on) |
| `--cinematic-tier TEXT` | `"base"` or `"full"` cinematic polish |
| `--validate / --no-validate` | Validate output before writing (default: on) |
| `--config PATH` | Project config file override |
| `--verbose / --no-verbose` | Enable detailed logging |

**What it does**:

1. Generates `.flow` files for every scene using the flow graph compiler
2. Creates an entry flow with fade-in and transition to the first scene
3. Applies cinematic direction (transitions, letterboxing, timing) if enabled
4. Copies and organizes assets into VNE directory layout
5. Generates `project.vne` manifest and `main.lua` entry point
6. Validates the assembled project (flow integrity, asset references, entry point)

### `vne config`

Manage VNE-CLI configuration.

```bash
vne config show              # Display resolved config as TOML
vne config show --resolved   # Show with source annotations per key
vne config init              # Create ./vne-cli.toml with defaults
vne config init --global     # Create ~/.vne-cli/config.toml with defaults
```

### `vne validate`

Validate any VNE-CLI intermediate file.

```bash
vne validate story.json         # Validate extracted story
vne validate scene.flow         # Validate a flow file
vne validate project.vne        # Validate project manifest
```

## Architecture

### Pipeline Overview

```
novel.txt
    |
    v
+----------+    story.json        characters.json
|  extract  |----+---------------> (optional output)
+----------+    |
                |
                v
         +-----------------+
         | generate-assets |
         +-----------------+
                |
                |   asset-manifest.json
                |   assets/backgrounds/*.png
                |   assets/characters/*.png
                |
                v
           +----------+
           | assemble | <-- reads story.json + assets/ + manifest
           +----------+
                |
                v
            ./project/
            +-- project.vne
            +-- main.lua
            +-- application/
                +-- flow/*.flow
                +-- resources/
                    +-- characters/
                    +-- backgrounds/
                    +-- audio/
                    +-- fonts/
                +-- icon/icon.png
```

### Module Structure

```
src/vne_cli/
+-- cli.py                 # Typer CLI, all command definitions
+-- commands/
|   +-- extract.py         # Extract pipeline orchestration
|   +-- generate_assets.py # Asset generation orchestration
|   +-- assemble.py        # Project assembly orchestration
+-- config/
|   +-- loader.py          # Layered TOML config loading
|   +-- schema.py          # Config Pydantic models
|   +-- credentials.py     # Credential resolution (env, config, keyring)
+-- extraction/
|   +-- chunker.py         # Smart text chunking for LLM context windows
|   +-- character_pass.py  # Character registry extraction
|   +-- structure_pass.py  # Chapter/scene/dialogue extraction
|   +-- branch_detector.py # Branch detection and enforcement
|   +-- validator.py       # Extraction output validation
+-- assets/
|   +-- pipeline.py        # Asset generation orchestration
|   +-- prompt_builder.py  # Image prompt construction
|   +-- manifest.py        # Asset manifest read/write
|   +-- downloader.py      # Image saving and format conversion
+-- assembly/
|   +-- project_builder.py # project.vne generation
|   +-- flow_writer.py     # .flow file generation
|   +-- asset_organizer.py # Asset copying and organization
|   +-- validator.py       # Assembled project validation
+-- flow/
|   +-- nodes.py           # 50 VNE node type definitions
|   +-- pins.py            # 13 pin type definitions
|   +-- graph.py           # Flow graph construction
|   +-- serializer.py      # Graph to .flow JSON
|   +-- scene_compiler.py  # Scene to flow graph compilation
|   +-- orchestrator.py    # Multi-scene flow orchestration
|   +-- cinematic.py       # Cinematic direction layer
+-- providers/
|   +-- base.py            # LLMProvider and ImageProvider protocols
|   +-- registry.py        # Provider loading from config
|   +-- errors.py          # Error hierarchy
|   +-- llm/               # Built-in LLM providers
|   +-- image/             # Built-in image providers
+-- schemas/               # Pydantic models for all data formats
+-- utils/                 # Logging, retry, path helpers
```

### Dependencies Flow

Dependencies flow inward: `cli -> commands -> {extraction, assets, assembly} -> {providers, flow, schemas} -> utils`. No cycles. `schemas/` and `providers/` never import from `extraction/`, `assets/`, or `assembly/`.

## Writing Custom Providers

VNE-CLI uses Python `Protocol` classes for structural subtyping. Your provider package does not need to import from `vne-cli` -- it only needs to match the interface.

See the [Provider Guide](docs/providers.md) for full details, including step-by-step instructions and the complete protocol reference.

Quick summary:

```python
# my_llm_provider.py
class MyLLMProvider:
    @property
    def name(self) -> str:
        return "my-provider"

    async def complete(self, prompt, *, system=None, temperature=0.7,
                       max_tokens=4096, response_format=None) -> str:
        # Call your LLM API here
        ...

    async def complete_structured(self, prompt, schema, *, system=None,
                                  temperature=0.3):
        # Return a validated Pydantic model instance
        ...

    async def close(self) -> None:
        ...

def create_llm_provider(*, api_key, model="default", **kwargs):
    return MyLLMProvider(api_key=api_key, model=model)
```

Register it in your config:

```toml
[providers.llm]
package = "my_llm_provider"
factory = "create_llm_provider"
model = "my-model"
```

## Supported Input Formats

| Format | Extension | Notes |
|---|---|---|
| Plain text | `.txt` | Most common. One continuous narrative. |
| Markdown | `.md` | Chapter headers detected via `#` headings. |

Explicit branching markup is supported in any format:

```
[CHOICE: What should Elena do?]
[OPTION: Read the letter immediately]
[OPTION: Hide it and read later]
```

The parser also detects implicit branching cues from narrative patterns (e.g., "faced with a choice", "what should X do?").

EPUB support is declared in the CLI interface but not yet implemented.

## Output Format

The assembled project follows the VNE engine's expected directory layout:

```
project/
+-- project.vne              # Engine project manifest (JSON)
+-- main.lua                 # Engine entry point
+-- application/
    +-- flow/
    |   +-- entry.flow        # Entry flow (fade-in, first scene)
    |   +-- ch_001_sc_001.flow
    |   +-- ch_001_sc_002.flow
    |   +-- ...
    +-- resources/
    |   +-- characters/       # Character sprite PNGs
    |   +-- backgrounds/      # Background PNGs
    |   +-- audio/            # Audio files
    |   +-- fonts/            # Font files
    +-- icon/
        +-- icon.png          # Default 64x64 icon
```

See the [Flow Format Guide](docs/flow-format.md) for details on the `.flow` file format.

## Development

### Setup

```bash
git clone <repo-url> && cd VNE-CLI
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest
pytest --cov=vne_cli        # With coverage
```

The test suite includes 254 tests covering config loading, provider protocols, text chunking, branch detection, extraction validation, asset generation, flow graph construction, and project assembly.

### Linting and Type Checking

```bash
ruff check src/
mypy src/vne_cli/
```

### Project Configuration

| Tool | Config Location |
|---|---|
| Build | `pyproject.toml` (hatchling) |
| Linting | `pyproject.toml` (`[tool.ruff]`) |
| Type checking | `pyproject.toml` (`[tool.mypy]`, strict mode) |
| Testing | `pyproject.toml` (`[tool.pytest.ini_options]`) |

## License

MIT
