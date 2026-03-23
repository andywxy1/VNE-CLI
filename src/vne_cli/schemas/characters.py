"""Character registry Pydantic models.

Produced by the character extraction pre-pass.
Can be generated independently and reused across extraction runs.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Character(BaseModel):
    """A fully described character in the registry."""

    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    is_protagonist: bool = False
    physical_description: str = ""
    clothing_default: str = ""
    personality_traits: list[str] = Field(default_factory=list)
    role: str = ""
    relationships: dict[str, str] = Field(default_factory=dict)
    sprite_expressions: list[str] = Field(
        default_factory=lambda: ["neutral", "happy", "sad", "angry", "surprised"]
    )


class CharacterRegistry(BaseModel):
    """The complete character registry for a novel.

    Produced by the character pre-pass, consumed by structure extraction
    and asset generation.
    """

    schema_: str = Field(default="vne-cli://characters/v1", alias="$schema")
    source_file: str = ""
    extracted_at: datetime | None = None
    protagonist: str = ""
    characters: dict[str, Character] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}
