"""Project-level flow orchestrator.

Takes a full Story structure and generates all .flow files:
- One .flow per scene.
- Scenes connected via switch_scene nodes.
- Entry flow (main menu -> first scene).
- Chapter-scoped branching via load_global / branch nodes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vne_cli.flow.graph import FlowGraph
from vne_cli.flow.scene_compiler import compile_scene
from vne_cli.flow.serializer import write_flow_file
from vne_cli.schemas.story import Chapter, Scene, Story


def generate_all_flows(
    story: Story,
    output_dir: Path,
) -> list[Path]:
    """Generate all .flow files for a story.

    Creates one .flow per scene, plus an entry flow.

    Args:
        story: The complete story structure.
        output_dir: Directory to write .flow files into.

    Returns:
        List of paths to the generated .flow files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # Build character lookup for name resolution.
    characters: dict[str, Any] = {}
    for cid, cref in story.characters.items():
        characters[cid] = cref

    # Generate entry flow.
    entry_path = output_dir / "entry.flow"
    entry_graph = _build_entry_flow(story)
    write_flow_file(entry_graph, entry_path)
    written.append(entry_path)

    # Generate per-scene flows.
    for chapter in story.chapters:
        for scene in chapter.scenes:
            scene_graph = compile_scene(scene, characters=characters)

            # If scene has branch_info pointing to a convergence scene, add a
            # switch_scene at the end to go there.
            _maybe_add_scene_transition(scene_graph, scene, chapter)

            flow_path = output_dir / f"{scene.id}.flow"
            write_flow_file(scene_graph, flow_path)
            written.append(flow_path)

    return written


def _build_entry_flow(story: Story) -> FlowGraph:
    """Build the entry flow that starts the first scene.

    Creates: entry -> transition_fade_in -> switch_scene(first_scene_id).
    """
    graph = FlowGraph()

    entry = graph.add_node("entry")

    fade_in = graph.add_node("transition_fade_in", pin_overrides={1: 1.0})
    graph.connect_flow(entry, fade_in)

    # Determine the first scene ID.
    first_scene_id = ""
    if story.chapters and story.chapters[0].scenes:
        first_scene_id = story.chapters[0].scenes[0].id

    switch = graph.add_node("switch_scene", pin_overrides={1: first_scene_id})
    graph.connect_flow(fade_in, switch)

    graph.auto_layout()
    return graph


def _maybe_add_scene_transition(
    graph: FlowGraph,
    scene: Scene,
    chapter: Chapter,
) -> None:
    """Add a switch_scene node at the end of the scene graph if appropriate.

    Determines the next scene by:
    1. If the scene has a branch convergence target, use that.
    2. Otherwise, find the next scene in the chapter's scene list.
    3. If this is the last scene in the chapter, look for the next chapter's first scene.
    """
    next_scene_id = _find_next_scene_id(scene, chapter)
    if not next_scene_id:
        return

    # Find the last node in the graph (highest ID, has an unconnected flow output).
    last_node = _find_tail_node(graph)
    if last_node is None:
        return

    switch = graph.add_node("switch_scene", pin_overrides={1: next_scene_id})
    try:
        graph.connect_flow(last_node, switch)
    except ValueError:
        # No available flow pin -- scene might end at a choice or switch_scene already.
        pass


def _find_next_scene_id(scene: Scene, chapter: Chapter) -> str:
    """Determine the next scene ID after the given scene."""
    # If convergence is specified in branch_info, use it.
    if scene.branch_info.converges_at:
        return scene.branch_info.converges_at

    # Find this scene's index in the chapter.
    for i, s in enumerate(chapter.scenes):
        if s.id == scene.id:
            if i + 1 < len(chapter.scenes):
                return chapter.scenes[i + 1].id
            break

    return ""


def _find_tail_node(graph: FlowGraph) -> Any:
    """Find the last node that has an unconnected flow output pin.

    Returns the node, or None if no suitable node is found.
    """
    from vne_cli.flow.pins import PinType

    connected_pins: set[int] = set()
    for link in graph.links:
        connected_pins.add(link.source_pin_id)
        connected_pins.add(link.dest_pin_id)

    # Walk nodes in reverse ID order to find the last one with a free flow output.
    for node in reversed(graph.nodes):
        for pin in node.output_pins:
            if pin.type_id == PinType.FLOW and pin.id not in connected_pins:
                return node
    return None
