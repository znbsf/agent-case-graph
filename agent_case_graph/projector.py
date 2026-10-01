from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .graph_runtime import build_graph_runtime_advice
from .ledger import sha256_file
from .model import ACGError, SCHEMA_VERSION
from .replay import build_replay_catalog
from .runtime import build_runtime_catalog
from .spatial import build_spatial_catalog


def _event_provenance(event: dict[str, Any]) -> dict[str, list[str]]:
    run_id = event.get("run_id")
    return {
        "capture_modes": [event["provenance"]["capture_mode"]],
        "source_refs": sorted(set(event["provenance"].get("source_refs", []))),
        "run_ids": [run_id] if isinstance(run_id, str) and run_id else [],
    }


def _merge_provenance(target: dict[str, list[str]], event: dict[str, Any]) -> None:
    incoming = _event_provenance(event)
    for key in ("capture_modes", "source_refs", "run_ids"):
        target[key] = sorted(set(target.get(key, [])) | set(incoming[key]))


def project_events(
    events: list[dict[str, Any]],
    *,
    ledger_path: str | Path | None = None,
    ledger_sha256: str | None = None,
) -> dict[str, Any]:
    declaration = events[0]["graph"]
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    state_history: list[dict[str, Any]] = []
    capture_modes: Counter[str] = Counter()

    for event in events:
        capture_modes[event["provenance"]["capture_mode"]] += 1
        kind = event["kind"]
        if kind == "node.recorded":
            incoming = event["node"]
            node_id = incoming["id"]
            existing = nodes.get(node_id)
            if existing is None:
                nodes[node_id] = {
                    "id": node_id,
                    "type": incoming["type"],
                    "label": incoming["label"],
                    "attrs": dict(incoming.get("attrs", {})),
                    "event_ids": [event["event_id"]],
                    "first_sequence": event["sequence"],
                    "last_sequence": event["sequence"],
                    "provenance": _event_provenance(event),
                }
            else:
                if existing["type"] != incoming["type"]:
                    raise ACGError(
                        f"node {node_id} changed type from {existing['type']} to {incoming['type']}"
                    )
                existing["label"] = incoming["label"]
                existing["attrs"].update(incoming.get("attrs", {}))
                existing["event_ids"].append(event["event_id"])
                existing["last_sequence"] = event["sequence"]
                _merge_provenance(existing["provenance"], event)
        elif kind == "edge.recorded":
            incoming = event["edge"]
            edge_id = incoming["id"]
            existing = edges.get(edge_id)
            if existing is None:
                edges[edge_id] = {
                    "id": edge_id,
                    "type": incoming["type"],
                    "from": incoming["from"],
                    "to": incoming["to"],
                    "attrs": dict(incoming.get("attrs", {})),
                    "event_ids": [event["event_id"]],
                    "first_sequence": event["sequence"],
                    "last_sequence": event["sequence"],
                    "provenance": _event_provenance(event),
                }
            else:
                identity = (existing["type"], existing["from"], existing["to"])
                incoming_identity = (incoming["type"], incoming["from"], incoming["to"])
                if identity != incoming_identity:
                    raise ACGError(f"edge {edge_id} changed identity")
                existing["attrs"].update(incoming.get("attrs", {}))
                existing["event_ids"].append(event["event_id"])
                existing["last_sequence"] = event["sequence"]
                _merge_provenance(existing["provenance"], event)
        elif kind == "state.changed":
            transition = dict(event["transition"])
            transition.update(
                {
                    "event_id": event["event_id"],
                    "sequence": event["sequence"],
                    "occurred_at": event["occurred_at"],
                    "actor": event["actor"],
                    "capture_mode": event["provenance"]["capture_mode"],
                }
            )
            state_history.append(transition)

    latest_states: dict[str, str] = {}
    for transition in state_history:
        latest_states[transition["subject_id"]] = transition["to"]
    for subject_id, state in latest_states.items():
        if subject_id in nodes:
            nodes[subject_id]["attrs"]["current_state"] = state

    source_ledger: dict[str, Any] | None = None
    if ledger_path is not None:
        source = Path(ledger_path)
        source_ledger = {"name": source.name, "sha256": ledger_sha256 or sha256_file(source)}

    node_list = sorted(nodes.values(), key=lambda item: (item["first_sequence"], item["id"]))
    edge_list = sorted(edges.values(), key=lambda item: (item["first_sequence"], item["id"]))
    graph = {
        "schema_version": SCHEMA_VERSION,
        "graph_id": declaration["id"],
        "graph_type": declaration["type"],
        "root_id": declaration["root_id"],
        "generated_at": events[-1]["occurred_at"],
        "source_ledger": source_ledger,
        "nodes": node_list,
        "edges": edge_list,
        "state_history": state_history,
        "stats": {
            "event_count": len(events),
            "node_count": len(node_list),
            "edge_count": len(edge_list),
            "capture_modes": dict(sorted(capture_modes.items())),
        },
    }
    graph["runtime"] = build_runtime_catalog(graph)
    graph["runtime_advice"] = build_graph_runtime_advice(graph)
    graph["spatial"] = build_spatial_catalog(graph)
    graph["replay"] = build_replay_catalog(graph, events)
    return graph
