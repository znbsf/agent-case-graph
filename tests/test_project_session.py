from __future__ import annotations

import copy
import hashlib
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from agent_case_graph.cli import _initial_case_events, main
from agent_case_graph.ledger import append_event, append_events, canonical_json, read_ledger_snapshot, write_new_ledger
from agent_case_graph.model import ACGError
from agent_case_graph.project_profile import inspect_project, workspace_path
from agent_case_graph.project_session import record_project_plan, review_project_plan, run_plan_check
from agent_case_graph.projector import project_events
from tests.test_project_planning import RepositoryFixture


class ProjectSessionTests(RepositoryFixture):
    def setUp(self) -> None:
        super().setUp()
        self.ledger_ref = ".artifacts/session/events.jsonl"
        self.ledger = self.root / self.ledger_ref
        write_new_ledger(self.ledger, _initial_case_events(
            case_id="project-trial", title="Actual checks in a synthetic source fixture", run_id="run:trial",
            capture_mode="live", actor_type="agent", actor_id="test", source_refs=["test:project-session"],
        ))

    def record(self, proposal: dict | None = None, plan_id: str = "plan:v1", **kwargs) -> dict:
        return record_project_plan(self.root, proposal or self.plan(), self.ledger_ref, plan_id=plan_id, run_id="run:trial", **kwargs)

    def check(self, code: str = "print('actual result')", **kwargs) -> dict:
        options = {"plan_id": "plan:v1", "task_id": "core-change", "criterion": 1, "command": [sys.executable, "-c", code]}
        options.update(kwargs)
        return run_plan_check(self.root, self.ledger_ref, **options)

    def review(self, plan_id: str = "plan:v1") -> dict:
        return review_project_plan(self.root, self.ledger_ref, plan_id=plan_id)

    def append_observation(self) -> None:
        append_event(self.ledger, case_id="project-trial", kind="node.recorded", actor_type="tool", actor_id="test",
                     capture_mode="live", source_refs=["test:concurrent"], run_id="run:trial",
                     payload={"node": {"id": "concurrent", "type": "Observation", "label": "Concurrent record", "attrs": {}}})

    def test_changed_untracked_commonjs_checker_expires_its_passing_receipt(self) -> None:
        self.write("prototype-check.cjs", "console.log('passed');\n")
        proposal = self.plan()
        proposal["tasks"][0]["source_refs"] = ["file:prototype-check.cjs"]
        self.record(proposal)
        result = self.check(command=["node", "prototype-check.cjs"])
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(self.review()["status"], "checks_passed")
        status = self.git("status", "--porcelain=v1")
        self.write("prototype-check.cjs", "throw new Error('source changed after the check');\n")
        self.assertEqual(status, self.git("status", "--porcelain=v1"))
        latest = self.review()
        self.assertEqual(latest["status"], "needs_followup")
        self.assertEqual(latest["tasks"][0]["criteria"][0]["status"], "stale_evidence")

    def test_recorded_plan_is_a_proposal_and_never_runtime_ready(self) -> None:
        before = self.git("status", "--porcelain=v1")
        result = self.record()
        self.assertEqual(result["status"], "proposal_recorded")
        self.assertFalse(result["execution_authorized"])
        events, _ = read_ledger_snapshot(self.ledger)
        graph = project_events(events)
        action = next(node for node in graph["nodes"] if node["type"] == "Action")
        self.assertFalse(action["attrs"]["runtime_managed"])
        self.assertEqual(action["attrs"]["status"], "proposed")
        self.assertEqual(graph["runtime_advice"]["recommendations"], [])
        self.assertEqual(before, self.git("status", "--porcelain=v1"))
        self.assertEqual(self.review()["tasks"][0]["criteria"][0]["status"], "missing_evidence")

    def test_actual_check_is_hashed_linked_and_separate_from_acceptance(self) -> None:
        self.record()
        checked = self.check()
        self.assertEqual(checked["exit_code"], 0)
        raw = (self.root / checked["receipt_path"]).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), checked["receipt_sha256"])
        receipt = json.loads(raw)
        log = (self.root / receipt["log"]["path"]).read_bytes()
        self.assertIn(b"actual result", log)
        self.assertEqual(hashlib.sha256(log).hexdigest(), receipt["log"]["sha256"])
        before = self.ledger.read_bytes()
        review = self.review()
        self.assertEqual(review["status"], "checks_passed")
        self.assertFalse(review["acceptance_assessed"])
        self.assertFalse(review["execution_authorized"])
        self.assertEqual(before, self.ledger.read_bytes())
        events, _ = read_ledger_snapshot(self.ledger)
        graph = project_events(events)
        criterion = next(node for node in graph["nodes"] if node["type"] == "AcceptanceCriterion")
        self.assertEqual(criterion["attrs"]["status"], "pending")
        self.assertTrue(any(edge["type"] == "verified_by" and edge["to"] == checked["receipt_node_id"] for edge in graph["edges"]))

    def test_latest_failure_replaces_earlier_success(self) -> None:
        self.record()
        self.check()
        failed = self.check("raise SystemExit(7)")
        self.assertEqual(failed["exit_code"], 7)
        latest = self.review()["tasks"][0]["criteria"][0]
        self.assertEqual(latest["status"], "check_failed")
        self.assertEqual(latest["receipt_node_id"], failed["receipt_node_id"])

    def test_disconnected_receipt_does_not_count(self) -> None:
        self.record()
        self.check()
        events, _ = read_ledger_snapshot(self.ledger)
        remaining = [event for event in events if not (event["kind"] == "edge.recorded" and event["edge"]["type"] == "verified_by")]
        for sequence, event in enumerate(remaining, start=1):
            event["sequence"] = sequence
        write_new_ledger(self.ledger, remaining, force=True)
        criterion = self.review()["tasks"][0]["criteria"][0]
        self.assertEqual(criterion["status"], "invalid_evidence")
        self.assertEqual(criterion["reason"], "missing_plan_evidence_relationship")

    def test_changed_source_expires_evidence_even_with_same_git_status(self) -> None:
        self.record()
        self.write("pkg/core.py", "value = 2\n")
        self.check()
        status = self.git("status", "--porcelain=v1")
        self.write("pkg/core.py", "value = 3\n")
        self.assertEqual(status, self.git("status", "--porcelain=v1"))
        review = self.review()
        self.assertEqual(review["tasks"][0]["criteria"][0]["status"], "stale_evidence")
        self.assertTrue(review["repository_changed_since_proposal"])

    def test_command_that_edits_repository_cannot_verify_its_own_changes(self) -> None:
        self.record()
        checked = self.check("from pathlib import Path; Path('pkg/core.py').write_text('value = 2\\n')")
        self.assertTrue(checked["repository_changed_during_check"])
        evidence = self.review()["tasks"][0]["criteria"][0]
        self.assertEqual(evidence["status"], "stale_evidence")
        self.assertEqual(evidence["reason"], "repository_changed_during_check")

    def test_modified_output_and_receipt_are_rejected(self) -> None:
        self.record()
        checked = self.check()
        receipt_path = self.root / checked["receipt_path"]
        receipt = json.loads(receipt_path.read_text())
        (self.root / receipt["log"]["path"]).write_bytes(b"modified")
        self.assertEqual(self.review()["tasks"][0]["criteria"][0]["reason"], "output_hash_mismatch")
        receipt_path.write_text("{}", encoding="utf-8")
        self.assertEqual(self.review()["tasks"][0]["criteria"][0]["reason"], "receipt_hash_mismatch")

    def test_all_criteria_need_checks_and_dependency_gaps_propagate(self) -> None:
        proposal = self.plan()
        proposal["tasks"][0]["acceptance_criteria"].append("An independently checked condition")
        dependent = copy.deepcopy(proposal["tasks"][0])
        dependent.update(id="dependent", depends_on=["core-change"], acceptance_criteria=["Dependent check"])
        proposal["tasks"].insert(0, dependent)
        self.record(proposal)
        self.check(task_id="dependent")
        self.check()
        dependent_row, core = self.review()["tasks"]
        self.assertEqual(core["criteria"][1]["status"], "missing_evidence")
        self.assertEqual(dependent_row["dependencies_needing_followup"], ["core-change"])
        self.check(criterion=2)
        self.assertEqual(self.review()["status"], "checks_passed")

    def test_revision_has_explicit_lineage_and_does_not_inherit_checks(self) -> None:
        self.record()
        checked = self.check()
        self.write("pkg/core.py", "value = 2\n")
        result = self.record(self.plan(), plan_id="plan:v2", supersedes="plan:v1", evidence_refs=[checked["receipt_node_id"]])
        self.assertEqual(result["supersedes"], "plan:v1")
        events, _ = read_ledger_snapshot(self.ledger)
        self.assertTrue(any(event["kind"] == "edge.recorded" and event["edge"]["type"] == "informs"
                            and event["edge"]["from"] == checked["receipt_node_id"] and event["edge"]["to"] == "plan:v2" for event in events))
        self.assertEqual(self.review()["superseded_by"], ["plan:v2"])
        self.assertEqual(self.review("plan:v2")["tasks"][0]["criteria"][0]["status"], "missing_evidence")
        with self.assertRaisesRegex(ACGError, "superseded"):
            self.check()
        with self.assertRaisesRegex(ACGError, "active project plan"):
            self.record(self.plan(), plan_id="plan:v3", supersedes="plan:v1")

    def test_revision_refuses_foreign_or_modified_evidence_and_same_run_contamination(self) -> None:
        self.record()
        checked = self.check()
        before = self.ledger.read_bytes()
        for refs in ([checked["receipt_node_id"]], ["unrelated-receipt"], [checked["receipt_node_id"], checked["receipt_node_id"]]):
            options = {} if refs == [checked["receipt_node_id"]] else {"supersedes": "plan:v1"}
            with self.assertRaises(ACGError):
                self.record(plan_id="plan:v2", evidence_refs=refs, **options)
        self.assertEqual(before, self.ledger.read_bytes())
        (self.root / checked["receipt_path"]).write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ACGError, "intact linked receipt"):
            self.record(plan_id="plan:v2", supersedes="plan:v1", evidence_refs=[checked["receipt_node_id"]])
        events, _ = read_ledger_snapshot(self.ledger)
        events[2]["provenance"]["capture_mode"] = "reconstructed"
        write_new_ledger(self.ledger, events, force=True)
        with self.assertRaisesRegex(ACGError, "live Run"):
            self.check()

    def test_event_batch_preserves_exact_prefix_and_enforces_actual_byte_limit(self) -> None:
        # Formatting contributes to the real limit even when canonical events
        # would fit; a failed transaction must leave the prefix untouched.
        data = self.ledger.read_bytes().replace(b'"schema_version":', b'"schema_version":       ')
        self.ledger.write_bytes(data.rstrip(b"\n"))
        events, digest = read_ledger_snapshot(self.ledger)
        prefix = self.ledger.read_bytes()
        options = dict(case_id="project-trial", records=[{"kind": "node.recorded", "node": {
            "id": "extra", "type": "Observation", "label": "Extra observation"}}], actor_type="agent", actor_id="test",
                       capture_mode="live", source_refs=[], run_id="run:trial", expected_sequence=len(events), expected_sha256=digest)
        with self.assertRaisesRegex(ACGError, "byte limit"):
            append_events(self.ledger, **options, maximum_bytes=len(prefix))
        self.assertEqual(prefix, self.ledger.read_bytes())
        append_events(self.ledger, **options)
        self.assertTrue(self.ledger.read_bytes().startswith(prefix + b"\n"))
        self.assertEqual(len(read_ledger_snapshot(self.ledger)[0]), len(events) + 1)

    def test_stale_plan_duplicate_ids_and_non_live_runs_do_not_append(self) -> None:
        proposal = self.plan()
        self.write("pkg/core.py", "value = 2\n")
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(ACGError, "invalid proposal"):
            self.record(proposal)
        self.assertEqual(before, self.ledger.read_bytes())
        self.record()
        before = self.ledger.read_bytes()
        with self.assertRaisesRegex(ACGError, "identifiers already exist"):
            self.record()
        self.assertEqual(before, self.ledger.read_bytes())
        events, _ = read_ledger_snapshot(self.ledger)
        events[2]["provenance"]["capture_mode"] = "synthetic"
        write_new_ledger(self.ledger, events, force=True)
        with self.assertRaisesRegex(ACGError, "live Run"):
            self.record(plan_id="plan:v2")

    def test_batch_validation_is_all_or_nothing(self) -> None:
        events, digest = read_ledger_snapshot(self.ledger)
        before = self.ledger.read_bytes()
        with self.assertRaises(ACGError):
            append_events(self.ledger, case_id="project-trial", records=[
                {"kind": "node.recorded", "node": {"id": "test", "type": "Plan", "label": "Valid first record"}},
                {"kind": "node.recorded", "node": {"id": "bad", "type": "Invalid", "label": "Invalid final record"}},
            ], actor_type="agent", actor_id="test", capture_mode="live", source_refs=[], run_id="run:trial",
                          expected_sequence=len(events), expected_sha256=digest)
        self.assertEqual(before, self.ledger.read_bytes())
        self.assertFalse(self.ledger.with_suffix(".jsonl.lock").exists())

    def test_concurrent_replacement_before_record_is_rejected_atomically(self) -> None:
        from agent_case_graph import project_session

        original = project_session._append
        def change_then_append(path, events, digest, *args):
            changed = copy.deepcopy(events)
            changed[1]["node"]["label"] = "Changed while validation ran"
            write_new_ledger(path, changed, force=True)
            return original(path, events, digest, *args)
        with patch.object(project_session, "_append", side_effect=change_then_append):
            with self.assertRaisesRegex(ACGError, "ledger changed"):
                self.record()
        events, _ = read_ledger_snapshot(self.ledger)
        self.assertEqual(len(events), 4)
        self.assertEqual(events[1]["node"]["label"], "Changed while validation ran")

    def test_concurrent_edit_after_command_keeps_receipt_without_replaying(self) -> None:
        from agent_case_graph import project_session

        self.record()
        original = project_session._capture
        def run_then_change(*args):
            result = original(*args)
            self.append_observation()
            return result
        with patch.object(project_session, "_capture", side_effect=run_then_change) as capture:
            with self.assertRaisesRegex(ACGError, "command finished; receipt preserved"):
                self.check()
            self.assertEqual(capture.call_count, 1)
        self.assertEqual(len(list((self.root / ".artifacts/project-checks").glob("*/receipt.json"))), 1)
        self.assertEqual(self.review()["tasks"][0]["criteria"][0]["status"], "missing_evidence")

    def test_timeout_output_limit_and_launch_error_are_not_success(self) -> None:
        self.record()
        self.assertEqual(self.check("import time; time.sleep(3)", timeout_seconds=1)["outcome"], "timeout")
        with patch("agent_case_graph.project_session.MAX_OUTPUT_BYTES", 128):
            result = self.check("print('x' * 2048)")
            receipt = json.loads((self.root / result["receipt_path"]).read_text())
            self.assertEqual(result["outcome"], "output_limit")
            self.assertEqual(receipt["log"]["captured_bytes"], 128)
            self.assertTrue(receipt["log"]["truncated"])
        self.assertEqual(self.check(command=[str(self.root / "missing-executable")])["outcome"], "launch_error")
        self.assertEqual(self.review()["tasks"][0]["criteria"][0]["status"], "check_failed")

    def test_unsafe_or_unignored_paths_and_invalid_criteria_do_not_execute(self) -> None:
        self.record()
        with patch("agent_case_graph.project_session._capture") as capture:
            for options in ({"criterion": 0}, {"command": []}, {"timeout_seconds": 0},
                            {"evidence_dir": "tracked-logs"}, {"evidence_dir": ".artifacts/secrets/logs"}):
                with self.assertRaises(ACGError):
                    self.check(**options)
            capture.assert_not_called()
        with self.assertRaises(ACGError):
            review_project_plan(self.root, "../outside.jsonl", plan_id="plan:v1")
        with self.assertRaises(ACGError):
            workspace_path(self.root, ".artifacts/session/events.jsonl")
        with self.assertRaises(ACGError):
            workspace_path(self.root, ".artifacts/.git/config", allow_artifacts=True)

    def test_cli_records_checks_and_reviews_without_a_shell(self) -> None:
        path = self.write(".artifacts/proposal.json", json.dumps(self.plan()))
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["record-project-plan", str(self.root), str(path), "--ledger", self.ledger_ref,
                                   "--plan-id", "plan:v1", "--run-id", "run:trial"]), 0)
            self.assertEqual(main(["run-plan-check", str(self.root), "--ledger", self.ledger_ref, "--plan-id", "plan:v1",
                                   "--task-id", "core-change", "--criterion", "1", "--command", sys.executable,
                                   "-c", "import sys; print(sys.argv[1])", "; literal shell syntax"]), 0)
            self.assertEqual(main(["review-project-plan", str(self.root), "--ledger", self.ledger_ref, "--plan-id", "plan:v1"]), 0)
        log = next((self.root / ".artifacts/project-checks").glob("*/output.log")).read_text()
        self.assertIn("; literal shell syntax", log)
        self.assertIn('"checks_passed"', out.getvalue())

    def test_malformed_historical_proposal_is_an_actionable_error(self) -> None:
        self.record()
        events, _ = read_ledger_snapshot(self.ledger)
        attrs = next(event["node"]["attrs"] for event in events if event["kind"] == "node.recorded" and event["node"]["id"] == "plan:v1")
        attrs["proposal"]["tasks"] = [{}]
        attrs["proposal_sha256"] = hashlib.sha256(canonical_json(attrs["proposal"]).encode("utf-8")).hexdigest()
        write_new_ledger(self.ledger, events, force=True)
        with self.assertRaisesRegex(ACGError, "malformed"):
            self.review()


if __name__ == "__main__":
    unittest.main()
