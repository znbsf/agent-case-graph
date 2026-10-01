"""Record proposals and actual CLI checks; derive feedback without granting execution."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .ledger import append_events, atomic_write_text, canonical_json
from .lint import lint_graph
from .model import ACGError, parse_events
from .planning import PLAN_VERSION, _check_plan, check_plan
from .project_profile import _git, inspect_project, repository_root, workspace_path
from .projector import project_events

SESSION_VERSION = "project-session-0.1"
CHECK_VERSION = "project-check-0.1"
RECOVERY_VERSION = "project-check-recovery-0.1"
MAX_LEDGER_BYTES = 4_000_000
MAX_OUTPUT_BYTES = 1_000_000


def _read(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as exc:
        raise ACGError("unable to read the selected workspace evidence") from exc
    if len(data) > limit:
        raise ACGError("selected workspace evidence exceeds its byte limit")
    return data


def _clean(events: list[dict[str, Any]]) -> dict[str, Any]:
    graph = project_events(events)
    errors = [row["code"] for row in lint_graph(graph) if row["severity"] == "error"]
    if errors:
        raise ACGError("project session refuses graph lint errors: " + ", ".join(sorted(set(errors))))
    return graph


def _load(root: Path, ledger: str) -> tuple[Path, list[dict[str, Any]], str, dict[str, Any]]:
    path = workspace_path(root, ledger, must_exist=True, allow_artifacts=True)
    data = _read(path, MAX_LEDGER_BYTES)
    try:
        events = parse_events(data.decode("utf-8-sig"))
    except UnicodeError as exc:
        raise ACGError("ledger must be UTF-8 JSONL") from exc
    return path, events, hashlib.sha256(data).hexdigest(), _clean(events)


def _node(node_id: str, node_type: str, label: str, **attrs: Any) -> dict[str, Any]:
    return {"kind": "node.recorded", "node": {"id": node_id, "type": node_type, "label": label, "attrs": attrs}}


def _edge(edge_type: str, from_id: str, to_id: str) -> dict[str, Any]:
    return {"kind": "edge.recorded", "edge": {
        "id": f"edge:{uuid.uuid4().hex}", "type": edge_type, "from": from_id, "to": to_id, "attrs": {},
    }}


def _append(path: Path, events: list[dict[str, Any]], digest: str, records: list[dict[str, Any]], run_id: str, refs: list[str],
            *, validate_inputs: Callable[[], None] | None = None) -> list[dict[str, Any]]:
    def validate(combined: list[dict[str, Any]]) -> None:
        if sum(len(canonical_json(event).encode("utf-8")) + 1 for event in combined) > MAX_LEDGER_BYTES:
            raise ACGError("project session would exceed the 4 MB ledger limit")
        _clean(combined)
        if validate_inputs:
            validate_inputs()

    return append_events(
        path, case_id=events[0]["case_id"], records=records, actor_type="agent", actor_id="acg-project-session",
        capture_mode="live", source_refs=refs, run_id=run_id,
        expected_sequence=len(events), expected_sha256=digest, validate_combined=validate,
        maximum_bytes=MAX_LEDGER_BYTES,
    )


def _plan_node(root: Path, graph: dict[str, Any], plan_id: str) -> dict[str, Any]:
    node = next((row for row in graph["nodes"] if row["id"] == plan_id), None)
    if not node or node["type"] != "Plan" or node.get("attrs", {}).get("project_plan_version") != PLAN_VERSION:
        raise ACGError("selected node is not a recorded project plan")
    if node.get("provenance", {}).get("capture_modes") != ["live"] or len(node.get("event_ids", [])) != 1:
        raise ACGError("project proposals must be immutable live records; use an explicit revision")
    proposal = node["attrs"].get("proposal")
    if not isinstance(proposal, dict) or node["attrs"].get("proposal_sha256") != hashlib.sha256(canonical_json(proposal).encode("utf-8")).hexdigest():
        raise ACGError("recorded plan proposal hash is invalid")
    tasks = proposal.get("tasks")
    refs = set()
    if isinstance(tasks, list):
        for task in tasks:
            if isinstance(task, dict) and isinstance(task.get("source_refs"), list):
                refs.update(ref for ref in task["source_refs"] if isinstance(ref, str))
    historical = {"snapshot_sha256": proposal.get("source_snapshot_sha256"), "sources": [{"id": ref} for ref in refs]}
    if (not _check_plan(root, historical, proposal)["valid"]
            or not isinstance(proposal.get("source_snapshot_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", proposal["source_snapshot_sha256"])
            or node["attrs"].get("source_snapshot_sha256") != proposal["source_snapshot_sha256"]):
        raise ACGError("recorded project proposal is malformed")
    _live_run(graph, node["attrs"].get("run_id"))
    nodes = {row["id"]: row for row in graph["nodes"]}
    edges = {(edge["type"], edge["from"], edge["to"]) for edge in graph["edges"]}
    if ("contains", node["attrs"]["run_id"], plan_id) not in edges:
        raise ACGError("recorded project plan has no Run containment relationship")
    for task in tasks:
        task_node = f"{plan_id}:task:{task['id']}"
        action = nodes.get(task_node, {})
        if (action.get("type") != "Action" or action.get("attrs", {}).get("runtime_managed") is not False
                or ("contains", plan_id, task_node) not in edges):
            raise ACGError("recorded project task is missing or no longer a proposal")
        for index, _ in enumerate(task["acceptance_criteria"], start=1):
            criterion_id = f"{task_node}:criterion:{index}"
            if nodes.get(criterion_id, {}).get("type") != "AcceptanceCriterion" or ("contains", task_node, criterion_id) not in edges:
                raise ACGError("recorded project task has an incomplete acceptance structure")
    return node


def _live_run(graph: dict[str, Any], run_id: str) -> None:
    run = next((row for row in graph["nodes"] if row["id"] == run_id), None)
    if (not run or run["type"] != "Run" or run.get("provenance", {}).get("capture_modes") != ["live"]
            or run.get("attrs", {}).get("capture_mode") != "live"):
        raise ACGError("project sessions require an explicit live Run")


def _successors(graph: dict[str, Any], plan_id: str) -> list[str]:
    return sorted({edge["from"] for edge in graph["edges"] if edge["type"] == "supersedes" and edge["to"] == plan_id})


def record_project_plan(
    workspace: str | Path, plan: dict[str, Any], ledger: str, *, plan_id: str, run_id: str,
    supersedes: str | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Explicit CLI write: store a fresh proposal, never a runtime-ready action."""
    root = repository_root(workspace)
    checked = check_plan(root, plan)
    if not checked["valid"]:
        raise ACGError("cannot record invalid proposal: " + ", ".join(row["code"] for row in checked["errors"]))
    if not isinstance(plan_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_:-]{0,119}", plan_id):
        raise ACGError("plan_id must be a short graph identifier")
    path, events, digest, graph = _load(root, ledger)
    nodes = {node["id"]: node for node in graph["nodes"]}
    _live_run(graph, run_id)
    evidence_refs = [] if evidence_refs is None else evidence_refs
    if (not isinstance(evidence_refs, list) or len(evidence_refs) > 24 or any(not isinstance(ref, str) for ref in evidence_refs)
            or len(set(evidence_refs)) != len(evidence_refs) or (evidence_refs and not supersedes)):
        raise ACGError("revision evidence must be unique receipt IDs from the explicitly superseded plan")
    if supersedes:
        previous = _plan_node(root, graph, supersedes)
        if previous["attrs"].get("run_id") != run_id or _successors(graph, supersedes):
            raise ACGError("revision must supersede an active project plan in the same Run")
    for ref in evidence_refs:
        evidence = nodes.get(ref)
        if (not evidence or evidence["type"] != "VerificationReceipt"
                or evidence.get("attrs", {}).get("project_check_version") != CHECK_VERSION
                or evidence["attrs"].get("plan_id") != supersedes
                or _linked_receipt_status(root, evidence, plan["source_snapshot_sha256"], graph)["status"] == "invalid_evidence"):
            raise ACGError("revision evidence must be an intact linked receipt from the superseded plan")
    proposal = json.loads(canonical_json(plan))
    proposal_hash = hashlib.sha256(canonical_json(proposal).encode("utf-8")).hexdigest()
    records = [
        _node(plan_id, "Plan", proposal["goal"], status="proposed", data_origin="agent_authored",
              project_plan_version=PLAN_VERSION, proposal=proposal, proposal_sha256=proposal_hash,
              source_snapshot_sha256=proposal["source_snapshot_sha256"], run_id=run_id, execution_authorized=False),
        _edge("contains", run_id, plan_id),
    ]
    task_nodes = {}
    for task in proposal["tasks"]:
        task_node = f"{plan_id}:task:{task['id']}"
        task_nodes[task["id"]] = task_node
        records.extend([
            _node(task_node, "Action", task["title"], status="proposed", runtime_managed=False,
                  project_plan_id=plan_id, project_task_id=task["id"], source_refs=task["source_refs"],
                  target_paths=task["target_paths"], acceptance_criteria=task["acceptance_criteria"]),
            _edge("contains", plan_id, task_node),
        ])
        for index, criterion in enumerate(task["acceptance_criteria"], start=1):
            criterion_id = f"{task_node}:criterion:{index}"
            records.extend([
                _node(criterion_id, "AcceptanceCriterion", criterion, status="pending", project_plan_id=plan_id,
                      project_task_id=task["id"], criterion_index=index),
                _edge("contains", task_node, criterion_id),
            ])
    for task in proposal["tasks"]:
        for dependency in task["depends_on"]:
            records.append(_edge("precedes", task_nodes[dependency], task_nodes[task["id"]]))
    if supersedes:
        records.append(_edge("supersedes", plan_id, supersedes))
    for ref in evidence_refs:
        records.append(_edge("informs", ref, plan_id))
    added_ids = [record["node"]["id"] for record in records if record["kind"] == "node.recorded"]
    if any(node_id in nodes for node_id in added_ids) or len(set(added_ids)) != len(added_ids):
        raise ACGError("project plan identifiers already exist in the ledger")
    # Reobserve immediately before the atomic ledger transaction. This is still
    # a sequential observation, not a filesystem lock or semantic validation.
    if inspect_project(root)["snapshot_sha256"] != proposal["source_snapshot_sha256"]:
        raise ACGError("repository changed before the plan could be recorded")
    batch = _append(path, events, digest, records, run_id, [f"project-plan:{proposal_hash}"])
    return {"protocol_version": SESSION_VERSION, "status": "proposal_recorded", "plan_id": plan_id,
            "task_node_ids": task_nodes, "events_appended": len(batch), "supersedes": supersedes, "evidence_refs": evidence_refs,
            "execution_authorized": False}


