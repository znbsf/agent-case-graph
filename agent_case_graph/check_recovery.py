"""Explicit recovery of a captured check; never execute the recorded argv."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .model import ACGError, parse_events
from .project_profile import _git, inspect_project, repository_root, workspace_path
from .project_session import (
    CHECK_VERSION, MAX_LEDGER_BYTES, MAX_OUTPUT_BYTES, RECOVERY_VERSION, SESSION_VERSION,
    _append, _check_records, _linked_receipt_status, _load, _plan_node, _read, _receipt_status, _successors,
)


def _sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _integer(value: Any, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _receipt(root: Path, receipt_ref: str, expected: str) -> tuple[dict[str, Any], bytes]:
    if not _sha(expected):
        raise ACGError("receipt_sha256 must be the original 64-character lowercase SHA-256")
    path = workspace_path(root, receipt_ref, must_exist=True, allow_artifacts=True)
    output_ref = (path.parent / "output.log").relative_to(root).as_posix()
    if (not receipt_ref.startswith(".artifacts/") or path.name != "receipt.json"
            or any(not _git(root, "check-ignore", "--", ref, allow_failure=True).strip()
                   for ref in (receipt_ref, output_ref))):
        raise ACGError("recovery requires an ignored .artifacts receipt.json")
    raw = _read(path, 400_000)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ACGError("recovery receipt differs from the original SHA-256")
    try:
        receipt = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ACGError("recovery receipt must be bounded UTF-8 JSON") from exc
    if not isinstance(receipt, dict) or receipt.get("version") != CHECK_VERSION:
        raise ACGError("unsupported check receipt")
    binding = receipt.get("recovery")
    if (not isinstance(binding, dict) or binding.get("version") != RECOVERY_VERSION
            or not isinstance(binding.get("check_id"), str)
            or not re.fullmatch(r"check:[0-9a-f]{32}", binding["check_id"])
            or not _sha(binding.get("proposal_sha256")) or not _sha(binding.get("ledger_sha256"))
            or not _integer(binding.get("ledger_bytes"), 1, MAX_LEDGER_BYTES)
            or not _integer(binding.get("ledger_sequence"), 1, MAX_LEDGER_BYTES)):
        raise ACGError("receipt has no valid recovery binding; legacy orphan receipts require manual review")
    argv = receipt.get("command")
    if (not isinstance(argv, list) or not 1 <= len(argv) <= 64
            or any(not isinstance(arg, str) or "\x00" in arg for arg in argv)
            or not argv[0] or sum(map(len, argv)) > 16_000 or receipt.get("cwd") != "."
            or not _integer(receipt.get("timeout_seconds"), 1, 300)
            or not _integer(receipt.get("max_output_bytes"), 1, MAX_OUTPUT_BYTES)):
        raise ACGError("invalid captured command contract")
    try:
        started, finished = [datetime.fromisoformat(receipt[key]) for key in ("started_at", "finished_at")]
        if started.utcoffset() is None or finished.utcoffset() is None or started > finished:
            raise ValueError("invalid time order")
    except (KeyError, ValueError, TypeError) as exc:
        raise ACGError("invalid check timestamps") from exc
    environment = receipt.get("environment")
    if not isinstance(environment, dict) or any(not isinstance(environment.get(key), str) for key in ("python", "platform")):
        raise ACGError("missing check environment")
    if (not _sha(receipt.get("snapshot_before"))
            or (not _sha(receipt.get("snapshot_after")) and not (
                receipt.get("snapshot_after") is None and receipt.get("observation_error") == "repository_unavailable_after_command"))):
        raise ACGError("invalid check snapshots")
    outcome, code = receipt.get("outcome"), receipt.get("exit_code")
    if not isinstance(outcome, str) or outcome not in {"passed", "failed", "timeout", "output_limit", "launch_error"}:
        raise ACGError("invalid check outcome")
    if ((outcome == "launch_error" and code is not None)
            or (outcome != "launch_error" and type(code) is not int)
            or (outcome == "passed" and code != 0) or (outcome == "failed" and code == 0)):
        raise ACGError("outcome and exit code disagree")
    log = receipt.get("log")
    if (not isinstance(log, dict) or log.get("path") != output_ref
            or not _sha(log.get("sha256"))
            or not _integer(log.get("captured_bytes"), 0, receipt["max_output_bytes"])
            or type(log.get("emitted_bytes")) is not int or log["emitted_bytes"] < log["captured_bytes"]
            or type(log.get("truncated")) is not bool
            or log["truncated"] != (log["emitted_bytes"] > log["captured_bytes"])
            or (outcome == "passed" and log["truncated"])):
        raise ACGError("invalid captured output contract")
    output = _read(workspace_path(root, log["path"], must_exist=True, allow_artifacts=True), MAX_OUTPUT_BYTES)
    if len(output) != log["captured_bytes"] or hashlib.sha256(output).hexdigest() != log["sha256"]:
        raise ACGError("recovery output differs from its recorded SHA-256")
    return receipt, raw


def recover_plan_check(workspace: str | Path, ledger: str, *, plan_id: str,
                       receipt_path: str, receipt_sha256: str, dry_run: bool = False) -> dict[str, Any]:
    """Attach one explicitly selected, pinned receipt to its original proposal."""
    root = repository_root(workspace)
    path, events, digest, graph = _load(root, ledger)
    # The append lock is generated beside the ledger. It must not change the
    # inspected repository's Git status while validating under that lock.
    if (not ledger.startswith(".artifacts/")
            or not _git(root, "check-ignore", "--", ledger, allow_failure=True).strip()
            or not _git(root, "check-ignore", "--", ledger + ".lock", allow_failure=True).strip()):
        raise ACGError("recovery requires an ignored .artifacts ledger and lock")
    plan = _plan_node(root, graph, plan_id)
    if _successors(graph, plan_id):
        raise ACGError("cannot recover a check for a superseded project plan")
    receipt, raw = _receipt(root, receipt_path, receipt_sha256)
    binding = receipt["recovery"]
    if (receipt.get("plan_id") != plan_id or binding.get("case_id") != events[0]["case_id"]
            or binding.get("run_id") != plan["attrs"]["run_id"] or binding.get("ledger") != ledger
            or binding["proposal_sha256"] != plan["attrs"]["proposal_sha256"]):
        raise ACGError("recovery receipt belongs to a different Case, Run, Plan or ledger")
    task_id, criterion = receipt.get("task_id"), receipt.get("criterion_index")
    task = next((task for task in plan["attrs"]["proposal"]["tasks"] if task["id"] == task_id), None)
    if not task or not _integer(criterion, 1, len(task["acceptance_criteria"])):
        raise ACGError("recovery task and criterion do not exist in the selected plan")
    data = _read(path, MAX_LEDGER_BYTES)
    if hashlib.sha256(data).hexdigest() != digest:
        raise ACGError("ledger changed during recovery validation")
    prefix = data[:binding["ledger_bytes"]]
    if len(prefix) != binding["ledger_bytes"] or hashlib.sha256(prefix).hexdigest() != binding["ledger_sha256"]:
        raise ACGError("ledger does not preserve the check's original byte prefix")
    try:
        prefix_events = parse_events(prefix.decode("utf-8-sig"))
    except (UnicodeError, ACGError) as exc:
        raise ACGError("original ledger prefix must be complete UTF-8 JSONL") from exc
    if len(prefix_events) != binding["ledger_sequence"]:
        raise ACGError("ledger does not preserve the check's original sequence")
    check_id = binding["check_id"]
    receipt_id, artifact_id = check_id + ":receipt", check_id + ":output"
    snapshot = inspect_project(root)["snapshot_sha256"]
    records = _check_records(plan, check_id, receipt_path, receipt_sha256, receipt, recovered=True)
    candidate = {"id": receipt_id, "attrs": records[1]["node"]["attrs"],
                 "event_ids": ["pending-recovery"], "provenance": {"capture_modes": ["live"]}}
    assessment = _receipt_status(root, candidate, snapshot)
    if assessment["status"] == "invalid_evidence":
        raise ACGError("cannot recover invalid evidence: " + assessment["reason"])
    result = {"protocol_version": SESSION_VERSION, "receipt_node_id": receipt_id,
              "receipt_path": receipt_path, "receipt_sha256": receipt_sha256,
              "evidence_status": assessment["status"], "command_executed": False,
              "execution_authorized": False, "acceptance_assessed": False}
    nodes = {node["id"]: node for node in graph["nodes"]}
    related = [node for node in graph["nodes"] if node["type"] == "VerificationReceipt" and (
        node.get("attrs", {}).get("source_path") == receipt_path or node.get("attrs", {}).get("sha256") == receipt_sha256)]
    if any(node_id in nodes for node_id in (check_id, receipt_id, artifact_id)) or related:
        expected_edges = {(record["edge"]["type"], record["edge"]["from"], record["edge"]["to"])
                          for record in records if record["kind"] == "edge.recorded"}
        owned_types = {kind for kind, _, _ in expected_edges}
        owned_ids = {check_id, receipt_id, artifact_id}
        owned_edges = [edge for edge in graph["edges"] if edge["type"] in owned_types
                       and ({edge["from"], edge["to"]} & owned_ids)]
        edges = {(edge["type"], edge["from"], edge["to"]) for edge in owned_edges}
        for record in records[:3]:
            expected = record["node"]
            actual = nodes.get(expected["id"], {})
            keys = set(expected["attrs"]) - {"recording_origin"}
            if (actual.get("type") != expected["type"] or actual.get("provenance", {}).get("capture_modes") != ["live"]
                    or actual.get("provenance", {}).get("run_ids") != [plan["attrs"]["run_id"]]
                    or len(actual.get("event_ids", [])) != 1
                    or any(actual.get("attrs", {}).get(key) != expected["attrs"][key] for key in keys)):
                raise ACGError("check identity is already present with incomplete or conflicting evidence")
        if (expected_edges != edges or len(owned_edges) != len(expected_edges)
                or any(edge.get("provenance", {}).get("capture_modes") != ["live"]
                       or edge.get("provenance", {}).get("run_ids") != [plan["attrs"]["run_id"]]
                       or len(edge.get("event_ids", [])) != 1 for edge in owned_edges)
                or len(related) != 1 or related[0]["id"] != receipt_id
                or _linked_receipt_status(root, nodes[receipt_id], snapshot, graph)["status"] == "invalid_evidence"):
            raise ACGError("check identity is already present with incomplete or conflicting relationships")
        return {**result, "status": "already_recorded", "events_appended": 0}
    # Check immutable history, including later updates to an earlier receipt.
    # Projected attrs can hide a competing receipt's original criterion.
    criterion_receipts = set()
    historical_attrs: dict[str, dict[str, Any]] = {}
    for event in events:
        if event["kind"] != "node.recorded" or event["node"]["type"] != "VerificationReceipt":
            continue
        node = event["node"]
        attrs = historical_attrs.setdefault(node["id"], {})
        attrs.update(node.get("attrs", {}))
        if attrs.get("plan_id") == plan_id and attrs.get("task_id") == task_id and attrs.get("criterion_index") == criterion:
            criterion_receipts.add(node["id"])
    if any(event["kind"] == "node.recorded" and event["node"]["id"] in criterion_receipts
           and event["sequence"] > binding["ledger_sequence"] for event in events):
        raise ACGError("a newer or competing criterion result is already recorded; inspect it instead of recovering an older check")
    if dry_run:
        return {**result, "status": "recovery_ready", "events_appended": 0}

    def validate_inputs() -> None:
        _, current = _receipt(root, receipt_path, receipt_sha256)
        if current != raw or inspect_project(root)["snapshot_sha256"] != snapshot:
            raise ACGError("receipt or repository changed during recovery; inspect and retry recovery")

    batch = _append(path, events, digest, records, plan["attrs"]["run_id"],
                    [f"file:{receipt_path}#{receipt_sha256}", f"check-recovery:{check_id}"], validate_inputs=validate_inputs)
    return {**result, "status": "check_recovered", "events_appended": len(batch)}
