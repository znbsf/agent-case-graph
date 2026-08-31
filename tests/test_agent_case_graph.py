from __future__ import annotations

import hashlib
import json
import re
import shutil
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from agent_case_graph.importer import import_issue_events
from agent_case_graph.ledger import append_event, write_new_ledger
from agent_case_graph.lint import lint_graph
from agent_case_graph.localization import load_display_locales
from agent_case_graph.model import ACGError, CASE_STATES, SCHEMA_VERSION, load_events
from agent_case_graph.projector import project_events
from agent_case_graph.renderer import write_projection
from agent_case_graph.runtime import build_runtime_snapshot, validate_step_transition


def _event(
    sequence: int,
    kind: str,
    payload: dict,
    *,
    case_id: str = "CASE-TEST",
    run_id: str | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": f"evt-test-{sequence:03d}",
        "case_id": case_id,
        "run_id": run_id,
        "sequence": sequence,
        "occurred_at": f"2026-08-31T10:00:{sequence:02d}+08:00",
        "kind": kind,
        "actor": {"type": "agent", "id": "test"},
        "provenance": {"capture_mode": "synthetic", "source_refs": ["unit-test"]},
        **payload,
    }


def _base_events(*, case_status: str = "intake") -> list[dict]:
    return [
        _event(
            1,
            "graph.declared",
            {
                "graph": {
                    "id": "graph:case:CASE-TEST",
                    "type": "case",
                    "root_id": "case:CASE-TEST",
                    "schema_version": SCHEMA_VERSION,
                }
            },
        ),
        _event(
            2,
            "node.recorded",
            {
                "node": {
                    "id": "case:CASE-TEST",
                    "type": "Case",
                    "label": "Synthetic test case",
                    "attrs": {"status": case_status, "capture_mode": "synthetic"},
                }
            },
        ),
        _event(
            3,
            "node.recorded",
            {
                "node": {
                    "id": "run:CASE-TEST:001",
                    "type": "Run",
                    "label": "Synthetic run",
                    "attrs": {"status": "running", "capture_mode": "synthetic"},
                }
            },
            run_id="run:CASE-TEST:001",
        ),
        _event(
            4,
            "edge.recorded",
            {
                "edge": {
                    "id": "edge:test:has-run",
                    "type": "has_run",
                    "from": "case:CASE-TEST",
                    "to": "run:CASE-TEST:001",
                    "attrs": {},
                }
            },
            run_id="run:CASE-TEST:001",
        ),
    ]


