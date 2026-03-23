"""Pydantic models for .flow JSON validation.

These models validate .flow files produced by VNE-CLI or by the VNE editor.
Field names match the actual VNE .flow specification exactly.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FlowPin(BaseModel):
    """A pin on a flow node."""

    id: int
    type_id: str
    is_output: bool
    name: str | None = None
    val: Any = None


class FlowNodeSchema(BaseModel):
    """A node in a .flow file."""

    id: int
    type_id: str
    position: dict[str, int] = Field(default_factory=lambda: {"x": 0, "y": 0})
    input_pin_list: list[FlowPin] = Field(default_factory=list)
    output_pin_list: list[FlowPin] = Field(default_factory=list)
    # Extra fields for comment nodes.
    text: str | None = None
    size: dict[str, int] | None = None

    model_config = {"extra": "allow"}


class FlowLink(BaseModel):
    """A link between pins in a .flow file.

    CRITICAL: The naming is counterintuitive.
    - input_pin_id = SOURCE node's output pin (is_output: true)
    - output_pin_id = DESTINATION node's input pin (is_output: false)
    """

    id: int
    input_pin_id: int
    output_pin_id: int


class FlowFile(BaseModel):
    """Top-level .flow file model."""

    max_uid: int = 0
    is_open: bool = True
    node_pool: list[FlowNodeSchema] = Field(default_factory=list)
    link_pool: list[FlowLink] = Field(default_factory=list)
