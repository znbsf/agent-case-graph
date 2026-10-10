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
from .ledger import append_event, atomic_write_text, canonical_json, read_ledger_snapshot, write_new_ledger
from .lint import lint_graph
from .localization import load_display_locales
from .model import ACGError, CAPTURE_MODES, SCHEMA_VERSION, load_events
from .projector import project_events
from .planning import check_plan, prepare_plan
from .project_profile import inspect_project
from .project_query import query_project
from .project_session import record_project_plan, review_project_plan, run_plan_check
from .check_recovery import recover_plan_check
from .renderer import write_projection
from .runtime import (
    build_runtime_snapshot,
    render_runtime_snapshot,
    validate_step_transition,
)
from .replay import build_path_review

MAX_PLAN_FILE_BYTES = 4_000_000


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, RecursionError) as exc:
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
    # End the bootstrap sequence at the current wall-clock time.  Starting at
    # "now" would put the later bootstrap events in the future, so an event
    # appended immediately after init-case could have an earlier timestamp.
    base_time = (
        datetime.now().astimezone().replace(microsecond=0)
        - timedelta(seconds=len(definitions) - 1)
    )
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
    events, digest = read_ledger_snapshot(ledger)
    graph = project_events(events, ledger_path=ledger, ledger_sha256=digest)
    findings = lint_graph(graph)
    return events, graph, findings


def _load_history_graphs(ledgers: Sequence[Path]) -> list[dict[str, Any]]:
    """Load separate historical Case Ledgers without merging them into this Case."""

    graphs: list[dict[str, Any]] = []
    for ledger in ledgers:
        events, digest = read_ledger_snapshot(ledger)
        graphs.append(project_events(events, ledger_path=ledger, ledger_sha256=digest))
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
        presentation=json.loads(args.presentation.read_text(encoding="utf-8")) if args.presentation else None,
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
    capture_mode = before.get("capture_mode")
    if not isinstance(capture_mode, str) or capture_mode not in CAPTURE_MODES:
        raise ACGError("checkpoint requires a Run with an explicit capture_mode")
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
        capture_mode=capture_mode,
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
        expected_sequence=len(events),
        expected_sha256=graph["source_ledger"]["sha256"],
    )
    updated_graph = project_events(events + [event])
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
    source_hash = graph["source_ledger"]["sha256"]
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
        expected_sequence=len(events),
        expected_sha256=source_hash,
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
        expected_sequence=len(events),
        expected_sha256=graph["source_ledger"]["sha256"],
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


def _project_result(value: dict[str, Any], output: Path | None) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2)
    if output:
        atomic_write_text(output, content + "\n")
    else:
        print(content)


def _cmd_inspect_project(args: argparse.Namespace) -> int:
    _project_result(inspect_project(args.workspace), args.output)
    return 0


def _cmd_query_project(args: argparse.Namespace) -> int:
    _project_result(query_project(args.workspace, path=args.path, module=args.module,
                                 include_neighbors=not args.no_neighbors, page_size=args.page_size,
                                 cursor=args.cursor), args.output)
    return 0


def _cmd_plan_project(args: argparse.Namespace) -> int:
    _project_result(prepare_plan(args.workspace, args.goal, ledger=args.ledger, run_id=args.run_id), args.output)
    return 0


def _read_project_plan(path: Path) -> Any:
    """Read bounded UTF-8 JSON, including Windows editor BOM output."""
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_PLAN_FILE_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise ACGError("plan must be a readable UTF-8 JSON file") from exc
    if len(data) > MAX_PLAN_FILE_BYTES:
        raise ACGError(f"plan file exceeds the {MAX_PLAN_FILE_BYTES} byte input limit")
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (ValueError, RecursionError) as exc:
        raise ACGError("plan must be a readable UTF-8 JSON file") from exc


def _cmd_check_plan(args: argparse.Namespace) -> int:
    plan = _read_project_plan(args.plan)
    result = check_plan(args.workspace, plan)
    _project_result(result, args.output)
    return 0 if result["valid"] else 1


def _cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import serve

    serve(args.workspace_root)
    return 0


def _cmd_record_project_plan(args: argparse.Namespace) -> int:
    plan = _read_project_plan(args.plan)
    _project_result(record_project_plan(args.workspace, plan, args.ledger, plan_id=args.plan_id,
                                       run_id=args.run_id, supersedes=args.supersedes, evidence_refs=args.evidence_node), None)
    return 0


def _cmd_review_project_plan(args: argparse.Namespace) -> int:
    _project_result(review_project_plan(args.workspace, args.ledger, plan_id=args.plan_id), args.output)
    return 0


def _cmd_run_plan_check(args: argparse.Namespace) -> int:
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    result = run_plan_check(args.workspace, args.ledger, plan_id=args.plan_id, task_id=args.task_id,
                            criterion=args.criterion, command=command, timeout_seconds=args.timeout_seconds,
                            evidence_dir=args.evidence_dir)
    _project_result(result, None)
    return 0 if result["outcome"] == "passed" else 1