def _capture(root: Path, command: list[str], timeout: int) -> tuple[str, int | None, bytes, int]:
    """Spool output outside the project and stop the direct child at its limits."""
    with tempfile.TemporaryFile() as stream:
        try:
            process = subprocess.Popen(command, cwd=root, shell=False, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT)
        except OSError:
            return "launch_error", None, b"", 0
        deadline = time.monotonic() + timeout
        outcome = None
        while process.poll() is None:
            size = stream.seek(0, 2)
            if size > MAX_OUTPUT_BYTES:
                outcome = "output_limit"
            elif time.monotonic() >= deadline:
                outcome = "timeout"
            if outcome:
                process.kill()
                break
            time.sleep(0.02)
        returncode = process.wait()
        total_bytes = stream.seek(0, 2)
        if total_bytes > MAX_OUTPUT_BYTES:
            outcome = "output_limit" if outcome is None else outcome
        stream.seek(0)
        output = stream.read(MAX_OUTPUT_BYTES)
        return outcome or ("passed" if returncode == 0 else "failed"), returncode, output, total_bytes


def run_plan_check(
    workspace: str | Path, ledger: str, *, plan_id: str, task_id: str, criterion: int,
    command: list[str], timeout_seconds: int = 60, evidence_dir: str = ".artifacts/project-checks",
) -> dict[str, Any]:
    """Run only explicitly supplied argv. No command is inferred from project text."""
    root = repository_root(workspace)
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 300:
        raise ACGError("timeout_seconds must be an integer between 1 and 300")
    if (not isinstance(command, list) or not 1 <= len(command) <= 64
            or any(not isinstance(arg, str) or "\x00" in arg for arg in command)
            or not command[0] or sum(len(arg) for arg in command) > 16_000):
        raise ACGError("check requires an explicit bounded argv list")
    path, events, digest, graph = _load(root, ledger)
    plan = _plan_node(root, graph, plan_id)
    if _successors(graph, plan_id):
        raise ACGError("cannot run a check for a superseded project plan")
    task = next((row for row in plan["attrs"]["proposal"]["tasks"] if row["id"] == task_id), None)
    if not task or not isinstance(criterion, int) or isinstance(criterion, bool) or not 1 <= criterion <= len(task["acceptance_criteria"]):
        raise ACGError("task_id and 1-based criterion must exist in the recorded plan")
    capture_base = workspace_path(root, evidence_dir, allow_artifacts=True)
    # Generated logs must not enter normal project context or version control.
    if not evidence_dir.startswith(".artifacts/") or not _git(root, "check-ignore", "--", evidence_dir + "/probe", allow_failure=True).strip():
        raise ACGError("evidence_dir must be an ignored directory under .artifacts/")
    capture_base.mkdir(parents=True, exist_ok=True)
    capture_dir = Path(tempfile.mkdtemp(prefix="check-", dir=capture_base))
    anchor = _read(path, MAX_LEDGER_BYTES)
    if hashlib.sha256(anchor).hexdigest() != digest:
        raise ACGError("ledger changed before the check; reload and retry the command")
    check_id = f"check:{uuid.uuid4().hex}"
    before = inspect_project(root)["snapshot_sha256"]
    started = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    outcome, exit_code, output, total_bytes = _capture(root, command, timeout_seconds)
    finished = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    log_path = capture_dir / "output.log"
    log_path.write_bytes(output)
    after = None
    observation_error = None
    try:
        after = inspect_project(root)["snapshot_sha256"]
    except (ACGError, OSError):
        observation_error = "repository_unavailable_after_command"
    receipt = {
        "version": CHECK_VERSION, "plan_id": plan_id, "task_id": task_id, "criterion_index": criterion,
        "command": command, "cwd": ".", "environment": {"python": platform.python_version(), "platform": sys.platform},
        "started_at": started, "finished_at": finished, "outcome": outcome, "exit_code": exit_code,
        "timeout_seconds": timeout_seconds, "max_output_bytes": MAX_OUTPUT_BYTES,
        "snapshot_before": before, "snapshot_after": after, "observation_error": observation_error,
        "recovery": {"version": RECOVERY_VERSION, "check_id": check_id, "case_id": events[0]["case_id"],
                     "run_id": plan["attrs"]["run_id"], "ledger": ledger,
                     "proposal_sha256": plan["attrs"]["proposal_sha256"], "ledger_sha256": digest,
                     "ledger_bytes": len(anchor), "ledger_sequence": len(events)},
        "log": {"path": log_path.relative_to(root).as_posix(), "sha256": hashlib.sha256(output).hexdigest(),
                "captured_bytes": len(output), "emitted_bytes": total_bytes, "truncated": total_bytes > len(output)},
    }
    receipt_path = capture_dir / "receipt.json"
    receipt_content = canonical_json(receipt) + "\n"
    receipt_hash = hashlib.sha256(receipt_content.encode("utf-8")).hexdigest()
    atomic_write_text(receipt_path, receipt_content)
    receipt_ref = receipt_path.relative_to(root).as_posix()
    records = _check_records(plan, check_id, receipt_ref, receipt_hash, receipt)
    # A concurrent ledger edit invalidates the append, not the already executed
    # command. Keep its receipt and original digest instead of replaying it.
    try:
        _append(path, events, digest, records, plan["attrs"]["run_id"], [f"file:{receipt_ref}#{receipt_hash}"])
    except (ACGError, OSError) as exc:
        raise ACGError(f"command finished; receipt preserved at {receipt_ref}; receipt_sha256={receipt_hash}; ledger append refused: {exc}") from exc
    return {"protocol_version": SESSION_VERSION, "outcome": outcome, "exit_code": exit_code,
            "receipt_node_id": f"{check_id}:receipt", "receipt_path": receipt_ref, "receipt_sha256": receipt_hash,
            "repository_changed_during_check": before != after, "acceptance_assessed": False}


