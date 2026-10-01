from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_case_graph.ledger import sha256_file, write_new_ledger
from agent_case_graph.cli import _initial_case_events
from agent_case_graph.mcp_server import create_server, serve
from agent_case_graph.model import ACGError
from agent_case_graph.project_session import record_project_plan, run_plan_check
from tests.test_project_planning import RepositoryFixture
from tests.project_runtime_fixtures import ledger_events, mutation_graph

HAS_MCP = importlib.util.find_spec("mcp") is not None
ROOT = Path(__file__).resolve().parents[1]


class MCPConfigurationTests(unittest.TestCase):
    def test_no_implicit_workspace_is_selected(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ACGError, "workspace-root"):
                serve()

    def test_core_still_works_without_the_optional_sdk(self) -> None:
        with patch.dict(sys.modules, {"mcp": None, "mcp.server": None}):
            with self.assertRaisesRegex(ACGError, "optional dependency"):
                create_server(ROOT)


@unittest.skipUnless(HAS_MCP, "install the mcp extra for SDK and stdio checks")
class MCPServerTests(RepositoryFixture):
    def test_tool_contracts_and_structured_profile(self) -> None:
        from mcp.client import Client

        async def run() -> None:
            async with Client(create_server(self.root)) as client:
                listed = await client.list_tools()
                self.assertEqual({tool.name for tool in listed.tools}, {
                    "acg_inspect_project", "acg_query_project", "acg_prepare_plan", "acg_check_plan", "acg_runtime_advice", "acg_review_plan",
                })
                for tool in listed.tools:
                    self.assertTrue(tool.annotations.read_only_hint)
                    self.assertFalse(tool.annotations.destructive_hint)
                    self.assertNotIn("workspace", tool.input_schema.get("properties", {}))
                result = await client.call_tool("acg_inspect_project", {})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["protocol_version"], "project-profile-0.1")
                page = await client.call_tool("acg_query_project", {"module": "pkg.core", "page_size": 1})
                self.assertFalse(page.is_error)
                self.assertEqual(page.structured_content["protocol_version"], "project-query-0.1")
                self.assertEqual(page.structured_content["pagination"]["returned_file_count"], 1)
                bad = await client.call_tool("acg_query_project", {"path": "../outside"})
                self.assertTrue(bad.is_error)

        asyncio.run(run())

    def test_real_stdio_process_handles_plan_and_rejects_workspace_escape(self) -> None:
        from mcp.client import Client
        from mcp.client.stdio import StdioServerParameters

        before = self.git("status", "--porcelain=v1")

        async def run() -> None:
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "agent_case_graph", "mcp", "--workspace-root", str(self.root)],
                cwd=ROOT,
            )
            async with Client(parameters, read_timeout_seconds=20, mode="legacy") as client:
                tools = await client.list_tools()
                self.assertEqual(len(tools.tools), 6)
                page = await client.call_tool("acg_query_project", {"path": "pkg", "page_size": 1})
                self.assertFalse(page.is_error)
                cursor = page.structured_content["pagination"]["next_cursor"]
                next_page = await client.call_tool("acg_query_project", {"path": "pkg", "page_size": 1, "cursor": cursor})
                self.assertFalse(next_page.is_error)
                self.assertNotEqual(page.structured_content["items"][0]["path"], next_page.structured_content["items"][0]["path"])
                packet = await client.call_tool("acg_prepare_plan", {"goal": "Improve core"})
                self.assertFalse(packet.is_error)
                plan = self.plan()
                self.assertEqual(packet.structured_content["source_snapshot_sha256"], plan["source_snapshot_sha256"])
                checked = await client.call_tool("acg_check_plan", {"plan": plan})
                self.assertTrue(checked.structured_content["valid"])
                self.assertFalse(checked.structured_content["execution_authorized"])
                self.write("pkg/core.py", "value = 9\n")
                stale_page = await client.call_tool("acg_query_project", {"path": "pkg", "page_size": 1, "cursor": cursor})
                self.assertTrue(stale_page.is_error)
                stale = await client.call_tool("acg_check_plan", {"plan": plan})
                self.assertFalse(stale.structured_content["valid"])
                bad = await client.call_tool("acg_runtime_advice", {"ledger": "../outside.jsonl"})
                self.assertTrue(bad.is_error)

        asyncio.run(run())
        # Only the test's own source edit changed the target repository.
        self.write("pkg/core.py", "def work():\n    return 1\n")
        self.assertEqual(before, self.git("status", "--porcelain=v1"))

    def test_adapter_preserves_mutation_gates_and_ledger_bytes(self) -> None:
        from mcp.client import Client

        graph = mutation_graph()
        next(node for node in graph["nodes"] if node["id"] == "approval")["attrs"]["status"] = "revoked"
        path = self.root / "evidence/events.jsonl"
        write_new_ledger(path, ledger_events(graph))
        digest = sha256_file(path)

        async def run() -> None:
            async with Client(create_server(self.root)) as client:
                result = await client.call_tool("acg_runtime_advice", {"ledger": "evidence/events.jsonl", "run_id": "run"})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["advice"]["recommendations"], [])
                self.assertEqual(result.structured_content["advice"]["runtime_snapshot"]["ready"], [])

        asyncio.run(run())
        self.assertEqual(digest, sha256_file(path))

    def test_adapter_rejects_lint_errors_with_actionable_diagnostics(self) -> None:
        from mcp.client import Client

        graph = mutation_graph()
        graph["edges"] = [edge for edge in graph["edges"] if edge["type"] != "approved_by"]
        path = self.root / "evidence/invalid.jsonl"
        write_new_ledger(path, ledger_events(graph))

        async def run() -> None:
            async with Client(create_server(self.root)) as client:
                result = await client.call_tool("acg_runtime_advice", {"ledger": "evidence/invalid.jsonl"})
                self.assertTrue(result.is_error)
                self.assertIn("ACG011", result.content[0].text)

        asyncio.run(run())

    def test_real_stdio_reviews_linked_checks_without_mutating_ledger(self) -> None:
        from mcp.client import Client
        from mcp.client.stdio import StdioServerParameters

        ledger = ".artifacts/session/events.jsonl"
        path = self.root / ledger
        write_new_ledger(path, _initial_case_events(case_id="mcp-review", title="Actual command in a fixture",
                        run_id="run:review", capture_mode="live", actor_type="agent", actor_id="test", source_refs=["test:mcp-review"]))
        record_project_plan(self.root, self.plan(), ledger, plan_id="plan:review", run_id="run:review")
        run_plan_check(self.root, ledger, plan_id="plan:review", task_id="core-change", criterion=1,
                       command=[sys.executable, "-c", "print('observed check')"])
        digest = sha256_file(path)
        async def run() -> None:
            params = StdioServerParameters(command=sys.executable,
                args=["-m", "agent_case_graph", "mcp", "--workspace-root", str(self.root)], cwd=ROOT)
            async with Client(params, mode="legacy", read_timeout_seconds=20) as client:
                result = await client.call_tool("acg_review_plan", {"ledger": ledger, "plan_id": "plan:review"})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["status"], "checks_passed")
                self.assertFalse(result.structured_content["acceptance_assessed"])
                wrong = await client.call_tool("acg_review_plan", {"ledger": ledger, "plan_id": "missing"})
                self.assertTrue(wrong.is_error)
                self.assertIn("not a recorded project plan", wrong.content[0].text)
        asyncio.run(run())
        self.assertEqual(digest, sha256_file(path))


if __name__ == "__main__":
    unittest.main()
