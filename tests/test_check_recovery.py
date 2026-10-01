from __future__ import annotations

import hashlib
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from agent_case_graph import check_recovery, cli, project_session
from agent_case_graph.cli import _initial_case_events
from agent_case_graph.ledger import append_event, canonical_json, read_ledger_snapshot, write_new_ledger
from agent_case_graph.model import ACGError
from tests.test_project_planning import RepositoryFixture


class CheckRecoveryTests(RepositoryFixture):
    def setUp(self):
        super().setUp()
        self.ledger_ref = ".artifacts/session/events.jsonl"
        self.ledger = self.root / self.ledger_ref
        write_new_ledger(self.ledger, _initial_case_events(case_id="recovery-fixture", title="Synthetic recovery trial",
            run_id="run:recovery", capture_mode="live", actor_type="agent", actor_id="test", source_refs=["test:recovery"]))
        project_session.record_project_plan(self.root, self.plan(), self.ledger_ref, plan_id="plan:v1", run_id="run:recovery")

    def append_observation(self):
        append_event(self.ledger, case_id="recovery-fixture", kind="node.recorded", actor_type="tool", actor_id="test",
            capture_mode="live", source_refs=["test:concurrent"], run_id="run:recovery",
            payload={"node": {"id": "concurrent", "type": "Observation", "label": "Synthetic concurrent record", "attrs": {}}})

    def orphan(self, code=None):
        capture = project_session._capture
        before = set((self.root / ".artifacts/project-checks").glob("*/receipt.json"))
        code = code or "from pathlib import Path; p=Path('.artifacts/execution-count.txt'); p.write_text((p.read_text() if p.exists() else '')+'run\\n'); print('observed once')"

        def capture_then_edit(*args):
            result = capture(*args)
            self.append_observation()
            return result

        with patch.object(project_session, "_capture", side_effect=capture_then_edit) as called:
            with self.assertRaisesRegex(ACGError, "command finished; receipt preserved") as error:
                project_session.run_plan_check(self.root, self.ledger_ref, plan_id="plan:v1", task_id="core-change",
                    criterion=1, command=[sys.executable, "-c", code])
            self.assertEqual(called.call_count, 1)
        created = set((self.root / ".artifacts/project-checks").glob("*/receipt.json")) - before
        self.assertEqual(len(created), 1)
        receipt = created.pop()
        return receipt.relative_to(self.root).as_posix(), hashlib.sha256(receipt.read_bytes()).hexdigest(), str(error.exception)

    def call_cli(self, receipt, digest, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = cli.main(["recover-plan-check", str(self.root), "--ledger", self.ledger_ref,
                    "--plan-id", "plan:v1", "--receipt", receipt, "--receipt-sha256", digest, *extra])
            except SystemExit as error:
                code = error.code
        return code, stdout.getvalue(), stderr.getvalue()

    def recover(self, receipt, digest, **kwargs):
        return check_recovery.recover_plan_check(self.root, self.ledger_ref, plan_id="plan:v1",
            receipt_path=receipt, receipt_sha256=digest, **kwargs)

    def repin(self, receipt, mutate):
        path = self.root / receipt
        value = json.loads(path.read_bytes())
        mutate(value)
        path.write_text(canonical_json(value) + "\n", encoding="utf-8")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def refused(self, receipt, digest, reason):
        before = self.ledger.read_bytes()
        with patch.object(project_session, "_capture", side_effect=AssertionError("recovery executed a command")):
            code, stdout, stderr = self.call_cli(receipt, digest)
        self.assertEqual(code, 2, stderr)
        self.assertEqual(stdout, "")
        self.assertIn(reason, stderr)
        self.assertEqual(self.ledger.read_bytes(), before)

    def run_check(self, code="print('check')"):
        return project_session.run_plan_check(self.root, self.ledger_ref, plan_id="plan:v1", task_id="core-change",
            criterion=1, command=[sys.executable, "-c", code])

    def test_cli_recovers_orphan_and_repeated_recovery_never_reexecutes(self):
        receipt, digest, error = self.orphan()
        self.assertEqual(project_session.review_project_plan(self.root, self.ledger_ref, plan_id="plan:v1")
                         ["tasks"][0]["criteria"][0]["status"], "missing_evidence")
        with patch.object(project_session, "_capture", side_effect=AssertionError("recovery executed a command")):
            code, stdout, stderr = self.call_cli(receipt, digest)
            self.assertEqual(code, 0, stderr)
            result = json.loads(stdout)
            self.assertEqual(result["status"], "check_recovered")
            self.assertFalse(result["command_executed"])
            self.assertIn(digest, error)
            after = self.ledger.read_bytes()
            code, stdout, stderr = self.call_cli(receipt, digest)
            self.assertEqual(code, 0, stderr)
            self.assertEqual(json.loads(stdout)["status"], "already_recorded")
            self.assertEqual(self.ledger.read_bytes(), after)
        review = project_session.review_project_plan(self.root, self.ledger_ref, plan_id="plan:v1")
        self.assertEqual(review["status"], "checks_passed")
        self.assertFalse(review["execution_authorized"])
        self.assertFalse(review["acceptance_assessed"])
        self.assertEqual((self.root / ".artifacts/execution-count.txt").read_text(), "run\n")

    def test_dry_run_validates_without_appending_or_executing(self):
        receipt, digest, _ = self.orphan()
        before = self.ledger.read_bytes()
        code, stdout, stderr = self.call_cli(receipt, digest, "--dry-run")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["status"], "recovery_ready")
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual((self.root / ".artifacts/execution-count.txt").read_text(), "run\n")

    def test_originally_linked_check_is_an_idempotent_noop(self):
        result = self.run_check()
        before = self.ledger.read_bytes()
        self.assertEqual(self.recover(result["receipt_path"], result["receipt_sha256"])["status"], "already_recorded")
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_original_digest_is_not_recomputed_after_receipt_write(self):
        writer = project_session.atomic_write_text
        original = []

        def replace_after_write(path, content):
            original.append(hashlib.sha256(content.encode("utf-8")).hexdigest())
            writer(path, content)
            path.write_bytes(b"{}\n")

        with patch.object(project_session, "atomic_write_text", side_effect=replace_after_write):
            receipt, changed_digest, error = self.orphan()
        self.assertNotEqual(changed_digest, original[0])
        self.assertIn("receipt_sha256=" + original[0], error)
        self.refused(receipt, original[0], "original SHA-256")

    def test_wrong_digest_and_modified_receipt_are_refused(self):
        receipt, digest, _ = self.orphan()
        for bad in ("0" * 64, "bad", digest.upper()):
            with self.subTest(digest=bad):
                self.refused(receipt, bad, "SHA-256")
        self.repin(receipt, lambda value: value.update(outcome="failed", exit_code=1))
        self.refused(receipt, digest, "original SHA-256")

    def test_modified_output_is_refused(self):
        receipt, digest, _ = self.orphan()
        log = json.loads((self.root / receipt).read_bytes())["log"]["path"]
        (self.root / log).write_bytes(b"altered output")
        self.refused(receipt, digest, "output differs")

    def test_actual_receipt_and_output_must_be_untracked_ignored_paths(self):
        receipt, digest, _ = self.orphan()
        directory = receipt.rsplit("/", 1)[0]
        original = (self.root / ".gitignore").read_bytes()
        for exception in (receipt, directory + "/output.log"):
            with self.subTest(exception=exception):
                self.write(".gitignore", ".artifacts/*\n!.artifacts/project-checks/\n.artifacts/project-checks/*\n!"
                    + directory + "/\n" + directory + "/*\n!" + exception + "\n")
                self.refused(receipt, digest, "ignored .artifacts receipt.json")
        (self.root / ".gitignore").write_bytes(original)
        self.git("add", "-f", "--", receipt)
        self.refused(receipt, digest, "ignored .artifacts receipt.json")

    def test_legacy_orphan_requires_manual_review(self):
        receipt, _, _ = self.orphan()
        digest = self.repin(receipt, lambda value: value.pop("recovery"))
        self.refused(receipt, digest, "legacy orphan")

    def test_legacy_linked_receipt_still_reviews_as_passing(self):
        result = self.run_check()
        digest = self.repin(result["receipt_path"], lambda value: value.pop("recovery"))
        events, _ = read_ledger_snapshot(self.ledger)
        node = next(event["node"] for event in events if event["kind"] == "node.recorded"
                    and event["node"]["id"] == result["receipt_node_id"])
        node["attrs"]["sha256"] = digest
        write_new_ledger(self.ledger, events, force=True)
        self.assertEqual(project_session.review_project_plan(self.root, self.ledger_ref, plan_id="plan:v1")["status"], "checks_passed")
        self.refused(result["receipt_path"], digest, "legacy orphan")

    def test_repinned_cross_context_and_malformed_contracts_are_refused(self):
        receipt, _, _ = self.orphan()
        original = (self.root / receipt).read_bytes()
        changes = [
            (lambda r: r["recovery"].update(case_id="foreign"), "different Case"),
            (lambda r: r["recovery"].update(run_id="foreign"), "different Case"),
            (lambda r: r["recovery"].update(ledger=".artifacts/other.jsonl"), "different Case"),
            (lambda r: r.update(plan_id="plan:foreign"), "different Case"),
            (lambda r: r["recovery"].update(proposal_sha256="0" * 64), "different Case"),
            (lambda r: r.update(task_id="absent"), "task and criterion"),
            (lambda r: r.update(criterion_index=True), "task and criterion"),
            (lambda r: r.update(command=[""], cwd="../"), "command contract"),
            (lambda r: r.update(finished_at="invalid"), "timestamps"),
            (lambda r: r.update(outcome="passed", exit_code=2), "exit code disagree"),
            (lambda r: r["log"].update(truncated=True), "output contract"),
            (lambda r: r["recovery"].update(ledger_sequence=True), "recovery binding"),
        ]
        for mutate, reason in changes:
            with self.subTest(reason=reason):
                (self.root / receipt).write_bytes(original)
                self.refused(receipt, self.repin(receipt, mutate), reason)

    def test_malformed_json_and_incomplete_byte_anchor_are_controlled_errors(self):
        receipt, _, _ = self.orphan()
        path = self.root / receipt
        original = path.read_bytes()
        path.write_bytes(b"[" * 20000 + b"0" + b"]" * 20000)
        self.refused(receipt, hashlib.sha256(path.read_bytes()).hexdigest(), "bounded UTF-8 JSON")
        path.write_bytes(original)
        prefix = self.ledger.read_bytes()[:20]
        digest = self.repin(receipt, lambda r: r["recovery"].update(
            ledger_bytes=len(prefix), ledger_sha256=hashlib.sha256(prefix).hexdigest()))
        self.refused(receipt, digest, "complete UTF-8 JSONL")

    def test_rewritten_ledger_prefix_is_refused(self):
        receipt, digest, _ = self.orphan()
        self.ledger.write_bytes(self.ledger.read_bytes().replace(b'Synthetic recovery trial', b'Changed recovery trial'))
        self.refused(receipt, digest, "original byte prefix")

    def test_superseded_plan_cannot_recover_into_old_revision(self):
        receipt, digest, _ = self.orphan()
        project_session.record_project_plan(self.root, self.plan(), self.ledger_ref,
            plan_id="plan:v2", run_id="run:recovery", supersedes="plan:v1")
        self.refused(receipt, digest, "superseded")

    def test_failed_and_stale_receipts_are_restored_without_becoming_success(self):
        receipt, digest, _ = self.orphan("import sys; print('failed'); sys.exit(7)")
        result = self.recover(receipt, digest)
        self.assertEqual(result["evidence_status"], "check_failed")
        self.assertFalse(result["acceptance_assessed"])
        self.assertEqual(project_session.review_project_plan(self.root, self.ledger_ref, plan_id="plan:v1")["status"], "needs_followup")
        # This fresh passing check becomes orphaned, then a source edit expires it.
        receipt, digest, _ = self.orphan()
        self.write("pkg/core.py", "value = 2\n")
        self.assertEqual(self.recover(receipt, digest)["evidence_status"], "stale_evidence")
        self.assertEqual(project_session.review_project_plan(self.root, self.ledger_ref, plan_id="plan:v1")["status"], "needs_followup")

    def test_newer_failure_blocks_older_success_even_after_identity_update(self):
        receipt, digest, _ = self.orphan()
        newer = self.run_check("import sys; sys.exit(3)")
        self.refused(receipt, digest, "newer or competing")
        append_event(self.ledger, case_id="recovery-fixture", kind="node.recorded", actor_type="tool", actor_id="test",
            capture_mode="live", source_refs=["test:rewrite-identity"], run_id="run:recovery",
            payload={"node": {"id": newer["receipt_node_id"], "type": "VerificationReceipt", "label": "Updated identity",
                              "attrs": {"task_id": "another-task"}}})
        self.refused(receipt, digest, "newer or competing")

    def test_update_to_preexisting_receipt_after_check_blocks_recovery(self):
        earlier = self.run_check("import sys; sys.exit(1)")
        receipt, digest, _ = self.orphan()
        append_event(self.ledger, case_id="recovery-fixture", kind="node.recorded", actor_type="tool", actor_id="test",
            capture_mode="live", source_refs=["test:update-earlier"], run_id="run:recovery",
            payload={"node": {"id": earlier["receipt_node_id"], "type": "VerificationReceipt", "label": "Updated earlier result",
                              "attrs": {"status": "failed"}}})
        self.refused(receipt, digest, "newer or competing")

    def test_split_identity_updates_cannot_hide_new_invalid_evidence(self):
        receipt, digest, _ = self.orphan()
        options = dict(case_id="recovery-fixture", kind="node.recorded", actor_type="tool", actor_id="test",
            capture_mode="live", source_refs=["test:split-identity"], run_id="run:recovery")
        append_event(self.ledger, **options, payload={"node": {"id": "split-receipt", "type": "VerificationReceipt",
            "label": "Partial identity", "attrs": {"plan_id": "plan:v1", "task_id": "core-change",
                                                      "project_check_version": project_session.CHECK_VERSION}}})
        append_event(self.ledger, **options, payload={"node": {"id": "split-receipt", "type": "VerificationReceipt",
            "label": "Completed identity", "attrs": {"criterion_index": 1}}})
        review = project_session.review_project_plan(self.root, self.ledger_ref, plan_id="plan:v1")
        self.assertEqual(review["tasks"][0]["criteria"][0]["status"], "invalid_evidence")
        self.refused(receipt, digest, "newer or competing")
        append_event(self.ledger, **options, payload={"node": {"id": "split-receipt", "type": "VerificationReceipt",
            "label": "Changed identity again", "attrs": {"task_id": "another-task"}}})
        self.refused(receipt, digest, "newer or competing")

    def test_noop_rejects_conflicting_ownership_relationships(self):
        receipt, digest, _ = self.orphan()
        self.recover(receipt, digest)
        check_id = json.loads((self.root / receipt).read_bytes())["recovery"]["check_id"]
        before = self.ledger.read_bytes()
        conflicts = [("checks", check_id + ":receipt", "plan:v1:task:core-change"),
                     ("contains", "plan:v1", check_id),
                     ("invokes", "run:recovery", check_id),
                     ("produces", check_id, "plan:v1"),
                     ("verified_by", "plan:v1", check_id + ":receipt")]
        for kind, source, target in conflicts:
            with self.subTest(kind=kind):
                self.ledger.write_bytes(before)
                append_event(self.ledger, case_id="recovery-fixture", kind="edge.recorded", actor_type="tool", actor_id="test",
                    capture_mode="live", source_refs=["test:conflict"], run_id="run:recovery",
                    payload={"edge": {"id": "conflicting-edge", "type": kind, "from": source, "to": target, "attrs": {}}})
                self.refused(receipt, digest, "incomplete or conflicting relationships")

    def test_noop_rejects_wrong_run_provenance_in_nodes_and_edges(self):
        receipt, digest, _ = self.orphan()
        self.recover(receipt, digest)
        check_id = json.loads((self.root / receipt).read_bytes())["recovery"]["check_id"]
        before = self.ledger.read_bytes()
        for kind in ("node.recorded", "edge.recorded"):
            with self.subTest(kind=kind):
                self.ledger.write_bytes(before)
                events, _ = read_ledger_snapshot(self.ledger)
                event = next(e for e in events if e["kind"] == kind and (
                    (kind == "node.recorded" and e["node"]["id"] == check_id)
                    or (kind == "edge.recorded" and e["edge"]["to"] == check_id)))
                event["run_id"] = "run:foreign"
                write_new_ledger(self.ledger, events, force=True)
                self.refused(receipt, digest, "incomplete or conflicting")

    def test_noop_after_newer_failure_keeps_latest_failure_and_bytes(self):
        receipt, digest, _ = self.orphan()
        self.recover(receipt, digest)
        self.run_check("import sys; sys.exit(4)")
        before = self.ledger.read_bytes()
        self.assertEqual(self.recover(receipt, digest)["status"], "already_recorded")
        self.assertEqual(before, self.ledger.read_bytes())
        self.assertEqual(project_session.review_project_plan(self.root, self.ledger_ref, plan_id="plan:v1")["status"], "needs_followup")

    def test_partial_existing_identity_or_relationships_refuse_append(self):
        receipt, digest, _ = self.orphan()
        self.recover(receipt, digest)
        events, _ = read_ledger_snapshot(self.ledger)
        missing_edge = next(event for event in events if event["kind"] == "edge.recorded" and event["edge"]["type"] == "checks")
        events.remove(missing_edge)
        for sequence, event in enumerate(events, 1):
            event["sequence"] = sequence
        write_new_ledger(self.ledger, events, force=True)
        self.refused(receipt, digest, "incomplete or conflicting relationships")

    def test_locked_revalidation_refuses_output_tampering(self):
        receipt, digest, _ = self.orphan()
        log = json.loads((self.root / receipt).read_bytes())["log"]["path"]
        append = check_recovery._append

        def tamper_then_append(*args, **kwargs):
            (self.root / log).write_bytes(b"changed")
            return append(*args, **kwargs)

        with patch.object(check_recovery, "_append", side_effect=tamper_then_append):
            self.refused(receipt, digest, "output differs")

    def test_locked_revalidation_refuses_repository_edit(self):
        receipt, digest, _ = self.orphan()
        append = check_recovery._append

        def edit_then_append(*args, **kwargs):
            self.write("pkg/core.py", "value = 9\n")
            return append(*args, **kwargs)

        with patch.object(check_recovery, "_append", side_effect=edit_then_append):
            self.refused(receipt, digest, "repository changed")

    def test_concurrent_append_is_kept_without_partial_recovery(self):
        receipt, digest, _ = self.orphan()
        append = check_recovery._append

        def edit_then_append(*args, **kwargs):
            self.append_observation()
            return append(*args, **kwargs)

        before_events, _ = read_ledger_snapshot(self.ledger)
        with patch.object(check_recovery, "_append", side_effect=edit_then_append):
            with self.assertRaises(ACGError):
                self.recover(receipt, digest)
        after_events, _ = read_ledger_snapshot(self.ledger)
        self.assertEqual(len(after_events), len(before_events) + 1)
        self.assertFalse(any(e.get("node", {}).get("type") == "VerificationReceipt" for e in after_events))

    def test_unignored_ledger_lock_is_refused_without_writing(self):
        receipt, _, _ = self.orphan()
        # Keep .artifacts ignored except this ledger lock, exposing the race.
        self.write(".gitignore", ".artifacts/*\n!.artifacts/session/\n.artifacts/session/*\n!.artifacts/session/events.jsonl.lock\n")
        digest = hashlib.sha256((self.root / receipt).read_bytes()).hexdigest()
        self.refused(receipt, digest, "ignored .artifacts ledger and lock")