def _cmd_recover_plan_check(args: argparse.Namespace) -> int:
    _project_result(recover_plan_check(args.workspace, args.ledger, plan_id=args.plan_id,
                    receipt_path=args.receipt, receipt_sha256=args.receipt_sha256, dry_run=args.dry_run), None)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="acg",
        description="Agent Case Graph local event ledger, projector and visualizer",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check the local runtime and optional ledger")
    doctor.add_argument("--ledger", type=Path)
    doctor.set_defaults(func=_cmd_doctor)

    inspect = subparsers.add_parser("inspect-project", help="read repository structure, source hashes and static Python imports")
    inspect.add_argument("workspace", type=Path)
    inspect.add_argument("--output", type=Path)
    inspect.set_defaults(func=_cmd_inspect_project)

    query = subparsers.add_parser("query-project", help="query a path subtree or Python module with snapshot-bound pagination")
    query.add_argument("workspace", type=Path)
    selector = query.add_mutually_exclusive_group()
    selector.add_argument("--path", help="exact POSIX file path or directory subtree")
    selector.add_argument("--module", help="exact dotted Python module name")
    query.add_argument("--no-neighbors", action="store_true", help="omit one-hop static Python import neighbors")
    query.add_argument("--page-size", type=int, default=20)
    query.add_argument("--cursor")
    query.add_argument("--output", type=Path)
    query.set_defaults(func=_cmd_query_project)

    plan = subparsers.add_parser("plan-project", help="prepare source-bound context for an agent-authored project plan")
    plan.add_argument("workspace", type=Path)
    plan.add_argument("--goal", required=True)
    plan.add_argument("--ledger", help="optional POSIX path relative to this repository")
    plan.add_argument("--run-id")
    plan.add_argument("--output", type=Path)
    plan.set_defaults(func=_cmd_plan_project)

    check = subparsers.add_parser("check-plan", help="check plan sources, snapshot freshness and dependency order")
    check.add_argument("workspace", type=Path)
    check.add_argument("plan", type=Path, help="UTF-8 JSON plan file (optional BOM; maximum 4,000,000 bytes)")
    check.add_argument("--output", type=Path)
    check.set_defaults(func=_cmd_check_plan)

    record_plan = subparsers.add_parser("record-project-plan", help="atomically record a fresh proposal; optional explicit revision lineage")
    record_plan.add_argument("workspace", type=Path)
    record_plan.add_argument("plan", type=Path, help="UTF-8 JSON plan file (optional BOM; maximum 4,000,000 bytes)")
    record_plan.add_argument("--ledger", required=True, help="workspace-relative POSIX ledger path")
    record_plan.add_argument("--plan-id", required=True)
    record_plan.add_argument("--run-id", required=True)
    record_plan.add_argument("--supersedes", help="active previous project Plan ID in the same Run")
    record_plan.add_argument("--evidence-node", action="append", default=[], help="intact check receipt ID from the superseded plan; repeat for multiple results")
    record_plan.set_defaults(func=_cmd_record_project_plan)

    review_plan = subparsers.add_parser("review-project-plan", help="derive feedback from current evidence and explicit plan lineage")
    review_plan.add_argument("workspace", type=Path)
    review_plan.add_argument("--ledger", required=True)
    review_plan.add_argument("--plan-id", required=True)
    review_plan.add_argument("--output", type=Path)
    review_plan.set_defaults(func=_cmd_review_project_plan)

    run_check = subparsers.add_parser("run-plan-check", help="execute an explicitly supplied command and capture a plan-linked receipt")
    run_check.add_argument("workspace", type=Path)
    run_check.add_argument("--ledger", required=True)
    run_check.add_argument("--plan-id", required=True)
    run_check.add_argument("--task-id", required=True)
    run_check.add_argument("--criterion", type=int, required=True, help="1-based acceptance criterion index")
    run_check.add_argument("--timeout-seconds", type=int, default=60)
    run_check.add_argument("--evidence-dir", default=".artifacts/project-checks")
    run_check.add_argument("--command", nargs=argparse.REMAINDER, required=True, help="explicit argv; put this option last; no shell is used")
    run_check.set_defaults(func=_cmd_run_plan_check)

    recover = subparsers.add_parser("recover-plan-check", help="attach a pinned captured receipt without rerunning its command")
    recover.add_argument("workspace", type=Path)
    recover.add_argument("--ledger", required=True)
    recover.add_argument("--plan-id", required=True)
    recover.add_argument("--receipt", required=True, help="workspace-relative ignored .artifacts receipt.json")
    recover.add_argument("--receipt-sha256", required=True, help="original digest reported after the check; do not recompute from changed evidence")
    recover.add_argument("--dry-run", action="store_true", help="validate recovery without appending any events")
    recover.set_defaults(func=_cmd_recover_plan_check)

    mcp = subparsers.add_parser("mcp", help="serve read-only project tools over MCP stdio (requires the mcp extra)")
    mcp.add_argument("--workspace-root", type=Path, help="explicit repository root; otherwise ACG_WORKSPACE_ROOT is required")
    mcp.set_defaults(func=_cmd_mcp)

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
    project.add_argument("--presentation", type=Path, help="optional ledger-hash-bound graph presentation JSON (display only)")
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
