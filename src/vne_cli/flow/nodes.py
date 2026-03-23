"""VNE flow node type catalog -- all 46 node types.

Each node type is defined declaratively as a sequence of PinSpec entries.
A factory function creates concrete ``FlowNode`` instances with proper pins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vne_cli.flow.pins import Pin, PinSpec, PinType


# ---------------------------------------------------------------------------
# Node catalog: every entry is (type_id, [input_pin_specs], [output_pin_specs])
# ---------------------------------------------------------------------------

def _p(
    type_id: PinType,
    is_output: bool,
    name: str | None = None,
    default_val: Any = None,
) -> PinSpec:
    """Shorthand for PinSpec construction."""
    return PinSpec(type_id=type_id, is_output=is_output, name=name, default_val=default_val)


# Convenience aliases
_IN = False
_OUT = True
F = PinType.FLOW
S = PinType.STRING
I = PinType.INT
FL = PinType.FLOAT
B = PinType.BOOL
V2 = PinType.VECTOR2
C = PinType.COLOR
OBJ = PinType.OBJECT
TEX = PinType.TEXTURE
AUD = PinType.AUDIO
VID = PinType.VIDEO
FNT = PinType.FONT
SHD = PinType.SHADER


@dataclass(frozen=True)
class NodeTypeDef:
    """Declarative definition of a VNE node type."""

    type_id: str
    input_pins: tuple[PinSpec, ...]
    output_pins: tuple[PinSpec, ...]
    extra_fields: tuple[str, ...] = ()  # e.g. ("text", "size") for comment


# ---- 5.1 Control Flow Nodes ----

ENTRY = NodeTypeDef(
    type_id="entry",
    input_pins=(),
    output_pins=(_p(F, _OUT),),
)

BRANCH = NodeTypeDef(
    type_id="branch",
    input_pins=(
        _p(F, _IN),
        _p(B, _IN, default_val=False),
    ),
    output_pins=(
        _p(F, _OUT, name="\u771f"),   # True
        _p(F, _OUT, name="\u5047"),   # False
    ),
)

LOOP = NodeTypeDef(
    type_id="loop",
    input_pins=(
        _p(F, _IN),
        _p(F, _IN, name="\u518d\u6b21\u6267\u884c"),
        _p(F, _IN, name="\u7ed3\u675f\u5faa\u73af"),
        _p(I, _IN, name="\u5faa\u73af\u6b21\u6570", default_val=-1),
    ),
    output_pins=(
        _p(F, _OUT, name="             "),
        _p(F, _OUT, name="   \u5faa\u73af\u4f53"),
        _p(I, _OUT, name="\u5f53\u524d\u6b21\u6570", default_val=0),
    ),
)

SWITCH_SCENE = NodeTypeDef(
    type_id="switch_scene",
    input_pins=(
        _p(F, _IN),
        _p(S, _IN, name="\u573a\u666fID", default_val=""),
    ),
    output_pins=(),
)

SWITCH_TO_GAME_SCENE = NodeTypeDef(
    type_id="switch_to_game_scene",
    input_pins=(
        _p(F, _IN),
        _p(S, _IN, name="\u573a\u666f\u6587\u4ef6", default_val=""),
    ),
    output_pins=(_p(F, _OUT),),
)

# ---- 5.2 Presentation / Staging Nodes ----

DELAY = NodeTypeDef(
    type_id="delay",
    input_pins=(
        _p(F, _IN),
        _p(FL, _IN, name="\u79d2", default_val=0.0),
    ),
    output_pins=(_p(F, _OUT),),
)

WAIT_INTERACTION = NodeTypeDef(
    type_id="wait_interaction",
    input_pins=(
        _p(F, _IN),
        _p(B, _IN, name="\u7b49\u5f85\u4e92\u52a8", default_val=True),
    ),
    output_pins=(_p(F, _OUT),),
)

SWITCH_BACKGROUND = NodeTypeDef(
    type_id="switch_background",
    input_pins=(
        _p(F, _IN),
        _p(TEX, _IN, name="\u7eb9\u7406", default_val=""),
        _p(FL, _IN, name="\u6de1\u5165\u65f6\u95f4", default_val=1.0),
        _p(B, _IN, name="\u7b49\u5f85\u4e92\u52a8", default_val=True),
    ),
    output_pins=(_p(F, _OUT),),
)

ADD_FOREGROUND = NodeTypeDef(
    type_id="add_foreground",
    input_pins=(
        _p(F, _IN),
        _p(FL, _IN, name="\u7f29\u653e", default_val=1.0),
        _p(V2, _IN, name="\u4f4d\u7f6e", default_val={"x": 0.0, "y": 0.0}),
        _p(TEX, _IN, name="\u7eb9\u7406", default_val=""),
        _p(FL, _IN, name="\u6de1\u5165\u65f6\u95f4", default_val=0.5),
        _p(B, _IN, name="\u7b49\u5f85\u4e92\u52a8", default_val=True),
    ),
    output_pins=(
        _p(F, _OUT, name="              "),
        _p(OBJ, _OUT, name="\u524d\u666f\u56fe\u7247"),
    ),
)

REMOVE_FOREGROUND = NodeTypeDef(
    type_id="remove_foreground",
    input_pins=(
        _p(F, _IN),
        _p(OBJ, _IN, name="\u524d\u666f\u56fe\u7247"),
        _p(FL, _IN, name="\u6de1\u51fa\u65f6\u95f4", default_val=0.5),
        _p(B, _IN, name="\u7b49\u5f85\u4e92\u52a8", default_val=True),
    ),
    output_pins=(_p(F, _OUT),),
)

MOVE_FOREGROUND = NodeTypeDef(
    type_id="move_foreground",
    input_pins=(
        _p(F, _IN),
        _p(OBJ, _IN, name="\u524d\u666f\u56fe\u7247"),
        _p(V2, _IN, name="\u76ee\u6807\u4f4d\u7f6e", default_val={"x": 0.0, "y": 0.0}),
        _p(FL, _IN, name="\u65f6\u95f4", default_val=0.5),
        _p(B, _IN, name="\u7b49\u5f85\u4e92\u52a8", default_val=True),
    ),
    output_pins=(_p(F, _OUT),),
)

SHOW_LETTERBOXING = NodeTypeDef(
    type_id="show_letterboxing",
    input_pins=(
        _p(F, _IN),
        _p(FL, _IN, name="\u9ad8\u5ea6", default_val=200.0),
        _p(FL, _IN, name="\u7f13\u5165\u65f6\u95f4", default_val=1.5),
        _p(B, _IN, name="\u7b49\u5f85\u4e92\u52a8", default_val=False),
    ),
    output_pins=(_p(F, _OUT),),
)

HIDE_LETTERBOXING = NodeTypeDef(
    type_id="hide_letterboxing",
    input_pins=(
        _p(F, _IN),
        _p(FL, _IN, name="\u7f13\u51fa\u65f6\u95f4", default_val=1.5),
        _p(B, _IN, name="\u7b49\u5f85\u4e92\u52a8", default_val=False),
    ),
    output_pins=(_p(F, _OUT),),
)

SHOW_SUBTITLE = NodeTypeDef(
    type_id="show_subtitle",
    input_pins=(
        _p(F, _IN),
        _p(S, _IN, name="\u6587\u672c", default_val=""),
        _p(FL, _IN, name="\u5b57\u7b26\u65f6\u95f4\u95f4\u9694", default_val=0.03),
        _p(FL, _IN, name="\u5c4f\u5e55\u5e95\u90e8\u8ddd\u79bb", default_val=40.0),
        _p(FNT, _IN, name="\u5b57\u4f53", default_val=""),
        _p(I, _IN, name="\u5b57\u53f7", default_val=25),
        _p(C, _IN, name="\u989c\u8272", default_val={"r": 0.95, "g": 0.95, "b": 0.95, "a": 1.0}),
        _p(B, _IN, name="\u7b49\u5f85\u4e92\u52a8", default_val=True),
    ),
    output_pins=(_p(F, _OUT),),
)

HIDE_SUBTITLE = NodeTypeDef(
    type_id="hide_subtitle",
    input_pins=(_p(F, _IN),),
    output_pins=(_p(F, _OUT),),
)

SHOW_DIALOG_BOX = NodeTypeDef(
    type_id="show_dialog_box",
    input_pins=(
        _p(F, _IN),
        _p(S, _IN, name="\u89d2\u8272\u6587\u672c", default_val=""),
        _p(S, _IN, name="\u5185\u5bb9\u6587\u672c", default_val=""),
        _p(V2, _IN, name="\u4f4d\u7f6e", default_val={"x": 0.0, "y": 0.0}),
        _p(FL, _IN, name="\u5bbd\u5ea6", default_val=420.0),
        _p(FL, _IN, name="\u6de1\u5165\u65f6\u95f4", default_val=1.0),
        _p(FNT, _IN, name="\u89d2\u8272\u5b57\u4f53", default_val=""),
        _p(FNT, _IN, name="\u5185\u5bb9\u5b57\u4f53", default_val=""),
        _p(I, _IN, name="\u89d2\u8272\u5b57\u53f7", default_val=20),
        _p(I, _IN, name="\u5185\u5bb9\u5b57\u53f7", default_val=25),
        _p(C, _IN, name="\u89d2\u8272\u989c\u8272",
           default_val={"r": 0.95, "g": 0.95, "b": 0.95, "a": 1.0}),
        _p(C, _IN, name="\u5185\u5bb9\u989c\u8272",
           default_val={"r": 0.75, "g": 0.75, "b": 0.75, "a": 1.0}),
        _p(C, _IN, name="\u80cc\u666f\u989c\u8272",
           default_val={"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.7}),
        _p(B, _IN, name="\u7b49\u5f85\u4e92\u52a8", default_val=True),
    ),
    output_pins=(
        _p(F, _OUT, name="          "),
        _p(OBJ, _OUT, name="\u5bf9\u8bdd\u6846"),
    ),
)

HIDE_DIALOG_BOX = NodeTypeDef(
    type_id="hide_dialog_box",
    input_pins=(
        _p(F, _IN),
        _p(OBJ, _IN, name="\u5bf9\u8bdd\u6846"),
        _p(FL, _IN, name="\u6de1\u51fa\u65f6\u95f4", default_val=1.0),
        _p(B, _IN, name="\u7b49\u5f85\u4e92\u52a8", default_val=True),
    ),
    output_pins=(_p(F, _OUT),),
)

TRANSITION_FADE_IN = NodeTypeDef(
    type_id="transition_fade_in",
    input_pins=(
        _p(F, _IN),
        _p(FL, _IN, name="\u65f6\u95f4", default_val=1.0),
        _p(B, _IN, name="\u7b49\u5f85\u4e92\u52a8", default_val=False),
    ),
    output_pins=(_p(F, _OUT),),
)

TRANSITION_FADE_OUT = NodeTypeDef(
    type_id="transition_fade_out",
    input_pins=(
        _p(F, _IN),
        _p(FL, _IN, name="\u65f6\u95f4", default_val=1.0),
        _p(B, _IN, name="\u7b49\u5f85\u4e92\u52a8", default_val=False),
    ),
    output_pins=(_p(F, _OUT),),
)

SHOW_CHOICE_BUTTON = NodeTypeDef(
    type_id="show_choice_button",
    input_pins=(
        _p(F, _IN),
        _p(S, _IN, name="\u5206\u652f\u6587\u672c1", default_val=""),
        _p(S, _IN, name="\u5206\u652f\u6587\u672c2", default_val=""),
        _p(S, _IN, name="\u5206\u652f\u6587\u672c3", default_val=""),
        _p(S, _IN, name="\u5206\u652f\u6587\u672c4", default_val=""),
        _p(S, _IN, name="\u5206\u652f\u6587\u672c5", default_val=""),
        _p(FNT, _IN, name="\u5b57\u4f53", default_val="default"),
        _p(I, _IN, name="\u5b57\u53f7", default_val=25),
        _p(C, _IN, name="\u9ed8\u8ba4\u989c\u8272",
           default_val={"r": 1.0, "g": 1.0, "b": 1.0, "a": 0.765}),
        _p(C, _IN, name="\u9ad8\u4eae\u989c\u8272",
           default_val={"r": 0.408, "g": 0.639, "b": 0.267, "a": 0.882}),
        _p(C, _IN, name="\u80cc\u666f\u989c\u8272",
           default_val={"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.686}),
        _p(C, _IN, name="\u8fb9\u6846\u989c\u8272",
           default_val={"r": 0.373, "g": 0.373, "b": 0.373, "a": 0.686}),
        _p(I, _IN, name="\u6309\u94ae\u95f4\u9694", default_val=20),
        _p(V2, _IN, name="\u6309\u94ae\u5185\u8fb9\u8ddd",
           default_val={"x": 100.0, "y": 12.0}),
        _p(FL, _IN, name="\u5c4f\u5e55\u5e95\u90e8\u8ddd\u79bb", default_val=150.0),
        _p(FL, _IN, name="\u6309\u94ae\u6700\u5c0f\u5bbd\u5ea6", default_val=400.0),
    ),
    output_pins=(
        _p(F, _OUT, name="\u5206\u652f1"),
        _p(F, _OUT, name="\u5206\u652f2"),
        _p(F, _OUT, name="\u5206\u652f3"),
        _p(F, _OUT, name="\u5206\u652f4"),
        _p(F, _OUT, name="\u5206\u652f5"),
    ),
)

PLAY_VIDEO = NodeTypeDef(
    type_id="play_video",
    input_pins=(
        _p(F, _IN),
        _p(VID, _IN, default_val=""),
        _p(I, _IN, name="\u5e27\u7387", default_val=30),
        _p(V2, _IN, name="\u5206\u8fa8\u7387", default_val={"x": 1920.0, "y": 1080.0}),
        _p(FL, _IN, name="\u97f3\u91cf", default_val=1.0),
    ),
    output_pins=(_p(F, _OUT, name="       "),),
)

# ---- 5.3 Audio Nodes ----

PLAY_AUDIO = NodeTypeDef(
    type_id="play_audio",
    input_pins=(
        _p(F, _IN),
        _p(AUD, _IN, default_val=""),
        _p(I, _IN, name="\u5faa\u73af\u6b21\u6570", default_val=0),
        _p(FL, _IN, name="\u97f3\u91cf", default_val=1.0),
        _p(FL, _IN, name="\u6de1\u5165\u65f6\u95f4", default_val=0.0),
    ),
    output_pins=(
        _p(F, _OUT, name="       "),
        _p(I, _OUT, name="\u9891\u9053", default_val=0),
    ),
)

STOP_AUDIO = NodeTypeDef(
    type_id="stop_audio",
    input_pins=(
        _p(F, _IN),
        _p(I, _IN, name="\u9891\u9053", default_val=-1),
        _p(FL, _IN, name="\u6de1\u51fa\u65f6\u95f4", default_val=0.0),
    ),
    output_pins=(_p(F, _OUT, name="       "),),
)

STOP_ALL_AUDIO = NodeTypeDef(
    type_id="stop_all_audio",
    input_pins=(
        _p(F, _IN),
        _p(FL, _IN, name="\u6de1\u51fa\u65f6\u95f4", default_val=0.0),
    ),
    output_pins=(_p(F, _OUT, name="       "),),
)

# ---- 5.4 Object / Variable Nodes ----

FIND_OBJECT = NodeTypeDef(
    type_id="find_object",
    input_pins=(
        _p(F, _IN),
        _p(S, _IN, name="\u5bf9\u8c61ID", default_val=""),
    ),
    output_pins=(
        _p(F, _OUT, name="       "),
        _p(F, _OUT, name="\u5931\u8d25"),
        _p(OBJ, _OUT),
    ),
)

SAVE_GLOBAL = NodeTypeDef(
    type_id="save_global",
    input_pins=(
        _p(F, _IN),
        _p(S, _IN, name="\u952e", default_val=""),
        _p(OBJ, _IN, name="\u503c"),
    ),
    output_pins=(_p(F, _OUT),),
)

LOAD_GLOBAL = NodeTypeDef(
    type_id="load_global",
    input_pins=(
        _p(F, _IN),
        _p(S, _IN, name="\u952e", default_val=""),
    ),
    output_pins=(
        _p(F, _OUT, name="       "),
        _p(F, _OUT, name="\u5931\u8d25"),
        _p(OBJ, _OUT, name="   \u503c"),
    ),
)

# ---- 5.5 Value Nodes (pure data, no flow pins) ----

VECTOR2_LITERAL = NodeTypeDef(
    type_id="vector2",
    input_pins=(),
    output_pins=(_p(V2, _OUT, default_val={"x": 0.0, "y": 0.0}),),
)

COLOR_LITERAL = NodeTypeDef(
    type_id="color",
    input_pins=(),
    output_pins=(_p(C, _OUT, default_val={"r": 0.0, "g": 0.0, "b": 0.0, "a": 1.0}),),
)

STRING_LITERAL = NodeTypeDef(
    type_id="string",
    input_pins=(),
    output_pins=(_p(S, _OUT, default_val=""),),
)

INT_LITERAL = NodeTypeDef(
    type_id="int",
    input_pins=(),
    output_pins=(_p(I, _OUT, default_val=0),),
)

FLOAT_LITERAL = NodeTypeDef(
    type_id="float",
    input_pins=(),
    output_pins=(_p(FL, _OUT, default_val=0.0),),
)

BOOL_LITERAL = NodeTypeDef(
    type_id="bool",
    input_pins=(),
    output_pins=(_p(B, _OUT, default_val=False),),
)

# ---- 5.6 Asset Reference Nodes (pure data, no flow pins) ----

FONT_REF = NodeTypeDef(
    type_id="font",
    input_pins=(),
    output_pins=(_p(FNT, _OUT, default_val=""),),
)

AUDIO_REF = NodeTypeDef(
    type_id="audio",
    input_pins=(),
    output_pins=(_p(AUD, _OUT, default_val=""),),
)

VIDEO_REF = NodeTypeDef(
    type_id="video",
    input_pins=(),
    output_pins=(_p(VID, _OUT, default_val=""),),
)

SHADER_REF = NodeTypeDef(
    type_id="shader",
    input_pins=(),
    output_pins=(_p(SHD, _OUT, default_val=""),),
)

TEXTURE_REF = NodeTypeDef(
    type_id="texture",
    input_pins=(),
    output_pins=(_p(TEX, _OUT, default_val=""),),
)

# ---- 5.7 Math / Logic Nodes ----

RANDOM_INT = NodeTypeDef(
    type_id="random_int",
    input_pins=(
        _p(F, _IN),
        _p(I, _IN, name="\u6700\u5c0f\u503c", default_val=0),
        _p(I, _IN, name="\u6700\u5927\u503c", default_val=100),
    ),
    output_pins=(
        _p(F, _OUT, name="       "),
        _p(I, _OUT, default_val=0),
    ),
)

ASSEMBLE_VECTOR2 = NodeTypeDef(
    type_id="assemble_vector2",
    input_pins=(
        _p(F, _IN),
        _p(FL, _IN, name="X", default_val=0.0),
        _p(FL, _IN, name="Y", default_val=0.0),
    ),
    output_pins=(
        _p(F, _OUT, name="              "),
        _p(V2, _OUT, default_val={"x": 0.0, "y": 0.0}),
    ),
)

EQUAL = NodeTypeDef(
    type_id="equal",
    input_pins=(
        _p(F, _IN),
        _p(OBJ, _IN, name="\u5de6\u503c"),
        _p(OBJ, _IN, name="\u53f3\u503c"),
    ),
    output_pins=(
        _p(F, _OUT, name=""),
        _p(B, _OUT, name="", default_val=False),
    ),
)

LESS = NodeTypeDef(
    type_id="less",
    input_pins=(
        _p(F, _IN),
        _p(OBJ, _IN, name="\u5de6\u503c"),
        _p(OBJ, _IN, name="\u53f3\u503c"),
        _p(B, _IN, name="\u5305\u542b\u4e34\u754c\u503c", default_val=False),
    ),
    output_pins=(
        _p(F, _OUT, name=""),
        _p(B, _OUT, name="", default_val=False),
    ),
)

GREATER = NodeTypeDef(
    type_id="greater",
    input_pins=(
        _p(F, _IN),
        _p(OBJ, _IN, name="\u5de6\u503c"),
        _p(OBJ, _IN, name="\u53f3\u503c"),
        _p(B, _IN, name="\u5305\u542b\u4e34\u754c\u503c", default_val=False),
    ),
    output_pins=(
        _p(F, _OUT, name=""),
        _p(B, _OUT, name="", default_val=False),
    ),
)

FLOOR = NodeTypeDef(
    type_id="floor",
    input_pins=(
        _p(F, _IN),
        _p(FL, _IN, name="", default_val=0.0),
    ),
    output_pins=(
        _p(F, _OUT, name=""),
        _p(I, _OUT, name="", default_val=0),
    ),
)

CEIL = NodeTypeDef(
    type_id="ceil",
    input_pins=(
        _p(F, _IN),
        _p(FL, _IN, name="", default_val=0.0),
    ),
    output_pins=(
        _p(F, _OUT, name=""),
        _p(I, _OUT, name="", default_val=0),
    ),
)

ROUND = NodeTypeDef(
    type_id="round",
    input_pins=(
        _p(F, _IN),
        _p(FL, _IN, name="", default_val=0.0),
    ),
    output_pins=(
        _p(F, _OUT, name=""),
        _p(I, _OUT, name="", default_val=0),
    ),
)

# ---- 5.8 Utility Nodes ----

COMMENT = NodeTypeDef(
    type_id="comment",
    input_pins=(),
    output_pins=(),
    extra_fields=("text", "size"),
)

EXTEND_PINS = NodeTypeDef(
    type_id="extend_pins",
    input_pins=(
        _p(F, _IN),
        _p(OBJ, _IN, name="\u5bf9\u8c61"),
    ),
    output_pins=(
        _p(F, _OUT, name="         "),
        _p(OBJ, _OUT, name="\u6269\u5c551"),
        _p(OBJ, _OUT, name="\u6269\u5c552"),
        _p(OBJ, _OUT, name="\u6269\u5c553"),
    ),
)

MERGE_FLOW = NodeTypeDef(
    type_id="merge_flow",
    input_pins=(
        _p(F, _IN, name="\u6d41\u7a0b1"),
        _p(F, _IN, name="\u6d41\u7a0b2"),
        _p(F, _IN, name="\u6d41\u7a0b3"),
    ),
    output_pins=(_p(F, _OUT),),
)

PRINT = NodeTypeDef(
    type_id="print",
    input_pins=(
        _p(F, _IN),
        _p(OBJ, _IN, name="\u503c"),
    ),
    output_pins=(_p(F, _OUT),),
)

# ---------------------------------------------------------------------------
# Registry -- maps type_id string to NodeTypeDef
# ---------------------------------------------------------------------------

NODE_CATALOG: dict[str, NodeTypeDef] = {}

def _register_all() -> None:
    """Register all 46 node types in the catalog."""
    import sys
    module = sys.modules[__name__]
    for attr_name in dir(module):
        val = getattr(module, attr_name)
        if isinstance(val, NodeTypeDef):
            NODE_CATALOG[val.type_id] = val

_register_all()


def get_node_type(type_id: str) -> NodeTypeDef:
    """Look up a node type definition by its type_id string.

    Raises:
        KeyError: If the type_id is not in the catalog.
    """
    if type_id not in NODE_CATALOG:
        raise KeyError(f"Unknown node type: {type_id!r}. Valid types: {sorted(NODE_CATALOG)}")
    return NODE_CATALOG[type_id]


# ---------------------------------------------------------------------------
# FlowNode -- a concrete node instance in a graph
# ---------------------------------------------------------------------------

@dataclass
class FlowNode:
    """A concrete node instance in a VNE flow graph.

    Created by ``FlowGraph.add_node()`` which assigns IDs.
    """

    id: int
    type_id: str
    position: dict[str, int] = field(default_factory=lambda: {"x": 0, "y": 0})
    input_pins: list[Pin] = field(default_factory=list)
    output_pins: list[Pin] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def get_input_pin(self, index: int) -> Pin:
        """Return the input pin at the given index."""
        return self.input_pins[index]

    def get_output_pin(self, index: int) -> Pin:
        """Return the output pin at the given index."""
        return self.output_pins[index]

    @property
    def flow_input_pin(self) -> Pin | None:
        """Return the first flow-type input pin, or None."""
        for pin in self.input_pins:
            if pin.type_id == PinType.FLOW:
                return pin
        return None

    @property
    def flow_output_pin(self) -> Pin | None:
        """Return the first flow-type output pin, or None."""
        for pin in self.output_pins:
            if pin.type_id == PinType.FLOW:
                return pin
        return None