def _check_records(plan: dict[str, Any], check_id: str, receipt_ref: str, receipt_hash: str,
                   receipt: dict[str, Any], *, recovered: bool = False) -> list[dict[str, Any]]:
    """Keep original checks and explicit recovery on the same evidence topology."""
    plan_id, task_id, criterion = receipt["plan_id"], receipt["task_id"], receipt["criterion_index"]
    outcome = receipt["outcome"]
    receipt_id, artifact_id = f"{check_id}:receipt", f"{check_id}:output"
    task_node = f"{plan_id}:task:{task_id}"
    return [
        _node(check_id, "ToolCall", f"Explicit check for {task_id}, criterion {criterion}",
              runtime_managed=False, status="completed" if outcome == "passed" else "failed",
              command=receipt["command"], execution_origin="explicit_cli_check", project_plan_id=plan_id,
              recording_origin="receipt_recovery" if recovered else "check_execution"),
        _node(receipt_id, "VerificationReceipt", f"Command result: {outcome}", status=outcome, capture_mode="live",
              project_check_version=CHECK_VERSION, plan_id=plan_id, task_id=task_id, criterion_index=criterion,
              source_path=receipt_ref, sha256=receipt_hash),
        _node(artifact_id, "Artifact", "Captured command output", source_path=receipt["log"]["path"],
              sha256=receipt["log"]["sha256"], capture_mode="live", truncated=receipt["log"]["truncated"]),
        _edge("contains", plan["attrs"]["run_id"], check_id), _edge("invokes", task_node, check_id),
        _edge("produces", check_id, receipt_id), _edge("produces", check_id, artifact_id),
        _edge("verified_by", task_node, receipt_id), _edge("checks", receipt_id, f"{task_node}:criterion:{criterion}"),
    ]


