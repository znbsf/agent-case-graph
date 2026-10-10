"""Evidence-preserving workbench projection, independent of runtime state.

Grouping is a display partition. Every summary edge carries exact canonical
edge witnesses; order, repeated membership and proximity never create edges.
"""
from __future__ import annotations

from collections import defaultdict
import html
from importlib.resources import files
import json
import re
from typing import Any

PROTOCOL_VERSION = "evidence-workbench-0.1"
STRUCTURAL = {"contains", "has_run", "instance_of"}
OWN_FIELDS = ("goal_ids", "plan_ids", "action_ids", "result_ids", "conclusion_ids",
              "decision_ids", "uncertainty_ids")
PAPERS = [
    {"id": "got", "title": "Graph of Trace", "publication": "ACL 2026 System Demonstrations",
     "url": "https://aclanthology.org/2026.acl-demo.29/", "sections": "§3.4–3.5, §4, §5, §8",
     "basis": "声明依赖、源记录与节点详情联动；大图折叠与渐进展开被列为未解决限制。",
     "limit": "5 位专家、7 个案例的研究；不是本工作台的可用性验证，也未验证我们的分组算法。"},
    {"id": "ledger", "title": "LEDGER", "publication": "arXiv v1, 2026-08-19 · 预印本 / preprint",
     "url": "https://arxiv.org/html/2608.18398v1", "sections": "§3.1–3.3, §4, §6",
     "basis": "Trace Records / Evidence / Workflow 分层；从结论沿类型化关系回到动作、产物和检查。",
     "limit": "高层结构是解释，不等于原始记录；案例研究不能证明自动分组或结论正确。"},
    {"id": "eyes", "title": "The Eyes Have It", "publication": "IEEE Visual Languages, 1996",
     "url": "https://hci.stanford.edu/courses/cs448b/papers/shneiderman96eyes.pdf", "sections": "§2, §3",
     "basis": "先总览，再缩放、筛选和按需详情；支持关系查看与导航历史。",
     "limit": "交互设计分类与原则，不是该具体界面的对照实验。"},
    {"id": "gansner", "title": "A Technique for Drawing Directed Graphs", "publication": "IEEE TSE, 1993",
     "url": "https://graphviz.org/documentation/TSE93.pdf", "sections": "§1.1, §1.4, §2.1",
     "basis": "分离分层、节点排序、坐标与布线；保持箭头原方向，减少交叉和长边。",
     "limit": "本实现使用简化的稳定分层和避让布线，并非完整 dot / network-simplex 算法。"},
]


def relation_class(edge: dict[str, Any]) -> str:
    if edge["type"] in STRUCTURAL:
        return "structure"
    if edge["type"] == "precedes":
        return "order"
    if edge["type"] in {"supports", "refutes", "checks", "verified_by", "tested_by", "references", "uses", "derived_from", "explains"}:
        return "evidence"
    return "recorded"


def build_workbench_model(reader: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    nodes = {node["id"]: node for node in reader["nodes"]}
    used_ids = set(nodes) | {edge["id"] for edge in reader["edges"]}

    def display_id(key: str) -> str:
        candidate = "display:" + key
        while candidate in used_ids:
            candidate = "display:" + candidate
        used_ids.add(candidate)
        return candidate

    group_ids = {stage["id"]: display_id("scope:" + stage["id"]) for stage in reader["stages"]}
    shared_id, unscoped_id = display_id("shared"), display_id("unscoped")
    candidates: dict[str, set[str]] = defaultdict(set)
    scopes = []
    for stage in reader["stages"]:
        own = {key for field in OWN_FIELDS for key in stage[field]} & nodes.keys()
        for key in own:
            candidates[key].add(stage["id"])
        scopes.append({**stage, "own_ids": sorted(own), "group_id": group_ids[stage["id"]]})
    # A shared Plan/Goal is not arbitrarily attributed to one execution.
    owners = {key: group_ids[next(iter(candidates[key]))] if len(candidates[key]) == 1
              else shared_id if candidates[key] else unscoped_id for key in nodes}
    groups = [{"id": scope["group_id"], "scope_id": scope["id"], "label": scope["title"],
               "kind": "stage", "explicit": scope["explicit_iteration"],
               "member_ids": [], "internal_edge_ids": [],
               "result_ids": scope["result_ids"], "conclusion_ids": scope["conclusion_ids"]}
              for scope in scopes]
    for key, kind, label in ((shared_id, "shared", "共享节点"), (unscoped_id, "unscoped", "未归入阶段的记录")):
        if key in owners.values():
            groups.append({"id": key, "scope_id": None, "label": label, "kind": kind,
                           "explicit": False, "member_ids": [], "internal_edge_ids": [],
                           "result_ids": [], "conclusion_ids": []})
    by_id = {group["id"]: group for group in groups}
    for key, owner in owners.items():
        by_id[owner]["member_ids"].append(key)
    aggregate: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for edge in reader["edges"]:
        source, target = owners[edge["from"]], owners[edge["to"]]
        if source == target:
            by_id[source]["internal_edge_ids"].append(edge["id"])
        else:
            aggregate[source, target, edge["type"]].append(edge["id"])
    used_ids.update(edge["id"] for edge in reader["edges"])
    group_edges = [{"id": display_id(f"summary:{index}"), "from": source, "to": target, "type": kind,
                    "relation_class": relation_class({"type": kind}),
                    "source_edge_ids": sorted(witnesses), "derived": True}
                   for index, ((source, target, kind), witnesses) in enumerate(sorted(aggregate.items()))]
    return {"protocol_version": PROTOCOL_VERSION, "nodes": reader["nodes"], "edges": reader["edges"],
            "groups": groups, "group_edges": group_edges, "node_owner": owners, "scopes": scopes,
            "trace": trace.get("trace", []), "sequence": trace.get("sequence", {}),
            "coverage": reader["coverage"], "capture_modes": reader["capture_modes"],
            "source_ledger": reader["source_ledger"], "boundary": reader["boundary"],
            "papers": PAPERS, "principles": {"grouping_is_display_only": True,
                "summary_edges_have_canonical_witnesses": True, "node_partition_is_lossless": True,
                "position_is_causality": False, "recorded_relation_is_verified_cause": False,
                "status_is_new_verification": False, "papers_validate_this_ui": False}}


def render_workbench_html(model: dict[str, Any], *, title: str,
                          display_locales: dict[str, dict[str, Any]] | None = None,
                          default_locale: str = "zh-CN") -> str:
    resources = files("agent_case_graph").joinpath("web")
    payload = json.dumps({"model": model, "title": title, "locales": display_locales or {},
                          "default_locale": default_locale}, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    replacements = {"TITLE": html.escape(title), "DATA": payload,
                    "STYLE": resources.joinpath("workbench.css").read_text(encoding="utf-8"),
                    "LAYOUT": resources.joinpath("workbench-layout.js").read_text(encoding="utf-8"),
                    "SCRIPT": resources.joinpath("workbench.js").read_text(encoding="utf-8")}
    return re.sub(r"__(TITLE|DATA|STYLE|LAYOUT|SCRIPT)__", lambda match: replacements[match[1]],
                  resources.joinpath("workbench.html").read_text(encoding="utf-8"))
