from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import ACGError


def _string_map(value: Any, *, field: str, source: Path) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ACGError(f"{source}: {field} must be an object")
    result: dict[str, str] = {}
    for key, text in value.items():
        if not isinstance(key, str) or not isinstance(text, str) or not text.strip():
            raise ACGError(f"{source}: {field} entries must be non-empty strings")
        result[key] = text
    return result


def load_display_locales(ledger_path: str | Path) -> dict[str, dict[str, Any]]:
    """Load optional display-only translations next to a ledger.

    Files live under ``<ledger parent>/locales/*.json``. They never alter the
    ledger, graph projection, canonical IDs, or authored source labels.
    """

    ledger = Path(ledger_path)
    locale_dir = ledger.parent / "locales"
    if not locale_dir.is_dir():
        return {}

    bundles: dict[str, dict[str, Any]] = {}
    for source in sorted(locale_dir.glob("*.json")):
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ACGError(f"cannot load display locale {source}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ACGError(f"{source}: locale document must be an object")
        locale = raw.get("locale", source.stem)
        if not isinstance(locale, str) or not locale.strip():
            raise ACGError(f"{source}: locale must be a non-empty string")
        title = raw.get("title")
        if title is not None and (not isinstance(title, str) or not title.strip()):
            raise ACGError(f"{source}: title must be a non-empty string")
        bundles[locale] = {
            "locale": locale,
            "title": title,
            "nodes": _string_map(raw.get("nodes"), field="nodes", source=source),
        }
    return bundles
