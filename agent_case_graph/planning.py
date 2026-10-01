"""Source-bound planning packets and proposal checks; neither grants execution."""

from __future__ import annotations

import re
import hashlib
from pathlib import Path
from typing import Any

from .graph_runtime import build_graph_runtime_advice
from .lint import lint_graph
from .model import ACGError, parse_events
from .project_profile import inspect_project, repository_root, workspace_path
from .projector import project_events

PACKET_VERSION = "project-planning-0.1"
PLAN_VERSION = "project-plan-0.1"
MAX_TASKS = 12


def runtime_advice(workspace: str | Path, ledger: str, *, run_id: str | None = None) -> dict[str, Any]:
    root = repository_root(workspace)
    path = workspace_path(root, ledger, must_exist=True, allow_artifacts=True)
    try:
        with path.open("rb") as stream:
            data = stream.read(4_000_001)
        if len(data) > 4_000_000:
            raise ACGError("ledger exceeds the local plugin's 4 MB input limit")
        events = parse_events(data.decode("utf-8-sig"))
        digest = hashlib.sha256(data).hexdigest()
    except (OSError, UnicodeError) as exc:
        raise ACGError("unable to read the workspace ledger") from exc
    graph = project_events(events, ledger_path=path, ledger_sha256=digest)
    findings = lint_graph(graph)
    errors = [finding for finding in findings if finding["severity"] == "error"]
    if errors:
        raise ACGError("runtime advice refuses a ledger with lint errors: " + ", ".join(sorted({finding["code"] for finding in errors})))
    return {
        "ledger_path": ledger, "ledger_sha256": digest,
        "advice": build_graph_runtime_advice(graph, run_id=run_id),
    }


