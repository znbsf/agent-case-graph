from __future__ import annotations

from collections import defaultdict, deque
import re
from typing import Any

from .model import ACGError


EXECUTABLE_NODE_TYPES = {"Step", "Action", "ToolCall", "Verification"}
SUCCESS_STATUSES = {"completed", "succeeded", "passed", "verified", "skipped"}
ACTIVE_STATUSES = {"claimed", "running", "in_progress"}
FAILED_STATUSES = {"failed", "error", "cancelled", "aborted", "unknown"}
GRANTED_APPROVAL_STATUSES = {"granted", "approved"}
RESOLVED_BLOCKER_STATUSES = SUCCESS_STATUSES | {
    "accepted",
    "closed",
    "granted",
    "resolved",
    "satisfied",
}

CONTEXT_EDGE_TYPES = {
    "approved_by",
    "checks",
    "derived_from",
    "explains",
    "guarded_by",
    "invokes",
    "modifies",
    "produces",
    "references",
    "satisfies",
    "supports",
    "targets",
    "uses",
    "frames",
    "informs",
}

CONTEXT_LINEAGE_NODE_TYPES = {"Action", "Step", "ToolCall", "Plan", "Decision"}


def _status(node: dict[str, Any]) -> str:
    value = node.get("attrs", {}).get("status", "pending")
    return str(value).strip().lower() or "pending"


def _selection_key(node: dict[str, Any]) -> tuple[int, int, str]:
    raw_priority = node.get("attrs", {}).get("priority", 100)
    try:
        priority = int(raw_priority)
    except (TypeError, ValueError):
        priority = 100
    return priority, int(node.get("first_sequence", 0)), node["id"]


def _node_summary(node: dict[str, Any], **extra: Any) -> dict[str, Any]:
    attrs = node.get("attrs", {})
    summary: dict[str, Any] = {
        "id": node["id"],
        "type": node["type"],
        "label": node["label"],
        "status": _status(node),
        "first_sequence": node.get("first_sequence"),
    }
    for key in ("executor", "mutating", "authorized_scope", "priority"):
        if key in attrs:
            summary[key] = attrs[key]
    # Keep actionable references, never inline arbitrary logs or tool payloads.
    references = {
        key: attrs[key]
        for key in ("path", "source_path", "source_uri", "sha256", "input_ref", "output_ref")
        if isinstance(attrs.get(key), str) and attrs[key]
    }
    for key in ("input_refs", "output_refs", "acceptance_criteria"):
        value = attrs.get(key)
        if isinstance(value, str):
            references[key] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            references[key] = list(value)
    if references:
        summary["references"] = references
    provenance = node.get("provenance", {})
    source_refs = provenance.get("source_refs", [])
    if source_refs:
        summary["source_refs"] = list(source_refs)
    if node.get("event_ids"):
        summary["event_ids"] = list(node["event_ids"])
    summary.update(extra)
    return summary


def _latest_runtime_run(graph: dict[str, Any]) -> str | None:
    candidates: list[dict[str, Any]] = []
    for run in graph["nodes"]:
        if run["type"] != "Run":
            continue
        _, runtime_nodes = _runtime_nodes_for_run(graph, run["id"])
        if runtime_nodes:
            candidates.append(run)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.get("first_sequence", 0), item["id"]))["id"]


