from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent_case_graph.cli import main
from agent_case_graph.model import ACGError
from agent_case_graph.planning import PLAN_VERSION, check_plan, prepare_plan, runtime_advice
from agent_case_graph.project_profile import inspect_project, workspace_path


class RepositoryFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="acg-project-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.git("init", "-q")
        self.write(".gitignore", ".artifacts/\nignored.py\n")
        self.write("pyproject.toml", '[project]\nname = "sample"\ndescription = "Fixture"\ndependencies = []\n[project.scripts]\nsample = "pkg.cli:main"\n')
        self.write("README.md", "# Sample\n\nA synthetic repository.\n\n```sh\npython -m unittest discover -s tests\n```\n")
        self.write("pkg/__init__.py", "")
        self.write("pkg/cli.py", "from . import core\nfrom .core import work\n\ndef main():\n    return work()\n")
        self.write("pkg/core.py", "def work():\n    return 1\n")
        self.write("tests/test_core.py", "from pkg.core import work\n")
        self.git("add", ".")
        self.git("-c", "user.name=ACG Test", "-c", "user.email=acg-test@example.invalid", "commit", "-qm", "Synthetic fixture")

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def git(self, *args: str) -> str:
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, check=True)
        return result.stdout.decode("utf-8")

    def plan(self) -> dict:
        return {
            "version": PLAN_VERSION,
            "source_snapshot_sha256": inspect_project(self.root)["snapshot_sha256"],
            "goal": "Improve core behavior",
            "tasks": [{
                "id": "core-change", "title": "Improve core behavior",
                "source_refs": ["file:pkg/core.py"], "target_paths": ["pkg/core.py", "tests/test_new_behavior.py"],
                "depends_on": [], "acceptance_criteria": ["The new behavior has an observed verification result."],
            }],
        }


