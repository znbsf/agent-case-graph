from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any, Sequence

from .graph_runtime import (
    GRAPH_RUNTIME_PROTOCOL_VERSION,
    build_claim_gate,
    build_graph_runtime_advice,
    recommendation_record_attrs,
    resolve_claim_run_id,
)
from .importer import import_issue_events
from .inference import infer_workflow
from .ledger import append_event, atomic_write_text, canonical_json, sha256_file, write_new_ledger
from .lint import lint_graph
from .localization import load_display_locales
from .model import ACGError, SCHEMA_VERSION, load_events
from .projector import project_events
from .renderer import write_projection
from .runtime import (
    build_runtime_snapshot,
    render_runtime_snapshot,
    validate_step_transition,
)
from .replay import build_path_review


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("value must be a JSON object")
    return parsed


def _common_record_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--actor-type", choices=("human", "agent", "tool", "service"), default="agent")
    parser.add_argument("--actor-id", default="local-agent")
    parser.add_argument(
        "--capture-mode",
        choices=("live", "reconstructed", "synthetic"),
        default="live",
    )
    parser.add_argument("--source-ref", action="append", default=[])
    parser.add_argument("--occurred-at")


def _initial_case_events(
    *,
    case_id: str,
    title: str,
    run_id: str,
    capture_mode: str,
    actor_type: str,
    actor_id: str,
    source_refs: list[str],
) -> list[dict[str, Any]]:
    base_time = datetime.now().astimezone().replace(microsecond=0)
    definitions = [
        (
            "graph.declared",
            {
                "graph": {
                    "id": f"graph:case:{case_id}",
                    "type": "case",
                    "root_id": f"case:{case_id}",
                    "schema_version": SCHEMA_VERSION,
                }
            },
            None,
        ),
        (
            "node.recorded",
            {
                "node": {
                    "id": f"case:{case_id}",
                    "type": "Case",
                    "label": title,
                    "attrs": {"status": "intake", "capture_mode": capture_mode},
                }
            },
            None,
        ),
        (
            "node.recorded",
            {
                "node": {
                    "id": run_id,
                    "type": "Run",
                    "label": f"Run for {case_id}",
                    "attrs": {"status": "created", "capture_mode": capture_mode},
                }
            },
            run_id,
        ),
        (
            "edge.recorded",
            {
                "edge": {
                    "id": f"edge:{case_id}:has-run:{run_id}",
                    "type": "has_run",
                    "from": f"case:{case_id}",
                    "to": run_id,
                    "attrs": {},
                }
            },
            run_id,
        ),
    ]
    events: list[dict[str, Any]] = []
    for index, (kind, payload, event_run_id) in enumerate(definitions, start=1):
        events.append(
            {
                "schema_version": SCHEMA_VERSION,
                "event_id": f"evt-{uuid.uuid4().hex}",
                "case_id": case_id,
                "run_id": event_run_id,
                "sequence": index,
                "occurred_at": (base_time + timedelta(seconds=index - 1)).isoformat(),
                "kind": kind,
                "actor": {"type": actor_type, "id": actor_id},
                "provenance": {
                    "capture_mode": capture_mode,
                    "source_refs": source_refs,
                },
                **payload,
            }
        )
    return events


def _print_findings(findings: list[dict[str, Any]]) -> None:
    if not findings:
        print("Lint: 0 errors, 0 warnings")
        return
    for finding in findings:
        target = finding.get("node_id") or finding.get("edge_id") or "graph"
        print(
            f"{finding['severity'].upper():7} {finding['code']} {target}: {finding['message']}"
        )
    errors = sum(item["severity"] == "error" for item in findings)
    warnings = sum(item["severity"] == "warning" for item in findings)
    print(f"Lint: {errors} errors, {warnings} warnings")


