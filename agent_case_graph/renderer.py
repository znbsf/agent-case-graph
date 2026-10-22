"""Single offline HTML view of the canonical graph.

Layout is a plain layered DAG: a node's row is one below the deepest earlier
predecessor (ledger order breaks cycles), columns follow ledger order.  Page
position is never a fact; only drawn edges come from the ledger.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .ledger import atomic_write_text, canonical_json, sha256_file
from .model import SCHEMA_VERSION

NODE_W, NODE_H, GAP_X, GAP_Y, PAD = 200, 52, 28, 64, 24
PALETTE = ("#4c78a8", "#f58518", "#54a24b", "#b279a2", "#e45756", "#72b7b2", "#9d755d", "#eeca3b", "#ff9da6", "#bab0ac")


def layout(graph: dict[str, Any]) -> dict[str, tuple[int, int]]:
    order = {node["id"]: index for index, node in enumerate(graph["nodes"])}
    preds: dict[str, list[str]] = {node_id: [] for node_id in order}
    for edge in graph["edges"]:
        if edge["from"] in order and edge["to"] in order and order[edge["from"]] < order[edge["to"]]:
            preds[edge["to"]].append(edge["from"])
    rank: dict[str, int] = {}
    for node in graph["nodes"]:
        rank[node["id"]] = 1 + max((rank[p] for p in preds[node["id"]]), default=-1)
    columns: dict[int, int] = {}
    positions = {}
    for node in graph["nodes"]:
        row = rank[node["id"]]
        col = columns.get(row, 0)
        columns[row] = col + 1
        positions[node["id"]] = (PAD + col * (NODE_W + GAP_X), PAD + row * (NODE_H + GAP_Y))
    return positions


def _svg(graph: dict[str, Any], positions: dict[str, tuple[int, int]], colors: dict[str, str]) -> str:
    esc = html.escape
    width = max((x for x, _ in positions.values()), default=0) + NODE_W + PAD
    height = max((y for _, y in positions.values()), default=0) + NODE_H + PAD
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<defs><marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
             '<path d="M0,0L10,5L0,10z" fill="context-stroke"/></marker></defs>']
    for edge in graph["edges"]:
        if edge["from"] not in positions or edge["to"] not in positions:
            continue
        (x1, y1), (x2, y2) = positions[edge["from"]], positions[edge["to"]]
        sx, sy, tx, ty = x1 + NODE_W / 2, y1 + NODE_H, x2 + NODE_W / 2, y2
        bend = max(40, abs(ty - sy) / 2)
        css = "edge structural" if edge["type"] == "contains" else "edge"
        parts.append(f'<path class="{css}" data-edge="{esc(edge["id"])}" d="M{sx},{sy} C{sx},{sy + bend} {tx},{ty - bend} {tx},{ty}" marker-end="url(#arrow)">'
                     f'<title>{esc(edge["type"])}: {esc(edge["from"])} → {esc(edge["to"])}</title></path>')
    for node in graph["nodes"]:
        x, y = positions[node["id"]]
        label = node["label"] if len(node["label"]) <= 28 else node["label"][:27] + "…"
        state = node["attrs"].get("current_state") or node["attrs"].get("status") or ""
        parts.append(f'<g class="node" data-node="{esc(node["id"])}" transform="translate({x},{y})">'
                     f'<title>{esc(node["label"])}</title>'
                     f'<rect width="{NODE_W}" height="{NODE_H}" rx="6" style="--c:{colors[node["type"]]}"/>'
                     f'<text x="10" y="20" class="type">{esc(node["type"])}{" · " + esc(str(state)) if state else ""}</text>'
                     f'<text x="10" y="40">{esc(label)}</text></g>')
    parts.append("</svg>")
    return "".join(parts)


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>__TITLE__</title>
<style>
:root { --bg:#fff; --fg:#1d1d1f; --muted:#6e6e73; --line:#d2d2d7; --panel:#f5f5f7; }
@media (prefers-color-scheme: dark) { :root { --bg:#161617; --fg:#f5f5f7; --muted:#a1a1a6; --line:#424245; --panel:#1f1f21; } }
* { box-sizing: border-box; }
body { margin:0; font:14px/1.45 system-ui, sans-serif; background:var(--bg); color:var(--fg); display:grid; grid-template-rows:auto 1fr; height:100vh; }
header { padding:12px 16px; border-bottom:1px solid var(--line); }
header h1 { font-size:17px; margin:0 0 4px; }
.meta, .legend { color:var(--muted); font-size:12px; }
.legend span { display:inline-block; margin-right:10px; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:4px; vertical-align:-1px; }
.warn { color:#e45756; }
main { display:grid; grid-template-columns:1fr 340px; min-height:0; }
#canvas { overflow:auto; }
aside { border-left:1px solid var(--line); background:var(--panel); padding:12px 16px; overflow:auto; }
aside h2 { font-size:15px; margin:0 0 8px; word-break:break-word; }
aside pre { white-space:pre-wrap; word-break:break-word; font-size:12px; margin:0; }
aside li { margin:2px 0; word-break:break-word; }
.edge { fill:none; stroke:var(--muted); stroke-width:1.4; }
.edge.structural { stroke:var(--line); stroke-dasharray:4 4; }
.edge.hot { stroke:var(--fg); stroke-width:2.2; }
.node { cursor:pointer; }
.node rect { fill:var(--bg); stroke:var(--c); stroke-width:1.5; }
.node.selected rect { stroke-width:3.5; }
.node text { fill:var(--fg); font-size:12px; }
.node text.type { fill:var(--muted); font-size:11px; }
@media (max-width: 720px) { main { grid-template-columns:1fr; grid-template-rows:1fr 40vh; } aside { border-left:0; border-top:1px solid var(--line); } }
</style>
</head>
<body>
<header>
<h1>__TITLE__</h1>
<div class="meta">__META__</div>
<div class="legend">__LEGEND__</div>
</header>
<main>
<div id="canvas">__SVG__</div>
<aside id="detail"><p class="meta">点击节点查看属性、关系与来源记录。虚线为 contains（作用域，不表示因果）。</p>__LINT__</aside>
</main>
<script>
const GRAPH = __GRAPH_JSON__;
const nodes = new Map(GRAPH.nodes.map(n => [n.id, n]));
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const link = id => `<a href="#" data-goto="${esc(id)}">${esc(nodes.get(id)?.label ?? id)}</a>`;
function select(id) {
  const n = nodes.get(id);
  document.querySelectorAll(".node").forEach(g => g.classList.toggle("selected", g.dataset.node === id));
  const related = GRAPH.edges.filter(e => e.from === id || e.to === id);
  const hot = new Set(related.map(e => e.id));
  document.querySelectorAll(".edge").forEach(p => p.classList.toggle("hot", hot.has(p.dataset.edge)));
  const out = related.filter(e => e.from === id).map(e => `<li>${esc(e.type)} → ${link(e.to)}</li>`).join("");
  const inc = related.filter(e => e.to === id).map(e => `<li>${link(e.from)} → ${esc(e.type)}</li>`).join("");
  document.getElementById("detail").innerHTML = `
    <h2>${esc(n.label)}</h2>
    <p class="meta">${esc(n.type)} · <code>${esc(n.id)}</code><br>记录号 ${n.first_sequence}–${n.last_sequence} · ${esc(n.provenance.capture_modes.join(", "))}</p>
    <h3>属性</h3><pre>${esc(JSON.stringify(n.attrs, null, 2))}</pre>
    <h3>出边</h3><ul>${out || "<li class=meta>无</li>"}</ul>
    <h3>入边</h3><ul>${inc || "<li class=meta>无</li>"}</ul>
    <h3>来源</h3><ul>${n.event_ids.map(e => `<li><code>${esc(e)}</code></li>`).join("")}${n.provenance.source_refs.map(r => `<li>${esc(r)}</li>`).join("")}</ul>`;
}
document.addEventListener("click", ev => {
  const g = ev.target.closest(".node"), a = ev.target.closest("[data-goto]");
  if (a) { ev.preventDefault(); select(a.dataset.goto); document.querySelector(`.node[data-node="${CSS.escape(a.dataset.goto)}"]`)?.scrollIntoView({block:"center", inline:"center"}); }
  else if (g) select(g.dataset.node);
});
</script>
</body>
</html>
"""


