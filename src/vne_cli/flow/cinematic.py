"""Cinematic direction layer.

Adds transitions, letterboxing, audio cues, and timing refinements
to a base flow graph. This is the "polish" pass that transforms
functional flows into cinematic experiences.

Two tiers:
- "base": Standard fade transitions at chapter/scene boundaries.
- "full": Letterboxing, audio fade control, delay adjustments.
"""

from __future__ import annotations

from vne_cli.config.schema import CinematicConfig
from vne_cli.flow.graph import FlowGraph
from vne_cli.flow.nodes import FlowNode
from vne_cli.flow.pins import PinType
from vne_cli.schemas.story import Scene


def apply_cinematic_direction(
    graph: FlowGraph,
    scene: Scene,
    config: CinematicConfig,
) -> FlowGraph:
    """Apply cinematic direction to a flow graph.

    Inserts transition nodes, letterboxing, and timing adjustments
    to create a polished visual novel experience.

    Args:
        graph: The base flow graph (functional but minimal).
        scene: Scene data for context-aware direction decisions.
        config: Cinematic settings (tier, enabled).

    Returns:
        The enhanced flow graph with cinematic nodes inserted.
    """
    if not config.enabled:
        return graph

    if config.tier in ("base", "full"):
        _apply_base_tier(graph, scene)

    if config.tier == "full":
        _apply_full_tier(graph, scene)

    return graph


def _apply_base_tier(graph: FlowGraph, scene: Scene) -> None:
    """Base tier: insert fade transitions after the entry node.

    Adds a transition_fade_in after the entry node so the scene
    opens with a fade from black.
    """
    entry_nodes = [n for n in graph.nodes if n.type_id == "entry"]
    if not entry_nodes:
        return

    entry = entry_nodes[0]

    # Check if there is already a transition_fade_in right after entry.
    connected_node = _find_flow_successor(graph, entry)
    if connected_node is not None and connected_node.type_id == "transition_fade_in":
        return  # Already has a fade-in.

    # If entry has a connected successor, we need to insert the fade between them.
    if connected_node is not None:
        # Remove the existing link between entry and its successor.
        _remove_flow_link_between(graph, entry, connected_node)

        # Insert fade_in between entry and successor.
        fade_in = graph.add_node("transition_fade_in", pin_overrides={1: 0.8})
        graph.connect_flow(entry, fade_in)
        graph.connect_flow(fade_in, connected_node)
    else:
        # Entry has no successor, just append.
        fade_in = graph.add_node("transition_fade_in", pin_overrides={1: 0.8})
        graph.connect_flow(entry, fade_in)


def _apply_full_tier(graph: FlowGraph, scene: Scene) -> None:
    """Full tier: add letterboxing for narration-heavy scenes.

    If the scene starts with narration, wrap it in letterboxing.
    """
    if not scene.beats:
        return

    # Check if first beat is narration -- if so, add letterboxing after entry.
    from vne_cli.schemas.story import BeatType
    if scene.beats[0].type == BeatType.NARRATION:
        entry_nodes = [n for n in graph.nodes if n.type_id == "entry"]
        if not entry_nodes:
            return

        entry = entry_nodes[0]
        successor = _find_flow_successor(graph, entry)

        # Only add if not already present.
        if successor is not None and successor.type_id != "show_letterboxing":
            # Find the right place -- after any fade_in.
            if successor.type_id == "transition_fade_in":
                after_fade = _find_flow_successor(graph, successor)
                if after_fade is not None and after_fade.type_id != "show_letterboxing":
                    _remove_flow_link_between(graph, successor, after_fade)
                    lb = graph.add_node("show_letterboxing")
                    graph.connect_flow(successor, lb)
                    graph.connect_flow(lb, after_fade)


# ---------------------------------------------------------------------------
# Graph navigation helpers
# ---------------------------------------------------------------------------

def _find_flow_successor(graph: FlowGraph, node: FlowNode) -> FlowNode | None:
    """Find the node connected to the first flow output of *node*."""
    pin_to_node: dict[int, FlowNode] = {}
    for n in graph.nodes:
        for pin in n.input_pins:
            pin_to_node[pin.id] = n

    for pin in node.output_pins:
        if pin.type_id == PinType.FLOW:
            for link in graph.links:
                if link.source_pin_id == pin.id:
                    dest_node = pin_to_node.get(link.dest_pin_id)
                    if dest_node is not None:
                        return dest_node
    return None


def _remove_flow_link_between(graph: FlowGraph, source: FlowNode, dest: FlowNode) -> None:
    """Remove the flow link connecting source to dest.

    Modifies the graph's internal link list directly.
    """
    src_pin_ids = {p.id for p in source.output_pins if p.type_id == PinType.FLOW}
    dst_pin_ids = {p.id for p in dest.input_pins if p.type_id == PinType.FLOW}

    to_remove = []
    for i, link in enumerate(graph._links):
        if link.source_pin_id in src_pin_ids and link.dest_pin_id in dst_pin_ids:
            to_remove.append(i)
            # Also clean up pin_connections tracking.
            graph._pin_connections.pop(link.source_pin_id, None)
            graph._pin_connections.pop(link.dest_pin_id, None)

    for i in reversed(to_remove):
        graph._links.pop(i)
