"""Small synthetic graphs shared by the project adapter's gate checks."""
from __future__ import annotations

import copy


def mutation_graph(node_type: str = "ToolCall") -> dict:
    definitions = [
        ("case", "Case", {"current_state": "execute"}),
        ("run", "Run", {"capture_mode": "live"}),
        ("call", node_type, {"runtime_managed": True, "mutating": True,
                             "authorized_scope": "repo", "status": "pending"}),
        ("approval", "Approval", {"status": "granted", "scope": "repo"}),
        ("target", "Target", {"path": "repo/example.txt"}),
    ]
    nodes = [{"id": node_id, "type": kind, "label": "Synthetic " + node_id,
              "attrs": attrs, "first_sequence": index, "event_ids": [f"evt:{node_id}"],
              "provenance": {"capture_modes": ["live"], "source_refs": ["test:project-runtime"], "run_ids": ["run"]}}
             for index, (node_id, kind, attrs) in enumerate(definitions, 1)]
    edges = [{"id": edge_id, "type": kind, "from": source, "to": target, "attrs": {},
              "first_sequence": index, "event_ids": [f"evt:{edge_id}"],
              "provenance": {"capture_modes": ["live"], "source_refs": ["test:project-runtime"], "run_ids": ["run"]}}
             for index, (edge_id, kind, source, target) in enumerate([
                 ("has-run", "has_run", "case", "run"), ("contains-call", "contains", "run", "call"),
                 ("approval-edge", "approved_by", "call", "approval"), ("target-edge", "targets", "call", "target")], 6)]
    return {"graph_id": "graph:synthetic", "root_id": "case", "nodes": nodes,
            "edges": edges, "state_history": [], "source_ledger": {"name": "synthetic.jsonl", "sha256": "0" * 64}}


def ledger_events(graph: dict) -> list[dict]:
    records = [("graph.declared", {"graph": {"id": graph["graph_id"], "type": "case", "root_id": graph["root_id"]}})]
    for node in graph["nodes"]:
        records.append(("node.recorded", {"node": {key: copy.deepcopy(node[key]) for key in ("id", "type", "label", "attrs")}}))
    for edge in graph["edges"]:
        records.append(("edge.recorded", {"edge": {key: copy.deepcopy(edge[key]) for key in ("id", "type", "from", "to", "attrs")}}))
    return [{"schema_version": "0.1.0", "event_id": f"evt-project-{index}", "case_id": "SYNTHETIC-PROJECT",
             "run_id": "run", "sequence": index, "occurred_at": "2026-01-01T00:00:00Z", "kind": kind,
             "actor": {"type": "tool", "id": "synthetic-test"},
             "provenance": {"capture_mode": "synthetic", "source_refs": ["test:project-runtime"]}, **payload}
            for index, (kind, payload) in enumerate(records, 1)]
