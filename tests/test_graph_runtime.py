from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agent_case_graph.cli import main
from agent_case_graph.graph_runtime import (
    RECOMMENDATION_RECORD_KIND,
    build_claim_gate,
    build_graph_runtime_advice,
)
from agent_case_graph.ledger import append_event, load_events, write_new_ledger
from agent_case_graph.projector import project_events
from agent_case_graph.replay import build_path_review
from agent_case_graph.runtime import build_runtime_snapshot


ROOT = Path(__file__).resolve().parents[1]
QUICKSTART = ROOT / "examples" / "quickstart" / "events.jsonl"


def _node(
    node_id: str,
    node_type: str,
    label: str,
    sequence: int,
    attrs: dict | None = None,
    capture_mode: str = "live",
) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "label": label,
        "attrs": attrs or {},
        "first_sequence": sequence,
        "event_ids": [f"evt:{node_id}"],
        "provenance": {
            "capture_modes": [capture_mode],
            "source_refs": [f"test:{node_id}"],
            "run_ids": [],
        },
    }


def _edge(edge_id: str, edge_type: str, source: str, target: str, sequence: int) -> dict:
    return {
        "id": edge_id,
        "type": edge_type,
        "from": source,
        "to": target,
        "attrs": {},
        "first_sequence": sequence,
        "event_ids": [f"evt:{edge_id}"],
        "provenance": {
            "capture_modes": ["live"],
            "source_refs": [f"test:{edge_id}"],
            "run_ids": [],
        },
    }


def _current_graph() -> dict:
    nodes = [
        _node("case", "Case", "Case", 1, {"current_state": "execute"}),
        _node("run", "Run", "Run", 2, {"capture_mode": "live"}),
        _node("round", "DialogueRound", "Round", 3, {"index": 0}),
        _node(
            "call",
            "ToolCall",
            "Collect the missing log",
            4,
            {"runtime_managed": True, "status": "pending", "reuse_key": "collect-log"},
        ),
        _node("output", "ToolOutput", "Requested log", 5, {"status": "pending"}),
        _node("claim", "Claim", "Cause confirmed", 6, {"status": "pending"}),
    ]
    edges = [
        _edge("has-run", "has_run", "case", "run", 7),
        _edge("run-round", "contains", "run", "round", 8),
        _edge("round-call", "contains", "round", "call", 9),
        _edge("round-output", "contains", "round", "output", 10),
        _edge("round-claim", "contains", "round", "claim", 11),
        _edge("call-output", "produces", "call", "output", 12),
        _edge("output-claim", "supports", "output", "claim", 13),
    ]
    return {
        "graph_id": "graph:current",
        "root_id": "case",
        "nodes": nodes,
        "edges": edges,
        "source_ledger": {"name": "current.jsonl", "sha256": "0" * 64},
    }


