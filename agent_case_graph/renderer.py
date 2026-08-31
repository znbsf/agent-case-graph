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
.summary-chip, .event-chip, .finding-chip {
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
.spatial-panel { min-height: 650px; background: var(--surface-soft); }
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
.spatial-stage {
  position: relative;
  min-height: 610px;
  height: calc(100vh - 235px);
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
.spatial-svg, .spatial-node-layer { position: absolute; inset: 0; width: 100%; height: 100%; }
.spatial-svg { overflow: visible; }
.spatial-node-layer { pointer-events: none; }
.spatial-plane { stroke-width: 1.2; vector-effect: non-scaling-stroke; transition: opacity .18s ease; }
.spatial-axis { fill: none; stroke-width: 2; vector-effect: non-scaling-stroke; }
.spatial-axis-label { font-size: 10px; font-weight: 800; paint-order: stroke; stroke: var(--canvas); stroke-width: 3px; }
.spatial-edge { fill: none; stroke-width: 1.45; vector-effect: non-scaling-stroke; }
.spatial-edge.dim { opacity: .08 !important; }
.spatial-edge.selected { stroke-width: 3; opacity: 1 !important; }
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
.spatial-node.projection-copy { border-style: dashed; }
.spatial-node-top { display: flex; align-items: center; justify-content: space-between; gap: 4px; color: var(--muted); font-size: 7.5px; font-weight: 760; }
.spatial-node-title { display: -webkit-box; margin-top: 3px; overflow: hidden; font-size: 9.5px; font-weight: 680; line-height: 1.3; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.spatial-node-status { width: 7px; height: 7px; border-radius: 999px; background: var(--node-color); box-shadow: 0 0 0 3px color-mix(in srgb, var(--node-color) 14%, transparent); }
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
.drawer-aux { display: grid; gap: 10px; margin-top: 14px; }
.drawer-panel-list { display: grid; gap: 8px; }
.drawer-panel-list .event, .drawer-panel-list .finding { margin: 0; padding: 10px; }
.event, .finding {
  max-width: 1060px;
  margin: 0 auto 10px;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 14px;
  background: var(--surface);
  box-shadow: 0 5px 14px rgba(35, 52, 73, .04);
}
.event-meta, .finding-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; color: var(--muted); font-size: 10px; }
.event-title, .finding-title { font-weight: 680; }
.event-detail, .finding-original { margin-top: 5px; color: var(--muted); font-size: 12px; line-height: 1.45; }
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
  .spatial-stage { height: calc(100vh - 275px); }
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
  .spatial-stage { min-height: 560px; height: 68vh; }
  .spatial-node { width: 108px; max-width: 30vw; }
  .spatial-hud-left { max-width: 245px; }
  .spatial-loop { grid-template-columns: 1fr; }
  .spatial-loop-arrow { transform: rotate(90deg); }
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
        <button class="tab active" type="button" role="tab" aria-selected="true" data-spatial-mode="orthogonal" data-i18n="tabOrthogonal">正交三面</button>
        <button class="tab" type="button" role="tab" aria-selected="false" data-spatial-mode="parallel" data-i18n="tabParallel">平行三层</button>
      </div>
      <div class="filters">
        <div class="search-wrap" id="searchWrap"><input id="search" type="search" placeholder="搜索节点 ID、类型、标签或属性" autocomplete="off"></div>
        <select id="spatialRunFilter" class="filter-control"><option value="">最新运行</option></select>
        <select id="relationFilter" class="filter-control">
          <option value="story" selected>主线关系</option>
          <option value="all">全部关系</option>
        </select>
        <button id="timelineButton" class="toolbar-action" type="button" data-i18n="timelineButton">运行记录</button>
        <button id="qualityButton" class="toolbar-action" type="button" data-i18n="qualityButton">质量</button>
      </div>
    </div>

    <div class="view active" id="spatialView" role="tabpanel">
      <div class="spatial-panel">
        <div class="spatial-intro">
          <div>
            <h2 id="spatialTitle">三张正交语义面</h2>
            <p id="spatialSubtitle">Knowledge、Control、Execution 在共享接口上交汇；箭头与流动粒子只来自显式关系。</p>
          </div>
          <span class="spatial-protocol">spatial-0.1</span>
        </div>
        <div id="spatialStage" class="spatial-stage" aria-label="三层空间图">
          <svg id="spatialSvg" class="spatial-svg" aria-hidden="true"></svg>
          <div id="spatialNodeLayer" class="spatial-node-layer"></div>
          <div id="spatialEmpty" class="spatial-empty" hidden></div>

          <div class="spatial-hud spatial-hud-left">
            <div class="spatial-card">
              <div class="spatial-loop" aria-label="信息闭环">
                <span data-i18n="loopKnowledge">Knowledge 知识</span><span class="spatial-loop-arrow">→</span>
                <span data-i18n="loopControl">Control 决策</span><span class="spatial-loop-arrow">→</span>
                <span data-i18n="loopExecution">Execution 执行</span>
              </div>
              <div class="spatial-loop-sub" data-i18n="loopHint">执行结果再回到 Knowledge，形成可复用经验。动态粒子表示所选 Run 的实际显式流向。</div>
              <div id="spatialLayerSummary" class="spatial-layer-summary"></div>
            </div>
          </div>

          <div class="spatial-hud spatial-hud-right">
            <div class="spatial-card spatial-layer-buttons" aria-label="空间投影层">
              <button class="spatial-layer-button active" type="button" data-spatial-layer="all" data-i18n="layerAll">全部</button>
              <button class="spatial-layer-button" type="button" data-spatial-layer="knowledge">Knowledge</button>
              <button class="spatial-layer-button" type="button" data-spatial-layer="control">Control</button>
              <button class="spatial-layer-button" type="button" data-spatial-layer="execution">Execution</button>
            </div>
          </div>

          <div class="spatial-hud spatial-hud-bottom">
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
    <div id="timeline" class="drawer-panel-list" hidden></div>
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

const UI = {
  "zh-CN": {
    languageLabel: "显示语言",
    themeToggle: "切换主题",
    tabOrthogonal: "正交三面",
    tabParallel: "平行三层",
    orthogonalTitle: "三张正交语义面",
    orthogonalSubtitle: "XY 是 Knowledge，XZ 是 Control，YZ 是 Execution；共享轴就是层间接口。",
    parallelTitle: "三张平行工作层",
    parallelSubtitle: "Knowledge、Control、Execution 分层排布，跨层箭头显示信息实际去向。",
    latestRun: "最新运行",
    layerAll: "全部",
    loopKnowledge: "Knowledge 知识",
    loopControl: "Control 决策",
    loopExecution: "Execution 执行",
    loopHint: "执行结果再回到 Knowledge，形成可复用经验。动态粒子只表示所选 Run 的显式流向。",
    timelineButton: "运行记录",
    qualityButton: "质量",
    timelineTitle: "运行与事件记录",
    qualityTitle: "质量检查",
    spatialNoData: "当前筛选没有可展示的节点",
    executionNoRuntime: "此图没有真实 Execution runtime 覆盖",
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
    noEvents: "没有事件",
    noFindings: "没有质量问题",
    lintHealthy: "当前投影没有错误或警告。",
    lintIssues: "当前投影包含 {errors} 个错误、{warnings} 个警告。",
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
    capturedAs: "采集模式",
    actor: "参与者"
  },
  "en-US": {
    languageLabel: "Display language",
    themeToggle: "Toggle theme",
    tabOrthogonal: "Orthogonal Planes",
    tabParallel: "Parallel Layers",
    orthogonalTitle: "Three orthogonal semantic planes",
    orthogonalSubtitle: "XY is Knowledge, XZ is Control, and YZ is Execution; shared axes are layer interfaces.",
    parallelTitle: "Three parallel work layers",
    parallelSubtitle: "Knowledge, Control, and Execution are separated while cross-layer arrows show actual destinations.",
    latestRun: "Latest run",
    layerAll: "All",
    loopKnowledge: "Knowledge",
    loopControl: "Control",
    loopExecution: "Execution",
    loopHint: "Execution results return to Knowledge as reusable experience. Moving particles show only explicit flow for the selected Run.",
    timelineButton: "Run log",
    qualityButton: "Quality",
    timelineTitle: "Run and event log",
    qualityTitle: "Quality checks",
    spatialNoData: "No node matches the current filters",
    executionNoRuntime: "This graph has no real Execution runtime overlay",
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
    noEvents: "No events",
    noFindings: "No quality findings",
    lintHealthy: "The current projection has no errors or warnings.",
    lintIssues: "The current projection has {errors} errors and {warnings} warnings.",
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
    capturedAs: "capture mode",
    actor: "actor"
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
const primaryEdgeTypes = new Set(["targets", "has_run", "precedes", "uses", "invokes", "produces", "supports", "refutes", "explains", "approved_by", "guarded_by", "modifies", "checks", "verified_by", "satisfies", "blocked_by"]);

let selectedId = null;
let currentLocale = resolveInitialLocale();
let spatialMode = "orthogonal";
let spatialLayer = "all";
let spatialCamera = {yaw: -0.62, pitch: 0.48, scale: 1};
let spatialDrag = null;
let activeAuxPanel = null;
let spatialRenderState = {instances: [], instanceByKey: new Map(), visibleIds: new Set()};

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
  knowledge: "var(--reason)", control: "var(--accent)", execution: "var(--execute)"
};
const SPATIAL_FLOW_COLORS = {
  knowledge: "var(--reason)", control: "var(--accent)", execution: "var(--execute)",
  "knowledge-control": "var(--scope)", "control-execution": "var(--evidence)",
  "execution-knowledge": "var(--knowledge)"
};
const SPATIAL_FLOW_TYPES = new Set([
  "has_run", "contains", "precedes", "targets", "uses", "invokes", "produces",
  "supports", "refutes", "explains", "approved_by", "guarded_by", "modifies",
  "checks", "verified_by", "satisfies", "blocked_by"
]);

function fallbackSpatialMembership(node) {
  const controlTypes = new Set(["Run", "Step", "Capability", "Agent", "Skill", "Tool", "Target", "Action", "Approval", "Policy", "Verification"]);
  const result = [];
  if (node.type !== "Run" && node.type !== "Step") result.push("knowledge");
  if (controlTypes.has(node.type)) result.push("control");
  return result.length ? result : ["knowledge"];
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
  return Array.isArray(membership) && membership.length ? membership.filter(function (layer) { return layer !== "execution"; }) : fallbackSpatialMembership(node);
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
  const result = canonicalMembership(node).slice();
  if (runtimeMap.has(node.id)) result.push("execution");
  return ["knowledge", "control", "execution"].filter(function (layer) { return result.includes(layer); });
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
function axisPositions(count, span) {
  const result = [];
  for (let index = 0; index < count; index += 1) {
    let value = -span + ((index + 1) * span * 2 / (count + 1));
    if (Math.abs(value) < 30) value += index % 2 ? 38 : -38;
    result.push(value);
  }
  return result;
}
function gridPositions(count, width, height) {
  if (!count) return [];
  const columns = Math.max(1, Math.ceil(Math.sqrt(count * 1.45)));
  const rows = Math.ceil(count / columns);
  return Array.from({length: count}, function (_, index) {
    const column = index % columns;
    const row = Math.floor(index / columns);
    return {
      u: columns === 1 ? 0 : -width / 2 + column * width / (columns - 1),
      v: rows === 1 ? 0 : -height / 2 + row * height / (rows - 1)
    };
  });
}
function buildOrthogonalInstances(nodes, runtimeMap) {
  if (spatialLayer !== "all") {
    const positions = gridPositions(nodes.length, 500, 350);
    return nodes.map(function (node, index) {
      const p = positions[index];
      const point = spatialLayer === "knowledge" ? {x: p.u, y: p.v, z: 0}
        : spatialLayer === "control" ? {x: p.u, y: 0, z: p.v}
        : {x: 0, y: p.u, z: p.v};
      return {key: node.id + "::" + spatialLayer, sourceId: node.id, node: node, layers: [spatialLayer], point: point};
    });
  }
  const buckets = {knowledge: [], control: [], execution: [], "knowledge-control": [], "control-execution": [], "execution-knowledge": [], origin: []};
  const knowledgeControlTypes = new Set(["Goal", "Decision", "AcceptanceCriterion", "Policy"]);
  const controlExecutionTypes = new Set(["Step", "Action", "Tool", "Approval", "Target", "Verification"]);
  const executionKnowledgeTypes = new Set(["Artifact", "Observation", "VerificationReceipt"]);
  nodes.forEach(function (node) {
    const membership = effectiveMembership(node, runtimeMap);
    let bucket = "knowledge";
    if (node.id === graph.root_id) bucket = "origin";
    else if (knowledgeControlTypes.has(node.type) && membership.includes("knowledge") && membership.includes("control")) bucket = "knowledge-control";
    else if (runtimeMap.has(node.id) && controlExecutionTypes.has(node.type)) bucket = "control-execution";
    else if (runtimeMap.has(node.id) && executionKnowledgeTypes.has(node.type)) bucket = "execution-knowledge";
    else if (runtimeMap.has(node.id)) bucket = "execution";
    else if (membership.includes("control")) bucket = "control";
    buckets[bucket].push({node: node, membership: membership});
  });
  const result = [];
  ["knowledge", "control", "execution"].forEach(function (layer) {
    const positions = gridPositions(buckets[layer].length, 450, 330);
    buckets[layer].forEach(function (item, index) {
      const p = positions[index];
      const point = layer === "knowledge" ? {x: p.u, y: p.v, z: 0}
        : layer === "control" ? {x: p.u, y: 0, z: p.v}
        : {x: 0, y: p.u, z: p.v};
      result.push({key: item.node.id + "::" + layer, sourceId: item.node.id, node: item.node, layers: item.membership, displayLayer: layer, point: point});
    });
  });
  [["knowledge-control", "x"], ["control-execution", "z"], ["execution-knowledge", "y"]].forEach(function (entry) {
    const bucket = buckets[entry[0]];
    const values = axisPositions(bucket.length, 255);
    bucket.forEach(function (item, index) {
      const point = {x: 0, y: 0, z: 0};
      point[entry[1]] = values[index];
      result.push({key: item.node.id + "::" + entry[0], sourceId: item.node.id, node: item.node, layers: item.membership, displayLayer: entry[0], point: point});
    });
  });
  buckets.origin.forEach(function (item) {
    result.push({key: item.node.id + "::origin", sourceId: item.node.id, node: item.node, layers: item.membership, displayLayer: "origin", point: {x: 0, y: 0, z: 0}});
  });
  return result;
}
function buildParallelInstances(nodes, runtimeMap) {
  const byLayer = {knowledge: [], control: [], execution: []};
  nodes.forEach(function (node) {
    effectiveMembership(node, runtimeMap).forEach(function (layer) { byLayer[layer].push(node); });
  });
  const zByLayer = {knowledge: -290, control: 0, execution: 290};
  const result = [];
  Object.keys(byLayer).forEach(function (layer) {
    const positions = gridPositions(byLayer[layer].length, 500, 330);
    byLayer[layer].forEach(function (node, index) {
      result.push({
        key: node.id + "::" + layer, sourceId: node.id, node: node, layers: [layer],
        point: {x: positions[index].u, y: positions[index].v, z: zByLayer[layer]},
        projectionCopy: effectiveMembership(node, runtimeMap).length > 1
      });
    });
  });
  return result;
}
function projectSpatialPoint(point, width, height) {
  const cosYaw = Math.cos(spatialCamera.yaw);
  const sinYaw = Math.sin(spatialCamera.yaw);
  const x1 = point.x * cosYaw + point.z * sinYaw;
  const z1 = -point.x * sinYaw + point.z * cosYaw;
  const cosPitch = Math.cos(spatialCamera.pitch);
  const sinPitch = Math.sin(spatialCamera.pitch);
  const y1 = point.y * cosPitch - z1 * sinPitch;
  const depth = point.y * sinPitch + z1 * cosPitch;
  const baseScale = Math.min(width / 1040, height / 720) * spatialCamera.scale;
  return {x: width / 2 + x1 * baseScale, y: height / 2 - y1 * baseScale + 18, depth: depth};
}
function relaxSpatialLabels(projected, instances, width, height) {
  for (let pass = 0; pass < 42; pass += 1) {
    for (let leftIndex = 0; leftIndex < instances.length; leftIndex += 1) {
      const left = projected.get(instances[leftIndex].key);
      for (let rightIndex = leftIndex + 1; rightIndex < instances.length; rightIndex += 1) {
        const right = projected.get(instances[rightIndex].key);
        const dx = right.x - left.x;
        const dy = right.y - left.y;
        if (Math.abs(dx) >= 142 || Math.abs(dy) >= 66) continue;
        const direction = dy === 0 ? (rightIndex % 2 ? 1 : -1) : Math.sign(dy);
        const push = (66 - Math.abs(dy)) / 2 + .8;
        left.y -= direction * push;
        right.y += direction * push;
        const horizontalPush = (142 - Math.abs(dx)) * .05;
        const horizontalDirection = dx === 0 ? (rightIndex % 2 ? 1 : -1) : Math.sign(dx);
        left.x -= horizontalDirection * horizontalPush;
        right.x += horizontalDirection * horizontalPush;
      }
    }
    instances.forEach(function (instance) {
      const point = projected.get(instance.key);
      point.x = Math.max(76, Math.min(width - 76, point.x));
      point.y = Math.max(32, Math.min(height - 34, point.y));
      if (point.x < 360 && point.y < 118) point.y = 128;
      if (point.x > width - 130 && point.y < 175) point.y = 185;
    });
  }
}
function svgElement(name, attrs) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attrs || {}).forEach(function (entry) { element.setAttribute(entry[0], String(entry[1])); });
  return element;
}
function spatialPlaneDefinitions() {
  const size = 315;
  if (spatialMode === "parallel") {
    return [
      {layer: "knowledge", label: "Knowledge", points: [{x:-size,y:-size,z:-290},{x:size,y:-size,z:-290},{x:size,y:size,z:-290},{x:-size,y:size,z:-290}]},
      {layer: "control", label: "Control", points: [{x:-size,y:-size,z:0},{x:size,y:-size,z:0},{x:size,y:size,z:0},{x:-size,y:size,z:0}]},
      {layer: "execution", label: "Execution", points: [{x:-size,y:-size,z:290},{x:size,y:-size,z:290},{x:size,y:size,z:290},{x:-size,y:size,z:290}]}
    ];
  }
  return [
    {layer: "knowledge", label: "XY · Knowledge", points: [{x:-size,y:-size,z:0},{x:size,y:-size,z:0},{x:size,y:size,z:0},{x:-size,y:size,z:0}]},
    {layer: "control", label: "XZ · Control", points: [{x:-size,y:0,z:-size},{x:size,y:0,z:-size},{x:size,y:0,z:size},{x:-size,y:0,z:size}]},
    {layer: "execution", label: "YZ · Execution", points: [{x:0,y:-size,z:-size},{x:0,y:size,z:-size},{x:0,y:size,z:size},{x:0,y:-size,z:size}]}
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
function spatialEdgePath(from, to) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.max(1, Math.hypot(dx, dy));
  const bend = Math.min(28, length * .12);
  const midX = (from.x + to.x) / 2 - dy / length * bend;
  const midY = (from.y + to.y) / 2 + dx / length * bend;
  return "M " + from.x.toFixed(1) + " " + from.y.toFixed(1) + " Q " + midX.toFixed(1) + " " + midY.toFixed(1) + " " + to.x.toFixed(1) + " " + to.y.toFixed(1);
}
function resetSpatialCamera() {
  if (spatialLayer === "knowledge") spatialCamera = {yaw: 0, pitch: 0, scale: 1.08};
  else if (spatialMode === "orthogonal" && spatialLayer === "control") spatialCamera = {yaw: 0, pitch: -Math.PI / 2, scale: 1.08};
  else if (spatialMode === "orthogonal" && spatialLayer === "execution") spatialCamera = {yaw: -Math.PI / 2, pitch: 0, scale: 1.08};
  else if (spatialMode === "parallel" && spatialLayer !== "all") spatialCamera = {yaw: 0, pitch: 0, scale: 1.08};
  else spatialCamera = spatialMode === "orthogonal" ? {yaw: -0.62, pitch: 0.48, scale: 1} : {yaw: -0.62, pitch: 0.38, scale: .92};
}
function renderSpatial() {
  const stage = document.getElementById("spatialStage");
  const svg = document.getElementById("spatialSvg");
  const nodeLayer = document.getElementById("spatialNodeLayer");
  const width = Math.max(640, stage.clientWidth || 1200);
  const height = Math.max(520, stage.clientHeight || 680);
  svg.setAttribute("viewBox", "0 0 " + width + " " + height);
  clearElement(svg);
  clearElement(nodeLayer);
  const snapshot = selectedRuntimeSnapshot();
  const runtimeMap = runtimeEntryMap(snapshot);
  let nodes = selectedRunScope(snapshot);
  if (spatialLayer !== "all") nodes = nodes.filter(function (node) { return effectiveMembership(node, runtimeMap).includes(spatialLayer); });
  let instances = spatialMode === "orthogonal" ? buildOrthogonalInstances(nodes, runtimeMap) : buildParallelInstances(nodes, runtimeMap);
  if (spatialLayer !== "all") instances = instances.filter(function (instance) { return instance.layers.includes(spatialLayer); });
  const projected = new Map();
  instances.forEach(function (instance) { projected.set(instance.key, projectSpatialPoint(instance.point, width, height)); });
  relaxSpatialLabels(projected, instances, width, height);
  spatialRenderState = {instances: instances, instanceByKey: new Map(instances.map(function (item) { return [item.key, item]; })), visibleIds: new Set(nodes.map(function (node) { return node.id; }))};

  const defs = svgElement("defs");
  const marker = svgElement("marker", {id: "spatialArrow", markerWidth: 8, markerHeight: 8, refX: 7, refY: 4, orient: "auto", markerUnits: "strokeWidth"});
  marker.appendChild(svgElement("path", {d: "M 0 0 L 8 4 L 0 8 z", fill: "context-stroke"}));
  defs.appendChild(marker);
  svg.appendChild(defs);

  const visiblePlanes = spatialPlaneDefinitions().filter(function (plane) { return spatialLayer === "all" || plane.layer === spatialLayer; });
  visiblePlanes.map(function (plane) {
    const points = plane.points.map(function (point) { return projectSpatialPoint(point, width, height); });
    return {plane: plane, points: points, depth: points.reduce(function (sum, point) { return sum + point.depth; }, 0) / points.length};
  }).sort(function (left, right) { return left.depth - right.depth; }).forEach(function (entry) {
    const color = SPATIAL_LAYER_COLORS[entry.plane.layer];
    const polygon = svgElement("polygon", {class: "spatial-plane", points: entry.points.map(function (point) { return point.x.toFixed(1) + "," + point.y.toFixed(1); }).join(" ")});
    polygon.setAttribute("style", "fill:color-mix(in srgb," + color + " 7%,transparent);stroke:color-mix(in srgb," + color + " 55%,transparent)");
    svg.appendChild(polygon);
    const anchor = entry.points[2];
    const label = svgElement("text", {class: "spatial-axis-label", x: anchor.x - 8, y: anchor.y - 9, fill: color, "text-anchor": "end"});
    label.textContent = entry.plane.label;
    svg.appendChild(label);
  });

  if (spatialMode === "orthogonal" && spatialLayer === "all") {
    [[{x:-340,y:0,z:0},{x:340,y:0,z:0},"X · K↔C"],[{x:0,y:-340,z:0},{x:0,y:340,z:0},"Y · E↔K"],[{x:0,y:0,z:-340},{x:0,y:0,z:340},"Z · C↔E"]].forEach(function (axis) {
      const from = projectSpatialPoint(axis[0], width, height);
      const to = projectSpatialPoint(axis[1], width, height);
      svg.appendChild(svgElement("line", {class: "spatial-axis", x1: from.x, y1: from.y, x2: to.x, y2: to.y, stroke: "var(--edge)"}));
      const label = svgElement("text", {class: "spatial-axis-label", x: to.x, y: to.y - 7, fill: "var(--muted)", "text-anchor": "middle"});
      label.textContent = axis[2];
      svg.appendChild(label);
    });
  }

  if (spatialMode === "parallel" && spatialLayer === "all") {
    const copies = new Map();
    instances.forEach(function (instance) {
      if (!copies.has(instance.sourceId)) copies.set(instance.sourceId, []);
      copies.get(instance.sourceId).push(instance);
    });
    copies.forEach(function (items) {
      if (items.length < 2) return;
      items.sort(function (left, right) { return left.point.z - right.point.z; });
      for (let index = 0; index < items.length - 1; index += 1) {
        const from = projected.get(items[index].key);
        const to = projected.get(items[index + 1].key);
        svg.appendChild(svgElement("line", {x1: from.x, y1: from.y, x2: to.x, y2: to.y, stroke: "var(--edge-soft)", "stroke-dasharray": "3 6", opacity: selectedId === items[index].sourceId ? .85 : .22}));
      }
    });
  }

  const relationMode = document.getElementById("relationFilter").value;
  const runScope = new Set([snapshot && snapshot.run_id].filter(Boolean));
  runtimeMap.forEach(function (_, id) { runScope.add(id); });
  graph.edges.forEach(function (edge) { if (snapshot && edge.from === snapshot.run_id && edge.type === "contains") runScope.add(edge.to); });
  const related = selectedId ? adjacentIds(selectedId) : null;
  spatialCatalogRelations().filter(function (relation) {
    if (!spatialRenderState.visibleIds.has(relation.from) || !spatialRenderState.visibleIds.has(relation.to)) return false;
    return relationMode === "all" || primaryEdgeTypes.has(relation.type) || (relation.type === "contains" && relation.from === (snapshot && snapshot.run_id));
  }).forEach(function (relation, index) {
    const flowKind = relation.flow_kind || (primaryEdgeTypes.has(relation.type) ? "control" : "knowledge");
    const fromInstance = chooseSpatialInstance(instances, relation.from, flowKind);
    const toInstance = chooseSpatialInstance(instances, relation.to, flowKind);
    if (!fromInstance || !toInstance || fromInstance.key === toInstance.key) return;
    const from = projected.get(fromInstance.key);
    const to = projected.get(toInstance.key);
    const pathText = spatialEdgePath(from, to);
    const selected = selectedId && (relation.from === selectedId || relation.to === selectedId);
    const dim = related && (!related.has(relation.from) || !related.has(relation.to));
    const color = SPATIAL_FLOW_COLORS[flowKind] || "var(--edge)";
    const path = svgElement("path", {class: "spatial-edge" + (selected ? " selected" : "") + (dim ? " dim" : ""), d: pathText, stroke: color, opacity: selected ? 1 : .56, "marker-end": "url(#spatialArrow)"});
    path.appendChild(document.createElementNS("http://www.w3.org/2000/svg", "title")).textContent = edgeTypeLabel(relation.type) + ": " + relation.from + " → " + relation.to;
    svg.appendChild(path);
    const explicitRunFlow = Boolean(snapshot && snapshot.has_runtime_overlay && relation.actual !== false && SPATIAL_FLOW_TYPES.has(relation.type) && runScope.has(relation.from) && runScope.has(relation.to));
    if ((relation.animated || explicitRunFlow) && !dim) {
      const particle = svgElement("circle", {r: selected ? 4 : 3, fill: color, opacity: .92});
      const motion = svgElement("animateMotion", {dur: (2.7 + (index % 4) * .45) + "s", repeatCount: "indefinite", path: pathText});
      particle.appendChild(motion);
      svg.appendChild(particle);
    }
  });

  instances.slice().sort(function (left, right) { return projected.get(left.key).depth - projected.get(right.key).depth; }).forEach(function (instance, index) {
    const screen = projected.get(instance.key);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "spatial-node" + (instance.projectionCopy ? " projection-copy" : "") + (selectedId === instance.sourceId ? " selected" : "") + (related && !related.has(instance.sourceId) ? " dim" : "");
    button.dataset.nodeId = instance.sourceId;
    button.style.left = screen.x + "px";
    button.style.top = screen.y + "px";
    button.style.zIndex = String(30 + index);
    const primaryLayer = instance.layers[instance.layers.length - 1] || "knowledge";
    button.style.setProperty("--node-color", SPATIAL_LAYER_COLORS[primaryLayer]);
    const top = document.createElement("div");
    top.className = "spatial-node-top";
    const runtimeEntry = runtimeMap.get(instance.sourceId);
    top.append(createText("span", "", nodeTypeLabel(instance.node.type)), createText("span", "", runtimeEntry ? statusLabel(runtimeEntry.runtime_lane) : instance.layers.map(function (layer) { return layer[0].toUpperCase(); }).join("/")));
    button.append(top, createText("div", "spatial-node-title", localizedNodeLabel(instance.node)));
    button.title = instance.node.id + " · " + instance.layers.join(" / ");
    button.addEventListener("click", function (event) { event.stopPropagation(); selectNode(instance.sourceId); });
    nodeLayer.appendChild(button);
  });

  const empty = document.getElementById("spatialEmpty");
  empty.textContent = message("spatialNoData");
  empty.hidden = instances.length > 0;
  const summary = document.getElementById("spatialLayerSummary");
  clearElement(summary);
  ["knowledge", "control", "execution"].forEach(function (layer) {
    const count = nodes.filter(function (node) { return effectiveMembership(node, runtimeMap).includes(layer); }).length;
    summary.appendChild(createText("span", "spatial-layer-chip", layer[0].toUpperCase() + " · " + count));
  });
  if (snapshot) summary.appendChild(createText("span", "spatial-layer-chip", (snapshot.run_label || snapshot.run_id)));
  if (!snapshot || !snapshot.has_runtime_overlay) summary.appendChild(createText("span", "spatial-layer-chip", message("executionNoRuntime")));
  document.getElementById("spatialTitle").textContent = message(spatialMode === "orthogonal" ? "orthogonalTitle" : "parallelTitle");
  document.getElementById("spatialSubtitle").textContent = message(spatialMode === "orthogonal" ? "orthogonalSubtitle" : "parallelSubtitle");
}
function selectNode(id) {
  selectedId = selectedId === id ? null : id;
  if (selectedId) openDrawer(nodeById.get(selectedId)); else closeDrawer();
  renderSpatial();
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
  activeAuxPanel = kind;
  document.getElementById("drawerNodeContent").hidden = true;
  document.getElementById("drawerAux").hidden = false;
  document.getElementById("timeline").hidden = kind !== "timeline";
  document.getElementById("findings").hidden = kind !== "quality";
  document.getElementById("drawerKicker").textContent = kind === "timeline" ? "Ledger" : "Lint";
  document.getElementById("drawerTitle").textContent = message(kind === "timeline" ? "timelineTitle" : "qualityTitle");
  if (kind === "timeline") renderTimeline(); else renderFindings();
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
        renderSpatial();
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
  const health = document.getElementById("healthText");
  if (health) {
    health.textContent = errors || warnings
      ? message("lintIssues", {errors: errors, warnings: warnings})
      : message("lintHealthy");
  }
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
function renderTimeline() {
  const target = document.getElementById("timeline");
  clearElement(target);
  if (!events.length) {
    target.appendChild(createText("div", "empty", message("noEvents")));
    return;
  }
  events.forEach(function (event) {
    const item = document.createElement("article");
    item.className = "event";
    const meta = document.createElement("div");
    meta.className = "event-meta";
    [
      "#" + event.sequence,
      event.occurred_at,
      message("actor") + ": " + actorLabel(event.actor.type) + ":" + event.actor.id,
      message("capturedAs") + ": " + modeLabel(event.provenance.capture_mode)
    ].forEach(function (text) { meta.appendChild(createText("span", "event-chip", text)); });
    item.append(meta, createText("div", "event-title", eventKindLabel(event.kind)), createText("div", "event-detail", eventDetail(event)));
    target.appendChild(item);
  });
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
  document.getElementById("drawerClose").setAttribute("aria-label", message("close"));
  document.getElementById("resetCamera").title = message("resetCamera");
  document.getElementById("rotateLeft").title = message("rotateLeft");
  document.getElementById("rotateRight").title = message("rotateRight");
  document.getElementById("rotateUp").title = message("rotateUp");
  document.getElementById("rotateDown").title = message("rotateDown");
  updateThemeLabel();
  rebuildSpatialRunOptions();
  renderSummary();
}
function setLocale(locale) {
  currentLocale = locale === "en-US" ? "en-US" : "zh-CN";
  try { localStorage.setItem("acg-locale", currentLocale); } catch (_) {}
  updateStaticText();
  renderTimeline();
  renderFindings();
  renderSpatial();
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
function activateSpatialMode(mode) {
  spatialMode = mode === "parallel" ? "parallel" : "orthogonal";
  document.querySelectorAll(".tab").forEach(function (item) {
    const active = item.dataset.spatialMode === spatialMode;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  resetSpatialCamera();
  renderSpatial();
}
function init() {
  updateStaticText();
  renderTimeline();
  renderFindings();
  resetSpatialCamera();
  renderSpatial();
  document.getElementById("languageSelect").addEventListener("change", function (event) { setLocale(event.target.value); });
  document.getElementById("themeToggle").addEventListener("click", function () { toggleTheme(); renderSpatial(); });
  document.getElementById("search").addEventListener("input", renderSpatial);
  document.getElementById("spatialRunFilter").addEventListener("change", function () { selectedId = null; closeDrawer(); renderSpatial(); });
  document.getElementById("relationFilter").addEventListener("change", renderSpatial);
  document.getElementById("timelineButton").addEventListener("click", function () { openAuxPanel("timeline"); });
  document.getElementById("qualityButton").addEventListener("click", function () { openAuxPanel("quality"); });
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
    event.preventDefault();
    spatialCamera.scale = Math.max(.58, Math.min(1.65, spatialCamera.scale * (event.deltaY > 0 ? .92 : 1.08)));
    renderSpatial();
  }, {passive: false});
  document.getElementById("drawerClose").addEventListener("click", function () {
    selectedId = null;
    closeDrawer();
    renderSpatial();
  });
  document.getElementById("drawerBackdrop").addEventListener("click", function () {
    selectedId = null;
    closeDrawer();
    renderSpatial();
  });
  document.querySelectorAll(".tab").forEach(function (tab) {
    tab.addEventListener("click", function () { activateSpatialMode(tab.dataset.spatialMode); });
  });
  window.addEventListener("resize", function () { window.clearTimeout(window.__acgResizeTimer); window.__acgResizeTimer = window.setTimeout(renderSpatial, 100); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      selectedId = null;
      closeDrawer();
      renderSpatial();
    } else if (event.key === "/" && document.activeElement !== document.getElementById("search")) {
      event.preventDefault();
      document.getElementById("search").focus();
    } else if (event.key === "0") {
      resetSpatialCamera();
      renderSpatial();
    } else if (event.key === "+" || event.key === "=") {
      spatialCamera.scale = Math.min(1.65, spatialCamera.scale + .1);
      renderSpatial();
    } else if (event.key === "-") {
      spatialCamera.scale = Math.max(.58, spatialCamera.scale - .1);
      renderSpatial();
    }
  });
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
            "style_reference": "ACG spatial-0.1 orthogonal planes and parallel layers; self-contained independent renderer",
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
