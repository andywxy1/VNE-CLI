"""Serialize a FlowGraph to VNE .flow JSON format.

CRITICAL: The link field naming is counterintuitive per the VNE spec:
  - ``input_pin_id``  = the SOURCE node's OUTPUT pin (is_output: true)
  - ``output_pin_id`` = the DESTINATION node's INPUT pin (is_output: false)

This is because from the *link's* perspective:
  - ``input_pin_id`` is the pin that feeds data INTO the link.
  - ``output_pin_id`` is the pin that receives data OUT OF the link.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from vne_cli.flow.graph import FlowGraph


def serialize_flow(graph: FlowGraph) -> dict[str, Any]:
    """Convert a FlowGraph to the VNE .flow JSON structure.

    Args:
        graph: The flow graph to serialize.

    Returns:
        A dict matching the .flow JSON schema with correct field names.
    """
    node_pool: list[dict[str, Any]] = []
    for node in graph.nodes:
        node_dict: dict[str, Any] = {
            "id": node.id,
            "type_id": node.type_id,
            "position": node.position,
            "input_pin_list": [pin.serialize() for pin in node.input_pins],
            "output_pin_list": [pin.serialize() for pin in node.output_pins],
        }
        # Add extra fields for special node types (e.g. comment).
        for key, value in node.extra.items():
            node_dict[key] = value
        node_pool.append(node_dict)

    link_pool: list[dict[str, Any]] = []
    for link in graph.links:
        link_pool.append({
            "id": link.id,
            # COUNTERINTUITIVE: input_pin_id = source output pin.
            "input_pin_id": link.source_pin_id,
            # COUNTERINTUITIVE: output_pin_id = dest input pin.
            "output_pin_id": link.dest_pin_id,
        })

    return {
        "max_uid": graph.max_uid,
        "is_open": True,
        "node_pool": node_pool,
        "link_pool": link_pool,
    }


def write_flow_file(graph: FlowGraph, path: Path) -> None:
    """Serialize a FlowGraph and write it to a .flow file.

    Args:
        graph: The flow graph to write.
        path: Output file path.
    """
    data = serialize_flow(graph)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
