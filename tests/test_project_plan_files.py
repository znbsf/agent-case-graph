from __future__ import annotations

import io
import json
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_case_graph.cli import MAX_PLAN_FILE_BYTES, _initial_case_events, main
from agent_case_graph.ledger import write_new_ledger
from tests.test_project_planning import RepositoryFixture


class ProjectPlanFileTests(RepositoryFixture):
    def setUp(self) -> None:
        super().setUp()
        self.ledger_ref = ".artifacts/plan-files/events.jsonl"
        self.ledger = self.root / self.ledger_ref
        write_new_ledger(self.ledger, _initial_case_events(
            case_id="plan-files", title="Synthetic plan file boundary checks", run_id="run:files",
            capture_mode="live", actor_type="agent", actor_id="test", source_refs=["test:plan-files"],
        ))

    def cli(self, command: str, path: Path, plan_id: str = "plan:input") -> tuple[int, str, str]:
        argv = [command, str(self.root), str(path)]
        if command == "record-project-plan":
            argv += ["--ledger", self.ledger_ref, "--plan-id", plan_id, "--run-id", "run:files"]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def plan_bytes(self, *, bom: bool = False) -> bytes:
        proposal = self.plan()
        proposal["goal"] = "核对 UTF-8 plan input 😀"
        data = json.dumps(proposal, ensure_ascii=False).encode("utf-8")
        return (b"\xef\xbb\xbf" if bom else b"") + data

    def test_utf8_with_and_without_bom_can_check_and_record(self) -> None:
        for index, bom in enumerate((False, True)):
            with self.subTest(bom=bom):
                path = self.write(f".artifacts/input-{index}.json", "")
                path.write_bytes(self.plan_bytes(bom=bom))
                code, stdout, stderr = self.cli("check-plan", path)
                self.assertEqual((code, stderr), (0, ""))
                self.assertTrue(json.loads(stdout)["valid"])
                code, stdout, stderr = self.cli("record-project-plan", path, f"plan:input-{index}")
                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(json.loads(stdout)["status"], "proposal_recorded")

    def test_exact_byte_limit_including_bom_and_unicode_is_accepted(self) -> None:
        for index, bom in enumerate((False, True)):
            with self.subTest(bom=bom):
                data = self.plan_bytes(bom=bom)
                path = self.write(f".artifacts/boundary-{index}.json", "")
                path.write_bytes(data + b" " * (MAX_PLAN_FILE_BYTES - len(data)))
                self.assertEqual(path.stat().st_size, MAX_PLAN_FILE_BYTES)
                for command in ("check-plan", "record-project-plan"):
                    code, _, stderr = self.cli(command, path, f"plan:boundary-{index}")
                    self.assertEqual((code, stderr), (0, ""))

    def test_one_byte_over_limit_is_rejected_before_inspection_or_append(self) -> None:
        data = self.plan_bytes(bom=True)
        path = self.write(".artifacts/oversized.json", "")
        path.write_bytes(data + b" " * (MAX_PLAN_FILE_BYTES + 1 - len(data)))
        before = self.ledger.read_bytes()
        with patch("agent_case_graph.cli.check_plan") as check, patch("agent_case_graph.cli.record_project_plan") as record:
            for command in ("check-plan", "record-project-plan"):
                code, stdout, stderr = self.cli(command, path)
                self.assertEqual((code, stdout), (2, ""))
                self.assertIn("4000000 byte input limit", stderr)
                self.assertNotIn("Traceback", stderr)
            check.assert_not_called()
            record.assert_not_called()
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_bad_encoding_or_json_is_rejected_without_ledger_changes(self) -> None:
        inputs = (b"\xff", "{}".encode("utf-16"), b"{broken}", b"", b"\xef\xbb\xbf\xef\xbb\xbf{}")
        before = self.ledger.read_bytes()
        for index, data in enumerate(inputs):
            with self.subTest(data=data):
                path = self.write(f".artifacts/malformed-{index}.json", "")
                path.write_bytes(data)
                for command in ("check-plan", "record-project-plan"):
                    code, stdout, stderr = self.cli(command, path)
                    self.assertEqual((code, stdout), (2, ""))
                    self.assertIn("readable UTF-8 JSON", stderr)
                    self.assertNotIn("Traceback", stderr)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_bom_does_not_bypass_snapshot_source_or_dependency_checks(self) -> None:
        proposals = []
        stale = self.plan()
        stale["source_snapshot_sha256"] = "0" * 64
        proposals.append(stale)
        missing = self.plan()
        missing["tasks"][0]["source_refs"] = ["file:missing.py"]
        proposals.append(missing)
        cycle = self.plan()
        cycle["tasks"][0]["depends_on"] = ["core-change"]
        proposals.append(cycle)
        before = self.ledger.read_bytes()
        for index, proposal in enumerate(proposals):
            with self.subTest(index=index):
                path = self.write(f".artifacts/invalid-{index}.json", "")
                path.write_bytes(b"\xef\xbb\xbf" + json.dumps(proposal).encode("utf-8"))
                code, stdout, _ = self.cli("check-plan", path)
                self.assertEqual(code, 1)
                self.assertFalse(json.loads(stdout)["valid"])
                self.assertEqual(self.cli("record-project-plan", path)[0], 2)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_non_object_json_keeps_structural_rejection(self) -> None:
        path = self.write(".artifacts/list-plan.json", "[]")
        before = self.ledger.read_bytes()
        code, stdout, _ = self.cli("check-plan", path)
        self.assertEqual(code, 1)
        self.assertIn("plan_must_be_an_object", {row["code"] for row in json.loads(stdout)["errors"]})
        self.assertEqual(self.cli("record-project-plan", path)[0], 2)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_operator_selected_external_plan_file_is_supported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="acg-external-plan-") as external:
            path = Path(external) / "plan.json"
            path.write_bytes(self.plan_bytes(bom=True))
            self.assertFalse(path.is_relative_to(self.root))
            self.assertEqual(self.cli("check-plan", path)[0], 0)
            self.assertEqual(self.cli("record-project-plan", path)[0], 0)

    def test_missing_file_keeps_normal_error(self) -> None:
        path = self.root / ".artifacts/absent.json"
        before = self.ledger.read_bytes()
        for command in ("check-plan", "record-project-plan"):
            code, stdout, stderr = self.cli(command, path)
            self.assertEqual((code, stdout), (2, ""))
            self.assertIn("readable UTF-8 JSON", stderr)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_null_path_keeps_normal_error_for_python_callers(self) -> None:
        before = self.ledger.read_bytes()
        for command in ("check-plan", "record-project-plan"):
            code, stdout, stderr = self.cli(command, Path("\x00"))
            self.assertEqual((code, stdout), (2, ""))
            self.assertIn("readable UTF-8 JSON", stderr)
            self.assertNotIn("Traceback", stderr)
        self.assertEqual(self.ledger.read_bytes(), before)