def _receipt_status(root: Path, node: dict[str, Any], snapshot: str) -> dict[str, Any]:
    attrs = node.get("attrs", {})
    result = {"receipt_node_id": node["id"], "receipt_path": attrs.get("source_path")}
    try:
        if node.get("provenance", {}).get("capture_modes") != ["live"] or len(node.get("event_ids", [])) != 1:
            raise ACGError("receipt_is_not_exclusively_live")
        raw = _read(workspace_path(root, attrs.get("source_path"), must_exist=True, allow_artifacts=True), 400_000)
        if hashlib.sha256(raw).hexdigest() != attrs.get("sha256"):
            raise ACGError("receipt_hash_mismatch")
        receipt = json.loads(raw)
        if (not isinstance(receipt, dict) or receipt.get("version") != CHECK_VERSION
                or any(receipt.get(key) != attrs.get(key) for key in ("plan_id", "task_id", "criterion_index"))):
            raise ACGError("receipt_identity_mismatch")
        log = receipt.get("log")
        if not isinstance(log, dict):
            raise ACGError("missing_command_output")
        output = _read(workspace_path(root, log.get("path"), must_exist=True, allow_artifacts=True), MAX_OUTPUT_BYTES)
        if hashlib.sha256(output).hexdigest() != log.get("sha256") or len(output) != log.get("captured_bytes"):
            raise ACGError("output_hash_mismatch")
        result.update(outcome=receipt.get("outcome"), exit_code=receipt.get("exit_code"), command=receipt.get("command"))
        if receipt.get("outcome") in {"failed", "timeout", "output_limit", "launch_error"}:
            return {**result, "status": "check_failed"}
        if receipt.get("outcome") != "passed" or type(receipt.get("exit_code")) is not int or receipt["exit_code"] != 0 or log.get("truncated") is not False:
            raise ACGError("invalid_passing_result")
        if receipt.get("snapshot_before") != receipt.get("snapshot_after"):
            return {**result, "status": "stale_evidence", "reason": "repository_changed_during_check"}
        if receipt.get("snapshot_after") != snapshot:
            return {**result, "status": "stale_evidence", "reason": "repository_changed_after_check"}
        return {**result, "status": "check_passed"}
    except (ACGError, OSError, ValueError, TypeError, RecursionError) as exc:
        return {**result, "status": "invalid_evidence", "reason": str(exc)[:240]}


