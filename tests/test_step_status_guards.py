from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_case_graph import cli
from agent_case_graph.ledger import append_event, write_new_ledger
from agent_case_graph.model import load_events
from tests.project_runtime_fixtures import ledger_events, mutation_graph


class StepStatusGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / "events.jsonl"

    def write_fixture(self, *, capture_mode="live", mutating=True):
        graph = mutation_graph("Step")
        next(node for node in graph["nodes"] if node["id"] == "run")["attrs"]["capture_mode"] = capture_mode
        next(node for node in graph["nodes"] if node["id"] == "call")["attrs"]["mutating"] = mutating
        events = ledger_events(graph)
        for event in events:
            event["provenance"]["capture_mode"] = capture_mode if isinstance(capture_mode, str) and capture_mode in {
                "live", "synthetic", "reconstructed"
            } else "synthetic"
        write_new_ledger(self.ledger, events, force=True)

    def checkpoint(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(["step-status", "--ledger", str(self.ledger), "--node-id", "call",
                             "--run-id", "run", "--status", "running", "--reason", "Synthetic regression"])
        return code, stdout.getvalue(), stderr.getvalue()

    def append_node(self, node_id, node_type, attrs):
        return append_event(self.ledger, case_id="SYNTHETIC-PROJECT", kind="node.recorded",
            actor_type="agent", actor_id="synthetic-other-writer", capture_mode="live",
            source_refs=["test:concurrent-writer"], run_id="run",
            payload={"node": {"id": node_id, "type": node_type, "label": "Synthetic " + node_id, "attrs": attrs}})

    def revoke_approval(self, *, rewrite=False):
        if rewrite:
            events = load_events(self.ledger)
            next(event["node"] for event in events if event.get("node", {}).get("id") == "approval")["attrs"]["status"] = "revoked"
            write_new_ledger(self.ledger, events, force=True)
        else:
            self.append_node("approval", "Approval", {"status": "revoked"})

    def assert_stale_checkpoint_refused(self, result, changed_bytes):
        code, stdout, stderr = result
        self.assertEqual(code, 2, (stdout, stderr))
        self.assertEqual(stdout, "")
        self.assertIn("ledger changed after validation", stderr)
        self.assertEqual(self.ledger.read_bytes(), changed_bytes)
        events = load_events(self.ledger)
        self.assertFalse(any(event.get("node", {}).get("attrs", {}).get("runtime_checkpoint_id") for event in events))

    def test_checkpoint_preserves_selected_run_capture_mode(self):
        for mode in ("live", "synthetic", "reconstructed"):
            with self.subTest(mode=mode):
                self.write_fixture(capture_mode=mode, mutating=False)
                code, stdout, stderr = self.checkpoint()
                self.assertEqual(code, 0, stderr)
                checkpoint = load_events(self.ledger)[-1]
                self.assertEqual(checkpoint["provenance"]["capture_mode"], mode)
                self.assertEqual(checkpoint["run_id"], "run")
                self.assertEqual(json.loads(stdout)["counts"]["running"], 1)

    def test_checkpoint_refuses_missing_or_invalid_run_capture_mode(self):
        for mode in (None, "unknown", ["live"]):
            with self.subTest(mode=mode):
                self.write_fixture(capture_mode=mode, mutating=False)
                original = self.ledger.read_bytes()
                code, stdout, stderr = self.checkpoint()
                self.assertEqual(code, 2, (stdout, stderr))
                self.assertEqual(stdout, "")
                self.assertIn("capture_mode", stderr)
                self.assertEqual(self.ledger.read_bytes(), original)

    def test_checkpoint_refuses_approval_revoked_after_validation_by_append(self):
        self.write_fixture()
        validate = cli.validate_step_transition
        changed = []

        def revoke_after_validation(*args, **kwargs):
            result = validate(*args, **kwargs)
            self.revoke_approval()
            changed.append(self.ledger.read_bytes())
            return result

        with patch.object(cli, "validate_step_transition", side_effect=revoke_after_validation):
            result = self.checkpoint()
        self.assert_stale_checkpoint_refused(result, changed[0])

    def test_checkpoint_refuses_same_length_approval_rewrite_after_validation(self):
        self.write_fixture()
        validate = cli.validate_step_transition
        initial_length = len(load_events(self.ledger))
        changed = []

        def rewrite_after_validation(*args, **kwargs):
            result = validate(*args, **kwargs)
            self.revoke_approval(rewrite=True)
            changed.append(self.ledger.read_bytes())
            return result

        with patch.object(cli, "validate_step_transition", side_effect=rewrite_after_validation):
            result = self.checkpoint()
        self.assert_stale_checkpoint_refused(result, changed[0])
        self.assertEqual(len(load_events(self.ledger)), initial_length)

    def test_checkpoint_binds_digest_to_events_loaded_before_projection(self):
        self.write_fixture()
        project = cli.project_events
        changed = []

        def rewrite_before_projection(*args, **kwargs):
            if not changed:
                self.revoke_approval(rewrite=True)
                changed.append(self.ledger.read_bytes())
            return project(*args, **kwargs)

        with patch.object(cli, "project_events", side_effect=rewrite_before_projection):
            result = self.checkpoint()
        self.assert_stale_checkpoint_refused(result, changed[0])

    def test_checkpoint_response_describes_own_committed_event_despite_later_writer(self):
        self.write_fixture()

        def append_then_complete(*args, **kwargs):
            checkpoint = append_event(*args, **kwargs)
            self.append_node("call", "Step", {"status": "completed"})
            return checkpoint

        with patch.object(cli, "append_event", side_effect=append_then_complete):
            code, stdout, stderr = self.checkpoint()
        self.assertEqual(code, 0, stderr)
        response = json.loads(stdout)
        self.assertEqual(response["checkpoint"]["to"], "running")
        self.assertEqual(response["counts"]["running"], 1)
        self.assertEqual(response["counts"]["completed"], 0)
        self.assertEqual(load_events(self.ledger)[-1]["node"]["attrs"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
