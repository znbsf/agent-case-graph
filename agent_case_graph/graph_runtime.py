"""Derived, graph-native operational advice for Agent Case Graph.

This module is deliberately a control-plane consumer of the canonical graph.
It never invokes a tool, changes external state, or turns a graph inference into
source telemetry.  Recommendations are derived from explicit nodes/edges and
runtime gates; callers that persist a recommendation must record it as a
``Decision`` with ``data_origin=derived``.
"""

from __future__ import annotations

from collections import defaultdict
import heapq
from typing import Any, Iterable

from .model import ACGError
from .runtime import (
    ACTIVE_STATUSES,
    EXECUTABLE_NODE_TYPES,
    FAILED_STATUSES,
    SUCCESS_STATUSES,
    build_runtime_snapshot,
)


GRAPH_RUNTIME_PROTOCOL_VERSION = "graph-runtime-0.1"
RECOMMENDATION_RECORD_KIND = "graph_runtime_recommendation"

ACTION_RECOMMENDATION_TYPES = frozenset({"Action", "ToolCall"})
CLAIM_NODE_TYPES = frozenset({"Claim", "RootCause"})
EVIDENCE_NODE_TYPES = frozenset(
    {
        "Artifact",
        "EnvironmentSnapshot",
        "Observation",
        "ToolOutput",
        "Verification",
        "VerificationReceipt",
        "AcceptanceCriterion",
    }
)

_EVIDENCE_PENDING_STATUSES = frozenset(
    {
        "pending",
        "planned",
        "expected",
        "missing",
        "unavailable",
        "partial",
        *ACTIVE_STATUSES,
        *FAILED_STATUSES,
    }
)


def _status(node: dict[str, Any]) -> str:
    value = node.get("attrs", {}).get("status", "recorded")
    return str(value).strip().lower() or "recorded"


def _sequence(node: dict[str, Any]) -> int:
    value = node.get("first_sequence")
    return value if isinstance(value, int) and not isinstance(value, bool) else 2**63 - 1


