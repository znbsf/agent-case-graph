from __future__ import annotations

import copy
import unittest
from datetime import datetime

from agent_case_graph.cli import _initial_case_events
from agent_case_graph.lint import lint_graph
from agent_case_graph.projector import project_events
from agent_case_graph.runtime import build_runtime_snapshot
from tests.project_runtime_fixtures import ledger_events, mutation_graph


class ProjectMainCompatibilityTests(unittest.TestCase):
    def test_bootstrap_timestamps_finish_at_present(self):
        events = _initial_case_events(case_id="synthetic-clock", title="Synthetic fixture", run_id="run",
                                      capture_mode="synthetic", actor_type="agent", actor_id="test", source_refs=["test:clock"])
        times = [datetime.fromisoformat(event["occurred_at"]) for event in events]
        self.assertEqual(times, sorted(times))
        self.assertLessEqual(times[-1], datetime.now().astimezone())

    def test_main_spatial_projection_and_receipt_provenance_coexist(self):
        graph = project_events(ledger_events(mutation_graph()))
        self.assertIn("spatial", graph)
        self.assertIn("runtime_advice", graph)
        self.assertEqual(next(node for node in graph["nodes"] if node["id"] == "run")["provenance"]["capture_modes"], ["synthetic"])
        self.assertEqual([], lint_graph(graph))

    def test_all_mutating_executable_types_require_exact_scope_and_typed_target(self):
        for kind in ("Action", "Step", "ToolCall", "Verification"):
            with self.subTest(kind=kind):
                graph = mutation_graph(kind)
                self.assertEqual(["call"], build_runtime_snapshot(graph, run_id="run")["next_action_ids"])
                wrong_scope = copy.deepcopy(graph)
                next(node for node in wrong_scope["nodes"] if node["id"] == "approval")["attrs"]["scope"] = "repository"
                self.assertEqual([], build_runtime_snapshot(wrong_scope, run_id="run")["next_action_ids"])
                wrong_target = copy.deepcopy(graph)
                next(node for node in wrong_target["nodes"] if node["id"] == "target")["type"] = "Goal"
                self.assertEqual([], build_runtime_snapshot(wrong_target, run_id="run")["next_action_ids"])

    def test_run_discovers_actions_nested_under_a_plan(self):
        graph = mutation_graph()
        graph["nodes"].append({"id": "plan", "type": "Plan", "label": "Synthetic group", "attrs": {}, "first_sequence": 10})
        next(edge for edge in graph["edges"] if edge["id"] == "contains-call")["from"] = "plan"
        graph["edges"].append({"id": "contains-plan", "type": "contains", "from": "run", "to": "plan", "attrs": {}})
        self.assertEqual(["call"], build_runtime_snapshot(graph, run_id="run")["next_action_ids"])


if __name__ == "__main__":
    unittest.main()
