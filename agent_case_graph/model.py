from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "0.1.0"

EVENT_KINDS = {
    "graph.declared",
    "node.recorded",
    "edge.recorded",
    "state.changed",
}

ACTOR_TYPES = {"human", "agent", "tool", "service"}
CAPTURE_MODES = {"live", "reconstructed", "synthetic"}

NODE_TYPES = {
    "Graph",
    "ProblemType",
    "Case",
    "Goal",
    "Plan",
    "DialogueRound",
    "ExecutionIteration",
    "UserFeedback",
    "AgentResponse",
    "Evaluation",
    "ReasoningSummary",
    "ToolCall",
    "ToolOutput",
    "AcceptanceCriterion",
    "Run",
    "Step",
    "Actor",
    "Capability",
    "Agent",
    "Skill",
    "Tool",
    "Target",
    "EnvironmentSnapshot",
    "Artifact",
    "Observation",
    "Claim",
    "RootCause",
    "Decision",
    "Uncertainty",
    "ScopeBoundary",
    "Action",
    "Approval",
    "Policy",
    "Verification",
    "VerificationReceipt",
    "Pattern",
    "Runbook",
    "SkillVersion",
    "EvalCase",
    "DriftFinding",
    "ExternalIssue",
}

EDGE_TYPES = {
    "instance_of",
    "contains",
    "has_run",
    "targets",
    "runs_in",
    "uses",
    "invokes",
    "precedes",
    "produces",
    "derived_from",
    "supports",
    "refutes",
    "explains",
    "approved_by",
    "guarded_by",
    "modifies",
    "checks",
    "verified_by",
    "satisfies",
    "blocked_by",
    "retry_of",
    "regression_of",
    "generalizes_to",
    "implemented_by",
    "tested_by",
    "supersedes",
    "deprecated_by",
    "references",
    "frames",
    "informs",
}

CASE_STATES = {
    "intake",
    "observe",
    "analyze",
    "plan",
    "authorize",
    "execute",
    "verify",
    "close",
    "promote",
    "blocked",
    "reopen",
    "regress",
}

ALLOWED_TRANSITIONS = {
    "intake": {"observe", "blocked"},
    "observe": {"analyze", "blocked"},
    "analyze": {"plan", "blocked"},
    "plan": {"authorize", "execute", "blocked"},
    "authorize": {"execute", "blocked"},
    "execute": {"verify", "blocked"},
    "verify": {"execute", "close", "blocked"},
    "close": {"promote", "reopen", "regress"},
    "promote": {"reopen", "regress"},
    "blocked": {"observe", "analyze", "plan", "authorize", "execute", "close"},
    "reopen": {"observe"},
    "regress": {"observe"},
}


class ACGError(ValueError):
    """Raised for deterministic protocol or ledger errors."""


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ACGError(f"{field} must be an object")
    return value


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ACGError(f"{field} must be a non-empty string")
    return value


