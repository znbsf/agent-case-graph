from __future__ import annotations

from collections import Counter, defaultdict
import json
from typing import Any


PROTOCOL_VERSION = "loop-projection-0.1"

CRITICAL_TYPES = {
    "Goal",
    "Plan",
    "UserFeedback",
    "AgentResponse",
    "Evaluation",
    "Approval",
    "Claim",
    "Decision",
    "RootCause",
    "ScopeBoundary",
    "Verification",
    "VerificationReceipt",
}

FLOW_TYPES = {
    "frames",
    "informs",
    "invokes",
    "precedes",
    "produces",
    "retry_of",
    "supersedes",
    "supports",
    "refutes",
    "checks",
}

CONTROL_TYPES = {"frames", "informs", "invokes", "precedes", "produces", "retry_of", "supersedes"}
REVIEW_TYPES = {"supports", "refutes", "checks", "explains", "derived_from", "uses", "references"}


def _ordered(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def index_of(item: dict[str, Any]) -> int:
        value = item.get("attrs", {}).get("index")
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 10**9

    def sequence_of(item: dict[str, Any]) -> int:
        value = item.get("first_sequence")
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 10**9

    return sorted(
        items,
        key=lambda item: (
            index_of(item),
            sequence_of(item),
            item["id"],
        ),
    )


def _union_provenance(nodes: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        key: sorted(
            {
                value
                for node in nodes
                for value in node.get("provenance", {}).get(key, [])
            }
        )
        for key in ("capture_modes", "source_refs", "run_ids")
    }


def _cycle_members(
    nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]], edge_types: set[str]
) -> set[str]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    self_loops: set[str] = set()
    for edge in edges:
        if edge["type"] not in edge_types or edge["from"] not in nodes or edge["to"] not in nodes:
            continue
        adjacency[edge["from"]].append(edge["to"])
        if edge["from"] == edge["to"]:
            self_loops.add(edge["from"])
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    cyclic: set[str] = set(self_loops)

    def visit(node_id: str) -> None:
        nonlocal index
        indices[node_id] = lowlinks[node_id] = index
        index += 1
        stack.append(node_id)
        on_stack.add(node_id)
        for target in sorted(set(adjacency[node_id])):
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
            if len(component) > 1:
                cyclic.update(component)

    for node_id in sorted(nodes):
        if node_id not in indices:
            visit(node_id)
    return cyclic


def _critical_reasons(
    node: dict[str, Any], incoming: dict[str, list[dict[str, Any]]],
    outgoing: dict[str, list[dict[str, Any]]], control_cycle_ids: set[str], review_cycle_ids: set[str]
) -> list[str]:
    reasons: list[str] = []
    if node["type"] in CRITICAL_TYPES:
        reasons.append("semantic_boundary")
    flow_in = [edge for edge in incoming[node["id"]] if edge["type"] in FLOW_TYPES]
    flow_out = [edge for edge in outgoing[node["id"]] if edge["type"] in FLOW_TYPES]
    if len({edge["from"] for edge in flow_in}) > 1:
        reasons.append("merge")
    if len({edge["to"] for edge in flow_out}) > 1:
        reasons.append("branch")
    if any(edge["type"] in {"retry_of", "supersedes"} for edge in flow_in + flow_out):
        reasons.append("revision_boundary")
    if node["id"] in control_cycle_ids:
        reasons.append("control_cycle_member")
    if node["id"] in review_cycle_ids:
        reasons.append("review_cycle_member")
    return reasons


