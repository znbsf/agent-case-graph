"""Compare recorded runtime recommendations with the Ledger path that followed.

Never invokes an executor and never replays external side effects.
"""

from __future__ import annotations

from typing import Any

from .graph_runtime import RECOMMENDATION_RECORD_KIND


PATH_REVIEW_PROTOCOL_VERSION = "path-review-0.1"
RUNTIME_NODE_TYPES = frozenset({"Step", "Action", "ToolCall", "Verification"})


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


def _runtime_event_row(event: dict[str, Any]) -> dict[str, Any]:
    node = event["node"]
    return {
        "sequence": event["sequence"],
        "event_id": event["event_id"],
        "node_id": node["id"],
        "node_type": node["type"],
        "status": node.get("attrs", {}).get("status"),
        "actor": dict(event["actor"]),
        "capture_mode": event["provenance"]["capture_mode"],
        "source_refs": list(event["provenance"].get("source_refs", [])),
    }


def _unique_node_ids(rows: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for row in rows:
        node_id = row["node_id"]
        if node_id not in seen:
            seen.add(node_id)
            result.append(node_id)
    return result


def _longest_common_subsequence(left: list[str], right: list[str]) -> list[str]:
    """Stable LCS over node IDs; this compares paths but never adds causality."""

    scores = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for left_index in range(len(left) - 1, -1, -1):
        for right_index in range(len(right) - 1, -1, -1):
            if left[left_index] == right[right_index]:
                scores[left_index][right_index] = 1 + scores[left_index + 1][right_index + 1]
            else:
                scores[left_index][right_index] = max(
                    scores[left_index + 1][right_index], scores[left_index][right_index + 1]
                )
    result: list[str] = []
    left_index = right_index = 0
    while left_index < len(left) and right_index < len(right):
        if left[left_index] == right[right_index]:
            result.append(left[left_index])
            left_index += 1
            right_index += 1
        elif scores[left_index + 1][right_index] >= scores[left_index][right_index + 1]:
            left_index += 1
        else:
            right_index += 1
    return result


def build_path_review(
    graph: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compare recorded derived recommendations with later Ledger action records.

    The recommendation is deliberately marked as derived.  The actual side is
    only a sequence-authoritative extraction of already-recorded Ledger events;
    it is not a re-execution trace and it makes no claim about omitted actions.
    """

    recommendations = [
        event
        for event in sorted(events, key=lambda item: (item["sequence"], item["event_id"]))
        if event.get("kind") == "node.recorded"
        and event.get("node", {}).get("type") == "Decision"
        and event.get("node", {}).get("attrs", {}).get("record_kind")
        == RECOMMENDATION_RECORD_KIND
    ]
    comparisons: list[dict[str, Any]] = []
    for index, recommendation in enumerate(recommendations):
        attrs = recommendation["node"].get("attrs", {})
        run_id = recommendation.get("run_id")
        end_sequence = next(
            (
                later["sequence"]
                for later in recommendations[index + 1 :]
                if later.get("run_id") == run_id
            ),
            None,
        )
        actual_rows = [
            _runtime_event_row(event)
            for event in events
            if event.get("run_id") == run_id
            and event["sequence"] > recommendation["sequence"]
            and (end_sequence is None or event["sequence"] < end_sequence)
            and event.get("kind") == "node.recorded"
            and event.get("node", {}).get("type") in RUNTIME_NODE_TYPES
            and event.get("node", {}).get("attrs", {}).get("runtime_managed") is True
            and event.get("node", {}).get("attrs", {}).get("data_origin") != "derived"
            and event.get("node", {}).get("attrs", {}).get("source_derived") is not True
        ]
        actual_rows.sort(key=lambda item: (item["sequence"], item["event_id"]))
        recommended_ids = _unique_node_ids(
            [
                {"node_id": node_id}
                for node_id in attrs.get("recommended_node_ids", [])
                if isinstance(node_id, str) and node_id
            ]
        )
        actual_ids = _unique_node_ids(actual_rows)
        matched = _longest_common_subsequence(recommended_ids, actual_ids)
        unobserved = [node_id for node_id in recommended_ids if node_id not in matched]
        unplanned = [node_id for node_id in actual_ids if node_id not in matched]
        if not recommended_ids:
            status = "no_action_recommended"
        elif not actual_rows:
            status = "awaiting_recorded_actual_path"
        elif not unobserved and not unplanned:
            status = "aligned"
        else:
            status = "diverged"
        comparisons.append(
            {
                "recommendation_node_id": recommendation["node"]["id"],
                "recommendation_event_id": recommendation["event_id"],
                "recommendation_sequence": recommendation["sequence"],
                "run_id": run_id,
                "actual_window_end_sequence": end_sequence,
                "status": status,
                "recommended": {
                    "data_origin": "derived",
                    "not_native_telemetry": True,
                    "node_ids": recommended_ids,
                    "record_capture_mode": recommendation["provenance"]["capture_mode"],
                    "source_ledger_sha256": attrs.get("source_ledger_sha256"),
                },
                "actual": {
                    "data_origin": "recorded_ledger_events",
                    "order_authority": "ledger.sequence",
                    "capture_profile": _capture_profile(actual_rows) if actual_rows else {
                        "track_kind": "unavailable",
                        "capture_modes": [],
                        "completeness": "unknown",
                        "boundary": "No subsequent runtime node records in this comparison window.",
                    },
                    "node_ids": actual_ids,
                    "events": actual_rows,
                },
                "comparison": {
                    "data_origin": "derived",
                    "not_native_telemetry": True,
                    "algorithm": "longest_common_subsequence_over_recorded_node_ids",
                    "matched_node_ids": matched,
                    "unobserved_recommended_node_ids": unobserved,
                    "unrecommended_recorded_node_ids": unplanned,
                },
            }
        )
    return {
        "protocol_version": PATH_REVIEW_PROTOCOL_VERSION,
        "visual_only": True,
        "reexecutes_actions": False,
        "comparison_origin": "derived",
        "comparisons": comparisons,
    }


__all__ = ["PATH_REVIEW_PROTOCOL_VERSION", "build_path_review"]
