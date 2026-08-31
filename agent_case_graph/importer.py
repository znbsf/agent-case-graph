from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .ledger import canonical_json, sha256_file
from .model import ACGError, SCHEMA_VERSION


DEFAULT_FILES = ("README.md", "EVIDENCE.md", "MANIFEST.md", "MANIFEST.json")


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _portable_source(path: Path, workspace_root: Path) -> str:
    try:
        return path.relative_to(workspace_root).as_posix()
    except ValueError as exc:
        raise ACGError(f"source is outside workspace root: {path}") from exc


def _first_heading(text: str, fallback: str) -> str:
    for line in text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1)
    return fallback


def _section(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return ""
    value = match.group(1).strip()
    if value.upper() == "TBD":
        return ""
    return value


def _split_markdown_row(line: str) -> list[str]:
    value = line.strip()
    if not (value.startswith("|") and value.endswith("|")):
        return []
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in value[1:-1]:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    cells.append("".join(current).strip())
    return cells


def _evidence_rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        cells = _split_markdown_row(line)
        if len(cells) != 6:
            continue
        if cells[0].lower() == "time" or all(set(cell) <= {"-", ":", " "} for cell in cells):
            continue
        rows.append(
            dict(
                zip(
                    ("time", "type", "source", "output", "conclusion", "risk"),
                    cells,
                    strict=True,
                )
            )
        )
    return rows


def import_issue_events(
    issue_dir: str | Path,
    *,
    workspace_root: str | Path,
    case_id: str | None = None,
    include_paths: Iterable[str] = (),
) -> list[dict[str, Any]]:
    root = Path(workspace_root).resolve()
    issue = Path(issue_dir).resolve()
    if not issue.is_dir():
        raise ACGError(f"issue directory does not exist: {issue}")
    if not _inside(issue, root):
        raise ACGError(f"issue directory is outside workspace root: {issue}")

    resolved_case_id = case_id or issue.name
    readme_path = issue / "README.md"
    if not readme_path.is_file():
        raise ACGError(f"historical import requires README.md: {readme_path}")

    selected: list[Path] = []
    for name in DEFAULT_FILES:
        candidate = (issue / name).resolve()
        if candidate.is_file():
            selected.append(candidate)
    for relative in include_paths:
        candidate = (issue / relative).resolve()
        if not _inside(candidate, issue):
            raise ACGError(f"include path escapes issue directory: {relative}")
        if not candidate.is_file():
            raise ACGError(f"included file does not exist: {relative}")
        if candidate not in selected:
            selected.append(candidate)

    selected.sort(key=lambda path: _portable_source(path, root).lower())
    base_mtime = min(path.stat().st_mtime for path in selected)
    base_time = datetime.fromtimestamp(base_mtime).astimezone().replace(microsecond=0)
    readme_text = readme_path.read_text(encoding="utf-8-sig", errors="replace")
    title = _first_heading(readme_text, resolved_case_id)

    events: list[dict[str, Any]] = []

    def emit(
        kind: str,
        payload: dict[str, Any],
        *,
        source_refs: list[str],
        run_id: str | None = None,
    ) -> None:
        sequence = len(events) + 1
        event_key = f"{resolved_case_id}:{sequence}:{kind}:{canonical_json(payload)}"
        events.append(
            {
                "schema_version": SCHEMA_VERSION,
                "event_id": f"evt-{uuid.uuid5(uuid.NAMESPACE_URL, event_key).hex}",
                "case_id": resolved_case_id,
                "run_id": run_id,
                "sequence": sequence,
                "occurred_at": (base_time + timedelta(seconds=sequence - 1)).isoformat(),
                "kind": kind,
                "actor": {"type": "tool", "id": "agent-case-graph-importer"},
                "provenance": {
                    "capture_mode": "reconstructed",
                    "source_refs": source_refs,
                },
                **payload,
            }
        )

    case_node_id = f"case:{resolved_case_id}"
    run_node_id = f"run:{resolved_case_id}:reconstructed-001"
    readme_ref = _portable_source(readme_path, root)
    emit(
        "graph.declared",
        {
            "graph": {
                "id": f"graph:case:{resolved_case_id}",
                "type": "case",
                "root_id": case_node_id,
                "schema_version": SCHEMA_VERSION,
            }
        },
        source_refs=[readme_ref],
    )
    emit(
        "node.recorded",
        {
            "node": {
                "id": case_node_id,
                "type": "Case",
                "label": title,
                "attrs": {
                    "status": "reconstructed",
                    "capture_mode": "reconstructed",
                    "source_issue_dir": _portable_source(issue, root),
                },
            }
        },
        source_refs=[readme_ref],
    )
    emit(
        "node.recorded",
        {
            "node": {
                "id": run_node_id,
                "type": "Run",
                "label": "Historical reconstruction run",
                "attrs": {
                    "status": "reconstructed",
                    "capture_mode": "reconstructed",
                    "source_file_count": len(selected),
                },
            }
        },
        source_refs=[readme_ref],
        run_id=run_node_id,
    )
    emit(
        "edge.recorded",
        {
            "edge": {
                "id": f"edge:{resolved_case_id}:has-run",
                "type": "has_run",
                "from": case_node_id,
                "to": run_node_id,
                "attrs": {},
            }
        },
        source_refs=[readme_ref],
        run_id=run_node_id,
    )
    scope_id = f"scope:{resolved_case_id}:historical-reconstruction"
    emit(
        "node.recorded",
        {
            "node": {
                "id": scope_id,
                "type": "ScopeBoundary",
                "label": "Historical documents are not an original Agent trajectory",
                "attrs": {
                    "capture_mode": "reconstructed",
                    "limitation": "missing original step-by-step agent events",
                },
            }
        },
        source_refs=[readme_ref],
        run_id=run_node_id,
    )
    emit(
        "edge.recorded",
        {
            "edge": {
                "id": f"edge:{resolved_case_id}:scope",
                "type": "contains",
                "from": case_node_id,
                "to": scope_id,
                "attrs": {},
            }
        },
        source_refs=[readme_ref],
        run_id=run_node_id,
    )

    artifact_ids: dict[Path, str] = {}
    for index, path in enumerate(selected, start=1):
        source_ref = _portable_source(path, root)
        artifact_id = f"artifact:{resolved_case_id}:{index:03d}"
        artifact_ids[path] = artifact_id
        emit(
            "node.recorded",
            {
                "node": {
                    "id": artifact_id,
                    "type": "Artifact",
                    "label": source_ref,
                    "attrs": {
                        "source_path": source_ref,
                        "sha256": sha256_file(path),
                        "size_bytes": path.stat().st_size,
                        "capture_mode": "reconstructed",
                        "content_loaded": path.suffix.lower() in {".md", ".json"},
                    },
                }
            },
            source_refs=[source_ref],
            run_id=run_node_id,
        )
        emit(
            "edge.recorded",
            {
                "edge": {
                    "id": f"edge:{resolved_case_id}:run-artifact:{index:03d}",
                    "type": "produces",
                    "from": run_node_id,
                    "to": artifact_id,
                    "attrs": {"relationship": "reconstructed-input"},
                }
            },
            source_refs=[source_ref],
            run_id=run_node_id,
        )

    evidence_path = (issue / "EVIDENCE.md").resolve()
    if evidence_path in artifact_ids:
        evidence_ref = _portable_source(evidence_path, root)
        evidence_text = evidence_path.read_text(encoding="utf-8-sig", errors="replace")
        for index, row in enumerate(_evidence_rows(evidence_text), start=1):
            label = row["conclusion"] or row["output"] or row["source"]
            observation_id = f"observation:{resolved_case_id}:ledger:{index:03d}"
            emit(
                "node.recorded",
                {
                    "node": {
                        "id": observation_id,
                        "type": "Observation",
                        "label": label[:240],
                        "attrs": {**row, "capture_mode": "reconstructed"},
                    }
                },
                source_refs=[evidence_ref],
                run_id=run_node_id,
            )
            emit(
                "edge.recorded",
                {
                    "edge": {
                        "id": f"edge:{resolved_case_id}:observation-source:{index:03d}",
                        "type": "derived_from",
                        "from": observation_id,
                        "to": artifact_ids[evidence_path],
                        "attrs": {},
                    }
                },
                source_refs=[evidence_ref],
                run_id=run_node_id,
            )
            emit(
                "edge.recorded",
                {
                    "edge": {
                        "id": f"edge:{resolved_case_id}:run-observation:{index:03d}",
                        "type": "produces",
                        "from": run_node_id,
                        "to": observation_id,
                        "attrs": {},
                    }
                },
                source_refs=[evidence_ref],
                run_id=run_node_id,
            )
            if row["conclusion"]:
                claim_id = f"claim:{resolved_case_id}:ledger:{index:03d}"
                emit(
                    "node.recorded",
                    {
                        "node": {
                            "id": claim_id,
                            "type": "Claim",
                            "label": row["conclusion"][:240],
                            "attrs": {
                                "status": "reported",
                                "capture_mode": "reconstructed",
                                "risk": row["risk"],
                            },
                        }
                    },
                    source_refs=[evidence_ref],
                    run_id=run_node_id,
                )
                emit(
                    "edge.recorded",
                    {
                        "edge": {
                            "id": f"edge:{resolved_case_id}:observation-claim:{index:03d}",
                            "type": "supports",
                            "from": observation_id,
                            "to": claim_id,
                            "attrs": {"support_level": "historical-ledger"},
                        }
                    },
                    source_refs=[evidence_ref],
                    run_id=run_node_id,
                )
                emit(
                    "edge.recorded",
                    {
                        "edge": {
                            "id": f"edge:{resolved_case_id}:case-claim:{index:03d}",
                            "type": "contains",
                            "from": case_node_id,
                            "to": claim_id,
                            "attrs": {},
                        }
                    },
                    source_refs=[evidence_ref],
                    run_id=run_node_id,
                )

    current_conclusion = _section(readme_text, "Current Conclusion")
    if current_conclusion:
        claim_id = f"claim:{resolved_case_id}:readme-current-conclusion"
        emit(
            "node.recorded",
            {
                "node": {
                    "id": claim_id,
                    "type": "Claim",
                    "label": current_conclusion.splitlines()[0][:240],
                    "attrs": {
                        "status": "self_reported",
                        "capture_mode": "reconstructed",
                        "full_text": current_conclusion,
                    },
                }
            },
            source_refs=[readme_ref],
            run_id=run_node_id,
        )
        emit(
            "edge.recorded",
            {
                "edge": {
                    "id": f"edge:{resolved_case_id}:readme-claim-source",
                    "type": "derived_from",
                    "from": claim_id,
                    "to": artifact_ids[readme_path.resolve()],
                    "attrs": {"not_independent_evidence": True},
                }
            },
            source_refs=[readme_ref],
            run_id=run_node_id,
        )
        emit(
            "edge.recorded",
            {
                "edge": {
                    "id": f"edge:{resolved_case_id}:case-readme-claim",
                    "type": "contains",
                    "from": case_node_id,
                    "to": claim_id,
                    "attrs": {},
                }
            },
            source_refs=[readme_ref],
            run_id=run_node_id,
        )

    verified = _section(readme_text, "Verified")
    if verified:
        observation_id = f"observation:{resolved_case_id}:readme-verified"
        emit(
            "node.recorded",
            {
                "node": {
                    "id": observation_id,
                    "type": "Observation",
                    "label": "Historical README reports verification",
                    "attrs": {
                        "reported_verification": verified,
                        "independently_replayed": False,
                        "capture_mode": "reconstructed",
                    },
                }
            },
            source_refs=[readme_ref],
            run_id=run_node_id,
        )
        emit(
            "edge.recorded",
            {
                "edge": {
                    "id": f"edge:{resolved_case_id}:verified-source",
                    "type": "derived_from",
                    "from": observation_id,
                    "to": artifact_ids[readme_path.resolve()],
                    "attrs": {},
                }
            },
            source_refs=[readme_ref],
            run_id=run_node_id,
        )

    not_verified = _section(readme_text, "Not Verified")
    if not_verified:
        uncertainty_id = f"uncertainty:{resolved_case_id}:readme-not-verified"
        emit(
            "node.recorded",
            {
                "node": {
                    "id": uncertainty_id,
                    "type": "Uncertainty",
                    "label": "Historical case has unverified scope",
                    "attrs": {
                        "details": not_verified,
                        "capture_mode": "reconstructed",
                    },
                }
            },
            source_refs=[readme_ref],
            run_id=run_node_id,
        )
        emit(
            "edge.recorded",
            {
                "edge": {
                    "id": f"edge:{resolved_case_id}:case-uncertainty",
                    "type": "contains",
                    "from": case_node_id,
                    "to": uncertainty_id,
                    "attrs": {},
                }
            },
            source_refs=[readme_ref],
            run_id=run_node_id,
        )

    for from_state, to_state, reason in (
        ("intake", "observe", "Historical issue documents were collected from an explicit allowlist"),
        ("observe", "analyze", "Evidence ledger and README sections were reconstructed"),
    ):
        emit(
            "state.changed",
            {
                "transition": {
                    "subject_id": case_node_id,
                    "from": from_state,
                    "to": to_state,
                    "reason": reason,
                }
            },
            source_refs=[readme_ref],
            run_id=run_node_id,
        )

    return events
