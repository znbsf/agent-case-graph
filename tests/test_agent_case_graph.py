from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_case_graph.ledger import append_event, load_events, write_new_ledger
from agent_case_graph.inference import infer_workflow
from agent_case_graph.lint import lint_graph
from agent_case_graph.localization import load_display_locales
from agent_case_graph.model import SCHEMA_VERSION, validate_event
from agent_case_graph.projector import project_events
from agent_case_graph.renderer import render_plantuml, write_projection
from agent_case_graph.runtime import build_runtime_snapshot
from agent_case_graph.trace_model import LAYOUT_EDGE_TYPES, PHASE_ORDER, PROTOCOL_VERSION, build_trace_model


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
        self.assertIn("neighbor median", model["principles"]["parallel_order"])
        self.assertFalse(model["principles"]["position_is_semantic"])
        self.assertEqual(sorted(LAYOUT_EDGE_TYPES), model["principles"]["layout_edge_types"])
        self.assertNotIn("contains", LAYOUT_EDGE_TYPES)
        self.assertIn("frames", LAYOUT_EDGE_TYPES)
        self.assertIn("produces", LAYOUT_EDGE_TYPES)
        self.assertEqual("workflow + forward-layout endpoints", model["principles"]["primary_node_policy"])
        self.assertTrue(set(PHASE_ORDER).issubset({node["phase"] for node in model["nodes"]}))
        self.assertTrue(all(node["first_sequence"] is not None for node in model["nodes"]))

    def test_review_cycles_do_not_collapse_workflow_layout_to_a_line(self) -> None:
        nodes = [
            {"id": "case", "type": "Case", "label": "Case", "attrs": {}, "event_ids": []},
            {"id": "left", "type": "Observation", "label": "Left evidence", "attrs": {}, "event_ids": []},
            {"id": "right", "type": "Observation", "label": "Right evidence", "attrs": {}, "event_ids": []},
            {"id": "cause", "type": "RootCause", "label": "Cause", "attrs": {}, "event_ids": []},
            {"id": "decision", "type": "Decision", "label": "Decision", "attrs": {}, "event_ids": []},
        ]
        edge_specs = [
            ("contains-left", "contains", "case", "left"),
            ("contains-right", "contains", "case", "right"),
            ("contains-cause", "contains", "case", "cause"),
            ("contains-decision", "contains", "case", "decision"),
            ("left-supports", "supports", "left", "cause"),
            ("right-supports", "supports", "right", "cause"),
            ("cause-precedes", "precedes", "cause", "decision"),
            ("decision-derived", "derived_from", "decision", "cause"),
        ]
        edges = [
            {"id": edge_id, "type": kind, "from": source, "to": target, "attrs": {}}
            for edge_id, kind, source, target in edge_specs
        ]
        graph = {
            "graph_id": "graph:branch-test", "root_id": "case", "generated_at": "2026-01-01T00:00:00Z",
            "nodes": nodes, "edges": edges, "stats": {"nodes": len(nodes), "edges": len(edges)},
        }
        model = build_trace_model(graph, [])
        ranks = {node["id"]: node["rank"] for node in model["nodes"]}
        self.assertEqual(ranks["left"], ranks["right"])
        self.assertEqual(ranks["left"], ranks["cause"])
        self.assertGreater(ranks["decision"], ranks["cause"])
        self.assertFalse(next(edge for edge in model["edges"] if edge["id"] == "decision-derived")["layout"])
        self.assertTrue(next(node for node in model["nodes"] if node["id"] == "cause")["primary"])
        self.assertFalse(next(node for node in model["nodes"] if node["id"] == "left")["primary"])

    def test_trace_model_is_deterministic(self) -> None:
        events = load_events(QUICKSTART)
        graph = project_events(events)
        self.assertEqual(build_trace_model(graph, events), build_trace_model(graph, events))

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
            ("Plan", "ReasoningSummary", "ToolCall", "ToolOutput"), start=1
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

    def test_only_tool_outputs_make_produces_a_workflow_edge(self) -> None:
        nodes = [
            {"id": "call", "type": "ToolCall", "label": "Call", "attrs": {}, "event_ids": []},
            {"id": "output", "type": "ToolOutput", "label": "Output", "attrs": {}, "event_ids": []},
            {"id": "verify", "type": "Verification", "label": "Verify", "attrs": {}, "event_ids": []},
            {"id": "receipt", "type": "VerificationReceipt", "label": "Receipt", "attrs": {}, "event_ids": []},
        ]
        edges = [
            {"id": "tool-output", "type": "produces", "from": "call", "to": "output", "attrs": {}},
            {"id": "verify-receipt", "type": "produces", "from": "verify", "to": "receipt", "attrs": {}},
        ]
        model = build_trace_model(
            {
                "graph_id": "graph",
                "root_id": "call",
                "generated_at": "2026-01-01T00:00:00Z",
                "nodes": nodes,
                "edges": edges,
                "stats": {"nodes": 4, "edges": 2},
            },
            [],
        )
        layout = {edge["id"]: edge["layout"] for edge in model["edges"]}
        self.assertTrue(layout["tool-output"])
        self.assertFalse(layout["verify-receipt"])

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
            if node["primary"]:
                self.assertIn(node["label"][:92], puml)
            else:
                self.assertNotIn(node["label"][:92], puml)
            self.assertIn(node["id"], html)
        self.assertIn("top to bottom direction", puml)
        self.assertIn("layered DAG", puml)
        self.assertNotIn("supports", puml)
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
        self.assertIn("maxColumns=3", html)
        self.assertIn("crossingReducedRanks", html)
        self.assertIn("function routedEdges", html)
        self.assertIn('"data-from":edge.from', html)
        self.assertIn('"data-route":item.displayRoute', html)
        self.assertIn('displayRoute="gap-same-rank"', html)
        self.assertIn('displayRoute="side-same-rank"', html)
        self.assertIn("group.length<=capacity", html)
        self.assertIn("item.wrapOverflow=true", html)
        self.assertIn("evidenceLinks=MODEL.edges.filter", html)
        self.assertIn("contentWidth=80+maxAcross*cardW+(maxAcross-1)*minGap", html)
        self.assertIn("overflow:auto", html)


if __name__ == "__main__":
    unittest.main()
