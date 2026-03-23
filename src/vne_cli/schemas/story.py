"""story.json Pydantic models.

This is the core intermediate format. The extract command produces it,
and both generate-assets and assemble consume it.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class BeatType(str, Enum):
    """Types of narrative beats within a scene."""

    DIALOGUE = "dialogue"
    NARRATION = "narration"
    CHOICE = "choice"
    TRANSITION = "transition"
    DIRECTION = "direction"


class ChoiceOption(BaseModel):
    """A single option within a choice beat."""

    text: str
    target_scene: str
    consequence_tag: str = ""


class Beat(BaseModel):
    """A single narrative beat (dialogue line, narration, choice, etc)."""

    id: str = ""
    type: BeatType
    character: str | None = None
    expression: str | None = None
    text: str = ""
    options: list[ChoiceOption] = Field(default_factory=list)
    style: str | None = None
    duration_ms: int | None = None


class CinematicAnnotation(BaseModel):
    """A single cinematic cue derived from prose analysis."""

    cue_type: str  # "sfx", "transition", "music", "camera", "lighting"
    reference: str  # e.g. "[SFX: gunshot]", "[TRANSITION: fade_to_black]"
    source_text: str = ""  # the prose that triggered this cue
    beat_id: str = ""  # the beat this annotation is attached to


class CinematicAnnotations(BaseModel):
    """Collection of cinematic annotations for a scene."""

    annotations: list[CinematicAnnotation] = Field(default_factory=list)
    enabled: bool = True


class BranchInfo(BaseModel):
    """Branch metadata for a scene."""

    is_branch: bool = False
    branch_source: str | None = None
    converges_at: str | None = None


class Scene(BaseModel):
    """A single scene within a chapter."""

    id: str
    title: str = ""
    location: str = ""
    time_of_day: str = ""
    background_description: str = ""
    characters_present: list[str] = Field(default_factory=list)
    beats: list[Beat] = Field(default_factory=list)
    branch_info: BranchInfo = Field(default_factory=BranchInfo)
    cinematic: CinematicAnnotations | None = None


class Choice(BaseModel):
    """A branch choice with its consequence and content."""

    label: str
    consequence_flag: str = ""
    scenes: list[Scene] = Field(default_factory=list)


class BranchPoint(BaseModel):
    """A branching point where the player makes a choice."""

    trigger_event_id: str = ""
    prompt_text: str = ""
    choices: list[Choice] = Field(default_factory=list)
    convergence_scene_id: str = ""


class Chapter(BaseModel):
    """A chapter containing one or more scenes."""

    id: str
    index: int = 0
    title: str = ""
    synopsis: str = ""
    scenes: list[Scene] = Field(default_factory=list)
    branch_points: list[BranchPoint] = Field(default_factory=list)
    branch_convergence: str | None = None


class CharacterRef(BaseModel):
    """Character reference within story.json (summary, not full registry)."""

    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    is_protagonist: bool = False
    description: str = ""
    personality: str = ""
    sprite_variants: list[str] = Field(default_factory=list)
    first_appearance: str = ""


class GameVariable(BaseModel):
    """A game variable tracked via save_global."""

    name: str
    var_type: str = "bool"  # "bool", "int", "string"
    default_value: str = "false"
    description: str = ""


class ExtractionMetadata(BaseModel):
    """Metadata about the extraction process."""

    extractor_version: str = "0.1.0"
    llm_provider: str = ""
    llm_model: str = ""
    total_chunks: int = 0
    total_tokens_estimated: int = 0
    extraction_duration_seconds: float = 0.0


class StoryMetadata(BaseModel):
    """Metadata for the extracted story."""

    title: str = ""
    author: str = ""
    source_file: str = ""
    extracted_at: datetime | None = None
    vne_cli_version: str = ""
    language: str = "en"


class Story(BaseModel):
    """Top-level story.json model.

    This is the complete intermediate representation produced by the
    extract command and consumed by generate-assets and assemble.
    """

    schema_: str = Field(default="vne-cli://story/v1", alias="$schema")
    metadata: StoryMetadata = Field(default_factory=StoryMetadata)
    characters: dict[str, CharacterRef] = Field(default_factory=dict)
    chapters: list[Chapter] = Field(default_factory=list)
    global_variables: list[GameVariable] = Field(default_factory=list)
    extraction_metadata: ExtractionMetadata = Field(default_factory=ExtractionMetadata)

    model_config = {"populate_by_name": True}
