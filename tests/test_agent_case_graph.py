from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

from agent_case_graph.cli import main
from agent_case_graph.ledger import append_event, load_events, write_new_ledger
from agent_case_graph.inference import infer_workflow
from agent_case_graph.lint import lint_graph
from agent_case_graph.model import SCHEMA_VERSION, validate_event
from agent_case_graph.projector import project_events
from agent_case_graph.renderer import layout, write_projection
from agent_case_graph.runtime import build_runtime_snapshot


ROOT = Path(__file__).resolve().parents[1]
QUICKSTART = ROOT / "examples" / "quickstart" / "events.jsonl"


class AgentCaseGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_public_quickstart_is_valid(self) -> None:
        events = load_events(QUICKSTART)
        graph = project_events(events, ledger_path=QUICKSTART)
        self.assertEqual([], lint_graph(graph))
        self.assertEqual(len(graph["nodes"]), len({n["id"] for n in graph["nodes"]}))

    def test_init_case_then_immediate_record_keeps_timestamps_monotonic(self) -> None:
        ledger = self.root / "events.jsonl"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(
                0,
                main(
                    [
                        "init-case",
                        "--ledger",
                        str(ledger),
                        "--case-id",
                        "TIMESTAMP-001",
                        "--title",
                        "Timestamp ordering regression",
                        "--capture-mode",
                        "synthetic",
                    ]
                ),
            )
            self.assertEqual(
                0,
                main(
                    [
                        "record-node",
                        "--ledger",
                        str(ledger),
                        "--case-id",
                        "TIMESTAMP-001",
                        "--run-id",
                        "run:TIMESTAMP-001:001",
                        "--capture-mode",
                        "synthetic",
                        "--node-id",
                        "goal:timestamp",
                        "--node-type",
                        "Goal",
                        "--label",
                        "Append immediately after init-case",
                    ]
                ),
            )

        timestamps = [
            datetime.fromisoformat(event["occurred_at"])
            for event in load_events(ledger)
        ]
        self.assertTrue(
            all(previous <= current for previous, current in zip(timestamps, timestamps[1:]))
        )

    def test_workflow_can_be_reverse_inferred_from_graph_relations(self) -> None:
        nodes = [
            {"id": "case", "type": "Case", "label": "Case", "attrs": {}, "event_ids": [], "first_sequence": 1},
            {"id": "goal", "type": "Goal", "label": "Find cause", "attrs": {}, "event_ids": [], "first_sequence": 2},
            {"id": "plan", "type": "Plan", "label": "Inspect evidence", "attrs": {}, "event_ids": [], "first_sequence": 3},
            {"id": "call", "type": "ToolCall", "label": "Search logs", "attrs": {}, "event_ids": [], "first_sequence": 4},
            {"id": "output", "type": "ToolOutput", "label": "Matched rows", "attrs": {}, "event_ids": [], "first_sequence": 5},
            {"id": "claim", "type": "Claim", "label": "Cause confirmed", "attrs": {}, "event_ids": [], "first_sequence": 6},
        ]
        edges = [
            {"id": "e1", "type": "frames", "from": "goal", "to": "plan", "attrs": {}},
            {"id": "e2", "type": "invokes", "from": "plan", "to": "call", "attrs": {}},
            {"id": "e3", "type": "produces", "from": "call", "to": "output", "attrs": {}},
            {"id": "e4", "type": "supports", "from": "output", "to": "claim", "attrs": {}},
        ]
        inferred = infer_workflow({"nodes": nodes, "edges": edges})
        self.assertEqual(["goal"], inferred["plans"][0]["framed_by"])
        self.assertEqual(["output"], inferred["plans"][0]["actions"][0]["outputs"])
        self.assertEqual(["claim"], inferred["plans"][0]["actions"][0]["supported_claims"])
        self.assertEqual([], inferred["gaps"])

    def test_new_workflow_types_and_relations_validate_as_ledger_events(self) -> None:
        base = {
            "schema_version": SCHEMA_VERSION,
            "case_id": "case",
            "sequence": 1,
            "occurred_at": "2026-01-01T00:00:00Z",
            "actor": {"type": "agent", "id": "test"},
            "provenance": {"capture_mode": "synthetic", "source_refs": []},
        }
        for index, node_type in enumerate(
            (
                "Plan", "ReasoningSummary", "ToolCall", "ToolOutput",
                "DialogueRound", "ExecutionIteration", "UserFeedback",
                "AgentResponse", "Evaluation",
            ), start=1
        ):
            validate_event(
                {
                    **base,
                    "event_id": f"node-{index}",
                    "kind": "node.recorded",
                    "node": {"id": f"n{index}", "type": node_type, "label": node_type, "attrs": {}},
                }
            )
        for index, edge_type in enumerate(("frames", "informs"), start=1):
            validate_event(
                {
                    **base,
                    "event_id": f"edge-{index}",
                    "kind": "edge.recorded",
                    "edge": {"id": f"e{index}", "type": edge_type, "from": "a", "to": "b", "attrs": {}},
                }
            )

    def test_inference_preserves_parallel_groups_and_reports_precedes_cycles(self) -> None:
        nodes = [
            {"id": "goal", "type": "Goal", "label": "Goal", "first_sequence": 1},
            {"id": "plan", "type": "Plan", "label": "Plan", "first_sequence": 2},
            {"id": "a", "type": "ToolCall", "label": "A", "first_sequence": 3},
            {"id": "b", "type": "ToolCall", "label": "B", "first_sequence": 4},
            {"id": "oa", "type": "ToolOutput", "label": "OA", "first_sequence": 5},
            {"id": "ob", "type": "ToolOutput", "label": "OB", "first_sequence": 6},
        ]
        edges = [
            {"id": "frames", "type": "frames", "from": "goal", "to": "plan"},
            {"id": "invoke-a", "type": "invokes", "from": "plan", "to": "a"},
            {"id": "invoke-b", "type": "invokes", "from": "plan", "to": "b"},
            {"id": "output-a", "type": "produces", "from": "a", "to": "oa"},
            {"id": "output-b", "type": "produces", "from": "b", "to": "ob"},
        ]
        parallel = infer_workflow({"nodes": nodes, "edges": edges})
        self.assertEqual("parallel_or_unordered", parallel["plans"][0]["action_groups"][0]["mode"])
        cyclic = infer_workflow(
            {
                "nodes": nodes,
                "edges": edges
                + [
                    {"id": "a-b", "type": "precedes", "from": "a", "to": "b"},
                    {"id": "b-a", "type": "precedes", "from": "b", "to": "a"},
                ],
            }
        )
        self.assertIn("precedes_cycle", {gap["code"] for gap in cyclic["gaps"]})
        self.assertEqual(["a", "b"], cyclic["plans"][0]["cyclic_action_ids"])

    def test_projection_writes_one_offline_page_with_every_node_and_edge(self) -> None:
        events = load_events(QUICKSTART)
        graph = project_events(events, ledger_path=QUICKSTART)
        out = self.root / "generated"
        receipt = write_projection(out, graph=graph, findings=lint_graph(graph), title="<Quickstart>")
        self.assertEqual(["graph.html", "graph.json", "lint.json"], sorted(receipt["outputs"]))
        self.assertEqual({"errors": 0, "warnings": 0}, receipt["lint"])
        html = (out / "graph.html").read_text(encoding="utf-8")
        self.assertIn("default-src 'none'", html)
        self.assertNotIn('src="http', html)
        self.assertIn("&lt;Quickstart&gt;", html)
        for node in graph["nodes"]:
            self.assertIn(f'data-node="{node["id"]}"', html)
        for edge in graph["edges"]:
            self.assertIn(f'data-edge="{edge["id"]}"', html)

    def test_layout_places_successors_below_and_survives_cycles(self) -> None:
        graph = {
            "nodes": [{"id": n} for n in ("a", "b", "c")],
            "edges": [
                {"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "c", "to": "a"},
            ],
        }
        positions = layout(graph)
        self.assertLess(positions["a"][1], positions["b"][1])
        self.assertLess(positions["b"][1], positions["c"][1])

    def test_label_markup_is_escaped_in_page(self) -> None:
        events = load_events(QUICKSTART)
        graph = project_events(events)
        graph["nodes"][0]["label"] = '</script><img src=x onerror=alert(1)>'
        out = self.root / "generated"
        write_projection(out, graph=graph, findings=[], title="Escape")
        html = (out / "graph.html").read_text(encoding="utf-8")
        self.assertNotIn("<img src=x", html)
        self.assertNotIn("</script><img", html)

    def test_runtime_frontier_remains_available(self) -> None:
        snapshot = build_runtime_snapshot(project_events(load_events(QUICKSTART)))
        self.assertIn(snapshot["status"], {"configured", "ready", "running", "blocked", "completed"})
        self.assertIn("counts", snapshot)

    def test_runtime_action_context_inherits_plan_goal_lineage(self) -> None:
        nodes = [
            {"id": "case", "type": "Case", "label": "Case", "attrs": {"current_state": "execute"}, "first_sequence": 1},
            {"id": "run", "type": "Run", "label": "Run", "attrs": {"capture_mode": "live"}, "first_sequence": 2},
            {"id": "goal", "type": "Goal", "label": "Goal", "attrs": {}, "first_sequence": 3},
            {"id": "plan", "type": "Plan", "label": "Plan", "attrs": {}, "first_sequence": 4},
            {"id": "action", "type": "Action", "label": "Act", "attrs": {"runtime_managed": True, "status": "pending", "mutating": False}, "first_sequence": 5},
        ]
        edges = [
            {"id": "has-run", "type": "has_run", "from": "case", "to": "run", "attrs": {}},
            {"id": "contains", "type": "contains", "from": "run", "to": "action", "attrs": {}},
            {"id": "frames", "type": "frames", "from": "goal", "to": "plan", "attrs": {}},
            {"id": "invokes", "type": "invokes", "from": "plan", "to": "action", "attrs": {}},
        ]
        graph = {"root_id": "case", "nodes": nodes, "edges": edges}
        ready = build_runtime_snapshot(graph, run_id="run")["ready"][0]
        context_ids = {item["id"] for item in ready["context"]["nodes"]}
        self.assertTrue({"goal", "plan"}.issubset(context_ids))



if __name__ == "__main__":
    unittest.main()
