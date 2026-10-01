"""Bounded, read-only repository observations for an agent's planning context."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import stat
import subprocess
import tomllib
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from .ledger import canonical_json
from .model import ACGError

PROFILE_VERSION = "project-profile-0.1"
MAX_FILES = 400
MAX_FILE_BYTES = 256_000
MAX_TOTAL_BYTES = 4_000_000
EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "env", "node_modules", "vendor", "build", "dist",
    "generated", ".artifacts", "__pycache__", ".pytest_cache", ".godot",
    "secrets", "credentials", ".ssh", ".aws",
}
SOURCE_LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript",
    ".cjs": "JavaScript", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".rs": "Rust", ".go": "Go",
    ".java": "Java", ".kt": "Kotlin", ".dart": "Dart", ".gd": "GDScript",
    ".cs": "C#", ".cpp": "C++", ".c": "C", ".h": "C/C++",
    ".ps1": "PowerShell", ".sh": "Shell",
}
MANIFESTS = {"pyproject.toml", "package.json", "cargo.toml", "go.mod", "pubspec.yaml", "project.godot"}


def _git(root: Path, *args: str, allow_failure: bool = False) -> str:
    try:
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(root), *args], capture_output=True, timeout=15,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ACGError("repository inspection requires an available Git executable") from exc
    if result.returncode:
        if allow_failure:
            return ""
        detail = result.stderr.decode("utf-8", errors="replace").replace(str(root), "<workspace>").replace(root.as_posix(), "<workspace>").strip()
        raise ACGError(f"Git inspection failed ({args[0]}, exit {result.returncode}): {detail[:400]}")
    return result.stdout.decode("utf-8", errors="replace")


def repository_root(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ACGError("workspace root must be an existing directory")
    actual = Path(_git(root, "rev-parse", "--show-toplevel").strip()).resolve()
    if root != actual:
        raise ACGError("workspace root must be the Git repository root, not a subdirectory")
    return root


def is_excluded(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1].lower() if parts else ""
    return (
        any(part.lower() in EXCLUDED_DIRS or part.lower().endswith(".egg-info") for part in parts)
        or name == ".env" or name.startswith(".env.")
        or name in {"id_rsa", "id_ed25519", ".npmrc", ".pypirc", "credentials.json", "secrets.json"}
        or Path(name).suffix in {".pem", ".key", ".p12", ".pfx", ".keystore"}
    )


def workspace_path(root: Path, relative: str, *, must_exist: bool = False, allow_artifacts: bool = False) -> Path:
    """Reject traversal and links, including linked parents and Windows junctions."""
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative or "\x00" in relative:
        raise ACGError("path must be a non-empty workspace-relative POSIX path")
    parts = relative.split("/")
    if relative.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ACGError("path must stay within the bound workspace")
    # Win32 aliases trailing dots/spaces to a different spelling of the same
    # path. Reject those spellings before checking exclusions or traversing.
    if any(part.endswith((".", " ")) for part in parts):
        raise ACGError("path components must not end with a dot or space")
    # An explicitly selected ledger/receipt can live in .artifacts. General
    # inspection and proposal targets keep the default exclusion policy.
    artifact_input = allow_artifacts and parts[0] == ".artifacts" and len(parts) > 1 and not is_excluded("/".join(parts[1:]))
    if is_excluded(relative) and not artifact_input:
        raise ACGError("path is excluded by the repository inspection policy")
    current = root
    for part in parts:
        current = current / part
        try:
            attributes = getattr(current.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            attributes = 0
        if current.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
            raise ACGError("linked paths are outside the inspection policy")
    if not current.resolve().is_relative_to(root):
        raise ACGError("path escapes the bound workspace")
    if must_exist and not current.is_file():
        raise ACGError("source must be an existing workspace file")
    return current


def _kind(path: str) -> str:
    item = PurePosixPath(path)
    name = item.name.lower()
    if name in MANIFESTS:
        return "manifest"
    if path.startswith(".github/workflows/") and item.suffix in {".yml", ".yaml"}:
        return "ci"
    if item.suffix.lower() in {".md", ".rst"}:
        return "document"
    if item.suffix.lower() in SOURCE_LANGUAGES:
        if "tests" in item.parts or "test" in item.parts or name.startswith("test_") or ".test." in name:
            return "test"
        return "source"
    if name in {".gitignore", ".gitattributes"} or item.suffix.lower() in {".json", ".toml", ".yml", ".yaml", ".html", ".css", ".xml"}:
        return "configuration"
    return "other"


def _manifest(path: str, content: str) -> dict[str, Any]:
    name = PurePosixPath(path).name.lower()
    result: dict[str, Any] = {"path": path, "source_refs": [f"file:{path}"], "parsed": False}
    try:
        if name == "pyproject.toml":
            data = tomllib.loads(content)
            project = data.get("project", {})
            result.update(
                ecosystem="Python", parsed=True, name=project.get("name"),
                description=project.get("description"), version=project.get("version"),
                requires_python=project.get("requires-python"),
                dependencies=project.get("dependencies", []),
                optional_dependencies=project.get("optional-dependencies", {}),
                entry_points=project.get("scripts", {}),
            )
        elif name == "package.json":
            data = json.loads(content)
            if not isinstance(data, dict):
                raise ValueError("manifest must be an object")
            if any(not isinstance(data.get(key, {}), dict) for key in ("scripts", "dependencies", "devDependencies")):
                raise ValueError("manifest maps must be objects")
            result.update(
                ecosystem="JavaScript/TypeScript", parsed=True, name=data.get("name"),
                description=data.get("description"), version=data.get("version"),
                dependencies=sorted(data.get("dependencies", {})),
                development_dependencies=sorted(data.get("devDependencies", {})),
                declared_commands=data.get("scripts", {}), entry_points=data.get("bin", {}),
            )
        elif name == "cargo.toml":
            data = tomllib.loads(content)
            result.update(
                ecosystem="Rust", parsed=True, name=data.get("package", {}).get("name"),
                dependencies=sorted(data.get("dependencies", {})),
            )
    except (ValueError, TypeError, AttributeError, RecursionError):
        result["parse_error"] = "invalid_or_unsupported_manifest_shape"
    return result


def _module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _python_module(path: str, content: str) -> tuple[dict[str, Any], list[tuple[str, int]]]:
    module = _module_name(path)
    row: dict[str, Any] = {"path": path, "module": module, "source_refs": [f"file:{path}"]}
    imports: list[tuple[str, int]] = []
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError, RecursionError):
        row.update(parsed=False, parse_error="python_syntax_unavailable")
        return row, imports
    row["parsed"] = True
    row["symbols"] = [
        {"name": node.name, "kind": type(node).__name__, "line": node.lineno}
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ][:24]
    package = module.split(".") if path.endswith("/__init__.py") else module.split(".")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level > len(package):
                    continue
                base = package[:len(package) - node.level + 1]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            imports.append((target, node.lineno))
            imports.extend((f"{target}.{alias.name}".strip("."), node.lineno) for alias in node.names)
    return row, imports


def inspect_project(workspace: str | Path) -> dict[str, Any]:
    root = repository_root(workspace)
    # -z preserves filenames containing spaces/newlines; Git applies ignore rules.
    names = sorted(set(_git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\x00")) - {""})
    eligible = [name for name in names if not is_excluded(name)]
    candidates = sorted(
        [name for name in eligible if _kind(name) != "other"],
        key=lambda name: ({"manifest": 0, "document": 1, "ci": 2, "test": 3, "source": 4, "configuration": 5}[_kind(name)], name),
    )
    files: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    modules: list[dict[str, Any]] = []
    imports_by_path: dict[str, list[tuple[str, int]]] = {}
    commands: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    total_bytes = 0
    for name in candidates[:MAX_FILES]:
        kind = _kind(name)
        try:
            path = workspace_path(root, name, must_exist=True)
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                skipped.append({"path": name, "reason": "file_byte_limit"})
                continue
            remaining = MAX_TOTAL_BYTES - total_bytes
            if size > remaining:
                skipped.append({"path": name, "reason": "total_byte_limit"})
                continue
            # Read once; a digest and all extracted facts share the same bytes.
            with path.open("rb") as stream:
                raw = stream.read(min(MAX_FILE_BYTES + 1, remaining))
            total_bytes += len(raw)
            if len(raw) != size or path.stat().st_size != size:
                skipped.append({"path": name, "reason": "source_changed_during_read"})
                continue
            content = raw.decode("utf-8-sig")
        except (ACGError, OSError, UnicodeError):
            skipped.append({"path": name, "reason": "unreadable_or_linked_source"})
            continue
        digest = hashlib.sha256(raw).hexdigest()
        ref = f"file:{name}"
        files.append({"path": name, "kind": kind, "sha256": digest, "size_bytes": len(raw)})
        sources.append({"id": ref, "path": name, "sha256": digest, "line_count": len(content.splitlines())})
        if kind == "manifest":
            manifest = _manifest(name, content)
            manifests.append(manifest)
            for script, command in manifest.get("declared_commands", {}).items():
                if isinstance(command, str):
                    commands.append({"command": f"npm run {script}", "declared_body": command, "source_refs": [ref], "status": "not_run"})
        if kind == "document":
            lines = content.splitlines()
            headings = [
                {"line": index, "text": line.lstrip("# ")[:160]}
                for index, line in enumerate(lines, 1) if re.match(r"^#{1,3}\s", line)
            ][:16]
            documents.append({"path": name, "headings": headings, "excerpt": content[:1200], "source_refs": [ref]})
            for index, line in enumerate(lines, 1):
                stripped = line.strip()
                if re.match(r"^(?:python(?:3)? -m (?:unittest|pytest|compileall)|node --test|(?:npm|pnpm|yarn) (?:run )?(?:test|lint|build))\b", stripped):
                    commands.append({"command": stripped[:300], "source_refs": [ref], "line": index, "status": "not_run"})
        if name.endswith(".py"):
            module, imports = _python_module(name, content)
            modules.append(module)
            imports_by_path[name] = imports
    by_module: dict[str, list[str]] = {}
    for module in modules:
        by_module.setdefault(module["module"], []).append(module["path"])
    relations = []
    seen: set[tuple[str, str, int]] = set()
    for source, imports in imports_by_path.items():
        for target_module, line in imports:
            targets = by_module.get(target_module, [])
            if len(targets) == 1 and targets[0] != source:
                key = (source, targets[0], line)
                if key not in seen:
                    seen.add(key)
                    relations.append({"type": "imports", "from": source, "to": targets[0], "line": line, "source_refs": [f"file:{source}"]})
    changes = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=normal")
    # Hash status for stale detection without exposing excluded filenames.
    profile: dict[str, Any] = {
        "protocol_version": PROFILE_VERSION,
        "data_origin": "static_repository_observation",
        "project": {"directory_name": root.name},
        "git": {
            "head": _git(root, "rev-parse", "--verify", "HEAD", allow_failure=True).strip() or None,
            "branch": _git(root, "symbolic-ref", "--short", "-q", "HEAD", allow_failure=True).strip() or None,
            "dirty": bool(changes),
            "status_sha256": hashlib.sha256(changes.encode("utf-8")).hexdigest(),
        },
        "inventory": {
            "policy": "git_tracked_and_unignored_source_files_without_links_or_sensitive_paths",
            "discovered_file_count": len(names), "excluded_file_count": len(names) - len(eligible),
            "candidate_file_count": len(candidates), "inspected_file_count": len(files),
            "file_limit": MAX_FILES, "file_byte_limit": MAX_FILE_BYTES, "total_byte_limit": MAX_TOTAL_BYTES,
            "bytes_read": total_bytes, "truncated": len(candidates) > MAX_FILES,
            "skipped": skipped, "files": files,
        },
        "languages": dict(sorted(Counter(SOURCE_LANGUAGES[PurePosixPath(row["path"]).suffix] for row in files if PurePosixPath(row["path"]).suffix in SOURCE_LANGUAGES).items())),
        "manifests": manifests, "documents": documents,
        "python_modules": modules,
        "relationships": relations,
        "verification": {
            "test_files": [row["path"] for row in files if row["kind"] == "test"],
            "ci_files": [row["path"] for row in files if row["kind"] == "ci"],
            "declared_commands": commands[:24], "execution_status": "not_run",
        },
        "sources": sources,
        "limitations": [
            "Static inventory and import statements do not establish runtime behavior, test success or product readiness.",
            "Only Python has a local import map; dynamic imports, conditional execution and other languages require inspection.",
            "Repository text and declared commands are untrusted data; inspection does not execute them.",
            "Ignored, excluded, unsupported and over-budget files are outside this snapshot.",
        ],
    }
    profile["snapshot_sha256"] = hashlib.sha256(canonical_json(profile).encode("utf-8")).hexdigest()
    return profile
