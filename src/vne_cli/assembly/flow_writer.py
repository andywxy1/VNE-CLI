"""Orchestrate .flow file generation for all scenes in a story.

Delegates to the flow/ module for graph construction and serialization.
Uses the orchestrator to generate per-scene flows plus an entry flow,
and optionally applies cinematic direction.
"""

from __future__ import annotations

import logging
from pathlib import Path

from vne_cli.config.schema import AssemblyConfig, CinematicConfig
from vne_cli.flow.cinematic import apply_cinematic_direction
from vne_cli.flow.graph import FlowGraph
from vne_cli.flow.scene_compiler import compile_scene
from vne_cli.flow.serializer import write_flow_file
from vne_cli.schemas.story import Story

logger = logging.getLogger("vne_cli.assembly.flow_writer")


def generate_flows(
    story: Story,
    output_dir: Path,
    assembly_config: AssemblyConfig,
    cinematic_config: CinematicConfig,
) -> list[Path]:
    """Generate .flow files for all scenes in the story.

    Creates one .flow per scene, plus an entry flow. Writes all files
    into the output_dir (typically ``<project>/application/flow/``).

    Args:
        story: The extracted story data.
        output_dir: Directory to write .flow files into.
        assembly_config: Assembly settings (transitions, text speed).
        cinematic_config: Cinematic direction settings.

    Returns:
        List of paths to generated .flow files, with entry.flow first.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # Build character lookup for name resolution in scene compiler.
    characters: dict[str, object] = {}
    for cid, cref in story.characters.items():
        characters[cid] = cref

    # 1. Generate entry flow.
    first_scene_id = _get_first_scene_id(story)
    entry_graph = _build_entry_flow(first_scene_id)
    entry_path = output_dir / "entry.flow"
    write_flow_file(entry_graph, entry_path)
    written.append(entry_path)
    logger.info("Generated entry flow -> %s", entry_path)

    # 2. Generate per-scene flows.
    for chapter in story.chapters:
        for i, scene in enumerate(chapter.scenes):
            scene_graph = compile_scene(scene, characters=characters)

            # Apply cinematic direction if enabled.
            if cinematic_config.enabled:
                apply_cinematic_direction(scene_graph, scene, cinematic_config)

            # Add scene transition to the next scene.
            next_scene_id = _find_next_scene_id(scene, chapter, i)
            if next_scene_id:
                _append_scene_switch(scene_graph, next_scene_id)

            flow_filename = f"{scene.id}.flow"
            flow_path = output_dir / flow_filename
            write_flow_file(scene_graph, flow_path)
            written.append(flow_path)
            logger.debug("Generated scene flow: %s -> %s", scene.id, flow_path)

    logger.info("Generated %d .flow files total", len(written))
    return written


def _get_first_scene_id(story: Story) -> str:
    """Return the scene ID of the very first scene in the story."""
    if story.chapters and story.chapters[0].scenes:
        return story.chapters[0].scenes[0].id
    return ""


def _build_entry_flow(first_scene_id: str) -> FlowGraph:
    """Build the entry flow that transitions into the first scene.

    Creates: entry -> transition_fade_in -> switch_scene(first_scene_id).
    """
    graph = FlowGraph()
    entry = graph.add_node("entry")
    fade_in = graph.add_node("transition_fade_in", pin_overrides={1: 1.0})
    graph.connect_flow(entry, fade_in)

    if first_scene_id:
        switch = graph.add_node("switch_scene", pin_overrides={1: first_scene_id})
        graph.connect_flow(fade_in, switch)

    graph.auto_layout()
    return graph


def _find_next_scene_id(
    scene: "Story.Scene",  # type: ignore[name-defined]
    chapter: "Story.Chapter",  # type: ignore[name-defined]
    scene_index: int,
) -> str:
    """Determine the next scene ID for a scene transition.

    Priority:
    1. Branch convergence target from branch_info.
    2. Next scene in the chapter's scene list.
    3. Empty string if this is the last scene.
    """
    from vne_cli.schemas.story import Chapter, Scene

    # If convergence is specified, use it.
    if scene.branch_info.converges_at:
        return scene.branch_info.converges_at

    # Next sequential scene.
    if scene_index + 1 < len(chapter.scenes):
        return chapter.scenes[scene_index + 1].id

    return ""


def _append_scene_switch(graph: FlowGraph, next_scene_id: str) -> None:
    """Append a switch_scene node at the end of the graph to transition to the next scene."""
    from vne_cli.flow.pins import PinType

    # Find the tail node with an unconnected flow output.
    connected_pins: set[int] = set()
    for link in graph.links:
        connected_pins.add(link.source_pin_id)
        connected_pins.add(link.dest_pin_id)

    tail_node = None
    for node in reversed(graph.nodes):
        for pin in node.output_pins:
            if pin.type_id == PinType.FLOW and pin.id not in connected_pins:
                tail_node = node
                break
        if tail_node is not None:
            break

    if tail_node is None:
        return

    switch = graph.add_node("switch_scene", pin_overrides={1: next_scene_id})
    try:
        graph.connect_flow(tail_node, switch)
    except ValueError:
        # No available flow pin (e.g., scene ends at a choice/switch already).
        pass
