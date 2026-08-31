"""Deterministic semantic catalog for the three-layer ACG spatial view.

The spatial catalog is deliberately a semantic projection, not a layout
engine.  It records which canonical nodes participate in the Knowledge and
Control layers, which selected runtime instances participate in Execution,
the three pairwise plane intersections, and flow metadata for canonical
relations.  Coordinates, sizes, routes, and other page decisions do not
belong here.

``graph`` is the canonical projection produced by :mod:`projector`.  Its
``runtime`` member is the runtime-0.1 catalog produced by :mod:`runtime`.
Only that explicit runtime catalog can populate the Execution layer; a
``runtime_managed`` attribute on a canonical node by itself is not enough.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .model import ACGError, NODE_TYPES


SPATIAL_PROTOCOL_VERSION = "spatial-0.1"
LAYER_NAMES = ("knowledge", "control", "execution")
INTERFACE_NAMES = (
    "knowledge-control",
    "control-execution",
    "execution-knowledge",
)

# The type split follows the ACG architecture contract rather than the
# renderer's stage presets.  Provenance and knowledge records remain on the
# Knowledge surface.  Nodes that define or gate a Run also appear on the
# Control surface.  Action/Approval/Verification intentionally belong to
# both surfaces: they are provenance facts and control-plane contracts.
KNOWLEDGE_NODE_TYPES = frozenset(NODE_TYPES - {"Run", "Step"})
CONTROL_NODE_TYPES = frozenset(
    {
        "Run",
        "Step",
        "Goal",
        "AcceptanceCriterion",
        "Decision",
        "Capability",
        "Agent",
        "Skill",
        "Tool",
        "Target",
        "Action",
        "Approval",
        "Policy",
        "Verification",
    }
)

RUNTIME_LANES = ("ready", "running", "blocked", "completed", "failed")
_DYNAMIC_EDGE_TYPES = frozenset({"precedes", "produces"})
_CONTROL_EDGE_TYPES = frozenset(
    {
        "contains",
        "has_run",
        "precedes",
        "blocked_by",
        "approved_by",
        "guarded_by",
        "checks",
        "satisfies",
        "targets",
        "uses",
        "invokes",
        "modifies",
    }
)


def _sequence(value: Any) -> int:
    """Return a stable sortable sequence, placing missing values last."""

    try:
        return int(value)
    except (TypeError, ValueError):
        return 2**63 - 1


def _node_sort_key(node: dict[str, Any]) -> tuple[int, str]:
    return _sequence(node.get("first_sequence")), str(node.get("id", ""))


def _edge_sort_key(edge: dict[str, Any]) -> tuple[int, str]:
    return _sequence(edge.get("first_sequence")), str(edge.get("id", ""))


def _require_graph_list(graph: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = graph.get(key, [])
    if not isinstance(value, list):
        raise ACGError(f"graph.{key} must be an array")
    if not all(isinstance(item, dict) for item in value):
        raise ACGError(f"graph.{key} items must be objects")
    return value


def _canonical_membership(node: dict[str, Any]) -> list[str]:
    node_type = node.get("type")
    membership: list[str] = []
    if node_type in KNOWLEDGE_NODE_TYPES:
        membership.append("knowledge")
    if node_type in CONTROL_NODE_TYPES:
        membership.append("control")
    # A future/extension node must remain visible.  Unknown canonical node
    # types are facts by default, never silently dropped from the catalog.
    if not membership:
        membership.append("knowledge")
    return membership


def _normalise_membership(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in LAYER_NAMES if item in value]


def _runtime_runs(runtime: Any) -> list[dict[str, Any]]:
    if not isinstance(runtime, dict):
        return []
    runs = runtime.get("runs", [])
    if not isinstance(runs, list):
        return []
    return [item for item in runs if isinstance(item, dict) and item.get("run_id")]


def _select_runtime_run(
    runs: list[dict[str, Any]],
    *,
    run_id: str | None,
    nodes_by_id: dict[str, dict[str, Any]],
    runtime: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if run_id is not None:
        for run in runs:
            if run.get("run_id") == run_id:
                return run
        raise ACGError(f"runtime Run does not exist: {run_id}")

    preferred_id = runtime.get("selected_run_id") if isinstance(runtime, dict) else None
    if preferred_id:
        for run in runs:
            if run.get("run_id") == preferred_id:
                return run

    # Runtime currently emits newest first.  Re-sort anyway so callers that
    # load a hand-authored/runtime-compatible JSON object receive the same
    # selected instance independent of array order.
    return sorted(
        runs,
        key=lambda run: (
            -_sequence(nodes_by_id.get(str(run.get("run_id")), {}).get("first_sequence")),
            str(run.get("run_id")),
        ),
    )[0] if runs else None


def _runtime_entries(
    snapshot: dict[str, Any],
    *,
    run_id: str,
    nodes_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Flatten a runtime snapshot into stable, selected instance records."""

    entries: dict[str, dict[str, Any]] = {}
    for lane in RUNTIME_LANES:
        raw_entries = snapshot.get(lane, [])
        if not isinstance(raw_entries, list):
            continue
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                continue
            node_id = raw_entry.get("id") or raw_entry.get("node_id")
            if not isinstance(node_id, str) or not node_id:
                continue
            # Runtime snapshots are expected to place an ID in one lane.  If
            # malformed input repeats it, fixed lane order gives a stable
            # result and avoids duplicate Execution membership.
            if node_id in entries:
                continue
            canonical = nodes_by_id.get(node_id, {})
            instance = deepcopy(raw_entry)
            instance["id"] = node_id
            instance["node_id"] = node_id
            instance["instance_id"] = f"{run_id}::{node_id}"
            instance["run_id"] = run_id
            instance["runtime_lane"] = lane
            instance["source_kind"] = "runtime"
            instance["membership"] = ["execution"]
            if "type" not in instance and canonical.get("type") is not None:
                instance["type"] = canonical["type"]
            if "label" not in instance and canonical.get("label") is not None:
                instance["label"] = canonical["label"]
            if "status" not in instance:
                instance["status"] = lane
            entries[node_id] = instance

    def sort_key(instance: dict[str, Any]) -> tuple[int, str]:
        canonical = nodes_by_id.get(str(instance["node_id"]), {})
        return _sequence(canonical.get("first_sequence")), str(instance["node_id"])

    return sorted(entries.values(), key=sort_key)


