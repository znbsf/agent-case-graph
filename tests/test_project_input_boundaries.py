from __future__ import annotations

import hashlib
import io
from contextlib import redirect_stderr

from agent_case_graph.cli import main
from agent_case_graph.model import ACGError, parse_events
from agent_case_graph.planning import check_plan, prepare_plan
from agent_case_graph.project_profile import inspect_project, workspace_path
from agent_case_graph.project_session import _receipt_status
from tests.test_project_planning import RepositoryFixture

DEEP_JSON = "[" * 20000 + "0" + "]" * 20000


class ProjectInputBoundaryTests(RepositoryFixture):
    def test_windows_aliases_cannot_bypass_sensitive_or_workspace_paths(self):
        self.write("secrets/token.py", "SYNTHETIC_SECRET")
        self.write("credentials.json", "{}")
        for value in ("secrets./token.py", "secrets /token.py", "credentials.json.", "credentials.json ", "pkg./core.py", "pkg /core.py"):
            with self.subTest(value=value), self.assertRaisesRegex(ACGError, "dot or space"):
                workspace_path(self.root, value, must_exist=True)
        proposal = self.plan()
        proposal["tasks"][0]["target_paths"] = ["secrets./token.py"]
        self.assertIn("unsafe_target_path", {row["code"] for row in check_plan(self.root, proposal)["errors"]})
        self.assertNotIn("SYNTHETIC_SECRET", str(inspect_project(self.root)))

    def test_deep_manifest_is_a_visible_parse_gap(self):
        self.write("package.json", DEEP_JSON)
        packet = prepare_plan(self.root, "Inspect packages")
        manifest = next(row for row in packet["profile"]["manifests"] if row["path"] == "package.json")
        self.assertFalse(manifest["parsed"])
        self.assertIn("package.json", packet["suggested_evidence_checks"][0]["parse_gap_paths"])

    def test_deep_receipt_is_invalid_evidence(self):
        path = self.write(".artifacts/receipt.json", DEEP_JSON)
        node = {"id": "receipt:deep", "attrs": {"source_path": ".artifacts/receipt.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                "provenance": {"capture_modes": ["live"]}, "event_ids": ["event:one"]}
        result = _receipt_status(self.root, node, "0" * 64)
        self.assertEqual(result["status"], "invalid_evidence")
        self.assertIn("recursion", result["reason"])

    def test_deep_ledger_and_cli_plan_fail_without_tracebacks(self):
        with self.assertRaisesRegex(ACGError, "line 1: invalid JSON"):
            parse_events(DEEP_JSON)
        path = self.write(".artifacts/deep-plan.json", DEEP_JSON)
        output = io.StringIO()
        with redirect_stderr(output):
            self.assertEqual(main(["check-plan", str(self.root), str(path)]), 2)
        self.assertIn("readable UTF-8 JSON", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())
        output = io.StringIO()
        with redirect_stderr(output):
            self.assertEqual(main(["record-project-plan", str(self.root), str(path), "--ledger", ".artifacts/absent.jsonl",
                                   "--plan-id", "plan:deep", "--run-id", "run:deep"]), 2)
        self.assertIn("readable UTF-8 JSON", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())
