"""Deterministic, visual-only replay projections for Agent Case Graph.

The replay catalog never invokes an executor and never replays external side
effects.  The actual track is a sequence-authoritative view of events that
were already appended to the Ledger.  The retrospective track is a stable
topological schedule over explicit ``precedes`` edges; without a declared
cost function it is a recommendation, not a globally proven optimum.
"""

from __future__ import annotations

from collections import defaultdict
import heapq
from typing import Any


REPLAY_PROTOCOL_VERSION = "replay-0.1"
RUNTIME_NODE_TYPES = frozenset({"Step", "Action", "Verification"})


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _event_frame(
    event: dict[str, Any], previous_statuses: dict[str, str]
) -> dict[str, Any]:
    frame: dict[str, Any] = {
        "sequence": event["sequence"],
        "event_id": event["event_id"],
        "kind": event["kind"],
        "occurred_at": event["occurred_at"],
        "actor": dict(event["actor"]),
        "capture_mode": event["provenance"]["capture_mode"],
        "source_refs": list(event["provenance"].get("source_refs", [])),
        "subject_ids": [],
    }
    if event["kind"] == "node.recorded":
        node = event["node"]
        node_id = node["id"]
        frame["node_id"] = node_id
        frame["node_type"] = node["type"]
        frame["subject_ids"] = [node_id]
        incoming_status = node.get("attrs", {}).get("status")
        if incoming_status is not None:
            frame["from_status"] = previous_statuses.get(node_id)
            frame["to_status"] = str(incoming_status)
            frame["status_source"] = (
                "inferred_from_prior_node_event"
                if node_id in previous_statuses
                else "recorded_to_only"
            )
            previous_statuses[node_id] = str(incoming_status)
    elif event["kind"] == "edge.recorded":
        edge = event["edge"]
        frame["edge_id"] = edge["id"]
        frame["edge_type"] = edge["type"]
        frame["subject_ids"] = [edge["from"], edge["to"]]
    elif event["kind"] == "state.changed":
        transition = event["transition"]
        frame["subject_ids"] = [transition["subject_id"]]
        frame["from_status"] = transition["from"]
        frame["to_status"] = transition["to"]
        frame["status_source"] = "recorded"
    return frame


def _capture_profile(frames: list[dict[str, Any]]) -> dict[str, Any]:
    modes = sorted({str(frame["capture_mode"]) for frame in frames})
    if modes == ["live"]:
        track_kind = "live-ledger"
        completeness = "partial"
        boundary = "Recorded Ledger events; raw tool I/O and external side effects may be absent."
    elif modes == ["reconstructed"]:
        track_kind = "reconstructed-ledger"
        completeness = "reconstructed"
        boundary = "Reconstructed evidence order; not the original step-by-step execution trace."
    elif modes == ["synthetic"]:
        track_kind = "synthetic-ledger"
        completeness = "synthetic"
        boundary = "Synthetic demonstration events; no real action execution is claimed."
    else:
        track_kind = "mixed-ledger"
        completeness = "partial"
        boundary = "Mixed capture modes; inspect each frame before treating it as execution evidence."
    return {
        "track_kind": track_kind,
        "capture_modes": modes,
        "completeness": completeness,
        "boundary": boundary,
    }


def _priority(node: dict[str, Any]) -> int:
    return _int(node.get("attrs", {}).get("priority"), 100)


def _runtime_entries(graph: dict[str, Any], run_id: str) -> dict[str, dict[str, Any]]:
    runtime = graph.get("runtime", {})
    snapshot = next(
        (
            item
            for item in runtime.get("runs", [])
            if item.get("run_id") == run_id
        ),
        None,
    )
    if snapshot is None:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for lane in ("ready", "running", "blocked", "completed", "failed"):
        for entry in snapshot.get(lane, []):
            node_id = entry.get("id") or entry.get("node_id")
            if isinstance(node_id, str) and node_id:
                result[node_id] = {
                    "lane": lane,
                    "blockers": list(entry.get("blockers", [])),
                }
    return result


