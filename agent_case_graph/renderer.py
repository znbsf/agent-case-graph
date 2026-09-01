from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .ledger import atomic_write_text, canonical_json, sha256_file
from .model import SCHEMA_VERSION


def _mermaid_text(value: str) -> str:
    return html.escape(value.replace('"', "'"), quote=False).replace("\n", " ")


def render_mermaid(graph: dict[str, Any]) -> str:
    node_aliases = {node["id"]: f"n{index}" for index, node in enumerate(graph["nodes"])}
    lines = ["flowchart LR"]
    for node in graph["nodes"]:
        alias = node_aliases[node["id"]]
        label = _mermaid_text(node["label"][:100])
        lines.append(f'    {alias}["{node["type"]}<br/>{label}"]')
    for edge in graph["edges"]:
        source = node_aliases.get(edge["from"])
        target = node_aliases.get(edge["to"])
        if source and target:
            lines.append(f'    {source} -->|"{_mermaid_text(edge["type"])}"| {target}')
    return "\n".join(lines) + "\n"


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:">
<title>__TITLE__</title>
<script>
(function () {
  try {
    var savedTheme = localStorage.getItem("acg-theme");
    if (savedTheme === "dark" || savedTheme === "light") {
      document.documentElement.dataset.theme = savedTheme;
    } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
      document.documentElement.dataset.theme = "dark";
    }
  } catch (_) {}
}());
</script>
<style>
:root {
  color-scheme: light;
  --page: #f4f7fb;
  --surface: #ffffff;
  --surface-raised: #ffffff;
  --surface-soft: #f8fafc;
  --surface-tint: #f1f6fb;
  --canvas: #f8fafc;
  --text: #132033;
  --muted: #66758a;
  --faint: #8d9aab;
  --border: #dfe6ef;
  --border-strong: #c8d4e2;
  --grid: #dce5ef;
  --shadow: 0 18px 50px rgba(42, 60, 82, .10);
  --accent: #1689b0;
  --accent-soft: #e4f5fa;
  --good: #138a63;
  --warn: #c57a00;
  --bad: #d1495b;
  --scope: #1b91b8;
  --execute: #2aa876;
  --evidence: #d99a22;
  --reason: #815ac0;
  --verify: #1d9a72;
  --knowledge: #cc5aa6;
  --edge: #8092a8;
  --edge-soft: #b4c0ce;
  --overlay: rgba(20, 31, 47, .28);
}
html[data-theme="dark"] {
  color-scheme: dark;
  --page: #08111f;
  --surface: #0f1b2d;
  --surface-raised: #142239;
  --surface-soft: #0c1728;
  --surface-tint: #13233a;
  --canvas: #0c1728;
  --text: #edf4ff;
  --muted: #9fb0c6;
  --faint: #71849d;
  --border: #273b57;
  --border-strong: #39516f;
  --grid: #243651;
  --shadow: 0 22px 60px rgba(0, 0, 0, .32);
  --accent: #5fc5e8;
  --accent-soft: #12334a;
  --good: #55d6a2;
  --warn: #ffc857;
  --bad: #ff7888;
  --scope: #55c4eb;
  --execute: #50d5a7;
  --evidence: #efbd58;
  --reason: #b695f5;
  --verify: #5cdda7;
  --knowledge: #ee8ed0;
  --edge: #5d7695;
  --edge-soft: #3a4e69;
  --overlay: rgba(1, 7, 15, .64);
}
* { box-sizing: border-box; }
html { min-width: 320px; }
body {
  margin: 0;
  min-height: 100vh;
  overflow-x: hidden;
  background:
    radial-gradient(circle at 12% -10%, color-mix(in srgb, var(--accent) 9%, transparent), transparent 32rem),
    var(--page);
  color: var(--text);
  font-family: Inter, "Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif;
}
button, input, select { font: inherit; }
button, select { cursor: pointer; }
button:focus-visible, input:focus-visible, select:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--accent) 34%, transparent);
  outline-offset: 2px;
}
.page {
  width: min(1560px, 100%);
  margin: 0 auto;
  padding: 18px 22px 30px;
}
.topbar {
  min-height: 62px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 14px;
}
.brand { display: flex; align-items: flex-start; gap: 12px; min-width: 0; }
.brand-dot {
  flex: 0 0 auto;
  width: 10px;
  height: 10px;
  margin-top: 9px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 0 7px color-mix(in srgb, var(--accent) 12%, transparent);
}
h1 {
  margin: 0;
  max-width: 920px;
  font-size: clamp(20px, 2vw, 28px);
  line-height: 1.18;
  letter-spacing: -.02em;
}
.summary {
  min-height: 24px;
  margin-top: 7px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
  color: var(--muted);
  font-size: 12px;
}
.summary-chip, .finding-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface-soft);
  padding: 3px 8px;
  white-space: nowrap;
}
.summary-chip.state { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 28%, var(--border)); }
.summary-chip.good { color: var(--good); }
.header-actions { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.compact-select, .icon-button, .tool-button {
  min-height: 38px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  color: var(--text);
  box-shadow: 0 5px 16px rgba(35, 52, 73, .05);
}
.compact-select { padding: 0 32px 0 11px; }
.icon-button, .tool-button { padding: 0 12px; }
.diagram-card {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 18px;
  background: var(--surface);
  box-shadow: var(--shadow);
}
.case-context {
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--surface) 97%, var(--accent) 3%);
}
.case-context-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.case-context-badge, .case-context-link {
  min-height: 26px;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 8px;
  color: var(--muted);
  background: var(--surface);
  font-size: 9px;
  line-height: 1.25;
}
.case-context-link { cursor: pointer; text-align: left; }
.case-context-link:hover, .case-context-link:focus-visible { border-color: var(--accent); color: var(--accent); }
.case-context-badge.synthetic { color: var(--evidence); border-color: color-mix(in srgb, var(--evidence) 42%, var(--border)); }
.case-context-badge.boundary { color: var(--bad); border-color: color-mix(in srgb, var(--bad) 38%, var(--border)); }
.workspace-panel { background: var(--surface-soft); }
.workspace-intro {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--border);
  padding: 12px 15px;
  background: var(--surface);
}
.workspace-intro h2 { margin: 0 0 3px; font-size: 15px; }
.workspace-intro p { margin: 0; max-width: 980px; color: var(--muted); font-size: 10px; line-height: 1.45; }
.workspace-kicker { flex: 0 0 auto; border-radius: 999px; padding: 4px 8px; color: var(--accent); background: var(--accent-soft); font-size: 9px; font-weight: 760; }
.workspace-content { padding: 14px; }
.relation-legend { display: flex; flex-wrap: wrap; gap: 7px 14px; margin-bottom: 12px; color: var(--muted); font-size: 9px; }
.relation-legend-item { display: inline-flex; align-items: center; gap: 7px; }
.relation-swatch { width: 34px; height: 0; border-top: 2px solid var(--edge); }
.relation-swatch.temporal { border-color: var(--execute); }
.relation-swatch.evidence { border-color: var(--reason); border-top-style: dashed; }
.relation-swatch.execution { height: 2px; border: 0; background: repeating-linear-gradient(90deg, var(--evidence) 0 11px, transparent 11px 15px, var(--evidence) 15px 17px, transparent 17px 21px); }
.relation-swatch.mapping { border-color: var(--edge); border-top-style: dotted; }
.semantic-stack-viewport { overflow-x: auto; overscroll-behavior-inline: contain; }
.semantic-stack {
  position: relative;
  min-width: 1080px;
  display: grid;
  gap: 14px;
  padding: 2px;
}
.overview-relations { position: absolute; inset: 0; z-index: 3; width: 100%; height: 100%; overflow: visible; pointer-events: none; }
.overview-relation { fill: none; stroke-width: 2.1; vector-effect: non-scaling-stroke; }
.overview-relation.temporal { stroke: var(--execute); }
.overview-relation.evidence { stroke: var(--reason); stroke-dasharray: 7 5; }
.overview-relation.execution { stroke: var(--evidence); stroke-dasharray: 11 4 2 4; }
.overview-relation.mapping { stroke: var(--edge); stroke-width: 1.4; stroke-dasharray: 2 6; }
.overview-relation-label { font-size: 8px; font-weight: 760; paint-order: stroke; stroke: var(--surface-soft); stroke-width: 4px; }
.semantic-layer {
  --layer-color: var(--accent);
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: 168px minmax(860px, 1fr);
  min-height: 142px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--layer-color) 32%, var(--border));
  border-radius: 15px;
  background: color-mix(in srgb, var(--layer-color) 4%, var(--surface));
}
.semantic-layer[data-semantic-layer="state"] { --layer-color: var(--reason); }
.semantic-layer[data-semantic-layer="control"] { --layer-color: var(--accent); }
.semantic-layer[data-semantic-layer="action"] { --layer-color: var(--execute); }
.semantic-layer-head { position: relative; z-index: 4; display: grid; align-content: center; gap: 7px; padding: 14px; border-right: 1px solid color-mix(in srgb, var(--layer-color) 24%, var(--border)); background: color-mix(in srgb, var(--layer-color) 8%, var(--surface-raised)); }
.semantic-layer-index { color: var(--layer-color); font: 760 10px/1 Consolas, monospace; letter-spacing: .08em; }
.semantic-layer-title { font-size: 15px; font-weight: 780; }
.semantic-layer-note { color: var(--muted); font-size: 9px; line-height: 1.4; }
.semantic-track { display: grid; grid-template-columns: repeat(5, minmax(150px, 1fr)); gap: 34px; align-items: center; padding: 22px 24px; }
.semantic-card {
  --card-color: var(--layer-color);
  position: relative;
  z-index: 4;
  min-width: 0;
  min-height: 74px;
  border: 1px solid color-mix(in srgb, var(--card-color) 42%, var(--border));
  border-left: 4px solid var(--card-color);
  border-radius: 10px;
  padding: 9px 10px;
  color: var(--text);
  background: color-mix(in srgb, var(--card-color) 7%, var(--surface-raised));
  box-shadow: 0 6px 16px rgba(21, 35, 54, .08);
  text-align: left;
}
button.semantic-card { cursor: pointer; }
button.semantic-card:hover, button.semantic-card:focus-visible { border-color: var(--card-color); box-shadow: 0 0 0 2px color-mix(in srgb, var(--card-color) 18%, transparent), 0 8px 20px rgba(21, 35, 54, .12); }
.semantic-card-kind { display: flex; justify-content: space-between; gap: 6px; color: var(--muted); font-size: 8px; font-weight: 760; }
.semantic-card-title { margin-top: 5px; font-size: 10px; font-weight: 690; line-height: 1.36; overflow-wrap: anywhere; }
.semantic-card-detail { margin-top: 5px; color: var(--muted); font-size: 8px; line-height: 1.35; overflow-wrap: anywhere; }
.semantic-card.runtime-instance { --card-color: var(--execute); border-style: dashed; }
.semantic-card.runtime-instance.blocked { --card-color: var(--warn); }
.semantic-card.runtime-instance.failed { --card-color: var(--bad); }
.telemetry-gap { grid-column: 2 / span 2; align-self: stretch; display: grid; place-items: center; min-height: 70px; border: 1px dashed var(--border-strong); border-radius: 10px; padding: 10px; color: var(--muted); background: color-mix(in srgb, var(--surface) 75%, transparent); font-size: 9px; line-height: 1.45; text-align: center; }
.workspace-boundary { display: flex; align-items: flex-start; gap: 8px; margin-bottom: 12px; border: 1px solid color-mix(in srgb, var(--warn) 38%, var(--border)); border-radius: 11px; padding: 9px 11px; color: var(--muted); background: color-mix(in srgb, var(--warn) 6%, var(--surface)); font-size: 9px; line-height: 1.45; }
.workspace-boundary strong { color: var(--warn); white-space: nowrap; }
.run-lanes { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
.run-lane { min-height: 170px; border: 1px solid var(--border); border-radius: 12px; padding: 10px; background: var(--surface); }
.run-lane-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 9px; color: var(--muted); font-size: 9px; font-weight: 760; }
.run-lane-count { min-width: 20px; border-radius: 999px; padding: 2px 6px; color: var(--text); background: var(--surface-soft); text-align: center; }
.run-lane-list { display: grid; gap: 8px; }
.run-lane-empty { border: 1px dashed var(--border); border-radius: 9px; padding: 18px 8px; color: var(--faint); font-size: 9px; text-align: center; }
.run-empty-summary { grid-column: 1 / -1; color: var(--muted); font-size: 8px; line-height: 1.4; }
.track-list { display: grid; gap: 9px; }
.track-row { display: grid; grid-template-columns: 170px minmax(0, 1fr) auto; gap: 12px; align-items: center; border: 1px solid var(--border); border-radius: 11px; padding: 11px 12px; background: var(--surface); }
.track-name { font-size: 10px; font-weight: 760; }
.track-detail { color: var(--muted); font-size: 9px; line-height: 1.45; }
.track-status { border-radius: 999px; padding: 3px 7px; color: var(--muted); background: var(--surface-soft); font-size: 8px; font-weight: 760; }
.track-status.available { color: var(--good); }
.track-status.unavailable, .track-status.gated { color: var(--warn); }
.review-actionbar { display: flex; align-items: center; justify-content: flex-end; margin-bottom: 10px; }
.review-replay-button { min-height: 34px; border: 1px solid var(--accent); border-radius: 9px; padding: 6px 11px; color: var(--accent); background: var(--accent-soft); font-size: 9px; font-weight: 760; }
.review-replay-button:hover, .review-replay-button:focus-visible { color: var(--surface-raised); background: var(--accent); }
.evidence-chains { min-width: 0; display: grid; gap: 12px; }
.evidence-chain { min-width: 0; border: 1px solid var(--border); border-radius: 12px; padding: 12px; background: var(--surface); }
.evidence-chain-title { margin-bottom: 10px; color: var(--muted); font-size: 9px; font-weight: 760; }
.evidence-chain-track { width: 100%; min-width: 0; display: flex; align-items: stretch; gap: 10px; overflow-x: auto; overscroll-behavior-inline: contain; padding: 2px; }
.evidence-chain-track .semantic-card { flex: 0 0 190px; }
.chain-relation { flex: 0 0 82px; display: grid; place-content: center; gap: 5px; color: var(--muted); font-size: 8px; text-align: center; }
.chain-relation-line { width: 100%; height: 0; border-top: 2px dashed var(--reason); }
.chain-relation.execution .chain-relation-line { height: 2px; border: 0; background: repeating-linear-gradient(90deg, var(--evidence) 0 11px, transparent 11px 15px, var(--evidence) 15px 17px, transparent 17px 21px); }
.chain-relation::after { content: "→"; margin-top: -13px; color: currentColor; text-align: right; }
.diagram-toolbar {
  min-height: 58px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--surface) 94%, var(--accent) 6%);
}
.tabs { display: flex; align-items: center; gap: 3px; flex: 0 0 auto; }
.tab {
  min-height: 36px;
  border: 0;
  border-radius: 9px;
  padding: 0 12px;
  color: var(--muted);
  background: transparent;
}
.tab.active {
  color: var(--text);
  background: var(--surface-raised);
  box-shadow: inset 0 0 0 1px var(--border), 0 4px 12px rgba(40, 58, 80, .06);
}
.filters {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  justify-content: flex-end;
}
.search-wrap { position: relative; width: min(310px, 28vw); min-width: 190px; }
.search-wrap::before {
  content: "⌕";
  position: absolute;
  left: 11px;
  top: 7px;
  color: var(--faint);
  font-size: 18px;
  pointer-events: none;
}
.filter-control {
  height: 36px;
  min-width: 112px;
  max-width: 190px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface);
  color: var(--text);
  padding: 0 30px 0 10px;
}
#search {
  width: 100%;
  height: 36px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface);
  color: var(--text);
  padding: 0 10px 0 34px;
}
.view { display: none; }
.view.active { display: block; }
.spatial-panel { min-height: 520px; background: var(--surface-soft); }
.spatial-intro {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--border);
  padding: 11px 15px;
  background: var(--surface);
}
.spatial-intro h2 { margin: 0 0 3px; font-size: 15px; }
.spatial-intro p { margin: 0; color: var(--muted); font-size: 10px; line-height: 1.45; }
.spatial-protocol { flex: 0 0 auto; border-radius: 999px; padding: 4px 8px; color: var(--accent); background: var(--accent-soft); font-size: 9px; font-weight: 760; }
.plan-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  padding: 9px 12px 0;
}
.plan-summary-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 27px;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 4px 9px;
  color: var(--muted);
  background: var(--surface);
  font-size: 8.5px;
  font-weight: 700;
}
.plan-summary-chip strong { color: var(--text); font: 760 9px/1 Consolas, monospace; }
.plan-summary-chip.available { color: var(--good); border-color: color-mix(in srgb, var(--good) 34%, var(--border)); }
.plan-summary-chip.unavailable { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 34%, var(--border)); }
.plan-workbench {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 292px;
  gap: 10px;
  padding: 10px 12px 12px;
}
.plan-canvas-shell {
  min-width: 0;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 13px;
  background: var(--canvas);
}
.plan-inspector {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 13px;
  padding: 11px;
  background: var(--surface);
}
.plan-inspector-head { margin-bottom: 10px; }
.plan-inspector-title { font-size: 11px; font-weight: 780; }
.plan-inspector-note { margin-top: 4px; color: var(--muted); font-size: 8px; line-height: 1.4; }
.plan-inspector-section + .plan-inspector-section { margin-top: 11px; padding-top: 10px; border-top: 1px solid var(--border); }
.plan-inspector-kicker { margin-bottom: 7px; color: var(--muted); font-size: 8px; font-weight: 780; letter-spacing: .05em; text-transform: uppercase; }
.plan-frontier-item {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 7px 8px;
  color: var(--text);
  background: var(--surface-raised);
  text-align: left;
}
button.plan-frontier-item { cursor: pointer; }
button.plan-frontier-item:hover { border-color: var(--accent); }
.plan-frontier-top { display: flex; align-items: center; justify-content: space-between; gap: 7px; color: var(--muted); font-size: 7.5px; font-weight: 760; }
.plan-frontier-label { margin-top: 4px; font-size: 9px; font-weight: 690; line-height: 1.35; overflow-wrap: anywhere; }
.plan-frontier-detail { margin-top: 4px; color: var(--muted); font-size: 7.5px; line-height: 1.38; overflow-wrap: anywhere; }
.spatial-stage {
  position: relative;
  min-height: 460px;
  height: clamp(460px, 56vh, 620px);
  overflow: hidden;
  cursor: grab;
  background:
    radial-gradient(circle at 50% 42%, color-mix(in srgb, var(--accent) 7%, transparent), transparent 42%),
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px),
    var(--canvas);
  background-size: auto, 24px 24px, 24px 24px, auto;
  touch-action: none;
}
.spatial-stage.dragging { cursor: grabbing; }
.spatial-stage[data-view-mode="flow"] { cursor: default; touch-action: pan-x pan-y; }
.plan-canvas-shell .spatial-stage[data-view-mode="flow"] { min-height: 330px; height: clamp(330px, 36vh, 360px); }
.spatial-viewport { position: absolute; inset: 0; overflow: hidden; }
.spatial-stage[data-view-mode="flow"] .spatial-viewport { overflow: auto; overscroll-behavior: contain; }
.spatial-scene { position: relative; width: 100%; height: 100%; min-width: 100%; min-height: 100%; }
.spatial-svg, .spatial-node-layer { position: absolute; inset: 0; width: 100%; height: 100%; }
.spatial-svg { overflow: visible; }
.spatial-node-layer { pointer-events: none; }
.spatial-plane { stroke-width: 1.2; vector-effect: non-scaling-stroke; transition: opacity .18s ease; }
.spatial-plane.route-face { stroke-width: 1.6; stroke-dasharray: 7 5; }
.spatial-axis { fill: none; stroke-width: 2; vector-effect: non-scaling-stroke; }
.spatial-origin { fill: var(--surface-raised); stroke: var(--accent); stroke-width: 2.5; vector-effect: non-scaling-stroke; }
.spatial-axis-label { font-size: 10px; font-weight: 800; paint-order: stroke; stroke: var(--canvas); stroke-width: 3px; }
.spatial-edge { fill: none; stroke-width: 1.45; vector-effect: non-scaling-stroke; }
.spatial-edge.relation-temporal { stroke-width: 2.35; }
.spatial-edge.relation-evidence { stroke-dasharray: 7 5; }
.spatial-edge.relation-gate { stroke-width: 2; stroke-dasharray: 3 4; }
.spatial-edge.relation-execution { stroke-dasharray: 11 4 2 4; }
.spatial-edge.relation-reference { stroke-width: 1.1; stroke-dasharray: 2 6; opacity: .34; }
.spatial-edge.dim { opacity: .08 !important; }
.spatial-edge.selected { stroke-width: 3; opacity: 1 !important; }
.spatial-edge.replay-future, .spatial-edge.replay-unrelated { opacity: .06 !important; }
.spatial-edge.replay-past { opacity: .82 !important; }
.spatial-edge.replay-current { stroke-width: 3.4; opacity: 1 !important; }
.spatial-node-tether { fill: none; stroke-width: 1; stroke-dasharray: 2 4; opacity: .42; vector-effect: non-scaling-stroke; }
.spatial-node-anchor { stroke: var(--canvas); stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.spatial-node {
  --node-color: var(--accent);
  position: absolute;
  width: 132px;
  max-width: 18vw;
  min-height: 46px;
  transform: translate(-50%, -50%);
  border: 1px solid color-mix(in srgb, var(--node-color) 45%, var(--border));
  border-left: 4px solid var(--node-color);
  border-radius: 9px;
  padding: 6px 7px;
  color: var(--text);
  background: color-mix(in srgb, var(--node-color) 7%, var(--surface-raised));
  box-shadow: 0 5px 14px rgba(25, 38, 57, .10);
  text-align: left;
  pointer-events: auto;
  transition: opacity .16s ease, border-color .16s ease, box-shadow .16s ease;
}
.spatial-node:hover, .spatial-node.selected { border-color: var(--node-color); box-shadow: 0 0 0 2px color-mix(in srgb, var(--node-color) 22%, transparent), 0 7px 18px rgba(25, 38, 57, .15); }
.spatial-node.dim { opacity: .14; }
.spatial-node.replay-future, .spatial-node.replay-unrelated { opacity: .10; }
.spatial-node.replay-past { opacity: .72; }
.spatial-node.replay-current { border-color: var(--node-color); box-shadow: 0 0 0 4px color-mix(in srgb, var(--node-color) 28%, transparent), 0 9px 24px rgba(25, 38, 57, .20); }
.spatial-node.flow-node { width: 232px; max-width: 32vw; min-height: 82px; padding: 8px 9px; }
.spatial-node-top { display: flex; align-items: center; justify-content: space-between; gap: 4px; color: var(--muted); font-size: 7.5px; font-weight: 760; }
.spatial-node-title { display: -webkit-box; margin-top: 4px; overflow: hidden; font-size: 10px; font-weight: 700; line-height: 1.32; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.spatial-node-detail { margin-top: 5px; color: var(--muted); font-size: 7.5px; line-height: 1.3; overflow-wrap: anywhere; }
.spatial-node-action-output { margin-top: 3px; color: var(--text); font-size: 7.8px; font-weight: 680; line-height: 1.32; overflow-wrap: anywhere; }
.flow-node .spatial-node-title { font-size: 11px; }
.flow-node .spatial-node-detail, .flow-node .spatial-node-action-output { font-size: 8.5px; }
.spatial-node-status { width: 7px; height: 7px; border-radius: 999px; background: var(--node-color); box-shadow: 0 0 0 3px color-mix(in srgb, var(--node-color) 14%, transparent); }
.flow-rank-line { stroke: var(--edge-soft); stroke-width: 1; stroke-dasharray: 2 7; vector-effect: non-scaling-stroke; }
.flow-rank-label { fill: var(--muted); font-size: 8px; font-weight: 720; paint-order: stroke; stroke: var(--canvas); stroke-width: 3px; }
.flow-run-boundary { fill: none; stroke: var(--edge); stroke-width: 1.1; stroke-dasharray: 8 6; vector-effect: non-scaling-stroke; }
.flow-run-label { fill: var(--muted); font-size: 9px; font-weight: 760; paint-order: stroke; stroke: var(--canvas); stroke-width: 4px; }
.flow-dependency-band { fill: color-mix(in srgb, var(--execute) 5%, transparent); stroke: color-mix(in srgb, var(--execute) 30%, transparent); stroke-width: 1; vector-effect: non-scaling-stroke; }
.flow-dependency-label { fill: var(--muted); font-size: 9px; font-weight: 760; paint-order: stroke; stroke: var(--canvas); stroke-width: 4px; }
.flow-edge-label { fill: var(--execute); font-size: 8px; font-weight: 780; paint-order: stroke; stroke: var(--canvas); stroke-width: 4px; }
.flow-edge-legend { display: flex; align-items: center; gap: 7px; color: var(--muted); font-size: 8px; line-height: 1.35; }
.flow-edge-legend + .flow-edge-legend { margin-top: 5px; }
.flow-edge-sample { width: 31px; height: 0; border-top: 2px solid var(--edge); }
.flow-edge-sample.precedes { border-color: var(--execute); }
.flow-edge-sample.structure { border-top-style: dashed; opacity: .55; }
.spatial-empty { position: absolute; inset: 0; display: grid; place-items: center; color: var(--muted); font-size: 12px; pointer-events: none; }
.spatial-hud { position: absolute; z-index: 20; display: grid; gap: 8px; pointer-events: none; }
.spatial-hud > * { pointer-events: auto; }
.spatial-hud-left { top: 14px; left: 14px; max-width: 320px; }
.spatial-hud-right { top: 14px; right: 14px; }
.spatial-hud-bottom { right: 14px; bottom: 14px; grid-auto-flow: column; }
.spatial-card { border: 1px solid var(--border); border-radius: 11px; padding: 9px 10px; background: color-mix(in srgb, var(--surface-raised) 92%, transparent); box-shadow: 0 8px 22px rgba(25, 38, 57, .10); backdrop-filter: blur(8px); }
.spatial-loop { display: grid; grid-template-columns: auto 18px auto 18px auto; align-items: center; gap: 3px; font-size: 9px; font-weight: 720; }
.spatial-loop-arrow { color: var(--accent); font-size: 14px; text-align: center; }
.spatial-loop-sub { margin-top: 6px; color: var(--muted); font-size: 8px; line-height: 1.35; }
.spatial-layer-buttons, .spatial-camera-buttons { display: grid; gap: 5px; }
.spatial-layer-button, .spatial-camera-button, .toolbar-action {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 8px;
  color: var(--muted);
  background: var(--surface);
  font-size: 9px;
  font-weight: 680;
}
.spatial-layer-button.active, .spatial-layer-button:hover, .spatial-camera-button:hover, .toolbar-action:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.spatial-camera-buttons { grid-auto-flow: column; grid-template-columns: repeat(4, 32px); }
.spatial-camera-button { padding: 6px 0; font-size: 12px; }
.toolbar-action { min-height: 32px; white-space: nowrap; }
.spatial-layer-summary { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }
.spatial-layer-chip { border-radius: 999px; padding: 2px 6px; color: var(--muted); background: var(--surface); font-size: 8px; }
.replay-console {
  display: grid;
  gap: 10px;
  margin: 0 12px 14px;
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 12px;
  background: var(--surface);
  box-shadow: 0 8px 24px rgba(25, 38, 57, .07);
}
.replay-console-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.replay-title { font-size: 12px; font-weight: 800; }
.replay-subtitle { margin-top: 4px; color: var(--muted); font-size: 8.5px; line-height: 1.4; }
.replay-track-tabs { display: grid; grid-template-columns: repeat(4, minmax(126px, 1fr)); gap: 6px; }
.replay-track-tab {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 8px 9px;
  color: var(--muted);
  background: var(--surface-raised);
  text-align: left;
}
.replay-track-tab:hover { border-color: var(--accent); color: var(--text); }
.replay-track-tab.active { border-color: var(--accent); color: var(--text); background: var(--accent-soft); box-shadow: inset 3px 0 0 var(--accent); }
.replay-track-tab[data-track-availability="unavailable"] { border-style: dashed; color: var(--faint); }
.replay-track-name { display: block; font-size: 9px; font-weight: 780; }
.replay-track-state { display: block; margin-top: 3px; font-size: 7.5px; line-height: 1.3; }
.replay-meta { display: flex; flex-wrap: wrap; gap: 6px; }
.replay-meta-chip { border-radius: 999px; padding: 3px 7px; color: var(--muted); background: var(--surface-soft); font-size: 7.5px; }
.replay-meta-chip strong { color: var(--text); }
.replay-boundary { border-left: 3px solid var(--warn); padding: 5px 8px; color: var(--muted); background: color-mix(in srgb, var(--warn) 5%, transparent); font-size: 8px; line-height: 1.42; }
.replay-console-body { display: grid; grid-template-columns: minmax(0, 1fr) 286px; gap: 10px; align-items: start; min-width: 0; }
.replay-timeline-pane { min-width: 0; display: grid; gap: 8px; }
.replay-strip {
  display: flex;
  gap: 6px;
  min-height: 92px;
  height: 92px;
  overflow-x: auto;
  overscroll-behavior-inline: contain;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px;
  background: var(--surface-soft);
  scrollbar-width: thin;
}
.replay-frame {
  flex: 0 0 92px;
  min-height: 58px;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 7px;
  color: var(--muted);
  background: var(--surface-raised);
  text-align: left;
}
.replay-frame:hover { border-color: var(--accent); color: var(--text); }
.replay-frame[aria-current="step"] { border-color: var(--accent); color: var(--text); background: var(--accent-soft); box-shadow: inset 0 -3px 0 var(--accent); }
.replay-frame-sequence { display: block; font: 760 8px/1.2 Consolas, monospace; }
.replay-frame-kind { display: -webkit-box; margin-top: 5px; overflow: hidden; font-size: 8px; font-weight: 680; line-height: 1.3; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.replay-frame-map { display: block; margin-top: 5px; color: var(--faint); font-size: 7px; }
.replay-empty { flex: 1 1 auto; display: grid; place-items: center; min-height: 58px; border: 1px dashed var(--border-strong); border-radius: 8px; padding: 10px; color: var(--muted); font-size: 8.5px; text-align: center; }
.replay-transport, .replay-progress-line { display: flex; align-items: center; gap: 6px; }
.replay-transport { flex-wrap: wrap; }
.replay-controls { display: flex; align-items: center; gap: 5px; }
.replay-controls button { min-width: 32px; min-height: 30px; border: 1px solid var(--border); border-radius: 7px; color: var(--text); background: var(--surface); }
.replay-controls button:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.replay-controls button:disabled { color: var(--faint); cursor: not-allowed; }
.replay-speed { min-height: 30px; border: 1px solid var(--border); border-radius: 7px; padding: 0 7px; color: var(--text); background: var(--surface); font-size: 9px; }
.replay-progress-line { flex: 1 1 240px; min-width: 0; }
.replay-range { flex: 1 1 auto; min-width: 90px; accent-color: var(--accent); }
.replay-counter { flex: 0 0 auto; color: var(--muted); font: 9px Consolas, monospace; }
.replay-inspector { min-width: 0; border: 1px solid var(--border); border-radius: 10px; padding: 9px; background: var(--surface-soft); }
.replay-inspector-title { margin-bottom: 7px; color: var(--muted); font-size: 8px; font-weight: 780; letter-spacing: .05em; text-transform: uppercase; }
.replay-detail-list { display: grid; grid-template-columns: minmax(72px, auto) minmax(0, 1fr); gap: 0; overflow: hidden; border: 1px solid var(--border); border-radius: 8px; }
.replay-detail-key, .replay-detail-value { padding: 6px 7px; border-bottom: 1px solid var(--border); font-size: 7.5px; line-height: 1.38; overflow-wrap: anywhere; }
.replay-detail-key { color: var(--muted); background: var(--surface); }
.replay-detail-value { color: var(--text); }
.replay-detail-list > :nth-last-child(-n+2) { border-bottom: 0; }
.drawer-aux { display: grid; gap: 10px; margin-top: 14px; }
.drawer-panel-list { display: grid; gap: 8px; }
.drawer-panel-list .finding { margin: 0; padding: 10px; }
.finding {
  max-width: 1060px;
  margin: 0 auto 10px;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 14px;
  background: var(--surface);
  box-shadow: 0 5px 14px rgba(35, 52, 73, .04);
}
.finding-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; color: var(--muted); font-size: 10px; }
.finding-title { font-weight: 680; }
.finding-original { margin-top: 5px; color: var(--muted); font-size: 12px; line-height: 1.45; }
.finding.error { border-left: 4px solid var(--bad); }
.finding.warning { border-left: 4px solid var(--warn); }
.empty { padding: 70px 24px; color: var(--muted); text-align: center; }
.drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 49;
  background: var(--overlay);
  backdrop-filter: blur(2px);
}
.details-drawer {
  position: fixed;
  top: 12px;
  right: 12px;
  bottom: 12px;
  z-index: 50;
  width: min(420px, calc(100vw - 24px));
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 17px;
  padding: 18px;
  background: var(--surface-raised);
  box-shadow: 0 24px 70px rgba(9, 18, 31, .28);
}
.drawer-header { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.drawer-kicker { color: var(--accent); font-size: 10px; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }
.drawer-close { width: 34px; height: 34px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); color: var(--text); }
.details-drawer h2 { margin: 6px 0 4px; font-size: 19px; line-height: 1.3; }
.original-label { margin: 0; color: var(--muted); font-size: 11px; line-height: 1.45; }
.node-id { display: block; margin-top: 11px; overflow-wrap: anywhere; color: var(--faint); font: 10px/1.45 Consolas, monospace; }
.drawer-section { margin-top: 18px; }
.drawer-section h3 { margin: 0 0 8px; font-size: 12px; }
.property-list { display: grid; grid-template-columns: minmax(90px, auto) minmax(0, 1fr); gap: 0; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.property-key, .property-value { padding: 8px 9px; border-bottom: 1px solid var(--border); font-size: 11px; overflow-wrap: anywhere; }
.property-key { color: var(--muted); background: var(--surface-soft); }
.property-value { color: var(--text); }
.property-list > :nth-last-child(-n+2) { border-bottom: 0; }
.relation-list, .source-list { display: grid; gap: 6px; }
.relation-button, .source-item {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 8px 9px;
  color: var(--text);
  background: var(--surface);
  text-align: left;
  font-size: 11px;
  line-height: 1.4;
}
.relation-button:hover { border-color: var(--accent); }
.relation-kind { display: block; margin-bottom: 2px; color: var(--accent); font-size: 9px; font-weight: 720; }
.source-item { overflow-wrap: anywhere; color: var(--muted); font-family: Consolas, monospace; }
details.raw { margin-top: 18px; }
details.raw summary { color: var(--muted); cursor: pointer; font-size: 11px; }
details.raw pre { overflow: auto; max-height: 340px; padding: 10px; border-radius: 9px; background: var(--surface-soft); color: var(--muted); font-size: 10px; white-space: pre-wrap; overflow-wrap: anywhere; }
.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
[hidden] { display: none !important; }
@media (max-width: 1160px) {
  .diagram-toolbar { align-items: flex-start; flex-wrap: wrap; }
  .filters { width: 100%; justify-content: flex-start; flex-wrap: wrap; }
  .search-wrap { width: min(100%, 360px); }
  .spatial-stage { height: clamp(480px, 62vh, 620px); }
  .plan-workbench { grid-template-columns: minmax(0, 1fr) 250px; }
  .replay-console-body { grid-template-columns: minmax(0, 1fr) 250px; }
}
@media (max-width: 760px) {
  .page { padding: 12px 10px 22px; }
  .topbar { align-items: flex-start; }
  .header-actions { flex-direction: column; align-items: stretch; }
  .compact-select, .icon-button { min-height: 34px; }
  .tabs { width: 100%; overflow-x: auto; }
  .tab { white-space: nowrap; }
  .filter-control { flex: 1 1 130px; max-width: none; }
  .search-wrap { flex: 1 1 100%; max-width: none; }
  .spatial-stage { min-height: 440px; height: 58vh; }
  .spatial-node { width: 108px; max-width: 30vw; }
  .workspace-intro { align-items: flex-start; }
  .workspace-content { padding: 10px; }
  .semantic-stack { min-width: 0; }
  .overview-relations { display: none; }
  .semantic-layer { grid-template-columns: 1fr; }
  .semantic-layer-head { padding: 11px; }
  .semantic-track { grid-template-columns: 1fr; gap: 8px; padding: 10px; }
  .semantic-card, .telemetry-gap { grid-column: 1 !important; }
  .semantic-card { min-height: 64px; }
  .track-row { grid-template-columns: 1fr; gap: 5px; }
  .track-status { justify-self: start; }
  .plan-summary { padding-inline: 10px; }
  .plan-workbench { grid-template-columns: 1fr; padding-inline: 10px; }
  .plan-inspector { order: 2; }
  .spatial-node.flow-node { width: 170px; max-width: 48vw; }
  .spatial-hud-left { max-width: 245px; }
  .spatial-loop { grid-template-columns: 1fr; }
  .spatial-loop-arrow { transform: rotate(90deg); }
  .replay-console { margin-inline: 10px; padding: 10px; }
  .replay-console-head { display: grid; }
  .replay-track-tabs { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .replay-console-body { grid-template-columns: 1fr; }
  .replay-inspector { order: 2; }
  .replay-progress-line { flex-basis: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  .spatial-edge, .spatial-node { transition: none; }
}
</style>
</head>
<body>
<div class="page">
  <header class="topbar">
    <div class="brand">
      <span class="brand-dot" aria-hidden="true"></span>
      <div>
        <h1 id="pageTitle">__TITLE__</h1>
        <div class="summary" id="summary"></div>
      </div>
    </div>
    <div class="header-actions">
      <label class="visually-hidden" for="languageSelect" data-i18n="languageLabel">显示语言</label>
      <select id="languageSelect" class="compact-select" aria-label="显示语言">
        <option value="zh-CN">中文</option>
        <option value="en-US">English</option>
      </select>
      <button id="themeToggle" class="icon-button" type="button" aria-label="切换主题">◐ <span id="themeLabel">浅色</span></button>
    </div>
  </header>

  <section class="diagram-card">
    <div class="diagram-toolbar">
      <div class="tabs" role="tablist">
        <button class="tab active" type="button" role="tab" aria-selected="true" data-workspace-mode="overview" data-i18n="tabOverview">总览</button>
        <button class="tab" type="button" role="tab" aria-selected="false" data-workspace-mode="plan" data-i18n="tabPlan">规划</button>
        <button class="tab" type="button" role="tab" aria-selected="false" data-workspace-mode="run" data-i18n="tabRun">运行</button>
        <button class="tab" type="button" role="tab" aria-selected="false" data-workspace-mode="review" data-i18n="tabReview">复盘</button>
        <button class="tab" type="button" role="tab" aria-selected="false" data-workspace-mode="evidence" data-i18n="tabEvidence">证据</button>
      </div>
      <div class="filters">
        <div class="search-wrap" id="searchWrap"><input id="search" type="search" placeholder="搜索节点 ID、类型、标签或属性" autocomplete="off"></div>
        <select id="spatialRunFilter" class="filter-control"><option value="">最新 Run 快照</option></select>
        <select id="planViewSelect" class="filter-control" aria-label="规划视图" hidden>
          <option value="flow" data-spatial-mode="flow">依赖图</option>
          <option value="orthogonal" data-spatial-mode="orthogonal">正交空间</option>
        </select>
        <select id="relationFilter" class="filter-control">
          <option value="story" selected>主线关系</option>
          <option value="all">全部关系</option>
        </select>
        <button id="qualityButton" class="toolbar-action" type="button" data-i18n="qualityButton">质量</button>
      </div>
    </div>

    <div id="caseContext" class="case-context" aria-label="Case 上下文"></div>

    <div class="view active workspace-panel" id="overviewView" role="tabpanel" data-workspace-panel="overview">
      <div class="workspace-intro">
        <div>
          <h2 data-i18n="overviewTitle">三层闭环工作台</h2>
          <p data-i18n="overviewSubtitle">状态证据提供上下文，控制策略选择下一步，行动接口改变环境；结果再回流为新证据。</p>
        </div>
        <span class="workspace-kicker">S / C / A + Trace</span>
      </div>
      <div class="workspace-content">
        <div class="relation-legend" aria-label="关系线型图例">
          <span class="relation-legend-item"><span class="relation-swatch temporal"></span><span data-i18n="legendTemporal">实线 · 计划前置约束</span></span>
          <span class="relation-legend-item"><span class="relation-swatch evidence"></span><span data-i18n="legendEvidence">虚线 · 证据与论证</span></span>
          <span class="relation-legend-item"><span class="relation-swatch execution"></span><span data-i18n="legendImplementation">点划线 · 决策落实</span></span>
          <span class="relation-legend-item"><span class="relation-swatch mapping"></span><span data-i18n="legendMapping">状态标记 · Runtime Trace 覆盖（非语义层）</span></span>
        </div>
        <div id="overviewBoundary" class="workspace-boundary"></div>
        <div class="semantic-stack-viewport">
          <div id="semanticStack" class="semantic-stack" data-telemetry="missing">
            <svg id="overviewRelations" class="overview-relations" aria-hidden="true"></svg>
            <section class="semantic-layer" data-semantic-layer="state">
              <header class="semantic-layer-head">
                <span class="semantic-layer-index">01 / S</span>
                <span class="semantic-layer-title">State / Evidence</span>
                <span class="semantic-layer-note" data-i18n="knowledgeLayerNote">输入、观察、证据、记忆与产物</span>
              </header>
              <div id="stateTrack" class="semantic-track"></div>
            </section>
            <section class="semantic-layer" data-semantic-layer="control">
              <header class="semantic-layer-head">
                <span class="semantic-layer-index">02 / C</span>
                <span class="semantic-layer-title">Control</span>
                <span class="semantic-layer-note" data-i18n="controlLayerNote">决策、显式依赖、门禁与验证</span>
              </header>
              <div id="controlTrack" class="semantic-track"></div>
            </section>
            <section class="semantic-layer" data-semantic-layer="action">
              <header class="semantic-layer-head">
                <span class="semantic-layer-index">03 / A</span>
                <span class="semantic-layer-title">Action / Interface</span>
                <span class="semantic-layer-note" data-i18n="executionLayerNote">工具调用、代码执行、交接与外部操作</span>
              </header>
              <div id="actionTrack" class="semantic-track"></div>
            </section>
          </div>
        </div>
      </div>
    </div>

    <div class="view workspace-panel" id="runView" role="tabpanel" data-workspace-panel="run">
      <div class="workspace-intro">
        <div><h2 data-i18n="runTitle">运行前沿</h2><p data-i18n="runSubtitle">按 Runtime 状态查看可执行、运行中、阻塞、完成与失败的实例，不把状态快照冒充执行轨迹。</p></div>
        <span class="workspace-kicker">Run</span>
      </div>
      <div class="workspace-content"><div id="runBoundary" class="workspace-boundary"></div><div id="runLanes" class="run-lanes"></div></div>
    </div>

    <div class="view workspace-panel" id="reviewView" role="tabpanel" data-workspace-panel="review">
      <div class="workspace-intro">
        <div><h2 data-i18n="reviewTitle">复盘结论与缺口</h2><p data-i18n="reviewSubtitle">汇总记录完整性、当前计划状态与证据缺口；逐项检查统一进入规划回放。</p></div>
        <span class="workspace-kicker">Review</span>
      </div>
      <div class="workspace-content">
        <div id="reviewBoundary" class="workspace-boundary"></div>
        <div class="review-actionbar"><button id="reviewReplayButton" class="review-replay-button" type="button" data-i18n="reviewOpenReplay">打开顺序检查器</button></div>
        <div id="reviewTracks" class="track-list"></div>
      </div>
    </div>

    <div class="view workspace-panel" id="evidenceView" role="tabpanel" data-workspace-panel="evidence">
      <div class="workspace-intro">
        <div><h2 data-i18n="evidenceTitle">证据与决策路径</h2><p data-i18n="evidenceSubtitle">只展示图中明确记录的 supports、explains、implemented_by 与 checks 关系。</p></div>
        <span class="workspace-kicker">Evidence</span>
      </div>
      <div class="workspace-content"><div id="evidenceChains" class="evidence-chains"></div></div>
    </div>

    <div class="view" id="spatialView" role="tabpanel" data-workspace-panel="plan">
      <div class="spatial-panel">
        <div class="spatial-intro">
          <div>
            <h2 id="spatialTitle">显式计划依赖</h2>
            <p id="spatialSubtitle">主画布只显示 Run 的任务节点与 precedes 约束；位置不代表真实执行顺序或耗时。</p>
          </div>
          <span class="spatial-protocol">spatial-0.2</span>
        </div>
        <div id="planSummary" class="plan-summary" aria-label="规划摘要"></div>
        <div id="planWorkbench" class="plan-workbench" data-plan-view="flow">
          <div class="plan-canvas-shell">
            <div id="spatialStage" class="spatial-stage" aria-label="Agent Case Graph 规划依赖图">
          <div id="spatialViewport" class="spatial-viewport">
            <div id="spatialScene" class="spatial-scene">
              <svg id="spatialSvg" class="spatial-svg" aria-hidden="true"></svg>
              <div id="spatialNodeLayer" class="spatial-node-layer"></div>
              <div id="spatialEmpty" class="spatial-empty" hidden></div>
            </div>
          </div>

          <div id="spatialMeaningHud" class="spatial-hud spatial-hud-left">
            <div id="spatialLoopCard" class="spatial-card">
              <div class="spatial-loop" aria-label="信息闭环">
                <span data-i18n="loopKnowledge">State 状态</span><span class="spatial-loop-arrow">→</span>
                <span data-i18n="loopControl">Control 控制</span><span class="spatial-loop-arrow">→</span>
                <span data-i18n="loopExecution">Action 行动</span>
              </div>
              <div class="spatial-loop-sub" data-i18n="loopHint">行动结果回流为新的 State / Evidence；Runtime Trace 只覆盖实际经过的节点和关系。</div>
              <div id="spatialLayerSummary" class="spatial-layer-summary"></div>
            </div>
            <div id="flowLegendCard" class="spatial-card">
              <div class="flow-edge-legend"><span class="flow-edge-sample precedes"></span><span data-i18n="flowPrecedesLegend">precedes：计划前置约束</span></div>
              <div class="flow-edge-legend"><span class="flow-edge-sample structure"></span><span data-i18n="flowStructureLegend">证据与所属关系收纳在摘要或结构副视图</span></div>
            </div>
          </div>

          <div id="spatialLayerHud" class="spatial-hud spatial-hud-right">
            <div class="spatial-card spatial-layer-buttons" aria-label="空间投影层">
              <button class="spatial-layer-button active" type="button" data-spatial-layer="all" data-i18n="layerAll">全部</button>
              <button class="spatial-layer-button" type="button" data-spatial-layer="state">State</button>
              <button class="spatial-layer-button" type="button" data-spatial-layer="control">Control</button>
              <button class="spatial-layer-button" type="button" data-spatial-layer="action">Action</button>
            </div>
          </div>

          <div id="spatialCameraHud" class="spatial-hud spatial-hud-bottom">
            <div class="spatial-card spatial-camera-buttons" aria-label="空间视角控制">
              <button id="rotateLeft" class="spatial-camera-button" type="button" title="向左旋转">↶</button>
              <button id="rotateUp" class="spatial-camera-button" type="button" title="向上旋转">↑</button>
              <button id="rotateDown" class="spatial-camera-button" type="button" title="向下旋转">↓</button>
              <button id="rotateRight" class="spatial-camera-button" type="button" title="向右旋转">↷</button>
              <button id="resetCamera" class="spatial-camera-button" type="button" title="重置视角">◎</button>
            </div>
          </div>
            </div>
          </div>
          <aside id="planInspector" class="plan-inspector" aria-label="规划检查器"></aside>
        </div>

        <section id="replayHud" class="replay-console" aria-label="运行记录与回放">
          <header class="replay-console-head">
            <div>
              <div class="replay-title" data-i18n="replayTitle">运行记录与回放</div>
              <div class="replay-subtitle" data-i18n="replaySubtitle">四条顺序轨道分开检查；记录顺序、计划约束、候选顺序和真实执行不能互相冒充。</div>
            </div>
            <span class="spatial-protocol">replay-0.1 · visual only</span>
          </header>
          <div id="replayTrackTabs" class="replay-track-tabs" role="tablist" aria-label="顺序轨道">
            <button class="replay-track-tab active" type="button" role="tab" aria-selected="true" data-replay-mode="ledger">
              <span class="replay-track-name" data-i18n="replayLedger">Ledger 记录</span>
              <span class="replay-track-state" data-replay-track-state="ledger"></span>
            </button>
            <button class="replay-track-tab" type="button" role="tab" aria-selected="false" data-replay-mode="plan">
              <span class="replay-track-name" data-i18n="replayPlan">计划依赖</span>
              <span class="replay-track-state" data-replay-track-state="plan"></span>
            </button>
            <button class="replay-track-tab" type="button" role="tab" aria-selected="false" data-replay-mode="candidate">
              <span class="replay-track-name" data-i18n="replayCandidate">候选调度</span>
              <span class="replay-track-state" data-replay-track-state="candidate"></span>
            </button>
            <button class="replay-track-tab" type="button" role="tab" aria-selected="false" data-replay-mode="observed" data-track-availability="unavailable">
              <span class="replay-track-name" data-i18n="replayObserved">已观测执行</span>
              <span class="replay-track-state" data-replay-track-state="observed"></span>
            </button>
          </div>
          <div id="replayMeta" class="replay-meta"></div>
          <div id="replayBoundary" class="replay-boundary" role="status"></div>
          <div class="replay-console-body">
            <div class="replay-timeline-pane">
              <div id="replayStrip" class="replay-strip" role="listbox" aria-label="记录时间线"></div>
              <div class="replay-transport">
                <div class="replay-controls">
                  <button id="replayReset" type="button" aria-label="回到第一项" title="回到第一项">|◀</button>
                  <button id="replayPrev" type="button" aria-label="上一项" title="上一项">◀</button>
                  <button id="replayPlay" type="button" aria-label="播放" title="播放">▶</button>
                  <button id="replayNext" type="button" aria-label="下一项" title="下一项">▶</button>
                  <button id="replayLast" type="button" aria-label="跳到最后一项" title="跳到最后一项">▶|</button>
                </div>
                <div class="replay-progress-line">
                  <input id="replayRange" class="replay-range" type="range" min="0" max="0" value="0" aria-label="播放位置">
                  <span id="replayCounter" class="replay-counter">0 / 0</span>
                </div>
                <select id="replaySpeed" class="replay-speed" aria-label="播放速度">
                  <option value="0.5">0.5×</option>
                  <option value="1" selected>1×</option>
                  <option value="2">2×</option>
                  <option value="4">4×</option>
                </select>
              </div>
            </div>
            <aside id="replayInspector" class="replay-inspector" aria-label="当前项详情">
              <div class="replay-inspector-title" data-i18n="replayCurrentItem">当前项</div>
              <div id="replayDetails" class="replay-detail-list"></div>
            </aside>
          </div>
        </section>
      </div>
    </div>
  </section>
</div>

<div id="drawerBackdrop" class="drawer-backdrop" hidden></div>
<aside id="detailsDrawer" class="details-drawer" aria-hidden="true" hidden>
  <div class="drawer-header">
    <div>
      <div id="drawerKicker" class="drawer-kicker"></div>
      <h2 id="drawerTitle"></h2>
    </div>
    <button id="drawerClose" class="drawer-close" type="button" aria-label="关闭">×</button>
  </div>
  <div id="drawerNodeContent">
    <p id="drawerOriginal" class="original-label"></p>
    <code id="drawerId" class="node-id"></code>
    <section class="drawer-section">
      <h3 data-i18n="propertiesTitle">属性</h3>
      <div id="propertyList" class="property-list"></div>
    </section>
    <section class="drawer-section">
      <h3 data-i18n="relationsTitle">直接关系</h3>
      <div id="relationList" class="relation-list"></div>
    </section>
    <section class="drawer-section">
      <h3 data-i18n="sourcesTitle">来源</h3>
      <div id="sourceList" class="source-list"></div>
    </section>
    <details class="raw">
      <summary data-i18n="rawTitle">查看原始投影数据</summary>
      <pre id="rawJson"></pre>
    </details>
  </div>
  <div id="drawerAux" class="drawer-aux" hidden>
    <div id="findings" class="drawer-panel-list" hidden></div>
  </div>
</aside>

<script id="graph-data" type="application/json">__GRAPH_JSON__</script>
<script id="events-data" type="application/json">__EVENTS_JSON__</script>
<script id="findings-data" type="application/json">__FINDINGS_JSON__</script>
<script id="display-locales-data" type="application/json">__DISPLAY_LOCALES_JSON__</script>
<script id="source-title-data" type="application/json">__SOURCE_TITLE_JSON__</script>
<script id="default-locale-data" type="application/json">__DEFAULT_LOCALE_JSON__</script>
<script>
"use strict";
const graph = JSON.parse(document.getElementById("graph-data").textContent);
const events = JSON.parse(document.getElementById("events-data").textContent);
const findings = JSON.parse(document.getElementById("findings-data").textContent);
const displayLocales = JSON.parse(document.getElementById("display-locales-data").textContent);
const sourceTitle = JSON.parse(document.getElementById("source-title-data").textContent);
const configuredLocale = JSON.parse(document.getElementById("default-locale-data").textContent);
const nodeById = new Map(graph.nodes.map(function (node) { return [node.id, node]; }));
const eventById = new Map(events.map(function (event) { return [event.event_id, event]; }));

const UI = {
  "zh-CN": {
    languageLabel: "显示语言",
    themeToggle: "切换主题",
    tabOverview: "总览",
    tabPlan: "规划",
    tabRun: "运行",
    tabReview: "复盘",
    tabEvidence: "证据",
    planViewFlow: "依赖主图",
    planViewOrthogonal: "辅助 · 六面体正交空间",
    overviewTitle: "三层闭环工作台",
    overviewSubtitle: "状态证据提供上下文，控制策略选择下一步，行动接口改变环境；结果再回流为新证据。",
    runTitle: "运行前沿",
    runSubtitle: "按 Runtime 状态查看可执行、运行中、阻塞、完成与失败的实例，不把状态快照冒充执行轨迹。",
    reviewTitle: "复盘结论与缺口",
    reviewSubtitle: "汇总记录完整性、当前计划状态与证据缺口；逐项检查统一进入规划回放。",
    evidenceTitle: "证据与决策路径",
    evidenceSubtitle: "只展示图中明确记录的 supports、explains、implemented_by 与 checks 关系。",
    knowledgeLayerNote: "输入、观察、证据、记忆与产物",
    controlLayerNote: "决策、显式依赖、门禁与验证",
    executionLayerNote: "工具调用、代码执行、交接与外部操作",
    legendTemporal: "实线 · 计划前置约束",
    legendEvidence: "虚线 · 证据与论证",
    legendImplementation: "点划线 · 决策落实",
    legendMapping: "状态标记 · Runtime Trace 覆盖（非语义层）",
    overviewTelemetryMissing: "三层语义结构可用；当前只有 Runtime 状态快照，没有完整执行遥测。状态标记不证明真实顺序、交接或耗时。",
    overviewTelemetryPresent: "三层语义结构叠加了显式执行遥测；仅当前真实关系使用一次有限流动提示。",
    runtimeInstance: "Run 实例",
    runtimeProjection: "实例投影",
    runtimeGap: "等待 VerificationReceipt / Observation 回流；当前没有可证明的 Action → State 反馈关系。",
    runBoundaryMissing: "当前只有 Runtime 推导状态快照，没有完整已观测执行 trace。状态列表示此刻的 frontier，不表示时间线。",
    runBoundaryPresent: "当前 Run 存在已观测执行遥测；状态列仍只表示当前 frontier。",
    laneReady: "可执行",
    laneRunning: "运行中",
    laneBlocked: "阻塞",
    laneCompleted: "完成",
    laneFailed: "失败",
    laneEmpty: "无实例",
    runZeroStates: "当前为 0：{states}",
    trackLedger: "Ledger 记录",
    trackPlan: "计划依赖",
    trackCandidate: "候选调度",
    trackObserved: "已观测执行",
    trackAvailable: "可用",
    trackUnavailable: "不可用",
    trackGated: "受门禁阻塞",
    reviewBoundary: "本页只汇总结论，不复制回放控件。相邻 Ledger 事件不是任务交接，候选调度也不是实际执行。",
    reviewOpenReplay: "打开顺序检查器",
    reviewRecordTitle: "记录完整性",
    reviewRecordDetail: "{count} 条 Ledger 事件 · {capture}；它只能证明记录顺序。",
    reviewStateTitle: "计划与前沿",
    reviewStateDetail: "{nodes} 个任务 / {edges} 条前置约束；当前 {runtime}；候选调度 {candidate}。",
    reviewGapTitle: "执行证据",
    reviewGapPresent: "已提供 execution-* 遥测，可在顺序检查器核对真实执行。",
    reviewGapMissing: "缺少 execution-* 遥测；不能声明真实顺序、交接或耗时。",
    evidenceReasoningChain: "观察 → 论断 → 决策 → 实现",
    evidenceVerificationChain: "验证 → 验收标准",
    evidenceNoPaths: "当前 Case 没有可展示的显式证据路径",
    flowTitle: "动作处理主线",
    flowSubtitle: "每个节点显示做了什么、使用的工具和产出；连线只表示显式 precedes，重建动作不冒充原生执行时间线。",
    orthogonalTitle: "六面体正交路由",
    orthogonalSubtitle: "三个相邻面只放 State / Control / Action 节点，三个相对面只走跨层线路：S↔C ∥ A，C↔A ∥ S，A↔S ∥ C。",
    latestRun: "最新 Run 快照",
    layerAll: "全部",
    loopKnowledge: "State 状态",
    loopControl: "Control 控制",
    loopExecution: "Action 行动",
    loopHint: "行动结果回流为新的 State / Evidence；Runtime Trace 只覆盖实际经过的节点和关系。",
    flowRank: "依赖层级 {rank}",
    flowRunScope: "Run 范围 · {run}",
    flowCycleWarning: "检测到 precedes 依赖环；已停止生成顺序层级。",
    flowPrecedesLegend: "precedes：计划前置约束",
    flowStructureLegend: "证据与所属关系收纳在摘要或结构副视图",
    planRevision: "计划快照",
    planNodes: "任务节点",
    planConstraints: "前置约束",
    planFrontier: "Runtime 前沿",
    planObservedMissing: "真实执行未录制",
    planObservedPresent: "真实执行可观测",
    planInspectorTitle: "规划检查器",
    planInspectorNote: "层级是 precedes 偏序，不是时间；状态来自当前 Runtime 快照。",
    actionToolLabel: "工具",
    actionOutputLabel: "产出",
    planActiveTitle: "当前动作",
    planBlockerTitle: "主要阻塞",
    planNoActive: "当前没有运行中或可执行任务",
    planNoBlocker: "当前没有已登记阻塞",
    planFrontierTitle: "节点与门禁",
    planConstraintsTitle: "显式约束",
    planNoTasks: "当前 Run 没有任务节点",
    planNoConstraints: "没有显式 precedes 约束",
    planLevel: "L{rank}",
    planDependency: "precedes",
    planNoRuntime: "未进入 Runtime 快照",
    contextNoBlocker: "当前没有已登记阻塞",
    contextCase: "Case",
    contextRun: "Run",
    syntheticBadge: "Synthetic 示例",
    snapshotBadge: "快照 · Ledger #{sequence}",
    executionTelemetryMissing: "已观测执行：未提供完整执行遥测",
    executionTelemetryPresent: "已观测执行：存在显式执行遥测",
    replayTitle: "运行记录与回放",
    replaySubtitle: "四条顺序轨道分开检查；记录顺序、计划约束、候选顺序和真实执行不能互相冒充。",
    replayLedger: "Ledger 记录",
    replayPlan: "计划依赖",
    replayCandidate: "候选调度",
    replayObserved: "已观测执行",
    replayTrackItems: "{count} 项",
    replayPlanItems: "{nodes} 节点 / {edges} 约束",
    replayUnavailableShort: "未提供",
    replayGatedShort: "门禁阻塞",
    replayCurrentItem: "当前项",
    replayReset: "回到第一项",
    replayPrev: "上一项",
    replayPlay: "播放",
    replayPause: "暂停",
    replayNext: "下一项",
    replayLast: "跳到最后一项",
    replayPosition: "播放位置",
    replaySpeed: "播放速度",
    replayUnavailable: "当前 Run 没有可重放轨迹",
    replayPlanBoundary: "计划依赖是显式 precedes 偏序，不是时间轴，因此只检查、不自动播放。",
    replayObservedUnavailable: "未提供 execution-* 执行遥测：不能声明真实执行顺序、交接或耗时，播放控件已禁用。",
    replayObservedBoundary: "只有显式 execution-* 遥测允许按真实执行轨迹播放并显示一次有限流动提示。",
    replayRecommendationGated: "当前 runtime 门禁未满足，候选调度不可执行。",
    replayVisualOnly: "只读可视化；不会重新执行 Action 或外部副作用。",
    replayRecommendationBoundary: "按显式 precedes 与 runtime 门禁得到的确定性候选调度；相邻项不等于真实执行交接，也不是全局最优证明。",
    replaySynthetic: "在最终导出快照上高亮 Synthetic Ledger 记录；不是逐帧历史还原，也不代表真实执行。",
    replayReconstructed: "在最终导出快照上高亮重建记录；不是原始逐步执行轨迹。",
    replayLive: "live Ledger 记录回看；不是完整执行 trace，原始工具输入输出可能未完整录制。",
    replayAuthority: "权威",
    replayCapture: "采集",
    replayCompleteness: "完整性",
    replayTrackKind: "轨道类型",
    replayItemCount: "项目数",
    replayDetailTrack: "轨道",
    replayDetailPosition: "位置",
    replayDetailEvent: "事件",
    replayDetailKind: "类型",
    replayDetailTime: "时间",
    replayDetailSubject: "对象",
    replayDetailTransition: "状态",
    replayDetailActor: "参与者",
    replayDetailCapture: "采集模式",
    replayDetailSources: "来源",
    replayDetailMapping: "规划图映射",
    replayDetailNode: "节点",
    replayDetailLane: "Runtime 列",
    replayDetailBlockers: "门禁",
    replayDetailPriority: "优先级",
    replayDetailOptimality: "最优性",
    replayDetailDependency: "约束",
    replayMapped: "可在规划图定位",
    replayNotMapped: "当前记录不属于规划主图；图保持稳定",
    replayNoSources: "未登记",
    qualityButton: "质量",
    qualityTitle: "质量检查",
    spatialNoData: "当前筛选没有可展示的节点",
    executionNoRuntime: "此图没有已观测 Runtime Trace 覆盖",
    resetCamera: "重置视角",
    rotateLeft: "向左旋转",
    rotateRight: "向右旋转",
    rotateUp: "向上旋转",
    rotateDown: "向下旋转",
    searchPlaceholder: "搜索节点 ID、类型、标签或属性",
    relationsStory: "主线关系",
    relationsAll: "全部关系",
    nodes: "节点",
    edges: "关系",
    events: "事件",
    errors: "错误",
    warnings: "警告",
    state: "状态",
    noFindings: "没有质量问题",
    propertiesTitle: "属性",
    relationsTitle: "直接关系",
    sourcesTitle: "来源",
    rawTitle: "查看原始投影数据",
    noProperties: "没有额外属性",
    noRelations: "没有直接关系",
    noSources: "没有登记来源",
    originalLabel: "原始标签",
    close: "关闭",
    themeLight: "浅色",
    themeDark: "深色",
    incoming: "入向",
    outgoing: "出向",
  },
  "en-US": {
    languageLabel: "Display language",
    themeToggle: "Toggle theme",
    tabOverview: "Overview",
    tabPlan: "Plan",
    tabRun: "Run",
    tabReview: "Review",
    tabEvidence: "Evidence",
    planViewFlow: "Primary dependency graph",
    planViewOrthogonal: "Aux · orthogonal cuboid",
    overviewTitle: "Three-layer closed-loop workbench",
    overviewSubtitle: "State and evidence provide context, control and policy select the next step, and actions change the environment before results return as evidence.",
    runTitle: "Runtime frontier",
    runSubtitle: "Inspect ready, running, blocked, completed, and failed instances without presenting a state snapshot as an execution trace.",
    reviewTitle: "Review conclusions and gaps",
    reviewSubtitle: "Summarize record completeness, current plan state, and evidence gaps; use Plan replay for item-by-item inspection.",
    evidenceTitle: "Evidence and decision paths",
    evidenceSubtitle: "Only explicitly recorded supports, explains, implemented_by, and checks relations are shown.",
    knowledgeLayerNote: "Inputs, observations, evidence, memory, and artifacts",
    controlLayerNote: "Decisions, explicit dependencies, gates, and verification",
    executionLayerNote: "Tool calls, code execution, handoffs, and external effects",
    legendTemporal: "Solid · planned prerequisite",
    legendEvidence: "Dashed · evidence and reasoning",
    legendImplementation: "Dash-dot · decision implementation",
    legendMapping: "Status marker · Runtime Trace overlay (not a semantic layer)",
    overviewTelemetryMissing: "The three semantic layers are available, but only a Runtime state snapshot is present. Status markers do not prove real order, handoff, or duration.",
    overviewTelemetryPresent: "Explicit execution telemetry is overlaid on the three semantic layers; only the current real relation receives one finite motion cue.",
    runtimeInstance: "Run instance",
    runtimeProjection: "instance projection",
    runtimeGap: "Waiting for VerificationReceipt / Observation feedback; no provable Action → State feedback relation is available.",
    runBoundaryMissing: "Only an inferred Runtime state snapshot is available, not a complete observed execution trace. Lanes represent the current frontier, not a timeline.",
    runBoundaryPresent: "Observed execution telemetry is available for this Run; lanes still represent only the current frontier.",
    laneReady: "Ready",
    laneRunning: "Running",
    laneBlocked: "Blocked",
    laneCompleted: "Completed",
    laneFailed: "Failed",
    laneEmpty: "No instances",
    runZeroStates: "Currently zero: {states}",
    trackLedger: "Ledger records",
    trackPlan: "Plan dependencies",
    trackCandidate: "Candidate schedule",
    trackObserved: "Observed execution",
    trackAvailable: "Available",
    trackUnavailable: "Unavailable",
    trackGated: "Gated",
    reviewBoundary: "This page summarizes conclusions without duplicating replay controls. Adjacent Ledger events are not task handoffs, and a candidate schedule is not actual execution.",
    reviewOpenReplay: "Open order inspector",
    reviewRecordTitle: "Record completeness",
    reviewRecordDetail: "{count} Ledger events · {capture}; this proves record order only.",
    reviewStateTitle: "Plan and frontier",
    reviewStateDetail: "{nodes} tasks / {edges} prerequisites; now {runtime}; candidate schedule {candidate}.",
    reviewGapTitle: "Execution evidence",
    reviewGapPresent: "Explicit execution-* telemetry is available for real-order inspection.",
    reviewGapMissing: "No execution-* telemetry is available; real order, handoff, and duration cannot be claimed.",
    evidenceReasoningChain: "Observation → Claim → Decision → Implementation",
    evidenceVerificationChain: "Verification → Acceptance criterion",
    evidenceNoPaths: "This Case has no explicit evidence path to display",
    flowTitle: "Action workflow",
    flowSubtitle: "Each node shows the action, tool, and output. Edges are explicit precedes constraints; reconstructed actions are not presented as a native execution timeline.",
    orthogonalTitle: "Orthogonal cuboid routing",
    orthogonalSubtitle: "Three adjacent faces contain State / Control / Action nodes; three opposite faces carry cross-layer routes: S↔C ∥ A, C↔A ∥ S, and A↔S ∥ C.",
    latestRun: "Latest Run snapshot",
    layerAll: "All",
    loopKnowledge: "State",
    loopControl: "Control",
    loopExecution: "Action",
    loopHint: "Action results return as State / Evidence. Runtime Trace only overlays observed nodes and relations.",
    flowRank: "Dependency level {rank}",
    flowRunScope: "Run scope · {run}",
    flowCycleWarning: "A precedes dependency cycle was detected; ordered levels are disabled.",
    flowPrecedesLegend: "precedes: planned prerequisite constraint",
    flowStructureLegend: "Evidence and membership relations live in summaries or structural views",
    planRevision: "Plan snapshot",
    planNodes: "Task nodes",
    planConstraints: "Prerequisites",
    planFrontier: "Runtime frontier",
    planObservedMissing: "Actual execution not recorded",
    planObservedPresent: "Actual execution observed",
    planInspectorTitle: "Plan inspector",
    planInspectorNote: "Levels are a precedes partial order, not time; state comes from the current Runtime snapshot.",
    actionToolLabel: "Tool",
    actionOutputLabel: "Output",
    planActiveTitle: "Current action",
    planBlockerTitle: "Primary blocker",
    planNoActive: "No running or ready task",
    planNoBlocker: "No recorded blocker",
    planFrontierTitle: "Nodes and gates",
    planConstraintsTitle: "Explicit constraints",
    planNoTasks: "This Run has no task nodes",
    planNoConstraints: "No explicit precedes constraints",
    planLevel: "L{rank}",
    planDependency: "precedes",
    planNoRuntime: "Not present in the Runtime snapshot",
    contextNoBlocker: "No recorded blocker",
    contextCase: "Case",
    contextRun: "Run",
    syntheticBadge: "Synthetic example",
    snapshotBadge: "Snapshot · Ledger #{sequence}",
    executionTelemetryMissing: "Observed execution: complete execution telemetry is unavailable",
    executionTelemetryPresent: "Observed execution: explicit execution telemetry is available",
    replayTitle: "Run records and replay",
    replaySubtitle: "Inspect four order tracks separately; record order, plan constraints, candidate order, and real execution are not interchangeable.",
    replayLedger: "Ledger records",
    replayPlan: "Plan dependencies",
    replayCandidate: "Candidate schedule",
    replayObserved: "Observed execution",
    replayTrackItems: "{count} items",
    replayPlanItems: "{nodes} nodes / {edges} constraints",
    replayUnavailableShort: "Unavailable",
    replayGatedShort: "Gated",
    replayCurrentItem: "Current item",
    replayReset: "Go to first item",
    replayPrev: "Previous item",
    replayPlay: "Play",
    replayPause: "Pause",
    replayNext: "Next item",
    replayLast: "Go to last item",
    replayPosition: "Playback position",
    replaySpeed: "Playback speed",
    replayUnavailable: "The selected Run has no replayable track",
    replayPlanBoundary: "Plan dependencies are an explicit precedes partial order, not a timeline, so they are inspectable but not auto-played.",
    replayObservedUnavailable: "No execution-* telemetry is provided: real order, handoff, and duration cannot be claimed, and playback controls are disabled.",
    replayObservedBoundary: "Only explicit execution-* telemetry may drive real execution playback and one finite motion cue.",
    replayRecommendationGated: "Current runtime gates are unresolved, so the candidate schedule is not executable.",
    replayVisualOnly: "Read-only visualization; Actions and external side effects are never re-executed.",
    replayRecommendationBoundary: "Deterministic candidate schedule from explicit precedes edges and runtime gates; adjacent items do not prove an execution handoff or global optimality.",
    replaySynthetic: "Synthetic Ledger records highlighted on the final exported snapshot; not historical frame reconstruction or real execution.",
    replayReconstructed: "Reconstructed records highlighted on the final exported snapshot; not the original step-by-step execution trace.",
    replayLive: "Live Ledger record review; not a complete execution trace, and raw tool input or output may be incomplete.",
    replayAuthority: "Authority",
    replayCapture: "Capture",
    replayCompleteness: "Completeness",
    replayTrackKind: "Track kind",
    replayItemCount: "Items",
    replayDetailTrack: "Track",
    replayDetailPosition: "Position",
    replayDetailEvent: "Event",
    replayDetailKind: "Kind",
    replayDetailTime: "Time",
    replayDetailSubject: "Subject",
    replayDetailTransition: "State",
    replayDetailActor: "Actor",
    replayDetailCapture: "Capture mode",
    replayDetailSources: "Sources",
    replayDetailMapping: "Plan mapping",
    replayDetailNode: "Node",
    replayDetailLane: "Runtime lane",
    replayDetailBlockers: "Gates",
    replayDetailPriority: "Priority",
    replayDetailOptimality: "Optimality",
    replayDetailDependency: "Constraint",
    replayMapped: "Mapped on the plan graph",
    replayNotMapped: "This record is outside the primary plan graph; the graph stays stable",
    replayNoSources: "Not recorded",
    qualityButton: "Quality",
    qualityTitle: "Quality checks",
    spatialNoData: "No node matches the current filters",
    executionNoRuntime: "This graph has no observed Runtime Trace overlay",
    resetCamera: "Reset camera",
    rotateLeft: "Rotate left",
    rotateRight: "Rotate right",
    rotateUp: "Rotate up",
    rotateDown: "Rotate down",
    searchPlaceholder: "Search node ID, type, label, or attributes",
    relationsStory: "Primary relationships",
    relationsAll: "All relationships",
    nodes: "nodes",
    edges: "relationships",
    events: "events",
    errors: "errors",
    warnings: "warnings",
    state: "state",
    noFindings: "No quality findings",
    propertiesTitle: "Properties",
    relationsTitle: "Direct relationships",
    sourcesTitle: "Sources",
    rawTitle: "View canonical projection data",
    noProperties: "No additional properties",
    noRelations: "No direct relationships",
    noSources: "No source references",
    originalLabel: "Original label",
    close: "Close",
    themeLight: "Light",
    themeDark: "Dark",
    incoming: "incoming",
    outgoing: "outgoing",
  }
};

const NODE_ZH = {
  Graph: "图谱", ProblemType: "问题类型", Case: "案例", Goal: "目标",
  AcceptanceCriterion: "验收标准", Run: "运行", Step: "步骤", Actor: "参与者",
  Capability: "能力", Agent: "代理", Skill: "技能", Tool: "工具", Target: "目标对象",
  EnvironmentSnapshot: "环境快照", Artifact: "产物", Observation: "观察", Claim: "论断",
  RootCause: "根因", Decision: "决策", Uncertainty: "不确定性", ScopeBoundary: "范围边界",
  Action: "操作", Approval: "授权", Policy: "策略", Verification: "验证",
  VerificationReceipt: "验证回执", Pattern: "模式", Runbook: "操作手册",
  SkillVersion: "技能版本", EvalCase: "评测案例", DriftFinding: "漂移发现",
  ExternalIssue: "外部问题"
};
const EDGE_ZH = {
  instance_of: "属于", contains: "包含", has_run: "关联运行", targets: "指向目标",
  runs_in: "运行于", uses: "使用", invokes: "调用", precedes: "先于", produces: "产出",
  derived_from: "源自", supports: "支持", refutes: "反驳", explains: "解释",
  approved_by: "经批准", guarded_by: "受约束", modifies: "修改", checks: "检查",
  verified_by: "经验证", satisfies: "满足", blocked_by: "受阻塞", retry_of: "重试自",
  regression_of: "回归自", generalizes_to: "泛化至", implemented_by: "由实现",
  tested_by: "由测试", supersedes: "替代", deprecated_by: "由弃用", references: "引用"
};
const EVENT_ZH = {
  "graph.declared": "图谱已声明", "node.recorded": "节点已记录",
  "edge.recorded": "关系已记录", "state.changed": "状态已变化"
};
const MODE_ZH = {live: "实时", reconstructed: "重建", synthetic: "合成"};
const ACTOR_ZH = {human: "人工", agent: "代理", tool: "工具", service: "服务"};
const STATUS_ZH = {
  intake: "受理", observe: "观察", analyze: "分析", plan: "规划", authorize: "授权",
  execute: "执行", verify: "验证", close: "关闭", promote: "晋升", blocked: "阻塞",
  reopen: "重新打开", regress: "回归", completed: "已完成", passed: "通过",
  failed: "失败", running: "运行中", executing: "执行中", granted: "已授权",
  satisfied: "已满足", confirmed: "已确认", uncertain: "不确定", failed_safe: "安全失败",
  failed_usability: "可用性失败", created: "已创建", accepted: "已采纳",
  pending: "待处理", ready: "可执行", claimed: "已领取", succeeded: "已成功",
  skipped: "已跳过", unknown: "状态未知"
};
const PROPERTY_ZH = {
  status: "状态", current_state: "当前阶段", capture_mode: "采集模式", scope: "范围",
  target: "目标", tests: "测试数", errors: "错误数", warnings: "警告数",
  limitations: "限制", mutating: "会修改状态", priority: "优先级",
  definition_version: "定义版本", duration_seconds: "耗时秒数", source_path: "来源路径",
  source_uri: "来源地址", sha256: "SHA256", boundary: "边界", finding: "发现",
  first_sequence: "首次序号", conclusion: "结论", output: "输出", risk: "风险",
  source: "来源", time: "时间", type: "类型", path: "路径", repo: "仓库",
  details: "详情", limitation: "限制", change_id: "Change-Id", commit: "提交",
  exit_code: "退出码", service_id: "服务 ID", service_type: "服务类型",
  service_count: "服务数", size_bytes: "字节数", source_file_count: "来源文件数",
  source_issue_dir: "来源问题目录", content_loaded: "内容已加载", has_av_pid: "包含 AV PID",
  blocks_close: "阻止关闭", device_verified: "设备已验证", first_failed_boundary: "首次失败边界",
  fresh_result: "最新结果", fresh_passed_result: "最新通过结果",
  independently_replayed: "已独立回放", not_current_authorization: "非本次授权",
  reported_verification: "报告中的验证", v3_provider_rows: "V3 Provider 行数",
  v4_inserted: "V4 已插入", v4_provider_rows: "V4 Provider 行数",
  full_text: "完整文本", error: "错误", events: "事件数", edges: "关系数",
  nodes: "节点数", tests_passed: "通过测试数", compileall: "编译检查",
  visual_qa: "可视化验证", input_hash_changes: "输入哈希变化数",
  ledger_events_added: "新增 Ledger 事件数", lint_errors: "Lint 错误数",
  lint_warnings: "Lint 警告数", lint_findings: "Lint 发现数",
  bootstrap_core_nodes: "自举核心节点数", bootstrap_lint_errors: "自举 Lint 错误数",
  bootstrap_edges: "自举关系数", bootstrap_runs: "自举运行数",
  historical_all_nodes: "历史图全部节点数", historical_edges: "历史图关系数",
  historical_core_nodes: "历史图核心节点数",
  historical_evidence_nodes: "历史图证据节点数", historical_execution_nodes: "历史图执行节点数",
  historical_input_hash_changes: "历史输入哈希变化数", historical_lint_errors: "历史图 Lint 错误数",
  historical_runs: "历史运行数", flow_phases: "信息流阶段数", body_overflow: "页面溢出",
  flow_overflow: "信息流溢出", runtime_managed: "由运行时管理", executor: "执行器",
  authorized_scope: "授权范围", expected_outputs: "期望产出", runtime_reason: "运行状态原因",
  runtime_checkpoint_id: "Checkpoint ID", attempt: "执行次数"
};
const FINDING_ZH = {
  ACG001: "根节点缺失", ACG002: "根节点必须是案例", ACG003: "关系来源节点不存在",
  ACG004: "关系目标节点不存在", ACG005: "案例没有运行记录", ACG006: "论断没有证据关系",
  ACG007: "已确认论断没有支持证据", ACG008: "产物没有来源路径或地址",
  ACG009: "产物没有有效 SHA256", ACG010: "产物没有采集模式",
  ACG011: "修改性操作没有授权", ACG012: "技能版本没有来源模式",
  ACG013: "技能版本没有评测案例", ACG014: "已完成案例没有验证回执",
  ACG015: "状态历史不连续", ACG016: "状态转换不合法",
  ACG017: "存在重复语义关系"
};
const spatialCoreTypes = new Set(["Case", "Goal", "AcceptanceCriterion", "Run", "RootCause", "Claim", "Decision", "Uncertainty", "Observation", "Action", "Approval", "Target", "ScopeBoundary", "Verification", "VerificationReceipt"]);
const primaryEdgeTypes = new Set(["targets", "has_run", "precedes", "uses", "invokes", "produces", "supports", "refutes", "explains", "implemented_by", "approved_by", "guarded_by", "modifies", "checks", "verified_by", "satisfies", "blocked_by"]);

let selectedId = null;
let currentLocale = resolveInitialLocale();
const initialViewParams = new URLSearchParams(window.location.search);
let workspaceMode = ["overview", "plan", "run", "review", "evidence"].includes(initialViewParams.get("mode")) ? initialViewParams.get("mode") : "overview";
let spatialMode = initialViewParams.get("plan") === "orthogonal" ? "orthogonal" : "flow";
let spatialLayer = "all";
let spatialCamera = {yaw: -0.62, pitch: 0.48, scale: 1};
let spatialDrag = null;
let activeAuxPanel = null;
let spatialRenderState = {instances: [], instanceByKey: new Map(), visibleIds: new Set()};
let replayMode = "ledger";
let replayCursors = {ledger: 0, candidate: 0, observed: 0};
let replayTimer = null;
const ORTHOGONAL_SIZE = 520;
const ORTHOGONAL_INSET = 66;

function resolveInitialLocale() {
  let locale = configuredLocale === "en-US" ? "en-US" : "zh-CN";
  try {
    const stored = localStorage.getItem("acg-locale");
    if (stored === "zh-CN" || stored === "en-US") locale = stored;
  } catch (_) {}
  return locale;
}
function message(key, values) {
  let text = (UI[currentLocale] && UI[currentLocale][key]) || UI["en-US"][key] || key;
  Object.entries(values || {}).forEach(function (entry) {
    text = text.replace("{" + entry[0] + "}", String(entry[1]));
  });
  return text;
}
function translated(mapping, value) {
  if (currentLocale === "zh-CN" && Object.prototype.hasOwnProperty.call(mapping, value)) return mapping[value];
  return value;
}
function nodeTypeLabel(type) { return translated(NODE_ZH, type); }
function edgeTypeLabel(type) { return translated(EDGE_ZH, type); }
function eventKindLabel(kind) { return translated(EVENT_ZH, kind); }
function modeLabel(mode) { return translated(MODE_ZH, mode); }
function actorLabel(actor) { return translated(ACTOR_ZH, actor); }
function statusLabel(status) { return translated(STATUS_ZH, status); }
function propertyLabel(key) { return translated(PROPERTY_ZH, key); }
function localizedNodeLabel(node) {
  const bundle = displayLocales[currentLocale];
  return (bundle && bundle.nodes && bundle.nodes[node.id]) || node.label;
}
function localizedTitle() {
  const bundle = displayLocales[currentLocale];
  return (bundle && bundle.title) || sourceTitle;
}
function rootNode() { return nodeById.get(graph.root_id); }
function rootState() {
  const root = rootNode();
  return root && root.attrs ? (root.attrs.current_state || root.attrs.status || "") : "";
}
function adjacentIds(id) {
  const result = new Set([id]);
  graph.edges.forEach(function (edge) {
    if (edge.from === id) result.add(edge.to);
    if (edge.to === id) result.add(edge.from);
  });
  return result;
}
function clearElement(element) {
  while (element.firstChild) element.removeChild(element.firstChild);
}
function createText(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  return element;
}
const SPATIAL_LAYER_COLORS = {
  state: "var(--reason)", control: "var(--accent)", action: "var(--execute)"
};
const SPATIAL_FLOW_COLORS = {
  state: "var(--reason)", control: "var(--accent)", action: "var(--execute)",
  "state-control": "var(--scope)", "control-action": "var(--evidence)",
  "action-state": "var(--knowledge)"
};
const FLOW_ORDER_EDGE_TYPES = new Set(["precedes"]);
const FLOW_TASK_NODE_TYPES = new Set(["Step", "Action", "Verification"]);
const RELATION_FAMILIES = {
  temporal: new Set(["precedes"]),
  evidence: new Set(["supports", "refutes", "explains", "produces", "checks", "verified_by", "satisfies"]),
  gate: new Set(["approved_by", "guarded_by", "blocked_by", "modifies"]),
  execution: new Set(["uses", "invokes", "implemented_by", "targets"]),
  reference: new Set(["contains", "has_run"])
};

function fallbackSpatialMembership(node) {
  const controlTypes = new Set(["Run", "Step", "Goal", "AcceptanceCriterion", "Decision", "Approval", "Policy", "Verification"]);
  const actionTypes = new Set(["Actor", "Capability", "Agent", "Skill", "Tool", "Target", "Action"]);
  if (controlTypes.has(node.type)) return ["control"];
  if (actionTypes.has(node.type)) return ["action"];
  return ["state"];
}
function spatialCatalogNodes() {
  return graph.spatial && Array.isArray(graph.spatial.nodes) ? graph.spatial.nodes : graph.nodes;
}
function spatialCatalogRelations() {
  return graph.spatial && Array.isArray(graph.spatial.relations) ? graph.spatial.relations : graph.edges;
}
function canonicalMembership(node) {
  const spatialNode = spatialCatalogNodes().find(function (item) { return item.id === node.id; });
  const membership = spatialNode && (spatialNode.canonical_membership || spatialNode.membership);
  return Array.isArray(membership) && membership.length ? membership.filter(function (layer) { return ["state", "control", "action"].includes(layer); }).slice(0, 1) : fallbackSpatialMembership(node);
}
function spatialRunCandidates() {
  const result = [];
  const seen = new Set();
  const runtimeRuns = graph.runtime && Array.isArray(graph.runtime.runs) ? graph.runtime.runs : [];
  runtimeRuns.forEach(function (run) {
    const canonicalRun = nodeById.get(run.run_id);
    result.push(Object.assign({}, run, {
      run_label: canonicalRun ? localizedNodeLabel(canonicalRun) : run.run_label,
      first_sequence: canonicalRun ? canonicalRun.first_sequence : 0,
      has_runtime_overlay: true
    }));
    seen.add(run.run_id);
  });
  graph.nodes.filter(function (node) { return node.type === "Run" && !seen.has(node.id); }).slice().sort(function (left, right) {
    return (right.first_sequence || 0) - (left.first_sequence || 0) || left.id.localeCompare(right.id);
  }).forEach(function (node) {
    result.push({run_id: node.id, run_label: localizedNodeLabel(node), status: node.attrs && node.attrs.status, case_state: rootState(), first_sequence: node.first_sequence || 0, has_runtime_overlay: false});
  });
  return result.sort(function (left, right) {
    return (right.first_sequence || 0) - (left.first_sequence || 0) || left.run_id.localeCompare(right.run_id);
  });
}
function selectedRuntimeSnapshot() {
  const runs = spatialRunCandidates();
  if (!runs.length) return null;
  const selected = document.getElementById("spatialRunFilter").value;
  if (selected) return runs.find(function (run) { return run.run_id === selected; }) || null;
  return runs[0];
}
function selectedReplayRun(snapshot) {
  const runs = graph.replay && Array.isArray(graph.replay.runs) ? graph.replay.runs : [];
  if (!snapshot || !snapshot.run_id) return null;
  return runs.find(function (run) { return run.run_id === snapshot.run_id; }) || null;
}
function ledgerReplayTrack(snapshot) {
  const run = selectedReplayRun(snapshot);
  const track = run && (run.ledger || run.actual);
  return track && typeof track.track_kind === "string" && track.track_kind.endsWith("-ledger") ? track : null;
}
function observedReplayTrack(snapshot) {
  const run = selectedReplayRun(snapshot);
  const track = run && (run.observed || (run.actual && typeof run.actual.track_kind === "string" && run.actual.track_kind.startsWith("execution-") ? run.actual : null));
  return track && typeof track.track_kind === "string" && track.track_kind.startsWith("execution-") ? track : null;
}
function hasObservedExecutionTrack(snapshot) {
  const track = observedReplayTrack(snapshot);
  return Boolean(track && track.status === "available");
}
function selectedReplayTrack(snapshot) {
  const run = selectedReplayRun(snapshot);
  if (!run) return null;
  if (replayMode === "candidate") return run.retrospective;
  if (replayMode === "observed") return observedReplayTrack(snapshot);
  if (replayMode === "ledger") return ledgerReplayTrack(snapshot);
  return null;
}
function replayItems(snapshot) {
  const track = selectedReplayTrack(snapshot);
  if (!track || (track.status !== "available" && !(replayMode === "candidate" && track.status === "gated"))) return [];
  return replayMode === "candidate" ? (track.steps || []) : (track.frames || []);
}
function replayCursorValue(snapshot) {
  const items = replayItems(snapshot);
  const maximum = Math.max(0, items.length - 1);
  replayCursors[replayMode] = Math.max(0, Math.min(maximum, replayCursors[replayMode] || 0));
  return replayCursors[replayMode];
}
function replayBoundaryText(track) {
  if (replayMode === "plan") return message("replayPlanBoundary");
  if (replayMode === "observed" && !track) return message("replayObservedUnavailable");
  if (track && replayMode === "candidate" && track.status === "gated") {
    const codes = (track.gate_blocker_codes || []).join(", ");
    return message("replayRecommendationGated") + (codes ? " [" + codes + "]" : "");
  }
  if (!track || track.status !== "available") return message("replayUnavailable");
  if (replayMode === "candidate") return message("replayRecommendationBoundary");
  if (replayMode === "observed") return track.boundary || message("replayObservedBoundary");
  if (track.track_kind === "synthetic-ledger") return message("replaySynthetic");
  if (track.track_kind === "reconstructed-ledger") return message("replayReconstructed");
  if (track.track_kind === "live-ledger") return message("replayLive");
  return track.boundary || message("replayVisualOnly");
}
function replayPlanModel(snapshot) {
  const runtimeMap = runtimeEntryMap(snapshot);
  const nodes = flowTaskNodes(caseContextNodes(snapshot), snapshot, runtimeMap);
  const nodeIds = new Set(nodes.map(function (node) { return node.id; }));
  const edges = spatialCatalogRelations().filter(function (relation) {
    return relation.type === "precedes" && nodeIds.has(relation.from) && nodeIds.has(relation.to);
  });
  const ranks = explicitFlowRanks(nodes).rank;
  return {nodes: nodes, edges: edges, nodeIds: nodeIds, edgeIds: new Set(edges.map(function (edge) { return edge.id; })), ranks: ranks, runtimeMap: runtimeMap};
}
function frameMapsToPlan(frame, snapshot) {
  if (!frame) return false;
  const plan = replayPlanModel(snapshot);
  if (frame.edge_id && plan.edgeIds.has(frame.edge_id)) return true;
  return (frame.subject_ids || []).some(function (id) { return plan.nodeIds.has(id); });
}
function replayPlayable(snapshot) {
  if (replayMode === "plan") return false;
  const track = selectedReplayTrack(snapshot);
  if (!track || track.status !== "available") return false;
  if (replayMode === "observed" && !hasObservedExecutionTrack(snapshot)) return false;
  return replayItems(snapshot).length > 0;
}
function replayVisualState(snapshot) {
  const empty = {active: false, focusGraph: false, mode: replayMode, currentNodeIds: new Set(), currentEdgeIds: new Set(), pastNodeIds: new Set(), pastEdgeIds: new Set(), routeNodeIds: new Set(), routeEdgeIds: new Set(), nodeStatuses: new Map()};
  const run = selectedReplayRun(snapshot);
  const track = selectedReplayTrack(snapshot);
  const items = replayItems(snapshot);
  if (!run || !track || !items.length) return empty;
  const cursor = replayCursorValue(snapshot);
  if (replayMode === "ledger" || replayMode === "observed") {
    const frame = items[cursor];
    const currentNodeIds = new Set(frame.subject_ids || []);
    const currentEdgeIds = new Set(frame.edge_id ? [frame.edge_id] : []);
    const pastNodeIds = new Set();
    const pastEdgeIds = new Set();
    const routeNodeIds = new Set();
    const routeEdgeIds = new Set();
    const nodeStatuses = new Map();
    items.forEach(function (item) {
      (item.subject_ids || []).forEach(function (id) { if (nodeById.has(id)) routeNodeIds.add(id); });
      if (item.edge_id) routeEdgeIds.add(item.edge_id);
    });
    items.slice(0, cursor + 1).forEach(function (item) {
      (item.subject_ids || []).forEach(function (id) { if (nodeById.has(id)) pastNodeIds.add(id); });
      if (item.edge_id) pastEdgeIds.add(item.edge_id);
      const statusId = item.node_id || ((item.kind === "state.changed" && item.subject_ids) ? item.subject_ids[0] : null);
      if (statusId && item.to_status != null) nodeStatuses.set(statusId, item.to_status);
    });
    return {active: true, focusGraph: frameMapsToPlan(frame, snapshot), mode: replayMode, sequence: frame.sequence, frame: frame, currentNodeIds: currentNodeIds, currentEdgeIds: currentEdgeIds, pastNodeIds: pastNodeIds, pastEdgeIds: pastEdgeIds, routeNodeIds: routeNodeIds, routeEdgeIds: routeEdgeIds, nodeStatuses: nodeStatuses};
  }
  const routeNodeIds = new Set(items.map(function (item) { return item.node_id; }));
  const routeEdgeIds = new Set((track.edges || []).map(function (edge) { return edge.edge_id; }));
  const pastNodeIds = new Set(items.slice(0, cursor + 1).map(function (item) { return item.node_id; }));
  const currentNodeIds = new Set([items[cursor].node_id]);
  const indexByNode = new Map(items.map(function (item, index) { return [item.node_id, index]; }));
  const pastEdgeIds = new Set((track.edges || []).filter(function (edge) { return (indexByNode.get(edge.to) || 0) <= cursor; }).map(function (edge) { return edge.edge_id; }));
  const currentEdgeIds = new Set((track.edges || []).filter(function (edge) { return edge.to === items[cursor].node_id; }).map(function (edge) { return edge.edge_id; }));
  return {active: true, focusGraph: true, mode: replayMode, step: items[cursor], currentNodeIds: currentNodeIds, currentEdgeIds: currentEdgeIds, pastNodeIds: pastNodeIds, pastEdgeIds: pastEdgeIds, routeNodeIds: routeNodeIds, routeEdgeIds: routeEdgeIds, nodeStatuses: new Map()};
}
function replayNodeClass(node, state) {
  if (!state.active || !state.focusGraph) return "";
  if (state.currentNodeIds.has(node.id)) return " replay-current";
  if (state.mode === "ledger" || state.mode === "observed") {
    if (state.pastNodeIds.has(node.id)) return " replay-past";
    return state.routeNodeIds.has(node.id) ? " replay-future" : " replay-unrelated";
  }
  if (!state.routeNodeIds.has(node.id)) return " replay-unrelated";
  return state.pastNodeIds.has(node.id) ? " replay-past" : " replay-future";
}
function replayEdgeClass(relation, state) {
  if (!state.active || !state.focusGraph) return "";
  if (state.currentEdgeIds.has(relation.id)) return " replay-current";
  if (state.mode === "ledger" || state.mode === "observed") {
    if (state.pastEdgeIds.has(relation.id)) return " replay-past";
    return state.routeEdgeIds.has(relation.id) ? " replay-future" : " replay-unrelated";
  }
  if (!state.routeEdgeIds.has(relation.id)) return " replay-unrelated";
  return state.pastEdgeIds.has(relation.id) ? " replay-past" : " replay-future";
}
function stopReplayPlayback() {
  if (replayTimer !== null) window.clearInterval(replayTimer);
  replayTimer = null;
  const button = document.getElementById("replayPlay");
  if (button) {
    button.textContent = "▶";
    button.title = message("replayPlay");
    button.setAttribute("aria-label", message("replayPlay"));
  }
}
function setReplayCursor(value) {
  const snapshot = selectedRuntimeSnapshot();
  const items = replayItems(snapshot);
  replayCursors[replayMode] = Math.max(0, Math.min(Math.max(0, items.length - 1), Number(value) || 0));
  renderWorkspace();
}
function stepReplay(delta) {
  stopReplayPlayback();
  setReplayCursor(replayCursorValue(selectedRuntimeSnapshot()) + delta);
}
function toggleReplayPlayback() {
  if (replayTimer !== null) {
    stopReplayPlayback();
    return;
  }
  const snapshot = selectedRuntimeSnapshot();
  const items = replayItems(snapshot);
  if (!replayPlayable(snapshot) || items.length < 2) return;
  if (replayCursorValue(snapshot) >= items.length - 1) replayCursors[replayMode] = 0;
  const speed = Number(document.getElementById("replaySpeed").value) || 1;
  document.getElementById("replayPlay").textContent = "Ⅱ";
  document.getElementById("replayPlay").title = message("replayPause");
  document.getElementById("replayPlay").setAttribute("aria-label", message("replayPause"));
  replayTimer = window.setInterval(function () {
    const liveSnapshot = selectedRuntimeSnapshot();
    const liveItems = replayItems(liveSnapshot);
    const cursor = replayCursorValue(liveSnapshot);
    if (!liveItems.length || cursor >= liveItems.length - 1) {
      stopReplayPlayback();
      return;
    }
    replayCursors[replayMode] = cursor + 1;
    renderWorkspace();
  }, Math.max(120, Math.round(900 / speed)));
  renderWorkspace();
}
function appendReplayMeta(target, labelText, valueText) {
  const chip = createText("span", "replay-meta-chip", "");
  chip.append(createText("strong", "", labelText + " · "), document.createTextNode(valueText || "—"));
  target.appendChild(chip);
}
function appendReplayDetail(target, labelKey, valueText) {
  if (valueText == null || valueText === "") return;
  target.append(createText("div", "replay-detail-key", message(labelKey)), createText("div", "replay-detail-value", String(valueText)));
}
function replayTrackLabel(mode) {
  return message(mode === "ledger" ? "replayLedger" : mode === "plan" ? "replayPlan" : mode === "candidate" ? "replayCandidate" : "replayObserved");
}
function replayTrackState(mode, snapshot) {
  const run = selectedReplayRun(snapshot);
  const plan = replayPlanModel(snapshot);
  if (mode === "plan") return {available: plan.nodes.length > 0, text: message("replayPlanItems", {nodes: plan.nodes.length, edges: plan.edges.length})};
  if (mode === "candidate") {
    const track = run && run.retrospective;
    const count = track && Array.isArray(track.steps) ? track.steps.length : 0;
    const suffix = track && track.status === "gated" ? " · " + message("replayGatedShort") : "";
    return {available: Boolean(track && (track.status === "available" || track.status === "gated")), text: (count ? message("replayTrackItems", {count: count}) : message("replayUnavailableShort")) + suffix};
  }
  if (mode === "observed") {
    const track = observedReplayTrack(snapshot);
    const available = Boolean(track && track.status === "available");
    const count = available ? (track.frames || []).length : 0;
    return {available: available, text: available ? message("replayTrackItems", {count: count}) : message("replayUnavailableShort")};
  }
  const track = ledgerReplayTrack(snapshot);
  const available = Boolean(track && track.status === "available");
  return {available: available, text: available ? message("replayTrackItems", {count: (track.frames || []).length}) + " · " + (track.completeness || "") : message("replayUnavailableShort")};
}
function renderReplayPlanStrip(strip, details, snapshot) {
  const plan = replayPlanModel(snapshot);
  const ordered = plan.nodes.slice().sort(function (left, right) {
    return (plan.ranks.get(left.id) || 0) - (plan.ranks.get(right.id) || 0) || (left.first_sequence || 0) - (right.first_sequence || 0) || left.id.localeCompare(right.id);
  });
  if (!ordered.length) strip.appendChild(createText("div", "replay-empty", message("planNoTasks")));
  ordered.forEach(function (node) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "replay-frame";
    button.setAttribute("role", "option");
    button.dataset.nodeId = node.id;
    button.append(createText("span", "replay-frame-sequence", message("planLevel", {rank: (plan.ranks.get(node.id) || 0) + 1})), createText("span", "replay-frame-kind", localizedNodeLabel(node)), createText("span", "replay-frame-map", nodeTypeLabel(node.type)));
    button.addEventListener("click", function () { selectNode(node.id); });
    strip.appendChild(button);
  });
  appendReplayDetail(details, "replayDetailTrack", replayTrackLabel("plan"));
  appendReplayDetail(details, "replayAuthority", "explicit precedes");
  appendReplayDetail(details, "replayDetailPosition", message("replayPlanItems", {nodes: plan.nodes.length, edges: plan.edges.length}));
  appendReplayDetail(details, "replayDetailDependency", plan.edges.map(function (edge) { return edge.from + " → " + edge.to; }).join("\n") || message("planNoConstraints"));
}
function renderReplayItemStrip(strip, details, snapshot, items, cursor) {
  let selectedButton = null;
  items.forEach(function (item, index) {
    const frameMode = replayMode === "ledger" || replayMode === "observed";
    const node = frameMode ? null : nodeById.get(item.node_id);
    const mapped = frameMode ? frameMapsToPlan(item, snapshot) : true;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "replay-frame";
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(index === cursor));
    if (index === cursor) {
      button.setAttribute("aria-current", "step");
      selectedButton = button;
    }
    button.dataset.replayIndex = String(index);
    button.dataset.planMapped = String(mapped);
    button.append(
      createText("span", "replay-frame-sequence", frameMode ? "#" + item.sequence : (index + 1) + " / " + items.length),
      createText("span", "replay-frame-kind", frameMode ? eventKindLabel(item.kind) : (node ? localizedNodeLabel(node) : item.node_id)),
      createText("span", "replay-frame-map", frameMode ? message(mapped ? "replayMapped" : "replayNotMapped") : statusLabel(item.runtime_lane || item.status || "pending"))
    );
    button.addEventListener("click", function () { stopReplayPlayback(); setReplayCursor(index); });
    strip.appendChild(button);
  });
  if (selectedButton) window.requestAnimationFrame(function () {
    const desired = selectedButton.offsetLeft - strip.clientWidth / 2 + selectedButton.clientWidth / 2;
    strip.scrollLeft = Math.max(0, desired);
  });
  if (!items.length) {
    strip.appendChild(createText("div", "replay-empty", replayMode === "observed" ? message("replayObservedUnavailable") : message("replayUnavailable")));
    appendReplayDetail(details, "replayDetailTrack", replayTrackLabel(replayMode));
    appendReplayDetail(details, "replayAuthority", replayMode === "observed" ? "execution-* telemetry" : "—");
    appendReplayDetail(details, "replayDetailMapping", message("replayUnavailableShort"));
    return;
  }
  const current = items[cursor];
  appendReplayDetail(details, "replayDetailTrack", replayTrackLabel(replayMode));
  appendReplayDetail(details, "replayDetailPosition", (cursor + 1) + " / " + items.length);
  if (replayMode === "ledger" || replayMode === "observed") {
    const rawEvent = eventById.get(current.event_id);
    const transition = current.from_status != null || current.to_status != null ? statusLabel(current.from_status || "—") + " → " + statusLabel(current.to_status || "—") : "";
    const subjectLabels = (current.subject_ids || []).map(function (id) { const node = nodeById.get(id); return node ? localizedNodeLabel(node) + " [" + id + "]" : id; });
    appendReplayDetail(details, "replayDetailEvent", current.event_id + " · #" + current.sequence);
    appendReplayDetail(details, "replayDetailKind", eventKindLabel(current.kind) + (rawEvent ? " · " + eventDetail(rawEvent) : ""));
    appendReplayDetail(details, "replayDetailTime", current.occurred_at);
    appendReplayDetail(details, "replayDetailSubject", subjectLabels.join("\n"));
    appendReplayDetail(details, "replayDetailTransition", transition);
    appendReplayDetail(details, "replayDetailActor", current.actor ? actorLabel(current.actor.type) + ":" + current.actor.id : "");
    appendReplayDetail(details, "replayDetailCapture", modeLabel(current.capture_mode));
    appendReplayDetail(details, "replayDetailSources", (current.source_refs || []).join("\n") || message("replayNoSources"));
    appendReplayDetail(details, "replayDetailMapping", message(frameMapsToPlan(current, snapshot) ? "replayMapped" : "replayNotMapped"));
  } else {
    const node = nodeById.get(current.node_id);
    const blockers = (current.blockers || []).map(function (blocker) { return blocker.message || blocker.code || blocker.node_id; }).filter(Boolean);
    appendReplayDetail(details, "replayDetailNode", (node ? localizedNodeLabel(node) : current.node_id) + " [" + current.node_id + "]");
    appendReplayDetail(details, "replayDetailKind", nodeTypeLabel(current.node_type) + " · " + statusLabel(current.status || "pending"));
    appendReplayDetail(details, "replayDetailLane", statusLabel(current.runtime_lane || "—"));
    appendReplayDetail(details, "replayDetailBlockers", blockers.join("\n") || message("contextNoBlocker"));
    appendReplayDetail(details, "replayDetailPriority", current.priority);
    appendReplayDetail(details, "replayDetailOptimality", (selectedReplayTrack(snapshot) && selectedReplayTrack(snapshot).optimality) || "not_proven");
  }
}
function renderReplayHud(snapshot) {
  const track = selectedReplayTrack(snapshot);
  const items = replayItems(snapshot);
  const cursor = replayCursorValue(snapshot);
  document.querySelectorAll("[data-replay-mode]").forEach(function (button) {
    const mode = button.dataset.replayMode;
    const active = mode === replayMode;
    const state = replayTrackState(mode, snapshot);
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.dataset.trackAvailability = state.available ? "available" : "unavailable";
    const stateTarget = button.querySelector("[data-replay-track-state]");
    if (stateTarget) stateTarget.textContent = state.text;
  });
  const meta = document.getElementById("replayMeta");
  clearElement(meta);
  if (replayMode === "plan") {
    const plan = replayPlanModel(snapshot);
    appendReplayMeta(meta, message("replayAuthority"), "explicit precedes");
    appendReplayMeta(meta, message("replayItemCount"), message("replayPlanItems", {nodes: plan.nodes.length, edges: plan.edges.length}));
  } else if (track) {
    appendReplayMeta(meta, message("replayAuthority"), track.order_authority || track.basis || (replayMode === "observed" ? "execution telemetry" : "—"));
    appendReplayMeta(meta, message("replayTrackKind"), track.track_kind || track.shape || replayMode);
    appendReplayMeta(meta, message("replayCompleteness"), track.completeness || track.optimality || "—");
    appendReplayMeta(meta, message("replayItemCount"), String(items.length));
  } else {
    appendReplayMeta(meta, message("replayAuthority"), replayMode === "observed" ? "execution-* telemetry" : "—");
    appendReplayMeta(meta, message("replayItemCount"), "0");
  }
  const range = document.getElementById("replayRange");
  range.max = String(Math.max(0, items.length - 1));
  range.value = String(cursor);
  const playable = replayPlayable(snapshot);
  range.disabled = !playable;
  document.getElementById("replayCounter").textContent = replayMode === "plan" ? "—" : items.length ? (cursor + 1) + " / " + items.length : "0 / 0";
  document.getElementById("replayBoundary").textContent = replayBoundaryText(track) + " " + message("replayVisualOnly");
  const strip = document.getElementById("replayStrip");
  const details = document.getElementById("replayDetails");
  clearElement(strip);
  clearElement(details);
  if (replayMode === "plan") renderReplayPlanStrip(strip, details, snapshot);
  else renderReplayItemStrip(strip, details, snapshot, items, cursor);
  ["replayReset", "replayPrev", "replayPlay", "replayNext", "replayLast"].forEach(function (id) { document.getElementById(id).disabled = !playable; });
  document.getElementById("replaySpeed").disabled = !playable;
}
function runtimeEntryMap(snapshot) {
  const result = new Map();
  if (!snapshot) return result;
  ["ready", "running", "blocked", "completed", "failed"].forEach(function (lane) {
    (snapshot[lane] || []).forEach(function (entry) {
      const id = entry.id || entry.node_id;
      if (id && !result.has(id)) result.set(id, Object.assign({}, entry, {runtime_lane: lane}));
    });
  });
  return result;
}
function effectiveMembership(node, runtimeMap) {
  return canonicalMembership(node).slice(0, 1);
}
function caseContextNodes(snapshot) {
  if (!snapshot || !snapshot.run_id) return graph.nodes.slice();
  const ids = new Set([graph.root_id, snapshot.run_id].filter(Boolean));
  graph.edges.forEach(function (edge) {
    if (edge.from === snapshot.run_id && edge.type === "contains") ids.add(edge.to);
  });
  return graph.nodes.filter(function (node) { return ids.has(node.id); });
}
function contextNodeButton(node, className, text) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.dataset.contextNodeId = node.id;
  button.textContent = text;
  button.title = node.id;
  button.addEventListener("click", function () { selectNode(node.id); });
  return button;
}
function renderCaseContext(snapshot, runtimeMap) {
  const target = document.getElementById("caseContext");
  clearElement(target);
  const caseNode = nodeById.get(graph.root_id) || null;
  const runNode = snapshot && nodeById.get(snapshot.run_id);
  const meta = document.createElement("div");
  meta.className = "case-context-meta";
  if (graph.stats && graph.stats.capture_modes && graph.stats.capture_modes.synthetic) {
    meta.appendChild(createText("span", "case-context-badge synthetic", message("syntheticBadge")));
  }
  const maximumSequence = events.reduce(function (maximum, event) { return Math.max(maximum, Number(event.sequence) || 0); }, 0);
  meta.appendChild(createText("span", "case-context-badge", message("snapshotBadge", {sequence: maximumSequence})));
  if (caseNode) meta.appendChild(contextNodeButton(caseNode, "case-context-link", message("contextCase") + " · " + localizedNodeLabel(caseNode)));
  if (runNode) meta.appendChild(contextNodeButton(runNode, "case-context-link", message("contextRun") + " · " + localizedNodeLabel(runNode)));
  const hasExecutionTelemetry = hasObservedExecutionTrack(snapshot);
  meta.appendChild(createText("span", "case-context-badge boundary", message(hasExecutionTelemetry ? "executionTelemetryPresent" : "executionTelemetryMissing")));
  target.appendChild(meta);
}
function relationBetween(fromId, toId, allowedTypes) {
  return spatialCatalogRelations().find(function (relation) {
    return relation.from === fromId && relation.to === toId && (!allowedTypes || allowedTypes.includes(relation.type));
  }) || null;
}
function semanticCanonicalCard(node, layer, column, runtimeMap) {
  if (!node) return null;
  const button = document.createElement("button");
  button.type = "button";
  const runtimeEntry = runtimeMap && runtimeMap.get(node.id);
  button.className = "semantic-card" + (runtimeEntry ? " runtime-instance " + runtimeEntry.runtime_lane : "");
  button.dataset.entityKind = "canonical";
  button.dataset.nodeId = node.id;
  button.style.gridColumn = String(column + 1);
  button.style.setProperty("--card-color", SPATIAL_LAYER_COLORS[layer] || "var(--accent)");
  const status = runtimeEntry ? statusLabel(runtimeEntry.runtime_lane) : node.attrs && node.attrs.status ? statusLabel(node.attrs.status) : "canonical";
  const kind = createText("div", "semantic-card-kind", "");
  kind.append(createText("span", "", nodeTypeLabel(node.type)), createText("span", "", status));
  button.append(kind, createText("div", "semantic-card-title", localizedNodeLabel(node)));
  const details = [node.id];
  if (runtimeEntry) {
    button.dataset.traceStatus = runtimeEntry.runtime_lane;
    details.push("Trace · " + statusLabel(runtimeEntry.runtime_lane));
  }
  button.appendChild(createText("div", "semantic-card-detail", details.join(" · ")));
  button.title = node.id;
  button.addEventListener("click", function () { selectNode(node.id); });
  return button;
}
function appendWorkspaceBoundary(target, textValue) {
  clearElement(target);
  target.append(createText("strong", "", currentLocale === "zh-CN" ? "边界" : "Boundary"), createText("span", "", textValue));
}
function overviewElementByNode(stack, nodeId) {
  return Array.from(stack.querySelectorAll("[data-entity-kind='canonical']")).find(function (element) { return element.dataset.nodeId === nodeId; }) || null;
}
function renderOverviewRelations() {
  const stack = document.getElementById("semanticStack");
  const svg = document.getElementById("overviewRelations");
  if (!stack || !svg || workspaceMode !== "overview") return;
  clearElement(svg);
  const stackRect = stack.getBoundingClientRect();
  const width = Math.max(stack.scrollWidth, Math.round(stackRect.width));
  const height = Math.max(stack.scrollHeight, Math.round(stackRect.height));
  svg.setAttribute("viewBox", "0 0 " + width + " " + height);
  const defs = svgElement("defs");
  const marker = svgElement("marker", {id: "overviewArrow", markerWidth: 8, markerHeight: 8, refX: 7, refY: 4, orient: "auto", markerUnits: "userSpaceOnUse", viewBox: "0 0 8 8"});
  marker.appendChild(svgElement("path", {d: "M 0 0 L 8 4 L 0 8 z", fill: "context-stroke"}));
  defs.appendChild(marker);
  svg.appendChild(defs);
  const planned = spatialCatalogRelations().filter(function (relation) {
    return ["targets", "supports", "explains", "implemented_by", "precedes", "produces", "approved_by", "guarded_by", "modifies", "uses", "invokes", "checks", "verified_by"].includes(relation.type);
  });
  function relativeBox(element) {
    const box = element.getBoundingClientRect();
    return {left: box.left - stackRect.left + stack.scrollLeft, right: box.right - stackRect.left + stack.scrollLeft, top: box.top - stackRect.top, bottom: box.bottom - stackRect.top, cx: (box.left + box.right) / 2 - stackRect.left + stack.scrollLeft, cy: (box.top + box.bottom) / 2 - stackRect.top};
  }
  function appendPath(fromElement, toElement, family, labelText, edgeId, mappingIndex) {
    if (!fromElement || !toElement) return;
    const from = relativeBox(fromElement);
    const to = relativeBox(toElement);
    const sameLayer = fromElement.closest("[data-semantic-layer]") === toElement.closest("[data-semantic-layer]");
    let pathText;
    let labelX;
    let labelY;
    if (sameLayer && family === "temporal") {
      const channel = Math.max(from.bottom, to.bottom) + 11 + (mappingIndex || 0) * 5;
      pathText = "M " + from.right + " " + from.cy + " L " + (from.right + 10) + " " + from.cy + " L " + (from.right + 10) + " " + channel + " L " + (to.left - 10) + " " + channel + " L " + (to.left - 10) + " " + to.cy + " L " + to.left + " " + to.cy;
      labelX = (from.right + to.left) / 2;
      labelY = channel - 4;
    } else if (sameLayer) {
      const midX = (from.right + to.left) / 2;
      pathText = "M " + from.right + " " + from.cy + " L " + midX + " " + from.cy + " L " + midX + " " + to.cy + " L " + to.left + " " + to.cy;
      labelX = midX;
      labelY = (from.cy + to.cy) / 2 - 5;
    } else {
      const downward = to.cy > from.cy;
      const startY = downward ? from.bottom : from.top;
      const endY = downward ? to.top : to.bottom;
      const midY = (startY + endY) / 2;
      pathText = "M " + from.cx + " " + startY + " L " + from.cx + " " + midY + " L " + to.cx + " " + midY + " L " + to.cx + " " + endY;
      labelX = (from.cx + to.cx) / 2 + 5;
      labelY = midY - 4;
    }
    const attrs = {class: "overview-relation " + family, d: pathText, "data-edge-family": family};
    if (edgeId) attrs["data-edge-id"] = edgeId;
    if (family !== "mapping") attrs["marker-end"] = "url(#overviewArrow)";
    svg.appendChild(svgElement("path", attrs));
    const labelColor = family === "mapping" ? "var(--muted)" : family === "temporal" ? "var(--execute)" : family === "evidence" ? "var(--reason)" : "var(--evidence)";
    const label = svgElement("text", {class: "overview-relation-label", x: labelX, y: labelY, fill: labelColor, "text-anchor": "middle"});
    label.textContent = labelText;
    svg.appendChild(label);
  }
  planned.forEach(function (relation, index) {
    appendPath(overviewElementByNode(stack, relation.from), overviewElementByNode(stack, relation.to), relationFamily(relation.type), edgeTypeLabel(relation.type), relation.id, index);
  });
}
function renderWorkspaceOverview(snapshot, runtimeMap) {
  const nodes = caseContextNodes(snapshot);
  const stateTrack = document.getElementById("stateTrack");
  const controlTrack = document.getElementById("controlTrack");
  const actionTrack = document.getElementById("actionTrack");
  [stateTrack, controlTrack, actionTrack].forEach(clearElement);
  const tracks = {state: stateTrack, control: controlTrack, action: actionTrack};
  const counters = {state: 0, control: 0, action: 0};
  nodes.slice().sort(function (left, right) {
    return (left.first_sequence || 0) - (right.first_sequence || 0) || left.id.localeCompare(right.id);
  }).forEach(function (node) {
    const layer = canonicalMembership(node)[0] || "state";
    const card = semanticCanonicalCard(node, layer, counters[layer] % 5, runtimeMap);
    counters[layer] += 1;
    if (card && tracks[layer]) tracks[layer].appendChild(card);
  });
  if (!nodes.some(function (node) { return canonicalMembership(node)[0] === "action"; })) {
    const gap = createText("div", "telemetry-gap", message("runtimeGap"));
    gap.dataset.telemetryGap = "action-feedback";
    actionTrack.appendChild(gap);
  }
  const observed = hasObservedExecutionTrack(snapshot);
  document.getElementById("semanticStack").dataset.telemetry = observed ? "observed" : "missing";
  appendWorkspaceBoundary(document.getElementById("overviewBoundary"), message(observed ? "overviewTelemetryPresent" : "overviewTelemetryMissing"));
  window.requestAnimationFrame(renderOverviewRelations);
}
function renderRuntimeWorkspace(snapshot, runtimeMap) {
  const observed = hasObservedExecutionTrack(snapshot);
  appendWorkspaceBoundary(document.getElementById("runBoundary"), message(observed ? "runBoundaryPresent" : "runBoundaryMissing"));
  const lanesTarget = document.getElementById("runLanes");
  clearElement(lanesTarget);
  const emptyLanes = [];
  [["completed", "laneCompleted"], ["running", "laneRunning"], ["ready", "laneReady"], ["blocked", "laneBlocked"], ["failed", "laneFailed"]].forEach(function (laneDef) {
    const entries = snapshot && Array.isArray(snapshot[laneDef[0]]) ? snapshot[laneDef[0]] : [];
    if (!entries.length) {
      emptyLanes.push(message(laneDef[1]));
      return;
    }
    const lane = document.createElement("section");
    lane.className = "run-lane";
    lane.dataset.runtimeLane = laneDef[0];
    const head = createText("div", "run-lane-head", "");
    head.append(createText("span", "", message(laneDef[1])), createText("span", "run-lane-count", String(entries.length)));
    const list = createText("div", "run-lane-list", "");
    entries.forEach(function (entry) { list.appendChild(runtimeInstanceCard(snapshot, Object.assign({}, entry, {runtime_lane: laneDef[0]}), null)); });
    lane.append(head, list);
    lanesTarget.appendChild(lane);
  });
  if (emptyLanes.length) lanesTarget.appendChild(createText("div", "run-empty-summary", message("runZeroStates", {states: emptyLanes.join(" · ")})));
}
function appendReviewTrack(target, kind, name, detail, status) {
  const row = document.createElement("section");
  row.className = "track-row";
  row.dataset.trackKind = kind;
  row.append(createText("div", "track-name", name), createText("div", "track-detail", detail), createText("span", "track-status " + status, message(status === "available" ? "trackAvailable" : status === "gated" ? "trackGated" : "trackUnavailable")));
  target.appendChild(row);
}
function renderReviewWorkspace(snapshot, runtimeMap) {
  appendWorkspaceBoundary(document.getElementById("reviewBoundary"), message("reviewBoundary"));
  const target = document.getElementById("reviewTracks");
  clearElement(target);
  const run = selectedReplayRun(snapshot);
  const ledger = ledgerReplayTrack(snapshot);
  const candidate = run && run.retrospective;
  const plan = replayPlanModel(snapshot);
  const ledgerStatus = ledger && ledger.status === "available" ? "available" : "unavailable";
  const candidateStatus = candidate && candidate.status === "available" ? "available" : candidate && candidate.status === "gated" ? "gated" : "unavailable";
  const runtimeState = ["completed", "running", "ready", "blocked", "failed"].map(function (lane) {
    const count = snapshot && Array.isArray(snapshot[lane]) ? snapshot[lane].length : 0;
    return count ? statusLabel(lane) + " " + count : null;
  }).filter(Boolean).join(" · ") || "—";
  appendReviewTrack(target, "record-completeness", message("reviewRecordTitle"), message("reviewRecordDetail", {count: ledger && ledger.event_count != null ? ledger.event_count : 0, capture: ledger ? (ledger.track_kind || ledger.completeness || "—") : "—"}), ledgerStatus);
  appendReviewTrack(target, "plan-state", message("reviewStateTitle"), message("reviewStateDetail", {nodes: plan.nodes.length, edges: plan.edges.length, runtime: runtimeState, candidate: message(candidateStatus === "available" ? "trackAvailable" : candidateStatus === "gated" ? "trackGated" : "trackUnavailable")}), plan.nodes.length ? candidateStatus : "unavailable");
  appendReviewTrack(target, "execution-gap", message("reviewGapTitle"), message(hasObservedExecutionTrack(snapshot) ? "reviewGapPresent" : "reviewGapMissing"), hasObservedExecutionTrack(snapshot) ? "available" : "unavailable");
}
function appendPlanSummaryChip(target, labelText, valueText, state) {
  const chip = createText("span", "plan-summary-chip" + (state ? " " + state : ""), "");
  chip.append(createText("span", "", labelText), createText("strong", "", String(valueText)));
  target.appendChild(chip);
}
function renderPlanWorkbench(snapshot, runtimeMap) {
  const plan = replayPlanModel(snapshot);
  const summary = document.getElementById("planSummary");
  clearElement(summary);
  const runtimeCounts = ["completed", "running", "ready", "blocked", "failed"].map(function (lane) {
    return statusLabel(lane) + " " + (snapshot && Array.isArray(snapshot[lane]) ? snapshot[lane].length : 0);
  }).join(" · ");
  appendPlanSummaryChip(summary, message("planRevision"), graph.replay && graph.replay.protocol_version ? graph.replay.protocol_version : "snapshot");
  appendPlanSummaryChip(summary, message("planNodes"), plan.nodes.length);
  appendPlanSummaryChip(summary, message("planConstraints"), plan.edges.length);
  appendPlanSummaryChip(summary, message("planFrontier"), runtimeCounts);
  appendPlanSummaryChip(summary, message(hasObservedExecutionTrack(snapshot) ? "planObservedPresent" : "planObservedMissing"), hasObservedExecutionTrack(snapshot) ? "execution-*" : "—", hasObservedExecutionTrack(snapshot) ? "available" : "unavailable");

  const inspector = document.getElementById("planInspector");
  clearElement(inspector);
  const head = createText("div", "plan-inspector-head", "");
  head.append(createText("div", "plan-inspector-title", message("planInspectorTitle")), createText("div", "plan-inspector-note", message("planInspectorNote")));
  inspector.appendChild(head);
  function appendFocusSection(titleKey, entry, emptyKey, defaultLane) {
    const section = createText("section", "plan-inspector-section", "");
    section.appendChild(createText("div", "plan-inspector-kicker", message(titleKey)));
    if (!entry) {
      section.appendChild(createText("div", "run-lane-empty", message(emptyKey)));
      inspector.appendChild(section);
      return;
    }
    const sourceId = entry.id || entry.node_id;
    const node = nodeById.get(sourceId);
    const blockers = Array.isArray(entry.blockers) ? entry.blockers.map(function (blocker) { return blocker.message || blocker.code || blocker.node_id; }).filter(Boolean) : [];
    const button = document.createElement("button");
    button.type = "button";
    button.className = "plan-frontier-item";
    button.dataset.nodeId = sourceId;
    const lane = entry.runtime_lane || defaultLane || entry.status || "";
    const top = createText("div", "plan-frontier-top", "");
    top.append(createText("span", "", node ? nodeTypeLabel(node.type) : sourceId), createText("span", "", statusLabel(lane)));
    button.append(top, createText("div", "plan-frontier-label", node ? localizedNodeLabel(node) : (entry.label || sourceId)), createText("div", "plan-frontier-detail", blockers.join(" · ") || entry.executor || statusLabel(lane)));
    button.addEventListener("click", function () { if (node) selectNode(node.id); });
    section.appendChild(button);
    inspector.appendChild(section);
  }
  const runningEntry = snapshot && (snapshot.running || [])[0];
  const activeEntry = runningEntry || (snapshot && (snapshot.ready || [])[0]);
  const blockedEntry = snapshot && (snapshot.blocked || [])[0];
  appendFocusSection("planActiveTitle", activeEntry, "planNoActive", runningEntry ? "running" : "ready");
  appendFocusSection("planBlockerTitle", blockedEntry, "planNoBlocker", "blocked");
}
function evidenceChainCard(node) {
  const card = semanticCanonicalCard(node, node ? (canonicalMembership(node)[0] || "state") : "control", 0);
  if (card) card.style.gridColumn = "";
  return card;
}
function renderEvidenceChain(target, titleKey, nodes, suffix) {
  const existing = nodes.filter(Boolean);
  if (!existing.length) return;
  const section = document.createElement("section");
  section.className = "evidence-chain";
  section.appendChild(createText("div", "evidence-chain-title", message(titleKey) + (suffix || "")));
  const track = createText("div", "evidence-chain-track", "");
  existing.forEach(function (node, index) {
    if (index) {
      const relation = relationBetween(existing[index - 1].id, node.id, ["supports", "explains", "implemented_by", "checks"]);
      if (relation) {
        const connector = createText("div", "chain-relation " + relationFamily(relation.type), "");
        connector.dataset.edgeId = relation.id;
        connector.append(createText("span", "chain-relation-line", ""), createText("span", "", edgeTypeLabel(relation.type)));
        track.appendChild(connector);
      }
    }
    const card = evidenceChainCard(node);
    if (card) track.appendChild(card);
  });
  section.appendChild(track);
  target.appendChild(section);
}
function explicitRelationPaths(nodes, allowedTypes) {
  const nodeIds = new Set(nodes.map(function (node) { return node.id; }));
  const relations = spatialCatalogRelations().filter(function (relation) {
    return allowedTypes.includes(relation.type) && nodeIds.has(relation.from) && nodeIds.has(relation.to);
  });
  const outgoing = new Map();
  const incoming = new Set();
  relations.forEach(function (relation) {
    if (!outgoing.has(relation.from)) outgoing.set(relation.from, []);
    outgoing.get(relation.from).push(relation);
    incoming.add(relation.to);
  });
  const starts = Array.from(outgoing.keys()).filter(function (id) { return !incoming.has(id); });
  const coveredEdges = new Set();
  const pathKeys = new Set();
  const paths = [];
  function visit(id, pathIds, usedEdges) {
    const next = (outgoing.get(id) || []).filter(function (relation) { return !usedEdges.has(relation.id) && !pathIds.includes(relation.to); });
    if (!next.length) {
      if (pathIds.length > 1) {
        const key = pathIds.join("\u0000");
        if (!pathKeys.has(key)) {
          pathKeys.add(key);
          paths.push(pathIds.map(function (nodeId) { return nodeById.get(nodeId); }).filter(Boolean));
        }
      }
      return;
    }
    next.forEach(function (relation) {
      coveredEdges.add(relation.id);
      const nextUsed = new Set(usedEdges);
      nextUsed.add(relation.id);
      visit(relation.to, pathIds.concat([relation.to]), nextUsed);
    });
  }
  starts.forEach(function (id) { visit(id, [id], new Set()); });
  relations.forEach(function (relation) {
    if (!coveredEdges.has(relation.id)) visit(relation.from, [relation.from], new Set());
  });
  return paths;
}
function renderEvidenceWorkspace(snapshot) {
  const nodes = caseContextNodes(snapshot);
  const target = document.getElementById("evidenceChains");
  clearElement(target);
  const groups = [
    ["evidenceReasoningChain", explicitRelationPaths(nodes, ["supports", "explains", "implemented_by"])],
    ["evidenceVerificationChain", explicitRelationPaths(nodes, ["checks"])]
  ];
  groups.forEach(function (group) {
    group[1].forEach(function (path, index) { renderEvidenceChain(target, group[0], path, group[1].length > 1 ? " · " + (index + 1) : ""); });
  });
  if (!target.childElementCount) target.appendChild(createText("div", "run-lane-empty", message("evidenceNoPaths")));
}
function spatialNodeMatches(node, query) {
  if (!query) return true;
  const text = JSON.stringify(node) + " " + localizedNodeLabel(node) + " " + nodeTypeLabel(node.type);
  return text.toLowerCase().includes(query);
}
function selectedRunScope(snapshot) {
  const query = document.getElementById("search").value.trim().toLowerCase();
  const allNodes = graph.nodes.slice();
  const seeds = new Set();
  if (graph.root_id) seeds.add(graph.root_id);
  if (snapshot && snapshot.run_id) seeds.add(snapshot.run_id);
  if (snapshot) runtimeEntryMap(snapshot).forEach(function (_, id) { seeds.add(id); });
  if (snapshot) {
    graph.edges.forEach(function (edge) {
      if (edge.from === snapshot.run_id && edge.type === "contains") seeds.add(edge.to);
    });
  }
  if (!snapshot) {
    allNodes.forEach(function (node) {
      if (!node.id.includes(":ledger:") && spatialCoreTypes.has(node.type)) seeds.add(node.id);
    });
  }
  const before = new Set(seeds);
  graph.edges.forEach(function (edge) {
    if (!primaryEdgeTypes.has(edge.type) && edge.type !== "contains") return;
    const expandsFrom = before.has(edge.from) && edge.from !== graph.root_id;
    const expandsTo = before.has(edge.to) && edge.to !== graph.root_id;
    if (expandsFrom) seeds.add(edge.to);
    if (expandsTo) seeds.add(edge.from);
  });
  if (query) {
    const matches = new Set(allNodes.filter(function (node) { return spatialNodeMatches(node, query); }).map(function (node) { return node.id; }));
    const expanded = new Set(matches);
    graph.edges.forEach(function (edge) {
      if (matches.has(edge.from)) expanded.add(edge.to);
      if (matches.has(edge.to)) expanded.add(edge.from);
    });
    seeds.clear();
    expanded.forEach(function (id) { seeds.add(id); });
    if (graph.root_id) seeds.add(graph.root_id);
  }
  if (selectedId) adjacentIds(selectedId).forEach(function (id) { seeds.add(id); });
  const ordered = allNodes.filter(function (node) { return seeds.has(node.id); });
  const displayLimit = snapshot && snapshot.has_runtime_overlay ? 22 : 18;
  if (ordered.length <= displayLimit) return ordered;
  const mandatory = new Set([graph.root_id, selectedId, snapshot && snapshot.run_id].filter(Boolean));
  if (snapshot && snapshot.has_runtime_overlay) runtimeEntryMap(snapshot).forEach(function (_, id) { mandatory.add(id); });
  if (snapshot && snapshot.has_runtime_overlay) graph.edges.forEach(function (edge) { if (edge.from === snapshot.run_id && edge.type === "contains") mandatory.add(edge.to); });
  const kept = ordered.filter(function (node) { return mandatory.has(node.id); });
  ordered.forEach(function (node) { if (kept.length < displayLimit && !mandatory.has(node.id)) kept.push(node); });
  return kept;
}
function positiveGridPositions(count, size) {
  if (!count) return [];
  const columns = Math.max(1, Math.ceil(Math.sqrt(count * 1.45)));
  const rows = Math.ceil(count / columns);
  const usable = Math.max(1, size - ORTHOGONAL_INSET * 2);
  return Array.from({length: count}, function (_, index) {
    const column = index % columns;
    const row = Math.floor(index / columns);
    return {
      u: columns === 1 ? size / 2 : ORTHOGONAL_INSET + column * usable / (columns - 1),
      v: rows === 1 ? size / 2 : ORTHOGONAL_INSET + row * usable / (rows - 1)
    };
  });
}
function buildOrthogonalInstances(nodes, runtimeMap) {
  const buckets = {state: [], control: [], action: []};
  nodes.forEach(function (node) {
    const layer = effectiveMembership(node, runtimeMap)[0] || "state";
    buckets[layer].push(node);
  });
  const result = [];
  ["state", "control", "action"].forEach(function (layer) {
    buckets[layer].sort(function (left, right) {
      return (left.first_sequence || 0) - (right.first_sequence || 0) || left.id.localeCompare(right.id);
    });
    const positions = positiveGridPositions(buckets[layer].length, ORTHOGONAL_SIZE);
    buckets[layer].forEach(function (node, index) {
      const p = positions[index];
      const point = layer === "state" ? {x: p.u, y: p.v, z: 0}
        : layer === "control" ? {x: p.u, y: 0, z: p.v}
        : {x: 0, y: p.u, z: p.v};
      result.push({key: node.id + "::" + layer, sourceId: node.id, node: node, layers: [layer], displayLayer: layer, point: point});
    });
  });
  return result;
}
function relationFamily(type) {
  for (const entry of Object.entries(RELATION_FAMILIES)) {
    if (entry[1].has(type)) return entry[0];
  }
  return "reference";
}
function flowTaskNodes(nodes, snapshot, runtimeMap) {
  const byId = new Map(nodes.map(function (node) { return [node.id, node]; }));
  const run = selectedReplayRun(snapshot);
  const candidateIds = new Set(run && run.retrospective && Array.isArray(run.retrospective.steps)
    ? run.retrospective.steps.map(function (step) { return step.node_id; }).filter(Boolean)
    : []);
  const runtimeIds = new Set(Array.from(runtimeMap.keys()));
  const precedesIds = new Set();
  spatialCatalogRelations().forEach(function (relation) {
    if (relation.type === "precedes") {
      precedesIds.add(relation.from);
      precedesIds.add(relation.to);
    }
  });
  const preferred = candidateIds.size ? candidateIds : runtimeIds.size ? runtimeIds : precedesIds;
  const selected = Array.from(preferred).map(function (id) { return byId.get(id); }).filter(function (node) {
    return node && FLOW_TASK_NODE_TYPES.has(node.type);
  });
  if (selected.length) return selected;
  return nodes.filter(function (node) { return FLOW_TASK_NODE_TYPES.has(node.type); });
}
function explicitFlowRanks(nodes) {
  const ids = new Set(nodes.map(function (node) { return node.id; }));
  const indegree = new Map(nodes.map(function (node) { return [node.id, 0]; }));
  const adjacency = new Map(nodes.map(function (node) { return [node.id, []]; }));
  spatialCatalogRelations().filter(function (relation) {
    return FLOW_ORDER_EDGE_TYPES.has(relation.type) && ids.has(relation.from) && ids.has(relation.to) && relation.from !== relation.to;
  }).slice().sort(function (left, right) {
    return (left.first_sequence || 0) - (right.first_sequence || 0) || left.id.localeCompare(right.id);
  }).forEach(function (relation) {
    adjacency.get(relation.from).push(relation.to);
    indegree.set(relation.to, indegree.get(relation.to) + 1);
  });
  const byId = new Map(nodes.map(function (node) { return [node.id, node]; }));
  const compareIds = function (left, right) {
    const leftNode = byId.get(left);
    const rightNode = byId.get(right);
    return (leftNode.first_sequence || 0) - (rightNode.first_sequence || 0) || left.localeCompare(right);
  };
  const queue = nodes.map(function (node) { return node.id; }).filter(function (id) { return indegree.get(id) === 0; }).sort(compareIds);
  const rank = new Map(nodes.map(function (node) { return [node.id, 0]; }));
  const visited = new Set();
  while (queue.length) {
    const id = queue.shift();
    visited.add(id);
    adjacency.get(id).slice().sort(compareIds).forEach(function (next) {
      rank.set(next, Math.max(rank.get(next), rank.get(id) + 1));
      indegree.set(next, indegree.get(next) - 1);
      if (indegree.get(next) === 0) {
        queue.push(next);
        queue.sort(compareIds);
      }
    });
  }
  const hasCycle = visited.size !== nodes.length;
  if (hasCycle) return {rank: new Map(nodes.map(function (node) { return [node.id, 0]; })), hasCycle: true};
  return {rank: rank, hasCycle: false};
}
function buildFlowLayout(nodes, runtimeMap, snapshot, viewportWidth, viewportHeight) {
  const flowNodes = flowTaskNodes(nodes, snapshot, runtimeMap);
  const rankResult = explicitFlowRanks(flowNodes);
  const cells = new Map();
  let maxRank = 0;
  flowNodes.forEach(function (node) {
    const rank = rankResult.rank.get(node.id) || 0;
    maxRank = Math.max(maxRank, rank);
    if (!cells.has(rank)) cells.set(rank, []);
    cells.get(rank).push(node);
  });
  let maxCell = 1;
  cells.forEach(function (cell) {
    cell.sort(function (left, right) {
      return (left.first_sequence || 0) - (right.first_sequence || 0) || left.id.localeCompare(right.id);
    });
    maxCell = Math.max(maxCell, cell.length);
  });
  const compact = viewportWidth < 760;
  const leftGutter = compact ? 100 : Math.max(126, Math.round(viewportWidth * .13));
  const rightGutter = compact ? 120 : Math.max(132, Math.round(viewportWidth * .13));
  const availableSpan = Math.max(0, viewportWidth - leftGutter - rightGutter);
  const columnGap = maxRank ? (compact ? 220 : Math.max(238, availableSpan / maxRank)) : 0;
  const topGutter = 82;
  const bottomGutter = 42;
  const graphHeight = Math.max(210, 114 + maxCell * 104);
  const graphCenter = topGutter + graphHeight / 2;
  const contentWidth = Math.max(viewportWidth, leftGutter + maxRank * columnGap + rightGutter);
  const contentHeight = Math.max(viewportHeight, topGutter + graphHeight + bottomGutter);
  const instances = [];
  cells.forEach(function (cell, rank) {
    cell.forEach(function (node, slot) {
      const x = leftGutter + rank * columnGap;
      const stackHeight = (cell.length - 1) * 98;
      const y = graphCenter - stackHeight / 2 + slot * 98;
      instances.push({
        key: node.id + "::flow", sourceId: node.id, node: node,
        layers: effectiveMembership(node, runtimeMap), displayLayer: "control",
        rank: rank,
        point: {x: x, y: y, z: 0}, screen: {x: x, y: y, depth: slot}
      });
    });
  });
  return {
    instances: instances, maxRank: maxRank, hasCycle: rankResult.hasCycle,
    contentWidth: contentWidth, contentHeight: contentHeight,
    leftGutter: leftGutter, columnGap: columnGap, top: topGutter,
    bottom: topGutter + graphHeight, graphHeight: graphHeight
  };
}
function renderFlowScaffold(svg, layout, snapshot) {
  svg.appendChild(svgElement("rect", {
    class: "flow-dependency-band", x: 22, y: layout.top + 4,
    width: layout.contentWidth - 44, height: layout.graphHeight - 8, rx: 18
  }));
  const bandLabel = svgElement("text", {class: "flow-dependency-label", x: 36, y: layout.top + 25});
  bandLabel.textContent = message("flowTitle");
  svg.appendChild(bandLabel);
  for (let rank = 0; rank <= layout.maxRank; rank += 1) {
    const x = layout.leftGutter + rank * layout.columnGap;
    svg.appendChild(svgElement("line", {class: "flow-rank-line", x1: x, y1: layout.top + 30, x2: x, y2: layout.bottom - 18}));
    const label = svgElement("text", {class: "flow-rank-label", x: x, y: layout.top - 10, "text-anchor": "middle"});
    label.textContent = message("flowRank", {rank: rank + 1});
    svg.appendChild(label);
  }
  const boundary = svgElement("rect", {
    class: "flow-run-boundary", x: 12, y: layout.top - 32,
    width: layout.contentWidth - 24, height: Math.max(80, layout.bottom - layout.top + 42), rx: 22
  });
  svg.appendChild(boundary);
  if (snapshot) {
    const label = svgElement("text", {class: "flow-run-label", x: 28, y: layout.top - 14});
    label.textContent = message("flowRunScope", {run: snapshot.run_label || snapshot.run_id});
    svg.appendChild(label);
  }
}
function clipSpatialEndpoints(from, to, halfWidth, halfHeight) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (!dx && !dy) return {from: from, to: to};
  const startScale = Math.min(1, Math.min(halfWidth / Math.max(1, Math.abs(dx)), halfHeight / Math.max(1, Math.abs(dy))));
  const endScale = startScale;
  return {
    from: {x: from.x + dx * startScale, y: from.y + dy * startScale},
    to: {x: to.x - dx * endScale, y: to.y - dy * endScale}
  };
}
function flowEdgePath(from, to, laneOffset) {
  const clipped = clipSpatialEndpoints(from, to, window.innerWidth < 760 ? 88 : 110, 38);
  const start = clipped.from;
  const end = clipped.to;
  if (Math.abs(end.y - start.y) < 18) {
    const controlX = (start.x + end.x) / 2;
    const bendY = start.y + laneOffset;
    return "M " + start.x.toFixed(1) + " " + start.y.toFixed(1) + " Q " + controlX.toFixed(1) + " " + bendY.toFixed(1) + " " + end.x.toFixed(1) + " " + end.y.toFixed(1);
  }
  const railX = (start.x + end.x) / 2 + laneOffset;
  return "M " + start.x.toFixed(1) + " " + start.y.toFixed(1) + " L " + railX.toFixed(1) + " " + start.y.toFixed(1) + " L " + railX.toFixed(1) + " " + end.y.toFixed(1) + " L " + end.x.toFixed(1) + " " + end.y.toFixed(1);
}
function buildRelationLaneOffsets(relations) {
  const groups = new Map();
  relations.forEach(function (relation) {
    const key = relation.from + "\u0000" + relation.to;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(relation);
  });
  const result = new Map();
  groups.forEach(function (items) {
    items.sort(function (left, right) { return left.type.localeCompare(right.type) || left.id.localeCompare(right.id); });
    items.forEach(function (relation, index) { result.set(relation.id, (index - (items.length - 1) / 2) * 12); });
  });
  return result;
}
function spatialSceneCenter() {
  if (spatialMode !== "orthogonal") return {x: 0, y: 0, z: 0};
  const half = ORTHOGONAL_SIZE / 2;
  if (spatialLayer === "state") return {x: half, y: half, z: 0};
  if (spatialLayer === "control") return {x: half, y: 0, z: half};
  if (spatialLayer === "action") return {x: 0, y: half, z: half};
  return {x: half, y: half, z: half};
}
function projectSpatialPoint(point, width, height) {
  const center = spatialSceneCenter();
  const modelX = point.x - center.x;
  const modelY = point.y - center.y;
  const modelZ = point.z - center.z;
  const cosYaw = Math.cos(spatialCamera.yaw);
  const sinYaw = Math.sin(spatialCamera.yaw);
  const x1 = modelX * cosYaw + modelZ * sinYaw;
  const z1 = -modelX * sinYaw + modelZ * cosYaw;
  const cosPitch = Math.cos(spatialCamera.pitch);
  const sinPitch = Math.sin(spatialCamera.pitch);
  const y1 = modelY * cosPitch - z1 * sinPitch;
  const depth = modelY * sinPitch + z1 * cosPitch;
  const baseScale = Math.min(width / 1040, height / 720) * spatialCamera.scale;
  return {x: width / 2 + x1 * baseScale, y: height / 2 - y1 * baseScale + 18, depth: depth};
}
function spatialLabelPositions(projected, instances, width, height) {
  const labels = new Map(instances.map(function (instance) {
    const anchor = projected.get(instance.key);
    return [instance.key, {x: anchor.x, y: anchor.y, depth: anchor.depth}];
  }));
  for (let pass = 0; pass < 64; pass += 1) {
    for (let leftIndex = 0; leftIndex < instances.length; leftIndex += 1) {
      const left = labels.get(instances[leftIndex].key);
      for (let rightIndex = leftIndex + 1; rightIndex < instances.length; rightIndex += 1) {
        const right = labels.get(instances[rightIndex].key);
        const dx = right.x - left.x;
        const dy = right.y - left.y;
        if (Math.abs(dx) >= 146 || Math.abs(dy) >= 62) continue;
        const yDirection = dy === 0 ? (rightIndex % 2 ? 1 : -1) : Math.sign(dy);
        const yPush = (62 - Math.abs(dy)) / 2 + .8;
        left.y -= yDirection * yPush;
        right.y += yDirection * yPush;
        const xDirection = dx === 0 ? (rightIndex % 2 ? 1 : -1) : Math.sign(dx);
        const xPush = (146 - Math.abs(dx)) * .08;
        left.x -= xDirection * xPush;
        right.x += xDirection * xPush;
      }
    }
    instances.forEach(function (instance) {
      const point = labels.get(instance.key);
      point.x = Math.max(72, Math.min(width - 72, point.x));
      point.y = Math.max(28, Math.min(height - 30, point.y));
      if (point.x < 370 && point.y < 122) point.y = 132;
      if (point.x > width - 132 && point.y < 174) point.y = 184;
    });
  }
  return labels;
}
function svgElement(name, attrs) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attrs || {}).forEach(function (entry) { element.setAttribute(entry[0], String(entry[1])); });
  return element;
}
function spatialPlaneDefinitions() {
  const size = ORTHOGONAL_SIZE;
  const chinese = currentLocale === "zh-CN";
  return [
    {kind: "node", layer: "state", label: chinese ? "XY · State · 节点面" : "XY · State · NODE", points: [{x:0,y:0,z:0},{x:size,y:0,z:0},{x:size,y:size,z:0},{x:0,y:size,z:0}]},
    {kind: "node", layer: "control", label: chinese ? "XZ · Control · 节点面" : "XZ · Control · NODE", points: [{x:0,y:0,z:0},{x:size,y:0,z:0},{x:size,y:0,z:size},{x:0,y:0,z:size}]},
    {kind: "node", layer: "action", label: chinese ? "YZ · Action · 节点面" : "YZ · Action · NODE", points: [{x:0,y:0,z:0},{x:0,y:size,z:0},{x:0,y:size,z:size},{x:0,y:0,z:size}]},
    {kind: "route", interface: "state-control", parallelLayer: "action", label: chinese ? "YZ · S↔C · 线路面 ∥ A" : "YZ · S↔C · ROUTE ∥ A", points: [{x:size,y:0,z:0},{x:size,y:size,z:0},{x:size,y:size,z:size},{x:size,y:0,z:size}]},
    {kind: "route", interface: "control-action", parallelLayer: "state", label: chinese ? "XY · C↔A · 线路面 ∥ S" : "XY · C↔A · ROUTE ∥ S", points: [{x:0,y:0,z:size},{x:size,y:0,z:size},{x:size,y:size,z:size},{x:0,y:size,z:size}]},
    {kind: "route", interface: "action-state", parallelLayer: "control", label: chinese ? "XZ · A↔S · 线路面 ∥ C" : "XZ · A↔S · ROUTE ∥ C", points: [{x:0,y:size,z:0},{x:size,y:size,z:0},{x:size,y:size,z:size},{x:0,y:size,z:size}]}
  ];
}
function chooseSpatialInstance(instances, nodeId, flowKind) {
  const candidates = instances.filter(function (instance) { return instance.sourceId === nodeId; });
  if (!candidates.length) return null;
  const desired = flowKind && flowKind.includes("-") ? flowKind.split("-") : [flowKind];
  return candidates.slice().sort(function (left, right) {
    const score = function (candidate) { return desired.filter(function (layer) { return candidate.layers.includes(layer); }).length; };
    return score(right) - score(left) || left.key.localeCompare(right.key);
  })[0];
}
function spatialLayerPairKind(fromLayer, toLayer) {
  const pair = new Set([fromLayer, toLayer]);
  if (pair.has("state") && pair.has("control")) return "state-control";
  if (pair.has("control") && pair.has("action")) return "control-action";
  if (pair.has("action") && pair.has("state")) return "action-state";
  return fromLayer;
}
function compactSpatialRoute(points) {
  return points.filter(function (point, index) {
    if (!index) return true;
    const previous = points[index - 1];
    return point.x !== previous.x || point.y !== previous.y || point.z !== previous.z;
  });
}
function spatialOrthogonalRoute(fromInstance, toInstance, lane) {
  const from = fromInstance.point;
  const to = toInstance.point;
  const fromLayer = fromInstance.displayLayer;
  const toLayer = toInstance.displayLayer;
  if (fromLayer === toLayer) {
    if (fromLayer === "state") {
      const midX = (from.x + to.x) / 2;
      return compactSpatialRoute([from, {x: midX, y: from.y, z: 0}, {x: midX, y: to.y, z: 0}, to]);
    }
    if (fromLayer === "control") {
      const midX = (from.x + to.x) / 2;
      return compactSpatialRoute([from, {x: midX, y: 0, z: from.z}, {x: midX, y: 0, z: to.z}, to]);
    }
    const midY = (from.y + to.y) / 2;
    return compactSpatialRoute([from, {x: 0, y: midY, z: from.z}, {x: 0, y: midY, z: to.z}, to]);
  }
  const size = ORTHOGONAL_SIZE;
  const routeLane = lane == null ? size / 2 : lane;
  const pair = new Set([fromLayer, toLayer]);
  let route;
  if (pair.has("state") && pair.has("control")) {
    const statePoint = fromLayer === "state" ? from : to;
    const controlPoint = fromLayer === "control" ? from : to;
    route = [statePoint, {x:size,y:statePoint.y,z:0}, {x:size,y:routeLane,z:0}, {x:size,y:routeLane,z:controlPoint.z}, {x:size,y:0,z:controlPoint.z}, controlPoint];
    return compactSpatialRoute(fromLayer === "state" ? route : route.reverse());
  }
  if (pair.has("state") && pair.has("action")) {
    const statePoint = fromLayer === "state" ? from : to;
    const actionPoint = fromLayer === "action" ? from : to;
    route = [actionPoint, {x:0,y:size,z:actionPoint.z}, {x:routeLane,y:size,z:actionPoint.z}, {x:routeLane,y:size,z:0}, {x:statePoint.x,y:size,z:0}, statePoint];
    return compactSpatialRoute(fromLayer === "action" ? route : route.reverse());
  }
  const controlPoint = fromLayer === "control" ? from : to;
  const actionPoint = fromLayer === "action" ? from : to;
  route = [controlPoint, {x:controlPoint.x,y:0,z:size}, {x:controlPoint.x,y:routeLane,z:size}, {x:0,y:routeLane,z:size}, {x:0,y:actionPoint.y,z:size}, actionPoint];
  return compactSpatialRoute(fromLayer === "control" ? route : route.reverse());
}
function resetSpatialCamera() {
  if (spatialMode === "flow") {
    spatialCamera = {yaw: 0, pitch: 0, scale: 1};
    return;
  }
  if (spatialLayer === "state") spatialCamera = {yaw: 0, pitch: 0, scale: 1.08};
  else if (spatialMode === "orthogonal" && spatialLayer === "control") spatialCamera = {yaw: 0, pitch: -Math.PI / 2, scale: 1.08};
  else if (spatialMode === "orthogonal" && spatialLayer === "action") spatialCamera = {yaw: -Math.PI / 2, pitch: 0, scale: 1.08};
  else spatialCamera = {yaw: -0.62, pitch: 0.48, scale: 1};
}
function appendSpatialArrowMarker(svg) {
  const defs = svgElement("defs");
  const marker = svgElement("marker", {id: "spatialArrow", markerWidth: 9, markerHeight: 9, refX: 8, refY: 4.5, orient: "auto", markerUnits: "userSpaceOnUse", viewBox: "0 0 9 9"});
  marker.appendChild(svgElement("path", {d: "M 0 0 L 9 4.5 L 0 9 z", fill: "context-stroke"}));
  defs.appendChild(marker);
  svg.appendChild(defs);
}
function appendSpatialNodeButton(nodeLayer, instance, screen, index, runtimeMap, replayState, related) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "spatial-node" + (spatialMode === "flow" ? " flow-node" : "") + (selectedId === instance.sourceId ? " selected" : "") + (related && !related.has(instance.sourceId) ? " dim" : "") + replayNodeClass(instance.node, replayState);
  button.dataset.nodeId = instance.sourceId;
  button.dataset.sourceNodeId = instance.sourceId;
  button.dataset.instanceKey = instance.key;
  button.dataset.displayLayer = instance.displayLayer;
  button.dataset.modelPoint = instance.point.x + "," + instance.point.y + "," + instance.point.z;
  if (spatialMode === "flow") {
    button.dataset.flowRank = String(instance.rank);
  }
  button.style.left = screen.x + "px";
  button.style.top = screen.y + "px";
  button.style.zIndex = String(30 + index);
  const primaryLayer = instance.displayLayer && SPATIAL_LAYER_COLORS[instance.displayLayer] ? instance.displayLayer : (instance.layers[0] || "state");
  button.style.setProperty("--node-color", SPATIAL_LAYER_COLORS[primaryLayer]);
  const top = document.createElement("div");
  top.className = "spatial-node-top";
  const runtimeEntry = runtimeMap.get(instance.sourceId);
  const replayStatus = replayState.nodeStatuses.get(instance.sourceId);
  const typeElement = createText("span", "", nodeTypeLabel(instance.node.type));
  const statusText = replayStatus ? statusLabel(replayStatus) : runtimeEntry ? statusLabel(runtimeEntry.runtime_lane) : instance.layers.map(function (layer) { return layer[0].toUpperCase(); }).join("/");
  top.append(typeElement, createText("span", "", statusText));
  button.append(top, createText("div", "spatial-node-title", localizedNodeLabel(instance.node)));
  if (spatialMode === "flow") {
    const details = [message("planLevel", {rank: (instance.rank || 0) + 1})];
    const attrs = instance.node.attrs || {};
    if (attrs.action_tool) details.push(message("actionToolLabel") + ": " + attrs.action_tool);
    if (runtimeEntry && runtimeEntry.executor) details.push(runtimeEntry.executor);
    if (runtimeEntry && runtimeEntry.blockers && runtimeEntry.blockers[0]) details.push(runtimeEntry.blockers[0].message || runtimeEntry.blockers[0].code || "gate");
    button.appendChild(createText("div", "spatial-node-detail", details.join(" · ")));
    if (attrs.action_output) button.appendChild(createText("div", "spatial-node-action-output", message("actionOutputLabel") + ": " + attrs.action_output));
    if (attrs.action_tool) button.dataset.actionTool = attrs.action_tool;
    if (attrs.action_output) button.dataset.actionOutput = attrs.action_output;
  }
  button.title = instance.node.id + " · " + instance.layers.join(" / ");
  button.addEventListener("click", function (event) { event.stopPropagation(); selectNode(instance.sourceId); });
  nodeLayer.appendChild(button);
}
function finishSpatialRender(nodes, instances, runtimeMap, snapshot) {
  const empty = document.getElementById("spatialEmpty");
  empty.textContent = message("spatialNoData");
  empty.hidden = instances.length > 0;
  const summary = document.getElementById("spatialLayerSummary");
  clearElement(summary);
  ["state", "control", "action"].forEach(function (layer) {
    const count = nodes.filter(function (node) { return effectiveMembership(node, runtimeMap).includes(layer); }).length;
    summary.appendChild(createText("span", "spatial-layer-chip", layer[0].toUpperCase() + " · " + count));
  });
  if (snapshot) summary.appendChild(createText("span", "spatial-layer-chip", (snapshot.run_label || snapshot.run_id)));
  if (!hasObservedExecutionTrack(snapshot)) summary.appendChild(createText("span", "spatial-layer-chip", message("executionNoRuntime")));
  const titleKey = spatialMode === "flow" ? "flowTitle" : "orthogonalTitle";
  const subtitleKey = spatialMode === "flow" ? "flowSubtitle" : "orthogonalSubtitle";
  document.getElementById("spatialTitle").textContent = message(titleKey);
  const cycleWarning = spatialMode === "flow" && document.getElementById("spatialStage").dataset.flowCycle === "true" ? " " + message("flowCycleWarning") : "";
  document.getElementById("spatialSubtitle").textContent = message(subtitleKey) + cycleWarning;
  renderReplayHud(snapshot);
}
function renderFlowSpatial(stage, scene, svg, nodeLayer, viewportWidth, viewportHeight, snapshot, runtimeMap, replayState, nodes) {
  const layout = buildFlowLayout(nodes, runtimeMap, snapshot, viewportWidth, viewportHeight);
  const viewport = document.getElementById("spatialViewport");
  viewport.style.overflow = layout.contentWidth > viewportWidth + 1 || layout.contentHeight > viewportHeight + 1 ? "auto" : "hidden";
  scene.style.width = layout.contentWidth + "px";
  scene.style.height = layout.contentHeight + "px";
  svg.setAttribute("viewBox", "0 0 " + layout.contentWidth + " " + layout.contentHeight);
  const instances = layout.instances;
  const projected = new Map(instances.map(function (instance) { return [instance.key, instance.screen]; }));
  spatialRenderState = {instances: instances, instanceByKey: new Map(instances.map(function (item) { return [item.key, item]; })), visibleIds: new Set(instances.map(function (item) { return item.sourceId; }))};
  appendSpatialArrowMarker(svg);
  renderFlowScaffold(svg, layout, snapshot);

  const related = selectedId ? adjacentIds(selectedId) : null;
  const relations = spatialCatalogRelations().filter(function (relation) {
    if (!spatialRenderState.visibleIds.has(relation.from) || !spatialRenderState.visibleIds.has(relation.to)) return false;
    return relation.type === "precedes";
  });
  const offsets = buildRelationLaneOffsets(relations);
  relations.forEach(function (relation) {
    const fromInstance = chooseSpatialInstance(instances, relation.from, relation.flow_kind);
    const toInstance = chooseSpatialInstance(instances, relation.to, relation.flow_kind);
    if (!fromInstance || !toInstance || fromInstance.key === toInstance.key) return;
    const from = projected.get(fromInstance.key);
    const to = projected.get(toInstance.key);
    const pathText = flowEdgePath(from, to, offsets.get(relation.id) || 0);
    const selected = selectedId && (relation.from === selectedId || relation.to === selectedId);
    const dim = related && (!related.has(relation.from) || !related.has(relation.to));
    const family = relationFamily(relation.type);
    const sameLane = fromInstance.displayLayer === toInstance.displayLayer;
    const color = sameLane ? SPATIAL_LAYER_COLORS[fromInstance.displayLayer] : "var(--edge)";
    const path = svgElement("path", {
      class: "spatial-edge relation-" + family + (selected ? " selected" : "") + (dim ? " dim" : "") + replayEdgeClass(relation, replayState),
      d: pathText, stroke: color, opacity: selected ? 1 : .62, "marker-end": "url(#spatialArrow)",
      "data-edge-id": relation.id, "data-edge-family": family, "data-edge-type": relation.type
    });
    path.appendChild(document.createElementNS("http://www.w3.org/2000/svg", "title")).textContent = edgeTypeLabel(relation.type) + ": " + relation.from + " → " + relation.to;
    svg.appendChild(path);
    const edgeLabel = svgElement("text", {class: "flow-edge-label", x: (from.x + to.x) / 2, y: Math.min(from.y, to.y) - 10 - Math.abs(offsets.get(relation.id) || 0), "text-anchor": "middle"});
    edgeLabel.textContent = edgeTypeLabel(relation.type);
    svg.appendChild(edgeLabel);
    const replayParticle = replayState.active && replayState.currentEdgeIds.has(relation.id) && replayState.mode === "observed" && hasObservedExecutionTrack(snapshot);
    const reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (replayParticle && !dim && !reducedMotion) {
      const particle = svgElement("circle", {class: "spatial-edge-flow-once", r: selected ? 4 : 3.4, fill: color, opacity: .94, "data-edge-id": relation.id});
      particle.appendChild(svgElement("animateMotion", {dur: ".68s", repeatCount: "1", path: pathText}));
      svg.appendChild(particle);
    }
  });
  instances.slice().sort(function (left, right) { return left.rank - right.rank || left.screen.y - right.screen.y || left.key.localeCompare(right.key); }).forEach(function (instance, index) {
    appendSpatialNodeButton(nodeLayer, instance, projected.get(instance.key), index, runtimeMap, replayState, related);
  });
  stage.dataset.flowCycle = String(layout.hasCycle);
  stage.dataset.flowInstanceCount = String(instances.length);
  stage.dataset.flowEdgeCount = String(relations.length);
  finishSpatialRender(nodes, instances, runtimeMap, snapshot);
}
function renderSpatial() {
  const stage = document.getElementById("spatialStage");
  const viewport = document.getElementById("spatialViewport");
  const scene = document.getElementById("spatialScene");
  const svg = document.getElementById("spatialSvg");
  const nodeLayer = document.getElementById("spatialNodeLayer");
  document.getElementById("planWorkbench").dataset.planView = spatialMode;
  stage.dataset.viewMode = spatialMode;
  stage.dataset.coordinateDomain = spatialMode === "flow" ? "explicit-precedes-rank;vertical-branch-avoidance" : "cuboid;node-faces:x=0|y=0|z=0;route-faces:x=L|y=L|z=L;orthogonal-segments";
  stage.dataset.camera = "yaw=" + spatialCamera.yaw + ";pitch=" + spatialCamera.pitch + ";scale=" + spatialCamera.scale;
  const viewportWidth = Math.max(320, stage.clientWidth || 1200);
  const viewportHeight = Math.max(spatialMode === "flow" ? 330 : 460, stage.clientHeight || (spatialMode === "flow" ? 350 : 560));
  clearElement(svg);
  clearElement(nodeLayer);
  const snapshot = selectedRuntimeSnapshot();
  const runtimeMap = runtimeEntryMap(snapshot);
  renderPlanWorkbench(snapshot, runtimeMap);
  const replayState = replayVisualState(snapshot);
  renderCaseContext(snapshot, runtimeMap);
  let nodes = spatialMode === "flow" ? replayPlanModel(snapshot).nodes : selectedRunScope(snapshot);
  if (spatialMode === "flow") {
    const query = document.getElementById("search").value.trim().toLowerCase();
    if (query) nodes = nodes.filter(function (node) { return spatialNodeMatches(node, query); });
  }
  if (spatialMode !== "flow" && spatialLayer !== "all") nodes = nodes.filter(function (node) { return effectiveMembership(node, runtimeMap).includes(spatialLayer); });
  document.getElementById("spatialCameraHud").hidden = spatialMode === "flow";
  document.getElementById("spatialLayerHud").hidden = spatialMode === "flow";
  document.getElementById("spatialLoopCard").hidden = spatialMode === "flow";
  document.getElementById("flowLegendCard").hidden = spatialMode !== "flow";
  document.getElementById("relationFilter").hidden = spatialMode === "flow";
  if (spatialMode === "flow") {
    renderFlowSpatial(stage, scene, svg, nodeLayer, viewportWidth, viewportHeight, snapshot, runtimeMap, replayState, nodes);
    return;
  }
  viewport.style.overflow = "hidden";
  scene.style.width = "100%";
  scene.style.height = "100%";
  viewport.scrollLeft = 0;
  viewport.scrollTop = 0;
  const width = viewportWidth;
  const height = viewportHeight;
  svg.setAttribute("viewBox", "0 0 " + width + " " + height);
  let instances = buildOrthogonalInstances(nodes, runtimeMap);
  if (spatialLayer !== "all") instances = instances.filter(function (instance) { return instance.layers.includes(spatialLayer); });
  const projected = new Map();
  instances.forEach(function (instance) { projected.set(instance.key, projectSpatialPoint(instance.point, width, height)); });
  const labelPositions = spatialLabelPositions(projected, instances, width, height);
  spatialRenderState = {instances: instances, instanceByKey: new Map(instances.map(function (item) { return [item.key, item]; })), visibleIds: new Set(nodes.map(function (node) { return node.id; }))};

  appendSpatialArrowMarker(svg);

  const visiblePlanes = spatialPlaneDefinitions().filter(function (plane) { return spatialLayer === "all" || (plane.kind === "node" && plane.layer === spatialLayer); });
  visiblePlanes.map(function (plane) {
    const points = plane.points.map(function (point) { return projectSpatialPoint(point, width, height); });
    return {plane: plane, points: points, depth: points.reduce(function (sum, point) { return sum + point.depth; }, 0) / points.length};
  }).sort(function (left, right) { return left.depth - right.depth; }).forEach(function (entry) {
    const color = entry.plane.kind === "node" ? SPATIAL_LAYER_COLORS[entry.plane.layer] : SPATIAL_FLOW_COLORS[entry.plane.interface];
    const polygon = svgElement("polygon", {class: "spatial-plane " + entry.plane.kind + "-face", points: entry.points.map(function (point) { return point.x.toFixed(1) + "," + point.y.toFixed(1); }).join(" ")});
    polygon.dataset.faceKind = entry.plane.kind;
    if (entry.plane.layer) polygon.dataset.layer = entry.plane.layer;
    if (entry.plane.interface) polygon.dataset.interface = entry.plane.interface;
    if (entry.plane.parallelLayer) polygon.dataset.parallelLayer = entry.plane.parallelLayer;
    polygon.dataset.modelPoints = entry.plane.points.map(function (point) { return point.x + "," + point.y + "," + point.z; }).join(";");
    const fillStrength = entry.plane.kind === "node" ? "7%" : "3%";
    polygon.setAttribute("style", "fill:color-mix(in srgb," + color + " " + fillStrength + ",transparent);stroke:color-mix(in srgb," + color + " 55%,transparent)");
    svg.appendChild(polygon);
    const anchor = entry.points[2];
    const label = svgElement("text", {class: "spatial-axis-label", x: anchor.x - 8, y: anchor.y - 9, fill: color, "text-anchor": "end"});
    label.textContent = entry.plane.label;
    svg.appendChild(label);
  });

  if (spatialMode === "orthogonal" && spatialLayer === "all") {
    const axisEnd = ORTHOGONAL_SIZE + 30;
    [[{x:0,y:0,z:0},{x:axisEnd,y:0,z:0},"X+"],[{x:0,y:0,z:0},{x:0,y:axisEnd,z:0},"Y+"],[{x:0,y:0,z:0},{x:0,y:0,z:axisEnd},"Z+"]].forEach(function (axis) {
      const from = projectSpatialPoint(axis[0], width, height);
      const to = projectSpatialPoint(axis[1], width, height);
      const line = svgElement("line", {class: "spatial-axis", x1: from.x, y1: from.y, x2: to.x, y2: to.y, stroke: "var(--edge)"});
      line.dataset.modelFrom = "0,0,0";
      line.dataset.modelTo = axis[1].x + "," + axis[1].y + "," + axis[1].z;
      svg.appendChild(line);
      const label = svgElement("text", {class: "spatial-axis-label", x: to.x, y: to.y - 7, fill: "var(--muted)", "text-anchor": "middle"});
      label.textContent = axis[2];
      svg.appendChild(label);
    });
    const origin = projectSpatialPoint({x:0,y:0,z:0}, width, height);
    svg.appendChild(svgElement("circle", {class: "spatial-origin", cx: origin.x, cy: origin.y, r: 5, "data-model-point": "0,0,0"}));
    const originLabel = svgElement("text", {class: "spatial-axis-label", x: origin.x - 8, y: origin.y + 15, fill: "var(--accent)", "text-anchor": "end"});
    originLabel.textContent = "O";
    svg.appendChild(originLabel);
  }

  const relationMode = document.getElementById("relationFilter").value;
  const related = selectedId ? adjacentIds(selectedId) : null;
  const routedRelations = spatialCatalogRelations().filter(function (relation) {
    if (!spatialRenderState.visibleIds.has(relation.from) || !spatialRenderState.visibleIds.has(relation.to)) return false;
    return relationMode === "all" || primaryEdgeTypes.has(relation.type) || (relation.type === "contains" && relation.from === (snapshot && snapshot.run_id));
  }).map(function (relation) {
    const flowKind = relation.flow_kind || (primaryEdgeTypes.has(relation.type) ? "control" : "state");
    const fromInstance = chooseSpatialInstance(instances, relation.from, flowKind);
    const toInstance = chooseSpatialInstance(instances, relation.to, flowKind);
    if (!fromInstance || !toInstance || fromInstance.key === toInstance.key) return null;
    return {relation: relation, flowKind: flowKind, fromInstance: fromInstance, toInstance: toInstance, routeKind: spatialLayerPairKind(fromInstance.displayLayer, toInstance.displayLayer)};
  }).filter(Boolean);
  const laneGroups = new Map();
  routedRelations.forEach(function (item) {
    if (item.fromInstance.displayLayer === item.toInstance.displayLayer) return;
    if (!laneGroups.has(item.routeKind)) laneGroups.set(item.routeKind, []);
    laneGroups.get(item.routeKind).push(item);
  });
  const relationLanes = new Map();
  laneGroups.forEach(function (items) {
    items.sort(function (left, right) { return left.relation.id.localeCompare(right.relation.id); });
    const usable = ORTHOGONAL_SIZE - ORTHOGONAL_INSET * 2;
    items.forEach(function (item, index) {
      relationLanes.set(item.relation.id, ORTHOGONAL_INSET + (index + 1) * usable / (items.length + 1));
    });
  });
  routedRelations.forEach(function (item) {
    const relation = item.relation;
    const flowKind = item.flowKind;
    const fromInstance = item.fromInstance;
    const toInstance = item.toInstance;
    const modelRoute = spatialOrthogonalRoute(fromInstance, toInstance, relationLanes.get(relation.id));
    const pathText = modelRoute.map(function (point, routeIndex) {
      const screen = projectSpatialPoint(point, width, height);
      return (routeIndex ? "L " : "M ") + screen.x.toFixed(1) + " " + screen.y.toFixed(1);
    }).join(" ");
    const selected = selectedId && (relation.from === selectedId || relation.to === selectedId);
    const dim = related && (!related.has(relation.from) || !related.has(relation.to));
    const color = SPATIAL_FLOW_COLORS[flowKind] || "var(--edge)";
    const family = relationFamily(relation.type);
    const path = svgElement("path", {class: "spatial-edge relation-" + family + (selected ? " selected" : "") + (dim ? " dim" : "") + replayEdgeClass(relation, replayState), d: pathText, stroke: color, opacity: selected ? 1 : .56, "marker-end": "url(#spatialArrow)", "data-edge-id": relation.id, "data-edge-family": family, "data-edge-type": relation.type});
    path.dataset.modelRoute = modelRoute.map(function (point) { return point.x + "," + point.y + "," + point.z; }).join(";");
    path.dataset.fromLayer = fromInstance.displayLayer;
    path.dataset.toLayer = toInstance.displayLayer;
    path.dataset.routeFace = fromInstance.displayLayer === toInstance.displayLayer ? fromInstance.displayLayer : item.routeKind;
    path.appendChild(document.createElementNS("http://www.w3.org/2000/svg", "title")).textContent = edgeTypeLabel(relation.type) + ": " + relation.from + " → " + relation.to;
    svg.appendChild(path);
    const replayParticle = replayState.active && replayState.currentEdgeIds.has(relation.id) && replayState.mode === "observed" && hasObservedExecutionTrack(snapshot);
    const reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (replayParticle && !dim && !reducedMotion) {
      const particle = svgElement("circle", {class: "spatial-edge-flow-once", r: selected ? 4 : 3.4, fill: color, opacity: .94, "data-edge-id": relation.id});
      particle.appendChild(svgElement("animateMotion", {dur: ".68s", repeatCount: "1", path: pathText}));
      svg.appendChild(particle);
    }
  });

  instances.forEach(function (instance) {
    const anchor = projected.get(instance.key);
    const labelPoint = labelPositions.get(instance.key);
    const color = SPATIAL_LAYER_COLORS[instance.displayLayer] || "var(--edge)";
    const distance = Math.hypot(labelPoint.x - anchor.x, labelPoint.y - anchor.y);
    if (distance > 5) {
      const tether = svgElement("line", {class: "spatial-node-tether", x1: anchor.x, y1: anchor.y, x2: labelPoint.x, y2: labelPoint.y, stroke: color});
      tether.dataset.sourceNodeId = instance.sourceId;
      svg.appendChild(tether);
    }
    const anchorDot = svgElement("circle", {class: "spatial-node-anchor", cx: anchor.x, cy: anchor.y, r: 3.2, fill: color});
    anchorDot.dataset.sourceNodeId = instance.sourceId;
    anchorDot.dataset.displayLayer = instance.displayLayer;
    anchorDot.dataset.modelPoint = instance.point.x + "," + instance.point.y + "," + instance.point.z;
    svg.appendChild(anchorDot);
  });

  instances.slice().sort(function (left, right) { return projected.get(left.key).depth - projected.get(right.key).depth; }).forEach(function (instance, index) {
    appendSpatialNodeButton(nodeLayer, instance, labelPositions.get(instance.key), index, runtimeMap, replayState, related);
  });
  finishSpatialRender(nodes, instances, runtimeMap, snapshot);
}
function selectNode(id) {
  selectedId = selectedId === id ? null : id;
  if (selectedId) openDrawer(nodeById.get(selectedId)); else closeDrawer();
  renderWorkspace();
}
function openDrawer(node) {
  if (!node) return;
  activeAuxPanel = null;
  document.getElementById("drawerNodeContent").hidden = false;
  document.getElementById("drawerAux").hidden = true;
  document.getElementById("drawerKicker").textContent = nodeTypeLabel(node.type);
  document.getElementById("drawerTitle").textContent = localizedNodeLabel(node);
  const original = document.getElementById("drawerOriginal");
  if (localizedNodeLabel(node) !== node.label) {
    original.textContent = message("originalLabel") + ": " + node.label;
    original.hidden = false;
  } else {
    original.hidden = true;
  }
  document.getElementById("drawerId").textContent = node.id;
  renderProperties(node);
  renderRelations(node);
  renderSources(node);
  document.getElementById("rawJson").textContent = JSON.stringify(node, null, 2);
  document.getElementById("drawerBackdrop").hidden = false;
  const drawer = document.getElementById("detailsDrawer");
  drawer.hidden = false;
  drawer.setAttribute("aria-hidden", "false");
}
function closeDrawer() {
  activeAuxPanel = null;
  document.getElementById("drawerBackdrop").hidden = true;
  const drawer = document.getElementById("detailsDrawer");
  drawer.hidden = true;
  drawer.setAttribute("aria-hidden", "true");
}
function openAuxPanel(kind) {
  activeAuxPanel = "quality";
  document.getElementById("drawerNodeContent").hidden = true;
  document.getElementById("drawerAux").hidden = false;
  document.getElementById("findings").hidden = false;
  document.getElementById("drawerKicker").textContent = "Lint";
  document.getElementById("drawerTitle").textContent = message("qualityTitle");
  renderFindings();
  document.getElementById("drawerBackdrop").hidden = false;
  const drawer = document.getElementById("detailsDrawer");
  drawer.hidden = false;
  drawer.setAttribute("aria-hidden", "false");
}
function displayValue(value) {
  if (Array.isArray(value)) return value.map(displayValue).join(" · ");
  if (value && typeof value === "object") return JSON.stringify(value);
  if (typeof value === "boolean") return currentLocale === "zh-CN" ? (value ? "是" : "否") : String(value);
  if (typeof value === "string") return statusLabel(modeLabel(value));
  return String(value);
}
function renderProperties(node) {
  const target = document.getElementById("propertyList");
  clearElement(target);
  const entries = Object.entries(node.attrs || {});
  entries.push(["first_sequence", node.first_sequence]);
  if (!entries.length) {
    target.appendChild(createText("div", "empty", message("noProperties")));
    return;
  }
  entries.forEach(function (entry) {
    target.appendChild(createText("div", "property-key", propertyLabel(entry[0])));
    target.appendChild(createText("div", "property-value", displayValue(entry[1])));
  });
}
function renderRelations(node) {
  const target = document.getElementById("relationList");
  clearElement(target);
  const relations = graph.edges.filter(function (edge) { return edge.from === node.id || edge.to === node.id; });
  if (!relations.length) {
    target.appendChild(createText("div", "source-item", message("noRelations")));
    return;
  }
  relations.forEach(function (edge) {
    const outgoing = edge.from === node.id;
    const neighbor = nodeById.get(outgoing ? edge.to : edge.from);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "relation-button";
    const direction = outgoing ? message("outgoing") + " →" : "← " + message("incoming");
    button.appendChild(createText("span", "relation-kind", direction + " · " + edgeTypeLabel(edge.type)));
    button.appendChild(document.createTextNode(neighbor ? localizedNodeLabel(neighbor) : (outgoing ? edge.to : edge.from)));
    button.addEventListener("click", function () {
      if (neighbor) {
        selectedId = neighbor.id;
        openDrawer(neighbor);
        renderWorkspace();
      }
    });
    target.appendChild(button);
  });
}
function renderSources(node) {
  const target = document.getElementById("sourceList");
  clearElement(target);
  const eventIds = new Set(node.event_ids || []);
  const sources = new Set();
  events.forEach(function (event) {
    if (eventIds.has(event.event_id)) {
      (event.provenance.source_refs || []).forEach(function (source) { sources.add(source); });
    }
  });
  if (!sources.size) {
    target.appendChild(createText("div", "source-item", message("noSources")));
    return;
  }
  Array.from(sources).forEach(function (source) {
    target.appendChild(createText("div", "source-item", source));
  });
}
function renderSummary() {
  const target = document.getElementById("summary");
  clearElement(target);
  const errors = findings.filter(function (item) { return item.severity === "error"; }).length;
  const warnings = findings.filter(function (item) { return item.severity === "warning"; }).length;
  const parts = [
    {text: graph.stats.node_count + " " + message("nodes")},
    {text: graph.stats.edge_count + " " + message("edges")},
    {text: graph.stats.event_count + " " + message("events")},
    {text: errors + " " + message("errors") + " / " + warnings + " " + message("warnings"), className: errors || warnings ? "" : "good"},
    {text: message("state") + ": " + statusLabel(rootState()), className: "state"}
  ];
  parts.forEach(function (part) {
    target.appendChild(createText("span", "summary-chip " + (part.className || ""), part.text));
  });
}
function eventDetail(event) {
  if (event.kind === "node.recorded" && event.node) {
    const node = nodeById.get(event.node.id) || event.node;
    return nodeTypeLabel(event.node.type) + " · " + localizedNodeLabel(node);
  }
  if (event.kind === "edge.recorded" && event.edge) {
    const from = nodeById.get(event.edge.from);
    const to = nodeById.get(event.edge.to);
    return (from ? localizedNodeLabel(from) : event.edge.from) + " → " + edgeTypeLabel(event.edge.type) + " → " + (to ? localizedNodeLabel(to) : event.edge.to);
  }
  if (event.kind === "state.changed" && event.transition) {
    return statusLabel(event.transition.from) + " → " + statusLabel(event.transition.to) + " · " + event.transition.reason;
  }
  return graph.graph_id;
}
function renderFindings() {
  const target = document.getElementById("findings");
  clearElement(target);
  if (!findings.length) {
    target.appendChild(createText("div", "empty", message("noFindings")));
    return;
  }
  findings.forEach(function (finding) {
    const item = document.createElement("article");
    item.className = "finding " + finding.severity;
    const meta = document.createElement("div");
    meta.className = "finding-meta";
    meta.appendChild(createText("span", "finding-chip", translated({error: "错误", warning: "警告"}, finding.severity)));
    meta.appendChild(createText("span", "finding-chip", finding.code));
    const localized = currentLocale === "zh-CN" ? (FINDING_ZH[finding.code] || finding.message) : finding.message;
    item.append(meta, createText("div", "finding-title", localized));
    if (localized !== finding.message) item.appendChild(createText("div", "finding-original", finding.message));
    target.appendChild(item);
  });
}
function setOptionText(selectId, value, text) {
  const option = document.querySelector("#" + selectId + " option[value='" + value + "']");
  if (option) option.textContent = text;
}
function rebuildSpatialRunOptions() {
  const select = document.getElementById("spatialRunFilter");
  const selected = select.value;
  clearElement(select);
  const latest = document.createElement("option");
  latest.value = "";
  latest.textContent = message("latestRun");
  select.appendChild(latest);
  const runs = spatialRunCandidates();
  runs.forEach(function (run) {
    const option = document.createElement("option");
    option.value = run.run_id;
    option.textContent = (run.run_label || run.run_id) + " · " + statusLabel(run.status || run.case_state || "");
    select.appendChild(option);
  });
  if (Array.from(select.options).some(function (option) { return option.value === selected; })) select.value = selected;
}
function updateStaticText() {
  document.documentElement.lang = currentLocale;
  document.getElementById("pageTitle").textContent = localizedTitle();
  document.title = localizedTitle();
  document.getElementById("languageSelect").value = currentLocale;
  document.querySelectorAll("[data-i18n]").forEach(function (element) {
    element.textContent = message(element.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-aria]").forEach(function (element) {
    element.setAttribute("aria-label", message(element.dataset.i18nAria));
  });
  document.getElementById("languageSelect").setAttribute("aria-label", message("languageLabel"));
  document.getElementById("themeToggle").setAttribute("aria-label", message("themeToggle"));
  document.getElementById("search").placeholder = message("searchPlaceholder");
  setOptionText("relationFilter", "story", message("relationsStory"));
  setOptionText("relationFilter", "all", message("relationsAll"));
  setOptionText("planViewSelect", "flow", message("planViewFlow"));
  setOptionText("planViewSelect", "orthogonal", message("planViewOrthogonal"));
  document.getElementById("drawerClose").setAttribute("aria-label", message("close"));
  document.getElementById("resetCamera").title = message("resetCamera");
  document.getElementById("rotateLeft").title = message("rotateLeft");
  document.getElementById("rotateRight").title = message("rotateRight");
  document.getElementById("rotateUp").title = message("rotateUp");
  document.getElementById("rotateDown").title = message("rotateDown");
  document.getElementById("replaySpeed").setAttribute("aria-label", message("replaySpeed"));
  document.getElementById("replayTrackTabs").setAttribute("aria-label", message("replayTitle"));
  document.getElementById("replayStrip").setAttribute("aria-label", message("replayTitle"));
  document.getElementById("replayReset").title = message("replayReset");
  document.getElementById("replayReset").setAttribute("aria-label", message("replayReset"));
  document.getElementById("replayPrev").title = message("replayPrev");
  document.getElementById("replayPrev").setAttribute("aria-label", message("replayPrev"));
  document.getElementById("replayPlay").title = replayTimer === null ? message("replayPlay") : message("replayPause");
  document.getElementById("replayPlay").setAttribute("aria-label", replayTimer === null ? message("replayPlay") : message("replayPause"));
  document.getElementById("replayNext").title = message("replayNext");
  document.getElementById("replayNext").setAttribute("aria-label", message("replayNext"));
  document.getElementById("replayLast").title = message("replayLast");
  document.getElementById("replayLast").setAttribute("aria-label", message("replayLast"));
  document.getElementById("replayRange").setAttribute("aria-label", message("replayPosition"));
  updateThemeLabel();
  rebuildSpatialRunOptions();
  renderSummary();
}
function setLocale(locale) {
  currentLocale = locale === "en-US" ? "en-US" : "zh-CN";
  try { localStorage.setItem("acg-locale", currentLocale); } catch (_) {}
  updateStaticText();
  renderFindings();
  renderWorkspace();
  if (selectedId) openDrawer(nodeById.get(selectedId));
  else if (activeAuxPanel) openAuxPanel(activeAuxPanel);
}
function updateThemeLabel() {
  const theme = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  document.getElementById("themeLabel").textContent = theme === "dark" ? message("themeDark") : message("themeLight");
}
function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("acg-theme", next); } catch (_) {}
  updateThemeLabel();
}
function updateWorkspaceChrome() {
  document.querySelectorAll("[data-workspace-mode]").forEach(function (item) {
    const active = item.dataset.workspaceMode === workspaceMode;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll("[data-workspace-panel]").forEach(function (panel) {
    const active = panel.dataset.workspacePanel === workspaceMode;
    panel.classList.toggle("active", active);
  });
  const planning = workspaceMode === "plan";
  document.getElementById("planViewSelect").hidden = !planning;
  document.getElementById("searchWrap").hidden = !planning;
  document.getElementById("relationFilter").hidden = !planning || spatialMode === "flow";
}
function renderWorkspace() {
  updateWorkspaceChrome();
  const snapshot = selectedRuntimeSnapshot();
  const runtimeMap = runtimeEntryMap(snapshot);
  renderCaseContext(snapshot, runtimeMap);
  if (workspaceMode === "plan") {
    document.getElementById("planViewSelect").value = spatialMode;
    renderSpatial();
  } else if (workspaceMode === "overview") {
    renderWorkspaceOverview(snapshot, runtimeMap);
  } else if (workspaceMode === "run") {
    renderRuntimeWorkspace(snapshot, runtimeMap);
  } else if (workspaceMode === "review") {
    renderReviewWorkspace(snapshot, runtimeMap);
  } else {
    renderEvidenceWorkspace(snapshot);
  }
}
function activateWorkspaceMode(mode) {
  workspaceMode = ["overview", "plan", "run", "review", "evidence"].includes(mode) ? mode : "overview";
  stopReplayPlayback();
  renderWorkspace();
}
function activatePlanView(mode) {
  spatialMode = mode === "orthogonal" || mode === "flow" ? mode : "flow";
  stopReplayPlayback();
  resetSpatialCamera();
  const viewport = document.getElementById("spatialViewport");
  viewport.scrollLeft = 0;
  viewport.scrollTop = 0;
  renderWorkspace();
}
function init() {
  updateStaticText();
  renderFindings();
  resetSpatialCamera();
  renderWorkspace();
  document.getElementById("languageSelect").addEventListener("change", function (event) { setLocale(event.target.value); });
  document.getElementById("themeToggle").addEventListener("click", function () { toggleTheme(); renderWorkspace(); });
  document.getElementById("search").addEventListener("input", renderWorkspace);
  document.getElementById("spatialRunFilter").addEventListener("change", function () { selectedId = null; stopReplayPlayback(); replayCursors = {ledger: 0, candidate: 0, observed: 0}; closeDrawer(); renderWorkspace(); });
  document.getElementById("planViewSelect").addEventListener("change", function (event) { activatePlanView(event.target.value); });
  document.getElementById("relationFilter").addEventListener("change", renderWorkspace);
  document.querySelectorAll("[data-replay-mode]").forEach(function (button) {
    button.addEventListener("click", function () {
      stopReplayPlayback();
      replayMode = ["ledger", "plan", "candidate", "observed"].includes(button.dataset.replayMode) ? button.dataset.replayMode : "ledger";
      renderWorkspace();
    });
  });
  document.getElementById("replayReset").addEventListener("click", function () { stopReplayPlayback(); setReplayCursor(0); });
  document.getElementById("replayPrev").addEventListener("click", function () { stepReplay(-1); });
  document.getElementById("replayPlay").addEventListener("click", toggleReplayPlayback);
  document.getElementById("replayNext").addEventListener("click", function () { stepReplay(1); });
  document.getElementById("replayLast").addEventListener("click", function () { stopReplayPlayback(); const items = replayItems(selectedRuntimeSnapshot()); setReplayCursor(Math.max(0, items.length - 1)); });
  document.getElementById("replayRange").addEventListener("input", function (event) { stopReplayPlayback(); setReplayCursor(event.target.value); });
  document.getElementById("replaySpeed").addEventListener("change", function () { if (replayTimer !== null) { stopReplayPlayback(); toggleReplayPlayback(); } });
  document.getElementById("qualityButton").addEventListener("click", function () { openAuxPanel("quality"); });
  document.getElementById("reviewReplayButton").addEventListener("click", function () {
    stopReplayPlayback();
    replayMode = "candidate";
    workspaceMode = "plan";
    spatialMode = "flow";
    renderWorkspace();
  });
  document.querySelectorAll(".spatial-layer-button").forEach(function (button) {
    button.addEventListener("click", function () {
      spatialLayer = button.dataset.spatialLayer;
      document.querySelectorAll(".spatial-layer-button").forEach(function (item) { item.classList.toggle("active", item === button); });
      resetSpatialCamera();
      renderSpatial();
    });
  });
  document.getElementById("rotateLeft").addEventListener("click", function () { spatialCamera.yaw -= .16; renderSpatial(); });
  document.getElementById("rotateRight").addEventListener("click", function () { spatialCamera.yaw += .16; renderSpatial(); });
  document.getElementById("rotateUp").addEventListener("click", function () { spatialCamera.pitch = Math.min(1.35, spatialCamera.pitch + .12); renderSpatial(); });
  document.getElementById("rotateDown").addEventListener("click", function () { spatialCamera.pitch = Math.max(-1.35, spatialCamera.pitch - .12); renderSpatial(); });
  document.getElementById("resetCamera").addEventListener("click", function () { resetSpatialCamera(); renderSpatial(); });
  const stage = document.getElementById("spatialStage");
  stage.addEventListener("pointerdown", function (event) {
    if (spatialMode === "flow") return;
    if (event.target.closest && event.target.closest("button, input, select")) return;
    spatialDrag = {x: event.clientX, y: event.clientY, yaw: spatialCamera.yaw, pitch: spatialCamera.pitch};
    stage.classList.add("dragging");
    stage.setPointerCapture(event.pointerId);
  });
  stage.addEventListener("pointermove", function (event) {
    if (!spatialDrag) return;
    spatialCamera.yaw = spatialDrag.yaw + (event.clientX - spatialDrag.x) * .006;
    spatialCamera.pitch = Math.max(-1.35, Math.min(1.35, spatialDrag.pitch + (event.clientY - spatialDrag.y) * .005));
    renderSpatial();
  });
  function stopSpatialDrag() { spatialDrag = null; stage.classList.remove("dragging"); }
  stage.addEventListener("pointerup", stopSpatialDrag);
  stage.addEventListener("pointercancel", stopSpatialDrag);
  stage.addEventListener("wheel", function (event) {
    if (spatialMode === "flow") return;
    event.preventDefault();
    spatialCamera.scale = Math.max(.58, Math.min(1.65, spatialCamera.scale * (event.deltaY > 0 ? .92 : 1.08)));
    renderSpatial();
  }, {passive: false});
  document.getElementById("drawerClose").addEventListener("click", function () {
    selectedId = null;
    closeDrawer();
    renderWorkspace();
  });
  document.getElementById("drawerBackdrop").addEventListener("click", function () {
    selectedId = null;
    closeDrawer();
    renderWorkspace();
  });
  document.querySelectorAll("[data-workspace-mode]").forEach(function (tab) {
    tab.addEventListener("click", function () { activateWorkspaceMode(tab.dataset.workspaceMode); });
  });
  window.addEventListener("resize", function () { window.clearTimeout(window.__acgResizeTimer); window.__acgResizeTimer = window.setTimeout(renderWorkspace, 100); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      selectedId = null;
      closeDrawer();
      renderWorkspace();
    } else if (event.key === "/" && document.activeElement !== document.getElementById("search")) {
      event.preventDefault();
      document.getElementById("search").focus();
    } else if (event.key === "0") {
      resetSpatialCamera();
      renderSpatial();
    } else if (spatialMode !== "flow" && (event.key === "+" || event.key === "=")) {
      spatialCamera.scale = Math.min(1.65, spatialCamera.scale + .1);
      renderSpatial();
    } else if (spatialMode !== "flow" && event.key === "-") {
      spatialCamera.scale = Math.max(.58, spatialCamera.scale - .1);
      renderSpatial();
    }
  });
  if (window.matchMedia) {
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (motionQuery.addEventListener) motionQuery.addEventListener("change", renderWorkspace);
    else if (motionQuery.addListener) motionQuery.addListener(renderWorkspace);
  }
}
init();
</script>
</body>
</html>
"""


def _json_for_html(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def render_html(
    graph: dict[str, Any],
    events: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    *,
    title: str,
    display_locales: dict[str, dict[str, Any]] | None = None,
    default_locale: str = "zh-CN",
) -> str:
    return (
        HTML_TEMPLATE.replace("__TITLE__", html.escape(title))
        .replace("__GRAPH_JSON__", _json_for_html(graph))
        .replace("__EVENTS_JSON__", _json_for_html(events))
        .replace("__FINDINGS_JSON__", _json_for_html(findings))
        .replace("__DISPLAY_LOCALES_JSON__", _json_for_html(display_locales or {}))
        .replace("__SOURCE_TITLE_JSON__", _json_for_html(title))
        .replace("__DEFAULT_LOCALE_JSON__", _json_for_html(default_locale))
    )


def write_projection(
    out_dir: str | Path,
    *,
    graph: dict[str, Any],
    events: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    title: str,
    display_locales: dict[str, dict[str, Any]] | None = None,
    default_locale: str = "zh-CN",
) -> dict[str, Any]:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    outputs = {
        "graph.json": json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "graph.mmd": render_mermaid(graph),
        "graph.html": render_html(
            graph,
            events,
            findings,
            title=title,
            display_locales=display_locales,
            default_locale=default_locale,
        ),
        "lint.json": json.dumps(findings, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    }
    for name, content in outputs.items():
        atomic_write_text(target / name, content)

    receipt = {
        "schema_version": SCHEMA_VERSION,
        "graph_id": graph["graph_id"],
        "projected_from": graph.get("source_ledger"),
        "generated_at": graph["generated_at"],
        "display": {
            "default_locale": default_locale,
            "locales": sorted((display_locales or {}).keys()),
            "style_reference": "ACG three-layer workbench with spatial-0.2 strict orthogonal auxiliary view and independent runtime trace",
        },
        "outputs": {
            name: {"sha256": sha256_file(target / name), "size_bytes": (target / name).stat().st_size}
            for name in sorted(outputs)
        },
        "lint": {
            "errors": sum(item["severity"] == "error" for item in findings),
            "warnings": sum(item["severity"] == "warning" for item in findings),
        },
    }
    atomic_write_text(target / "projection-receipt.json", canonical_json(receipt) + "\n")
    return receipt