class ProjectProfileTests(RepositoryFixture):
    def test_commonjs_and_esm_check_sources_can_be_cited_without_execution(self) -> None:
        self.write("prototype-check.cjs", "throw new Error('inspection must not execute this');\n")
        self.write("tools/browser-check.mjs", "throw new Error('inspection must not execute this');\n")
        profile = inspect_project(self.root)
        self.assertEqual(profile["languages"]["JavaScript"], 2)
        refs = {row["id"] for row in profile["sources"]}
        self.assertIn("file:prototype-check.cjs", refs)
        self.assertIn("file:tools/browser-check.mjs", refs)
        proposal = self.plan()
        proposal["tasks"][0]["source_refs"] = ["file:prototype-check.cjs", "file:tools/browser-check.mjs"]
        self.assertTrue(check_plan(self.root, proposal)["valid"])
        self.assertEqual(profile["verification"]["execution_status"], "not_run")

    def test_manifest_and_local_imports_are_observed_without_execution(self) -> None:
        self.write("pkg/bomb.py", "raise RuntimeError('inspection must not import this')\n")
        profile = inspect_project(self.root)
        self.assertEqual(profile["manifests"][0]["entry_points"], {"sample": "pkg.cli:main"})
        self.assertIn(("pkg/cli.py", "pkg/core.py"), {(r["from"], r["to"]) for r in profile["relationships"]})
        self.assertEqual(profile["verification"]["execution_status"], "not_run")
        self.assertEqual(profile["verification"]["declared_commands"][0]["command"], "python -m unittest discover -s tests")
        source = next(row for row in profile["sources"] if row["path"] == "pkg/core.py")
        self.assertEqual(source["line_count"], 2)
        self.assertEqual(len(source["sha256"]), 64)

    def test_repository_fsmonitor_hook_is_not_executed(self) -> None:
        hook = self.write(".artifacts/fsmonitor.sh", "#!/bin/sh\necho EXECUTED > .artifacts/hook-executed\n")
        hook.chmod(0o755)
        self.git("config", "core.fsmonitor", str(hook))
        inspect_project(self.root)
        self.assertFalse((self.root / ".artifacts/hook-executed").exists())

    def test_snapshots_are_deterministic_and_detect_dirty_content_changes(self) -> None:
        original = inspect_project(self.root)
        self.assertEqual(original, inspect_project(self.root))
        self.write("pkg/core.py", "def work():\n    return 2\n")
        dirty = inspect_project(self.root)
        self.write("pkg/core.py", "def work():\n    return 3\n")
        changed = inspect_project(self.root)
        self.assertEqual(dirty["git"]["status_sha256"], changed["git"]["status_sha256"])
        self.assertNotEqual(dirty["snapshot_sha256"], changed["snapshot_sha256"])
        self.assertNotEqual(original["snapshot_sha256"], dirty["snapshot_sha256"])

    def test_private_generated_and_ignored_sources_are_excluded(self) -> None:
        for path in (".env", "secrets/token.py", "generated/private.py", "credentials.json", "id_rsa", "ignored.py"):
            self.write(path, "PRIVATE_SENTINEL")
        self.git("add", "-f", ".env", "credentials.json")
        text = json.dumps(inspect_project(self.root))
        self.assertNotIn("PRIVATE_SENTINEL", text)
        self.assertNotIn('"path": ".env"', text)
        self.assertNotIn('"path": "ignored.py"', text)

    def test_paths_with_spaces_and_nested_manifest_are_preserved(self) -> None:
        self.write("a space/helper.py", "value = 1\n")
        self.write("frontend/package.json", '{"name":"ui","scripts":{"test":"node --test"},"dependencies":{"lib":"1"}}')
        profile = inspect_project(self.root)
        self.assertIn("a space/helper.py", [row["path"] for row in profile["sources"]])
        node_manifest = next(row for row in profile["manifests"] if row["path"] == "frontend/package.json")
        self.assertEqual(node_manifest["dependencies"], ["lib"])

    def test_invalid_manifests_and_syntax_remain_explicit_gaps(self) -> None:
        self.write("package.json", '{"scripts":[]}')
        self.write("pkg/broken.py", "def nope(\n")
        packet = prepare_plan(self.root, "Inspect parser")
        gaps = packet["suggested_evidence_checks"][0]
        self.assertEqual(gaps["id"], "resolve-context-gaps")
        self.assertIn("package.json", gaps["parse_gap_paths"])
        self.assertIn("pkg/broken.py", gaps["parse_gap_paths"])

    def test_file_and_count_limits_are_reported(self) -> None:
        self.write("pkg/large.py", "x" * 300_000)
        profile = inspect_project(self.root)
        self.assertIn({"path": "pkg/large.py", "reason": "file_byte_limit"}, profile["inventory"]["skipped"])
        with patch("agent_case_graph.project_profile.MAX_FILES", 2):
            limited = inspect_project(self.root)
        self.assertTrue(limited["inventory"]["truncated"])
        self.assertEqual(limited["inventory"]["inspected_file_count"], 2)
        with patch("agent_case_graph.project_profile.MAX_TOTAL_BYTES", 200):
            byte_limited = inspect_project(self.root)
        self.assertLessEqual(byte_limited["inventory"]["bytes_read"], 200)
        self.assertTrue(any(row["reason"] == "total_byte_limit" for row in byte_limited["inventory"]["skipped"]))

    def test_src_and_relative_imports_map_only_unique_local_modules(self) -> None:
        self.write("src/extra/__init__.py", "")
        self.write("src/extra/a.py", "from .b import work\n")
        self.write("src/extra/b.py", "def work(): pass\n")
        profile = inspect_project(self.root)
        self.assertIn(("src/extra/a.py", "src/extra/b.py"), {(r["from"], r["to"]) for r in profile["relationships"]})
        self.write("src/pkg/core.py", "def work(): pass\n")
        ambiguous = inspect_project(self.root)
        self.assertFalse(any(r["from"] == "pkg/cli.py" and r["to"].endswith("pkg/core.py") for r in ambiguous["relationships"]))

    def test_detached_head_and_unborn_repositories_are_supported(self) -> None:
        self.git("checkout", "--detach", "-q")
        self.assertIsNone(inspect_project(self.root)["git"]["branch"])
        with tempfile.TemporaryDirectory(prefix="acg-empty-") as directory:
            subprocess.run(["git", "init", "-q", directory], check=True)
            empty = inspect_project(directory)
        self.assertIsNone(empty["git"]["head"])
        self.assertEqual(empty["inventory"]["inspected_file_count"], 0)

    def test_git_worktree_is_supported(self) -> None:
        linked = Path(self.temp.name).with_name(Path(self.temp.name).name + "-worktree")
        self.git("worktree", "add", "--detach", "-q", str(linked))
        try:
            self.assertIsNone(inspect_project(linked)["git"]["branch"])
        finally:
            self.git("worktree", "remove", "--force", str(linked))

    def test_non_repository_and_repository_subdirectory_are_rejected(self) -> None:
        with self.assertRaises(ACGError):
            inspect_project(self.root / "pkg")
        with tempfile.TemporaryDirectory(prefix="acg-not-git-") as directory:
            with self.assertRaises(ACGError):
                inspect_project(directory)

    def test_symlinks_are_not_read_or_valid_targets(self) -> None:
        link = self.root / "linked.py"
        try:
            link.symlink_to(self.root / "pkg/core.py")
        except OSError:
            self.skipTest("symlink creation unavailable on this host")
        profile = inspect_project(self.root)
        self.assertIn({"path": "linked.py", "reason": "unreadable_or_linked_source"}, profile["inventory"]["skipped"])
        with self.assertRaises(ACGError):
            workspace_path(self.root, "linked.py")

    @unittest.skipUnless(os.name == "nt", "Windows junction check")
    def test_windows_junction_parents_are_rejected(self) -> None:
        subprocess.run([
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "New-Item -ItemType Junction -Path $env:ACG_TEST_JUNCTION_LINK -Target $env:ACG_TEST_JUNCTION_TARGET | Out-Null",
        ], capture_output=True, check=True, env={
            **os.environ, "ACG_TEST_JUNCTION_LINK": str(self.root / "linked"),
            "ACG_TEST_JUNCTION_TARGET": str(self.root / "pkg"),
        })
        with self.assertRaisesRegex(ACGError, "linked"):
            workspace_path(self.root, "linked/core.py")


