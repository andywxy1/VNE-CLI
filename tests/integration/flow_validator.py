"""Reusable .flow file validator for integration tests.

Validates .flow files against the VNE specification:
- Valid JSON structure with required fields
- max_uid >= highest ID in the file
- All link pin references exist and are valid
- Pin type compatibility on links
- No orphaned nodes (unreachable from entry)
- Counterintuitive link naming is correct (input_pin_id = source output)
- Node IDs are unique and monotonically assigned
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FlowValidationResult:
    """Result of validating a .flow file."""

    path: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    node_count: int = 0
    link_count: int = 0
    max_uid: int = 0
    highest_id_found: int = 0

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def assert_valid(self) -> None:
        """Raise AssertionError if validation failed."""
        if self.errors:
            msg = f"Flow validation failed for {self.path}:\n"
            msg += "\n".join(f"  - {e}" for e in self.errors)
            raise AssertionError(msg)


def validate_flow_file(path: Path) -> FlowValidationResult:
    """Validate a single .flow file against the VNE spec.

    Args:
        path: Path to the .flow file.

    Returns:
        FlowValidationResult with errors and warnings.
    """
    result = FlowValidationResult(path=str(path))

    if not path.exists():
        result.errors.append(f"File does not exist: {path}")
        return result

    # 1. Parse JSON
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except json.JSONDecodeError as e:
        result.errors.append(f"Invalid JSON: {e}")
        return result

    if not isinstance(data, dict):
        result.errors.append("Root must be a JSON object.")
        return result

    # 2. Required fields
    for field_name in ("max_uid", "node_pool", "link_pool"):
        if field_name not in data:
            result.errors.append(f"Missing required field: {field_name}")

    if result.errors:
        return result

    # 3. max_uid type check
    max_uid = data["max_uid"]
    if not isinstance(max_uid, int) or max_uid < 0:
        result.errors.append(f"max_uid must be a non-negative integer, got: {max_uid}")
        return result
    result.max_uid = max_uid

    # 4. Validate node_pool
    node_pool = data["node_pool"]
    if not isinstance(node_pool, list):
        result.errors.append("node_pool must be an array.")
        return result

    link_pool = data["link_pool"]
    if not isinstance(link_pool, list):
        result.errors.append("link_pool must be an array.")
        return result

    result.node_count = len(node_pool)
    result.link_count = len(link_pool)

    # Collect all IDs across nodes, pins, and links
    all_ids: list[int] = []
    node_ids: set[int] = set()
    pin_map: dict[int, dict[str, Any]] = {}  # pin_id -> pin dict
    pin_to_node: dict[int, int] = {}  # pin_id -> node_id
    output_pins: set[int] = set()
    input_pins: set[int] = set()

    for node in node_pool:
        if not isinstance(node, dict):
            result.errors.append("node_pool item must be an object.")
            continue

        node_id = node.get("id")
        if node_id is None:
            result.errors.append("Node missing 'id' field.")
            continue

        if not isinstance(node_id, int):
            result.errors.append(f"Node id must be integer, got: {type(node_id).__name__}")
            continue

        if node_id in node_ids:
            result.errors.append(f"Duplicate node ID: {node_id}")
        node_ids.add(node_id)
        all_ids.append(node_id)

        if "type_id" not in node:
            result.errors.append(f"Node {node_id} missing 'type_id'.")

        # Validate input pins
        for pin in node.get("input_pin_list", []):
            if not isinstance(pin, dict):
                result.errors.append(f"Node {node_id}: input pin must be an object.")
                continue
            pin_id = pin.get("id")
            if pin_id is not None:
                all_ids.append(pin_id)
                pin_map[pin_id] = pin
                pin_to_node[pin_id] = node_id
                input_pins.add(pin_id)
                if pin.get("is_output", False):
                    result.errors.append(
                        f"Node {node_id}: pin {pin_id} in input_pin_list has is_output=true"
                    )

        # Validate output pins
        for pin in node.get("output_pin_list", []):
            if not isinstance(pin, dict):
                result.errors.append(f"Node {node_id}: output pin must be an object.")
                continue
            pin_id = pin.get("id")
            if pin_id is not None:
                all_ids.append(pin_id)
                pin_map[pin_id] = pin
                pin_to_node[pin_id] = node_id
                output_pins.add(pin_id)
                if not pin.get("is_output", False):
                    result.errors.append(
                        f"Node {node_id}: pin {pin_id} in output_pin_list has is_output=false"
                    )

    # 5. Validate ID uniqueness
    seen_ids: set[int] = set()
    for uid in all_ids:
        if uid in seen_ids:
            result.errors.append(f"Duplicate ID across entities: {uid}")
        seen_ids.add(uid)

    # 6. Validate links
    link_ids: set[int] = set()
    connected_inputs: set[int] = set()
    connected_outputs: set[int] = set()
    # Adjacency for reachability analysis
    flow_adjacency: dict[int, list[int]] = {}  # node_id -> [node_id]

    for link in link_pool:
        if not isinstance(link, dict):
            result.errors.append("link_pool item must be an object.")
            continue

        link_id = link.get("id")
        if link_id is not None:
            all_ids.append(link_id)
            if link_id in link_ids or link_id in seen_ids:
                result.errors.append(f"Duplicate link ID: {link_id}")
            link_ids.add(link_id)
            seen_ids.add(link_id)

        for req_field in ("id", "input_pin_id", "output_pin_id"):
            if req_field not in link:
                result.errors.append(f"Link missing required field: {req_field}")

        input_pin_id = link.get("input_pin_id")
        output_pin_id = link.get("output_pin_id")

        if input_pin_id is None or output_pin_id is None:
            continue

        # COUNTERINTUITIVE NAMING CHECK:
        # input_pin_id should reference a SOURCE node's OUTPUT pin (is_output=true)
        # output_pin_id should reference a DEST node's INPUT pin (is_output=false)
        if input_pin_id in pin_map:
            pin = pin_map[input_pin_id]
            if not pin.get("is_output", False):
                result.errors.append(
                    f"Link {link_id}: input_pin_id={input_pin_id} references a pin "
                    f"with is_output=false. Per counterintuitive naming, input_pin_id "
                    f"must point to the SOURCE node's OUTPUT pin."
                )
        else:
            if input_pin_id not in pin_map and node_pool:
                result.errors.append(
                    f"Link {link_id}: input_pin_id={input_pin_id} references nonexistent pin."
                )

        if output_pin_id in pin_map:
            pin = pin_map[output_pin_id]
            if pin.get("is_output", False):
                result.errors.append(
                    f"Link {link_id}: output_pin_id={output_pin_id} references a pin "
                    f"with is_output=true. Per counterintuitive naming, output_pin_id "
                    f"must point to the DEST node's INPUT pin."
                )
        else:
            if output_pin_id not in pin_map and node_pool:
                result.errors.append(
                    f"Link {link_id}: output_pin_id={output_pin_id} references nonexistent pin."
                )

        # Self-connection check
        src_node = pin_to_node.get(input_pin_id)
        dst_node = pin_to_node.get(output_pin_id)
        if src_node is not None and dst_node is not None:
            if src_node == dst_node:
                result.errors.append(
                    f"Link {link_id}: self-connection on node {src_node}."
                )
            # Pin type compatibility
            src_pin = pin_map.get(input_pin_id, {})
            dst_pin = pin_map.get(output_pin_id, {})
            src_type = src_pin.get("type_id", "")
            dst_type = dst_pin.get("type_id", "")
            if src_type and dst_type:
                if not _pins_compatible(src_type, dst_type):
                    result.errors.append(
                        f"Link {link_id}: incompatible pin types {src_type} -> {dst_type}."
                    )

            # Build flow adjacency for reachability
            if src_type == "flow":
                flow_adjacency.setdefault(src_node, []).append(dst_node)

    # 7. max_uid check
    if all_ids:
        highest = max(all_ids)
        result.highest_id_found = highest
        if highest > max_uid:
            result.errors.append(
                f"max_uid ({max_uid}) is less than the highest ID found ({highest})."
            )

    # 8. Entry node check
    entry_nodes = [
        n for n in node_pool
        if isinstance(n, dict) and n.get("type_id") == "entry"
    ]
    if not entry_nodes:
        result.warnings.append("No 'entry' node found.")
    elif len(entry_nodes) > 1:
        result.errors.append(f"Multiple entry nodes found ({len(entry_nodes)}).")

    # 9. Reachability check from entry node
    if entry_nodes and len(entry_nodes) == 1:
        entry_id = entry_nodes[0].get("id")
        if entry_id is not None:
            reachable = _find_reachable(entry_id, flow_adjacency)
            # Comment nodes have no flow pins, so they are naturally unreachable.
            # We only warn about non-comment nodes that are unreachable.
            for nid in node_ids:
                if nid not in reachable and nid != entry_id:
                    # Find the node type
                    node_type = ""
                    for n in node_pool:
                        if isinstance(n, dict) and n.get("id") == nid:
                            node_type = n.get("type_id", "")
                            break
                    if node_type != "comment":
                        result.warnings.append(
                            f"Node {nid} ({node_type}) is unreachable from entry."
                        )

    return result


def validate_flow_data(data: dict[str, Any], label: str = "<in-memory>") -> FlowValidationResult:
    """Validate a .flow JSON dict (already parsed)."""
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".flow", delete=False, encoding="utf-8"
    ) as f:
        json.dump(data, f)
        tmp_path = Path(f.name)
    try:
        result = validate_flow_file(tmp_path)
        result.path = label
        return result
    finally:
        tmp_path.unlink(missing_ok=True)


def _pins_compatible(src_type: str, dst_type: str) -> bool:
    """Check if two pin types are compatible for linking."""
    if src_type == dst_type:
        return True
    # Object is a wildcard for non-flow pins
    if src_type != "flow" and dst_type == "object":
        return True
    if src_type == "object" and dst_type != "flow":
        return True
    # int -> float promotion
    if src_type == "int" and dst_type == "float":
        return True
    return False


def _find_reachable(start: int, adjacency: dict[int, list[int]]) -> set[int]:
    """BFS to find all reachable nodes from start via flow links."""
    visited: set[int] = set()
    queue = [start]
    while queue:
        node = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        for child in adjacency.get(node, []):
            if child not in visited:
                queue.append(child)
    return visited
