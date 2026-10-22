from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from agent_case_graph.cli import main
from agent_case_graph.ledger import load_events

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
# On Windows, System32\bash.exe is WSL and cannot see this interpreter.
USABLE_BASH = BASH is not None and "system32" not in BASH.lower()


class ExampleTests(unittest.TestCase):
    @unittest.skipUnless(USABLE_BASH, "needs a POSIX bash")
    def test_bugfix_walkthrough_runs_and_confirms_claim_only_after_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "bugfix"
            env = dict(os.environ, ACG=f"{Path(sys.executable).as_posix()} -m agent_case_graph", PYTHONPATH=str(ROOT))
            result = subprocess.run(
                [BASH, "examples/bugfix/record.sh", out.as_posix()],
                cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=600,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("BLOCKED ver:pytest: predecessor_incomplete", result.stdout)
            self.assertIn("insufficient_support_count", result.stderr)
            self.assertIn("Lint: 0 errors, 0 warnings", result.stdout)
            claim_states = [
                event["node"]["attrs"].get("status")
                for event in load_events(out / "events.jsonl")
                if event["kind"] == "node.recorded" and event["node"]["id"] == "claim:locale"
            ]
            self.assertEqual(["proposed", "confirmed"], claim_states)
            receipt = json.loads((out / "projection-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual({"errors": 0, "warnings": 0}, receipt["lint"])

    def test_cli_output_survives_a_legacy_console_code_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "events.jsonl"
            console = io.TextIOWrapper(io.BytesIO(), encoding="gbk")
            with redirect_stdout(console):
                main(["init-case", "--ledger", str(ledger), "--case-id", "ENC-001", "--title", "Encoding", "--capture-mode", "synthetic"])
                code = main([
                    "record-node", "--ledger", str(ledger), "--case-id", "ENC-001", "--capture-mode", "synthetic",
                    "--node-id", "obs:umlaut", "--node-type", "Observation", "--label", "time data '03 Mär 2026'",
                ])
            self.assertEqual(0, code)
            self.assertEqual("time data '03 Mär 2026'", load_events(ledger)[-1]["node"]["label"])


if __name__ == "__main__":
    unittest.main()