class ProjectPlanningTests(RepositoryFixture):
    def test_valid_proposal_remains_unapproved_and_does_not_write(self) -> None:
        plan = self.plan()
        before = self.git("status", "--porcelain=v1")
        result = check_plan(self.root, plan)
        self.assertTrue(result["valid"])
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["status"], "valid_proposal")
        self.assertEqual(before, self.git("status", "--porcelain=v1"))
        self.assertFalse((self.root / "tests/test_new_behavior.py").exists())

    def test_source_edit_invalidates_a_proposal(self) -> None:
        plan = self.plan()
        self.write("pkg/core.py", "def work():\n    return 4\n")
        result = check_plan(self.root, plan)
        self.assertIn("stale_repository_snapshot", [row["code"] for row in result["errors"]])

    def test_configuration_edit_invalidates_a_proposal(self) -> None:
        self.write("schema.json", '{"type":"object"}')
        plan = self.plan()
        self.write("schema.json", '{"type":"string"}')
        self.assertFalse(check_plan(self.root, plan)["valid"])

    def test_missing_sources_unknown_sources_and_acceptance_are_rejected(self) -> None:
        plan = self.plan()
        plan["tasks"][0]["source_refs"] = ["file:imaginary.py"]
        plan["tasks"][0]["acceptance_criteria"] = []
        result = check_plan(self.root, plan)
        self.assertIn("unknown_source_ref", [row["code"] for row in result["errors"]])
        self.assertIn("missing_acceptance_criteria", [row["code"] for row in result["errors"]])
        plan["tasks"][0]["source_refs"] = []
        self.assertIn("missing_source_refs", [row["code"] for row in check_plan(self.root, plan)["errors"]])

    def test_dependency_cycles_unknown_dependencies_and_duplicate_ids_are_rejected(self) -> None:
        plan = self.plan()
        task = plan["tasks"][0]
        task["depends_on"] = [task["id"]]
        self.assertIn("dependency_cycle", [row["code"] for row in check_plan(self.root, plan)["errors"]])
        task["depends_on"] = ["missing"]
        self.assertIn("unknown_dependency", [row["code"] for row in check_plan(self.root, plan)["errors"]])
        task["depends_on"] = []
        plan["tasks"].append(copy.deepcopy(task))
        self.assertIn("duplicate_task_id", [row["code"] for row in check_plan(self.root, plan)["errors"]])

    def test_traversal_absolute_sensitive_and_windows_target_paths_are_rejected(self) -> None:
        for target in ("../outside.py", "/tmp/a.py", "C:/a.py", "pkg\\a.py", ".env", "secrets/a.py", "pkg/../a.py"):
            with self.subTest(target=target):
                plan = self.plan()
                plan["tasks"][0]["target_paths"] = [target]
                self.assertIn("unsafe_target_path", [row["code"] for row in check_plan(self.root, plan)["errors"]])

    def test_malformed_plan_data_returns_diagnostics(self) -> None:
        for value in (None, [], {"tasks": "bad"}, {"tasks": [None]}):
            with self.subTest(value=value):
                self.assertFalse(check_plan(self.root, value)["valid"])
        plan = self.plan()
        plan["approved"] = True
        self.assertIn("invalid_plan_fields", [row["code"] for row in check_plan(self.root, plan)["errors"]])
        del plan["approved"]
        plan["tasks"][0]["source_refs"] = [None]
        self.assertFalse(check_plan(self.root, plan)["valid"])

    def test_packet_exposes_observed_gaps_and_lexical_context(self) -> None:
        packet = prepare_plan(self.root, "Improve core")
        self.assertIn("pkg/core.py", packet["focus"]["paths"])
        self.assertIn("pkg/cli.py", packet["focus"]["import_neighbors"])
        self.assertEqual(packet["execution_status"], "proposal_context_only")
        self.assertIsNone(packet["runtime"])
        self.assertEqual(packet["suggested_evidence_checks"][0]["id"], "verify-baseline")
        chinese = prepare_plan(self.root, "改进项目规划能力")
        self.assertEqual(chinese["focus"]["status"], "agent_selection_required")

    def test_empty_goal_and_implicit_ledger_are_rejected(self) -> None:
        with self.assertRaises(ACGError):
            prepare_plan(self.root, " ")
        with self.assertRaises(ACGError):
            prepare_plan(self.root, "test", run_id="implicit")
        with self.assertRaises(ACGError):
            runtime_advice(self.root, "../outside.jsonl")

    def test_invalid_encoding_and_oversized_ledgers_are_rejected(self) -> None:
        path = self.root / "evidence/invalid.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xff")
        with self.assertRaises(ACGError):
            runtime_advice(self.root, "evidence/invalid.jsonl")
        path.write_bytes(b"x" * 4_000_001)
        with self.assertRaisesRegex(ACGError, "input limit"):
            runtime_advice(self.root, "evidence/invalid.jsonl")

    def test_cli_writes_ignored_context_and_reports_stale_plan_exit(self) -> None:
        output = self.root / ".artifacts/context.json"
        self.assertEqual(main(["plan-project", str(self.root), "--goal", "Improve core", "--output", str(output)]), 0)
        self.assertEqual(json.loads(output.read_text())["goal"], "Improve core")
        proposal = self.root / ".artifacts/plan.json"
        proposal.write_text(json.dumps(self.plan()), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["check-plan", str(self.root), str(proposal)]), 0)
        self.write("pkg/core.py", "changed = True\n")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["check-plan", str(self.root), str(proposal)]), 1)
        with redirect_stderr(io.StringIO()):
            self.assertEqual(main(["check-plan", str(self.root), str(self.root / "missing.json")]), 2)


if __name__ == "__main__":
    unittest.main()
