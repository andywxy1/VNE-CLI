"""VNE flow pin type definitions and connection validation.

Models all 13 pin types from the VNE .flow specification.
Handles pin creation, value serialization, and connection compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PinType(str, Enum):
    """All 13 VNE pin types."""

    FLOW = "flow"
    OBJECT = "object"
    VECTOR2 = "vector2"
    COLOR = "color"
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    FONT = "font"
    AUDIO = "audio"
    VIDEO = "video"
    SHADER = "shader"
    TEXTURE = "texture"


# Pin types that carry data values (have a serialized `val` field).
DATA_PIN_TYPES: frozenset[PinType] = frozenset(PinType) - {PinType.FLOW, PinType.OBJECT}

# Asset-type pins (string-valued asset IDs).
ASSET_PIN_TYPES: frozenset[PinType] = frozenset({
    PinType.FONT,
    PinType.AUDIO,
    PinType.VIDEO,
    PinType.SHADER,
    PinType.TEXTURE,
})

# Default values for each data pin type.
DEFAULT_VALUES: dict[PinType, Any] = {
    PinType.VECTOR2: {"x": 0.0, "y": 0.0},
    PinType.COLOR: {"r": 0.0, "g": 0.0, "b": 0.0, "a": 1.0},
    PinType.STRING: "",
    PinType.INT: 0,
    PinType.FLOAT: 0.0,
    PinType.BOOL: False,
    PinType.FONT: "",
    PinType.AUDIO: "",
    PinType.VIDEO: "",
    PinType.SHADER: "",
    PinType.TEXTURE: "",
}


@dataclass
class PinSpec:
    """Declarative specification for a pin on a node type.

    Used in the node catalog to describe what pins a node type has.
    Not the runtime pin instance -- see ``Pin`` for that.
    """

    type_id: PinType
    is_output: bool
    name: str | None = None
    default_val: Any = None  # None means "use DEFAULT_VALUES for the type"

    def resolved_default(self) -> Any:
        """Return the concrete default value for serialization."""
        if self.default_val is not None:
            return self.default_val
        return DEFAULT_VALUES.get(self.type_id)


@dataclass
class Pin:
    """A runtime pin instance on a concrete node in a flow graph.

    Attributes:
        id: Unique ID from the shared graph counter.
        type_id: One of the 13 pin types.
        is_output: True for output pins, False for input pins.
        name: Optional display label.
        val: Stored value. None for flow/object pins.
    """

    id: int
    type_id: PinType
    is_output: bool
    name: str | None = None
    val: Any = None

    @property
    def has_val(self) -> bool:
        """Whether this pin carries a serializable value."""
        return self.type_id in DATA_PIN_TYPES

    def serialize(self) -> dict[str, Any]:
        """Serialize this pin to the .flow JSON format.

        Rules from the spec:
        - Always include id, type_id, is_output.
        - Include ``name`` only if it is not None.
        - Include ``val`` only for data pin types (not flow, not object).
        """
        result: dict[str, Any] = {
            "id": self.id,
            "type_id": self.type_id.value,
            "is_output": self.is_output,
        }
        if self.name is not None:
            result["name"] = self.name
        if self.has_val:
            result["val"] = self.val
        return result


# ---------------------------------------------------------------------------
# Connection compatibility
# ---------------------------------------------------------------------------

# Compatibility matrix.  Key = (source_output_pin_type, dest_input_pin_type).
# If the pair is in this set, the connection is allowed.
_COMPAT: set[tuple[PinType, PinType]] = set()


def _build_compat() -> None:
    """Populate the compatibility set according to spec Section 4.4."""
    # Same type connects to same type.
    for pt in PinType:
        _COMPAT.add((pt, pt))

    # object accepts any non-flow type (wildcard for data pins).
    for pt in PinType:
        if pt is not PinType.FLOW:
            _COMPAT.add((pt, PinType.OBJECT))
            _COMPAT.add((PinType.OBJECT, pt))

    # int output -> float input is allowed.
    _COMPAT.add((PinType.INT, PinType.FLOAT))


_build_compat()


def pins_compatible(source_type: PinType, dest_type: PinType) -> bool:
    """Return True if a connection from *source_type* output to *dest_type* input is valid."""
    return (source_type, dest_type) in _COMPAT
