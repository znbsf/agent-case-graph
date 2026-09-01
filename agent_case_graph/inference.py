from __future__ import annotations

from collections import defaultdict
from typing import Any


SEMANTIC_TYPES = {
    "Goal", "Plan", "ReasoningSummary", "ToolCall", "ToolOutput", "Claim", "RootCause"
}


def _ordered_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(nodes, key=lambda node: (node.get("first_sequence", 0), node["id"]))


def _provenance(node: dict[str, Any]) -> dict[str, list[str]]:
    value = node.get("provenance", {})
    return {
        "capture_modes": list(value.get("capture_modes", [])),
        "source_refs": list(value.get("source_refs", [])),
        "run_ids": list(value.get("run_ids", [])),
    }


def _action_groups(
    node_ids: set[str], nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[list[list[str]], list[str]]:
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in node_ids}
    for edge in edges:
        if edge["type"] != "precedes":
            continue
        source, target = edge["from"], edge["to"]
        if source not in node_ids or target not in node_ids or source == target:
            continue
        outgoing[source].append(target)
        indegree[target] += 1

    remaining = set(node_ids)
    groups: list[list[str]] = []
    while remaining:
        ready = _ordered_nodes(
            [nodes[node_id] for node_id in remaining if indegree[node_id] == 0]
        )
        if not ready:
            cyclic = _ordered_nodes([nodes[node_id] for node_id in remaining])
            return groups, [node["id"] for node in cyclic]
        group = [node["id"] for node in ready]
        groups.append(group)
        for source in group:
            remaining.remove(source)
            for target in outgoing[source]:
                indegree[target] -= 1
    return groups, []


def _run_scope(
    graph: dict[str, Any], run_id: str | None
) -> tuple[str | None, set[str] | None, list[dict[str, str]]]:
    nodes = {node["id"]: node for node in graph["nodes"]}
    members: dict[str, set[str]] = defaultdict(set)
    for edge in graph["edges"]:
        if edge["type"] == "contains" and nodes.get(edge["from"], {}).get("type") == "Run":
            members[edge["from"]].add(edge["to"])
    relevant = sorted(
        candidate
        for candidate, node_ids in members.items()
        if any(nodes.get(node_id, {}).get("type") in SEMANTIC_TYPES for node_id in node_ids)
    )
    if run_id is not None:
        if run_id not in members:
            return run_id, set(), [{"code": "run_not_found", "node_id": run_id}]
        return run_id, members[run_id], []
    if len(relevant) == 1:
        return relevant[0], members[relevant[0]], []
    if len(relevant) > 1:
        return None, set(), [
            {"code": "multiple_runs_require_selection", "node_id": ",".join(relevant)}
        ]
    return None, None, []