def validate_event(event: dict[str, Any], *, line_number: int | None = None) -> None:
    prefix = f"line {line_number}: " if line_number is not None else ""
    try:
        if event.get("schema_version") != SCHEMA_VERSION:
            raise ACGError(
                f"schema_version must be {SCHEMA_VERSION!r}, got {event.get('schema_version')!r}"
            )
        _require_text(event.get("event_id"), "event_id")
        _require_text(event.get("case_id"), "case_id")

        sequence = event.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise ACGError("sequence must be an integer >= 1")

        occurred_at = _require_text(event.get("occurred_at"), "occurred_at")
        parsed_time = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        if parsed_time.tzinfo is None:
            raise ACGError("occurred_at must include a timezone")

        kind = _require_text(event.get("kind"), "kind")
        if kind not in EVENT_KINDS:
            raise ACGError(f"unsupported event kind: {kind}")

        actor = _require_mapping(event.get("actor"), "actor")
        if actor.get("type") not in ACTOR_TYPES:
            raise ACGError(f"unsupported actor.type: {actor.get('type')!r}")
        _require_text(actor.get("id"), "actor.id")

        provenance = _require_mapping(event.get("provenance"), "provenance")
        if provenance.get("capture_mode") not in CAPTURE_MODES:
            raise ACGError(
                f"unsupported provenance.capture_mode: {provenance.get('capture_mode')!r}"
            )
        refs = provenance.get("source_refs")
        if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
            raise ACGError("provenance.source_refs must be an array of strings")

        if kind == "graph.declared":
            graph = _require_mapping(event.get("graph"), "graph")
            _require_text(graph.get("id"), "graph.id")
            _require_text(graph.get("type"), "graph.type")
            _require_text(graph.get("root_id"), "graph.root_id")
        elif kind == "node.recorded":
            node = _require_mapping(event.get("node"), "node")
            _require_text(node.get("id"), "node.id")
            node_type = _require_text(node.get("type"), "node.type")
            if node_type not in NODE_TYPES:
                raise ACGError(f"unsupported node.type: {node_type}")
            _require_text(node.get("label"), "node.label")
            attrs = node.get("attrs", {})
            if not isinstance(attrs, dict):
                raise ACGError("node.attrs must be an object")
        elif kind == "edge.recorded":
            edge = _require_mapping(event.get("edge"), "edge")
            _require_text(edge.get("id"), "edge.id")
            edge_type = _require_text(edge.get("type"), "edge.type")
            if edge_type not in EDGE_TYPES:
                raise ACGError(f"unsupported edge.type: {edge_type}")
            _require_text(edge.get("from"), "edge.from")
            _require_text(edge.get("to"), "edge.to")
            attrs = edge.get("attrs", {})
            if not isinstance(attrs, dict):
                raise ACGError("edge.attrs must be an object")
        else:
            transition = _require_mapping(event.get("transition"), "transition")
            _require_text(transition.get("subject_id"), "transition.subject_id")
            from_state = _require_text(transition.get("from"), "transition.from")
            to_state = _require_text(transition.get("to"), "transition.to")
            if from_state not in CASE_STATES or to_state not in CASE_STATES:
                raise ACGError(f"unsupported state transition: {from_state} -> {to_state}")
            _require_text(transition.get("reason"), "transition.reason")
    except (ACGError, TypeError, ValueError) as exc:
        if isinstance(exc, ACGError):
            raise ACGError(prefix + str(exc)) from exc
        raise ACGError(prefix + str(exc)) from exc


def load_events(path: str | Path) -> list[dict[str, Any]]:
    ledger_path = Path(path)
    if not ledger_path.is_file():
        raise ACGError(f"ledger does not exist: {ledger_path}")

    return parse_events(ledger_path.read_text(encoding="utf-8-sig"))


def parse_events(text: str) -> list[dict[str, Any]]:
    """Validate an immutable ledger snapshot without reopening its source."""

    events: list[dict[str, Any]] = []
    event_ids: set[str] = set()
    case_ids: set[str] = set()

    with io.StringIO(text) as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ACGError(f"line {line_number}: invalid JSON: {exc}") from exc
            if not isinstance(event, dict):
                raise ACGError(f"line {line_number}: event must be an object")
            validate_event(event, line_number=line_number)
            if event["event_id"] in event_ids:
                raise ACGError(f"line {line_number}: duplicate event_id {event['event_id']}")
            expected_sequence = len(events) + 1
            if event["sequence"] != expected_sequence:
                raise ACGError(
                    f"line {line_number}: expected sequence {expected_sequence}, got {event['sequence']}"
                )
            event_ids.add(event["event_id"])
            case_ids.add(event["case_id"])
            events.append(event)

    if not events:
        raise ACGError("ledger is empty")
    if events[0]["kind"] != "graph.declared":
        raise ACGError("first event must be graph.declared")
    if sum(event["kind"] == "graph.declared" for event in events) != 1:
        raise ACGError("ledger must contain exactly one graph.declared event")
    if len(case_ids) != 1:
        raise ACGError(f"one ledger must contain exactly one case_id, got {sorted(case_ids)}")
    return events