class GraphRuntimeTests(unittest.TestCase):
    def test_nested_runtime_toolcall_recommends_evidence_collection_without_claiming_completion(self) -> None:
        graph = _current_graph()

        snapshot = build_runtime_snapshot(graph, run_id="run")
        self.assertEqual(["call"], snapshot["next_action_ids"])

        advice = build_graph_runtime_advice(graph, run_id="run")
        self.assertEqual("action_recommended", advice["status"])
        self.assertEqual("ToolCall", advice["recommendations"][0]["node"]["type"])
        self.assertEqual(["claim"], advice["recommendations"][0]["addresses_claim_ids"])
        gate = advice["claim_gates"][0]
        self.assertFalse(gate["can_confirm"])
        self.assertIn("evidence_not_complete", {item["code"] for item in gate["missing_evidence"]})
        self.assertTrue(advice["derivation"]["not_native_telemetry"])

    def test_claim_gate_only_opens_after_explicit_completed_evidence(self) -> None:
        graph = _current_graph()
        blocked = build_claim_gate(graph, "claim", run_id="run")
        self.assertEqual("blocked", blocked["status"])

        completed = copy.deepcopy(graph)
        next(node for node in completed["nodes"] if node["id"] == "output")["attrs"]["status"] = "completed"
        open_gate = build_claim_gate(completed, "claim", run_id="run")
        self.assertEqual("open", open_gate["status"])
        self.assertTrue(open_gate["can_confirm"])
        self.assertEqual("live-recorded-evidence", open_gate["evidence_actualness"])
        self.assertEqual("run", build_claim_gate(completed, "claim")["run_id"])

    def test_claim_gate_rejects_cross_run_global_and_derived_supports(self) -> None:
        cross_run = _current_graph()
        cross_run["nodes"].extend(
            [
                _node("other-run", "Run", "Other Run", 20),
                _node(
                    "other-observation",
                    "Observation",
                    "Other Run evidence",
                    21,
                    {"status": "completed"},
                ),
            ]
        )
        cross_run["edges"].extend(
            [
                _edge("other-contains", "contains", "other-run", "other-observation", 22),
                _edge("other-support", "supports", "other-observation", "claim", 23),
            ]
        )
        cross_gate = build_claim_gate(cross_run, "claim", run_id="run")
        self.assertFalse(cross_gate["can_confirm"])
        self.assertEqual([], cross_gate["supporting_evidence"])
        self.assertEqual(
            ["other-observation"],
            [item["evidence"]["id"] for item in cross_gate["excluded_supports"]],
        )

        global_evidence = _current_graph()
        output = next(node for node in global_evidence["nodes"] if node["id"] == "output")
        global_evidence["edges"] = [
            edge for edge in global_evidence["edges"] if edge["id"] != "round-output"
        ]
        output["attrs"]["status"] = "completed"
        global_gate = build_claim_gate(global_evidence, "claim", run_id="run")
        self.assertFalse(global_gate["can_confirm"])
        self.assertEqual("support_outside_selected_run_scope", global_gate["excluded_supports"][0]["reason"])
        global_advice = build_graph_runtime_advice(global_evidence, run_id="run")
        self.assertEqual(
            [],
            global_advice["recommendations"][0]["addresses_claim_ids"],
        )

        derived_evidence = _current_graph()
        output = next(node for node in derived_evidence["nodes"] if node["id"] == "output")
        output["attrs"].update({"status": "completed", "data_origin": "derived"})
        derived_gate = build_claim_gate(derived_evidence, "claim", run_id="run")
        self.assertFalse(derived_gate["can_confirm"])
        self.assertIn(
            "derived_evidence_not_confirmable",
            {item["reason"] for item in derived_gate["incomplete_or_invalid_supports"]},
        )

        derived_relation = _current_graph()
        output = next(node for node in derived_relation["nodes"] if node["id"] == "output")
        output["attrs"]["status"] = "completed"
        next(edge for edge in derived_relation["edges"] if edge["id"] == "output-claim")["attrs"]["data_origin"] = "derived"
        relation_gate = build_claim_gate(derived_relation, "claim", run_id="run")
        self.assertFalse(relation_gate["can_confirm"])
        self.assertIn(
            "derived_support_relation_not_confirmable",
            {item["reason"] for item in relation_gate["incomplete_or_invalid_supports"]},
        )

    def test_advice_default_matches_runtime_run_selection(self) -> None:
        graph = _current_graph()
        graph["nodes"].append(_node("later-run", "Run", "No runtime", 100))
        advice = build_graph_runtime_advice(graph)
        self.assertEqual("run", advice["run_id"])
        self.assertEqual(["call"], [item["node"]["id"] for item in advice["recommendations"]])

        for node in graph["nodes"]:
            if node["id"] == "call":
                node["attrs"]["runtime_managed"] = False
        no_runtime_advice = build_graph_runtime_advice(graph)
        self.assertIsNone(no_runtime_advice["run_id"])
        self.assertEqual([], no_runtime_advice["claim_gates"])

    def test_reconstructed_history_is_advisory_only_even_when_its_case_has_receipt(self) -> None:
        current = _current_graph()
        history = {
            "graph_id": "graph:history",
            "root_id": "history-case",
            "source_ledger": {"name": "history.jsonl", "sha256": "1" * 64},
            "nodes": [
                _node(
                    "history-case",
                    "Case",
                    "Historic case",
                    1,
                    {"current_state": "close", "status": "closed"},
                    "reconstructed",
                ),
                _node("history-run", "Run", "Historic run", 2, {}, "reconstructed"),
                _node("other-run", "Run", "Other historic run", 3, {}, "reconstructed"),
                _node(
                    "history-call",
                    "ToolCall",
                    "Collect historical log",
                    4,
                    {"runtime_managed": True, "status": "completed", "reuse_key": "collect-log"},
                    "reconstructed",
                ),
                _node(
                    "other-call",
                    "ToolCall",
                    "Collect other historical log",
                    5,
                    {"runtime_managed": True, "status": "completed", "reuse_key": "collect-log"},
                    "reconstructed",
                ),
                _node("receipt", "VerificationReceipt", "Receipt", 6, {"status": "verified"}, "reconstructed"),
                _node(
                    "derived-receipt",
                    "VerificationReceipt",
                    "Derived receipt",
                    7,
                    {"data_origin": "derived"},
                    "reconstructed",
                ),
            ],
            "edges": [
                _edge("history-has-run", "has_run", "history-case", "history-run", 8),
                _edge("other-has-run", "has_run", "history-case", "other-run", 9),
                _edge("history-contains", "contains", "history-run", "history-call", 10),
                _edge("history-receipt-contains", "contains", "history-run", "receipt", 11),
                _edge("other-contains", "contains", "other-run", "other-call", 12),
                _edge("other-receipt-contains", "contains", "other-run", "derived-receipt", 13),
                _edge("history-receipt", "verified_by", "history-case", "receipt", 14),
                _edge("other-receipt", "verified_by", "history-case", "derived-receipt", 15),
            ],
        }

        advice = build_graph_runtime_advice(
            current, run_id="run", history_graphs=[history]
        )
        matches = {
            match["history_run_id"]: match
            for match in advice["historical_reuse"]["matches"]
        }
        verified_match = matches["history-run"]
        self.assertEqual("verified_success_path", verified_match["qualification"])
        self.assertEqual("advisory_only_non_live_history", verified_match["reuse_mode"])
        self.assertEqual("reconstructed-evidence", verified_match["provenance"]["actualness"])
        self.assertEqual("historical_subgraph", matches["other-run"]["qualification"])
        for receipt_status in (None, "failed", "blocked", "invalid"):
            with self.subTest(receipt_status=receipt_status):
                receipt = next(node for node in history["nodes"] if node["id"] == "receipt")
                receipt["attrs"] = {} if receipt_status is None else {"status": receipt_status}
                unverified = build_graph_runtime_advice(current, run_id="run", history_graphs=[history])
                match = next(item for item in unverified["historical_reuse"]["matches"]
                             if item["history_run_id"] == "history-run")
                self.assertEqual("historical_subgraph", match["qualification"])

    def test_path_review_compares_derived_recommendation_with_later_ledger_records(self) -> None:
        events = copy.deepcopy(load_events(QUICKSTART))
        recommendation = {
            "schema_version": "0.1.0",
            "event_id": "evt-recommendation",
            "case_id": "DEMO-001",
            "run_id": "run:DEMO-001:001",
            "sequence": 32,
            "occurred_at": "2026-01-01T00:00:32Z",
            "kind": "node.recorded",
            "actor": {"type": "agent", "id": "runtime"},
            "provenance": {"capture_mode": "live", "source_refs": ["ledger-sha256:test"]},
            "node": {
                "id": "decision:recommendation",
                "type": "Decision",
                "label": "Recommendation",
                "attrs": {
                    "record_kind": RECOMMENDATION_RECORD_KIND,
                    "data_origin": "derived",
                    "recommended_node_ids": ["action:DEMO-001:select"],
                    "source_ledger_sha256": "2" * 64,
                },
            },
        }
        actual = copy.deepcopy(
            next(
                event
                for event in events
                if event["kind"] == "node.recorded"
                and event["node"]["id"] == "action:DEMO-001:select"
            )
        )
        actual.update(
            {
                "event_id": "evt-action-completed",
                "sequence": 33,
                "occurred_at": "2026-01-01T00:00:33Z",
            }
        )
        actual["node"]["attrs"]["status"] = "completed"
        review = build_path_review(project_events(events), events + [recommendation, actual])
        comparison = review["comparisons"][0]
        self.assertEqual("aligned", comparison["status"])
        self.assertEqual("derived", comparison["recommended"]["data_origin"])
        self.assertEqual("recorded_ledger_events", comparison["actual"]["data_origin"])
        self.assertEqual(["action:DEMO-001:select"], comparison["comparison"]["matched_node_ids"])

    def test_path_review_ignores_non_runtime_and_derived_records(self) -> None:
        events = copy.deepcopy(load_events(QUICKSTART))
        recommendation = {
            "schema_version": "0.1.0",
            "event_id": "evt-recommendation-filter",
            "case_id": "DEMO-001",
            "run_id": "run:DEMO-001:001",
            "sequence": 32,
            "occurred_at": "2026-01-01T00:00:32Z",
            "kind": "node.recorded",
            "actor": {"type": "agent", "id": "runtime"},
            "provenance": {"capture_mode": "live", "source_refs": ["ledger-sha256:test"]},
            "node": {
                "id": "decision:recommendation-filter",
                "type": "Decision",
                "label": "Recommendation filter",
                "attrs": {
                    "record_kind": RECOMMENDATION_RECORD_KIND,
                    "data_origin": "derived",
                    "recommended_node_ids": ["tool:planned", "tool:derived"],
                    "source_ledger_sha256": "3" * 64,
                },
            },
        }
        template = copy.deepcopy(
            next(
                event
                for event in events
                if event["kind"] == "node.recorded"
                and event["node"]["id"] == "action:DEMO-001:select"
            )
        )
        planned = copy.deepcopy(template)
        planned.update({"event_id": "evt-planned", "sequence": 33, "occurred_at": "2026-01-01T00:00:33Z"})
        planned["node"].update(
            {
                "id": "tool:planned",
                "type": "ToolCall",
                "label": "Only planned",
                "attrs": {"status": "pending", "runtime_managed": False},
            }
        )
        derived = copy.deepcopy(planned)
        derived.update({"event_id": "evt-derived", "sequence": 34, "occurred_at": "2026-01-01T00:00:34Z"})
        derived["node"].update(
            {
                "id": "tool:derived",
                "label": "Derived snapshot",
                "attrs": {
                    "status": "completed",
                    "runtime_managed": True,
                    "data_origin": "derived",
                },
            }
        )
        review = build_path_review(project_events(events), events + [recommendation, planned, derived])
        comparison = review["comparisons"][0]
        self.assertEqual("awaiting_recorded_actual_path", comparison["status"])
        self.assertEqual([], comparison["actual"]["node_ids"])

    def test_recommendation_cli_records_derived_snapshot_then_replays_recorded_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "events.jsonl"
            events = copy.deepcopy(load_events(QUICKSTART))
            next(
                event
                for event in events
                if event["kind"] == "node.recorded"
                and event["node"]["id"] == "action:DEMO-001:select"
            )["node"]["attrs"]["status"] = "pending"
            write_new_ledger(ledger, events, force=True)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "record-recommendation",
                            "--ledger",
                            str(ledger),
                            "--run-id",
                            "run:DEMO-001:001",
                        ]
                    ),
                )
            recommendation = load_events(ledger)[-1]
            self.assertEqual("Decision", recommendation["node"]["type"])
            self.assertEqual("derived", recommendation["node"]["attrs"]["data_origin"])
            self.assertEqual(
                ["action:DEMO-001:select"],
                recommendation["node"]["attrs"]["recommended_node_ids"],
            )
            for status in ("running", "completed"):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        0,
                        main(
                            [
                                "step-status",
                                "--ledger",
                                str(ledger),
                                "--node-id",
                                "action:DEMO-001:select",
                                "--status",
                                status,
                                "--reason",
                                "runtime test",
                            ]
                        ),
                    )
            review_output = io.StringIO()
            with redirect_stdout(review_output):
                self.assertEqual(0, main(["review-paths", str(ledger)]))
            review = json.loads(review_output.getvalue())
            self.assertEqual("aligned", review["comparisons"][0]["status"])
            self.assertEqual(
                ["action:DEMO-001:select"],
                review["comparisons"][0]["actual"]["node_ids"],
            )

    def test_claim_status_cli_refuses_then_records_a_confirmed_claim_after_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "events.jsonl"
            base_events = load_events(QUICKSTART)
            write_new_ledger(ledger, base_events, force=True)
            append_event(
                ledger,
                case_id="DEMO-001",
                kind="node.recorded",
                actor_type="agent",
                actor_id="test",
                capture_mode="live",
                source_refs=["test"],
                run_id="run:DEMO-001:001",
                payload={
                    "node": {
                        "id": "claim:gate-test",
                        "type": "Claim",
                        "label": "Gate test",
                        "attrs": {"status": "pending"},
                    }
                },
            )
            with redirect_stderr(io.StringIO()):
                self.assertEqual(
                    2,
                    main(
                        [
                            "claim-status",
                            "--ledger",
                            str(ledger),
                            "--claim-id",
                            "claim:gate-test",
                            "--status",
                            "confirmed",
                        ]
                    ),
                )
            append_event(
                ledger,
                case_id="DEMO-001",
                kind="node.recorded",
                actor_type="tool",
                actor_id="test",
                capture_mode="live",
                source_refs=["test"],
                run_id="run:DEMO-001:001",
                payload={
                    "node": {
                        "id": "observation:gate-test",
                        "type": "Observation",
                        "label": "Observed proof",
                        "attrs": {"status": "confirmed"},
                    }
                },
            )
            append_event(
                ledger,
                case_id="DEMO-001",
                kind="edge.recorded",
                actor_type="agent",
                actor_id="test",
                capture_mode="live",
                source_refs=["test"],
                run_id="run:DEMO-001:001",
                payload={
                    "edge": {
                        "id": "edge:gate-test:supports",
                        "type": "supports",
                        "from": "observation:gate-test",
                        "to": "claim:gate-test",
                        "attrs": {},
                    }
                },
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    0,
                    main(
                        [
                            "claim-status",
                            "--ledger",
                            str(ledger),
                            "--claim-id",
                            "claim:gate-test",
                            "--status",
                            "confirmed",
                        ]
                    ),
                )
            last = load_events(ledger)[-1]
            self.assertEqual("confirmed", last["node"]["attrs"]["status"])
            self.assertTrue(last["node"]["attrs"]["runtime_claim_gate"]["not_native_telemetry"])
            self.assertEqual("run:DEMO-001:001", last["run_id"])
            event_count = len(load_events(ledger))
            with redirect_stderr(io.StringIO()):
                self.assertEqual(
                    2,
                    main(
                        [
                            "claim-status",
                            "--ledger",
                            str(ledger),
                            "--claim-id",
                            "claim:gate-test",
                            "--status",
                            "confirmed",
                            "--run-id",
                            "run:missing",
                        ]
                    ),
                )
            self.assertEqual(event_count, len(load_events(ledger)))

    def test_approval_scope_uses_exact_tokens_not_substring_matches(self) -> None:
        graph = {
            "root_id": "case",
            "nodes": [
                _node("case", "Case", "Case", 1, {"current_state": "execute"}),
                _node("run", "Run", "Run", 2, {"capture_mode": "live"}),
                _node(
                    "action",
                    "Action",
                    "Mutate target",
                    3,
                    {
                        "runtime_managed": True,
                        "status": "pending",
                        "mutating": True,
                        "authorized_scope": "target",
                    },
                ),
                _node("target", "Target", "Target", 4),
                _node("approval", "Approval", "Other target approval", 5, {"status": "granted", "scope": "target-other"}),
            ],
            "edges": [
                _edge("has-run", "has_run", "case", "run", 6),
                _edge("contains", "contains", "run", "action", 7),
                _edge("targets", "targets", "action", "target", 8),
                _edge("approved", "approved_by", "action", "approval", 9),
            ],
        }
        blocked = build_runtime_snapshot(graph, run_id="run")["blocked"][0]
        self.assertIn(
            "approval_not_granted_or_scope_mismatch",
            {item["code"] for item in blocked["blockers"]},
        )


if __name__ == "__main__":
    unittest.main()
