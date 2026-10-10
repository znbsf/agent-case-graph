"""Graph-first, read-only presentation over source-bound reader scopes.

Optional editorial cards are explicit, ledger-hash-bound display annotations.
Their tones never change canonical verdicts. Layout connections are not causal.
"""
from __future__ import annotations

import copy
import html
import json
import re
from importlib.resources import files
from typing import Any

from .model import ACGError

TONES = {"recorded", "gain", "open", "negative", "hypothesis", "paused"}


def build_story_model(reader: dict[str, Any], presentation: dict[str, Any] | None = None) -> dict[str, Any]:
    stages = {stage["id"]: stage for stage in reader["stages"]}
    nodes = {node["id"]: node for node in reader["nodes"]}
    if presentation is None:
        cards = [{"id": stage["id"], "stage_ids": [stage["id"]], "node_ids": [],
                  "parent_id": None, "title": stage["title"], "results": [],
                  "summary": "", "boundary": ""} for stage in stages.values()]
        return {"protocol_version": "case-story-0.1", "authored": False,
                "title": "", "cards": cards, "reader": reader}

    def require(ok, message):
        if not ok:
            raise ACGError("graph presentation: " + message)

    require(isinstance(presentation, dict), "expected an object")
    require(presentation.get("version") == "case-story-0.1", "unsupported version")
    digest = (reader.get("source_ledger") or {}).get("sha256")
    require(bool(digest) and presentation.get("source_sha256") == digest, "source ledger SHA256 mismatch")
    cards = copy.deepcopy(presentation.get("cards"))
    require(isinstance(cards, list) and bool(cards), "cards must be a non-empty list")
    seen = set()
    covered = []
    for card in cards:
        require(isinstance(card, dict), "card must be an object")
        key = card.get("id")
        require(isinstance(key, str) and bool(key) and key not in seen, "unique card id required")
        seen.add(key)
        for field in ("stage_ids", "node_ids"):
            values = card.get(field, [])
            require(isinstance(values, list) and all(isinstance(value, str) for value in values), field + " must contain ids")
            require(len(set(values)) == len(values), "duplicate " + field)
            card[field] = values
        require(bool(card["stage_ids"] or card["node_ids"]), "card must reference source stages or nodes")
        require(set(card["stage_ids"]) <= stages.keys(), "unknown stage id")
        require(set(card["node_ids"]) <= nodes.keys(), "unknown node id")
        covered.extend(card["stage_ids"])
        scope = set(card["node_ids"])
        for stage_id in card["stage_ids"]:
            scope.update(stages[stage_id]["related_node_ids"])
        for field in ("title", "summary", "boundary"):
            value = card.get(field, "")
            require(isinstance(value, str), field + " must be text")
            require(len(value) <= (160 if field == "title" else 320), field + " is too long for a graph card")
            card[field] = value
        require(bool(card["title"].strip()), "card title required")
        parent = card.get("parent_id")
        require(parent is None or isinstance(parent, str), "invalid parent id")
        card["parent_id"] = parent
        results = card.get("results", [])
        require(isinstance(results, list) and len(results) <= 3, "at most three result annotations per card")
        for result in results:
            require(isinstance(result, dict), "result must be an object")
            require(isinstance(result.get("tone"), str) and result["tone"] in TONES, "unknown display tone")
            require(isinstance(result.get("text"), str) and 0 < len(result["text"]) <= 160, "result text required (max 160 characters)")
            refs = result.get("source_ids")
            require(isinstance(refs, list) and bool(refs) and all(isinstance(ref, str) for ref in refs), "result requires source_ids")
            require(set(refs) <= scope, "result source outside card scope")
        card["results"] = results
    require(len(covered) == len(set(covered)) and set(covered) == stages.keys(), "every stage must appear exactly once")
    main = {card["id"] for card in cards if card["parent_id"] is None}
    require(bool(main), "at least one main card required")
    for card in cards:
        require(card["parent_id"] is None or card["parent_id"] in main, "branch parent must be a main card")
    title = presentation.get("title", "")
    require(isinstance(title, str) and len(title) <= 160, "invalid title")
    return {"protocol_version": "case-story-0.1", "authored": True,
            "title": title, "cards": cards, "reader": reader,
            "source_sha256": digest,
            "principles": {"layout_is_editorial": True, "layout_is_causality": False,
                           "tones_are_verdicts": False, "source_records_modified": False}}


def render_story_html(model: dict[str, Any], *, title: str,
                      display_locales: dict[str, dict[str, Any]] | None = None,
                      default_locale: str = "zh-CN") -> str:
    resources = files("agent_case_graph").joinpath("web")
    payload = json.dumps({"model": model, "title": title, "locales": display_locales or {},
                          "default_locale": default_locale}, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    replacements = {"TITLE": html.escape(title), "DATA": payload,
                    "STYLE": resources.joinpath("story.css").read_text(encoding="utf-8"),
                    "SCRIPT": resources.joinpath("story.js").read_text(encoding="utf-8")}
    return re.sub(r"__(TITLE|DATA|STYLE|SCRIPT)__", lambda match: replacements[match[1]],
                  resources.joinpath("story.html").read_text(encoding="utf-8"))