def _linked_receipt_status(root: Path, node: dict[str, Any], snapshot: str, graph: dict[str, Any]) -> dict[str, Any]:
    attrs = node.get("attrs", {})
    result = {"receipt_node_id": node["id"], "receipt_path": attrs.get("source_path")}
    task_node = f"{attrs.get('plan_id')}:task:{attrs.get('task_id')}"
    criterion_id = f"{task_node}:criterion:{attrs.get('criterion_index')}"
    edges = {(edge["type"], edge["from"], edge["to"]) for edge in graph["edges"]}
    if ("verified_by", task_node, node["id"]) not in edges or ("checks", node["id"], criterion_id) not in edges:
        return {**result, "status": "invalid_evidence", "reason": "missing_plan_evidence_relationship"}
    calls = [call for call in graph["nodes"] if call["type"] == "ToolCall"
             and ("produces", call["id"], node["id"]) in edges and ("invokes", task_node, call["id"]) in edges
             and call.get("attrs", {}).get("execution_origin") == "explicit_cli_check"
             and call.get("provenance", {}).get("capture_modes") == ["live"]]
    if len(calls) != 1:
        return {**result, "status": "invalid_evidence", "reason": "missing_live_command_relationship"}
    status = _receipt_status(root, node, snapshot)
    if status["status"] != "invalid_evidence" and status.get("command") != calls[0]["attrs"].get("command"):
        return {**result, "status": "invalid_evidence", "reason": "command_identity_mismatch"}
    return status


