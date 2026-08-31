import copy
from pathlib import Path
import unittest

from agent_case_graph.ledger import load_events
from agent_case_graph.projector import project_events
from agent_case_graph.replay import REPLAY_PROTOCOL_VERSION, build_replay_catalog


REPO_ROOT = Path(__file__).resolve().parents[1]
QUICKSTART_LEDGER = REPO_ROOT / "examples" / "quickstart" / "events.jsonl"


class ReplayCatalogTests(unittest.TestCase):
    def _quickstart(self):
        events = load_events(QUICKSTART_LEDGER)
        graph = project_events(events, ledger_path=QUICKSTART_LEDGER)
        replay = graph["replay"]
        run = next(item for item in replay["runs"] if item["run_id"] == "run:DEMO-001:001")
        return events, graph, replay, run

    def test_actual_track_is_sequence_authoritative_and_visual_only(self):
        _, _, replay, run = self._quickstart()

        self.assertEqual(REPLAY_PROTOCOL_VERSION, replay["protocol_version"])
        self.assertTrue(replay["visual_only"])
        self.assertFalse(replay["reexecutes_actions"])
        actual = run["actual"]
        self.assertEqual("synthetic-ledger", actual["track_kind"])
        self.assertEqual("synthetic", actual["completeness"])
        self.assertEqual(29, actual["event_count"])
        self.assertEqual(list(range(3, 32)), [frame["sequence"] for frame in actual["frames"]])
        self.assertTrue(actual["visual_only"])
        self.assertFalse(actual["reexecutes_actions"])

    def test_recommendation_uses_explicit_precedes_and_is_not_claimed_optimal(self):
        _, _, _, run = self._quickstart()

        retrospective = run["retrospective"]
        self.assertEqual("available", retrospective["status"])
        self.assertEqual("not_proven", retrospective["optimality"])
        self.assertEqual(
            [
                "step:DEMO-001:inspect",
                "action:DEMO-001:select",
                "verification:DEMO-001:review",
            ],
            [step["node_id"] for step in retrospective["steps"]],
        )
        self.assertEqual(
            ["edge:demo:step-action", "edge:demo:action-verification"],
            [edge["edge_id"] for edge in retrospective["edges"]],
        )

    def test_node_status_transition_is_inferred_within_the_selected_run(self):
        events, graph, _, _ = self._quickstart()
        updated = copy.deepcopy(events)
        completion = copy.deepcopy(
            next(
                event
                for event in events
                if event["kind"] == "node.recorded"
                and event["node"]["id"] == "action:DEMO-001:select"
            )
        )
        completion["sequence"] = 32
        completion["event_id"] = "evt-demo-action-completed"
        completion["occurred_at"] = "2026-01-01T00:00:32Z"
        completion["node"]["attrs"]["status"] = "completed"
        updated.append(completion)

        replay = build_replay_catalog(graph, updated)
        run = next(item for item in replay["runs"] if item["run_id"] == "run:DEMO-001:001")
        frame = run["actual"]["frames"][-1]
        self.assertEqual("running", frame["from_status"])
        self.assertEqual("completed", frame["to_status"])
        self.assertEqual("inferred_from_prior_node_event", frame["status_source"])

    def test_unresolved_runtime_gates_reject_an_executable_recommendation(self):
        events = copy.deepcopy(load_events(QUICKSTART_LEDGER))
        action_event = next(
            event
            for event in events
            if event["kind"] == "node.recorded"
            and event["node"]["id"] == "action:DEMO-001:select"
        )
        action_event["node"]["attrs"].update(
            {
                "status": "pending",
                "mutating": True,
                "authorized_scope": "demo-target",
            }
        )

        graph = project_events(events, ledger_path=QUICKSTART_LEDGER)
        run = next(
            item
            for item in graph["replay"]["runs"]
            if item["run_id"] == "run:DEMO-001:001"
        )
        retrospective = run["retrospective"]
        self.assertEqual("gated", retrospective["status"])
        self.assertEqual("not_proven", retrospective["optimality"])
        self.assertIn("target_missing", retrospective["gate_blocker_codes"])
        self.assertIn("approval_missing", retrospective["gate_blocker_codes"])
        self.assertIn("non_live_mutation", retrospective["gate_blocker_codes"])

    def test_timestamp_order_does_not_change_replay_and_cycle_is_rejected(self):
        events, graph, _, _ = self._quickstart()
        reordered_times = copy.deepcopy(events)
        reordered_times[2]["occurred_at"] = "2026-01-01T00:00:30Z"
        reordered_times[3]["occurred_at"] = "2026-01-01T00:00:01Z"
        replay = build_replay_catalog(graph, reordered_times)
        run = next(item for item in replay["runs"] if item["run_id"] == "run:DEMO-001:001")
        self.assertEqual(list(range(3, 32)), [frame["sequence"] for frame in run["actual"]["frames"]])

        cyclic = copy.deepcopy(graph)
        cyclic["edges"].append(
            {
                "id": "edge:demo:cycle",
                "type": "precedes",
                "from": "verification:DEMO-001:review",
                "to": "step:DEMO-001:inspect",
                "attrs": {},
                "first_sequence": 32,
            }
        )
        cyclic_replay = build_replay_catalog(cyclic, events)
        cyclic_run = next(item for item in cyclic_replay["runs"] if item["run_id"] == "run:DEMO-001:001")
        self.assertEqual("cycle", cyclic_run["retrospective"]["status"])
        self.assertEqual("not_proven", cyclic_run["retrospective"]["optimality"])


if __name__ == "__main__":
    unittest.main()
