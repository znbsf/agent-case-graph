from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


PROTOCOL_VERSION = "paper-trace-0.1"

PHASE_ORDER = ("context", "plan", "inspect", "execute", "validate", "claim")

PHASE_BY_TYPE = {
    "Case": "context",
    "Run": "context",
    "Goal": "context",
    "Input": "context",
    "Evidence": "inspect",
    "Constraint": "context",
    "ScopeBoundary": "context",
    "EnvironmentSnapshot": "context",
    "ExternalIssue": "context",
    "Decision": "plan",
    "Plan": "plan",
    "Task": "plan",
    "Step": "inspect",
    "Observation": "inspect",
    "Uncertainty": "inspect",
    "Action": "execute",
    "ToolCall": "execute",
    "Artifact": "execute",
    "Verification": "validate",
    "Check": "validate",
    "AcceptanceCriterion": "validate",
    "VerificationReceipt": "validate",
    "Claim": "claim",
    "RootCause": "claim",
    "Outcome": "claim",
    "Pattern": "claim",
    "Runbook": "claim",
    "SkillVersion": "claim",
    "EvalCase": "validate",
}

EVIDENCE_TYPES = {
    "Observation",
    "Evidence",
    "Artifact",
    "Verification",
    "VerificationReceipt",
    "Check",
    "Claim",
    "RootCause",
    "AcceptanceCriterion",
    "Uncertainty",
    "ScopeBoundary",
    "Approval",
}

# Only forward control/dependency relations may constrain the layered DAG.
# Evidence relations intentionally point both from evidence to claims and from
# decisions/actions back to their basis, so mixing them into one topological
# sort can create a valid review cycle and collapse the layout to a line.
LAYOUT_EDGE_TYPES = {
    "has_run",
    "contains",
    "precedes",
    "implemented_by",
    "targets",
    "invokes",
    "modifies",
    "satisfies",
    "tested_by",
}


def _phase(node: dict[str, Any]) -> str:
    authored = str(node.get("attrs", {}).get("workflow_phase", "")).lower()
    if authored in PHASE_ORDER:
        return authored
    return PHASE_BY_TYPE.get(node["type"], "execute")


def _status(node: dict[str, Any]) -> str:
    attrs = node.get("attrs", {})
    return str(attrs.get("current_state") or attrs.get("status") or "recorded")


def _ranks(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, int]:
    ids = {node["id"] for node in nodes}
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in ids}
    for edge in edges:
        if edge["type"] not in LAYOUT_EDGE_TYPES:
            continue
        source, target = edge["from"], edge["to"]
        if source not in ids or target not in ids or source == target:
            continue
        outgoing[source].append(target)
        indegree[target] += 1

    queue = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    ranks = {node_id: 0 for node_id in ids}
    visited = 0
    while queue:
        source = queue.popleft()
        visited += 1
        for target in sorted(outgoing[source]):
            ranks[target] = max(ranks[target], ranks[source] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    if visited != len(ids):
        # Lint owns cycle reporting. The review projection stays deterministic.
        return {node["id"]: index for index, node in enumerate(nodes)}
    return ranks


def build_trace_model(
    graph: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    ranks = _ranks(graph["nodes"], graph["edges"])
    event_sequence = {event["event_id"]: event["sequence"] for event in events}
    nodes = []
    for node in graph["nodes"]:
        attrs = node.get("attrs", {})
        nodes.append(
            {
                "id": node["id"],
                "type": node["type"],
                "label": node["label"],
                "phase": _phase(node),
                "status": _status(node),
                "rank": ranks[node["id"]],
                "level": "evidence" if node["type"] in EVIDENCE_TYPES else "workflow",
                "tool": attrs.get("action_tool") or attrs.get("tool") or attrs.get("executor"),
                "output": attrs.get("action_output") or attrs.get("output") or attrs.get("result"),
                "attrs": attrs,
                "event_ids": list(node.get("event_ids", [])),
                "first_sequence": min(
                    (
                        event_sequence[event_id]
                        for event_id in node.get("event_ids", [])
                        if event_id in event_sequence
                    ),
                    default=None,
                ),
            }
        )

    node_ids = {node["id"] for node in nodes}
    edges = [
        {
            "id": edge["id"],
            "type": edge["type"],
            "from": edge["from"],
            "to": edge["to"],
            "layout": edge["type"] in LAYOUT_EDGE_TYPES,
            "attrs": edge.get("attrs", {}),
        }
        for edge in graph["edges"]
        if edge["from"] in node_ids and edge["to"] in node_ids
    ]

    primary_ids = {
        node["id"]
        for node in nodes
        if node["level"] == "workflow"
    }
    for edge in edges:
        if edge["layout"] and edge["type"] not in {"contains", "has_run"}:
            primary_ids.update((edge["from"], edge["to"]))
    for node in nodes:
        node["primary"] = node["id"] in primary_ids

    trace = [
        {
            "sequence": event["sequence"],
            "event_id": event["event_id"],
            "kind": event["kind"],
            "actor": event["actor"],
            "occurred_at": event["occurred_at"],
            "capture_mode": event["provenance"]["capture_mode"],
            "source_refs": list(event["provenance"].get("source_refs", [])),
            "node_id": event.get("node", {}).get("id"),
            "edge_id": event.get("edge", {}).get("id"),
        }
        for event in events
    ]

    return {
        "protocol_version": PROTOCOL_VERSION,
        "graph_id": graph["graph_id"],
        "root_id": graph["root_id"],
        "generated_at": graph["generated_at"],
        "phases": list(PHASE_ORDER),
        "nodes": nodes,
        "edges": edges,
        "trace": trace,
        "stats": graph["stats"],
        "principles": {
            "primary_reading": "workflow",
            "layout": "layered-top-down-dag",
            "layout_edge_types": sorted(LAYOUT_EDGE_TYPES),
            "primary_node_policy": "workflow + forward-layout endpoints",
            "parallel_order": "neighbor median + first source sequence + stable id",
            "review_direction": "claim-to-evidence",
            "source_records_preserved": True,
            "position_is_semantic": False,
        },
    }
