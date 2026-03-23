"""Asset manifest Pydantic models.

Tracks the generation state of every visual asset for resume capability.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AssetStatus(str, Enum):
    """Generation status for a single asset."""

    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"


class AssetType(str, Enum):
    """Type of visual asset."""

    BACKGROUND = "background"
    SPRITE = "sprite"


class AssetEntry(BaseModel):
    """A single asset in the manifest."""

    type: AssetType
    character: str | None = None
    expression: str | None = None
    prompt: str = ""
    status: AssetStatus = AssetStatus.PENDING
    file: str | None = None
    width: int = 0
    height: int = 0
    generated_at: datetime | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AssetSummary(BaseModel):
    """Summary counts for the manifest."""

    total: int = 0
    complete: int = 0
    pending: int = 0
    failed: int = 0


class AssetManifestSchema(BaseModel):
    """Top-level asset manifest model."""

    schema_: str = Field(default="vne-cli://asset-manifest/v1", alias="$schema")
    generated_at: datetime | None = None
    provider: str = ""
    style: str = ""
    assets: dict[str, AssetEntry] = Field(default_factory=dict)
    summary: AssetSummary = Field(default_factory=AssetSummary)

    model_config = {"populate_by_name": True}

    def recompute_summary(self) -> None:
        """Recompute summary counts from asset entries."""
        self.summary.total = len(self.assets)
        self.summary.complete = sum(
            1 for a in self.assets.values() if a.status == AssetStatus.COMPLETE
        )
        self.summary.pending = sum(
            1 for a in self.assets.values() if a.status == AssetStatus.PENDING
        )
        self.summary.failed = sum(
            1 for a in self.assets.values() if a.status == AssetStatus.FAILED
        )
