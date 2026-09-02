from __future__ import annotations

from typing import Any


PROTOCOL_VERSION = "sequence-projection-0.1"

PARTICIPANTS = (
    {"id": "user", "label": "User", "kind": "actor"},
    {"id": "agent", "label": "Agent", "kind": "participant"},
    {"id": "tool", "label": "Tool / Runtime", "kind": "participant"},
    {"id": "world", "label": "Evidence / World", "kind": "database"},
    {"id": "evaluator", "label": "Evaluator", "kind": "participant"},
)

STRUCTURAL_TYPES = {
    "Case",
    "Run",
    "DialogueRound",
    "ExecutionIteration",
    "Aggregate",
}

USER_INPUT_TYPES = {"Input", "UserFeedback", "Constraint", "ScopeBoundary"}
AGENT_INTERNAL_TYPES = {
    "Goal",
    "Plan",
    "Task",
    "Step",
    "Decision",
    "ReasoningSummary",
    "Uncertainty",
}
AGENT_ACTION_TYPES = {"Action", "ToolCall"}
WORLD_RESULT_TYPES = {
    "ToolOutput",
    "Artifact",
    "Observation",
    "Evidence",
    "EnvironmentSnapshot",
    "ExternalIssue",
}
VALIDATION_TYPES = {
    "Verification",
    "VerificationReceipt",
    "Check",
    "AcceptanceCriterion",
    "Evaluation",
    "EvalCase",
}
AGENT_RESPONSE_TYPES = {
    "AgentResponse",
    "Claim",
    "RootCause",
    "Outcome",
    "Pattern",
    "Runbook",
    "SkillVersion",
}

TERMINAL_VALIDATION_STATES = {
    "accepted",
    "completed",
    "confirmed",
    "failed",
    "passed",
    "rejected",
    "verified",
}

# These relations impose a useful before/after constraint for a sequence
# projection.  They do not turn the resulting total order into proof that every
# adjacent pair is causally related; unrelated ready nodes still use source
# sequence as a deterministic tie-breaker.
TEMPORAL_FORWARD_RELATIONS = {
    "precedes",
    "frames",
    "informs",
    "invokes",
    "produces",
    "supports",
    "refutes",
    "explains",
    "implemented_by",
    "modifies",
    "satisfies",
    "targets",
    "tested_by",
    "verified_by",
    "approved_by",
}
TEMPORAL_REVERSE_RELATIONS = {
    "checks",
    "supersedes",
    "derived_from",
    "uses",
    "references",
}


def _route(node: dict[str, Any]) -> tuple[str, str]:
    node_type = node["type"]
    if node_type in USER_INPUT_TYPES:
        return "user", "agent"
    if node_type in AGENT_INTERNAL_TYPES:
        return "agent", "agent"
    if node_type in AGENT_ACTION_TYPES:
        return "agent", "tool"
    if node_type in WORLD_RESULT_TYPES:
        return ("tool", "agent") if node_type == "ToolOutput" else ("world", "agent")
    if node_type in VALIDATION_TYPES:
        if str(node.get("status", "")).lower() in TERMINAL_VALIDATION_STATES:
            return "evaluator", "agent"
        return "agent", "evaluator"
    if node_type in AGENT_RESPONSE_TYPES:
        return "agent", "user"
    return "agent", "agent"


def _linearize_step_ids(
    step_ids: list[str],
    steps_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[str], int, list[str]]:
    """Return a deterministic linear extension of explicit temporal relations."""

    node_to_step = {steps_by_id[step_id]["node_id"]: step_id for step_id in step_ids}
    successors = {step_id: set() for step_id in step_ids}
    indegree = {step_id: 0 for step_id in step_ids}
    relation_count = 0
    for edge in edges:
        source = node_to_step.get(edge["from"])
        target = node_to_step.get(edge["to"])
        if not source or not target or source == target:
            continue
        if edge["type"] in TEMPORAL_FORWARD_RELATIONS:
            before, after = source, target
        elif edge["type"] in TEMPORAL_REVERSE_RELATIONS:
            before, after = target, source
        else:
            continue
        if after in successors[before]:
            continue
        successors[before].add(after)
        indegree[after] += 1
        relation_count += 1

    stable_key = lambda step_id: (
        steps_by_id[step_id]["sequence"],
        steps_by_id[step_id]["node_id"],
    )
    ready = sorted((step_id for step_id, degree in indegree.items() if degree == 0), key=stable_key)
    ordered: list[str] = []
    while ready:
        step_id = ready.pop(0)
        ordered.append(step_id)
        for target in sorted(successors[step_id], key=stable_key):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort(key=stable_key)

    cycle_step_ids = sorted(
        (step_id for step_id, degree in indegree.items() if degree > 0),
        key=stable_key,
    )
    ordered.extend(cycle_step_ids)
    return ordered, relation_count, [steps_by_id[step_id]["node_id"] for step_id in cycle_step_ids]