def _runtime_nodes_for_run(
    graph: dict[str, Any], run_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    nodes = {node["id"]: node for node in graph["nodes"]}
    run = nodes.get(run_id)
    if run is None or run.get("type") != "Run":
        raise ACGError(f"runtime Run does not exist: {run_id}")

    children: dict[str, list[str]] = defaultdict(list)
    for edge in graph["edges"]:
        if edge["type"] == "contains":
            children[edge["from"]].append(edge["to"])
    contained_ids: set[str] = set()
    frontier = [run_id]
    while frontier:
        scope_id = frontier.pop()
        for child_id in sorted(children.get(scope_id, []), reverse=True):
            if child_id not in contained_ids:
                contained_ids.add(child_id)
                frontier.append(child_id)
    runtime_nodes = [
        nodes[node_id]
        for node_id in contained_ids
        if node_id in nodes
        and nodes[node_id]["type"] in EXECUTABLE_NODE_TYPES
        and nodes[node_id].get("attrs", {}).get("runtime_managed") is True
    ]
    runtime_nodes.sort(key=_selection_key)
    return run, runtime_nodes


def runtime_nodes_for_run(graph: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    """Return runtime-managed descendants of a Run without executing anything."""

    _, nodes = _runtime_nodes_for_run(graph, run_id)
    return nodes


def _find_precedes_cycle(
    node_ids: set[str], edges: list[dict[str, Any]]
) -> list[str]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if (
            edge["type"] == "precedes"
            and edge["from"] in node_ids
            and edge["to"] in node_ids
        ):
            adjacency[edge["from"]].append(edge["to"])
    for targets in adjacency.values():
        targets.sort()

    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []

    def visit(node_id: str) -> list[str] | None:
        if node_id in visiting:
            start = path.index(node_id)
            return path[start:] + [node_id]
        if node_id in visited:
            return None
        visiting.add(node_id)
        path.append(node_id)
        for target_id in adjacency[node_id]:
            cycle = visit(target_id)
            if cycle:
                return cycle
        path.pop()
        visiting.remove(node_id)
        visited.add(node_id)
        return None

    for node_id in sorted(node_ids):
        cycle = visit(node_id)
        if cycle:
            return cycle
    return []


def _approval_covers(action: dict[str, Any], approval: dict[str, Any]) -> bool:
    action_scope = str(action.get("attrs", {}).get("authorized_scope", "")).strip()
    raw_scope = approval.get("attrs", {}).get("scope", "")
    if not action_scope or raw_scope is None:
        return False
    if isinstance(raw_scope, list):
        approval_scopes = {
            str(item).strip().casefold()
            for item in raw_scope
            if isinstance(item, str) and item.strip()
        }
    else:
        approval_scopes = {
            item.strip().casefold()
            for item in re.split(r"[,;\n]", str(raw_scope))
            if item.strip()
        }
    return "*" in approval_scopes or action_scope.casefold() in approval_scopes


def _context_packet(
    graph: dict[str, Any],
    *,
    run: dict[str, Any],
    node: dict[str, Any],
    predecessor_ids: list[str],
    nodes: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    related: dict[str, dict[str, Any]] = {}

    def include(node_id: str, relation: str, direction: str) -> None:
        candidate = nodes.get(node_id)
        if candidate is None or node_id == node["id"]:
            return
        existing = related.get(node_id)
        value = _node_summary(candidate, relation=relation, direction=direction)
        if existing is None or (relation, direction) < (
            existing.get("relation", ""),
            existing.get("direction", ""),
        ):
            related[node_id] = value

    include(graph["root_id"], "case", "scope")
    include(run["id"], "run", "scope")

    for edge in outgoing[node["id"]] + incoming[node["id"]]:
        if edge["type"] not in CONTEXT_EDGE_TYPES:
            continue
        if edge["from"] == node["id"]:
            include(edge["to"], edge["type"], "outgoing")
        elif edge["to"] == node["id"]:
            include(edge["from"], edge["type"], "incoming")

    lineage_queue = deque([(node["id"], 0)])
    lineage_seen = {node["id"]}
    while lineage_queue:
        current_id, depth = lineage_queue.popleft()
        if depth >= 3:
            continue
        for edge in incoming[current_id]:
            if edge["type"] not in CONTEXT_EDGE_TYPES:
                continue
            source_id = edge["from"]
            include(source_id, edge["type"], "context_lineage")
            source = nodes.get(source_id)
            if (
                source is not None
                and source["type"] in CONTEXT_LINEAGE_NODE_TYPES
                and source_id not in lineage_seen
            ):
                lineage_seen.add(source_id)
                lineage_queue.append((source_id, depth + 1))

    for predecessor_id in predecessor_ids:
        include(predecessor_id, "precedes", "incoming")
        for edge in outgoing[predecessor_id]:
            if edge["type"] == "produces":
                include(edge["to"], "produces", "predecessor_output")

    for edge in outgoing[run["id"]]:
        if edge["type"] in {"targets", "uses", "references"}:
            include(edge["to"], edge["type"], "run_scope")

    context_nodes = sorted(
        related.values(), key=lambda item: (item.get("first_sequence") or 0, item["id"])
    )
    full_count = len(graph["nodes"])
    selected_count = len(context_nodes) + 1
    reduction = 0.0 if full_count == 0 else round(1 - selected_count / full_count, 4)
    return {
        "task": _node_summary(node),
        "nodes": context_nodes,
        "selected_node_count": selected_count,
        "full_graph_node_count": full_count,
        "context_reduction_ratio": reduction,
        "node_reduction_ratio": reduction,
        "measurement_basis": "node_count",
    }


def build_runtime_snapshot(
    graph: dict[str, Any], *, run_id: str | None = None
) -> dict[str, Any]:
    selected_run_id = run_id or _latest_runtime_run(graph)
    if selected_run_id is None:
        return {
            "status": "not_configured",
            "run_id": None,
            "message": "No Run contains runtime_managed Step/Action/Verification nodes.",
            "ready": [],
            "running": [],
            "blocked": [],
            "completed": [],
            "failed": [],
        }

    run, runtime_nodes = _runtime_nodes_for_run(graph, selected_run_id)
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    runtime_ids = {node["id"] for node in runtime_nodes}
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph["edges"]:
        outgoing[edge["from"]].append(edge)
        incoming[edge["to"]].append(edge)

    cycle = _find_precedes_cycle(runtime_ids, graph["edges"])
    ready: list[dict[str, Any]] = []
    running: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    root = node_by_id.get(graph["root_id"], {})
    case_state = str(root.get("attrs", {}).get("current_state", ""))

    for node in runtime_nodes:
        node_id = node["id"]
        status = _status(node)
        predecessor_ids = sorted(
            {
                edge["from"]
                for edge in incoming[node_id]
                if edge["type"] == "precedes" and edge["from"] in runtime_ids
            }
        )
        context = _context_packet(
            graph, run=run, node=node, predecessor_ids=predecessor_ids,
            nodes=node_by_id, outgoing=outgoing, incoming=incoming,
        )
        base = _node_summary(
            node,
            predecessors=predecessor_ids,
            context=context,
            selection_key=list(_selection_key(node)),
        )

        if status in SUCCESS_STATUSES:
            completed.append(base)
            continue
        if status in ACTIVE_STATUSES:
            running.append(base)
            continue
        if status in FAILED_STATUSES:
            failed.append(base)
            continue

        reasons: list[dict[str, Any]] = []
        if cycle:
            reasons.append(
                {
                    "code": "precedes_cycle",
                    "message": "The runtime precedes graph contains a cycle.",
                    "nodes": cycle,
                }
            )

        for predecessor_id in predecessor_ids:
            predecessor = node_by_id[predecessor_id]
            predecessor_status = _status(predecessor)
            if predecessor_status in FAILED_STATUSES:
                reasons.append(
                    {
                        "code": "predecessor_failed",
                        "node_id": predecessor_id,
                        "message": f"Predecessor is {predecessor_status}.",
                    }
                )
            elif predecessor_status not in SUCCESS_STATUSES:
                reasons.append(
                    {
                        "code": "predecessor_incomplete",
                        "node_id": predecessor_id,
                        "message": f"Predecessor is {predecessor_status}.",
                    }
                )

        for edge in outgoing[node_id]:
            if edge["type"] != "blocked_by":
                continue
            blocker = node_by_id.get(edge["to"])
            blocker_status = _status(blocker) if blocker else "missing"
            if blocker is None or blocker_status not in RESOLVED_BLOCKER_STATUSES:
                reasons.append(
                    {
                        "code": "explicit_blocker",
                        "node_id": edge["to"],
                        "message": f"Explicit blocker is {blocker_status}.",
                    }
                )

        attrs = node.get("attrs", {})
        if attrs.get("mutating") is True:
            target_edges = [
                edge for edge in outgoing[node_id]
                if (
                    edge["type"] == "targets"
                    and node_by_id.get(edge["to"], {}).get("type") == "Target"
                ) or (
                    edge["type"] == "modifies"
                    and node_by_id.get(edge["to"], {}).get("type") in {"Target", "Artifact"}
                )
            ]
            if not target_edges:
                reasons.append(
                    {
                        "code": "target_missing",
                        "message": "Mutating node requires targets -> Target or modifies -> Target/Artifact.",
                    }
                )

            approval_nodes = [
                node_by_id[edge["to"]]
                for edge in outgoing[node_id]
                if edge["type"] == "approved_by"
                and node_by_id.get(edge["to"], {}).get("type") == "Approval"
            ]
            granted = [
                approval
                for approval in approval_nodes
                if _status(approval) in GRANTED_APPROVAL_STATUSES
                and _approval_covers(node, approval)
            ]
            if not approval_nodes:
                reasons.append(
                    {
                        "code": "approval_missing",
                        "message": "Mutating node has no typed Approval.",
                    }
                )
            elif not granted:
                reasons.append(
                    {
                        "code": "approval_not_granted_or_scope_mismatch",
                        "nodes": [approval["id"] for approval in approval_nodes],
                        "message": "No granted Approval covers authorized_scope.",
                    }
                )
            if case_state != "execute":
                reasons.append(
                    {
                        "code": "case_not_executing",
                        "message": f"Mutating node requires Case state execute, got {case_state or 'unset'}.",
                    }
                )
            if run.get("attrs", {}).get("capture_mode") != "live":
                reasons.append(
                    {
                        "code": "non_live_mutation",
                        "message": "Mutating node requires an explicitly live Run.",
                    }
                )

        if reasons:
            blocked.append({**base, "blockers": reasons})
        else:
            ready.append({**base, "ready_reason": "All explicit runtime gates are satisfied."})

    ready.sort(key=lambda item: tuple(item["selection_key"]))
    running.sort(key=lambda item: tuple(item["selection_key"]))
    blocked.sort(key=lambda item: tuple(item["selection_key"]))
    completed.sort(key=lambda item: tuple(item["selection_key"]))
    failed.sort(key=lambda item: tuple(item["selection_key"]))

    return {
        "status": "invalid" if cycle else "configured",
        "run_id": run["id"],
        "run_label": run["label"],
        "capture_mode": run.get("attrs", {}).get("capture_mode"),
        "case_state": case_state,
        "cycle": cycle,
        "ready": ready,
        "next_action_ids": [item["id"] for item in ready],
        "running": running,
        "blocked": blocked,
        "completed": completed,
        "failed": failed,
        "counts": {
            "ready": len(ready),
            "running": len(running),
            "blocked": len(blocked),
            "completed": len(completed),
            "failed": len(failed),
        },
    }


def build_runtime_catalog(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = {node["id"]: node for node in graph["nodes"]}
    run_ids = [
        run["id"]
        for run in graph["nodes"]
        if run["type"] == "Run" and runtime_nodes_for_run(graph, run["id"])
    ]
    unique_run_ids = sorted(
        set(run_ids),
        key=lambda item: (nodes[item].get("first_sequence", 0), item),
        reverse=True,
    )
    return {
        "protocol_version": "runtime-0.1",
        "runs": [build_runtime_snapshot(graph, run_id=run_id) for run_id in unique_run_ids],
    }


def validate_step_transition(
    graph: dict[str, Any],
    *,
    node_id: str,
    to_status: str,
    run_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = to_status.strip().lower()
    allowed_targets = {"running", "completed", "failed", "blocked", "skipped"}
    if normalized not in allowed_targets:
        raise ACGError(
            f"unsupported runtime status {to_status!r}; expected {sorted(allowed_targets)}"
        )

    snapshot = build_runtime_snapshot(graph, run_id=run_id)
    if snapshot["status"] == "not_configured":
        raise ACGError("runtime is not configured for this graph")

    all_entries = [
        *snapshot["ready"],
        *snapshot["running"],
        *snapshot["blocked"],
        *snapshot["completed"],
        *snapshot["failed"],
    ]
    entry = next((item for item in all_entries if item["id"] == node_id), None)
    if entry is None:
        raise ACGError(f"node is not runtime_managed in Run {snapshot['run_id']}: {node_id}")

    current = entry["status"]
    ready_ids = {item["id"] for item in snapshot["ready"]}
    if normalized == "running":
        if node_id not in ready_ids:
            blockers = next(
                (item.get("blockers", []) for item in snapshot["blocked"] if item["id"] == node_id),
                [],
            )
            raise ACGError(
                f"node is not Ready: {node_id}; status={current}; blockers={blockers}"
            )
    elif normalized in {"completed", "failed", "blocked"}:
        if current not in ACTIVE_STATUSES:
            raise ACGError(
                f"runtime transition requires an active node: {current} -> {normalized}"
            )
    elif normalized == "skipped":
        if current in SUCCESS_STATUSES | ACTIVE_STATUSES:
            raise ACGError(f"cannot skip node from status {current}")
        if entry.get("mutating") is True:
            raise ACGError("mutating node cannot be silently skipped")

    nodes = {node["id"]: node for node in graph["nodes"]}
    return nodes[node_id], snapshot


def render_runtime_snapshot(snapshot: dict[str, Any]) -> str:
    if snapshot["status"] == "not_configured":
        return snapshot["message"]
    lines = [
        f"Run: {snapshot['run_id']} ({snapshot['run_label']})",
        f"Case state: {snapshot['case_state']}",
        (
            "Frontier: "
            f"{snapshot['counts']['ready']} ready / "
            f"{snapshot['counts']['running']} running / "
            f"{snapshot['counts']['blocked']} blocked / "
            f"{snapshot['counts']['completed']} completed / "
            f"{snapshot['counts']['failed']} failed"
        ),
    ]
    for item in snapshot["ready"]:
        context = item["context"]
        lines.append(
            f"READY   {item['id']}: {item['label']} "
            f"(context {context['selected_node_count']}/{context['full_graph_node_count']}, "
            f"node reduction {context['node_reduction_ratio']:.1%})"
        )
    for item in snapshot["running"]:
        lines.append(f"RUNNING {item['id']}: {item['label']}")
    for item in snapshot["blocked"]:
        reason_text = "; ".join(reason["code"] for reason in item["blockers"])
        lines.append(f"BLOCKED {item['id']}: {reason_text}")
    for item in snapshot["failed"]:
        lines.append(f"FAILED  {item['id']}: {item['label']}")
    return "\n".join(lines)
