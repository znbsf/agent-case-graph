"""Deterministic semantic catalog for the three-surface ACG spatial view.

The spatial catalog is deliberately a semantic projection, not a layout
engine.  Each canonical node has exactly one primary surface: State,
Control, or Action.  Runtime frontier information is a status overlay and
never changes that semantic home; observed execution remains a separate replay
trace.  The catalog also records the three pairwise interfaces
and flow metadata for canonical relations.  Coordinates, sizes, routes, and
other page decisions do not belong here.

``graph`` is the canonical projection produced by :mod:`projector`.  Its
``runtime`` member is the runtime-0.1 catalog produced by :mod:`runtime`.
Only that explicit runtime catalog can populate the runtime overlay; a
``runtime_managed`` attribute on a canonical node by itself is not enough.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .model import ACGError, NODE_TYPES


SPATIAL_PROTOCOL_VERSION = "spatial-0.2"
LAYER_NAMES = ("state", "control", "action")
INTERFACE_NAMES = (
    "state-control",
    "control-action",
    "action-state",
)

# A canonical node has one semantic home.  Cross-surface meaning belongs to
# relations and projections, not duplicate membership.  This makes the three
# surfaces geometrically strict and keeps runtime state independent.
STATE_NODE_TYPES = frozenset(
    {
        "Graph",
        "ProblemType",
        "Case",
        "EnvironmentSnapshot",
        "Artifact",
        "Observation",
        "Claim",
        "RootCause",
        "Uncertainty",
        "ScopeBoundary",
        "VerificationReceipt",
        "Pattern",
        "Runbook",
        "SkillVersion",
        "EvalCase",
        "DriftFinding",
        "ExternalIssue",
    }
)
CONTROL_NODE_TYPES = frozenset(
    {
        "Run",
        "Step",
        "Goal",
        "AcceptanceCriterion",
        "Decision",
        "Approval",
        "Policy",
        "Verification",
    }
)
ACTION_NODE_TYPES = frozenset(
    {
        "Actor",
        "Capability",
        "Agent",
        "Skill",
        "Tool",
        "Target",
        "Action",
    }
)

_LAYER_TYPE_SETS = (STATE_NODE_TYPES, CONTROL_NODE_TYPES, ACTION_NODE_TYPES)
if frozenset().union(*_LAYER_TYPE_SETS) != NODE_TYPES:
    raise RuntimeError("spatial-0.2 layer types must cover every canonical NODE_TYPE")
if any(
    left & right
    for index, left in enumerate(_LAYER_TYPE_SETS)
    for right in _LAYER_TYPE_SETS[index + 1 :]
):
    raise RuntimeError("spatial-0.2 layer type sets must be disjoint")

# Compatibility aliases for callers that imported the spatial-0.1 constants.
# They now identify the nearest spatial-0.2 surface rather than overlapping
# memberships.
KNOWLEDGE_NODE_TYPES = STATE_NODE_TYPES
EXECUTION_NODE_TYPES = ACTION_NODE_TYPES

RUNTIME_LANES = ("ready", "running", "blocked", "completed", "failed")
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
    if node_type in STATE_NODE_TYPES:
        return ["state"]
    if node_type in CONTROL_NODE_TYPES:
        return ["control"]
    if node_type in ACTION_NODE_TYPES:
        return ["action"]
    # A future/extension node must remain visible. Unknown canonical node
    # types are state records by default, never silently dropped.
    return ["state"]


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
            # runtime-overlay result.
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
            instance["membership"] = ["runtime-overlay"]
            canonical_membership = _canonical_membership(canonical)
            instance["primary_layer"] = canonical_membership[0]
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
        ("state-control", "state", "control"),
        ("control-action", "control", "action"),
        ("action-state", "action", "state"),
    ):
        if (left in from_membership and right in to_membership) or (
            right in from_membership and left in to_membership
        ):
            result.append(name)
    return result


def _same_layer_flow(from_membership: list[str], to_membership: list[str]) -> str:
    common = [layer for layer in LAYER_NAMES if layer in from_membership and layer in to_membership]
    return common[0] if common else "state"


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
    if interfaces:
        return interfaces[0]
    if edge_type in _CONTROL_EDGE_TYPES and "control" in from_membership + to_membership:
        return "control"
    if edge_type in {"supports", "refutes", "explains", "derived_from", "references", "generalizes_to", "regression_of"}:
        return "state"
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
    """Build a deterministic ``spatial-0.2`` semantic catalog.

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
        records plus ``layers``, ``interfaces``, ``runtime_overlay``, and
        ``selected_runtime``.
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
        output_node["primary_layer"] = membership[0]
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

    runtime_overlay_ids = set(selected_node_ids)
    effective_memberships = canonical_memberships

    # Reflect the selected runtime status on canonical nodes without changing
    # their semantic home. Observed execution is represented only by replay
    # execution telemetry, not by this snapshot.
    for node in canonical_nodes:
        node_id = node["id"]
        if node_id in runtime_overlay_ids:
            instance_id = f"{selected_snapshot['run_id']}::{node_id}" if selected_snapshot else None
            node["runtime_instance_id"] = instance_id
            matching = next((item for item in selected_instances if item["node_id"] == node_id), None)
            if matching is not None:
                node["runtime_status"] = matching.get("runtime_lane")

    layer_members: dict[str, list[str]] = {
        layer: sorted(
            [node_id for node_id, membership in effective_memberships.items() if layer in membership],
            key=lambda node_id: _node_sort_key(nodes_by_id[node_id]),
        )
        for layer in LAYER_NAMES
    }
    overlay_nodes = deepcopy(selected_instances)
    for item in overlay_nodes:
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
        runtime_touched = str(from_id) in runtime_overlay_ids or str(to_id) in runtime_overlay_ids
        default_animated = False
        relation = deepcopy(edge)
        relation["from_membership"] = list(from_membership)
        relation["to_membership"] = list(to_membership)
        relation["from_layer"] = from_membership[0] if from_membership else None
        relation["to_layer"] = to_membership[0] if to_membership else None
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
        relation["runtime_touched"] = runtime_touched
        if str(from_id) in runtime_overlay_ids:
            relation["from_instance_id"] = f"{selected_snapshot['run_id']}::{from_id}" if selected_snapshot else None
        if str(to_id) in runtime_overlay_ids:
            relation["to_instance_id"] = f"{selected_snapshot['run_id']}::{to_id}" if selected_snapshot else None
        relations.append(relation)

    interfaces: dict[str, dict[str, Any]] = {}
    for name, left, right in (
        ("state-control", "state", "control"),
        ("control-action", "control", "action"),
        ("action-state", "action", "state"),
    ):
        relation_ids = sorted(
            [edge_id for edge_id, edge_interfaces in relation_interface_map.items() if name in edge_interfaces],
            key=lambda edge_id: _edge_sort_key(edge_by_id[edge_id]),
        )
        endpoint_ids = sorted(
            {
                str(endpoint)
                for edge_id in relation_ids
                for endpoint in (edge_by_id[edge_id].get("from"), edge_by_id[edge_id].get("to"))
                if str(endpoint) in nodes_by_id
            },
            key=lambda node_id: _node_sort_key(nodes_by_id[node_id]),
        )
        interfaces[name] = {
            "id": name,
            "layers": [left, right],
            "membership": [],
            "node_ids": endpoint_ids,
            "instance_ids": [],
            "relation_ids": relation_ids,
        }

    layers: dict[str, dict[str, Any]] = {}
    for layer in LAYER_NAMES:
        members = list(layer_members[layer])
        layers[layer] = {
            "id": layer,
            "membership": members,
            "node_ids": members,
            "instance_ids": [],
            "node_count": len(members),
            "status": "populated" if members else "empty",
        }

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
        "runtime_overlay": {
            "status": "populated" if selected_instances else "empty",
            "membership": list(selected_node_ids),
            "node_ids": list(selected_node_ids),
            "instance_ids": list(selected_instance_ids),
            "nodes": overlay_nodes,
            "selected_runtime": selected_runtime,
        },
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
    "ACTION_NODE_TYPES",
    "CONTROL_NODE_TYPES",
    "EXECUTION_NODE_TYPES",
    "INTERFACE_NAMES",
    "KNOWLEDGE_NODE_TYPES",
    "LAYER_NAMES",
    "SPATIAL_PROTOCOL_VERSION",
    "STATE_NODE_TYPES",
    "build_spatial_catalog",
    "build_spatial_projection",
]
