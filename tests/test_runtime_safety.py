from __future__ import annotations

import copy
import hashlib
import io
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_case_graph import cli
from agent_case_graph.graph_runtime import build_claim_gate
from agent_case_graph.ledger import append_event, read_ledger_snapshot, write_new_ledger
from agent_case_graph.lint import lint_graph
from agent_case_graph.model import ACGError, load_events
from agent_case_graph.runtime import build_runtime_snapshot, validate_step_transition
from tests.test_graph_runtime import _current_graph, _edge, _node


def mutation_graph(node_type: str = "ToolCall") -> dict:
    graph = _current_graph()
    call = next(node for node in graph["nodes"] if node["id"] == "call")
    call["type"] = node_type
    call["attrs"].update({"mutating": True, "authorized_scope": "repo"})
    graph["nodes"].extend([
        _node("approval", "Approval", "Synthetic approval", 14, {"status": "granted", "scope": "repo"}),
        _node("target", "Target", "Synthetic file", 15, {"path": "repo/example.txt"}),
    ])
    graph["edges"].extend([
        _edge("call-approval", "approved_by", "call", "approval", 16),
        _edge("call-target", "targets", "call", "target", 17),
    ])
    graph["state_history"] = []
    return graph


def ledger_events(graph: dict) -> list[dict]:
    definitions = [("graph.declared", {"graph": {
        "id": graph["graph_id"], "type": "case", "root_id": graph["root_id"],
    }})]
    for node in graph["nodes"]:
        definitions.append(("node.recorded", {"node": {
            key: copy.deepcopy(node[key]) for key in ("id", "type", "label", "attrs")
        }}))
    for edge in graph["edges"]:
        definitions.append(("edge.recorded", {"edge": {
            key: copy.deepcopy(edge[key]) for key in ("id", "type", "from", "to", "attrs")
        }}))
    return [{
        "schema_version": "0.1.0", "event_id": f"evt-safety-{sequence}",
        "case_id": "SAFETY-TEST", "run_id": "run", "sequence": sequence,
        "occurred_at": "2026-01-01T00:00:00Z", "kind": kind,
        "actor": {"type": "tool", "id": "synthetic-test"},
        "provenance": {"capture_mode": "synthetic", "source_refs": ["test:runtime-safety"]},
        **payload,
    } for sequence, (kind, payload) in enumerate(definitions, 1)]


