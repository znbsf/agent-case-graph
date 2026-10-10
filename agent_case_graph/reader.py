"""Read-only, source-bound reading spans over the canonical graph.

A span is a display grouping, not a newly observed execution or a new verdict.
No label matching, chronology-to-causality inference, or runtime writes occur.
"""
from __future__ import annotations

import html
import json
import re
from collections import Counter
from importlib.resources import files
from typing import Any

PROTOCOL_VERSION = "case-reader-0.1"
QUIET_RELATIONS = {"contains", "has_run", "instance_of"}


def build_reader_model(graph: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    nodes = {node["id"]: node for node in trace["nodes"]}
    edges = trace["edges"]
    overview = trace.get("overview", {})
    groups = {node["source_group_id"]: node for node in overview.get("nodes", [])}
    plan_uses = Counter(key for group in overview.get("nodes", [])
                        if group.get("attrs", {}).get("loop_scope") == "execution"
                        for key in set(group.get("attrs", {}).get("member_ids", []))
                        if nodes.get(key, {}).get("type") == "Plan")
    stages = []
    covered: set[str] = set()

    def ordered(ids):
        return sorted(set(ids) & nodes.keys(), key=lambda key: (
            nodes[key].get("first_sequence") or 0, key))

    for group in overview.get("nodes", []):
        attrs = group.get("attrs", {})
        if attrs.get("loop_scope") != "execution":
            continue
        members = set(attrs.get("member_ids", [])) & nodes.keys()
        plan_ids = ordered(key for key in members if nodes[key]["type"] == "Plan")
        goal_ids = {edge["from"] for edge in edges
                    if edge["type"] == "frames" and edge["to"] in plan_ids
                    and nodes.get(edge["from"], {}).get("type") == "Goal"}
        parent = groups.get(attrs.get("parent_group_id"), {})
        goal_ids.update(key for key in parent.get("attrs", {}).get("member_ids", [])
                        if nodes.get(key, {}).get("type") in {"Goal", "UserFeedback"})
        members.update(goal_ids)
        related = [edge for edge in edges if edge["type"] not in QUIET_RELATIONS
                   and (edge["from"] in members or edge["to"] in members)]
        # Only immediate, explicitly related evidence is included. In particular,
        # a shared Run/Case never pulls every sibling stage into this scope.
        evidence_ids = members | {key for edge in related for key in (edge["from"], edge["to"])
                                  if key in nodes}
        covered.update(members)
        title_node = nodes.get(plan_ids[0]) if plan_ids else nodes.get(attrs.get("focus_member_id"))
        title = title_node["label"] if title_node else group["label"]
        categorized = lambda types: ordered(key for key in members if nodes[key]["type"] in types)
        conclusions = categorized({"Claim", "RootCause", "AgentResponse", "Outcome"})
        action_ids = categorized({"Action", "ToolCall", "Step"})
        result_ids = categorized({"ToolOutput", "Observation", "Artifact", "VerificationReceipt", "Evaluation"})
        if plan_ids:
            # Loop groups may also contain an earlier stage's informing output.
            # Keep it as context, never relabel it as this stage's own result.
            invoked = {edge["to"] for edge in edges if edge["from"] in plan_ids
                       and edge["type"] in {"invokes", "implemented_by"}}
            action_ids = ordered(invoked & members)
            produced = {edge["to"] for edge in edges if edge["from"] in action_ids
                        and edge["type"] in {"produces", "verified_by"}}
            result_ids = ordered(produced)
            own_claims = {edge["to"] for edge in edges if edge["from"] in produced
                          and edge["type"] in {"supports", "explains"}}
            conclusions = [key for key in conclusions if key in own_claims]
            # A shared, refuted hypothesis is one-hop counterevidence, not an
            # owned seed from which to import other stages' refuting outputs.
            counter_targets = {edge["to"] for edge in edges
                               if edge["from"] in produced and edge["type"] == "refutes"}
            scope_seeds = members - (counter_targets - set(conclusions))
            related = [edge for edge in edges if edge["type"] not in QUIET_RELATIONS
                       and (edge["from"] in scope_seeds or edge["to"] in scope_seeds)]
            evidence_ids = scope_seeds | {key for edge in related for key in (edge["from"], edge["to"])
                                         if key in nodes}
        counter_edges = [edge["id"] for edge in related if edge["type"] == "refutes"
                         and (edge["from"] in result_ids or edge["to"] in conclusions)]
        modes = sorted({mode for key in members for mode in nodes[key].get("provenance", {}).get("capture_modes", [])})
        sources = sorted({ref for key in evidence_ids
                          for ref in nodes[key].get("provenance", {}).get("source_refs", [])})
        content_members = set(plan_ids + ordered(goal_ids) + action_ids + result_ids + conclusions
                              + categorized({"Decision", "UserFeedback", "Uncertainty", "ScopeBoundary"}))
        boundaries = list(dict.fromkeys(str(nodes[key]["attrs"]["boundary"]) for key in ordered(content_members)
                                       if nodes[key].get("attrs", {}).get("boundary")))
        source_kinds = sorted({nodes[key]["attrs"]["source_kind"] for key in members
                               if isinstance(nodes[key].get("attrs", {}).get("source_kind"), str)})
        stages.append({
            "id": plan_ids[0] if len(plan_ids) == 1 and plan_uses[plan_ids[0]] == 1 else group["id"],
            "title": title, "title_node_id": title_node["id"] if title_node else None,
            "sequence_scope_id": group["id"], "explicit_iteration": attrs.get("explicit") is True,
            "member_ids": ordered(members), "related_node_ids": ordered(evidence_ids),
            "goal_ids": ordered(goal_ids), "plan_ids": plan_ids,
            "action_ids": action_ids, "result_ids": result_ids,
            "conclusion_ids": conclusions,
            "decision_ids": categorized({"Decision", "UserFeedback"}),
            "uncertainty_ids": categorized({"Uncertainty", "ScopeBoundary"}),
            "relation_ids": [edge["id"] for edge in related],
            "counterevidence_ids": counter_edges, "capture_modes": modes,
            "source_kinds": source_kinds, "source_refs": sources, "boundaries": boundaries,
        })

    root = next((node for node in graph["nodes"] if node["id"] == graph["root_id"]), {})
    raw_coverage = root.get("attrs", {}).get("coverage", {})
    coverage = {key: value for key, value in raw_coverage.items()
                if key in {"returned_turn_metadata", "turns_with_visible_items", "turns_without_items", "selected_excerpt_turns"}
                and isinstance(value, int) and not isinstance(value, bool) and value >= 0} if isinstance(raw_coverage, dict) else {}
    capture_modes = sorted({event["capture_mode"] for event in trace.get("trace", [])})
    return {
        "protocol_version": PROTOCOL_VERSION, "graph_id": graph["graph_id"],
        "root_id": graph["root_id"], "stages": stages, "nodes": list(nodes.values()), "edges": edges,
        "capture_modes": capture_modes, "coverage": coverage,
        "unscoped_node_ids": ordered(nodes.keys() - covered - {graph["root_id"]}),
        "global_boundary_ids": ordered(key for key in nodes if nodes[key]["type"] == "ScopeBoundary"),
        "boundary": root.get("attrs", {}).get("boundary", ""),
        "event_count": len(trace.get("trace", [])), "source_ledger": graph.get("source_ledger"),
        "principles": {"display_only": True, "stage_order_is_causality": False,
                       "status_is_new_verification": False, "source_records_modified": False},
    }


def render_reader_html(model: dict[str, Any], *, title: str,
                       display_locales: dict[str, dict[str, Any]] | None = None,
                       default_locale: str = "zh-CN") -> str:
    resources = files("agent_case_graph").joinpath("web")
    payload = json.dumps({"model": model, "title": title, "locales": display_locales or {},
                          "default_locale": default_locale}, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    replacements = {"TITLE": html.escape(title), "DATA": payload,
                    "STYLE": resources.joinpath("reader.css").read_text(encoding="utf-8"),
                    "SCRIPT": resources.joinpath("reader.js").read_text(encoding="utf-8")}
    # One substitution pass: source labels containing template tokens stay data.
    return re.sub(r"__(TITLE|DATA|STYLE|SCRIPT)__", lambda match: replacements[match[1]],
                  resources.joinpath("reader.html").read_text(encoding="utf-8"))
