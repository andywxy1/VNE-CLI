"""Compile a Scene from story data into a FlowGraph.

Maps narrative beats (dialogue, narration, choices, transitions, etc.)
to VNE flow node sequences with proper connections.
"""

from __future__ import annotations

from typing import Any

from vne_cli.flow.graph import FlowGraph
from vne_cli.flow.nodes import FlowNode
from vne_cli.schemas.story import Beat, BeatType, Scene


def compile_scene(scene: Scene, *, characters: dict[str, Any] | None = None) -> FlowGraph:
    """Compile a single Scene into a FlowGraph.

    Args:
        scene: The scene to compile.
        characters: Optional character registry (id -> CharacterRef-like dict)
            for resolving character names from IDs.

    Returns:
        A complete FlowGraph for this scene.
    """
    characters = characters or {}
    graph = FlowGraph()
    compiler = _SceneCompiler(graph, scene, characters)
    compiler.compile()
    graph.auto_layout()
    return graph


class _SceneCompiler:
    """Internal compiler that walks beats and emits nodes."""

    def __init__(
        self,
        graph: FlowGraph,
        scene: Scene,
        characters: dict[str, Any],
    ) -> None:
        self.graph = graph
        self.scene = scene
        self.characters = characters
        # The "current" node whose flow output we connect the next node to.
        self._current: FlowNode | None = None
        # Track foreground objects by character ID for enter/exit.
        self._fg_objects: dict[str, FlowNode] = {}

    def compile(self) -> None:
        """Run the full compilation."""
        # 1. Entry node.
        entry = self.graph.add_node("entry")
        self._current = entry

        # 2. Scene background (if described).
        if self.scene.background_description:
            bg_texture_id = _scene_to_texture_id(self.scene.id)
            self._emit_switch_background(bg_texture_id)

        # 3. Add foreground sprites for characters present at scene start.
        for char_id in self.scene.characters_present:
            self._emit_add_foreground(char_id)

        # 4. Walk beats.
        for beat in self.scene.beats:
            self._compile_beat(beat)

    def _chain(self, node: FlowNode) -> None:
        """Connect current node's flow output to *node*'s flow input, then advance."""
        if self._current is not None:
            self.graph.connect_flow(self._current, node)
        self._current = node

    def _compile_beat(self, beat: Beat) -> None:
        """Dispatch a beat to the appropriate emitter."""
        if beat.type == BeatType.DIALOGUE:
            self._compile_dialogue(beat)
        elif beat.type == BeatType.NARRATION:
            self._compile_narration(beat)
        elif beat.type == BeatType.CHOICE:
            self._compile_choice(beat)
        elif beat.type == BeatType.TRANSITION:
            self._compile_transition(beat)
        elif beat.type == BeatType.DIRECTION:
            self._compile_direction(beat)

    # ------------------------------------------------------------------
    # Beat compilers
    # ------------------------------------------------------------------

    def _compile_dialogue(self, beat: Beat) -> None:
        """Dialogue beat -> show_dialog_box with character name and text."""
        char_name = self._resolve_character_name(beat.character)
        # Pin overrides: index 1 = character text, index 2 = content text.
        overrides: dict[int, Any] = {
            1: char_name,
            2: beat.text,
        }
        node = self.graph.add_node("show_dialog_box", pin_overrides=overrides)
        self._chain(node)

    def _compile_narration(self, beat: Beat) -> None:
        """Narration beat -> show_subtitle with text."""
        overrides: dict[int, Any] = {
            1: beat.text,
        }
        node = self.graph.add_node("show_subtitle", pin_overrides=overrides)
        self._chain(node)

    def _compile_choice(self, beat: Beat) -> None:
        """Choice beat -> show_choice_button with branches, then merge_flow."""
        options = beat.options
        if not options:
            return

        # Build pin overrides for choice texts (pins 1-5).
        overrides: dict[int, Any] = {}
        for i, opt in enumerate(options[:5]):
            overrides[1 + i] = opt.text

        choice_node = self.graph.add_node("show_choice_button", pin_overrides=overrides)
        self._chain(choice_node)

        # For each option, create a branch content sequence.
        # Each branch saves a consequence tag to globals and then flows to merge.
        branch_ends: list[FlowNode] = []
        for i, opt in enumerate(options[:5]):
            # Save consequence tag if present.
            if opt.consequence_tag:
                save_node = self.graph.add_node("save_global", pin_overrides={
                    1: opt.consequence_tag,  # key
                })
                # Connect choice output pin [i] to save_node flow input.
                self.graph.connect(choice_node, i, save_node, 0)
                branch_ends.append(save_node)
            else:
                # Create a wait_interaction as a placeholder branch node.
                wait_node = self.graph.add_node("wait_interaction")
                self.graph.connect(choice_node, i, wait_node, 0)
                branch_ends.append(wait_node)

        # Merge the branches back together.
        merge_node = self.graph.add_node("merge_flow")
        for i, end_node in enumerate(branch_ends[:3]):
            self.graph.connect_flow(end_node, merge_node)

        # If more than 3 branches, chain additional merge nodes.
        if len(branch_ends) > 3:
            merge2 = self.graph.add_node("merge_flow")
            for end_node in branch_ends[3:]:
                self.graph.connect_flow(end_node, merge2)
            # Connect merge2 output to merge1's remaining input.
            self.graph.connect_flow(merge2, merge_node)

        self._current = merge_node

    def _compile_transition(self, beat: Beat) -> None:
        """Transition beat -> transition_fade_out + transition_fade_in."""
        duration_s = (beat.duration_ms or 500) / 1000.0

        if beat.style == "fade" or beat.style is None:
            fade_out = self.graph.add_node("transition_fade_out", pin_overrides={
                1: duration_s,
            })
            self._chain(fade_out)

            fade_in = self.graph.add_node("transition_fade_in", pin_overrides={
                1: duration_s,
            })
            self._chain(fade_in)
        else:
            # Default: just a delay.
            delay = self.graph.add_node("delay", pin_overrides={
                1: duration_s,
            })
            self._chain(delay)

    def _compile_direction(self, beat: Beat) -> None:
        """Stage direction beat -- interpret text-based directions.

        Directions use the ``text`` field with keywords like:
        - "play audio <id>"
        - "stop audio"
        - "show letterboxing"
        - "hide letterboxing"
        - "play video <id>"
        - "enter <character_id>"
        - "exit <character_id>"

        If the direction text does not match a known pattern, we emit a
        comment node so the information is preserved but does not break flow.
        """
        text_lower = beat.text.lower().strip()

        if text_lower.startswith("play audio "):
            audio_id = beat.text.strip().split(" ", 2)[-1]
            node = self.graph.add_node("play_audio", pin_overrides={1: audio_id})
            self._chain(node)

        elif text_lower.startswith("stop audio"):
            node = self.graph.add_node("stop_all_audio")
            self._chain(node)

        elif text_lower == "show letterboxing":
            node = self.graph.add_node("show_letterboxing")
            self._chain(node)

        elif text_lower == "hide letterboxing":
            node = self.graph.add_node("hide_letterboxing")
            self._chain(node)

        elif text_lower.startswith("play video "):
            video_id = beat.text.strip().split(" ", 2)[-1]
            node = self.graph.add_node("play_video", pin_overrides={1: video_id})
            self._chain(node)

        elif text_lower.startswith("enter "):
            char_id = beat.text.strip().split(" ", 1)[-1]
            self._emit_add_foreground(char_id)

        elif text_lower.startswith("exit "):
            char_id = beat.text.strip().split(" ", 1)[-1]
            self._emit_remove_foreground(char_id)

        elif text_lower.startswith("delay "):
            try:
                seconds = float(beat.text.strip().split(" ", 1)[-1])
            except ValueError:
                seconds = 1.0
            node = self.graph.add_node("delay", pin_overrides={1: seconds})
            self._chain(node)

        else:
            # Unrecognized direction: emit as comment node.
            node = self.graph.add_node("comment", extra={
                "text": beat.text,
                "size": {"x": 300, "y": 0},
            })
            # Comment nodes have no flow pins, so do not chain.

    # ------------------------------------------------------------------
    # Staging helpers
    # ------------------------------------------------------------------

    def _emit_switch_background(self, texture_id: str) -> None:
        """Emit a switch_background node."""
        node = self.graph.add_node("switch_background", pin_overrides={
            1: texture_id,
        })
        self._chain(node)

    def _emit_add_foreground(self, char_id: str) -> None:
        """Emit an add_foreground node for a character sprite."""
        texture_id = _char_to_texture_id(char_id)
        node = self.graph.add_node("add_foreground", pin_overrides={
            3: texture_id,  # texture pin is index 3
        })
        self._chain(node)
        self._fg_objects[char_id] = node

    def _emit_remove_foreground(self, char_id: str) -> None:
        """Emit a remove_foreground node for a character sprite.

        If we have the add_foreground node that created this character's
        foreground object, connect its object output to the remove node's
        object input.
        """
        node = self.graph.add_node("remove_foreground")
        self._chain(node)

        # Connect the foreground object reference if available.
        add_node = self._fg_objects.pop(char_id, None)
        if add_node is not None:
            # add_foreground output pin index 1 = object.
            # remove_foreground input pin index 1 = object.
            self.graph.connect(add_node, 1, node, 1)

    # ------------------------------------------------------------------
    # Name resolution
    # ------------------------------------------------------------------

    def _resolve_character_name(self, char_id: str | None) -> str:
        """Resolve a character ID to a display name."""
        if not char_id:
            return ""
        char = self.characters.get(char_id)
        if char is not None:
            if hasattr(char, "name"):
                return char.name
            if isinstance(char, dict):
                return char.get("name", char_id)
        return char_id


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

def _scene_to_texture_id(scene_id: str) -> str:
    """Convert a scene ID to a background texture asset ID."""
    return scene_id.replace(" ", "_").lower()


def _char_to_texture_id(char_id: str, expression: str = "neutral") -> str:
    """Convert a character ID + expression to a sprite texture asset ID."""
    return f"{char_id}_{expression}"