def _runtime_events(
    *, approval_status: str = "granted", approval_scope: str = "repo"
) -> list[dict]:
    events = _base_events()
    definitions = [
        (
            "node.recorded",
            {
                "node": {
                    "id": "run:CASE-TEST:001",
                    "type": "Run",
                    "label": "Synthetic run",
                    "attrs": {"status": "running", "capture_mode": "live"},
                }
            },
        ),
        (
            "node.recorded",
            {
                "node": {
                    "id": "approval:test",
                    "type": "Approval",
                    "label": "Approve runtime mutation",
                    "attrs": {"status": approval_status, "scope": approval_scope},
                }
            },
        ),
        (
            "node.recorded",
            {
                "node": {
                    "id": "target:test",
                    "type": "Target",
                    "label": "Runtime target",
                    "attrs": {"path": "repo/file.txt"},
                }
            },
        ),
        (
            "node.recorded",
            {
                "node": {
                    "id": "step:test:inspect",
                    "type": "Step",
                    "label": "Inspect evidence",
                    "attrs": {"runtime_managed": True, "status": "completed"},
                }
            },
        ),
        (
            "node.recorded",
            {
                "node": {
                    "id": "action:test:change",
                    "type": "Action",
                    "label": "Apply bounded change",
                    "attrs": {
                        "runtime_managed": True,
                        "status": "pending",
                        "mutating": True,
                        "authorized_scope": "repo",
                        "priority": 10,
                    },
                }
            },
        ),
        (
            "node.recorded",
            {
                "node": {
                    "id": "verification:test",
                    "type": "Verification",
                    "label": "Verify bounded change",
                    "attrs": {"runtime_managed": True, "status": "pending"},
                }
            },
        ),
        (
            "edge.recorded",
            {
                "edge": {
                    "id": "edge:run:inspect",
                    "type": "contains",
                    "from": "run:CASE-TEST:001",
                    "to": "step:test:inspect",
                    "attrs": {},
                }
            },
        ),
        (
            "edge.recorded",
            {
                "edge": {
                    "id": "edge:run:action",
                    "type": "contains",
                    "from": "run:CASE-TEST:001",
                    "to": "action:test:change",
                    "attrs": {},
                }
            },
        ),
        (
            "edge.recorded",
            {
                "edge": {
                    "id": "edge:run:verification",
                    "type": "contains",
                    "from": "run:CASE-TEST:001",
                    "to": "verification:test",
                    "attrs": {},
                }
            },
        ),
        (
            "edge.recorded",
            {
                "edge": {
                    "id": "edge:inspect:action",
                    "type": "precedes",
                    "from": "step:test:inspect",
                    "to": "action:test:change",
                    "attrs": {},
                }
            },
        ),
        (
            "edge.recorded",
            {
                "edge": {
                    "id": "edge:action:verification",
                    "type": "precedes",
                    "from": "action:test:change",
                    "to": "verification:test",
                    "attrs": {},
                }
            },
        ),
        (
            "edge.recorded",
            {
                "edge": {
                    "id": "edge:action:approval",
                    "type": "approved_by",
                    "from": "action:test:change",
                    "to": "approval:test",
                    "attrs": {},
                }
            },
        ),
        (
            "edge.recorded",
            {
                "edge": {
                    "id": "edge:action:target",
                    "type": "targets",
                    "from": "action:test:change",
                    "to": "target:test",
                    "attrs": {},
                }
            },
        ),
    ]
    for kind, payload in definitions:
        events.append(
            _event(
                len(events) + 1,
                kind,
                payload,
                run_id="run:CASE-TEST:001",
            )
        )

    transitions = [
        ("intake", "observe"),
        ("observe", "analyze"),
        ("analyze", "plan"),
        ("plan", "authorize"),
        ("authorize", "execute"),
    ]
    for from_state, to_state in transitions:
        events.append(
            _event(
                len(events) + 1,
                "state.changed",
                {
                    "transition": {
                        "subject_id": "case:CASE-TEST",
                        "from": from_state,
                        "to": to_state,
                        "reason": "runtime unit test",
                    }
                },
                run_id="run:CASE-TEST:001",
            )
        )
    return events


class AgentCaseGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch_parent = Path(__file__).resolve().parent / ".test-tmp"
        self.scratch_parent.mkdir(exist_ok=True)
        self.temp_root = self.scratch_parent / f"case-{uuid.uuid4().hex}"
        self.temp_root.mkdir()

    def tearDown(self) -> None:
        if self.temp_root.parent.resolve() != self.scratch_parent.resolve():
            raise AssertionError(f"refusing unsafe test cleanup: {self.temp_root}")
        shutil.rmtree(self.temp_root, ignore_errors=True)
        try:
            self.scratch_parent.rmdir()
        except OSError:
            pass

    def test_public_quickstart_projects_without_lint_errors(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        ledger = repository_root / "examples" / "quickstart" / "events.jsonl"
        events = load_events(ledger)
        graph = project_events(events, ledger_path=ledger)
        findings = lint_graph(graph)
        self.assertEqual([], [item for item in findings if item["severity"] == "error"])
        self.assertEqual("case:DEMO-001", graph["root_id"])
        self.assertIn(graph["nodes"][0]["attrs"]["current_state"], CASE_STATES)
        runtime = graph["runtime"]["runs"][0]
        self.assertEqual((1, 1, 0, 1, 0), tuple(len(runtime[lane]) for lane in ("completed", "running", "ready", "blocked", "failed")))
        replay = graph["replay"]["runs"][0]
        self.assertEqual("synthetic-ledger", replay["actual"]["track_kind"])
        self.assertEqual("available", replay["retrospective"]["status"])
        self.assertEqual(3, len(replay["retrospective"]["steps"]))
        self.assertFalse(replay["actual"]["track_kind"].startswith("execution-"))


    def test_ledger_rejects_non_contiguous_sequence(self) -> None:
        events = _base_events()
        events[3]["sequence"] = 8
        ledger = self.temp_root / "bad.jsonl"
        ledger.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
        with self.assertRaisesRegex(ACGError, "expected sequence 4"):
            load_events(ledger)

    def test_lint_requires_approval_for_mutating_action(self) -> None:
        events = _base_events()
        events.append(
            _event(
                5,
                "node.recorded",
                {
                    "node": {
                        "id": "action:test:write",
                        "type": "Action",
                        "label": "Write a file",
                        "attrs": {"mutating": True},
                    }
                },
            )
        )
        graph = project_events(events)
        codes = {item["code"] for item in lint_graph(graph)}
        self.assertIn("ACG011", codes)

    def test_lint_requires_receipt_for_completed_case(self) -> None:
        graph = project_events(_base_events(case_status="completed"))
        codes = {item["code"] for item in lint_graph(graph)}
        self.assertIn("ACG014", codes)

    def test_historical_import_is_read_only_and_reconstructed(self) -> None:
        issue = self.temp_root / "issue" / "CASE-HISTORY"
        issue.mkdir(parents=True)
        readme = issue / "README.md"
        evidence = issue / "EVIDENCE.md"
        readme.write_text(
            "# Historical case\n\n## Current Conclusion\n\nTBD\n\n## Verified\n\nTBD\n\n## Not Verified\n\n- device replay\n",
            encoding="utf-8",
        )
        evidence.write_text(
            "# Evidence Ledger\n\n"
            "| Time | Type | Command / Source | Output | Conclusion | Risk |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 2026-01-01 | log | sample.log | value=1 | parser saw value | device not replayed |\n",
            encoding="utf-8",
        )
        before = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (readme, evidence)
        }
        events = import_issue_events(issue, workspace_root=self.temp_root)
        after = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (readme, evidence)
        }
        self.assertEqual(before, after)
        self.assertTrue(
            all(event["provenance"]["capture_mode"] == "reconstructed" for event in events)
        )
        graph = project_events(events)
        self.assertEqual([], [item for item in lint_graph(graph) if item["severity"] == "error"])
        self.assertTrue(any(node["type"] == "Uncertainty" for node in graph["nodes"]))
        self.assertTrue(any(edge["type"] == "supports" for edge in graph["edges"]))
        replay_run = graph["replay"]["runs"][0]
        self.assertEqual("reconstructed-ledger", replay_run["actual"]["track_kind"])
        self.assertEqual("reconstructed", replay_run["actual"]["completeness"])
        self.assertEqual("unavailable", replay_run["retrospective"]["status"])

    def test_append_event_and_self_contained_projection(self) -> None:
        ledger = self.temp_root / "events.jsonl"
        write_new_ledger(ledger, _base_events())
        appended = append_event(
            ledger,
            case_id="CASE-TEST",
            kind="node.recorded",
            actor_type="agent",
            actor_id="unit-test",
            capture_mode="live",
            source_refs=["unit-test"],
            payload={
                "node": {
                    "id": "goal:test",
                    "type": "Goal",
                    "label": "Verify append-only record",
                    "attrs": {},
                }
            },
        )
        self.assertEqual(5, appended["sequence"])
        events = load_events(ledger)
        graph = project_events(events, ledger_path=ledger)
        findings = lint_graph(graph)
        locale_dir = ledger.parent / "locales"
        locale_dir.mkdir()
        (locale_dir / "zh-CN.json").write_text(
            json.dumps(
                {
                    "locale": "zh-CN",
                    "title": "合成投影",
                    "nodes": {"goal:test": "验证只追加记录"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        display_locales = load_display_locales(ledger)
        out_dir = self.temp_root / "projection"
        receipt = write_projection(
            out_dir,
            graph=graph,
            events=events,
            findings=findings,
            title="Synthetic projection",
            display_locales=display_locales,
        )
        html_text = (out_dir / "graph.html").read_text(encoding="utf-8")
        dom_id_list = re.findall(r'id="([^"]+)"', html_text)
        dom_ids = set(dom_id_list)
        referenced_ids = set(re.findall(r'getElementById\("([^"]+)"\)', html_text))
        self.assertEqual(len(dom_id_list), len(dom_ids))
        self.assertEqual(set(), referenced_ids - dom_ids)
        locale_block = re.search(r'"zh-CN": \{([\s\S]*?)\n  \},\n  "en-US": \{([\s\S]*?)\n  \}\n\};', html_text)
        self.assertIsNotNone(locale_block)
        locale_key_sets = [set(re.findall(r"(?m)^\s{4}([A-Za-z][A-Za-z0-9_]*):", block)) for block in locale_block.groups()]
        self.assertEqual(locale_key_sets[0], locale_key_sets[1])
        static_i18n_keys = set(re.findall(r'data-i18n(?:-aria)?="([^"]+)"', html_text))
        literal_message_keys = set(re.findall(r'message\("([^"]+)"', html_text))
        self.assertEqual(set(), (static_i18n_keys | literal_message_keys) - locale_key_sets[0])
        self.assertIn("Verify append-only record", html_text)
        self.assertIn("验证只追加记录", html_text)
        self.assertIn('id="languageSelect"', html_text)
        self.assertIn('value="zh-CN"', html_text)
        self.assertIn('value="en-US"', html_text)
        self.assertIn('id="spatialView"', html_text)
        self.assertIn('data-spatial-mode="flow"', html_text)
        self.assertIn('data-spatial-mode="orthogonal"', html_text)
        self.assertIn('data-spatial-mode="parallel"', html_text)
        self.assertEqual(1, html_text.count('data-workspace-mode="overview"'))
        self.assertEqual(1, html_text.count('data-workspace-mode="plan"'))
        self.assertEqual(1, html_text.count('data-workspace-mode="run"'))
        self.assertEqual(1, html_text.count('data-workspace-mode="review"'))
        self.assertEqual(1, html_text.count('data-workspace-mode="evidence"'))
        self.assertNotIn('data-workspace-mode="orthogonal"', html_text)
        self.assertNotIn('data-workspace-mode="parallel"', html_text)
        self.assertIn('data-i18n="tabOverview"', html_text)
        self.assertIn('data-i18n="tabPlan"', html_text)
        self.assertIn('data-i18n="tabRun"', html_text)
        self.assertIn('data-i18n="tabReview"', html_text)
        self.assertIn('data-i18n="tabEvidence"', html_text)
        self.assertIn('class="tab active" type="button" role="tab" aria-selected="true" data-workspace-mode="overview"', html_text)
        self.assertIn('id="planViewSelect"', html_text)
        self.assertIn('id="overviewView"', html_text)
        self.assertIn('id="runView"', html_text)
        self.assertIn('id="reviewView"', html_text)
        self.assertIn('id="evidenceView"', html_text)
        self.assertEqual(1, html_text.count('section class="semantic-layer" data-semantic-layer="knowledge"'))
        self.assertEqual(1, html_text.count('section class="semantic-layer" data-semantic-layer="control"'))
        self.assertEqual(1, html_text.count('section class="semantic-layer" data-semantic-layer="execution"'))
        self.assertIn('id="spatialSvg"', html_text)
        self.assertIn('id="spatialViewport"', html_text)
        self.assertIn('id="spatialScene"', html_text)
        self.assertIn('id="caseContext"', html_text)
        self.assertIn('id="flowLegendCard"', html_text)
        self.assertIn('id="spatialLayerHud"', html_text)
        self.assertIn('id="detailsDrawer"', html_text)
        self.assertIn('id="qualityButton"', html_text)
        self.assertNotIn('id="timelineButton"', html_text)
        self.assertNotIn('id="replayButton"', html_text)
        self.assertIn('id="reviewReplayButton"', html_text)
        self.assertIn('id="replayHud"', html_text)
        self.assertIn('id="planSummary"', html_text)
        self.assertIn('id="planWorkbench"', html_text)
        self.assertIn('id="planInspector"', html_text)
        self.assertIn('id="replayTrackTabs"', html_text)
        self.assertEqual(1, html_text.count('data-replay-mode="ledger"'))
        self.assertEqual(1, html_text.count('data-replay-mode="plan"'))
        self.assertEqual(1, html_text.count('data-replay-mode="candidate"'))
        self.assertEqual(1, html_text.count('data-replay-mode="observed"'))
        self.assertIn('id="replayStrip"', html_text)
        self.assertIn('id="replayDetails"', html_text)
        self.assertIn('id="replayRange"', html_text)
        self.assertIn('id="replayLast"', html_text)
        self.assertIn('aria-label="播放位置"', html_text)
        self.assertIn("function renderSpatial", html_text)
        self.assertIn("function renderWorkspace", html_text)
        self.assertIn("function renderWorkspaceOverview", html_text)
        self.assertIn("function renderRuntimeWorkspace", html_text)
        self.assertIn("function renderReviewWorkspace", html_text)
        self.assertIn("function renderEvidenceWorkspace", html_text)
        self.assertIn("function explicitRelationPaths", html_text)
        self.assertIn("function renderOverviewRelations", html_text)
        self.assertIn("function renderFlowSpatial", html_text)
        self.assertIn("function buildFlowLayout", html_text)
        self.assertIn("function flowTaskNodes", html_text)
        self.assertIn('const FLOW_ORDER_EDGE_TYPES = new Set(["precedes"]);', html_text)
        self.assertIn('const FLOW_TASK_NODE_TYPES = new Set(["Step", "Action", "Verification"]);', html_text)
        self.assertIn('return relation.type === "precedes";', html_text)
        self.assertIn("function explicitFlowRanks", html_text)
        self.assertIn("function relationFamily", html_text)
        self.assertIn("function clipSpatialEndpoints", html_text)
        self.assertIn("function buildRelationLaneOffsets", html_text)
        self.assertIn("function replayVisualState", html_text)
        self.assertIn("function replayPlanModel", html_text)
        self.assertIn("function renderPlanWorkbench", html_text)
        self.assertIn("function renderReplayPlanStrip", html_text)
        self.assertIn("function renderReplayItemStrip", html_text)
        self.assertIn("function hasObservedExecutionTrack", html_text)
        self.assertIn("function ledgerReplayTrack", html_text)
        self.assertIn("function observedReplayTrack", html_text)
        self.assertIn('replayState.mode === "observed" && hasObservedExecutionTrack(snapshot)', html_text)
        self.assertIn('let replayMode = "ledger";', html_text)
        self.assertIn('track.track_kind.endsWith("-ledger")', html_text)
        self.assertIn('message("replayObservedUnavailable")', html_text)
        self.assertIn("if (hasCycle) return {rank: new Map", html_text)
        self.assertIn('message("flowCycleWarning")', html_text)
        self.assertIn("return runs[0];", html_text)
        self.assertIn("right.first_sequence", html_text)
        self.assertIn('points: [{x:0,y:0,z:0},{x:size,y:0,z:0},{x:size,y:size,z:0},{x:0,y:size,z:0}]', html_text)
        self.assertIn('line.dataset.modelFrom = "0,0,0"', html_text)
        self.assertIn('button.dataset.modelPoint = instance.point.x', html_text)
        self.assertIn('"x>=0;y>=0;z>=0"', html_text)
        self.assertIn('Math.max(320, stage.clientWidth', html_text)
        self.assertIn("结构三面", html_text)
        self.assertIn("三层投影", html_text)
        self.assertIn("三层语义总览", html_text)
        self.assertIn("复盘结论与缺口", html_text)
        self.assertIn("四条顺序轨道分开检查", html_text)
        self.assertIn("Knowledge", html_text)
        self.assertIn("Control", html_text)
        self.assertIn("Execution", html_text)
        self.assertIn("主线关系", html_text)
        self.assertIn('let workspaceMode = "overview";', html_text)
        self.assertIn('let spatialMode = "flow";', html_text)
        self.assertIn('row.dataset.trackKind = kind;', html_text)
        self.assertIn('button.dataset.entityKind = "runtime-instance";', html_text)
        self.assertIn('button.dataset.instanceId = (snapshot && snapshot.run_id', html_text)
        self.assertIn('hasObservedExecutionTrack(snapshot) ? "available" : "unavailable"', html_text)
        self.assertIn('message("runZeroStates"', html_text)
        self.assertIn("repeat(auto-fit, minmax(220px, 1fr))", html_text)
        self.assertIn('.evidence-chains { min-width: 0;', html_text)
        self.assertIn('.semantic-stack { min-width: 0; }', html_text)
        self.assertIn('.overview-relations { display: none; }', html_text)
        self.assertNotIn("let replayVisible", html_text)
        self.assertNotIn("function renderTimeline", html_text)
        self.assertIn("Runtime 状态快照可用，但没有已观测执行遥测", html_text)
        self.assertIn('markerUnits: "userSpaceOnUse"', html_text)
        self.assertIn('@media (prefers-reduced-motion: reduce)', html_text)
        self.assertIn('repeatCount: "1"', html_text)
        self.assertNotIn('repeatCount: "indefinite"', html_text)
        self.assertNotIn("explicitRunFlow", html_text)
        self.assertNotIn("retrospectiveOrderMap", html_text)
        self.assertNotIn("primaryFlowLane", html_text)
        self.assertNotIn("button.dataset.flowLane", html_text)
        self.assertNotIn("SPATIAL_FLOW_TYPES", html_text)
        self.assertNotIn("src=\"http", html_text)
        self.assertEqual("spatial-0.1", graph["spatial"]["protocol_version"])
        self.assertEqual("replay-0.1", graph["replay"]["protocol_version"])
        self.assertTrue(graph["replay"]["visual_only"])
        self.assertFalse(graph["replay"]["reexecutes_actions"])
        self.assertNotIn("验证只追加记录", (out_dir / "graph.json").read_text(encoding="utf-8"))
        self.assertNotIn("验证只追加记录", (out_dir / "graph.mmd").read_text(encoding="utf-8"))
        self.assertEqual(64, len(receipt["outputs"]["graph.html"]["sha256"]))
        self.assertEqual(["zh-CN"], receipt["display"]["locales"])
        self.assertTrue((out_dir / "projection-receipt.json").is_file())

    def test_state_transition_lint_detects_invalid_skip(self) -> None:
        events = _base_events()
        events.append(
            _event(
                5,
                "state.changed",
                {
                    "transition": {
                        "subject_id": "case:CASE-TEST",
                        "from": "intake",
                        "to": "execute",
                        "reason": "invalid test skip",
                    }
                },
            )
        )
        codes = {item["code"] for item in lint_graph(project_events(events))}
        self.assertIn("ACG016", codes)

    def test_runtime_frontier_advances_only_after_checkpoint(self) -> None:
        events = _runtime_events()
        graph = project_events(events)
        snapshot = build_runtime_snapshot(graph, run_id="run:CASE-TEST:001")
        self.assertEqual("configured", snapshot["status"])
        self.assertEqual(["action:test:change"], [item["id"] for item in snapshot["ready"]])
        self.assertEqual(
            ["verification:test"], [item["id"] for item in snapshot["blocked"]]
        )
        self.assertLess(
            snapshot["ready"][0]["context"]["selected_node_count"],
            snapshot["ready"][0]["context"]["full_graph_node_count"],
        )
        node, _ = validate_step_transition(
            graph,
            node_id="action:test:change",
            to_status="running",
            run_id="run:CASE-TEST:001",
        )
        self.assertEqual("Action", node["type"])

        events.append(
            _event(
                len(events) + 1,
                "node.recorded",
                {
                    "node": {
                        "id": "action:test:change",
                        "type": "Action",
                        "label": "Apply bounded change",
                        "attrs": {"runtime_managed": True, "status": "running"},
                    }
                },
                run_id="run:CASE-TEST:001",
            )
        )
        running_graph = project_events(events)
        validate_step_transition(
            running_graph,
            node_id="action:test:change",
            to_status="completed",
            run_id="run:CASE-TEST:001",
        )
        events.append(
            _event(
                len(events) + 1,
                "node.recorded",
                {
                    "node": {
                        "id": "action:test:change",
                        "type": "Action",
                        "label": "Apply bounded change",
                        "attrs": {"runtime_managed": True, "status": "completed"},
                    }
                },
                run_id="run:CASE-TEST:001",
            )
        )
        after = build_runtime_snapshot(
            project_events(events), run_id="run:CASE-TEST:001"
        )
        self.assertEqual(
            ["verification:test"], [item["id"] for item in after["ready"]]
        )
        self.assertEqual(1, len(project_events(events)["runtime"]["runs"]))

    def test_runtime_rejects_ungranted_or_mismatched_approval(self) -> None:
        for approval_status, approval_scope in (("requested", "repo"), ("granted", "other")):
            with self.subTest(status=approval_status, scope=approval_scope):
                graph = project_events(
                    _runtime_events(
                        approval_status=approval_status,
                        approval_scope=approval_scope,
                    )
                )
                snapshot = build_runtime_snapshot(graph, run_id="run:CASE-TEST:001")
                action = next(
                    item for item in snapshot["blocked"] if item["id"] == "action:test:change"
                )
                codes = {item["code"] for item in action["blockers"]}
                self.assertIn("approval_not_granted_or_scope_mismatch", codes)
                with self.assertRaisesRegex(ACGError, "not Ready"):
                    validate_step_transition(
                        graph,
                        node_id="action:test:change",
                        to_status="running",
                        run_id="run:CASE-TEST:001",
                    )

    def test_runtime_blocks_a_precedes_cycle(self) -> None:
        events = _runtime_events()
        events.append(
            _event(
                len(events) + 1,
                "edge.recorded",
                {
                    "edge": {
                        "id": "edge:verification:inspect",
                        "type": "precedes",
                        "from": "verification:test",
                        "to": "step:test:inspect",
                        "attrs": {},
                    }
                },
                run_id="run:CASE-TEST:001",
            )
        )
        snapshot = build_runtime_snapshot(
            project_events(events), run_id="run:CASE-TEST:001"
        )
        self.assertEqual("invalid", snapshot["status"])
        self.assertEqual(
            [
                "action:test:change",
                "verification:test",
                "step:test:inspect",
                "action:test:change",
            ],
            snapshot["cycle"],
        )
        self.assertEqual(
            {
                "action:test:change",
                "verification:test",
            },
            {
                item["id"]
                for item in snapshot["blocked"]
                if any(blocker["code"] == "precedes_cycle" for blocker in item["blockers"])
            },
        )


if __name__ == "__main__":
    unittest.main()
