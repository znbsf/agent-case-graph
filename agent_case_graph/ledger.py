from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from .model import ACGError, SCHEMA_VERSION, load_events, parse_events, validate_event


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_ledger_snapshot(path: str | Path) -> tuple[list[dict[str, Any]], str]:
    """Return events and the SHA256 of the exact bytes that produced them."""
    source = Path(path)
    if not source.is_file():
        raise ACGError(f"ledger does not exist: {source}")
    data = source.read_bytes()
    return parse_events(data.decode("utf-8-sig")), hashlib.sha256(data).hexdigest()


def atomic_write_text(path: str | Path, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()


def write_new_ledger(
    path: str | Path,
    events: list[dict[str, Any]],
    *,
    force: bool = False,
) -> None:
    target = Path(path)
    if target.exists() and not force:
        raise ACGError(f"refusing to overwrite existing ledger: {target}")
    for index, event in enumerate(events, start=1):
        if event.get("sequence") != index:
            raise ACGError(f"event {index} has non-contiguous sequence {event.get('sequence')}")
        validate_event(event)
    content = "".join(canonical_json(event) + "\n" for event in events)
    atomic_write_text(target, content)


@contextmanager
def _ledger_lock(path: Path, timeout_seconds: float = 5.0) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + timeout_seconds
    fd: int | None = None
    while fd is None:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ACGError(f"ledger is locked: {lock_path}")
            time.sleep(0.05)
    try:
        os.write(fd, f"pid={os.getpid()}\n".encode("ascii"))
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def append_event(
    path: str | Path,
    *,
    case_id: str,
    kind: str,
    actor_type: str,
    actor_id: str,
    capture_mode: str,
    source_refs: list[str],
    payload: dict[str, Any],
    run_id: str | None = None,
    occurred_at: str | None = None,
    expected_sequence: int | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    ledger_path = Path(path)
    if not ledger_path.is_file():
        raise ACGError(f"ledger does not exist: {ledger_path}")

    with _ledger_lock(ledger_path):
        events, digest = read_ledger_snapshot(ledger_path)
        if (
            (expected_sequence is not None and len(events) != expected_sequence)
            or (expected_sha256 is not None and digest != expected_sha256)
        ):
            raise ACGError("ledger changed after validation; reload and retry the command")
        if events[0]["case_id"] != case_id:
            raise ACGError(
                f"case_id mismatch: ledger has {events[0]['case_id']!r}, got {case_id!r}"
            )
        event: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "event_id": f"evt-{uuid.uuid4().hex}",
            "case_id": case_id,
            "run_id": run_id,
            "sequence": len(events) + 1,
            "occurred_at": occurred_at or datetime.now().astimezone().isoformat(timespec="seconds"),
            "kind": kind,
            "actor": {"type": actor_type, "id": actor_id},
            "provenance": {
                "capture_mode": capture_mode,
                "source_refs": source_refs,
            },
        }
        payload_key = {
            "graph.declared": "graph", "node.recorded": "node",
            "edge.recorded": "edge", "state.changed": "transition",
        }.get(kind)
        if set(payload) != {payload_key}:
            raise ACGError(f"payload for {kind} must contain only {payload_key!r}")
        event.update(payload)
        validate_event(event)
        with ledger_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json(event) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    return event


def append_events(
    path: str | Path, *, case_id: str, records: list[dict[str, Any]],
    actor_type: str, actor_id: str, capture_mode: str, source_refs: list[str],
    run_id: str | None, expected_sequence: int, expected_sha256: str,
    validate_combined: Callable[[list[dict[str, Any]]], None] | None = None,
    maximum_bytes: int | None = None,
) -> list[dict[str, Any]]:
    """Commit a validated batch atomically, preserving the original byte prefix.

    A plan and its relationships must never be partly appended. Both freshness
    comparisons and optional graph validation run under the existing lock.
    """
    if not records:
        raise ACGError("an event batch must contain at least one record")
    target = Path(path)
    if not target.is_file():
        raise ACGError(f"ledger does not exist: {target}")
    with _ledger_lock(target):
        data = target.read_bytes()
        events = parse_events(data.decode("utf-8-sig"))
        if len(events) != expected_sequence or hashlib.sha256(data).hexdigest() != expected_sha256:
            raise ACGError("ledger changed after validation; reload and retry the command")
        if events[0]["case_id"] != case_id:
            raise ACGError("case_id mismatch for event batch")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        batch = []
        for offset, record in enumerate(records, start=1):
            kind = record.get("kind")
            key = {"node.recorded": "node", "edge.recorded": "edge", "state.changed": "transition"}.get(kind)
            if key is None or set(record) != {"kind", key}:
                raise ACGError("batch records must contain one supported kind and its payload")
            event = {
                "schema_version": SCHEMA_VERSION, "event_id": f"evt-{uuid.uuid4().hex}",
                "case_id": case_id, "run_id": run_id, "sequence": len(events) + offset,
                "occurred_at": now, "kind": kind, "actor": {"type": actor_type, "id": actor_id},
                "provenance": {"capture_mode": capture_mode, "source_refs": source_refs},
                key: record[key],
            }
            validate_event(event)
            batch.append(event)
        if validate_combined:
            validate_combined(events + batch)
        prefix = data.decode("utf-8")
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        content = prefix + "".join(canonical_json(event) + "\n" for event in batch)
        if maximum_bytes is not None and len(content.encode("utf-8")) > maximum_bytes:
            raise ACGError("event batch would exceed the ledger byte limit")
        atomic_write_text(target, content)
    return batch
