from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_case_graph.ledger import append_event, load_events, write_new_ledger
from agent_case_graph.lint import lint_graph
from agent_case_graph.localization import load_display_locales
from agent_case_graph.projector import project_events
from agent_case_graph.renderer import render_plantuml, write_projection
from agent_case_graph.runtime import build_runtime_snapshot
from agent_case_graph.trace_model import PHASE_ORDER, PROTOCOL_VERSION, build_trace_model


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
        self.assertEqual("replay-0.1", graph["replay"]["protocol_version"])
        self.assertNotIn("spatial", graph)

    def test_trace_model_uses_paper_layers_and_preserves_source_records(self) -> None:
        events = load_events(QUICKSTART)
        graph = project_events(events)
        model = build_trace_model(graph, events)
        self.assertEqual(PROTOCOL_VERSION, model["protocol_version"])
        self.assertEqual(list(PHASE_ORDER), model["phases"])
        self.assertEqual(len(events), len(model["trace"]))
        self.assertTrue(model["principles"]["source_records_preserved"])
        self.assertEqual("claim-to-evidence", model["principles"]["review_direction"])
        self.assertFalse(model["principles"]["position_is_semantic"])
        self.assertTrue(set(PHASE_ORDER).issubset({node["phase"] for node in model["nodes"]}))

    def test_trace_model_is_deterministic(self) -> None:
        events = load_events(QUICKSTART)
        graph = project_events(events)
        self.assertEqual(build_trace_model(graph, events), build_trace_model(graph, events))

    def test_plantuml_and_html_share_one_trace_model(self) -> None:
        events = load_events(QUICKSTART)
        graph = project_events(events, ledger_path=QUICKSTART)
        out = self.root / "generated"
        receipt = write_projection(
            out,
            graph=graph,
            events=events,
            findings=lint_graph(graph),
            title="Paper Trace Test",
            display_locales=load_display_locales(QUICKSTART),
        )
        model = json.loads((out / "trace-model.json").read_text(encoding="utf-8"))
        puml = (out / "trace.puml").read_text(encoding="utf-8")
        html = (out / "graph.html").read_text(encoding="utf-8")
        for node in model["nodes"]:
            self.assertIn(node["label"][:92], puml)
            self.assertIn(node["id"], html)
        self.assertIn("top to bottom direction", puml)
        self.assertIn("layered DAG", puml)
        self.assertIn('id="timeline"', html)
        self.assertIn('id="graphSvg"', html)
        self.assertIn('id="details"', html)
        self.assertIn('data-view="workflow"', html)
        self.assertIn('data-view="evidence"', html)
        self.assertIn('data-view="trace"', html)
        self.assertIn("claim-to-evidence", (out / "trace-model.json").read_text(encoding="utf-8"))
        self.assertEqual(PROTOCOL_VERSION, receipt["protocol_version"])
        self.assertEqual(64, len(receipt["outputs"]["graph.html"]["sha256"]))

    def test_projection_removes_known_legacy_mermaid_output(self) -> None:
        events = load_events(QUICKSTART)
        graph = project_events(events)
        out = self.root / "generated"
        out.mkdir()
        (out / "graph.mmd").write_text("legacy", encoding="utf-8")
        write_projection(out, graph=graph, events=events, findings=[], title="Reset")
        self.assertFalse((out / "graph.mmd").exists())
        self.assertTrue((out / "trace.puml").exists())

    def test_projection_is_self_contained_and_has_no_spatial_legacy(self) -> None:
        events = load_events(QUICKSTART)
        graph = project_events(events)
        out = self.root / "generated"
        write_projection(out, graph=graph, events=events, findings=[], title="Offline")
        html = (out / "graph.html").read_text(encoding="utf-8")
        self.assertNotIn('src="http', html)
        self.assertNotIn('href="http', html)
        self.assertIn("default-src 'none'", html)
        self.assertNotIn("orthogonal", html.lower())
        self.assertNotIn("three.js", html.lower())

    def test_append_only_event_is_visible_in_trace(self) -> None:
        ledger = self.root / "events.jsonl"
        events = load_events(QUICKSTART)
        write_new_ledger(ledger, events, force=True)
        event = append_event(
            ledger,
            case_id=events[0]["case_id"],
            kind="node.recorded",
            actor_type="agent",
            actor_id="unit-test",
            capture_mode="live",
            source_refs=["unit-test"],
            payload={"node": {"id": "artifact:test", "type": "Artifact", "label": "Generated audit artifact", "attrs": {"output": "report.json"}}},
        )
        updated = load_events(ledger)
        model = build_trace_model(project_events(updated), updated)
        self.assertEqual(event["event_id"], model["trace"][-1]["event_id"])
        self.assertEqual("artifact:test", model["trace"][-1]["node_id"])

    def test_runtime_frontier_remains_available_below_new_renderer(self) -> None:
        snapshot = build_runtime_snapshot(project_events(load_events(QUICKSTART)))
        self.assertIn(snapshot["status"], {"configured", "ready", "running", "blocked", "completed"})
        self.assertIn("counts", snapshot)

    def test_plantuml_escapes_quotes_backslashes_and_control_characters(self) -> None:
        events = load_events(QUICKSTART)
        model = build_trace_model(project_events(events), events)
        model["nodes"][0]["label"] = 'Inspect "C:\\logs"\r@enduml\r@startuml\x00'
        puml = render_plantuml(model)
        self.assertIn("Inspect 'C:\\\\logs' @enduml @startuml ", puml)
        self.assertEqual(1, puml.count("\n@enduml"))

    def test_html_allocates_width_for_wide_parallel_ranks(self) -> None:
        events = load_events(QUICKSTART)
        graph = project_events(events)
        out = self.root / "generated"
        write_projection(out, graph=graph, events=events, findings=[], title="Wide rank")
        html = (out / "graph.html").read_text(encoding="utf-8")
        self.assertIn("contentWidth=140+maxAcross*cardW+(maxAcross-1)*minGap", html)
        self.assertIn("overflow:auto", html)


if __name__ == "__main__":
    unittest.main()
