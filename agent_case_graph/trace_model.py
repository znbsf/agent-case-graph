from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


PROTOCOL_VERSION = "paper-trace-0.1"

PHASE_ORDER = ("context", "plan", "inspect", "execute", "validate", "claim")

PHASE_BY_TYPE = {
    "Case": "context",
    "Run": "context",
    "Goal": "context",
    "DialogueRound": "context",
    "ExecutionIteration": "execute",
    "UserFeedback": "context",
    "AgentResponse": "claim",
    "Evaluation": "validate",
    "Aggregate": "context",
    "ReasoningSummary": "inspect",
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
    "ToolOutput": "execute",
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
    "ReasoningSummary",
    "ToolOutput",
    "Evaluation",
}

# Only forward control/dependency relations may constrain the layered DAG.
# Evidence relations intentionally point both from evidence to claims and from
# decisions/actions back to their basis, so mixing them into one topological
# sort can create a valid review cycle and collapse the layout to a line.
LAYOUT_EDGE_TYPES = {
    "has_run",
    "precedes",
    "implemented_by",
    "targets",
    "invokes",
    "produces",
    "modifies",
    "satisfies",
    "tested_by",
    "frames",
}


def _phase(node: dict[str, Any]) -> str:
    authored = str(node.get("attrs", {}).get("workflow_phase", "")).lower()
    if authored in PHASE_ORDER:
        return authored
    return PHASE_BY_TYPE.get(node["type"], "execute")


def _status(node: dict[str, Any]) -> str:
    attrs = node.get("attrs", {})
    return str(attrs.get("current_state") or attrs.get("status") or "recorded")


def _is_layout_edge(edge: dict[str, Any], node_types: dict[str, str]) -> bool:
    if edge["type"] not in LAYOUT_EDGE_TYPES:
        return False
    if edge["type"] != "produces":
        return True
    return edge.get("attrs", {}).get("flow") is True or (
        node_types.get(edge["from"]) == "ToolCall"
        and node_types.get(edge["to"]) == "ToolOutput"
    )


def _ranks(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, int]:
    ids = {node["id"] for node in nodes}
    node_types = {node["id"]: node["type"] for node in nodes}
    outgoing: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if not _is_layout_edge(edge, node_types):
            continue
        source, target = edge["from"], edge["to"]
        if source not in ids or target not in ids or source == target:
            continue
        outgoing[source].add(target)

    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node_id: str) -> None:
        nonlocal index
        indices[node_id] = lowlinks[node_id] = index
        index += 1
        stack.append(node_id)
        on_stack.add(node_id)
        for target in sorted(outgoing[node_id]):
            if target not in indices:
                visit(target)
                lowlinks[node_id] = min(lowlinks[node_id], lowlinks[target])
            elif target in on_stack:
                lowlinks[node_id] = min(lowlinks[node_id], indices[target])
        if lowlinks[node_id] == indices[node_id]:
            component: list[str] = []
            while stack:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node_id:
                    break
            components.append(sorted(component))

    for node_id in sorted(ids):
        if node_id not in indices:
            visit(node_id)

    component_of = {
        node_id: component_id
        for component_id, component in enumerate(components)
        for node_id in component
    }
    component_outgoing: dict[int, set[int]] = defaultdict(set)
    component_indegree = {component_id: 0 for component_id in range(len(components))}
    for source, targets in outgoing.items():
        for target in targets:
            source_component = component_of[source]
            target_component = component_of[target]
            if source_component == target_component or target_component in component_outgoing[source_component]:
                continue
            component_outgoing[source_component].add(target_component)
            component_indegree[target_component] += 1

    component_key = {index: component[0] for index, component in enumerate(components)}
    ready = deque(
        sorted(
            (component_id for component_id, degree in component_indegree.items() if degree == 0),
            key=component_key.get,
        )
    )
    component_rank = {component_id: 0 for component_id in range(len(components))}
    while ready:
        source = ready.popleft()
        for target in sorted(component_outgoing[source], key=component_key.get):
            component_rank[target] = max(component_rank[target], component_rank[source] + 1)
            component_indegree[target] -= 1
            if component_indegree[target] == 0:
                ready.append(target)
    return {node_id: component_rank[component_of[node_id]] for node_id in ids}


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
                "provenance": node.get("provenance", {}),
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
    node_types = {node["id"]: node["type"] for node in graph["nodes"]}
    edges = [
        {
            "id": edge["id"],
            "type": edge["type"],
            "from": edge["from"],
            "to": edge["to"],
            "layout": _is_layout_edge(edge, node_types),
            "attrs": edge.get("attrs", {}),
            "provenance": edge.get("provenance", {}),
            "event_ids": list(edge.get("event_ids", [])),
            "first_sequence": edge.get("first_sequence"),
            "last_sequence": edge.get("last_sequence"),
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