def _stable_runtime_snapshot(
    snapshot: dict[str, Any],
    *,
    nodes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Copy the selected snapshot while normalising unordered lane arrays."""

    result = deepcopy(snapshot)
    for lane in RUNTIME_LANES:
        raw_entries = result.get(lane)
        if not isinstance(raw_entries, list):
            continue
        raw_entries.sort(
            key=lambda item: (
                _sequence(
                    nodes_by_id.get(
                        str(item.get("id") or item.get("node_id")), {}
                    ).get("first_sequence")
                )
                if isinstance(item, dict)
                else 2**63 - 1,
                str(item.get("id") or item.get("node_id") or "")
                if isinstance(item, dict)
                else "",
            )
        )
    return result


def _interface_pairs(
    from_membership: list[str], to_membership: list[str]
) -> list[str]:
    result: list[str] = []
    for name, left, right in (
        ("knowledge-control", "knowledge", "control"),
        ("control-execution", "control", "execution"),
        ("execution-knowledge", "execution", "knowledge"),
    ):
        if (left in from_membership and right in to_membership) or (
            right in from_membership and left in to_membership
        ):
            result.append(name)
    return result


def _same_layer_flow(from_membership: list[str], to_membership: list[str]) -> str:
    common = [layer for layer in LAYER_NAMES if layer in from_membership and layer in to_membership]
    return common[0] if common else "knowledge"


def _flow_kind(
    edge: dict[str, Any],
    *,
    from_membership: list[str],
    to_membership: list[str],
    interfaces: list[str],
) -> str:
    attrs = edge.get("attrs", {})
    if isinstance(attrs, dict) and isinstance(attrs.get("flow_kind"), str) and attrs["flow_kind"]:
        return attrs["flow_kind"]

    edge_type = edge.get("type")
    if edge_type in _CONTROL_EDGE_TYPES and "control" in from_membership + to_membership:
        # Scheduling and gating remain control semantics even when their
        # selected runtime overlay also touches the Control/Execution axis.
        return "control"
    if edge_type == "produces" and "execution" in from_membership and "knowledge" in to_membership:
        return "execution-knowledge"
    if edge_type in {"supports", "refutes", "explains", "derived_from", "references", "generalizes_to", "regression_of"}:
        if "knowledge-control" in interfaces:
            return "knowledge-control"
        return "knowledge"
    if interfaces:
        # Pairwise interface order is part of the protocol and makes the
        # result independent of canonical edge/list order.
        return interfaces[0]
    return _same_layer_flow(from_membership, to_membership)


def _bool_attr(attrs: Any, key: str, default: bool) -> bool:
    if isinstance(attrs, dict) and key in attrs:
        return attrs[key] is True
    return default


def build_spatial_catalog(
    graph: dict[str, Any],
    *,
    run_id: str | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic ``spatial-0.1`` semantic catalog.

    Args:
        graph: Canonical projected graph.  It must contain ``nodes`` and
            ``edges`` arrays.  ``graph.runtime`` is used unless ``runtime``
            is explicitly supplied.
        run_id: Optional explicit runtime Run selection.  Without it, an
            explicitly supplied ``selected_run_id`` is honoured; otherwise
            the newest Run by canonical ``first_sequence`` is selected.
        runtime: Optional runtime catalog override, useful for callers that
            have not attached the catalog to the canonical graph yet.

    Returns:
        A JSON-compatible dictionary containing canonical node/relationship
        records plus ``layers``, ``interfaces``, and ``selected_runtime``.
        It contains no layout coordinates or renderer-derived positions.
    """

    if not isinstance(graph, dict):
        raise ACGError("graph must be an object")
    raw_nodes = _require_graph_list(graph, "nodes")
    raw_edges = _require_graph_list(graph, "edges")

    nodes_by_id: dict[str, dict[str, Any]] = {}
    for raw_node in raw_nodes:
        node_id = raw_node.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise ACGError("graph.nodes items require a non-empty id")
        if node_id in nodes_by_id:
            raise ACGError(f"duplicate canonical node id: {node_id}")
        nodes_by_id[node_id] = raw_node

    canonical_memberships: dict[str, list[str]] = {}
    canonical_nodes: list[dict[str, Any]] = []
    for node in sorted(nodes_by_id.values(), key=_node_sort_key):
        membership = _canonical_membership(node)
        canonical_memberships[node["id"]] = membership
        output_node = deepcopy(node)
        output_node["membership"] = list(membership)
        output_node["canonical_membership"] = list(membership)
        output_node["source_kind"] = "canonical"
        canonical_nodes.append(output_node)

    edge_by_id: dict[str, dict[str, Any]] = {}
    for raw_edge in raw_edges:
        edge_id = raw_edge.get("id")
        if not isinstance(edge_id, str) or not edge_id:
            raise ACGError("graph.edges items require a non-empty id")
        if edge_id in edge_by_id:
            raise ACGError(f"duplicate canonical edge id: {edge_id}")
        edge_by_id[edge_id] = raw_edge

    runtime_catalog: Any = graph.get("runtime") if runtime is None else runtime
    runtime_dict = runtime_catalog if isinstance(runtime_catalog, dict) else None
    runs = _runtime_runs(runtime_catalog)
    selected_snapshot = _select_runtime_run(
        runs,
        run_id=run_id,
        nodes_by_id=nodes_by_id,
        runtime=runtime_dict,
    )

    selected_instances: list[dict[str, Any]] = []
    selected_node_ids: list[str] = []
    selected_instance_ids: list[str] = []
    selected_runtime: dict[str, Any] | None = None
    if selected_snapshot is not None:
        selected_run_id = str(selected_snapshot["run_id"])
        selected_instances = _runtime_entries(
            selected_snapshot,
            run_id=selected_run_id,
            nodes_by_id=nodes_by_id,
        )
        selected_node_ids = [item["node_id"] for item in selected_instances]
        selected_instance_ids = [item["instance_id"] for item in selected_instances]
        selected_runtime = {
            "run_id": selected_run_id,
            "run_label": selected_snapshot.get("run_label"),
            "status": selected_snapshot.get("status"),
            "case_state": selected_snapshot.get("case_state"),
            "counts": deepcopy(selected_snapshot.get("counts", {})),
            "node_ids": list(selected_node_ids),
            "instance_ids": list(selected_instance_ids),
            "instances": deepcopy(selected_instances),
            "snapshot": _stable_runtime_snapshot(
                selected_snapshot,
                nodes_by_id=nodes_by_id,
            ),
        }

    execution_ids = set(selected_node_ids)
    effective_memberships: dict[str, list[str]] = {}
    for node_id, membership in canonical_memberships.items():
        effective = list(membership)
        if node_id in execution_ids:
            effective.append("execution")
        effective_memberships[node_id] = [layer for layer in LAYER_NAMES if layer in effective]

    # Reflect the selected overlay on canonical nodes without changing the
    # source graph.  Runtime instance details remain in Execution.nodes.
    for node in canonical_nodes:
        node_id = node["id"]
        node["membership"] = list(effective_memberships[node_id])
        if node_id in execution_ids:
            instance_id = f"{selected_snapshot['run_id']}::{node_id}" if selected_snapshot else None
            node["runtime_instance_id"] = instance_id

    layer_members: dict[str, list[str]] = {
        layer: sorted(
            [node_id for node_id, membership in effective_memberships.items() if layer in membership],
            key=lambda node_id: _node_sort_key(nodes_by_id[node_id]),
        )
        for layer in LAYER_NAMES
    }
    layer_instance_ids = {
        "knowledge": [],
        "control": [],
        "execution": list(selected_instance_ids),
    }
    execution_nodes = deepcopy(selected_instances)
    for item in execution_nodes:
        item["canonical_membership"] = list(canonical_memberships.get(item["node_id"], []))

    relations: list[dict[str, Any]] = []
    relation_interface_map: dict[str, list[str]] = {}
    for edge in sorted(edge_by_id.values(), key=_edge_sort_key):
        from_id = edge.get("from")
        to_id = edge.get("to")
        from_membership = effective_memberships.get(str(from_id), [])
        to_membership = effective_memberships.get(str(to_id), [])
        interfaces = _interface_pairs(from_membership, to_membership)
        relation_interface_map[str(edge["id"])] = interfaces
        attrs = edge.get("attrs", {})
        touches_execution = "execution" in from_membership or "execution" in to_membership
        default_animated = touches_execution and edge.get("type") in _DYNAMIC_EDGE_TYPES
        relation = deepcopy(edge)
        relation["from_membership"] = list(from_membership)
        relation["to_membership"] = list(to_membership)
        relation["interfaces"] = list(interfaces)
        relation["flow_interfaces"] = list(interfaces)
        relation["flow_kind"] = _flow_kind(
            edge,
            from_membership=from_membership,
            to_membership=to_membership,
            interfaces=interfaces,
        )
        relation["actual"] = _bool_attr(attrs, "actual", True)
        relation["animated"] = _bool_attr(attrs, "animated", default_animated)
        relation["source_kind"] = "canonical"
        if str(from_id) in execution_ids:
            relation["from_instance_id"] = f"{selected_snapshot['run_id']}::{from_id}" if selected_snapshot else None
        if str(to_id) in execution_ids:
            relation["to_instance_id"] = f"{selected_snapshot['run_id']}::{to_id}" if selected_snapshot else None
        relations.append(relation)

    interfaces: dict[str, dict[str, Any]] = {}
    for name, left, right in (
        ("knowledge-control", "knowledge", "control"),
        ("control-execution", "control", "execution"),
        ("execution-knowledge", "execution", "knowledge"),
    ):
        shared_node_ids = sorted(
            set(layer_members[left]) & set(layer_members[right]),
            key=lambda node_id: _node_sort_key(nodes_by_id[node_id]),
        )
        shared_instance_ids = [
            item["instance_id"]
            for item in selected_instances
            if item["node_id"] in shared_node_ids
        ]
        relation_ids = sorted(
            [edge_id for edge_id, edge_interfaces in relation_interface_map.items() if name in edge_interfaces],
            key=lambda edge_id: _edge_sort_key(edge_by_id[edge_id]),
        )
        interfaces[name] = {
            "id": name,
            "layers": [left, right],
            "membership": list(shared_node_ids),
            "node_ids": list(shared_node_ids),
            "instance_ids": list(shared_instance_ids),
            "relation_ids": relation_ids,
        }

    layers: dict[str, dict[str, Any]] = {}
    for layer in LAYER_NAMES:
        members = list(layer_members[layer])
        instances = list(layer_instance_ids[layer])
        layers[layer] = {
            "id": layer,
            "membership": members,
            "node_ids": members,
            "instance_ids": instances,
            "node_count": len(members),
            "status": "empty" if layer == "execution" and not members else "populated",
        }
        if layer == "execution":
            layers[layer]["nodes"] = execution_nodes
            layers[layer]["selected_runtime"] = selected_runtime

    available_run_ids = sorted(
        [str(run.get("run_id")) for run in runs],
        key=lambda item: (
            -_sequence(nodes_by_id.get(item, {}).get("first_sequence")),
            item,
        ),
    )
    return {
        "protocol_version": SPATIAL_PROTOCOL_VERSION,
        "graph_id": graph.get("graph_id"),
        "graph_type": graph.get("graph_type"),
        "root_id": graph.get("root_id"),
        "generated_at": graph.get("generated_at"),
        "layers": layers,
        "interfaces": interfaces,
        "nodes": canonical_nodes,
        "relations": relations,
        "selected_runtime": selected_runtime,
        "runtime": {
            "protocol_version": runtime_dict.get("protocol_version") if runtime_dict else None,
            "available_run_ids": available_run_ids,
            "selected_run_id": selected_runtime.get("run_id") if selected_runtime else None,
        },
    }


# A descriptive alias is useful to callers that call the output a spatial
# projection.  Both names intentionally share the exact same implementation.
build_spatial_projection = build_spatial_catalog


__all__ = [
    "CONTROL_NODE_TYPES",
    "INTERFACE_NAMES",
    "KNOWLEDGE_NODE_TYPES",
    "LAYER_NAMES",
    "SPATIAL_PROTOCOL_VERSION",
    "build_spatial_catalog",
    "build_spatial_projection",
]
