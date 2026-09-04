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
from agent_case_graph.localization import load_display_locales
from agent_case_graph.loop_projection import analyze_loops, build_loop_projection
from agent_case_graph.model import SCHEMA_VERSION, validate_event
from agent_case_graph.projector import project_events
from agent_case_graph.renderer import render_plantuml, render_sequence_plantuml, write_projection
from agent_case_graph.runtime import build_runtime_snapshot
from agent_case_graph.sequence_projection import build_sequence_projection
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

    def test_sequence_projection_linearizes_one_execution_iteration_from_typed_relations(self) -> None:
        nodes = [
            {"id": "feedback", "type": "UserFeedback", "label": "Clarify scope", "phase": "context", "status": "recorded", "first_sequence": 1, "event_ids": [], "tool": None, "output": None},
            {"id": "plan", "type": "Plan", "label": "Inspect code", "phase": "plan", "status": "recorded", "first_sequence": 4, "event_ids": [], "tool": None, "output": None},
            {"id": "call", "type": "ToolCall", "label": "Search callers", "phase": "execute", "status": "completed", "first_sequence": 5, "event_ids": [], "tool": "rg", "output": None},
            {"id": "output", "type": "ToolOutput", "label": "Matched two callers", "phase": "execute", "status": "completed", "first_sequence": 3, "event_ids": [], "tool": "rg", "output": "2 matches"},
            {"id": "verification", "type": "Verification", "label": "Check matched callers", "phase": "validate", "status": "verified", "first_sequence": 0, "event_ids": [], "tool": None, "output": None},
            {"id": "claim", "type": "Claim", "label": "Cause confirmed", "phase": "claim", "status": "confirmed", "first_sequence": 2, "event_ids": [], "tool": None, "output": None},
        ]
        trace_model = {
            "nodes": nodes,
            "trace": [],
            "edges": [
                {"type": "invokes", "from": "plan", "to": "call"},
                {"type": "produces", "from": "call", "to": "output"},
                {"type": "checks", "from": "verification", "to": "output"},
                {"type": "supports", "from": "output", "to": "claim"},
            ],
        }
        overview = {
            "nodes": [
                {
                    "id": "overview:i0",
                    "label": "Execution iteration 1",
                    "attrs": {
                        "loop_scope": "execution",
                        "member_ids": ["plan", "call", "output", "verification", "claim"],
                        "focus_member_id": "plan",
                    },
                }
            ]
        }
        sequence = build_sequence_projection(trace_model, overview)
        self.assertEqual("sequence-projection-0.1", sequence["protocol_version"])
        self.assertFalse(sequence["principles"]["sequence_is_causality"])
        self.assertEqual("typed-partial-order-linearization", sequence["scopes"][0]["order_mode"])
        self.assertEqual(4, sequence["scopes"][0]["ordering_relation_count"])
        self.assertEqual(["plan", "call", "output", "verification", "claim"], [
            next(step for step in sequence["steps"] if step["id"] == step_id)["node_id"]
            for step_id in sequence["scopes"][0]["step_ids"]
        ])
        routes = {step["node_id"]: (step["from"], step["to"]) for step in sequence["steps"]}
        self.assertEqual(("agent", "tool"), routes["call"])
        self.assertEqual(("tool", "agent"), routes["output"])
        self.assertEqual(("agent", "user"), routes["claim"])
        self.assertEqual(["feedback"], [
            next(step for step in sequence["steps"] if step["id"] == step_id)["node_id"]
            for step_id in sequence["scopes"][1]["step_ids"]
        ])
        puml = render_sequence_plantuml(sequence)
        self.assertIn("title Agent execution — sequence projection", puml)
        self.assertIn("agent -> tool : [ToolCall] Search callers", puml)
        self.assertIn("tool --> agent : [ToolOutput] Matched two callers", puml)

    def test_control_cycle_is_condensed_without_input_order_dependent_fake_ranks(self) -> None:
        nodes = [
            {"id": node_id, "type": "Action", "label": node_id, "attrs": {}, "event_ids": []}
            for node_id in ("a", "b", "c")
        ]
        edges = [
            {"id": "a-b", "type": "precedes", "from": "a", "to": "b", "attrs": {}},
            {"id": "b-c", "type": "precedes", "from": "b", "to": "c", "attrs": {}},
            {"id": "c-a", "type": "precedes", "from": "c", "to": "a", "attrs": {}},
        ]
        base = {
            "graph_id": "cycle", "root_id": "a", "generated_at": "2026-01-01T00:00:00Z",
            "stats": {"node_count": 3, "edge_count": 3},
        }
        first = build_trace_model({**base, "nodes": nodes, "edges": edges}, [])
        reversed_model = build_trace_model(
            {**base, "nodes": list(reversed(nodes)), "edges": list(reversed(edges))}, []
        )
        first_ranks = {node["id"]: node["rank"] for node in first["nodes"]}
        reversed_ranks = {node["id"]: node["rank"] for node in reversed_model["nodes"]}
        self.assertEqual(first_ranks, reversed_ranks)
        self.assertEqual({0}, set(first_ranks.values()))

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

    def test_explicit_nested_loops_are_distinct_and_contraction_is_traceable(self) -> None:
        node_specs = [
            ("round", "DialogueRound", "Round", {"index": 0, "trigger_type": "initial_request"}),
            ("iteration", "ExecutionIteration", "Iteration", {"index": 0}),
            ("feedback", "UserFeedback", "Request", {}),
            ("goal", "Goal", "Goal", {}),
            ("plan", "Plan", "Plan", {}),
            ("call", "ToolCall", "Call", {}),
            ("output", "ToolOutput", "Output", {}),
            ("evaluation", "Evaluation", "Evaluate", {}),
            ("response", "AgentResponse", "Response", {}),
        ]
        nodes = [
            {
                "id": node_id, "type": node_type, "label": label, "attrs": attrs,
                "event_ids": [], "first_sequence": index,
                "provenance": {"capture_modes": ["synthetic"], "source_refs": ["test"], "run_ids": []},
            }
            for index, (node_id, node_type, label, attrs) in enumerate(node_specs, start=1)
        ]
        edge_specs = [
            ("round-iteration", "contains", "round", "iteration"),
            ("round-feedback", "contains", "round", "feedback"),
            ("round-goal", "contains", "round", "goal"),
            ("round-response", "contains", "round", "response"),
            ("iteration-plan", "contains", "iteration", "plan"),
            ("iteration-call", "contains", "iteration", "call"),
            ("iteration-output", "contains", "iteration", "output"),
            ("iteration-evaluation", "contains", "iteration", "evaluation"),
            ("feedback-goal", "informs", "feedback", "goal"),
            ("goal-plan", "frames", "goal", "plan"),
            ("plan-call", "invokes", "plan", "call"),
            ("call-output", "produces", "call", "output"),
            ("call-evaluation", "precedes", "call", "evaluation"),
            ("evaluation-call", "retry_of", "evaluation", "call"),
            ("evaluation-response", "informs", "evaluation", "response"),
        ]
        edges = [
            {
                "id": edge_id, "type": edge_type, "from": source, "to": target,
                "attrs": {},
                "provenance": {"capture_modes": ["synthetic"], "source_refs": ["test"], "run_ids": []},
            }
            for edge_id, edge_type, source, target in edge_specs
        ]
        graph = {
            "graph_id": "graph", "root_id": "round", "generated_at": "2026-01-01T00:00:00Z",
            "nodes": nodes, "edges": edges, "stats": {"node_count": len(nodes), "edge_count": len(edges)},
        }
        trace = build_trace_model(graph, [])
        original_nodes = json.loads(json.dumps(graph["nodes"]))
        analysis = analyze_loops(graph)
        overview = build_loop_projection(graph, trace)
        self.assertEqual("explicit", analysis["mode"])
        self.assertEqual(1, len(analysis["dialogue_rounds"]))
        self.assertEqual(1, len(analysis["execution_iterations"]))
        self.assertIsNone(analysis["signals"]["first_attempt_success_observed"])
        self.assertEqual(2, overview["metrics"]["overview_node_count"])
        self.assertLess(overview["metrics"]["compression_ratio"], 1)
        self.assertTrue(overview["principles"]["all_members_traceable"])
        self.assertTrue(overview["principles"]["all_source_nodes_accounted"])
        self.assertEqual([], overview["unmapped_node_ids"])
        self.assertEqual([], overview["unmapped_edge_ids"])
        self.assertIn("goal-plan", {
            edge_id
            for edge in overview["edges"]
            for edge_id in edge["attrs"]["original_edge_ids"]
        })
        execution = next(
            node for node in overview["nodes"] if node["attrs"]["loop_scope"] == "execution"
        )
        self.assertIn("iteration", execution["attrs"]["member_ids"])
        self.assertEqual("round", execution["attrs"]["parent_group_id"])
        self.assertEqual(
            {"call-evaluation", "evaluation-call"},
            set(execution["attrs"]["cycle_edge_ids"]),
        )
        self.assertEqual(
            {"contains", "frames", "informs", "invokes"},
            {
                edge["type"]
                for edge in overview["edges"]
                if edge["from"] != edge["to"]
            },
        )
        reversed_graph = {**graph, "nodes": list(reversed(nodes)), "edges": list(reversed(edges))}
        self.assertEqual(
            overview,
            build_loop_projection(reversed_graph, build_trace_model(reversed_graph, [])),
        )
        self.assertEqual(original_nodes, graph["nodes"])

    def test_planless_graph_still_gets_a_conservative_loop_overview(self) -> None:
        graph = {
            "graph_id": "graph", "root_id": "goal", "generated_at": "2026-01-01T00:00:00Z",
            "nodes": [
                {"id": "goal", "type": "Goal", "label": "Goal", "attrs": {}, "event_ids": [], "first_sequence": 1},
                {"id": "action", "type": "Action", "label": "Action", "attrs": {}, "event_ids": [], "first_sequence": 2},
            ],
            "edges": [], "stats": {"node_count": 2, "edge_count": 0},
        }
        overview = build_loop_projection(graph, build_trace_model(graph, []))
        self.assertEqual("display-fallback", overview["mode"])
        self.assertEqual(1, overview["metrics"]["dialogue_round_count"])
        self.assertEqual(1, overview["metrics"]["execution_iteration_count"])
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
        sequence_puml = (out / "sequence.puml").read_text(encoding="utf-8")
        html = (out / "graph.html").read_text(encoding="utf-8")
        for node in model["nodes"]:
            if node["primary"]:
                self.assertIn(node["label"][:92], puml)
            else:
                self.assertNotIn(node["label"][:92], puml)
            self.assertIn(node["id"], html)
        self.assertIn("top to bottom direction", puml)
        self.assertIn("layered DAG", puml)
        self.assertIn("sequence projection", sequence_puml)
        self.assertIn("sequence_is_causality", (out / "trace-model.json").read_text(encoding="utf-8"))
        self.assertNotIn("supports", puml)
        self.assertIn('id="timeline"', html)
        self.assertIn('id="graphSvg"', html)
        self.assertIn('id="details"', html)
        self.assertIn('data-view="workflow"', html)
        self.assertIn('data-view="overview"', html)
        self.assertIn('data-view="sequence"', html)
        self.assertIn('data-view="evidence"', html)
        self.assertIn('data-view="trace"', html)
        self.assertIn('id="sequenceScopeSelect"', html)
        self.assertIn("function renderSequence", html)
        self.assertIn('"data-edge-label":edge.type', html)
        self.assertIn("claim-to-evidence", (out / "trace-model.json").read_text(encoding="utf-8"))
        self.assertEqual(PROTOCOL_VERSION, receipt["protocol_version"])
        self.assertTrue((out / "loop-model.json").is_file())
        self.assertTrue((out / "sequence-model.json").is_file())
        self.assertTrue((out / "runtime-advice.json").is_file())
        self.assertTrue((out / "sequence.puml").is_file())
        self.assertEqual(64, len(receipt["outputs"]["graph.html"]["sha256"]))
        self.assertEqual(64, len(receipt["outputs"]["runtime-advice.json"]["sha256"]))

    def test_projection_removes_known_legacy_mermaid_output(self) -> None:
        events = load_events(QUICKSTART)
        graph = project_events(events)
        out = self.root / "generated"
        out.mkdir()
        (out / "graph.mmd").write_text("legacy", encoding="utf-8")
        write_projection(out, graph=graph, events=events, findings=[], title="Reset")
        self.assertFalse((out / "graph.mmd").exists())
        self.assertTrue((out / "trace.puml").exists())
        self.assertTrue((out / "sequence.puml").exists())

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