def _ordered(nodes: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(nodes, key=lambda node: (_sequence(node), node["id"]))


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return sorted({item.strip() for item in value if isinstance(item, str) and item.strip()})
    return []


def _capture_modes(item: dict[str, Any]) -> list[str]:
    provenance = item.get("provenance", {})
    modes = provenance.get("capture_modes", []) if isinstance(provenance, dict) else []
    if not modes:
        capture_mode = item.get("attrs", {}).get("capture_mode")
        modes = [capture_mode] if isinstance(capture_mode, str) else []
    return sorted({str(mode) for mode in modes if isinstance(mode, str) and mode})


def _is_derived(item: dict[str, Any]) -> bool:
    attrs = item.get("attrs", {})
    return (
        isinstance(attrs, dict)
        and (attrs.get("data_origin") == "derived" or attrs.get("source_derived") is True)
    )


def _provenance_summary(item: dict[str, Any]) -> dict[str, Any]:
    provenance = item.get("provenance", {})
    modes = _capture_modes(item)
    refs = provenance.get("source_refs", []) if isinstance(provenance, dict) else []
    event_ids = item.get("event_ids", [])
    recorded = isinstance(event_ids, list) and bool(event_ids)
    content_origin = "derived" if _is_derived(item) else "recorded" if recorded else "unknown"
    if modes == ["live"]:
        actualness = "live-recorded" if recorded else "live-declared"
    elif modes == ["reconstructed"]:
        actualness = "reconstructed-recorded" if recorded else "reconstructed-declared"
    elif modes == ["synthetic"]:
        actualness = "synthetic-recorded" if recorded else "synthetic-declared"
    elif modes:
        actualness = "mixed-recorded" if recorded else "mixed-declared"
    else:
        actualness = "unknown"
    return {
        "recorded_in_ledger": recorded,
        "content_origin": content_origin,
        "capture_modes": modes,
        "source_refs": sorted({str(ref) for ref in refs if isinstance(ref, str)}),
        "actualness": actualness,
    }


def _node_summary(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node["id"],
        "type": node["type"],
        "label": node.get("label", node["id"]),
        "status": _status(node),
        "first_sequence": node.get("first_sequence"),
        "provenance": _provenance_summary(node),
    }


def _descendants(graph: dict[str, Any], scope_id: str) -> set[str]:
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in graph.get("edges", []):
        if edge.get("type") == "contains":
            outgoing[str(edge.get("from"))].append(str(edge.get("to")))
    seen: set[str] = set()
    frontier = [scope_id]
    while frontier:
        current = frontier.pop()
        for child in sorted(outgoing.get(current, []), reverse=True):
            if child not in seen:
                seen.add(child)
                frontier.append(child)
    return seen


def _run_owner_index(graph: dict[str, Any]) -> dict[str, set[str]]:
    """Map each node to all Run scopes that explicitly own it."""

    owners: dict[str, set[str]] = defaultdict(set)
    for run in _run_nodes(graph):
        run_id = run["id"]
        for node_id in _descendants(graph, run_id):
            owners[node_id].add(run_id)
    return owners


def _declared_run_ids(item: dict[str, Any]) -> set[str]:
    provenance = item.get("provenance", {})
    values = provenance.get("run_ids", []) if isinstance(provenance, dict) else []
    return {value for value in values if isinstance(value, str) and value}


def _node_run_owners(node: dict[str, Any], owner_index: dict[str, set[str]]) -> set[str]:
    return set(owner_index.get(node["id"], set())) | _declared_run_ids(node)


def _edge_run_owners(
    edge: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    owner_index: dict[str, set[str]],
) -> set[str]:
    """Resolve an edge scope without allowing a global relation to bridge Runs."""

    declared = _declared_run_ids(edge)
    source = nodes.get(edge.get("from"))
    target = nodes.get(edge.get("to"))
    source_owners = _node_run_owners(source, owner_index) if source else set()
    target_owners = _node_run_owners(target, owner_index) if target else set()
    # A relation with no explicit event Run can inherit a scope only when both
    # endpoints already belong to the same unique Run.  A global evidence node
    # therefore cannot silently become evidence for a Run-local Claim.
    inferred = source_owners & target_owners
    return declared | inferred


def _matches_scope(owners: set[str], run_id: str | None) -> bool:
    return not owners if run_id is None else owners == {run_id}


def _run_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return _ordered(node for node in graph.get("nodes", []) if node.get("type") == "Run")


def _resolve_runtime_run_id(graph: dict[str, Any], run_id: str | None) -> str | None:
    nodes = {node["id"]: node for node in graph.get("nodes", [])}
    if run_id is not None:
        if nodes.get(run_id, {}).get("type") != "Run":
            raise ACGError(f"runtime Run does not exist: {run_id}")
        return run_id
    snapshot = build_runtime_snapshot(graph)
    selected_run_id = snapshot.get("run_id")
    return selected_run_id if isinstance(selected_run_id, str) and selected_run_id else None


def resolve_claim_run_id(graph: dict[str, Any], claim_id: str) -> str | None:
    """Return the Claim's unique explicit Run owner, or None for a global Claim."""

    nodes = {node["id"]: node for node in graph.get("nodes", [])}
    claim = nodes.get(claim_id)
    if claim is None or claim.get("type") not in CLAIM_NODE_TYPES:
        raise ACGError(f"claim gate requires a Claim or RootCause node: {claim_id}")
    owners = _node_run_owners(claim, _run_owner_index(graph))
    if len(owners) <= 1:
        return next(iter(owners), None)
    raise ACGError(
        f"claim belongs to multiple Run scopes and needs an unambiguous per-Run Claim: {claim_id}"
    )


def _evidence_state(node: dict[str, Any]) -> tuple[bool, str | None]:
    if node.get("type") not in EVIDENCE_NODE_TYPES:
        return False, "unsupported_evidence_node_type"
    if _is_derived(node):
        return False, "derived_evidence_not_confirmable"
    status = _status(node)
    if status in _EVIDENCE_PENDING_STATUSES:
        return False, "evidence_not_complete"
    return True, None


def _requirement_count(attrs: dict[str, Any]) -> tuple[int, str | None]:
    value = attrs.get("minimum_support_count", 1)
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 1, "invalid_minimum_support_count"
    # A confirmed claim always needs at least one explicit evidence relation.
    return max(1, count), None


def _relation_summary(edge: dict[str, Any]) -> dict[str, Any]:
    derived = edge["type"] == "derived_from" or _is_derived(edge)
    return {
        "edge_id": edge["id"],
        "type": edge["type"],
        "from": edge["from"],
        "to": edge["to"],
        "relation_origin": "declared_derived_relation"
        if derived
        else "declared_canonical_relation",
        "provenance": _provenance_summary(edge),
    }


def build_claim_gate(
    graph: dict[str, Any], claim_id: str, *, run_id: str | None = None
) -> dict[str, Any]:
    """Return a deterministic gate before a Claim/RootCause may be confirmed.

    The result is derived analysis.  Source nodes and authored relations remain
    individually traceable so a caller cannot mistake the gate for native tool
    telemetry.
    """

    nodes = {node["id"]: node for node in graph.get("nodes", [])}
    claim = nodes.get(claim_id)
    if claim is None or claim.get("type") not in CLAIM_NODE_TYPES:
        raise ACGError(f"claim gate requires a Claim or RootCause node: {claim_id}")
    selected_run_id = run_id if run_id is not None else resolve_claim_run_id(graph, claim_id)
    if selected_run_id is not None and nodes.get(selected_run_id, {}).get("type") != "Run":
        raise ACGError(f"runtime Run does not exist: {selected_run_id}")

    owner_index = _run_owner_index(graph)
    claim_owners = _node_run_owners(claim, owner_index)
    if not _matches_scope(claim_owners, selected_run_id):
        requested_scope = selected_run_id or "global"
        actual_scopes = sorted(claim_owners) or ["global"]
        raise ACGError(
            f"claim scope does not match requested Run {requested_scope}: {claim_id} belongs to {actual_scopes}"
        )

    incoming = [
        edge
        for edge in graph.get("edges", [])
        if edge.get("to") == claim_id and edge.get("type") in {"supports", "refutes"}
    ]
    supports = [edge for edge in incoming if edge["type"] == "supports"]
    refutes = [edge for edge in incoming if edge["type"] == "refutes"]
    usable_supports: list[dict[str, Any]] = []
    unusable_supports: list[dict[str, Any]] = []
    usable_refutes: list[dict[str, Any]] = []
    excluded_supports: list[dict[str, Any]] = []
    excluded_refutes: list[dict[str, Any]] = []
    unusable_refutes: list[dict[str, Any]] = []

    for edge in sorted(supports, key=lambda item: (item.get("first_sequence", 2**63 - 1), item["id"])):
        evidence = nodes.get(edge["from"])
        if evidence is None:
            unusable_supports.append({
                "node_id": edge["from"],
                "reason": "evidence_node_missing",
                "relation": _relation_summary(edge),
            })
            continue
        row = {"evidence": _node_summary(evidence), "relation": _relation_summary(edge)}
        evidence_owners = _node_run_owners(evidence, owner_index)
        relation_owners = _edge_run_owners(edge, nodes, owner_index)
        if not (
            _matches_scope(evidence_owners, selected_run_id)
            and _matches_scope(relation_owners, selected_run_id)
        ):
            excluded_supports.append(
                {
                    **row,
                    "reason": "support_outside_selected_run_scope",
                    "evidence_run_ids": sorted(evidence_owners),
                    "relation_run_ids": sorted(relation_owners),
                }
            )
            continue
        if _is_derived(edge):
            unusable_supports.append(
                {**row, "reason": "derived_support_relation_not_confirmable"}
            )
            continue
        usable, reason = _evidence_state(evidence)
        if usable:
            usable_supports.append(row)
        else:
            unusable_supports.append({**row, "reason": reason})

    for edge in sorted(refutes, key=lambda item: (item.get("first_sequence", 2**63 - 1), item["id"])):
        evidence = nodes.get(edge["from"])
        if evidence is None:
            continue
        row = {"evidence": _node_summary(evidence), "relation": _relation_summary(edge)}
        evidence_owners = _node_run_owners(evidence, owner_index)
        relation_owners = _edge_run_owners(edge, nodes, owner_index)
        if not (
            _matches_scope(evidence_owners, selected_run_id)
            and _matches_scope(relation_owners, selected_run_id)
        ):
            excluded_refutes.append(
                {
                    **row,
                    "reason": "refute_outside_selected_run_scope",
                    "evidence_run_ids": sorted(evidence_owners),
                    "relation_run_ids": sorted(relation_owners),
                }
            )
            continue
        if _is_derived(edge):
            unusable_refutes.append(
                {**row, "reason": "derived_refute_relation_not_confirmable"}
            )
            continue
        usable, _ = _evidence_state(evidence)
        if usable:
            usable_refutes.append(row)
        else:
            unusable_refutes.append({**row, "reason": "refuting_evidence_not_complete_or_derived"})

    attrs = claim.get("attrs", {})
    minimum_support_count, count_error = _requirement_count(attrs)
    required_ids = _string_list(attrs.get("required_evidence_ids"))
    required_types = _string_list(attrs.get("required_evidence_types"))
    required_modes = _string_list(attrs.get("required_capture_modes"))
    usable_ids = {item["evidence"]["id"] for item in usable_supports}
    usable_types = {item["evidence"]["type"] for item in usable_supports}
    usable_modes = {
        mode
        for item in usable_supports
        for mode in item["evidence"]["provenance"]["capture_modes"]
    }
    missing: list[dict[str, Any]] = []
    if count_error:
        missing.append({"code": count_error, "claim_id": claim_id})
    if len(usable_supports) < minimum_support_count:
        missing.append(
            {
                "code": "insufficient_support_count",
                "claim_id": claim_id,
                "required": minimum_support_count,
                "available": len(usable_supports),
            }
        )
    for support in unusable_supports:
        missing.append(
            {
                "code": support["reason"],
                "claim_id": claim_id,
                "evidence_id": support.get("evidence", {}).get("id", support.get("node_id")),
                "edge_id": support["relation"]["edge_id"],
            }
        )
    for evidence_id in required_ids:
        if evidence_id not in usable_ids:
            missing.append(
                {
                    "code": "required_evidence_missing_or_incomplete",
                    "claim_id": claim_id,
                    "evidence_id": evidence_id,
                }
            )
    for evidence_type in required_types:
        if evidence_type not in usable_types:
            missing.append(
                {
                    "code": "required_evidence_type_missing",
                    "claim_id": claim_id,
                    "evidence_type": evidence_type,
                }
            )
    for capture_mode in required_modes:
        if capture_mode not in usable_modes:
            missing.append(
                {
                    "code": "required_capture_mode_missing",
                    "claim_id": claim_id,
                    "capture_mode": capture_mode,
                }
            )
    if usable_refutes:
        missing.append(
            {
                "code": "refuting_evidence_present",
                "claim_id": claim_id,
                "evidence_ids": [item["evidence"]["id"] for item in usable_refutes],
            }
        )

    source_node_ids = sorted(
        {claim_id}
        | {item["evidence"]["id"] for item in usable_supports}
        | {
            item.get("evidence", {}).get("id", item.get("node_id", ""))
            for item in unusable_supports
        }
        | {item["evidence"]["id"] for item in excluded_supports}
        | {item["evidence"]["id"] for item in usable_refutes}
        | {item["evidence"]["id"] for item in unusable_refutes}
        | {item["evidence"]["id"] for item in excluded_refutes}
    )
    source_node_ids = [node_id for node_id in source_node_ids if node_id]
    source_edge_ids = sorted(edge["id"] for edge in incoming)
    support_modes = sorted(usable_modes)
    support_actualness = _provenance_actualness(support_modes, usable_supports)
    return {
        "protocol_version": GRAPH_RUNTIME_PROTOCOL_VERSION,
        "kind": "claim_gate",
        "run_id": selected_run_id,
        "claim": _node_summary(claim),
        "status": "open" if not missing else "blocked",
        "can_confirm": not missing,
        "requirements": {
            "minimum_support_count": minimum_support_count,
            "required_evidence_ids": required_ids,
            "required_evidence_types": required_types,
            "required_capture_modes": required_modes,
        },
        "supporting_evidence": usable_supports,
        "incomplete_or_invalid_supports": unusable_supports,
        "excluded_supports": excluded_supports,
        "refuting_evidence": usable_refutes,
        "incomplete_or_invalid_refutes": unusable_refutes,
        "excluded_refutes": excluded_refutes,
        "missing_evidence": missing,
        "evidence_actualness": support_actualness,
        "derivation": {
            "data_origin": "derived",
            "not_native_telemetry": True,
            "source": "canonical_graph_explicit_supports_refutes",
            "source_node_ids": source_node_ids,
            "source_edge_ids": source_edge_ids,
        },
    }


def _provenance_actualness(modes: list[str], rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "no_usable_evidence"
    if modes == ["live"]:
        return "live-recorded-evidence"
    if modes == ["reconstructed"]:
        return "reconstructed-evidence"
    if modes == ["synthetic"]:
        return "synthetic-evidence"
    if modes:
        return "mixed-evidence"
    return "evidence-provenance-unknown"


def _claims_in_scope(graph: dict[str, Any], run_id: str | None) -> list[dict[str, Any]]:
    owner_index = _run_owner_index(graph)
    return _ordered(
        node
        for node in graph.get("nodes", [])
        if node.get("type") in CLAIM_NODE_TYPES
        and _matches_scope(_node_run_owners(node, owner_index), run_id)
    )


def _addressed_claim_ids(
    graph: dict[str, Any], node_id: str, claim_ids: set[str], *, run_id: str | None
) -> list[str]:
    nodes = {node["id"]: node for node in graph.get("nodes", [])}
    owner_index = _run_owner_index(graph)
    action = nodes.get(node_id)
    if action is None or not _matches_scope(_node_run_owners(action, owner_index), run_id):
        return []
    edges = graph.get("edges", [])
    evidence_ids = {
        edge["to"]
        for edge in edges
        if edge.get("from") == node_id and edge.get("type") == "produces"
        and edge.get("to") in nodes
        and _matches_scope(_edge_run_owners(edge, nodes, owner_index), run_id)
        and _matches_scope(_node_run_owners(nodes[edge["to"]], owner_index), run_id)
    }
    result = {
        edge["to"]
        for edge in edges
        if edge.get("from") in evidence_ids
        and edge.get("to") in claim_ids
        and edge.get("type") in {"supports", "refutes"}
        and _matches_scope(_edge_run_owners(edge, nodes, owner_index), run_id)
        and _matches_scope(_node_run_owners(nodes[edge["to"]], owner_index), run_id)
    }
    return sorted(result)


def _reuse_keys(node: dict[str, Any]) -> list[str]:
    attrs = node.get("attrs", {})
    return _string_list(attrs.get("reuse_keys") or attrs.get("reuse_key"))


def _topological_node_order(
    graph: dict[str, Any], node_ids: set[str]
) -> tuple[list[str], list[str]]:
    nodes = {node["id"]: node for node in graph.get("nodes", [])}
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    for edge in graph.get("edges", []):
        source, target = edge.get("from"), edge.get("to")
        if (
            edge.get("type") == "precedes"
            and source in node_ids
            and target in node_ids
            and target not in adjacency[source]
        ):
            adjacency[source].add(target)
            indegree[target] += 1

    def key(node_id: str) -> tuple[int, str]:
        return _sequence(nodes[node_id]), node_id

    ready: list[tuple[tuple[int, str], str]] = []
    for node_id, degree in indegree.items():
        if degree == 0:
            heapq.heappush(ready, (key(node_id), node_id))
    ordered: list[str] = []
    while ready:
        _, node_id = heapq.heappop(ready)
        ordered.append(node_id)
        for target in sorted(adjacency[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, (key(target), target))
    if len(ordered) != len(node_ids):
        return [], sorted(node_ids - set(ordered), key=key)
    return ordered, []


def _run_success_evidence(
    graph: dict[str, Any], run_id: str, owner_index: dict[str, set[str]]
) -> dict[str, Any]:
    """Return only non-derived receipts that prove this one historical Run."""

    nodes = {node["id"]: node for node in graph.get("nodes", [])}
    root = nodes.get(graph.get("root_id", ""))
    if root is None or root.get("type") != "Case":
        return {"status": "not_proven", "reason": "case_root_missing"}
    attrs = root.get("attrs", {})
    closed = attrs.get("current_state") in {"close", "promote"} or _status(root) in {
        "closed",
        "completed",
        "resolved",
    }
    receipts = []
    for edge in graph.get("edges", []):
        receipt = nodes.get(edge.get("to"))
        if not (
            edge.get("type") == "verified_by"
            and edge.get("from") == root["id"]
            and receipt is not None
            and receipt.get("type") == "VerificationReceipt"
            and not _is_derived(edge)
            and not _is_derived(receipt)
        ):
            continue
        receipt_owners = _node_run_owners(receipt, owner_index)
        relation_owners = _edge_run_owners(edge, nodes, owner_index)
        if _matches_scope(receipt_owners, run_id) and (
            not relation_owners or relation_owners == {run_id}
        ):
            receipts.append(edge)
    if closed and receipts:
        return {
            "status": "verified_success",
            "case_id": root["id"],
            "run_id": run_id,
            "receipt_edge_ids": sorted(edge["id"] for edge in receipts),
            "receipt_node_ids": sorted(edge["to"] for edge in receipts),
        }
    all_receipt_edges = [
        edge
        for edge in graph.get("edges", [])
        if edge.get("type") == "verified_by"
        and edge.get("from") == root["id"]
        and nodes.get(edge.get("to"), {}).get("type") == "VerificationReceipt"
    ]
    return {
        "status": "not_proven",
        "case_id": root["id"],
        "run_id": run_id,
        "reason": "case_close_and_same_run_non_derived_verification_receipt_required",
        "closed_or_completed_recorded": bool(closed),
        "receipt_edge_ids": sorted(edge["id"] for edge in all_receipt_edges),
    }


def find_reusable_paths(
    graph: dict[str, Any],
    *,
    run_id: str | None,
    history_graphs: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find explicitly keyed historical subgraphs; never match labels heuristically."""

    owner_index = _run_owner_index(graph)
    current_nodes = {
        node["id"]: node
        for node in graph.get("nodes", [])
        if node.get("type") in ACTION_RECOMMENDATION_TYPES
        and _matches_scope(_node_run_owners(node, owner_index), run_id)
    }
    current_by_key: dict[str, set[str]] = defaultdict(set)
    for node in current_nodes.values():
        for key in _reuse_keys(node):
            current_by_key[key].add(node["id"])
    if not current_by_key:
        return []

    matches: list[dict[str, Any]] = []
    for history in history_graphs:
        history_nodes = {node["id"]: node for node in history.get("nodes", [])}
        history_owner_index = _run_owner_index(history)
        for history_run in _run_nodes(history):
            success = _run_success_evidence(
                history, history_run["id"], history_owner_index
            )
            actions = [
                node
                for node in history_nodes.values()
                if node.get("type") in ACTION_RECOMMENDATION_TYPES
                and _matches_scope(
                    _node_run_owners(node, history_owner_index), history_run["id"]
                )
            ]
            for reuse_key in sorted(current_by_key):
                matched_actions = [node for node in actions if reuse_key in _reuse_keys(node)]
                if not matched_actions:
                    continue
                action_ids = {node["id"] for node in matched_actions}
                path_ids, cycle_ids = _topological_node_order(history, action_ids)
                subgraph_ids = set(action_ids)
                for edge in history.get("edges", []):
                    if edge.get("from") in action_ids and edge.get("type") == "produces":
                        subgraph_ids.add(edge["to"])
                    if edge.get("from") in subgraph_ids and edge.get("type") in {"supports", "refutes"}:
                        subgraph_ids.add(edge["to"])
                edge_ids = sorted(
                    edge["id"]
                    for edge in history.get("edges", [])
                    if edge.get("from") in subgraph_ids and edge.get("to") in subgraph_ids
                )
                all_actions_complete = all(_status(node) in SUCCESS_STATUSES for node in matched_actions)
                qualification = (
                    "verified_success_path"
                    if success["status"] == "verified_success" and all_actions_complete and not cycle_ids
                    else "historical_subgraph"
                )
                modes = sorted(
                    {
                        mode
                        for node_id in subgraph_ids
                        for mode in _capture_modes(history_nodes.get(node_id, {}))
                    }
                )
                reuse_mode = (
                    "template_only"
                    if modes == ["live"]
                    else "advisory_only_non_live_history"
                )
                match_id = (
                    f"history:{history.get('graph_id', 'unknown')}:{history_run['id']}:{reuse_key}"
                )
                matches.append(
                    {
                        "match_id": match_id,
                        "qualification": qualification,
                        "reuse_mode": reuse_mode,
                        "reuse_key": reuse_key,
                        "current_node_ids": sorted(current_by_key[reuse_key]),
                        "history_graph_id": history.get("graph_id"),
                        "history_run_id": history_run["id"],
                        "history_source_ledger": history.get("source_ledger"),
                        "success_evidence": success,
                        "path_node_ids": path_ids,
                        "path_cycle_node_ids": cycle_ids,
                        "subgraph_node_ids": sorted(subgraph_ids),
                        "subgraph_edge_ids": edge_ids,
                        "provenance": {
                            "data_origin": "historical_canonical_subgraph",
                            "not_current_run_telemetry": True,
                            "capture_modes": modes,
                            "actualness": _provenance_actualness(modes, matched_actions),
                        },
                    }
                )
    return sorted(
        matches,
        key=lambda item: (
            0 if item["qualification"] == "verified_success_path" else 1,
            item["match_id"],
        ),
    )


def build_graph_runtime_advice(
    graph: dict[str, Any],
    *,
    run_id: str | None = None,
    history_graphs: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Derive evidence gaps, safe next Action/ToolCall suggestions and reuse hints."""

    selected_run_id = _resolve_runtime_run_id(graph, run_id)
    snapshot = (
        build_runtime_snapshot(graph, run_id=selected_run_id)
        if selected_run_id is not None
        else {"status": "not_configured", "ready": [], "counts": {}}
    )
    gates = [
        build_claim_gate(graph, node["id"], run_id=selected_run_id)
        for node in _claims_in_scope(graph, selected_run_id)
    ]
    missing_evidence = [
        {**gap, "gate_claim_id": gate["claim"]["id"]}
        for gate in gates
        for gap in gate["missing_evidence"]
    ]
    missing_claim_ids = {gap["claim_id"] for gap in missing_evidence if "claim_id" in gap}
    ready = list(snapshot.get("ready", []))
    recommendations: list[dict[str, Any]] = []
    prerequisite_nodes: list[dict[str, Any]] = []
    for entry in ready:
        if entry.get("type") in ACTION_RECOMMENDATION_TYPES:
            addressed = _addressed_claim_ids(
                graph, entry["id"], missing_claim_ids, run_id=selected_run_id
            )
            recommendations.append(
                {
                    "node": {
                        key: entry[key]
                        for key in ("id", "type", "label", "status", "first_sequence", "priority")
                        if key in entry
                    },
                    "addresses_claim_ids": addressed,
                    "rationale": (
                        "explicit_runtime_frontier_and_authored_evidence_path"
                        if addressed
                        else "explicit_runtime_frontier"
                    ),
                    "context": entry.get("context", {}),
                    "derivation": {
                        "data_origin": "derived",
                        "not_native_telemetry": True,
                        "source_node_ids": sorted(
                            {entry["id"]}
                            | set(addressed)
                            | {
                                node["id"]
                                for node in entry.get("context", {}).get("nodes", [])
                                if isinstance(node, dict) and isinstance(node.get("id"), str)
                            }
                        ),
                        "source_edge_ids": [],
                    },
                }
            )
        else:
            prerequisite_nodes.append(entry)

    history_matches = find_reusable_paths(
        graph, run_id=selected_run_id, history_graphs=history_graphs
    )
    matches_by_current: dict[str, list[str]] = defaultdict(list)
    for match in history_matches:
        for node_id in match["current_node_ids"]:
            matches_by_current[node_id].append(match["match_id"])
    for recommendation in recommendations:
        recommendation["historical_match_ids"] = sorted(
            matches_by_current.get(recommendation["node"]["id"], [])
        )

    if selected_run_id is None:
        status = "no_run"
    elif recommendations:
        status = "action_recommended"
    elif prerequisite_nodes:
        status = "runtime_prerequisite_ready"
    elif missing_evidence:
        status = "evidence_gap_without_authored_action"
    else:
        status = "no_action_recommended"

    source_nodes = {
        node_id
        for gate in gates
        for node_id in gate["derivation"]["source_node_ids"]
    }
    source_nodes.update(
        recommendation["node"]["id"] for recommendation in recommendations
    )
    return {
        "protocol_version": GRAPH_RUNTIME_PROTOCOL_VERSION,
        "status": status,
        "run_id": selected_run_id,
        "source_graph_id": graph.get("graph_id"),
        "runtime_snapshot": snapshot,
        "claim_gates": gates,
        "missing_evidence": missing_evidence,
        "recommendations": recommendations,
        "prerequisite_runtime_nodes": prerequisite_nodes,
        "historical_reuse": {
            "match_policy": "explicit_reuse_key_only_no_label_similarity",
            "matches": history_matches,
        },
        "derivation": {
            "data_origin": "derived",
            "not_native_telemetry": True,
            "source": "canonical_graph_runtime_state_and_authored_relations",
            "source_node_ids": sorted(source_nodes),
            "source_edge_ids": sorted(
                {
                    edge_id
                    for gate in gates
                    for edge_id in gate["derivation"]["source_edge_ids"]
                }
            ),
        },
    }


def recommendation_record_attrs(
    advice: dict[str, Any], *, source_ledger_sha256: str | None
) -> dict[str, Any]:
    """Make the durable portion of a derived recommendation explicit and small."""

    gates = []
    for gate in advice.get("claim_gates", []):
        gates.append(
            {
                "claim_id": gate["claim"]["id"],
                "gate_status": gate["status"],
                "can_confirm": gate["can_confirm"],
                "missing_codes": sorted(
                    {item["code"] for item in gate.get("missing_evidence", [])}
                ),
                "evidence_actualness": gate["evidence_actualness"],
            }
        )
    return {
        "record_kind": RECOMMENDATION_RECORD_KIND,
        "runtime_protocol_version": GRAPH_RUNTIME_PROTOCOL_VERSION,
        "data_origin": "derived",
        "not_native_telemetry": True,
        "source_graph_id": advice.get("source_graph_id"),
        "source_ledger_sha256": source_ledger_sha256,
        "run_id": advice.get("run_id"),
        "recommended_node_ids": [
            item["node"]["id"] for item in advice.get("recommendations", [])
        ],
        "prerequisite_node_ids": [
            item["id"] for item in advice.get("prerequisite_runtime_nodes", [])
        ],
        "claim_gate_snapshot": gates,
        "historical_path_refs": [
            item["match_id"]
            for item in advice.get("historical_reuse", {}).get("matches", [])
        ],
        "source_node_ids": list(advice.get("derivation", {}).get("source_node_ids", [])),
        "source_edge_ids": list(advice.get("derivation", {}).get("source_edge_ids", [])),
    }


__all__ = [
    "ACTION_RECOMMENDATION_TYPES",
    "CLAIM_NODE_TYPES",
    "EVIDENCE_NODE_TYPES",
    "GRAPH_RUNTIME_PROTOCOL_VERSION",
    "RECOMMENDATION_RECORD_KIND",
    "build_claim_gate",
    "build_graph_runtime_advice",
    "find_reusable_paths",
    "recommendation_record_attrs",
    "resolve_claim_run_id",
]