def _cmd_doctor(args: argparse.Namespace) -> int:
    schema_root = files("agent_case_graph").joinpath("schemas")
    checks = {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "schema_version": SCHEMA_VERSION,
        "event_schema": schema_root.joinpath("event.schema.json").is_file(),
        "graph_schema": schema_root.joinpath("graph.schema.json").is_file(),
    }
    if args.ledger:
        events = load_events(args.ledger)
        checks["ledger"] = str(args.ledger)
        checks["ledger_events"] = len(events)
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if checks["event_schema"] and checks["graph_schema"] else 1


def _cmd_init_case(args: argparse.Namespace) -> int:
    run_id = args.run_id or f"run:{args.case_id}:001"
    events = _initial_case_events(
        case_id=args.case_id,
        title=args.title,
        run_id=run_id,
        capture_mode=args.capture_mode,
        actor_type=args.actor_type,
        actor_id=args.actor_id,
        source_refs=args.source_ref,
    )
    write_new_ledger(args.ledger, events, force=args.force)
    print(f"Wrote {args.ledger} ({len(events)} events)")
    return 0


def _cmd_validate_ledger(args: argparse.Namespace) -> int:
    events = load_events(args.ledger)
    print(
        json.dumps(
            {
                "ledger": str(args.ledger),
                "case_id": events[0]["case_id"],
                "events": len(events),
                "last_sequence": events[-1]["sequence"],
                "capture_modes": sorted(
                    {event["provenance"]["capture_mode"] for event in events}
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _load_project_lint(ledger: Path) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    events = load_events(ledger)
    graph = project_events(events, ledger_path=ledger)
    findings = lint_graph(graph)
    return events, graph, findings


def _load_history_graphs(ledgers: Sequence[Path]) -> list[dict[str, Any]]:
    """Load separate historical Case Ledgers without merging them into this Case."""

    graphs: list[dict[str, Any]] = []
    for ledger in ledgers:
        events = load_events(ledger)
        graphs.append(project_events(events, ledger_path=ledger))
    return graphs


def _cmd_lint(args: argparse.Namespace) -> int:
    _, _, findings = _load_project_lint(args.ledger)
    if args.json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
    else:
        _print_findings(findings)
    errors = any(item["severity"] == "error" for item in findings)
    warnings = any(item["severity"] == "warning" for item in findings)
    return 1 if errors or (args.strict and warnings) else 0


def _cmd_project(args: argparse.Namespace) -> int:
    events, graph, findings = _load_project_lint(args.ledger)
    root = next((node for node in graph["nodes"] if node["id"] == graph["root_id"]), None)
    title = args.title or (root["label"] if root else graph["graph_id"])
    display_locales = load_display_locales(args.ledger)
    receipt = write_projection(
        args.out_dir,
        graph=graph,
        events=events,
        findings=findings,
        title=title,
        display_locales=display_locales,
        default_locale=args.default_locale,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    has_errors = receipt["lint"]["errors"] > 0
    return 1 if has_errors and not args.allow_errors else 0


def _require_clean_runtime_graph(
    ledger: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events, graph, findings = _load_project_lint(ledger)
    errors = [item for item in findings if item["severity"] == "error"]
    if errors:
        codes = ", ".join(sorted({item["code"] for item in errors}))
        raise ACGError(f"runtime refuses a graph with lint errors: {codes}")
    return events, graph


def _cmd_next_actions(args: argparse.Namespace) -> int:
    _, graph = _require_clean_runtime_graph(args.ledger)
    snapshot = build_runtime_snapshot(graph, run_id=args.run_id)
    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        print(render_runtime_snapshot(snapshot))
    return 1 if snapshot["status"] == "invalid" else 0


def _cmd_step_status(args: argparse.Namespace) -> int:
    events, graph = _require_clean_runtime_graph(args.ledger)
    node, before = validate_step_transition(
        graph,
        node_id=args.node_id,
        to_status=args.status,
        run_id=args.run_id,
    )
    from_status = str(node.get("attrs", {}).get("status", "pending"))
    attempt = int(node.get("attrs", {}).get("attempt", 0) or 0)
    if args.status == "running":
        attempt += 1
    checkpoint_id = f"checkpoint:{args.node_id}:{len(events) + 1}"
    event = append_event(
        args.ledger,
        case_id=events[0]["case_id"],
        kind="node.recorded",
        actor_type=args.actor_type,
        actor_id=args.actor_id,
        capture_mode="live",
        source_refs=args.source_ref,
        payload={
            "node": {
                "id": node["id"],
                "type": node["type"],
                "label": node["label"],
                "attrs": {
                    "runtime_managed": True,
                    "status": args.status,
                    "runtime_reason": args.reason,
                    "runtime_checkpoint_id": checkpoint_id,
                    "attempt": attempt,
                },
            }
        },
        run_id=before["run_id"],
        occurred_at=args.occurred_at,
    )
    updated_events = load_events(args.ledger)
    updated_graph = project_events(updated_events, ledger_path=args.ledger)
    after = build_runtime_snapshot(updated_graph, run_id=before["run_id"])
    print(
        json.dumps(
            {
                "checkpoint": {
                    "id": checkpoint_id,
                    "event_id": event["event_id"],
                    "sequence": event["sequence"],
                    "node_id": node["id"],
                    "from": from_status,
                    "to": args.status,
                    "reason": args.reason,
                    "attempt": attempt,
                },
                "next_ready": [item["id"] for item in after["ready"]],
                "counts": after.get("counts", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_advise(args: argparse.Namespace) -> int:
    _, graph = _require_clean_runtime_graph(args.ledger)
    advice = build_graph_runtime_advice(
        graph,
        run_id=args.run_id,
        history_graphs=_load_history_graphs(args.history_ledger),
    )
    print(json.dumps(advice, ensure_ascii=False, indent=2))
    return 0


def _cmd_record_recommendation(args: argparse.Namespace) -> int:
    events, graph = _require_clean_runtime_graph(args.ledger)
    advice = build_graph_runtime_advice(
        graph,
        run_id=args.run_id,
        history_graphs=_load_history_graphs(args.history_ledger),
    )
    selected_run_id = advice.get("run_id")
    if not isinstance(selected_run_id, str) or not selected_run_id:
        raise ACGError("cannot record a runtime recommendation without a selected Run")
    source_hash = sha256_file(args.ledger)
    recommendation_id = f"decision:runtime-recommendation:{events[0]['case_id']}:{len(events) + 1}"
    event = append_event(
        args.ledger,
        case_id=events[0]["case_id"],
        kind="node.recorded",
        actor_type=args.actor_type,
        actor_id=args.actor_id,
        capture_mode=args.capture_mode,
        source_refs=sorted(set(args.source_ref + [f"ledger-sha256:{source_hash}"])),
        payload={
            "node": {
                "id": recommendation_id,
                "type": "Decision",
                "label": f"Graph-runtime recommendation #{len(events) + 1}",
                "attrs": recommendation_record_attrs(
                    advice, source_ledger_sha256=source_hash
                ),
            }
        },
        run_id=selected_run_id,
        occurred_at=args.occurred_at,
    )
    print(
        json.dumps(
            {
                "recommendation": {
                    "node_id": recommendation_id,
                    "event_id": event["event_id"],
                    "sequence": event["sequence"],
                    "run_id": selected_run_id,
                    "data_origin": "derived",
                    "not_native_telemetry": True,
                },
                "advice_status": advice["status"],
                "recommended_node_ids": event["node"]["attrs"]["recommended_node_ids"],
                "claim_gate_snapshot": event["node"]["attrs"]["claim_gate_snapshot"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_claim_status(args: argparse.Namespace) -> int:
    events, graph = _require_clean_runtime_graph(args.ledger)
    selected_run_id = args.run_id or resolve_claim_run_id(graph, args.claim_id)
    gate = build_claim_gate(graph, args.claim_id, run_id=selected_run_id)
    if args.status == "confirmed" and not gate["can_confirm"]:
        codes = ", ".join(sorted({item["code"] for item in gate["missing_evidence"]}))
        raise ACGError(
            f"Claim gate blocked confirmation for {args.claim_id}: {codes or 'evidence insufficient'}"
        )
    claim = gate["claim"]
    source_node_ids = gate["derivation"]["source_node_ids"]
    source_edge_ids = gate["derivation"]["source_edge_ids"]
    checkpoint_id = f"claim-gate:{args.claim_id}:{len(events) + 1}"
    event = append_event(
        args.ledger,
        case_id=events[0]["case_id"],
        kind="node.recorded",
        actor_type=args.actor_type,
        actor_id=args.actor_id,
        capture_mode=args.capture_mode,
        source_refs=args.source_ref,
        payload={
            "node": {
                "id": claim["id"],
                "type": claim["type"],
                "label": claim["label"],
                "attrs": {
                    "status": args.status,
                    "runtime_claim_gate": {
                        "checkpoint_id": checkpoint_id,
                        "protocol_version": GRAPH_RUNTIME_PROTOCOL_VERSION,
                        "data_origin": "derived",
                        "not_native_telemetry": True,
                        "gate_status": gate["status"],
                        "can_confirm": gate["can_confirm"],
                        "evidence_actualness": gate["evidence_actualness"],
                        "source_node_ids": source_node_ids,
                        "source_edge_ids": source_edge_ids,
                    },
                },
            }
        },
        run_id=selected_run_id,
        occurred_at=args.occurred_at,
    )
    print(
        json.dumps(
            {
                "checkpoint": {
                    "id": checkpoint_id,
                    "event_id": event["event_id"],
                    "sequence": event["sequence"],
                    "claim_id": claim["id"],
                    "to": args.status,
                },
                "gate": gate,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_review_paths(args: argparse.Namespace) -> int:
    events, graph, _ = _load_project_lint(args.ledger)
    print(json.dumps(build_path_review(graph, events), ensure_ascii=False, indent=2))
    return 0


def _cmd_import_issue(args: argparse.Namespace) -> int:
    events = import_issue_events(
        args.issue_dir,
        workspace_root=args.workspace_root,
        case_id=args.case_id,
        include_paths=args.include,
    )
    write_new_ledger(args.output, events, force=args.force)
    print(
        json.dumps(
            {
                "issue_dir": str(args.issue_dir),
                "output": str(args.output),
                "events": len(events),
                "capture_mode": "reconstructed",
                "input_was_modified": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_infer_workflow(args: argparse.Namespace) -> int:
    _, graph, _ = _load_project_lint(args.ledger)
    result = infer_workflow(graph, run_id=args.run_id)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(args.output, rendered)
        print(f"Wrote {args.output}")
    else:
        print(rendered, end="")
    return 1 if args.strict and result["gaps"] else 0


def _record_common(args: argparse.Namespace, *, kind: str, payload: dict[str, Any]) -> int:
    event = append_event(
        args.ledger,
        case_id=args.case_id,
        kind=kind,
        actor_type=args.actor_type,
        actor_id=args.actor_id,
        capture_mode=args.capture_mode,
        source_refs=args.source_ref,
        payload=payload,
        run_id=args.run_id,
        occurred_at=args.occurred_at,
    )
    print(canonical_json(event))
    return 0


def _cmd_record_node(args: argparse.Namespace) -> int:
    return _record_common(
        args,
        kind="node.recorded",
        payload={
            "node": {
                "id": args.node_id,
                "type": args.node_type,
                "label": args.label,
                "attrs": args.attrs,
            }
        },
    )


def _cmd_record_edge(args: argparse.Namespace) -> int:
    edge_id = args.edge_id or f"edge:{uuid.uuid4().hex}"
    return _record_common(
        args,
        kind="edge.recorded",
        payload={
            "edge": {
                "id": edge_id,
                "type": args.edge_type,
                "from": args.from_id,
                "to": args.to_id,
                "attrs": args.attrs,
            }
        },
    )


def _cmd_record_state(args: argparse.Namespace) -> int:
    return _record_common(
        args,
        kind="state.changed",
        payload={
            "transition": {
                "subject_id": args.subject_id,
                "from": args.from_state,
                "to": args.to_state,
                "reason": args.reason,
            }
        },
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="acg",
        description="Agent Case Graph local event ledger, projector and visualizer",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check the local runtime and optional ledger")
    doctor.add_argument("--ledger", type=Path)
    doctor.set_defaults(func=_cmd_doctor)

    init_case = subparsers.add_parser("init-case", help="create a new live/synthetic Case ledger")
    init_case.add_argument("--ledger", required=True, type=Path)
    init_case.add_argument("--case-id", required=True)
    init_case.add_argument("--title", required=True)
    init_case.add_argument("--run-id")
    init_case.add_argument("--capture-mode", choices=("live", "synthetic"), default="live")
    init_case.add_argument("--actor-type", choices=("human", "agent", "tool", "service"), default="agent")
    init_case.add_argument("--actor-id", default="local-agent")
    init_case.add_argument("--source-ref", action="append", default=[])
    init_case.add_argument("--force", action="store_true")
    init_case.set_defaults(func=_cmd_init_case)

    validate = subparsers.add_parser("validate-ledger", help="validate JSONL structure and ordering")
    validate.add_argument("ledger", type=Path)
    validate.set_defaults(func=_cmd_validate_ledger)

    lint = subparsers.add_parser("lint", help="run deterministic graph checks")
    lint.add_argument("ledger", type=Path)
    lint.add_argument("--json", action="store_true")
    lint.add_argument("--strict", action="store_true", help="treat warnings as failure")
    lint.set_defaults(func=_cmd_lint)

    project = subparsers.add_parser("project", help="generate JSON, PlantUML, HTML and receipt")
    project.add_argument("ledger", type=Path)
    project.add_argument("--out-dir", required=True, type=Path)
    project.add_argument("--title")
    project.add_argument("--default-locale", default="zh-CN")
    project.add_argument("--allow-errors", action="store_true")
    project.set_defaults(func=_cmd_project)

    next_actions = subparsers.add_parser(
        "next-actions",
        help="compute the ready runtime frontier, blockers and minimal context packets",
    )
    next_actions.add_argument("ledger", type=Path)
    next_actions.add_argument("--run-id")
    next_actions.add_argument("--json", action="store_true")
    next_actions.set_defaults(func=_cmd_next_actions)

    step_status = subparsers.add_parser(
        "step-status",
        help="append a guarded runtime checkpoint and recompute the ready frontier",
    )
    step_status.add_argument("--ledger", required=True, type=Path)
    step_status.add_argument("--node-id", required=True)
    step_status.add_argument(
        "--status",
        required=True,
        choices=("running", "completed", "failed", "blocked", "skipped"),
    )
    step_status.add_argument("--reason", required=True)
    step_status.add_argument("--run-id")
    step_status.add_argument(
        "--actor-type", choices=("human", "agent", "tool", "service"), default="agent"
    )
    step_status.add_argument("--actor-id", default="local-agent")
    step_status.add_argument("--source-ref", action="append", default=[])
    step_status.add_argument("--occurred-at")
    step_status.set_defaults(func=_cmd_step_status)

    advise = subparsers.add_parser(
        "advise",
        help="derive evidence gaps, Claim gates and next safe Action/ToolCall candidates",
    )
    advise.add_argument("ledger", type=Path)
    advise.add_argument("--run-id")
    advise.add_argument(
        "--history-ledger",
        action="append",
        type=Path,
        default=[],
        help="separate historical Case Ledger; only explicit reuse_key matches are considered",
    )
    advise.set_defaults(func=_cmd_advise)

    record_recommendation = subparsers.add_parser(
        "record-recommendation",
        help="append a derived Decision snapshot of current graph-runtime advice",
    )
    record_recommendation.add_argument("--ledger", required=True, type=Path)
    record_recommendation.add_argument("--run-id")
    record_recommendation.add_argument("--history-ledger", action="append", type=Path, default=[])
    record_recommendation.add_argument(
        "--actor-type", choices=("human", "agent", "tool", "service"), default="agent"
    )
    record_recommendation.add_argument("--actor-id", default="local-agent")
    record_recommendation.add_argument(
        "--capture-mode", choices=("live", "reconstructed", "synthetic"), default="live"
    )
    record_recommendation.add_argument("--source-ref", action="append", default=[])
    record_recommendation.add_argument("--occurred-at")
    record_recommendation.set_defaults(func=_cmd_record_recommendation)

    claim_status = subparsers.add_parser(
        "claim-status",
        help="append a Claim/RootCause status checkpoint; confirmed requires the graph Claim gate",
    )
    claim_status.add_argument("--ledger", required=True, type=Path)
    claim_status.add_argument("--claim-id", required=True)
    claim_status.add_argument(
        "--status",
        required=True,
        choices=("draft", "proposed", "confirmed", "blocked", "refuted"),
    )
    claim_status.add_argument("--run-id")
    claim_status.add_argument(
        "--actor-type", choices=("human", "agent", "tool", "service"), default="agent"
    )
    claim_status.add_argument("--actor-id", default="local-agent")
    claim_status.add_argument(
        "--capture-mode", choices=("live", "reconstructed", "synthetic"), default="live"
    )
    claim_status.add_argument("--source-ref", action="append", default=[])
    claim_status.add_argument("--occurred-at")
    claim_status.set_defaults(func=_cmd_claim_status)

    review_paths = subparsers.add_parser(
        "review-paths",
        help="compare recorded derived recommendations with later Ledger runtime records",
    )
    review_paths.add_argument("ledger", type=Path)
    review_paths.set_defaults(func=_cmd_review_paths)

    importer = subparsers.add_parser("import-issue", help="read-only historical issue import")
    importer.add_argument("issue_dir", type=Path)
    importer.add_argument("--workspace-root", required=True, type=Path)
    importer.add_argument("--output", required=True, type=Path)
    importer.add_argument("--case-id")
    importer.add_argument("--include", action="append", default=[])
    importer.add_argument("--force", action="store_true")
    importer.set_defaults(func=_cmd_import_issue)

    infer = subparsers.add_parser(
        "infer-workflow", help="reverse-infer goals, plans, actions, outputs and claims"
    )
    infer.add_argument("ledger", type=Path)
    infer.add_argument("--output", type=Path)
    infer.add_argument("--run-id", help="select one Run when a graph contains multiple runs")
    infer.add_argument("--strict", action="store_true", help="fail when semantic gaps remain")
    infer.set_defaults(func=_cmd_infer_workflow)

    record_node = subparsers.add_parser("record-node", help="append a node.recorded event")
    _common_record_args(record_node)
    record_node.add_argument("--node-id", required=True)
    record_node.add_argument("--node-type", required=True)
    record_node.add_argument("--label", required=True)
    record_node.add_argument("--attrs", type=_json_object, default={})
    record_node.set_defaults(func=_cmd_record_node)

    record_edge = subparsers.add_parser("record-edge", help="append an edge.recorded event")
    _common_record_args(record_edge)
    record_edge.add_argument("--edge-id")
    record_edge.add_argument("--edge-type", required=True)
    record_edge.add_argument("--from-id", required=True)
    record_edge.add_argument("--to-id", required=True)
    record_edge.add_argument("--attrs", type=_json_object, default={})
    record_edge.set_defaults(func=_cmd_record_edge)

    record_state = subparsers.add_parser("record-state", help="append a state.changed event")
    _common_record_args(record_state)
    record_state.add_argument("--subject-id", required=True)
    record_state.add_argument("--from-state", required=True)
    record_state.add_argument("--to-state", required=True)
    record_state.add_argument("--reason", required=True)
    record_state.set_defaults(func=_cmd_record_state)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ACGError as exc:
        print(f"ACG error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