def _goal(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ACGError("goal must be a non-empty string of at most 2000 characters")
    return value.strip()


def prepare_plan(
    workspace: str | Path, goal: str, *, ledger: str | None = None, run_id: str | None = None,
) -> dict[str, Any]:
    goal = _goal(goal)
    if run_id and not ledger:
        raise ACGError("run_id requires an explicit workspace ledger")
    profile = inspect_project(workspace)
    tokens = set(re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", goal.lower()))
    ranked = []
    for row in profile["inventory"]["files"]:
        score = sum(token in row["path"].lower() for token in tokens)
        if score:
            ranked.append((score, row["path"]))
    focus = [path for _, path in sorted(ranked, key=lambda item: (-item[0], item[1]))[:8]]
    neighboring = sorted({
        edge["to"] if edge["from"] in focus else edge["from"]
        for edge in profile["relationships"]
        if edge["from"] in focus or edge["to"] in focus
    } - set(focus))[:8]
    verification = profile["verification"]
    observed_refs = [source["id"] for source in profile["sources"]]
    checks: list[dict[str, Any]] = []
    inventory = profile["inventory"]
    parse_gaps = [row["path"] for row in profile["python_modules"] if not row["parsed"]]
    parse_gaps.extend(row["path"] for row in profile["manifests"] if not row["parsed"])
    if inventory["truncated"] or inventory["skipped"] or parse_gaps:
        checks.append({
            "id": "resolve-context-gaps", "priority": 0,
            "reason": "Some repository inputs could not be inspected or parsed; absence conclusions are incomplete.",
            "source_refs": observed_refs[:3], "parse_gap_paths": parse_gaps,
            "acceptance": "Inspect the missing inputs relevant to the goal and record the remaining scope limit.",
        })
    if verification["test_files"] or verification["declared_commands"]:
        checks.append({
            "id": "verify-baseline", "priority": 1,
            "reason": "Test files or commands are declared, but this static snapshot has no execution results.",
            "source_refs": sorted({f"file:{path}" for path in verification["test_files"][:4]} | {
                ref for command in verification["declared_commands"] for ref in command["source_refs"]
            }),
            "candidate_commands": verification["declared_commands"],
            "acceptance": "Record an actual command, environment, exit code and result before asserting that checks pass.",
        })
    else:
        checks.append({
            "id": "define-validation", "priority": 1,
            "reason": "No test entry was observed within this inspection scope.",
            "source_refs": observed_refs[:3],
            "acceptance": "Define observable acceptance criteria and a verification method appropriate to the requested change.",
        })
    if not verification["ci_files"]:
        checks.append({
            "id": "check-ci-coverage", "priority": 2,
            "reason": "No GitHub Actions workflow was observed; other CI systems may still exist.",
            "source_refs": observed_refs[:3],
            "acceptance": "Identify the project's CI system and check that it covers the proposed behavior.",
        })
    return {
        "protocol_version": PACKET_VERSION, "data_origin": "derived", "goal": goal,
        "source_snapshot_sha256": profile["snapshot_sha256"], "profile": profile,
        "focus": {
            "match_policy": "literal_goal_terms_in_paths_only_not_semantic_relevance",
            "paths": focus, "import_neighbors": neighboring,
            "status": "lexical_matches" if focus else "agent_selection_required",
        },
        "suggested_evidence_checks": checks,
        "runtime": runtime_advice(workspace, ledger, run_id=run_id) if ledger else None,
        "plan_contract": {
            "version": PLAN_VERSION, "maximum_tasks": MAX_TASKS,
            "required_fields": ["version", "source_snapshot_sha256", "goal", "tasks"],
            "task_fields": ["id", "title", "source_refs", "target_paths", "depends_on", "acceptance_criteria"],
            "source_ref_format": "Use exact IDs from profile.sources, for example file:pyproject.toml.",
        },
        "execution_status": "proposal_context_only",
        "limitations": [
            "The host agent authors the goal-specific plan; lexical matches and evidence checks are not an autonomous planner.",
            "Declared commands are candidate data, not execution instructions or approval.",
            "A valid proposal does not make tasks runtime-ready or bypass the canonical graph's authorization and evidence gates.",
        ],
    }


def check_plan(workspace: str | Path, plan: dict[str, Any]) -> dict[str, Any]:
    profile = inspect_project(workspace)
    root = repository_root(workspace)
    return _check_plan(root, profile, plan)


def _check_plan(root: Path, profile: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Shared validator; historical ledger checks supply historical source IDs."""
    errors: list[dict[str, Any]] = []

    def error(code: str, **fields: Any) -> None:
        errors.append({"code": code, **fields})

    if not isinstance(plan, dict):
        plan = {}
        error("plan_must_be_an_object")
    required = {"version", "source_snapshot_sha256", "goal", "tasks"}
    if set(plan) != required:
        error("invalid_plan_fields", required_fields=sorted(required))
    if plan.get("version") != PLAN_VERSION:
        error("unsupported_plan_version")
    if plan.get("source_snapshot_sha256") != profile["snapshot_sha256"]:
        error("stale_repository_snapshot", expected_sha256=profile["snapshot_sha256"])
    try:
        _goal(plan.get("goal"))
    except ACGError:
        error("invalid_goal")
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= MAX_TASKS:
        error("invalid_task_count", maximum=MAX_TASKS)
        tasks = []
    sources = {source["id"] for source in profile["sources"]}
    ids: set[str] = set()
    dependencies: dict[str, list[str]] = {}
    task_fields = {"id", "title", "source_refs", "target_paths", "depends_on", "acceptance_criteria"}
    for index, task in enumerate(tasks):
        if not isinstance(task, dict) or set(task) != task_fields:
            error("invalid_task_fields", task_index=index)
            continue
        task_id = task.get("id")
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", task_id):
            error("invalid_task_id", task_index=index)
            continue
        if task_id in ids:
            error("duplicate_task_id", task_id=task_id)
        ids.add(task_id)
        if not isinstance(task["title"], str) or not task["title"].strip() or len(task["title"]) > 400:
            error("invalid_task_title", task_id=task_id)
        for key in ("source_refs", "target_paths", "depends_on", "acceptance_criteria"):
            values = task[key]
            if not isinstance(values, list) or len(values) > 24 or any(not isinstance(value, str) or not value.strip() or len(value) > 2000 for value in values):
                error("invalid_task_list", task_id=task_id, field=key)
                task = {**task, key: []}
        if not task["source_refs"]:
            error("missing_source_refs", task_id=task_id)
        for ref in task["source_refs"]:
            if ref not in sources:
                error("unknown_source_ref", task_id=task_id, source_ref=ref)
        for path in task["target_paths"]:
            try:
                workspace_path(root, path)
            except (ACGError, OSError):
                error("unsafe_target_path", task_id=task_id, target_path=path)
        if not task["acceptance_criteria"]:
            error("missing_acceptance_criteria", task_id=task_id)
        dependencies[task_id] = task["depends_on"]
    for task_id, parents in dependencies.items():
        for parent in parents:
            if parent not in ids:
                error("unknown_dependency", task_id=task_id, dependency_id=parent)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> bool:
        if task_id in visiting:
            return True
        if task_id in visited:
            return False
        visiting.add(task_id)
        for parent in dependencies.get(task_id, []):
            if parent in dependencies and visit(parent):
                return True
        visiting.remove(task_id)
        visited.add(task_id)
        return False

    if any(visit(task_id) for task_id in sorted(dependencies)):
        error("dependency_cycle")
    return {
        "protocol_version": PLAN_VERSION,
        "status": "invalid_proposal" if errors else "valid_proposal",
        "valid": not errors, "errors": errors,
        "current_snapshot_sha256": profile["snapshot_sha256"], "task_count": len(tasks),
        "execution_authorized": False,
        "limitations": ["This checks structure, snapshot freshness, source existence and dependency order; it does not prove semantic accuracy or authorize execution."],
    }