class RuntimeSafetyTests(unittest.TestCase):
    def test_all_mutating_executable_types_share_gates(self):
        for node_type in ("Action", "ToolCall", "Step", "Verification"):
            with self.subTest(node_type=node_type):
                graph = mutation_graph(node_type)
                self.assertEqual([], lint_graph(graph))
                self.assertEqual(["call"], build_runtime_snapshot(graph, run_id="run")["next_action_ids"])
                graph["edges"] = [edge for edge in graph["edges"] if edge["type"] != "approved_by"]
                self.assertIn("ACG011", {item["code"] for item in lint_graph(graph)})
                snapshot = build_runtime_snapshot(graph, run_id="run")
                self.assertEqual([], snapshot["next_action_ids"])
                self.assertIn("approval_missing", {item["code"] for item in snapshot["blocked"][0]["blockers"]})
                with self.assertRaises(ACGError):
                    validate_step_transition(graph, node_id="call", to_status="running", run_id="run")

    def test_wrong_approval_and_target_types_do_not_grant_readiness(self):
        for node_id, expected_code in (("approval", "approval_missing"), ("target", "target_missing")):
            with self.subTest(node_id=node_id):
                graph = mutation_graph()
                next(node for node in graph["nodes"] if node["id"] == node_id)["type"] = "Observation"
                snapshot = build_runtime_snapshot(graph, run_id="run")
                self.assertEqual([], snapshot["next_action_ids"])
                self.assertIn(expected_code, {item["code"] for item in snapshot["blocked"][0]["blockers"]})
                if node_id == "approval":
                    self.assertIn("ACG023", {item["code"] for item in lint_graph(graph)})

    def test_mutation_requires_explicit_live_run(self):
        for mode in (None, "", "synthetic", "reconstructed", "invalid"):
            with self.subTest(mode=mode):
                graph = mutation_graph()
                run = next(node for node in graph["nodes"] if node["id"] == "run")
                if mode is None:
                    del run["attrs"]["capture_mode"]
                else:
                    run["attrs"]["capture_mode"] = mode
                snapshot = build_runtime_snapshot(graph, run_id="run")
                self.assertEqual([], snapshot["next_action_ids"])
                self.assertIn("non_live_mutation", {item["code"] for item in snapshot["blocked"][0]["blockers"]})

    def test_claim_requires_explicit_type_appropriate_complete_status(self):
        accepted = {
            "Artifact": "captured", "EnvironmentSnapshot": "recorded",
            "Observation": "confirmed", "ToolOutput": "completed",
            "Verification": "passed", "VerificationReceipt": "verified",
            "AcceptanceCriterion": "satisfied",
        }
        for node_type, complete in accepted.items():
            for status in (complete, None, "", "blocked", "skipped", "invalid", "pending", "failed"):
                with self.subTest(node_type=node_type, status=status):
                    graph = _current_graph()
                    output = next(node for node in graph["nodes"] if node["id"] == "output")
                    output["type"] = node_type
                    output["attrs"] = {} if status is None else {"status": status}
                    gate = build_claim_gate(graph, "claim", run_id="run")
                    self.assertEqual(status == complete, gate["can_confirm"])

    def test_support_threshold_counts_distinct_evidence(self):
        graph = _current_graph()
        next(node for node in graph["nodes"] if node["id"] == "output")["attrs"]["status"] = "completed"
        next(node for node in graph["nodes"] if node["id"] == "claim")["attrs"]["minimum_support_count"] = 2
        graph["edges"].append(_edge("duplicate-support", "supports", "output", "claim", 20))
        gate = build_claim_gate(graph, "claim", run_id="run")
        self.assertFalse(gate["can_confirm"])
        shortage = next(item for item in gate["missing_evidence"] if item["code"] == "insufficient_support_count")
        self.assertEqual(1, shortage["available"])

    def test_context_preserves_task_and_references_without_raw_payloads(self):
        graph = mutation_graph()
        call = next(node for node in graph["nodes"] if node["id"] == "call")
        call["attrs"].update({"input_ref": "artifact:request", "raw_payload": "omitted input"})
        output = next(node for node in graph["nodes"] if node["id"] == "output")
        output["attrs"].update({"source_uri": "artifact:result", "sha256": "a" * 64, "raw_output": "omitted log"})
        packet = build_runtime_snapshot(graph, run_id="run")["ready"][0]["context"]
        self.assertEqual("artifact:request", packet["task"]["references"]["input_ref"])
        context = {node["id"]: node for node in packet["nodes"]}
        self.assertEqual("repo/example.txt", context["target"]["references"]["path"])
        self.assertEqual("a" * 64, context["output"]["references"]["sha256"])
        self.assertIn("test:output", context["output"]["source_refs"])
        self.assertEqual(len(context) + 1, packet["selected_node_count"])
        self.assertEqual("node_count", packet["measurement_basis"])
        self.assertNotIn("omitted", json.dumps(packet))


class LedgerConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / "events.jsonl"
        self.events = ledger_events(mutation_graph())
        write_new_ledger(self.ledger, self.events)

    def append_node(self, node: dict, **extra):
        return append_event(
            self.ledger, case_id="SAFETY-TEST", kind="node.recorded",
            actor_type="tool", actor_id="synthetic-test", capture_mode="synthetic",
            source_refs=["test:runtime-safety"], run_id="run", payload={"node": node}, **extra,
        )

    def test_snapshot_hash_matches_exact_source_bytes(self):
        events, digest = read_ledger_snapshot(self.ledger)
        self.assertEqual(self.events, events)
        self.assertEqual(hashlib.sha256(self.ledger.read_bytes()).hexdigest(), digest)
        # A same-length replacement is stale too, even when its event count matches.
        changed = copy.deepcopy(events)
        changed[1]["node"]["label"] = "A different source"
        write_new_ledger(self.ledger, changed, force=True)
        with self.assertRaisesRegex(ACGError, "ledger changed"):
            self.append_node(changed[1]["node"], expected_sequence=len(events), expected_sha256=digest)
        self.assertEqual(changed, load_events(self.ledger))

    def test_simultaneous_start_records_only_one_checkpoint(self):
        barrier = threading.Barrier(2)
        original = cli.validate_step_transition

        def validate_together(*args, **kwargs):
            result = original(*args, **kwargs)
            barrier.wait(timeout=10)
            return result

        args = ["step-status", "--ledger", str(self.ledger), "--node-id", "call",
                "--run-id", "run", "--status", "running", "--reason", "Synthetic race"]
        with patch.object(cli, "validate_step_transition", side_effect=validate_together), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(cli.main, args) for _ in range(2)]
                codes = [future.result(timeout=15) for future in futures]
        self.assertEqual([0, 2], sorted(codes))
        events = load_events(self.ledger)
        self.assertEqual(len(self.events) + 1, len(events))
        attrs = events[-1]["node"]["attrs"]
        self.assertEqual(f"checkpoint:call:{events[-1]['sequence']}", attrs["runtime_checkpoint_id"])
        self.assertEqual(1, attrs["attempt"])

    def test_revoked_approval_between_validation_and_append_rejects_start(self):
        original = cli.append_event

        def revoke_then_append(*args, **kwargs):
            self.append_node({"id": "approval", "type": "Approval", "label": "Revoked",
                              "attrs": {"status": "revoked"}})
            return original(*args, **kwargs)

        with patch.object(cli, "append_event", side_effect=revoke_then_append), redirect_stderr(io.StringIO()):
            result = cli.main(["step-status", "--ledger", str(self.ledger), "--node-id", "call",
                               "--status", "running", "--reason", "Synthetic revocation"])
        self.assertEqual(2, result)
        events = load_events(self.ledger)
        self.assertEqual(len(self.events) + 1, len(events))
        self.assertEqual("approval", events[-1]["node"]["id"])

    def test_synthetic_checkpoint_keeps_synthetic_provenance(self):
        graph = mutation_graph()
        next(node for node in graph["nodes"] if node["id"] == "run")["attrs"]["capture_mode"] = "synthetic"
        next(node for node in graph["nodes"] if node["id"] == "call")["attrs"]["mutating"] = False
        write_new_ledger(self.ledger, ledger_events(graph), force=True)
        with redirect_stdout(io.StringIO()):
            code = cli.main(["step-status", "--ledger", str(self.ledger), "--node-id", "call",
                             "--status", "running", "--reason", "Synthetic checkpoint"])
        self.assertEqual(0, code)
        self.assertEqual("synthetic", load_events(self.ledger)[-1]["provenance"]["capture_mode"])

    def test_claim_and_recommendation_reject_changed_evidence(self):
        for command in ("claim-status", "record-recommendation"):
            with self.subTest(command=command):
                graph = mutation_graph()
                next(node for node in graph["nodes"] if node["id"] == "output")["attrs"]["status"] = "completed"
                initial = ledger_events(graph)
                write_new_ledger(self.ledger, initial, force=True)
                original = cli.append_event

                def invalidate_then_append(*args, **kwargs):
                    self.append_node({"id": "output", "type": "ToolOutput", "label": "Incomplete",
                                      "attrs": {"status": "blocked"}})
                    return original(*args, **kwargs)

                args = [command, "--ledger", str(self.ledger), "--run-id", "run"]
                if command == "claim-status":
                    args += ["--claim-id", "claim", "--status", "confirmed"]
                with patch.object(cli, "append_event", side_effect=invalidate_then_append), redirect_stderr(io.StringIO()):
                    self.assertEqual(2, cli.main(args))
                events = load_events(self.ledger)
                self.assertEqual(len(initial) + 1, len(events))
                self.assertEqual("output", events[-1]["node"]["id"])

    def test_payload_cannot_override_sequence_or_provenance(self):
        with self.assertRaisesRegex(ACGError, "payload"):
            append_event(self.ledger, case_id="SAFETY-TEST", kind="node.recorded",
                         actor_type="tool", actor_id="test", capture_mode="synthetic",
                         source_refs=[], payload={"node": self.events[1]["node"], "sequence": 1})
        self.assertEqual(self.events, load_events(self.ledger))


if __name__ == "__main__":
    unittest.main()