def _recommendation(
    graph: dict[str, Any], run_id: str
) -> dict[str, Any]:
    nodes_by_id = {node["id"]: node for node in graph.get("nodes", [])}
    contained = {
        edge["to"]
        for edge in graph.get("edges", [])
        if edge.get("type") == "contains" and edge.get("from") == run_id
    }
    candidate_ids = {
        node_id
        for node_id in contained
        if node_id in nodes_by_id
        and nodes_by_id[node_id].get("type") in RUNTIME_NODE_TYPES
        and nodes_by_id[node_id].get("attrs", {}).get("runtime_managed") is True
    }
    if not candidate_ids:
        return {
            "status": "unavailable",
            "basis": "explicit_precedes + runtime gates + stable tie-break",
            "optimality": "not_proven",
            "reason": "No runtime-managed Step, Action, or Verification nodes are contained by this Run.",
            "steps": [],
            "edges": [],
        }

    adjacency: dict[str, set[str]] = {node_id: set() for node_id in candidate_ids}
    indegree = {node_id: 0 for node_id in candidate_ids}
    route_edges: list[dict[str, Any]] = []
    for edge in graph.get("edges", []):
        source = edge.get("from")
        target = edge.get("to")
        if (
            edge.get("type") == "precedes"
            and source in candidate_ids
            and target in candidate_ids
            and target not in adjacency[source]
        ):
            adjacency[source].add(target)
            indegree[target] += 1
            route_edges.append(
                {
                    "edge_id": edge["id"],
                    "from": source,
                    "to": target,
                    "type": "precedes",
                }
            )

    def key(node_id: str) -> tuple[int, int, str]:
        node = nodes_by_id[node_id]
        return (
            _priority(node),
            _int(node.get("first_sequence"), 2**63 - 1),
            node_id,
        )

    ready: list[tuple[tuple[int, int, str], str]] = []
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

    if len(ordered) != len(candidate_ids):
        cycle_ids = sorted(candidate_ids - set(ordered))
        return {
            "status": "cycle",
            "basis": "explicit_precedes + runtime gates + stable tie-break",
            "optimality": "not_proven",
            "reason": "The explicit precedes graph contains a cycle.",
            "cycle_node_ids": cycle_ids,
            "steps": [],
            "edges": sorted(route_edges, key=lambda item: item["edge_id"]),
        }

    steps = []
    runtime_entries = _runtime_entries(graph, run_id)
    order_index = {node_id: index for index, node_id in enumerate(ordered)}
    unresolved_gates: list[dict[str, Any]] = []
    for index, node_id in enumerate(ordered):
        node = nodes_by_id[node_id]
        runtime_entry = runtime_entries.get(node_id, {})
        lane = runtime_entry.get("lane")
        blockers = list(runtime_entry.get("blockers", []))
        if lane == "failed":
            unresolved_gates.append(
                {"node_id": node_id, "code": "runtime_failed"}
            )
        for blocker in blockers:
            blocker_code = blocker.get("code")
            predecessor_id = blocker.get("node_id")
            is_resolvable_predecessor = (
                blocker_code == "predecessor_incomplete"
                and predecessor_id in order_index
                and order_index[predecessor_id] < index
            )
            if not is_resolvable_predecessor:
                unresolved_gates.append(
                    {
                        "node_id": node_id,
                        "code": blocker_code or "runtime_gate",
                        "gate_node_id": predecessor_id,
                    }
                )
        steps.append(
            {
                "index": index,
                "node_id": node_id,
                "node_type": node["type"],
                "status": node.get("attrs", {}).get("status"),
                "runtime_lane": lane,
                "blockers": blockers,
                "priority": _priority(node),
                "first_sequence": node.get("first_sequence"),
            }
        )
    sorted_route_edges = sorted(
        route_edges,
        key=lambda item: (
            order_index[item["from"]],
            order_index[item["to"]],
            item["edge_id"],
        ),
    )
    if unresolved_gates:
        blocker_codes = sorted({item["code"] for item in unresolved_gates})
        return {
            "status": "gated",
            "basis": "explicit_precedes + runtime gates + (priority, first_sequence, node_id)",
            "shape": "deterministic_topological_schedule",
            "optimality": "not_proven",
            "reason": "The current runtime snapshot contains unresolved non-sequential gates.",
            "gate_blocker_codes": blocker_codes,
            "unresolved_gates": unresolved_gates,
            "steps": steps,
            "edges": sorted_route_edges,
        }
    return {
        "status": "available",
        "basis": "explicit_precedes + runtime gates + (priority, first_sequence, node_id)",
        "shape": "deterministic_topological_schedule",
        "optimality": "not_proven",
        "reason": "No complete alternative graph or declared cost function is available.",
        "steps": steps,
        "edges": sorted_route_edges,
    }


def build_replay_catalog(
    graph: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build a JSON-compatible replay catalog from canonical graph and events."""

    previous_statuses_by_run: dict[str, dict[str, str]] = defaultdict(dict)
    frames_by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in sorted(events, key=lambda item: (item["sequence"], item["event_id"])):
        run_id = event.get("run_id")
        if isinstance(run_id, str) and run_id:
            frame = _event_frame(event, previous_statuses_by_run[run_id])
            frames_by_run[run_id].append(frame)

    run_nodes = sorted(
        [node for node in graph.get("nodes", []) if node.get("type") == "Run"],
        key=lambda node: (
            _int(node.get("first_sequence"), 2**63 - 1),
            str(node.get("id", "")),
        ),
    )
    runs = []
    for run_node in run_nodes:
        run_id = run_node["id"]
        frames = frames_by_run.get(run_id, [])
        actual = {
            "status": "available" if frames else "unavailable",
            "order_authority": "ledger.sequence",
            "wall_clock": "display_only",
            "visual_only": True,
            "reexecutes_actions": False,
            "event_count": len(frames),
            "first_sequence": frames[0]["sequence"] if frames else None,
            "last_sequence": frames[-1]["sequence"] if frames else None,
            "frames": frames,
        }
        actual.update(_capture_profile(frames) if frames else {
            "track_kind": "unavailable",
            "capture_modes": [],
            "completeness": "unknown",
            "boundary": "No Ledger events reference this Run.",
        })
        runs.append(
            {
                "run_id": run_id,
                "run_label": run_node.get("label"),
                "actual": actual,
                "retrospective": _recommendation(graph, run_id),
            }
        )

    return {
        "protocol_version": REPLAY_PROTOCOL_VERSION,
        "order_authority": "ledger.sequence",
        "visual_only": True,
        "reexecutes_actions": False,
        "runs": runs,
    }


__all__ = ["REPLAY_PROTOCOL_VERSION", "build_replay_catalog"]
