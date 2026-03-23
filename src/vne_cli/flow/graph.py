"""Flow graph construction with shared monotonic ID counter.

Builds a directed graph of FlowNodes connected by links.
All IDs (node, pin, link) share a single counter per the VNE spec.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vne_cli.flow.nodes import FlowNode, get_node_type
from vne_cli.flow.pins import Pin, PinType, pins_compatible


@dataclass(frozen=True)
class Link:
    """A connection between two pins on two nodes.

    Attributes:
        id: Unique link ID from the shared graph counter.
        source_pin_id: Output pin on the source node (is_output=True).
        dest_pin_id: Input pin on the destination node (is_output=False).
    """

    id: int
    source_pin_id: int
    dest_pin_id: int


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
NODE_H_SPACING = 280
NODE_V_SPACING = 200


class FlowGraph:
    """A directed graph of VNE flow nodes with shared ID counter.

    The ID counter (``_next_uid``) is consumed by nodes, pins, and links
    in strict order per the spec (Section 2).
    """

    def __init__(self) -> None:
        self._nodes: dict[int, FlowNode] = {}
        self._links: list[Link] = []
        self._next_uid: int = 1
        # Track which pins are already connected (pin_id -> link_id).
        self._pin_connections: dict[int, int] = {}

    def _alloc_uid(self) -> int:
        """Allocate and return the next unique ID."""
        uid = self._next_uid
        self._next_uid += 1
        return uid

    @property
    def max_uid(self) -> int:
        """The highest ID that has been assigned (``_next_uid - 1``).

        If nothing has been allocated yet, returns 0.
        """
        return self._next_uid - 1

    @property
    def nodes(self) -> list[FlowNode]:
        """All nodes in the graph, ordered by ID."""
        return sorted(self._nodes.values(), key=lambda n: n.id)

    @property
    def links(self) -> list[Link]:
        """All links in the graph."""
        return list(self._links)

    # ------------------------------------------------------------------
    # Node creation
    # ------------------------------------------------------------------

    def add_node(
        self,
        type_id: str,
        *,
        position: dict[str, int] | None = None,
        pin_overrides: dict[int, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> FlowNode:
        """Create a node from the catalog and assign IDs.

        The node gets the next UID, then each input pin, then each output pin.

        Args:
            type_id: Node type string (e.g. ``"entry"``, ``"show_dialog_box"``).
            position: Canvas position ``{x, y}``.  Defaults to ``{0, 0}``.
            pin_overrides: Map from pin *index* (0-based, inputs first then
                outputs) to a replacement value.  Useful for setting dialog
                text, texture IDs, etc.
            extra: Extra fields for special node types (e.g. comment text/size).

        Returns:
            The fully constructed ``FlowNode`` with assigned IDs.
        """
        node_def = get_node_type(type_id)
        node_id = self._alloc_uid()
        pos = position if position is not None else {"x": 0, "y": 0}

        input_pins: list[Pin] = []
        for idx, spec in enumerate(node_def.input_pins):
            pin_id = self._alloc_uid()
            val = spec.resolved_default()
            if pin_overrides and idx in pin_overrides:
                val = pin_overrides[idx]
            input_pins.append(Pin(
                id=pin_id,
                type_id=spec.type_id,
                is_output=False,
                name=spec.name,
                val=val,
            ))

        output_pins: list[Pin] = []
        n_inputs = len(node_def.input_pins)
        for idx, spec in enumerate(node_def.output_pins):
            pin_id = self._alloc_uid()
            val = spec.resolved_default()
            override_key = n_inputs + idx
            if pin_overrides and override_key in pin_overrides:
                val = pin_overrides[override_key]
            output_pins.append(Pin(
                id=pin_id,
                type_id=spec.type_id,
                is_output=True,
                name=spec.name,
                val=val,
            ))

        node = FlowNode(
            id=node_id,
            type_id=type_id,
            position=pos,
            input_pins=input_pins,
            output_pins=output_pins,
            extra=extra if extra else {},
        )
        self._nodes[node_id] = node
        return node

    # ------------------------------------------------------------------
    # Connections
    # ------------------------------------------------------------------

    def connect(
        self,
        source_node: FlowNode,
        source_pin_index: int,
        dest_node: FlowNode,
        dest_pin_index: int,
    ) -> Link:
        """Connect an output pin on *source_node* to an input pin on *dest_node*.

        Args:
            source_node: The node whose output pin to connect from.
            source_pin_index: Index into ``source_node.output_pins``.
            dest_node: The node whose input pin to connect to.
            dest_pin_index: Index into ``dest_node.input_pins``.

        Returns:
            The created ``Link``.

        Raises:
            ValueError: On invalid nodes, pins, or incompatible types.
        """
        if source_node.id == dest_node.id:
            msg = f"Cannot connect a node to itself (node {source_node.id})."
            raise ValueError(msg)
        if source_node.id not in self._nodes:
            msg = f"Source node {source_node.id} not in graph."
            raise ValueError(msg)
        if dest_node.id not in self._nodes:
            msg = f"Destination node {dest_node.id} not in graph."
            raise ValueError(msg)

        src_pin = source_node.output_pins[source_pin_index]
        dst_pin = dest_node.input_pins[dest_pin_index]

        if not src_pin.is_output:
            msg = f"Pin {src_pin.id} on source node is not an output pin."
            raise ValueError(msg)
        if dst_pin.is_output:
            msg = f"Pin {dst_pin.id} on dest node is not an input pin."
            raise ValueError(msg)
        if not pins_compatible(src_pin.type_id, dst_pin.type_id):
            msg = (
                f"Incompatible pin types: {src_pin.type_id.value} -> {dst_pin.type_id.value}"
            )
            raise ValueError(msg)

        link_id = self._alloc_uid()
        link = Link(id=link_id, source_pin_id=src_pin.id, dest_pin_id=dst_pin.id)
        self._links.append(link)
        self._pin_connections[src_pin.id] = link_id
        self._pin_connections[dst_pin.id] = link_id
        return link

    def connect_flow(self, source_node: FlowNode, dest_node: FlowNode) -> Link:
        """Connect the first available flow output of *source* to the first available flow input of *dest*.

        Searches for the first unconnected flow output pin on the source,
        and the first unconnected flow input pin on the destination.
        """
        src_pin_idx: int | None = None
        for i, pin in enumerate(source_node.output_pins):
            if pin.type_id == PinType.FLOW and pin.id not in self._pin_connections:
                src_pin_idx = i
                break
        if src_pin_idx is None:
            msg = f"No available flow output pin on node {source_node.id} ({source_node.type_id})."
            raise ValueError(msg)

        dst_pin_idx: int | None = None
        for i, pin in enumerate(dest_node.input_pins):
            if pin.type_id == PinType.FLOW and pin.id not in self._pin_connections:
                dst_pin_idx = i
                break
        if dst_pin_idx is None:
            msg = f"No available flow input pin on node {dest_node.id} ({dest_node.type_id})."
            raise ValueError(msg)

        return self.connect(source_node, src_pin_idx, dest_node, dst_pin_idx)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """Validate the graph for correctness.

        Returns:
            List of error/warning messages. Empty means valid.
        """
        errors: list[str] = []

        # 1. Check ID uniqueness across all entities.
        all_ids: list[int] = []
        for node in self._nodes.values():
            all_ids.append(node.id)
            for pin in node.input_pins + node.output_pins:
                all_ids.append(pin.id)
        for link in self._links:
            all_ids.append(link.id)

        seen: set[int] = set()
        for uid in all_ids:
            if uid in seen:
                errors.append(f"Duplicate ID: {uid}")
            seen.add(uid)

        # 2. Build pin lookup for link validation.
        pin_map: dict[int, Pin] = {}
        pin_to_node: dict[int, int] = {}
        for node in self._nodes.values():
            for pin in node.input_pins + node.output_pins:
                pin_map[pin.id] = pin
                pin_to_node[pin.id] = node.id

        # 3. Validate links.
        input_connected: set[int] = set()
        output_connected: set[int] = set()
        for link in self._links:
            src_pin = pin_map.get(link.source_pin_id)
            dst_pin = pin_map.get(link.dest_pin_id)
            if src_pin is None:
                errors.append(f"Link {link.id}: source pin {link.source_pin_id} not found.")
                continue
            if dst_pin is None:
                errors.append(f"Link {link.id}: dest pin {link.dest_pin_id} not found.")
                continue
            if not src_pin.is_output:
                errors.append(
                    f"Link {link.id}: source pin {src_pin.id} is not an output pin."
                )
            if dst_pin.is_output:
                errors.append(
                    f"Link {link.id}: dest pin {dst_pin.id} is not an input pin."
                )
            src_node_id = pin_to_node.get(link.source_pin_id)
            dst_node_id = pin_to_node.get(link.dest_pin_id)
            if src_node_id == dst_node_id:
                errors.append(f"Link {link.id}: self-connection on node {src_node_id}.")
            if not pins_compatible(src_pin.type_id, dst_pin.type_id):
                errors.append(
                    f"Link {link.id}: incompatible types "
                    f"{src_pin.type_id.value} -> {dst_pin.type_id.value}."
                )
            # Each input pin: at most one connection.
            if link.dest_pin_id in input_connected:
                errors.append(
                    f"Link {link.id}: input pin {link.dest_pin_id} already connected."
                )
            input_connected.add(link.dest_pin_id)
            # Each output pin: at most one connection.
            if link.source_pin_id in output_connected:
                errors.append(
                    f"Link {link.id}: output pin {link.source_pin_id} already connected."
                )
            output_connected.add(link.source_pin_id)

        # 4. Check exactly one entry node.
        entry_count = sum(1 for n in self._nodes.values() if n.type_id == "entry")
        if entry_count == 0:
            errors.append("No entry node found.")
        elif entry_count > 1:
            errors.append(f"Multiple entry nodes found ({entry_count}).")

        # 5. max_uid consistency.
        if seen and max(seen) != self.max_uid:
            errors.append(
                f"max_uid mismatch: tracked={self.max_uid}, actual max={max(seen)}."
            )

        return errors

    # ------------------------------------------------------------------
    # Auto-layout
    # ------------------------------------------------------------------

    def auto_layout(self) -> None:
        """Assign reasonable x,y positions to all nodes.

        Uses a topological-order approach: nodes are laid out left-to-right
        following flow connections, with branching spreading vertically.
        """
        if not self._nodes:
            return

        # Build adjacency from flow links.
        pin_to_node: dict[int, int] = {}
        pin_type_map: dict[int, PinType] = {}
        for node in self._nodes.values():
            for pin in node.input_pins + node.output_pins:
                pin_to_node[pin.id] = node.id
                pin_type_map[pin.id] = pin.type_id

        flow_children: dict[int, list[int]] = {}
        for link in self._links:
            src_type = pin_type_map.get(link.source_pin_id)
            if src_type == PinType.FLOW:
                src_nid = pin_to_node.get(link.source_pin_id)
                dst_nid = pin_to_node.get(link.dest_pin_id)
                if src_nid is not None and dst_nid is not None:
                    flow_children.setdefault(src_nid, []).append(dst_nid)

        # BFS from entry node.
        entry_nodes = [n for n in self._nodes.values() if n.type_id == "entry"]
        if not entry_nodes:
            for i, node in enumerate(self.nodes):
                node.position = {"x": 0, "y": i * NODE_V_SPACING}
            return

        visited: set[int] = set()
        queue: list[tuple[int, int, int]] = [(entry_nodes[0].id, 0, 0)]
        col_row_tracker: dict[int, int] = {}

        while queue:
            nid, col, row = queue.pop(0)
            if nid in visited:
                continue
            visited.add(nid)

            self._nodes[nid].position = {"x": col * NODE_H_SPACING, "y": row * NODE_V_SPACING}

            children = flow_children.get(nid, [])
            next_col = col + 1
            if next_col not in col_row_tracker:
                col_row_tracker[next_col] = 0

            for child_id in children:
                if child_id not in visited:
                    child_row = col_row_tracker[next_col]
                    col_row_tracker[next_col] = child_row + 1
                    queue.append((child_id, next_col, child_row))

        # Handle unvisited nodes (disconnected).
        max_y = max(
            (n.position.get("y", 0) for n in self._nodes.values() if n.id in visited),
            default=0,
        )
        offset_y = max_y + NODE_V_SPACING * 2
        for i, node in enumerate(self.nodes):
            if node.id not in visited:
                node.position = {"x": 0, "y": offset_y + i * NODE_V_SPACING}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_node(self, node_id: int) -> FlowNode:
        """Get a node by ID."""
        return self._nodes[node_id]

    def set_pin_value(
        self, node: FlowNode, pin_index: int, value: Any, *, is_input: bool = True
    ) -> None:
        """Set the value of a specific pin on a node."""
        pins = node.input_pins if is_input else node.output_pins
        pins[pin_index].val = value
