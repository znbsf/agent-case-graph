"""Small, snapshot-bound pages over the existing bounded repository profile."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .ledger import canonical_json
from .model import ACGError
from .project_profile import inspect_project, repository_root, workspace_path

QUERY_VERSION = "project-query-0.1"
MAX_PAGE_SIZE = 50


def _encode_cursor(value: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(canonical_json(value).encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> dict[str, Any]:
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= 1024 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        data = json.loads(raw)
        if (not isinstance(data, dict) or set(data) != {"version", "snapshot", "query", "offset"}
                or data["version"] != QUERY_VERSION or type(data["offset"]) is not int or data["offset"] < 1
                or any(not isinstance(data[key], str) or not re.fullmatch(r"[0-9a-f]{64}", data[key]) for key in ("snapshot", "query"))
                or _encode_cursor(data) != value):
            raise ValueError
        return data
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ACGError("invalid query cursor; start a new query") from exc


def query_project(
    workspace: str | Path, *, path: str | None = None, module: str | None = None,
    include_neighbors: bool = True, page_size: int = 20, cursor: str | None = None,
) -> dict[str, Any]:
    """Select a path subtree or exact Python module, with optional one-hop imports."""
    if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ACGError(f"page_size must be an integer between 1 and {MAX_PAGE_SIZE}")
    if type(include_neighbors) is not bool:
        raise ACGError("include_neighbors must be a boolean")
    if path is not None and module is not None:
        raise ACGError("select either path or module, not both")
    root = repository_root(workspace)
    if path is not None:
        selected_path = workspace_path(root, path)
        if not selected_path.exists():
            raise ACGError("query path must exist within the bound repository")
        canonical_path = selected_path.resolve().relative_to(root).as_posix()
        if path != canonical_path:
            raise ACGError(f"query path must use the repository's canonical spelling: {canonical_path}")
    if module is not None and (not isinstance(module, str) or len(module) > 2000
                              or not all(part.isidentifier() for part in module.split("."))):
        raise ACGError("module must be an exact dotted Python module name")
    query = {"path": path, "module": module, "include_neighbors": include_neighbors, "page_size": page_size}
    query_hash = hashlib.sha256(canonical_json(query).encode("utf-8")).hexdigest()
    decoded = _decode_cursor(cursor) if cursor is not None else None
    profile = inspect_project(root)
    snapshot = profile["snapshot_sha256"]
    if decoded:
        if decoded["query"] != query_hash:
            raise ACGError("query cursor belongs to different parameters; start a new query")
        if decoded["snapshot"] != snapshot:
            raise ACGError("repository changed since the query cursor; start a new query")
    files = {row["path"]: row for row in profile["inventory"]["files"]}
    if module is not None:
        matches = [row["path"] for row in profile["python_modules"] if row["module"] == module]
        if len(matches) != 1:
            raise ACGError("module must resolve to one inspected Python file; absent or ambiguous within the inspection scope")
        selected = set(matches)
    elif path is not None:
        selected = {name for name in files if name == path or name.startswith(path + "/")}
    else:
        selected = set(files)
    direct = set(selected)
    if include_neighbors:
        for edge in profile["relationships"]:
            if edge["from"] in direct or edge["to"] in direct:
                selected.update((edge["from"], edge["to"]))
    ordered = sorted(selected)
    offset = decoded["offset"] if decoded else 0
    if decoded and (offset >= len(ordered) or offset % page_size):
        raise ACGError("invalid query cursor offset; start a new query")
    page = ordered[offset:offset + page_size]
    page_set = set(page)
    details = {kind: {row["path"]: row for row in profile[kind]} for kind in ("manifests", "documents", "python_modules")}
    items = []
    for name in page:
        item = {**files[name], "selection": "direct" if name in direct else "import_neighbor", "source_refs": [f"file:{name}"]}
        for kind, values in details.items():
            if name in values:
                item[kind] = values[name]
        items.append(item)
    next_offset = offset + len(page)
    next_cursor = _encode_cursor({"version": QUERY_VERSION, "snapshot": snapshot, "query": query_hash, "offset": next_offset}) if next_offset < len(ordered) else None
    return {
        "protocol_version": QUERY_VERSION, "data_origin": profile["data_origin"],
        "project": profile["project"], "git": profile["git"], "source_snapshot_sha256": snapshot,
        "query": query, "selection_policy": "exact_path_or_subtree_or_python_module_with_optional_one_hop_static_imports",
        "pagination": {"offset": offset, "page_size": page_size, "returned_file_count": len(items),
                       "matched_file_count": len(ordered), "direct_file_count": len(direct), "next_cursor": next_cursor},
        "items": items, "sources": [row for row in profile["sources"] if row["path"] in page_set],
        # An edge appears only on its importing file's page, including targets on other pages.
        "relationships": [edge for edge in profile["relationships"] if edge["from"] in page_set and edge["to"] in selected],
        "inspection_scope": {key: value for key, value in profile["inventory"].items() if key != "files"},
        "execution_status": "not_run", "execution_authorized": False,
        "limitations": [*profile["limitations"],
            "Pagination limits returned context; each request still recomputes the bounded whole-repository profile.",
            "A path query can be empty when inputs are unsupported, ignored or over budget; inspect inspection_scope before concluding absence.",
            "Relationships are outbound from this page; targets may be on later pages. Python neighbors are static references, not semantic test coverage.",
            "Cursors bind observed snapshot and exact query parameters; they are not execution approvals or atomic filesystem snapshots.",
        ],
    }