def infer_workflow(graph: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    """Reconstruct a workflow using only explicit canonical graph semantics."""

    selected_run, scope_ids, gaps = _run_scope(graph, run_id)
    if gaps:
        return {
            "protocol_version": "workflow-inference-0.2",
            "source": "canonical-graph-only",
            "status": "ambiguous" if gaps[0]["code"].startswith("multiple") else "invalid",
            "run_id": selected_run,
            "capture_modes": [],
            "actualness": "unresolved",
            "goals": [], "plans": [], "claims": [], "gaps": gaps,
        }

    source_nodes = graph["nodes"] if scope_ids is None else [
        node for node in graph["nodes"] if node["id"] in scope_ids
    ]
    nodes = {node["id"]: node for node in source_nodes}
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scoped_edges = [
        edge for edge in graph["edges"] if edge["from"] in nodes and edge["to"] in nodes
    ]
    for edge in scoped_edges:
        outgoing[edge["from"]].append(edge)
        incoming[edge["to"]].append(edge)

    capture_modes = sorted({
        mode
        for node in source_nodes
        for mode in node.get("provenance", {}).get("capture_modes", [])
    })
    actualness = (
        "live-captured" if capture_modes == ["live"]
        else capture_modes[0] if len(capture_modes) == 1
        else "mixed" if capture_modes else "unknown"
    )
    goals = _ordered_nodes([node for node in nodes.values() if node["type"] == "Goal"])
    plans = _ordered_nodes([node for node in nodes.values() if node["type"] == "Plan"])
    plan_rows: list[dict[str, Any]] = []

    for plan in plans:
        framed_by = [
            nodes[edge["from"]] for edge in incoming[plan["id"]]
            if edge["type"] == "frames" and edge["from"] in nodes
        ]
        informed_by = [
            nodes[edge["from"]] for edge in incoming[plan["id"]]
            if edge["type"] in {"informs", "derived_from"} and edge["from"] in nodes
        ]
        invoked_ids = {
            edge["to"] for edge in outgoing[plan["id"]]
            if edge["type"] in {"invokes", "implemented_by"} and edge["to"] in nodes
        }
        group_ids, cycle_ids = _action_groups(invoked_ids, nodes, scoped_edges)
        actions: list[dict[str, Any]] = []
        action_groups = []
        for group_index, group in enumerate(group_ids):
            group_actions = []
            for action_id in group:
                action = nodes[action_id]
                outputs = [
                    nodes[edge["to"]] for edge in outgoing[action_id]
                    if edge["type"] == "produces" and edge["to"] in nodes
                ]
                claim_relations = []
                for output in outputs:
                    for edge in outgoing[output["id"]]:
                        if edge["type"] in {"supports", "refutes", "explains"} and edge["to"] in nodes:
                            claim_relations.append({
                                "edge_id": edge["id"],
                                "relation": edge["type"],
                                "evidence_id": output["id"],
                                "claim_id": edge["to"],
                            })
                row = {
                    "id": action["id"], "label": action["label"], "type": action["type"],
                    "parallel_group": group_index,
                    "parallel": len(group) > 1,
                    "outputs": [item["id"] for item in _ordered_nodes(outputs)],
                    "supported_claims": sorted({
                        item["claim_id"] for item in claim_relations if item["relation"] == "supports"
                    }),
                    "refuted_claims": sorted({
                        item["claim_id"] for item in claim_relations if item["relation"] == "refutes"
                    }),
                    "claim_relations": claim_relations,
                    "provenance": _provenance(action),
                }
                actions.append(row)
                group_actions.append(action_id)
                if not outputs:
                    gaps.append({"code": "tool_without_output", "node_id": action_id})
            action_groups.append({
                "index": group_index,
                "mode": "parallel_or_unordered" if len(group_actions) > 1 else "sequential",
                "action_ids": group_actions,
            })
        if cycle_ids:
            gaps.append({"code": "precedes_cycle", "node_id": ",".join(cycle_ids)})
        if not framed_by:
            gaps.append({"code": "plan_without_goal_context", "node_id": plan["id"]})
        if not invoked_ids:
            gaps.append({"code": "plan_without_action", "node_id": plan["id"]})
        plan_rows.append({
            "id": plan["id"], "label": plan["label"],
            "framed_by": [item["id"] for item in _ordered_nodes(framed_by)],
            "informed_by": [item["id"] for item in _ordered_nodes(informed_by)],
            "action_groups": action_groups,
            "actions": actions,
            "cyclic_action_ids": cycle_ids,
            "provenance": _provenance(plan),
        })

    framed_goal_ids = {goal_id for plan in plan_rows for goal_id in plan["framed_by"]}
    for goal in goals:
        if goal["id"] not in framed_goal_ids:
            gaps.append({"code": "goal_without_plan", "node_id": goal["id"]})

    claims = []
    for claim in _ordered_nodes(
        [node for node in nodes.values() if node["type"] in {"Claim", "RootCause"}]
    ):
        evidence_relations = [
            {"edge_id": edge["id"], "relation": edge["type"], "evidence_id": edge["from"]}
            for edge in incoming[claim["id"]]
            if edge["type"] in {"supports", "refutes", "explains"}
        ]
        claims.append({
            "id": claim["id"], "label": claim["label"],
            "evidence_relations": evidence_relations,
            "provenance": _provenance(claim),
        })
        if not evidence_relations:
            gaps.append({"code": "claim_without_evidence", "node_id": claim["id"]})

    gaps.sort(key=lambda item: (item["code"], item["node_id"]))
    return {
        "protocol_version": "workflow-inference-0.2",
        "source": "canonical-graph-only",
        "status": "complete" if not gaps else "incomplete",
        "run_id": selected_run,
        "capture_modes": capture_modes,
        "actualness": actualness,
        "goals": [
            {"id": node["id"], "label": node["label"], "provenance": _provenance(node)}
            for node in goals
        ],
        "plans": plan_rows,
        "claims": claims,
        "gaps": gaps,
    }