def review_project_plan(workspace: str | Path, ledger: str, *, plan_id: str) -> dict[str, Any]:
    """Check latest evidence per criterion, then derive revision hints; never execute."""
    root = repository_root(workspace)
    _, _, digest, graph = _load(root, ledger)
    plan = _plan_node(root, graph, plan_id)
    snapshot = inspect_project(root)["snapshot_sha256"]
    task_rows = []
    hints = []
    receipts = [node for node in graph["nodes"] if node["type"] == "VerificationReceipt"
                and node.get("attrs", {}).get("project_check_version") == CHECK_VERSION
                and node["attrs"].get("plan_id") == plan_id]
    for task in plan["attrs"]["proposal"]["tasks"]:
        criteria = []
        for index, text in enumerate(task["acceptance_criteria"], start=1):
            candidates = [node for node in receipts if node["attrs"].get("task_id") == task["id"] and node["attrs"].get("criterion_index") == index]
            latest = max(candidates, key=lambda node: node["last_sequence"], default=None)
            evidence = _linked_receipt_status(root, latest, snapshot, graph) if latest else {"status": "missing_evidence"}
            criteria.append({"index": index, "text": text, **evidence})
            if evidence["status"] != "check_passed":
                hints.append({"task_id": task["id"], "criterion_index": index, "reason": evidence["status"],
                              "next_step": "Inspect the latest result and reconsider the task, then record a relevant check against the current repository."})
        status = "checks_passed" if all(row["status"] == "check_passed" for row in criteria) else "needs_followup"
        task_rows.append({"id": task["id"], "title": task["title"], "status": status, "criteria": criteria, "depends_on": task["depends_on"]})
    # Propagate dependency gaps regardless of the proposal's presentation order.
    by_id = {row["id"]: row for row in task_rows}
    for _ in task_rows:
        for row in task_rows:
            blocked = [parent for parent in row["depends_on"] if by_id[parent]["status"] != "checks_passed"]
            if blocked:
                row.update(status="needs_followup", dependencies_needing_followup=blocked)
    changed = snapshot != plan["attrs"]["source_snapshot_sha256"]
    if changed:
        hints.append({"reason": "repository_changed_since_proposal", "next_step": "Review the changed context; author a fresh proposal with an explicit supersedes link if the plan should change."})
    superseded_by = _successors(graph, plan_id)
    return {
        "protocol_version": SESSION_VERSION, "data_origin": "derived", "plan_id": plan_id,
        "status": "superseded" if superseded_by else ("checks_passed" if all(row["status"] == "checks_passed" for row in task_rows) else "needs_followup"),
        "ledger_sha256": digest, "current_snapshot_sha256": snapshot, "repository_changed_since_proposal": changed,
        "superseded_by": superseded_by, "tasks": task_rows, "suggested_revisions": hints,
        "execution_authorized": False, "acceptance_assessed": False,
        "limitations": [
            "Exit zero verifies the supplied command, not the semantic acceptance criterion or task completion.",
            "Receipt and log hashes check recorded file integrity, not cryptographic attestation of execution.",
            "Freshness conservatively covers the whole inspected repository, not ignored inputs or an atomic filesystem snapshot.",
            "New revisions do not inherit checks; recorded proposals and checks do not grant canonical runtime approval.",
        ],
    }