def _fallback_groups(
    nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        incoming[edge["to"]].append(edge)
        outgoing[edge["from"]].append(edge)
    rounds: list[dict[str, Any]] = []
    iterations: list[dict[str, Any]] = []
    plans = _ordered([node for node in nodes.values() if node["type"] == "Plan"])
    if not plans:
        goals = _ordered([node for node in nodes.values() if node["type"] == "Goal"])
        workflow_members = _ordered(
            [
                node
                for node in nodes.values()
                if node["type"] not in {"Case", "Run", "Goal"}
            ]
        )
        if goals or workflow_members:
            goal = goals[0] if goals else workflow_members[0]
            rounds.append(
                {
                    "id": "aggregate:dialogue:1",
                    "label": f"Display span: {goal['label']}",
                    "index": 0,
                    "member_ids": [node["id"] for node in goals],
                    "trigger_type": "unresolved_without_user_input_evidence",
                    "explicit": False,
                    "focus_member_id": goal["id"],
                }
            )
            iterations.append(
                {
                    "id": "aggregate:execution:1",
                    "label": "Execution span: workflow evidence",
                    "index": 0,
                    "round_id": "aggregate:dialogue:1",
                    "member_ids": [node["id"] for node in workflow_members],
                    "explicit": False,
                    "focus_member_id": workflow_members[0]["id"] if workflow_members else goal["id"],
                }
            )
        return rounds, iterations

    for index, plan in enumerate(plans):
        goal_ids = sorted(
            edge["from"]
            for edge in incoming[plan["id"]]
            if edge["type"] == "frames" and edge["from"] in nodes
        )
        action_ids = sorted(
            edge["to"]
            for edge in outgoing[plan["id"]]
            if edge["type"] in {"invokes", "implemented_by"} and edge["to"] in nodes
        )
        output_ids = sorted(
            edge["to"]
            for action_id in action_ids
            for edge in outgoing[action_id]
            if edge["type"] == "produces" and edge["to"] in nodes
        )
        claim_ids = sorted(
            edge["to"]
            for output_id in output_ids
            for edge in outgoing[output_id]
            if edge["type"] in {"supports", "refutes", "explains"} and edge["to"] in nodes
        )
        informed_ids = sorted(
            edge["from"]
            for edge in incoming[plan["id"]]
            if edge["type"] in {"informs", "derived_from"} and edge["from"] in nodes
        )
        round_id = f"aggregate:dialogue:{index + 1}"
        iteration_id = f"aggregate:execution:{index + 1}"
        rounds.append(
            {
                "id": round_id,
                "label": f"Display span {index + 1}: {plan['label']}",
                "index": index,
                "member_ids": goal_ids,
                "trigger_type": "unresolved_without_user_input_evidence",
                "explicit": False,
                "focus_member_id": goal_ids[0] if goal_ids else plan["id"],
            }
        )
        iteration_members = [plan["id"], *informed_ids, *action_ids, *output_ids, *claim_ids]
        iterations.append(
            {
                "id": iteration_id,
                "label": f"Execution span {index + 1}: {plan['label']}",
                "index": index,
                "round_id": round_id,
                "member_ids": list(dict.fromkeys(iteration_members)),
                "explicit": False,
                "focus_member_id": plan["id"],
            }
        )
    return rounds, iterations


def analyze_loops(graph: dict[str, Any]) -> dict[str, Any]:
    """Analyze explicit nested loops, with a conservative Plan-based fallback."""

    nodes = {node["id"]: node for node in graph["nodes"]}
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    contains: dict[str, list[str]] = defaultdict(list)
    for edge in graph["edges"]:
        incoming[edge["to"]].append(edge)
        outgoing[edge["from"]].append(edge)
        if edge["type"] == "contains":
            contains[edge["from"]].append(edge["to"])

    explicit_round_nodes = _ordered(
        [node for node in nodes.values() if node["type"] == "DialogueRound"]
    )
    explicit_iteration_nodes = _ordered(
        [node for node in nodes.values() if node["type"] == "ExecutionIteration"]
    )
    if explicit_round_nodes or explicit_iteration_nodes:
        rounds = []
        for index, node in enumerate(explicit_round_nodes):
            attrs = node.get("attrs", {})
            members = sorted(member for member in contains[node["id"]] if member in nodes)
            rounds.append(
                {
                    "id": node["id"],
                    "label": node["label"],
                    "index": attrs.get("index", index),
                    "member_ids": members,
                    "trigger_type": attrs.get("trigger_type", "unclassified"),
                    "exit_condition": attrs.get("exit_condition"),
                    "replan_reason": attrs.get("replan_reason"),
                    "accepted": attrs.get("accepted"),
                    "explicit": True,
                    "focus_member_id": next(
                        (member for member in members if nodes[member]["type"] == "UserFeedback"),
                        next((member for member in members if nodes[member]["type"] == "Goal"), node["id"]),
                    ),
                }
            )
        if not rounds:
            rounds.append(
                {
                    "id": "aggregate:dialogue:unresolved",
                    "label": "Unknown dialogue span",
                    "index": 0,
                    "member_ids": [],
                    "trigger_type": "unresolved_without_user_input_evidence",
                    "explicit": False,
                    "focus_member_id": explicit_iteration_nodes[0]["id"],
                }
            )
        iterations = []
        for index, node in enumerate(explicit_iteration_nodes):
            attrs = node.get("attrs", {})
            round_id = next(
                (
                    edge["from"]
                    for edge in incoming[node["id"]]
                    if edge["type"] == "contains"
                    and nodes.get(edge["from"], {}).get("type") == "DialogueRound"
                ),
                attrs.get("dialogue_round_id") or rounds[min(index, len(rounds) - 1)]["id"],
            )
            members = sorted(member for member in contains[node["id"]] if member in nodes)
            iterations.append(
                {
                    "id": node["id"],
                    "label": node["label"],
                    "index": attrs.get("index", index),
                    "round_id": round_id,
                    "member_ids": members,
                    "exit_condition": attrs.get("exit_condition"),
                    "replan_reason": attrs.get("replan_reason"),
                    "explicit": True,
                    "focus_member_id": next(
                        (member for member in members if nodes[member]["type"] == "Plan"),
                        node["id"],
                    ),
                }
            )
        if not iterations and explicit_round_nodes:
            _, fallback_iterations = _fallback_groups(nodes, graph["edges"])
            for index, item in enumerate(fallback_iterations):
                item["round_id"] = rounds[min(index, len(rounds) - 1)]["id"]
                iterations.append(item)
    else:
        rounds, iterations = _fallback_groups(nodes, graph["edges"])

    control_cycle_ids = _cycle_members(nodes, graph["edges"], CONTROL_TYPES)
    review_cycle_ids = _cycle_members(nodes, graph["edges"], REVIEW_TYPES)
    critical_nodes = []
    for node in _ordered(list(nodes.values())):
        reasons = _critical_reasons(
            node, incoming, outgoing, control_cycle_ids, review_cycle_ids
        )
        if reasons:
            critical_nodes.append({"id": node["id"], "reasons": reasons})

    retry_count = sum(edge["type"] == "retry_of" for edge in graph["edges"])
    dialogue_replans = sum(
        item.get("trigger_type") not in {"initial_request", "unclassified", None}
        and item.get("explicit") is True for item in rounds
    )
    execution_replans = sum(bool(item.get("replan_reason")) for item in iterations)
    first_observed = rounds[0].get("accepted") if rounds else None
    return {
        "protocol_version": PROTOCOL_VERSION,
        "source": "canonical-graph-only",
        "mode": (
            "explicit" if explicit_round_nodes and explicit_iteration_nodes
            else "partial-explicit" if explicit_round_nodes or explicit_iteration_nodes
            else "display-fallback"
        ),
        "dialogue_rounds": rounds,
        "execution_iterations": iterations,
        "critical_nodes": critical_nodes,
        "signals": {
            "dialogue_replan_count": dialogue_replans,
            "execution_replan_count": execution_replans,
            "retry_edge_count": retry_count,
            "first_attempt_success_observed": first_observed,
            "first_attempt_success_boundary": (
                "explicit accepted signal" if first_observed is not None else "unknown_without_explicit_acceptance"
            ),
            "revision_triggers": sorted(
                Counter(item.get("trigger_type", "unclassified") for item in rounds).items()
            ),
        },
    }


def build_loop_projection(
    graph: dict[str, Any], trace_model: dict[str, Any]
) -> dict[str, Any]:
    analysis = analyze_loops(graph)
    source_nodes = {node["id"]: node for node in graph["nodes"]}
    groups = [
        *(dict(item, loop_scope="dialogue") for item in analysis["dialogue_rounds"]),
        *(dict(item, loop_scope="execution") for item in analysis["execution_iterations"]),
    ]
    execution_member_ids = {
        node_id
        for group in groups
        if group["loop_scope"] == "execution"
        for node_id in group["member_ids"]
    }
    child_groups: dict[str, list[str]] = defaultdict(list)
    for item in analysis["execution_iterations"]:
        if item.get("round_id"):
            child_groups[item["round_id"]].append(item["id"])
    overview_nodes: list[dict[str, Any]] = []
    member_to_group: dict[str, str] = {}
    for group in groups:
        member_ids = [node_id for node_id in group["member_ids"] if node_id in source_nodes]
        if group["loop_scope"] == "dialogue":
            member_ids = [
                node_id
                for node_id in member_ids
                if node_id not in execution_member_ids
                and source_nodes[node_id]["type"] != "ExecutionIteration"
            ]
        if group["id"] in source_nodes:
            member_ids.append(group["id"])
        members = [source_nodes[node_id] for node_id in sorted(set(member_ids))]
        provenance_members = list(members)
        if group["id"] in source_nodes:
            provenance_members.append(source_nodes[group["id"]])
        critical_ids = {
            item["id"] for item in analysis["critical_nodes"]
        } & {node["id"] for node in members}
        type_counts = dict(sorted(Counter(node["type"] for node in members).items()))
        for member in members:
            # Inner execution ownership is intentionally more specific than its outer round.
            if group["loop_scope"] == "execution" or member["id"] not in member_to_group:
                member_to_group[member["id"]] = group["id"]
        if group["id"] in source_nodes:
            member_to_group[group["id"]] = group["id"]
        overview_nodes.append(
            {
                "id": f"overview:{group['id']}",
                "source_group_id": group["id"],
                "type": "Aggregate",
                "label": group["label"],
                "phase": "context" if group["loop_scope"] == "dialogue" else "execute",
                "status": "recorded",
                "rank": (
                    group["index"] if isinstance(group.get("index"), int) else len(overview_nodes)
                ),
                "level": "overview",
                "primary": True,
                "tool": None,
                "output": None,
                "event_ids": sorted({event_id for node in provenance_members for event_id in node.get("event_ids", [])}),
                "first_sequence": min(
                    (
                        node["first_sequence"]
                        for node in provenance_members
                        if isinstance(node.get("first_sequence"), int)
                    ),
                    default=None,
                ),
                "provenance": _union_provenance(provenance_members),
                "attrs": {
                    "derived": True,
                    "projection_only": True,
                    "container_node_id": group["id"] if group["id"] in source_nodes else None,
                    "parent_group_id": group.get("round_id"),
                    "child_group_ids": sorted(child_groups[group["id"]]),
                    "loop_scope": group["loop_scope"],
                    "member_ids": [node["id"] for node in members],
                    "member_count": len(members),
                    "member_type_counts": type_counts,
                    "critical_member_ids": sorted(critical_ids),
                    "internal_edge_ids": [],
                    "cycle_edge_ids": [],
                    "focus_member_id": group.get("focus_member_id"),
                    "trigger_type": group.get("trigger_type"),
                    "exit_condition": group.get("exit_condition"),
                    "replan_reason": group.get("replan_reason"),
                    "explicit": group["explicit"],
                },
            }
        )

    overview_ids = {node["source_group_id"]: node["id"] for node in overview_nodes}
    edge_buckets: dict[tuple[str, str, str, bool, str], dict[str, Any]] = {}
    internal_edge_ids: dict[str, list[str]] = defaultdict(list)
    cycle_edge_ids: dict[str, list[str]] = defaultdict(list)
    mapped_edge_ids: set[str] = set()
    cycle_member_ids = {
        item["id"]
        for item in analysis["critical_nodes"]
        if any(reason.endswith("cycle_member") for reason in item["reasons"])
    }

    def add_edge(
        source_group: str, target_group: str, source_edge: dict[str, Any], *, derived: bool = False
    ) -> None:
        if source_group == target_group:
            if not derived:
                mapped_edge_ids.add(source_edge["id"])
                internal_edge_ids[source_group].append(source_edge["id"])
                if source_edge["from"] in cycle_member_ids and source_edge["to"] in cycle_member_ids:
                    cycle_edge_ids[source_group].append(source_edge["id"])
            return
        if source_group not in overview_ids or target_group not in overview_ids:
            return
        if not derived:
            mapped_edge_ids.add(source_edge["id"])
        attrs_key = json.dumps(source_edge.get("attrs", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        key = (source_group, target_group, source_edge["type"], derived, attrs_key)
        bucket = edge_buckets.setdefault(
            key,
            {
                "from": overview_ids[source_group],
                "to": overview_ids[target_group],
                "type": source_edge["type"],
                "layout": derived,
                "attrs": {
                    "derived": derived,
                    "projection_only": True,
                    "original_edge_ids": [], "derived_edge_ids": [],
                    "endpoint_pairs": [], "relation_types": [],
                },
                "provenance": {"capture_modes": [], "source_refs": [], "run_ids": []},
            },
        )
        bucket["attrs"]["derived_edge_ids" if derived else "original_edge_ids"].append(source_edge["id"])
        if not derived:
            bucket["attrs"]["endpoint_pairs"].append(
                {
                    "edge_id": source_edge["id"],
                    "from": source_edge["from"],
                    "to": source_edge["to"],
                    "type": source_edge["type"],
                    "attrs": source_edge.get("attrs", {}),
                    "event_ids": list(source_edge.get("event_ids", [])),
                    "first_sequence": source_edge.get("first_sequence"),
                    "last_sequence": source_edge.get("last_sequence"),
                    "provenance": source_edge.get("provenance", {}),
                }
            )
        bucket["attrs"]["relation_types"].append(source_edge["type"])
        for field in ("capture_modes", "source_refs", "run_ids"):
            bucket["provenance"][field].extend(source_edge.get("provenance", {}).get(field, []))

    for edge in graph["edges"]:
        source_group = member_to_group.get(edge["from"])
        target_group = member_to_group.get(edge["to"])
        if source_group and target_group:
            add_edge(source_group, target_group, edge)

    ordered_rounds = analysis["dialogue_rounds"]
    iterations_by_round = {item.get("round_id"): item for item in analysis["execution_iterations"]}
    for index, round_item in enumerate(ordered_rounds):
        iteration = iterations_by_round.get(round_item["id"])
        if iteration:
            add_edge(
                round_item["id"],
                iteration["id"],
                {"id": f"derived:round-iteration:{index}", "type": "invokes", "provenance": {"capture_modes": ["synthetic"], "source_refs": ["derived://loop-projection"], "run_ids": []}},
                derived=True,
            )
            if index + 1 < len(ordered_rounds):
                add_edge(
                    iteration["id"],
                    ordered_rounds[index + 1]["id"],
                    {"id": f"derived:iteration-round:{index}", "type": "informs", "provenance": {"capture_modes": ["synthetic"], "source_refs": ["derived://loop-projection"], "run_ids": []}},
                    derived=True,
                )

    overview_edges = []
    for index, key in enumerate(sorted(edge_buckets), start=1):
        edge = edge_buckets[key]
        edge["id"] = f"overview-edge:{index:03d}"
        edge["attrs"]["original_edge_ids"] = sorted(set(edge["attrs"]["original_edge_ids"]))
        edge["attrs"]["derived_edge_ids"] = sorted(set(edge["attrs"]["derived_edge_ids"]))
        edge["attrs"]["relation_types"] = sorted(set(edge["attrs"]["relation_types"]))
        edge["attrs"]["endpoint_pairs"] = sorted(
            edge["attrs"]["endpoint_pairs"], key=lambda item: item["edge_id"]
        )
        edge["attrs"]["original_edge_count"] = len(edge["attrs"]["original_edge_ids"])
        for field in ("capture_modes", "source_refs", "run_ids"):
            edge["provenance"][field] = sorted(set(edge["provenance"][field]))
        overview_edges.append(edge)

    overview_by_group = {node["source_group_id"]: node for node in overview_nodes}
    for group_id, edge_ids in internal_edge_ids.items():
        if group_id in overview_by_group:
            overview_by_group[group_id]["attrs"]["internal_edge_ids"] = sorted(set(edge_ids))
            overview_by_group[group_id]["attrs"]["cycle_edge_ids"] = sorted(
                set(cycle_edge_ids[group_id])
            )

    original_count = len(trace_model["nodes"])
    overview_count = len(overview_nodes)
    unmapped_node_ids = sorted(set(source_nodes) - set(member_to_group))
    unmapped_edge_ids = sorted(
        edge["id"] for edge in graph["edges"] if edge["id"] not in mapped_edge_ids
    )
    return {
        **analysis,
        "nodes": overview_nodes,
        "edges": overview_edges,
        "unmapped_node_ids": unmapped_node_ids,
        "unmapped_edge_ids": unmapped_edge_ids,
        "source_node_ids": sorted(source_nodes),
        "source_edge_ids": sorted(edge["id"] for edge in graph["edges"]),
        "metrics": {
            "original_node_count": original_count,
            "overview_node_count": overview_count,
            "compression_ratio": round(overview_count / original_count, 4) if original_count else 0,
            "dialogue_round_count": len(analysis["dialogue_rounds"]),
            "execution_iteration_count": len(analysis["execution_iterations"]),
        },
        "principles": {
            "canonical_graph_mutated": False,
            "all_members_traceable": all(
                member_id in source_nodes
                for node in overview_nodes
                for member_id in node["attrs"]["member_ids"]
            ),
            "all_source_nodes_accounted": (
                set(source_nodes) == set(member_to_group) | set(unmapped_node_ids)
            ),
            "unmapped_nodes_are_explicit": True,
            "raw_graph_embedded_in_parent_trace_model": True,
            "cross_group_edges_preserve_original_ids": True,
            "inner_group_ownership_precedes_outer_group_ownership": True,
        },
    }