def _json_for_html(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def render_html(graph: dict[str, Any], *, title: str, findings: list[dict[str, Any]] | None = None) -> str:
    esc = html.escape
    types = sorted({node["type"] for node in graph["nodes"]})
    colors = {kind: PALETTE[index % len(PALETTE)] for index, kind in enumerate(types)}
    stats = graph["stats"]
    modes = ", ".join(f"{mode} {count}" for mode, count in stats["capture_modes"].items())
    meta = f'{stats["event_count"]} 条记录 · {stats["node_count"]} 节点 · {stats["edge_count"]} 关系 · {esc(modes)}'
    if any(mode != "live" for mode in stats["capture_modes"]):
        meta += ' · <span class="warn">含非实时记录（reconstructed / synthetic）</span>'
    legend = "".join(f'<span><i style="background:{colors[kind]}"></i>{esc(kind)}</span>' for kind in types)
    lint = ""
    if findings:
        items = "".join(f'<li><b>{esc(item["severity"])}</b> {esc(item["code"])}: {esc(item.get("message", ""))}</li>' for item in findings)
        lint = f'<h3 class="warn">Lint {len(findings)}</h3><ul>{items}</ul>'
    replacements = {
        "__TITLE__": esc(title), "__META__": meta, "__LEGEND__": legend, "__LINT__": lint,
        "__SVG__": _svg(graph, layout(graph), colors), "__GRAPH_JSON__": _json_for_html({"nodes": graph["nodes"], "edges": graph["edges"]}),
    }
    page = HTML_TEMPLATE
    for key, value in replacements.items():
        page = page.replace(key, value)
    return page


def write_projection(out_dir: str | Path, *, graph: dict[str, Any], findings: list[dict[str, Any]], title: str) -> dict[str, Any]:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    outputs = {
        "graph.json": json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "lint.json": json.dumps(findings, ensure_ascii=False, indent=2) + "\n",
        "graph.html": render_html(graph, title=title, findings=findings),
    }
    for name, content in outputs.items():
        atomic_write_text(target / name, content)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "graph_id": graph["graph_id"],
        "projected_from": graph.get("source_ledger"),
        "generated_at": graph["generated_at"],
        "outputs": {name: {"sha256": sha256_file(target / name), "size_bytes": (target / name).stat().st_size} for name in sorted(outputs)},
        "lint": {
            "errors": sum(item["severity"] == "error" for item in findings),
            "warnings": sum(item["severity"] == "warning" for item in findings),
        },
    }
    atomic_write_text(target / "projection-receipt.json", canonical_json(receipt) + "\n")
    return receipt
