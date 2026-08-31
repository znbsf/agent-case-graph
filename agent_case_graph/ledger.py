from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .model import ACGError, SCHEMA_VERSION, load_events, validate_event


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
) -> dict[str, Any]:
    ledger_path = Path(path)
    if not ledger_path.is_file():
        raise ACGError(f"ledger does not exist: {ledger_path}")

    with _ledger_lock(ledger_path):
        events = load_events(ledger_path)
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
        event.update(payload)
        validate_event(event)
        with ledger_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json(event) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    return event
