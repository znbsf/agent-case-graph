from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .model import ALLOWED_TRANSITIONS


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def lint_graph(graph: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = graph["edges"]
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add(
        code: str,
        severity: str,
        message: str,
        *,
        node_id: str | None = None,
        edge_id: str | None = None,
    ) -> None:
        finding = {"code": code, "severity": severity, "message": message}
        if node_id:
            finding["node_id"] = node_id
        if edge_id:
            finding["edge_id"] = edge_id
        findings.append(finding)

    root = nodes.get(graph["root_id"])
    if root is None:
        add("ACG001", "error", f"root node is missing: {graph['root_id']}")
    elif root["type"] != "Case":
        add("ACG002", "error", "root node must have type Case", node_id=root["id"])

    for edge in edges:
        if edge["from"] not in nodes:
            add(
                "ACG003",
                "error",
                f"edge source does not exist: {edge['from']}",
                edge_id=edge["id"],
            )
        if edge["to"] not in nodes:
            add(
                "ACG004",
                "error",
                f"edge target does not exist: {edge['to']}",
                edge_id=edge["id"],
            )
        outgoing[edge["from"]].append(edge)
        incoming[edge["to"]].append(edge)

    for node in nodes.values():
        node_id = node["id"]
        node_type = node["type"]
        attrs = node.get("attrs", {})
        if node_type == "Case":
            has_run = any(edge["type"] == "has_run" for edge in outgoing[node_id])
            if not has_run:
                add("ACG005", "error", "Case has no Run", node_id=node_id)
        elif node_type == "Claim":
            evidence_edges = [
                edge for edge in incoming[node_id] if edge["type"] in {"supports", "refutes"}
            ]
            if not evidence_edges:
                severity = "error" if attrs.get("status") == "confirmed" else "warning"
                add(
                    "ACG006",
                    severity,
                    "Claim has no supports/refutes evidence edge",
                    node_id=node_id,
                )
            if attrs.get("status") == "confirmed" and not any(
                edge["type"] == "supports" for edge in evidence_edges
            ):
                add(
                    "ACG007",
                    "error",
                    "confirmed Claim has no supporting evidence",
                    node_id=node_id,
                )
        elif node_type == "Artifact":
            source_present = bool(attrs.get("source_path") or attrs.get("source_uri"))
            if not source_present:
                add("ACG008", "error", "Artifact has no source path/URI", node_id=node_id)
            digest = attrs.get("sha256")
            if not isinstance(digest, str) or not SHA256_PATTERN.fullmatch(digest):
                add("ACG009", "error", "Artifact has no valid SHA256", node_id=node_id)
            if attrs.get("capture_mode") not in {"live", "reconstructed", "synthetic"}:
                add("ACG010", "error", "Artifact has no capture mode", node_id=node_id)
        elif node_type == "Action" and attrs.get("mutating") is True:
            approvals = [edge for edge in outgoing[node_id] if edge["type"] == "approved_by"]
            if not approvals:
                add("ACG011", "error", "mutating Action has no Approval", node_id=node_id)
        elif node_type == "SkillVersion":
            has_pattern = any(edge["type"] == "implemented_by" for edge in incoming[node_id])
            has_eval = any(edge["type"] == "tested_by" for edge in outgoing[node_id])
            if not has_pattern:
                add("ACG012", "error", "SkillVersion has no source Pattern", node_id=node_id)
            if not has_eval:
                add("ACG013", "error", "SkillVersion has no EvalCase", node_id=node_id)

        if node_type in {"DialogueRound", "ExecutionIteration"}:
            index = attrs.get("index")
            if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                add(
                    "ACG018",
                    "error",
                    f"{node_type} index must be an integer >= 0",
                    node_id=node_id,
                )
        if node_type == "DialogueRound":
            parents = [
                edge["from"]
                for edge in incoming[node_id]
                if edge["type"] == "contains"
                and nodes.get(edge["from"], {}).get("type") in {"Case", "Run"}
            ]
            if len(set(parents)) != 1:
                add(
                    "ACG019",
                    "error",
                    "DialogueRound must have exactly one Case or Run scope parent",
                    node_id=node_id,
                )
        elif node_type == "ExecutionIteration":
            parents = [
                edge["from"]
                for edge in incoming[node_id]
                if edge["type"] == "contains"
                and nodes.get(edge["from"], {}).get("type") == "DialogueRound"
            ]
            if len(set(parents)) != 1:
                add(
                    "ACG020",
                    "error",
                    "ExecutionIteration must have exactly one DialogueRound parent",
                    node_id=node_id,
                )
        elif node_type in {"UserFeedback", "AgentResponse", "Evaluation"}:
            expected_parent = "ExecutionIteration" if node_type == "Evaluation" else "DialogueRound"
            has_parent = any(
                edge["type"] == "contains"
                and nodes.get(edge["from"], {}).get("type") == expected_parent
                for edge in incoming[node_id]
            )
            if not has_parent:
                add(
                    "ACG021",
                    "error",
                    f"{node_type} must be contained by {expected_parent}",
                    node_id=node_id,
                )

    scoped_indexes: dict[tuple[str, str, int], str] = {}
    for node in nodes.values():
        if node["type"] not in {"DialogueRound", "ExecutionIteration"}:
            continue
        index = node.get("attrs", {}).get("index")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            continue
        parent_type = "DialogueRound" if node["type"] == "ExecutionIteration" else None
        parents = [
            edge["from"]
            for edge in incoming[node["id"]]
            if edge["type"] == "contains"
            and (parent_type is None or nodes.get(edge["from"], {}).get("type") == parent_type)
        ]
        for parent in sorted(set(parents)):
            key = (parent, node["type"], index)
            if key in scoped_indexes:
                add(
                    "ACG022",
                    "error",
                    f"duplicate {node['type']} index {index} under {parent}",
                    node_id=node["id"],
                )
            else:
                scoped_indexes[key] = node["id"]

    if root is not None:
        root_state = root.get("attrs", {}).get("current_state")
        root_status = root.get("attrs", {}).get("status")
        if root_state in {"close", "promote"} or root_status in {
            "closed",
            "completed",
            "resolved",
        }:
            has_receipt = any(
                edge["type"] == "verified_by"
                and nodes.get(edge["to"], {}).get("type") == "VerificationReceipt"
                for edge in outgoing[root["id"]]
            )
            if not has_receipt:
                add(
                    "ACG014",
                    "error",
                    "closed/completed Case has no VerificationReceipt",
                    node_id=root["id"],
                )

    previous_state: dict[str, str] = {}
    for transition in graph["state_history"]:
        subject_id = transition["subject_id"]
        from_state = transition["from"]
        to_state = transition["to"]
        if subject_id in previous_state and previous_state[subject_id] != from_state:
            add(
                "ACG015",
                "error",
                f"state history discontinuity: expected {previous_state[subject_id]}, got {from_state}",
                node_id=subject_id,
            )
        if to_state not in ALLOWED_TRANSITIONS.get(from_state, set()):
            add(
                "ACG016",
                "error",
                f"invalid state transition: {from_state} -> {to_state}",
                node_id=subject_id,
            )
        previous_state[subject_id] = to_state

    edge_signatures: dict[tuple[str, str, str], str] = {}
    for edge in edges:
        signature = (edge["type"], edge["from"], edge["to"])
        if signature in edge_signatures:
            add(
                "ACG017",
                "warning",
                f"duplicate semantic edge; first is {edge_signatures[signature]}",
                edge_id=edge["id"],
            )
        else:
            edge_signatures[signature] = edge["id"]

    return sorted(
        findings,
        key=lambda item: (
            0 if item["severity"] == "error" else 1,
            item["code"],
            item.get("node_id", ""),
            item.get("edge_id", ""),
        ),
    )