def build_sequence_projection(
    trace_model: dict[str, Any], overview: dict[str, Any]
) -> dict[str, Any]:
    """Build a chronological, single-execution projection from canonical nodes.

    The sequence projection intentionally uses ``first_sequence`` only for display
    order. Causality stays in the canonical typed edges and remains available in
    the workflow and evidence projections.
    """

    steps: list[dict[str, Any]] = []
    for node in trace_model["nodes"]:
        if node["type"] in STRUCTURAL_TYPES or node.get("first_sequence") is None:
            continue
        source_modes = sorted(
            {
                item["capture_mode"]
                for item in trace_model["trace"]
                if item["event_id"] in node.get("event_ids", [])
            }
        )
        source, target = _route(node)
        steps.append(
            {
                "id": f"sequence:{node['id']}",
                "node_id": node["id"],
                "sequence": node["first_sequence"],
                "from": source,
                "to": target,
                "type": node["type"],
                "phase": node["phase"],
                "status": node["status"],
                "label": node["label"],
                "tool": node.get("tool"),
                "output": node.get("output"),
                "capture_modes": source_modes,
                "event_ids": list(node.get("event_ids", [])),
            }
        )
    steps.sort(key=lambda item: (item["sequence"], item["node_id"]))

    steps_by_id = {step["id"]: step for step in steps}
    scopes: list[dict[str, Any]] = []
    assigned_step_ids: set[str] = set()
    for aggregate in overview.get("nodes", []):
        attrs = aggregate.get("attrs", {})
        if attrs.get("loop_scope") != "execution":
            continue
        member_ids = set(attrs.get("member_ids", []))
        raw_step_ids = [step["id"] for step in steps if step["node_id"] in member_ids]
        step_ids, relation_count, cycle_node_ids = _linearize_step_ids(
            raw_step_ids, steps_by_id, trace_model.get("edges", [])
        )
        if not step_ids:
            continue
        assigned_step_ids.update(step_ids)
        scopes.append(
            {
                "id": aggregate["id"],
                "label": aggregate["label"],
                "source": "execution-aggregate",
                "focus_member_id": attrs.get("focus_member_id"),
                "member_ids": sorted(member_ids),
                "step_ids": step_ids,
                "order_mode": "typed-partial-order-linearization",
                "ordering_relation_count": relation_count,
                "ordering_cycle_node_ids": cycle_node_ids,
            }
        )

    unscoped = [step["id"] for step in steps if step["id"] not in assigned_step_ids]
    if unscoped:
        scopes.append(
            {
                "id": "sequence:unscoped",
                "label": "Unscoped execution span",
                "source": "display-fallback",
                "focus_member_id": None,
                "member_ids": [],
                "step_ids": unscoped,
                "order_mode": "source-record-order",
                "ordering_relation_count": 0,
                "ordering_cycle_node_ids": [],
            }
        )
    if not scopes:
        scopes.append(
            {
                "id": "sequence:all",
                "label": "Execution span",
                "source": "display-fallback",
                "focus_member_id": steps[0]["node_id"] if steps else None,
                "member_ids": [step["node_id"] for step in steps],
                "step_ids": [step["id"] for step in steps],
                "order_mode": "source-record-order",
                "ordering_relation_count": 0,
                "ordering_cycle_node_ids": [],
            }
        )

    step_sequence = {step["id"]: step["sequence"] for step in steps}
    scopes.sort(
        key=lambda scope: (
            0 if scope["source"] == "execution-aggregate" else 1,
            min(
                (step_sequence[step_id] for step_id in scope["step_ids"]),
                default=float("inf"),
            ),
        )
    )

    return {
        "protocol_version": PROTOCOL_VERSION,
        "participants": [dict(item) for item in PARTICIPANTS],
        "steps": steps,
        "scopes": scopes,
        "metrics": {
            "participant_count": len(PARTICIPANTS),
            "step_count": len(steps),
            "scope_count": len(scopes),
        },
        "principles": {
            "order_source": "typed temporal relations with first_sequence tie-breaker",
            "scope_source": "execution aggregates when available",
            "sequence_is_causality": False,
            "linearized_adjacency_is_causality": False,
            "source_sequence_preserved": True,
            "hidden_chain_of_thought_recovered": False,
            "source_nodes_traceable": True,
        },
    }
