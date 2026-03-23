"""Comprehensive tests for the flow generation system.

Covers:
- ID generation (monotonic, shared counter)
- Link serialization (counterintuitive naming)
- Pin compatibility validation
- Minimal flow: entry -> dialog -> wait_interaction
- Branching flow: entry -> choice -> two paths -> merge
- Scene compilation from sample story data
- Node catalog completeness (46 types)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vne_cli.flow.graph import FlowGraph, Link
from vne_cli.flow.nodes import FlowNode, NODE_CATALOG, get_node_type
from vne_cli.flow.pins import Pin, PinType, pins_compatible
from vne_cli.flow.scene_compiler import compile_scene
from vne_cli.flow.serializer import serialize_flow, write_flow_file
from vne_cli.schemas.story import Beat, BeatType, BranchInfo, ChoiceOption, Scene


# =====================================================================
# Node catalog
# =====================================================================

class TestNodeCatalog:
    """Verify the node catalog has all 46 types."""

    def test_catalog_has_all_types(self) -> None:
        # The spec summary says "46" but the actual enumerated table has 50 entries.
        # 5 control + 16 staging + 3 audio + 3 obj/var + 6 value + 8 math/logic + 5 asset + 4 utility = 50.
        assert len(NODE_CATALOG) == 50, (
            f"Expected 50 node types, got {len(NODE_CATALOG)}: "
            f"{sorted(NODE_CATALOG.keys())}"
        )

    def test_entry_node_in_catalog(self) -> None:
        entry = get_node_type("entry")
        assert entry.type_id == "entry"
        assert len(entry.input_pins) == 0
        assert len(entry.output_pins) == 1
        assert entry.output_pins[0].type_id == PinType.FLOW

    def test_show_dialog_box_pin_count(self) -> None:
        dialog = get_node_type("show_dialog_box")
        assert len(dialog.input_pins) == 14  # 1 flow + 13 data
        assert len(dialog.output_pins) == 2  # 1 flow + 1 object

    def test_show_choice_button_outputs(self) -> None:
        choice = get_node_type("show_choice_button")
        assert len(choice.output_pins) == 5  # 5 branch flow outputs
        for pin_spec in choice.output_pins:
            assert pin_spec.type_id == PinType.FLOW

    def test_comment_node_has_no_pins(self) -> None:
        comment = get_node_type("comment")
        assert len(comment.input_pins) == 0
        assert len(comment.output_pins) == 0
        assert "text" in comment.extra_fields
        assert "size" in comment.extra_fields

    def test_unknown_type_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="Unknown node type"):
            get_node_type("nonexistent_node")


# =====================================================================
# ID generation
# =====================================================================

class TestIDGeneration:
    """Verify shared monotonic counter for nodes, pins, and links."""

    def test_entry_node_ids(self) -> None:
        """Entry node: node ID=1, output flow pin ID=2, max_uid=2."""
        graph = FlowGraph()
        entry = graph.add_node("entry")
        assert entry.id == 1
        assert entry.output_pins[0].id == 2
        assert graph.max_uid == 2

    def test_sequential_node_ids(self) -> None:
        """Second node gets IDs continuing from where first left off."""
        graph = FlowGraph()
        entry = graph.add_node("entry")  # IDs: 1 (node), 2 (pin) => max_uid=2
        delay = graph.add_node("delay")  # IDs: 3 (node), 4 (flow in), 5 (float in), 6 (flow out)
        assert delay.id == 3
        assert delay.input_pins[0].id == 4  # flow input
        assert delay.input_pins[1].id == 5  # float input (seconds)
        assert delay.output_pins[0].id == 6  # flow output
        assert graph.max_uid == 6

    def test_link_consumes_uid(self) -> None:
        """Links also consume from the shared counter."""
        graph = FlowGraph()
        entry = graph.add_node("entry")       # IDs: 1, 2
        wait = graph.add_node("wait_interaction")  # IDs: 3, 4, 5, 6
        link = graph.connect_flow(entry, wait)
        assert link.id == 7  # next after pin 6
        assert graph.max_uid == 7

    def test_no_duplicate_ids(self) -> None:
        """All IDs across a multi-node graph are unique."""
        graph = FlowGraph()
        entry = graph.add_node("entry")
        bg = graph.add_node("switch_background")
        dialog = graph.add_node("show_dialog_box")
        graph.connect_flow(entry, bg)
        graph.connect_flow(bg, dialog)

        all_ids: list[int] = []
        for node in graph.nodes:
            all_ids.append(node.id)
            for pin in node.input_pins + node.output_pins:
                all_ids.append(pin.id)
        for link in graph.links:
            all_ids.append(link.id)

        assert len(all_ids) == len(set(all_ids)), f"Duplicate IDs found: {all_ids}"

    def test_max_uid_matches_highest_id(self) -> None:
        """max_uid always equals the highest assigned ID."""
        graph = FlowGraph()
        graph.add_node("entry")
        graph.add_node("delay")
        assert graph.max_uid == max(
            [n.id for n in graph.nodes]
            + [p.id for n in graph.nodes for p in n.input_pins + n.output_pins]
        )


# =====================================================================
# Pin compatibility
# =====================================================================

class TestPinCompatibility:
    """Test pin type connection rules from spec Section 4.4."""

    def test_same_type_compatible(self) -> None:
        assert pins_compatible(PinType.FLOW, PinType.FLOW)
        assert pins_compatible(PinType.STRING, PinType.STRING)
        assert pins_compatible(PinType.INT, PinType.INT)

    def test_flow_only_connects_to_flow(self) -> None:
        assert not pins_compatible(PinType.FLOW, PinType.STRING)
        assert not pins_compatible(PinType.STRING, PinType.FLOW)
        assert not pins_compatible(PinType.FLOW, PinType.OBJECT)

    def test_object_accepts_any_non_flow(self) -> None:
        for pt in PinType:
            if pt is not PinType.FLOW:
                assert pins_compatible(pt, PinType.OBJECT), f"{pt} -> object should work"
                assert pins_compatible(PinType.OBJECT, pt), f"object -> {pt} should work"

    def test_int_to_float_compatible(self) -> None:
        assert pins_compatible(PinType.INT, PinType.FLOAT)

    def test_float_to_int_not_compatible(self) -> None:
        assert not pins_compatible(PinType.FLOAT, PinType.INT)

    def test_incompatible_types(self) -> None:
        assert not pins_compatible(PinType.STRING, PinType.INT)
        assert not pins_compatible(PinType.BOOL, PinType.TEXTURE)
        assert not pins_compatible(PinType.AUDIO, PinType.VIDEO)


# =====================================================================
# Link serialization
# =====================================================================

class TestLinkSerialization:
    """Test the counterintuitive link naming in serialized output."""

    def test_link_field_naming(self) -> None:
        """input_pin_id = source OUTPUT pin, output_pin_id = dest INPUT pin."""
        graph = FlowGraph()
        entry = graph.add_node("entry")       # node=1, out_flow_pin=2
        wait = graph.add_node("wait_interaction")  # node=3, in_flow_pin=4, ...
        graph.connect_flow(entry, wait)

        data = serialize_flow(graph)
        link = data["link_pool"][0]

        # entry's output pin (is_output=True) -> input_pin_id
        assert link["input_pin_id"] == entry.output_pins[0].id
        # wait's input pin (is_output=False) -> output_pin_id
        assert link["output_pin_id"] == wait.input_pins[0].id

    def test_serialized_link_has_three_fields(self) -> None:
        graph = FlowGraph()
        entry = graph.add_node("entry")
        wait = graph.add_node("wait_interaction")
        graph.connect_flow(entry, wait)

        data = serialize_flow(graph)
        link = data["link_pool"][0]
        assert set(link.keys()) == {"id", "input_pin_id", "output_pin_id"}

    def test_max_uid_in_output(self) -> None:
        graph = FlowGraph()
        entry = graph.add_node("entry")
        wait = graph.add_node("wait_interaction")
        graph.connect_flow(entry, wait)

        data = serialize_flow(graph)
        assert data["max_uid"] == graph.max_uid
        assert data["is_open"] is True


# =====================================================================
# Pin serialization
# =====================================================================

class TestPinSerialization:
    """Test pin value serialization rules."""

    def test_flow_pin_no_val(self) -> None:
        """Flow pins omit the val field."""
        pin = Pin(id=1, type_id=PinType.FLOW, is_output=True)
        s = pin.serialize()
        assert "val" not in s
        assert s["type_id"] == "flow"
        assert s["is_output"] is True

    def test_flow_pin_no_name_omitted(self) -> None:
        """Flow pins without a name omit the name field."""
        pin = Pin(id=1, type_id=PinType.FLOW, is_output=False)
        s = pin.serialize()
        assert "name" not in s

    def test_flow_pin_with_name(self) -> None:
        """Flow pins with a name include it."""
        pin = Pin(id=1, type_id=PinType.FLOW, is_output=True, name="\u771f")
        s = pin.serialize()
        assert s["name"] == "\u771f"

    def test_string_pin_has_val(self) -> None:
        pin = Pin(id=1, type_id=PinType.STRING, is_output=False, name="text", val="hello")
        s = pin.serialize()
        assert s["val"] == "hello"
        assert s["name"] == "text"

    def test_color_pin_serialization(self) -> None:
        color_val = {"r": 0.95, "g": 0.95, "b": 0.95, "a": 1.0}
        pin = Pin(id=1, type_id=PinType.COLOR, is_output=False, name="color", val=color_val)
        s = pin.serialize()
        assert s["val"] == color_val

    def test_object_pin_no_val(self) -> None:
        """Object pins do not have a serialized val."""
        pin = Pin(id=1, type_id=PinType.OBJECT, is_output=True, name="obj")
        s = pin.serialize()
        assert "val" not in s


# =====================================================================
# Node serialization
# =====================================================================

class TestNodeSerialization:
    """Test node serialization in the .flow format."""

    def test_entry_node_serialization(self) -> None:
        graph = FlowGraph()
        entry = graph.add_node("entry")
        data = serialize_flow(graph)

        node = data["node_pool"][0]
        assert node["id"] == 1
        assert node["type_id"] == "entry"
        assert node["input_pin_list"] == []
        assert len(node["output_pin_list"]) == 1
        assert node["output_pin_list"][0]["type_id"] == "flow"
        assert node["output_pin_list"][0]["is_output"] is True

    def test_comment_node_extra_fields(self) -> None:
        graph = FlowGraph()
        graph.add_node("entry")  # Need entry for valid graph.
        comment = graph.add_node("comment", extra={
            "text": "A note",
            "size": {"x": 300, "y": 0},
        })
        data = serialize_flow(graph)
        comment_data = [n for n in data["node_pool"] if n["type_id"] == "comment"][0]
        assert comment_data["text"] == "A note"
        assert comment_data["size"] == {"x": 300, "y": 0}

    def test_switch_background_pin_values(self) -> None:
        graph = FlowGraph()
        bg = graph.add_node("switch_background", pin_overrides={1: "classroom"})
        data = serialize_flow(graph)
        node = data["node_pool"][0]
        # Pin index 1 = texture pin.
        texture_pin = node["input_pin_list"][1]
        assert texture_pin["val"] == "classroom"
        assert texture_pin["type_id"] == "texture"


# =====================================================================
# Minimal flow: entry -> dialog -> wait_interaction
# =====================================================================

class TestMinimalFlow:
    """Test building and serializing a minimal but complete flow."""

    def test_entry_dialog_wait(self) -> None:
        graph = FlowGraph()

        entry = graph.add_node("entry")
        dialog = graph.add_node("show_dialog_box", pin_overrides={
            1: "Elena",
            2: "I never expected to find this here.",
        })
        wait = graph.add_node("wait_interaction")

        graph.connect_flow(entry, dialog)
        graph.connect_flow(dialog, wait)

        # Validate.
        errors = graph.validate()
        assert errors == [], f"Validation errors: {errors}"

        # Serialize and check structure.
        data = serialize_flow(graph)
        assert len(data["node_pool"]) == 3
        assert len(data["link_pool"]) == 2
        assert data["max_uid"] == graph.max_uid

        # Verify dialog pin values.
        dialog_node = [n for n in data["node_pool"] if n["type_id"] == "show_dialog_box"][0]
        assert dialog_node["input_pin_list"][1]["val"] == "Elena"
        assert dialog_node["input_pin_list"][2]["val"] == "I never expected to find this here."

    def test_write_and_read_flow_file(self, tmp_path: Path) -> None:
        graph = FlowGraph()
        entry = graph.add_node("entry")
        wait = graph.add_node("wait_interaction")
        graph.connect_flow(entry, wait)

        flow_path = tmp_path / "test.flow"
        write_flow_file(graph, flow_path)

        assert flow_path.exists()
        data = json.loads(flow_path.read_text(encoding="utf-8"))
        assert data["max_uid"] == graph.max_uid
        assert data["is_open"] is True
        assert len(data["node_pool"]) == 2
        assert len(data["link_pool"]) == 1


# =====================================================================
# Branching flow: entry -> choice -> two paths -> merge
# =====================================================================

class TestBranchingFlow:
    """Test choice-based branching with merge."""

    def test_choice_two_paths_merge(self) -> None:
        graph = FlowGraph()

        entry = graph.add_node("entry")
        choice = graph.add_node("show_choice_button", pin_overrides={
            1: "Option A",
            2: "Option B",
        })
        graph.connect_flow(entry, choice)

        # Branch A: a dialog node.
        dialog_a = graph.add_node("show_dialog_box", pin_overrides={
            1: "Elena",
            2: "I chose option A.",
        })
        graph.connect(choice, 0, dialog_a, 0)  # choice branch1 -> dialog_a flow in

        # Branch B: a different dialog node.
        dialog_b = graph.add_node("show_dialog_box", pin_overrides={
            1: "Elena",
            2: "I chose option B.",
        })
        graph.connect(choice, 1, dialog_b, 0)  # choice branch2 -> dialog_b flow in

        # Merge.
        merge = graph.add_node("merge_flow")
        graph.connect_flow(dialog_a, merge)
        graph.connect_flow(dialog_b, merge)

        # Continue after merge.
        wait = graph.add_node("wait_interaction")
        graph.connect_flow(merge, wait)

        errors = graph.validate()
        assert errors == [], f"Validation errors: {errors}"

        data = serialize_flow(graph)
        assert len(data["node_pool"]) == 6  # entry, choice, 2 dialogs, merge, wait
        assert len(data["link_pool"]) == 6  # entry->choice, choice->A, choice->B, A->merge, B->merge, merge->wait

    def test_connect_incompatible_raises(self) -> None:
        """Connecting flow to string pin raises ValueError."""
        graph = FlowGraph()
        entry = graph.add_node("entry")
        bg = graph.add_node("switch_background")
        # entry output[0] is flow, bg input[1] is texture.
        with pytest.raises(ValueError, match="Incompatible pin types"):
            graph.connect(entry, 0, bg, 1)

    def test_self_connection_raises(self) -> None:
        graph = FlowGraph()
        # Use a node that has both flow input and output.
        delay = graph.add_node("delay")
        with pytest.raises(ValueError, match="Cannot connect a node to itself"):
            graph.connect(delay, 0, delay, 0)


# =====================================================================
# Graph validation
# =====================================================================

class TestGraphValidation:
    """Test the validate() method."""

    def test_valid_graph_no_errors(self) -> None:
        graph = FlowGraph()
        entry = graph.add_node("entry")
        wait = graph.add_node("wait_interaction")
        graph.connect_flow(entry, wait)
        assert graph.validate() == []

    def test_no_entry_node(self) -> None:
        graph = FlowGraph()
        graph.add_node("wait_interaction")
        errors = graph.validate()
        assert any("No entry node" in e for e in errors)

    def test_multiple_entry_nodes(self) -> None:
        graph = FlowGraph()
        graph.add_node("entry")
        graph.add_node("entry")
        errors = graph.validate()
        assert any("Multiple entry nodes" in e for e in errors)


# =====================================================================
# Scene compilation
# =====================================================================

class TestSceneCompilation:
    """Test compiling Scene objects into FlowGraphs."""

    def _make_simple_scene(self) -> Scene:
        return Scene(
            id="ch_001_sc_001",
            title="The Library",
            background_description="Castle library",
            characters_present=["char_001"],
            beats=[
                Beat(
                    type=BeatType.DIALOGUE,
                    character="char_001",
                    expression="neutral",
                    text="I never expected to find this here.",
                ),
                Beat(
                    type=BeatType.NARRATION,
                    text="The dust motes drifted through the amber light.",
                ),
            ],
        )

    def test_simple_scene_compiles(self) -> None:
        scene = self._make_simple_scene()
        graph = compile_scene(scene, characters={"char_001": {"name": "Elena"}})

        errors = graph.validate()
        assert errors == [], f"Validation errors: {errors}"

        # Should have: entry, switch_background, add_foreground, show_dialog_box, show_subtitle.
        type_ids = [n.type_id for n in graph.nodes]
        assert "entry" in type_ids
        assert "switch_background" in type_ids
        assert "add_foreground" in type_ids
        assert "show_dialog_box" in type_ids
        assert "show_subtitle" in type_ids

    def test_dialogue_uses_character_name(self) -> None:
        scene = Scene(
            id="test",
            beats=[
                Beat(type=BeatType.DIALOGUE, character="char_001", text="Hello."),
            ],
        )
        graph = compile_scene(scene, characters={"char_001": {"name": "Elena"}})
        data = serialize_flow(graph)

        dialog_nodes = [n for n in data["node_pool"] if n["type_id"] == "show_dialog_box"]
        assert len(dialog_nodes) == 1
        # Pin index 1 = character name.
        assert dialog_nodes[0]["input_pin_list"][1]["val"] == "Elena"

    def test_choice_scene_compiles(self) -> None:
        scene = Scene(
            id="choice_test",
            beats=[
                Beat(
                    type=BeatType.CHOICE,
                    text="What should Elena do?",
                    options=[
                        ChoiceOption(text="Read immediately", target_scene="sc_002a", consequence_tag="impulsive"),
                        ChoiceOption(text="Hide it", target_scene="sc_002b", consequence_tag="cautious"),
                    ],
                ),
            ],
        )
        graph = compile_scene(scene)

        errors = graph.validate()
        assert errors == [], f"Validation errors: {errors}"

        type_ids = [n.type_id for n in graph.nodes]
        assert "show_choice_button" in type_ids
        assert "merge_flow" in type_ids
        assert type_ids.count("save_global") == 2  # One per consequence tag.

    def test_transition_beat(self) -> None:
        scene = Scene(
            id="trans_test",
            beats=[
                Beat(type=BeatType.TRANSITION, style="fade", duration_ms=1000),
            ],
        )
        graph = compile_scene(scene)
        type_ids = [n.type_id for n in graph.nodes]
        assert "transition_fade_out" in type_ids
        assert "transition_fade_in" in type_ids

    def test_direction_play_audio(self) -> None:
        scene = Scene(
            id="audio_test",
            beats=[
                Beat(type=BeatType.DIRECTION, text="play audio bgm_01"),
            ],
        )
        graph = compile_scene(scene)
        data = serialize_flow(graph)
        audio_nodes = [n for n in data["node_pool"] if n["type_id"] == "play_audio"]
        assert len(audio_nodes) == 1
        # Audio asset pin is index 1.
        assert audio_nodes[0]["input_pin_list"][1]["val"] == "bgm_01"

    def test_direction_letterboxing(self) -> None:
        scene = Scene(
            id="lb_test",
            beats=[
                Beat(type=BeatType.DIRECTION, text="show letterboxing"),
                Beat(type=BeatType.NARRATION, text="Narration text."),
                Beat(type=BeatType.DIRECTION, text="hide letterboxing"),
            ],
        )
        graph = compile_scene(scene)
        type_ids = [n.type_id for n in graph.nodes]
        assert "show_letterboxing" in type_ids
        assert "hide_letterboxing" in type_ids

    def test_empty_scene_compiles(self) -> None:
        scene = Scene(id="empty")
        graph = compile_scene(scene)
        errors = graph.validate()
        assert errors == []
        assert any(n.type_id == "entry" for n in graph.nodes)

    def test_scene_serialization_roundtrip(self, tmp_path: Path) -> None:
        """Compile a scene, write to disk, and validate the JSON structure."""
        scene = self._make_simple_scene()
        graph = compile_scene(scene, characters={"char_001": {"name": "Elena"}})

        path = tmp_path / "scene.flow"
        write_flow_file(graph, path)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert "max_uid" in data
        assert "node_pool" in data
        assert "link_pool" in data
        assert "is_open" in data
        assert data["max_uid"] > 0

        # Verify all link pin references exist in the node pool.
        all_pin_ids: set[int] = set()
        for node in data["node_pool"]:
            for pin in node["input_pin_list"] + node["output_pin_list"]:
                all_pin_ids.add(pin["id"])

        for link in data["link_pool"]:
            assert link["input_pin_id"] in all_pin_ids, (
                f"Link {link['id']}: input_pin_id {link['input_pin_id']} not found."
            )
            assert link["output_pin_id"] in all_pin_ids, (
                f"Link {link['id']}: output_pin_id {link['output_pin_id']} not found."
            )


# =====================================================================
# Auto-layout
# =====================================================================

class TestAutoLayout:
    """Test the auto-layout system."""

    def test_layout_assigns_positions(self) -> None:
        graph = FlowGraph()
        entry = graph.add_node("entry")
        wait = graph.add_node("wait_interaction")
        graph.connect_flow(entry, wait)
        graph.auto_layout()

        # Entry should be at column 0, wait at column 1.
        assert entry.position["x"] < wait.position["x"]

    def test_branching_layout_spreads_vertically(self) -> None:
        graph = FlowGraph()
        entry = graph.add_node("entry")
        choice = graph.add_node("show_choice_button", pin_overrides={1: "A", 2: "B"})
        graph.connect_flow(entry, choice)

        branch_a = graph.add_node("wait_interaction")
        branch_b = graph.add_node("wait_interaction")
        graph.connect(choice, 0, branch_a, 0)
        graph.connect(choice, 1, branch_b, 0)

        graph.auto_layout()

        # Branches should have different Y positions.
        assert branch_a.position["y"] != branch_b.position["y"]
