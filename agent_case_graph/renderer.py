from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from .ledger import atomic_write_text, canonical_json, sha256_file
from .loop_projection import build_loop_projection
from .model import SCHEMA_VERSION
from .sequence_projection import build_sequence_projection
from .reader import build_reader_model, render_reader_html
from .story_graph import build_story_model, render_story_html
from .workbench import build_workbench_model, render_workbench_html
from .trace_model import PROTOCOL_VERSION, build_trace_model


PHASE_COLORS = {
    "context": "#dbeafe", "plan": "#e0e7ff", "inspect": "#ede9fe",
    "execute": "#ffedd5", "validate": "#dcfce7", "claim": "#fce7f3",
}

QUIET_EDGE_TYPES = {"contains", "has_run"}


def _plantuml_text(value: Any) -> str:
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", str(value or ""))
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\\", "\\\\")
        .replace('"', "'")
    )


def _plantuml_alias(index: int, node_id: str) -> str:
    hint = re.sub(r"[^A-Za-z0-9_]", "_", node_id)[-28:]
    return f"n{index}_{hint}"


def _primary_layout_edges(model: dict[str, Any], primary_ids: set[str]) -> list[dict[str, Any]]:
    candidates = [
        edge
        for edge in model["edges"]
        if edge.get("layout") and edge["from"] in primary_ids and edge["to"] in primary_ids
    ]
    incoming_flow = {
        edge["to"] for edge in candidates if edge["type"] not in QUIET_EDGE_TYPES
    }
    return [
        edge
        for edge in candidates
        if edge["type"] != "contains" or edge["to"] not in incoming_flow
    ]


def render_plantuml(model: dict[str, Any]) -> str:
    primary_nodes = [node for node in model["nodes"] if node.get("primary", True)]
    primary_ids = {node["id"] for node in primary_nodes}
    aliases = {node["id"]: _plantuml_alias(index, node["id"]) for index, node in enumerate(primary_nodes)}
    layout_edges = _primary_layout_edges(model, primary_ids)
    lines = [
        "@startuml", "' Generated from the same paper-trace model as graph.html",
        "top to bottom direction", "skinparam backgroundColor #F8FAFC",
        "skinparam shadowing false", "skinparam roundCorner 10",
        "skinparam defaultFontName Arial", "skinparam ArrowColor #64748B",
        "skinparam ArrowThickness 1", "skinparam rectangleBorderColor #64748B",
        "skinparam rectangleFontColor #172033", "skinparam rectangleFontSize 11",
        "skinparam linetype polyline", "hide stereotype",
        "title Agent workflow trace — layered DAG",
    ]
    for node in primary_nodes:
        alias, phase = aliases[node["id"]], node["phase"]
        label = _plantuml_text(node["label"][:92])
        meta = _plantuml_text(f"{phase.upper()} · {node['type']} · {node['status']}")
        lines.append(f'rectangle "<b>{label}</b>\\n<size:9>{meta}</size>" as {alias} {PHASE_COLORS[phase]}')
    evidence_edges = {"supports", "checks", "explains", "derived_from", "uses", "informs"}
    for edge in layout_edges:
        source, target = aliases.get(edge["from"]), aliases.get(edge["to"])
        if not source or not target:
            continue
        if edge["type"] in evidence_edges:
            lines.append(f"{source} ..> {target} : {_plantuml_text(edge['type'])}")
        elif edge["type"] in QUIET_EDGE_TYPES:
            lines.append(f"{source} -[#CBD5E1]-> {target}")
        else:
            lines.append(f"{source} --> {target} : {_plantuml_text(edge['type'])}")
    lines.extend([
        "legend left", "  |= Color |= Workflow phase |", "  |<#DBEAFE> | Context |",
        "  |<#E0E7FF> | Plan |", "  |<#EDE9FE> | Inspect |", "  |<#FFEDD5> | Execute |",
        "  |<#DCFCE7> | Validate |", "  |<#FCE7F3> | Claim |",
        "  Static view = forward workflow/dependency DAG", "  Evidence/review links = HTML Evidence tab", "endlegend", "@enduml", "",
    ])
    return "\n".join(lines)


def render_sequence_plantuml(sequence: dict[str, Any]) -> str:
    aliases = {item["id"]: item["id"] for item in sequence["participants"]}
    lines = [
        "@startuml",
        "' Typed partial-order projection; source record numbers remain traceable",
        "skinparam backgroundColor #F8FAFC",
        "skinparam shadowing false",
        "skinparam sequenceArrowColor #64748B",
        "skinparam sequenceLifeLineBorderColor #94A3B8",
        "skinparam sequenceParticipantBorderColor #64748B",
        "skinparam sequenceParticipantBackgroundColor #FFFFFF",
        "title Agent execution — sequence projection",
        "autonumber",
    ]
    declarations = {
        "actor": "actor",
        "database": "database",
        "participant": "participant",
    }
    for participant in sequence["participants"]:
        kind = declarations.get(participant["kind"], "participant")
        lines.append(
            f'{kind} "{_plantuml_text(participant["label"])}" as {aliases[participant["id"]]}'
        )
    steps_by_id = {step["id"]: step for step in sequence["steps"]}
    emitted: set[str] = set()
    for scope in sequence["scopes"]:
        scope_steps = [
            steps_by_id[step_id]
            for step_id in scope["step_ids"]
            if step_id in steps_by_id and step_id not in emitted
        ]
        if not scope_steps:
            continue
        lines.append(f'group {_plantuml_text(scope["label"])}')
        for step in scope_steps:
            emitted.add(step["id"])
            arrow = "-->" if step["from"] in {"tool", "world", "evaluator"} else "->"
            label = _plantuml_text(
                f"[{step['type']}] {step['label']} [source #{step['sequence']}]"
            )
            lines.append(
                f"  {aliases[step['from']]} {arrow} {aliases[step['to']]} : {label}"
            )
        lines.append("end")
    if not emitted:
        lines.append("note over agent: No chronological execution steps were projected")
    lines.extend(
        [
            "legend left",
            "  Sequence = explicit temporal constraints + stable source-order tie-break",
            "  Adjacent messages are not necessarily causally related",
            "  See trace.puml / graph.html for typed causal and evidence relations",
            "endlegend",
            "@enduml",
            "",
        ]
    )
    return "\n".join(lines)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:">
<title>__TITLE__</title><style>
:root{color-scheme:light;--page:#f4f7fb;--panel:#fff;--ink:#172033;--muted:#667085;--line:#d9e1ea;--soft:#eef3f7;--accent:#247aa5;--selected:#0f6f94;--context:#dbeafe;--plan:#e0e7ff;--inspect:#ede9fe;--execute:#ffedd5;--validate:#dcfce7;--claim:#fce7f3}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 Inter,Segoe UI,Arial,sans-serif}button,select{font:inherit}.app{min-height:100vh;display:grid;grid-template-rows:auto 1fr}.topbar{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:18px 24px;background:var(--panel);border-bottom:1px solid var(--line)}
.brand h1{margin:0;font-size:18px;letter-spacing:-.02em}.brand p{margin:3px 0 0;color:var(--muted);font-size:12px}.top-actions{display:flex;gap:8px}.top-actions select,.top-actions button{border:1px solid var(--line);border-radius:8px;background:#fff;padding:7px 10px;color:var(--ink)}
.workspace{min-height:0;display:grid;grid-template-columns:270px minmax(460px,1fr) 330px;gap:1px;background:var(--line)}.panel{min-width:0;min-height:0;background:var(--panel)}.panel-head{height:67px;padding:13px 16px;border-bottom:1px solid var(--line)}.panel-head h2{margin:0;font-size:12px;text-transform:uppercase;letter-spacing:.08em}.panel-head p{margin:4px 0 0;color:var(--muted);font-size:11px}
.timeline{height:calc(100vh - 135px);overflow:auto;padding:10px}.event{width:100%;display:grid;grid-template-columns:28px 1fr;gap:8px;text-align:left;border:0;border-radius:8px;background:transparent;padding:8px;color:var(--ink);cursor:pointer}.event:hover,.event.active{background:var(--soft)}.event-seq{color:var(--muted);font:600 10px/1.4 ui-monospace,monospace}.event-kind{font-size:11px;font-weight:650}.event-meta{color:var(--muted);font-size:10px;overflow-wrap:anywhere}
.center{display:grid;grid-template-rows:auto 1fr;min-height:0}.center-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-bottom:1px solid var(--line)}.view-tabs{display:flex;gap:4px;background:var(--soft);border-radius:9px;padding:3px}.view-tab{border:0;border-radius:7px;background:transparent;padding:6px 10px;color:var(--muted);cursor:pointer}.view-tab.active{background:#fff;color:var(--ink);box-shadow:0 1px 4px rgba(20,30,40,.12)}
.center-tools{display:flex;align-items:center;justify-content:flex-end;min-width:0}.sequence-controls{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:10px}.sequence-controls select{max-width:310px;border:1px solid var(--line);border-radius:7px;background:#fff;padding:5px 7px;color:var(--ink)}.legend{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px;color:var(--muted);font-size:10px}.legend span{display:inline-flex;align-items:center;gap:4px}.relation-chip{border-radius:999px;background:var(--soft);padding:2px 6px;color:#43546a;font-weight:650}.dot{width:8px;height:8px;border-radius:2px;background:var(--c)}.canvas-shell{min-height:0;overflow:auto;background:linear-gradient(#f4f7fa 1px,transparent 1px),linear-gradient(90deg,#f4f7fa 1px,transparent 1px),#fbfcfe;background-size:24px 24px}#graphSvg{display:block;min-width:100%;min-height:100%}
.edge{fill:none;stroke:#94a3b8;stroke-width:1.2}.edge.evidence{stroke-dasharray:5 4}.edge.quiet{stroke:#cbd5e1}.edge.reverse{stroke:#8291a6}.edge.same-rank{stroke:#74869d}.edge.dim{opacity:.20}.edge.active{stroke:var(--selected);stroke-width:2.2;opacity:1}.edge-label{font-size:9px;font-weight:700;fill:#526173;paint-order:stroke;stroke:#fbfcfe;stroke-width:4px;stroke-linejoin:round}.sequence-lifeline{stroke:#cbd5e1;stroke-width:1;stroke-dasharray:5 5}.sequence-participant{fill:#fff;stroke:#64748b;stroke-width:1}.sequence-participant-label{font-size:10px;font-weight:700;fill:#243246}.sequence-arrow{fill:none;stroke:#64748b;stroke-width:1.4}.sequence-arrow.return{stroke-dasharray:5 4}.sequence-arrow.active{stroke:var(--selected);stroke-width:2.2}.sequence-arrow.dim{opacity:.22}.sequence-step-label{font-size:10px;font-weight:650;fill:#26364a;paint-order:stroke;stroke:#fbfcfe;stroke-width:5px;stroke-linejoin:round}.sequence-step-meta{font-size:8.5px;fill:#64748b;paint-order:stroke;stroke:#fbfcfe;stroke-width:4px}.sequence-note{font-size:9px;fill:#667085}.sequence-step{cursor:pointer}.node{cursor:pointer}.node rect{stroke:#8493a6;stroke-width:1;rx:9;filter:url(#nodeShadow)}.node:hover rect,.node.active rect{stroke:var(--selected);stroke-width:2}.node.dim{opacity:.44}.node .phase{font-size:8px;font-weight:750;letter-spacing:.08em;fill:#526173}.node .label{font-size:11px;font-weight:650;fill:var(--ink)}.node .meta{font-size:8.5px;fill:#64748b}
.trace-cards{padding:28px;display:grid;gap:10px;max-width:820px;margin:0 auto}.trace-card{display:grid;grid-template-columns:50px 1fr;gap:12px;border:1px solid var(--line);border-radius:10px;background:#fff;padding:12px}.trace-card strong{font-size:12px}.trace-card p{margin:4px 0 0;color:var(--muted);font-size:11px}.details{height:calc(100vh - 135px);overflow:auto;padding:16px}.detail-empty{color:var(--muted);padding:20px 0}.badge{display:inline-flex;border-radius:999px;padding:3px 7px;background:var(--soft);color:var(--muted);font-size:10px;font-weight:700}.details h3{margin:10px 0 5px;font-size:16px}.node-id{color:var(--muted);font:10px/1.5 ui-monospace,monospace;overflow-wrap:anywhere}
.section{margin-top:18px;padding-top:14px;border-top:1px solid var(--line)}.section h4{margin:0 0 8px;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}.kv{display:grid;grid-template-columns:72px 1fr;gap:6px;font-size:11px}.kv dt{color:var(--muted)}.kv dd{margin:0;overflow-wrap:anywhere}.relation{display:block;width:100%;border:0;border-radius:7px;background:var(--soft);text-align:left;padding:7px 8px;margin:5px 0;color:var(--ink);cursor:pointer;font-size:10px}.capture-note{margin:10px 0 0;border-left:3px solid #f59e0b;padding:7px 9px;background:#fff8e8;color:#72510d;font-size:10px}
.view-tab{white-space:nowrap}
.top-actions{flex-wrap:wrap}.reader-return{display:inline-flex;align-items:center;color:var(--selected);padding:7px;text-decoration:none;font-size:12px}
.kv{grid-template-columns:72px minmax(0,1fr)}.kv dt,.kv dd{min-width:0;overflow-wrap:anywhere}
[hidden]{display:none!important}
@media(max-width:1050px){
  .workspace{grid-template-columns:220px minmax(0,1fr)}
  .details-panel{grid-column:1/-1;border-top:1px solid var(--line)}
  .details{height:auto;max-height:50vh}
  .canvas-shell{max-height:70vh}
  .center-head{flex-wrap:wrap}
  .view-tabs{flex-wrap:wrap}
}
@media(max-width:720px){
  .topbar{padding:13px 14px;flex-wrap:wrap;gap:12px}
  .brand{min-width:0}.brand h1{overflow-wrap:anywhere}
  .workspace{grid-template-columns:minmax(0,1fr)}
  .timeline-panel{display:none}
  .center-head{align-items:flex-start;flex-direction:column}
  .view-tabs{width:100%}
  .center-tools{width:100%;justify-content:flex-start;flex-wrap:wrap}
  .sequence-controls{max-width:100%}.sequence-controls select{min-width:0;max-width:100%}
  .legend{justify-content:flex-start}
}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
</style></head><body><div class="app"><header class="topbar"><div class="brand"><h1 id="pageTitle">__TITLE__</h1><p id="subtitle"></p></div><div class="top-actions"><select id="languageSelect" aria-label="显示语言"><option value="zh-CN">中文</option><option value="en-US">English</option></select><button id="fitButton" type="button">适合画布</button></div></header>
<main class="workspace"><aside class="panel timeline-panel"><div class="panel-head"><h2 id="timelineTitle"></h2><p id="timelineHint"></p></div><div class="timeline" id="timeline"></div></aside><section class="panel center"><div class="center-head"><div class="view-tabs" role="tablist"><button class="view-tab active" data-view="overview" role="tab" aria-selected="true"></button><button class="view-tab" data-view="sequence" role="tab" aria-selected="false"></button><button class="view-tab" data-view="workflow" role="tab" aria-selected="false"></button><button class="view-tab" data-view="evidence" role="tab" aria-selected="false"></button><button class="view-tab" data-view="trace" role="tab" aria-selected="false"></button></div><div class="center-tools"><label class="sequence-controls" id="sequenceControls" hidden><span id="sequenceScopeLabel"></span><select id="sequenceScopeSelect"></select></label><div class="legend" id="legend"></div></div></div><div class="canvas-shell" id="canvasShell"><svg id="graphSvg" role="img" aria-label="Layered agent workflow graph"></svg></div></section><aside class="panel details-panel"><div class="panel-head"><h2 id="detailsTitle"></h2><p id="detailsHint"></p></div><div class="details" id="details"></div></aside></main></div>
<script>
const MODEL=__MODEL_JSON__,LOCALES=__DISPLAY_LOCALES_JSON__,SOURCE_TITLE=__SOURCE_TITLE_JSON__,DEFAULT_LOCALE=__DEFAULT_LOCALE_JSON__;
const UI={"zh-CN":{subtitle:"双循环 Trace：时序看单次执行，图关系解释原因与证据",timelineTitle:"原始 Trace",timelineHint:"保留顺序，不把时间当成因果",detailsTitle:"节点证据",detailsHint:"选择聚合点可查看成员并展开",fit:"适合画布",overview:"循环总览",sequence:"单次执行",workflow:"因果流程",evidence:"证据链",trace:"原始记录",sequenceScope:"执行迭代",sequenceNote:"纵向只表示记录顺序；因果关系请看因果流程与证据链。",participantUser:"用户",participantAgent:"Agent",participantTool:"工具 / Runtime",participantWorld:"证据 / 外界",participantEvaluator:"评估器",outerLoop:"外层 · 用户对话推进",innerLoop:"内层 · Agent 执行迭代",tool:"工具",output:"产出",status:"状态",phase:"阶段",type:"类型",incoming:"上游关系",outgoing:"下游关系",source:"源记录",members:"聚合成员",expand:"展开这一轮",reconstructed:"历史重建：可审阅，但不等同于原生执行遥测。",events:"项记录"},"en-US":{subtitle:"Nested-loop trace: use sequence for one execution, graph relations for causes and evidence",timelineTitle:"Source trace",timelineHint:"Sequence is preserved without claiming causality",detailsTitle:"Node evidence",detailsHint:"Select an aggregate to inspect and expand its members",fit:"Fit canvas",overview:"Loop overview",sequence:"Single execution",workflow:"Causal flow",evidence:"Evidence",trace:"Trace records",sequenceScope:"Execution iteration",sequenceNote:"Vertical order is recorded sequence only; inspect Causal flow and Evidence for typed relations.",participantUser:"User",participantAgent:"Agent",participantTool:"Tool / Runtime",participantWorld:"Evidence / World",participantEvaluator:"Evaluator",outerLoop:"Outer · dialogue progress",innerLoop:"Inner · agent execution",tool:"Tool",output:"Output",status:"Status",phase:"Phase",type:"Type",incoming:"Incoming",outgoing:"Outgoing",source:"Source records",members:"Members",expand:"Expand this loop",reconstructed:"Historical reconstruction: reviewable, but not native execution telemetry.",events:"records"}};
const PHASES={context:"Context",plan:"Plan",inspect:"Inspect",execute:"Execute",validate:"Validate",claim:"Claim"},COLORS={context:"#dbeafe",plan:"#e0e7ff",inspect:"#ede9fe",execute:"#ffedd5",validate:"#dcfce7",claim:"#fce7f3"},EVIDENCE_EDGES=new Set(["supports","refutes","checks","explains","derived_from","informs","uses","produces","approved_by","verified_by","references","tested_by","satisfies"]),CAUSAL_OVERLAY_EDGES=new Set(["informs","supersedes"]),SEMANTIC_EDGES=new Set(["frames","informs","supersedes","supports","refutes","invokes","produces","checks","tested_by","explains"]),DEFAULT_LABEL_EDGES=new Set(["frames","supersedes","supports"]),QUIET_EDGES=new Set(["contains","has_run"]);
UI["zh-CN"].sequenceNote="纵向按显式时序关系线性化，同级按源记录稳定排序；相邻步骤不一定有因果。";
UI["en-US"].sequenceNote="Vertical order linearizes explicit temporal relations with source order as a stable tie-break; adjacency does not imply causality.";
let locale=LOCALES[DEFAULT_LOCALE]?DEFAULT_LOCALE:"zh-CN",view=MODEL.overview?.nodes?.length?"overview":"workflow",selectedId=MODEL.overview?.nodes?.[0]?.id||MODEL.root_id||MODEL.nodes[0]?.id||null,sequenceScopeId=MODEL.sequence?.scopes?.[0]?.id||null,selectionFocused=false;const svg=document.getElementById("graphSvg"),ns="http://www.w3.org/2000/svg";
function t(key){return (UI[locale]||UI["zh-CN"])[key]||key}function label(node){return LOCALES[locale]?.nodes?.[node.id]||node.label}function el(name,attrs={}){const node=document.createElementNS(ns,name);Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,String(v)));return node}function htmlEl(name,className,text){const node=document.createElement(name);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node}function allNodes(){return[...MODEL.nodes,...(MODEL.overview?.nodes||[])]}function findNode(id){return allNodes().find(n=>n.id===id)}function activeEdges(){return view==="overview"?(MODEL.overview?.edges||[]):MODEL.edges}function relatedIds(id){const ids=new Set([id]);activeEdges().forEach(e=>{if(e.from===id)ids.add(e.to);if(e.to===id)ids.add(e.from)});return ids}function sequenceScope(){return MODEL.sequence?.scopes?.find(scope=>scope.id===sequenceScopeId)||MODEL.sequence?.scopes?.[0]||null}function sequenceStepNode(step){return findNode(step.node_id)}
function visibleGraph(){if(view==="overview")return{nodes:MODEL.overview?.nodes||[],edges:(MODEL.overview?.edges||[]).filter(e=>e.layout)};if(view==="workflow"){const nodes=MODEL.nodes.filter(n=>n.primary),ids=new Set(nodes.map(n=>n.id)),candidates=MODEL.edges.filter(e=>(e.layout||CAUSAL_OVERLAY_EDGES.has(e.type))&&ids.has(e.from)&&ids.has(e.to)),incoming=new Set(candidates.filter(e=>!QUIET_EDGES.has(e.type)).map(e=>e.to)),edges=candidates.filter(e=>e.type!=="contains"||!incoming.has(e.to));return{nodes,edges}}const seeds=new Set(MODEL.nodes.filter(n=>n.level==="evidence").map(n=>n.id)),evidenceLinks=MODEL.edges.filter(e=>EVIDENCE_EDGES.has(e.type)&&(seeds.has(e.from)||seeds.has(e.to))),ids=new Set(seeds);evidenceLinks.forEach(e=>{ids.add(e.from);ids.add(e.to)});return{nodes:MODEL.nodes.filter(n=>ids.has(n.id)),edges:MODEL.edges.filter(e=>ids.has(e.from)&&ids.has(e.to)&&!QUIET_EDGES.has(e.type))}}
function wrap(text,max=29){
  // Measure with the actual SVG label font: character counts overflow for CJK
  // and wide glyphs. Preserve the full label in the node's aria-label/drawer.
  const maxWidth=Math.min(152,max*6),group=el("g",{class:"node",visibility:"hidden","aria-hidden":"true"}),probe=el("text",{class:"label"});group.append(probe);svg.append(group);
  const value=String(text).replace(/\s+/g," ").trim(),chars=typeof Intl.Segmenter==="function"?[...new Intl.Segmenter(locale,{granularity:"grapheme"}).segment(value)].map(item=>item.segment):Array.from(value);
  const fits=value=>{probe.textContent=value;return probe.getComputedTextLength()<=maxWidth};
  const prefix=(items,suffix="")=>{let low=0,high=items.length;while(low<high){const mid=Math.ceil((low+high)/2);if(fits(items.slice(0,mid).join("")+suffix))low=mid;else high=mid-1}return low};
  try{if(fits(value))return[value];let cut=prefix(chars),space=chars.slice(0,cut).lastIndexOf(" ");if(space>cut/2)cut=space;const first=chars.slice(0,cut).join(""),tail=chars.slice(cut).join("").trim(),rest=typeof Intl.Segmenter==="function"?[...new Intl.Segmenter(locale,{granularity:"grapheme"}).segment(tail)].map(item=>item.segment):Array.from(tail);return[first,fits(tail)?tail:rest.slice(0,prefix(rest,"…")).join("")+"…"]}finally{group.remove()}
}
function stableTextOrder(a,b){return a<b?-1:a>b?1:0}
function stableNodeOrder(a,b){const sa=a.first_sequence??Number.MAX_SAFE_INTEGER,sb=b.first_sequence??Number.MAX_SAFE_INTEGER;return sa-sb||stableTextOrder(a.id,b.id)}
function median(values){if(!values.length)return null;const sorted=[...values].sort((a,b)=>a-b),mid=Math.floor(sorted.length/2);return sorted.length%2?sorted[mid]:(sorted[mid-1]+sorted[mid])/2}
function orderCrossingCount(byRank,ranks,edges){const pos=new Map();ranks.forEach((rank,y)=>{const group=byRank.get(rank);group.forEach((n,i)=>pos.set(n.id,{x:(i+.5)/group.length,y}))});const orient=(a,b,c)=>(b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x),cross=(a,b,c,d)=>orient(a,b,c)*orient(a,b,d)<0&&orient(c,d,a)*orient(c,d,b)<0;let count=0;for(let i=0;i<edges.length;i++)for(let j=i+1;j<edges.length;j++){const a=edges[i],b=edges[j];if(new Set([a.from,a.to,b.from,b.to]).size<4)continue;if(cross(pos.get(a.from),pos.get(a.to),pos.get(b.from),pos.get(b.to)))count++}return count}
function crossingReducedRanks(nodes,edges){const byRank=new Map(),nodeRank=new Map(),incident=new Map(),nodeById=new Map(nodes.map(n=>[n.id,n]));nodes.forEach(n=>{const rank=n.rank||0;nodeRank.set(n.id,rank);if(!byRank.has(rank))byRank.set(rank,[]);byRank.get(rank).push(n);incident.set(n.id,[])});edges.forEach(e=>{if(incident.has(e.from)&&incident.has(e.to)){incident.get(e.from).push(e.to);incident.get(e.to).push(e.from)}});const ranks=[...byRank.keys()].sort((a,b)=>a-b);byRank.forEach(group=>group.sort(stableNodeOrder));let bestScore=orderCrossingCount(byRank,ranks,edges),best=new Map(ranks.map(rank=>[rank,byRank.get(rank).map(n=>n.id)]));const remember=()=>{const score=orderCrossingCount(byRank,ranks,edges);if(score<bestScore){bestScore=score;best=new Map(ranks.map(rank=>[rank,byRank.get(rank).map(n=>n.id)]))}};const sweep=forward=>{const order=new Map();byRank.forEach(group=>group.forEach((n,i)=>order.set(n.id,(i+.5)/group.length)));const scan=forward?ranks.slice(1):ranks.slice(0,-1).reverse();scan.forEach(rank=>{const group=byRank.get(rank),previous=new Map(group.map((n,i)=>[n.id,i]));group.sort((a,b)=>{const score=node=>median(incident.get(node.id).filter(id=>forward?nodeRank.get(id)<rank:nodeRank.get(id)>rank).map(id=>order.get(id)).filter(Number.isFinite));const as=score(a),bs=score(b);if(as!==null&&bs!==null&&as!==bs)return as-bs;if(as!==null&&bs===null)return-1;if(as===null&&bs!==null)return 1;return previous.get(a.id)-previous.get(b.id)||stableNodeOrder(a,b)});group.forEach((n,i)=>order.set(n.id,(i+.5)/group.length))});remember()};for(let i=0;i<6;i++){sweep(true);sweep(false)}ranks.forEach(rank=>byRank.set(rank,best.get(rank).map(id=>nodeById.get(id))));return{byRank,ranks,crossings:bestScore}}
function routeKind(edge,a,b,cardH,nodeRank){if(nodeRank.get(edge.from)===nodeRank.get(edge.to))return"same-rank";if(Math.abs(a.y-b.y)<cardH/2)return"same-rank";return b.y>a.y?"forward":"reverse"}
function routeEdgeKey(item){const e=item.edge;return`${e.from}\u0000${e.to}\u0000${e.type}\u0000${String(item.index).padStart(5,"0")}`}
function portPoint(node,side,index,count,cardW,cardH){const margin=16,fraction=(index+1)/(count+1);if(side==="top"||side==="bottom")return{x:node.x+margin+fraction*(cardW-2*margin),y:node.y+(side==="bottom"?cardH:0)};return{x:node.x+(side==="right"?cardW:0),y:node.y+margin+fraction*(cardH-2*margin)}}
function routedEdges(edges,pos,nodeRank,cardW,cardH,width,rowGap){
  const items=edges.map((edge,index)=>{const a=pos.get(edge.from),b=pos.get(edge.to);if(!a||!b)return null;const kind=routeKind(edge,a,b,cardH,nodeRank),wrapped=kind==="same-rank"&&Math.abs(a.y-b.y)>=cardH/2,right=b.x+cardW/2>=a.x+cardW/2,outsideLeft=(a.x+b.x+cardW)/2<=width/2,down=b.y>a.y,sourceSide=wrapped?(down?"bottom":"top"):kind==="forward"?"bottom":kind==="reverse"?"top":right?"right":"left",targetSide=wrapped?(down?"top":"bottom"):kind==="forward"?"top":kind==="reverse"?"bottom":right?"left":"right";return{edge,index,a,b,kind,wrapped,outsideLeft,sourceSide,targetSide}}).filter(Boolean),buckets=new Map();
  const add=(nodeId,side,item,end)=>{const key=`${nodeId}:${side}`;if(!buckets.has(key))buckets.set(key,[]);buckets.get(key).push({item,end})};
  items.forEach(item=>{add(item.edge.from,item.sourceSide,item,"source");add(item.edge.to,item.targetSide,item,"target")});
  buckets.forEach(bucket=>{bucket.sort((u,v)=>{const up=u.end==="source"?u.item.b:u.item.a,vp=v.end==="source"?v.item.b:v.item.a;return up.x-vp.x||up.y-vp.y||stableTextOrder(routeEdgeKey(u.item),routeEdgeKey(v.item))});bucket.forEach((entry,index)=>{entry.item[`${entry.end}Port`]=portPoint(entry.end==="source"?entry.item.a:entry.item.b,entry.end==="source"?entry.item.sourceSide:entry.item.targetSide,index,bucket.length,cardW,cardH)})});
  const sameRows=new Map();items.filter(item=>item.kind==="same-rank"&&!item.wrapped).forEach(item=>{const key=Math.round(item.a.y);if(!sameRows.has(key))sameRows.set(key,[]);sameRows.get(key).push(item)});sameRows.forEach(group=>group.sort((a,b)=>stableTextOrder(routeEdgeKey(a),routeEdgeKey(b))).forEach((item,index)=>item.sameLane=index));
  const wrappedGaps=new Map();items.filter(item=>item.wrapped&&Math.abs(item.targetPort.y-item.sourcePort.y)<80).forEach(item=>{const key=`${Math.min(item.sourcePort.y,item.targetPort.y)}:${Math.max(item.sourcePort.y,item.targetPort.y)}`;if(!wrappedGaps.has(key))wrappedGaps.set(key,[]);wrappedGaps.get(key).push(item)});wrappedGaps.forEach(group=>{group.sort((a,b)=>stableTextOrder(routeEdgeKey(a),routeEdgeKey(b)));const gap=Math.abs(group[0].targetPort.y-group[0].sourcePort.y),capacity=Math.max(1,Math.floor((gap-16)/8)+1);group.forEach((item,index)=>{if(group.length<=capacity){item.wrapLane=index;item.wrapCount=group.length}else{item.wrapOverflow=true;item.outsideLeft=index%2===0}})});
  return items.map(item=>{const p=item.sourcePort,q=item.targetPort,verticalDistance=Math.abs(q.y-p.y);let path,displayRoute=item.kind;if(item.wrapped){const laneX=item.outsideLeft?18:width-18,direction=q.y>p.y?1:-1;if(verticalDistance<80&&!item.wrapOverflow){const low=Math.min(p.y,q.y)+8,high=Math.max(p.y,q.y)-8,laneY=item.wrapCount===1?(low+high)/2:low+item.wrapLane*(high-low)/(item.wrapCount-1);path=`M ${p.x} ${p.y} L ${p.x} ${laneY} L ${q.x} ${laneY} L ${q.x} ${q.y}`;displayRoute="gap-same-rank"}else if(verticalDistance<80){path=`M ${p.x} ${p.y} C ${laneX} ${p.y}, ${laneX} ${q.y}, ${q.x} ${q.y}`;displayRoute="side-same-rank"}else{path=`M ${p.x} ${p.y} C ${laneX} ${p.y}, ${laneX} ${p.y+direction*18}, ${laneX} ${p.y+direction*36} L ${laneX} ${q.y-direction*36} C ${laneX} ${q.y-direction*18}, ${laneX} ${q.y}, ${q.x} ${q.y}`;displayRoute="side-same-rank"}}else if(item.kind==="same-rank"){const above=item.sameLane%2===0,lane=Math.floor(item.sameLane/2),laneY=(above?Math.min(item.a.y,item.b.y):Math.max(item.a.y,item.b.y)+cardH)+(above?-24-lane*10:24+lane*10);path=`M ${p.x} ${p.y} C ${p.x} ${laneY}, ${q.x} ${laneY}, ${q.x} ${q.y}`}else if(verticalDistance>rowGap*1.25){const left=(p.x+q.x)/2<width/2,laneX=left?18:width-18,direction=q.y>p.y?1:-1;path=`M ${p.x} ${p.y} C ${p.x} ${p.y+direction*18}, ${laneX} ${p.y+direction*18}, ${laneX} ${p.y+direction*36} L ${laneX} ${q.y-direction*36} C ${laneX} ${q.y-direction*18}, ${q.x} ${q.y-direction*18}, ${q.x} ${q.y}`;displayRoute=`side-${item.kind}`}else{const direction=q.y>p.y?1:-1,curve=Math.max(20,Math.min(48,verticalDistance/2));path=`M ${p.x} ${p.y} C ${p.x} ${p.y+direction*curve}, ${q.x} ${q.y-direction*curve}, ${q.x} ${q.y}`}return{...item,path,displayRoute}})
}
function renderSequence(){
  svg.replaceChildren();const sequence=MODEL.sequence||{participants:[],steps:[],scopes:[]},scope=sequenceScope(),stepsById=new Map(sequence.steps.map(step=>[step.id,step])),steps=(scope?.step_ids||[]).map(id=>stepsById.get(id)).filter(Boolean),participants=sequence.participants,width=Math.max(760,document.getElementById("canvasShell").clientWidth),side=70,available=Math.max(600,width-side*2),stepGap=64,top=112,height=Math.max(520,top+steps.length*stepGap+54),positions=new Map();svg.setAttribute("viewBox",`0 0 ${width} ${height}`);svg.setAttribute("width",width);svg.setAttribute("height",height);
  const defs=el("defs"),marker=el("marker",{id:"sequenceArrow",viewBox:"0 0 10 10",refX:9,refY:5,markerWidth:6,markerHeight:6,orient:"auto-start-reverse"});marker.append(el("path",{d:"M 0 0 L 10 5 L 0 10 z",fill:"#64748b"}));defs.append(marker);svg.append(defs);
  const participantText={user:t("participantUser"),agent:t("participantAgent"),tool:t("participantTool"),world:t("participantWorld"),evaluator:t("participantEvaluator")};participants.forEach((participant,index)=>{const x=side+(participants.length===1?available/2:index*available/(participants.length-1));positions.set(participant.id,x);svg.append(el("line",{x1:x,y1:62,x2:x,y2:height-26,class:"sequence-lifeline"}));svg.append(el("rect",{x:x-55,y:24,width:110,height:34,rx:7,class:"sequence-participant"}));const text=el("text",{x,y:45,"text-anchor":"middle",class:"sequence-participant-label"});text.textContent=participantText[participant.id]||participant.label;svg.append(text)});
  const note=el("text",{x:side,y:82,class:"sequence-note"});note.textContent=t("sequenceNote");svg.append(note);if(!steps.length){const empty=el("text",{x:width/2,y:150,"text-anchor":"middle",class:"sequence-note"});empty.textContent=locale==="zh-CN"?"这一迭代没有可展示的执行步骤":"No execution steps in this iteration";svg.append(empty);return}
  steps.forEach((step,index)=>{const y=top+index*stepGap,fromX=positions.get(step.from),toX=positions.get(step.to),node=sequenceStepNode(step),active=step.node_id===selectedId,dim=selectionFocused&&selectedId&&!active,group=el("g",{class:"sequence-step","data-sequence-step":step.id,"data-node-id":step.node_id,tabindex:"0",role:"button","aria-label":node?label(node):step.label});let path,labelX;if(fromX===toX){const direction=fromX>width/2?-1:1,loopX=fromX+direction*58;path=`M ${fromX} ${y} C ${loopX} ${y}, ${loopX} ${y+30}, ${fromX} ${y+30}`;labelX=fromX+direction*68}else{path=`M ${fromX} ${y} L ${toX} ${y}`;labelX=(fromX+toX)/2}const arrow=el("path",{d:path,"marker-end":"url(#sequenceArrow)",class:`sequence-arrow ${step.from==="tool"||step.from==="world"||step.from==="evaluator"?"return":""} ${active?"active":""} ${dim?"dim":""}`});group.append(arrow);const text=el("text",{x:labelX,y:y-7,"text-anchor":"middle",class:"sequence-step-label"}),shown=node?label(node):step.label;text.textContent=`${index+1} · ${step.type} · ${shown.length>54?shown.slice(0,53)+"…":shown}`;group.append(text);const meta=el("text",{x:labelX,y:y+12,"text-anchor":"middle",class:"sequence-step-meta"}),detail=[`source #${step.sequence}`,step.tool,step.status].filter(Boolean).join(" · ");meta.textContent=detail;group.append(meta);group.addEventListener("click",()=>selectNode(step.node_id));group.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" ")selectNode(step.node_id)});svg.append(group)})
}
function renderGraph(){
  svg.replaceChildren();
  if(view==="sequence"){renderSequence();return}
  if(view==="trace"){renderTraceCards();return}
  const{nodes,edges}=visibleGraph(),{byRank,ranks}=crossingReducedRanks(nodes,edges),cardW=176,cardH=62,minGap=22,maxColumns=3,maxAcross=Math.max(1,...[...byRank.values()].map(group=>Math.min(maxColumns,group.length))),contentWidth=80+maxAcross*cardW+(maxAcross-1)*minGap,width=Math.max(680,document.getElementById("canvasShell").clientWidth,contentWidth),rowGap=106,top=58,pos=new Map();
  let visualRow=0;
  ranks.forEach(rank=>{const group=byRank.get(rank);for(let offset=0;offset<group.length;offset+=maxColumns){const chunk=group.slice(offset,offset+maxColumns),gap=Math.max(minGap,(width-80-chunk.length*cardW)/Math.max(1,chunk.length-1)),total=chunk.length*cardW+(chunk.length-1)*gap,start=Math.max(40,(width-total)/2);chunk.forEach((n,i)=>pos.set(n.id,{x:start+i*(cardW+gap),y:top+visualRow*rowGap}));visualRow++}});
  const height=Math.max(520,top+visualRow*rowGap+80);svg.setAttribute("viewBox",`0 0 ${width} ${height}`);svg.setAttribute("width",width);svg.setAttribute("height",height);
  const defs=el("defs"),marker=el("marker",{id:"arrow",viewBox:"0 0 10 10",refX:9,refY:5,markerWidth:6,markerHeight:6,orient:"auto-start-reverse"});marker.append(el("path",{d:"M 0 0 L 10 5 L 0 10 z",fill:"#94a3b8"}));const filter=el("filter",{id:"nodeShadow",x:"-20%",y:"-20%",width:"140%",height:"160%"});filter.append(el("feDropShadow",{dx:0,dy:2,stdDeviation:2,"flood-color":"#21364d","flood-opacity":".10"}));defs.append(marker,filter);svg.append(defs);
  const active=selectionFocused&&selectedId?relatedIds(selectedId):new Set();
  const nodeRank=new Map(nodes.map(node=>[node.id,node.rank||0]));
  const routes=routedEdges(edges,pos,nodeRank,cardW,cardH,width,rowGap);routes.forEach(item=>{const edge=item.edge;svg.append(el("path",{d:item.path,"marker-end":"url(#arrow)","data-from":edge.from,"data-to":edge.to,"data-type":edge.type,"data-route":item.displayRoute,class:`edge ${EVIDENCE_EDGES.has(edge.type)&&!edge.layout?"evidence":""} ${QUIET_EDGES.has(edge.type)?"quiet":""} ${item.kind==="reverse"?"reverse":""} ${item.kind==="same-rank"?"same-rank":""} ${selectionFocused&&selectedId&&!(edge.from===selectedId||edge.to===selectedId)?"dim":""} ${selectionFocused&&(edge.from===selectedId||edge.to===selectedId)?"active":""}`}))});routes.forEach(item=>{const edge=item.edge,connected=edge.from===selectedId||edge.to===selectedId,show=view==="overview"||SEMANTIC_EDGES.has(edge.type)&&(selectionFocused?connected:DEFAULT_LABEL_EDGES.has(edge.type));if(!show||QUIET_EDGES.has(edge.type))return;const text=el("text",{x:(item.sourcePort.x+item.targetPort.x)/2,y:(item.sourcePort.y+item.targetPort.y)/2-5,class:"edge-label","text-anchor":"middle","data-edge-label":edge.type});text.textContent=edge.type;svg.append(text)});if(view==="overview")[["dialogue",t("outerLoop")],["execution",t("innerLoop")]].forEach(([scope,title])=>{const node=nodes.find(n=>n.attrs?.loop_scope===scope),p=node&&pos.get(node.id);if(!p)return;const text=el("text",{x:p.x+cardW/2,y:28,class:"edge-label","text-anchor":"middle"});text.textContent=title;svg.append(text)})
  nodes.forEach(node=>{const p=pos.get(node.id),group=el("g",{class:`node ${node.id===selectedId?"active":""} ${selectionFocused&&selectedId&&!active.has(node.id)?"dim":""}`,"data-node-id":node.id,"data-rank":node.rank,tabindex:"0",role:"button","aria-label":label(node)});group.setAttribute("transform",`translate(${p.x} ${p.y})`);group.append(el("rect",{width:cardW,height:cardH,fill:COLORS[node.phase]||"#fff"}));const phase=el("text",{x:12,y:15,class:"phase"});phase.textContent=PHASES[node.phase]||node.phase;group.append(phase);wrap(label(node),26).forEach((line,i)=>{const text=el("text",{x:12,y:33+i*14,class:"label"});text.textContent=line;group.append(text)});const meta=el("text",{x:cardW-10,y:15,class:"meta","text-anchor":"end"});meta.textContent=node.type;group.append(meta);group.addEventListener("click",()=>selectNode(node.id));group.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" ")selectNode(node.id)});svg.append(group)})
}
function renderTraceCards(){const height=Math.max(600,MODEL.trace.length*82);svg.setAttribute("viewBox",`0 0 900 ${height}`);svg.setAttribute("height",height);const foreign=el("foreignObject",{x:0,y:0,width:900,height}),list=htmlEl("div","trace-cards");MODEL.trace.forEach(item=>{const card=htmlEl("div","trace-card");card.append(htmlEl("strong","",`#${item.sequence}`));const body=htmlEl("div");body.append(htmlEl("strong","",item.kind),htmlEl("p","",`${item.actor.type}:${item.actor.id} · ${item.capture_mode} · ${item.occurred_at}`));card.append(body);if(item.node_id){card.style.cursor="pointer";card.onclick=()=>selectNode(item.node_id)}list.append(card)});foreign.append(list);svg.append(foreign)}
function renderTimeline(){const root=document.getElementById("timeline");root.replaceChildren();MODEL.trace.forEach(item=>{const button=htmlEl("button",`event ${item.node_id===selectedId?"active":""}`),seq=htmlEl("span","event-seq",`#${item.sequence}`),body=htmlEl("span");body.append(htmlEl("span","event-kind",item.kind),htmlEl("div","event-meta",`${item.actor.type}:${item.actor.id} · ${item.capture_mode}`));button.append(seq,body);if(item.node_id)button.onclick=()=>selectNode(item.node_id);root.append(button)})}
function relationButton(edge,direction){const otherId=direction==="in"?edge.from:edge.to,other=findNode(otherId),types=edge.attrs?.relation_types?.join("+")||edge.type,count=edge.attrs?.original_edge_count,button=htmlEl("button","relation",`${types}${count?` [${count}]`:""} · ${other?label(other):otherId}`);button.title=edge.attrs?.original_edge_ids?.join("\n")||edge.id;button.onclick=()=>selectNode(otherId);return button}
function setView(next){const current=findNode(selectedId);if(next==="overview"&&!MODEL.overview?.nodes?.some(n=>n.id===selectedId)){selectedId=MODEL.overview?.nodes?.find(n=>n.attrs?.member_ids?.includes(selectedId))?.id||MODEL.overview?.nodes?.[0]?.id||selectedId}else if(next==="workflow"&&current?.type==="Aggregate"){selectedId=current.attrs?.focus_member_id||current.attrs?.member_ids?.[0]||selectedId}else if(next==="sequence"){const scopes=MODEL.sequence?.scopes||[],scope=scopes.find(item=>item.id===selectedId||item.member_ids?.includes(selectedId)||item.step_ids?.some(stepId=>MODEL.sequence.steps.find(step=>step.id===stepId)?.node_id===selectedId))||scopes[0];if(scope){sequenceScopeId=scope.id;const firstStep=MODEL.sequence.steps.find(step=>step.id===scope.step_ids?.[0]);selectedId=scope.focus_member_id&&findNode(scope.focus_member_id)?scope.focus_member_id:firstStep?.node_id||selectedId}}view=next;document.querySelectorAll(".view-tab").forEach(b=>{const active=b.dataset.view===view;b.classList.toggle("active",active);b.setAttribute("aria-selected",String(active))})}
function renderDetails(){const root=document.getElementById("details");root.replaceChildren();const node=findNode(selectedId);if(!node){root.append(htmlEl("div","detail-empty",t("noDetails")));return}root.append(htmlEl("span","badge",PHASES[node.phase]||node.phase),htmlEl("h3","",label(node)),htmlEl("div","node-id",node.id));const dl=htmlEl("dl","kv");[[t("type"),node.type],[t("status"),node.status],[t("phase"),node.phase],[t("tool"),node.tool],[t("output"),node.output]].filter(x=>x[1]!==null&&x[1]!==undefined&&x[1]!=="").forEach(([k,v])=>dl.append(htmlEl("dt","",k),htmlEl("dd","",String(v))));root.append(dl);const memberIds=node.attrs?.member_ids||[];if(memberIds.length){const section=htmlEl("section","section");section.append(htmlEl("h4","",`${t("members")} · ${memberIds.length}`));memberIds.forEach(id=>{const member=findNode(id),button=htmlEl("button","relation",member?`${member.type} · ${label(member)}`:id);button.onclick=()=>{setView("workflow");selectNode(id)};section.append(button)});const expand=htmlEl("button","relation",t("expand"));expand.onclick=()=>{setView("workflow");selectNode(node.attrs?.focus_member_id||memberIds[0])};section.append(expand);root.append(section)}const attrs=Object.entries(node.attrs||{}).filter(([key,value])=>!["status","current_state","tool","executor","action_tool","output","result","action_output","member_ids"].includes(key)&&value!==null&&value!==undefined&&value!=="");if(attrs.length){const section=htmlEl("section","section");section.append(htmlEl("h4","",locale==="zh-CN"?"结构化信息":"Structured attributes"));const values=htmlEl("dl","kv");attrs.forEach(([key,value])=>values.append(htmlEl("dt","",key),htmlEl("dd","",typeof value==="object"?JSON.stringify(value):String(value))));section.append(values);root.append(section)}const captures=new Set(MODEL.trace.filter(e=>node.event_ids.includes(e.event_id)).map(e=>e.capture_mode));if(captures.has("reconstructed"))root.append(htmlEl("p","capture-note",t("reconstructed")));const edges=activeEdges(),incoming=edges.filter(e=>e.to===node.id),outgoing=edges.filter(e=>e.from===node.id);[[t("incoming"),incoming,"in"],[t("outgoing"),outgoing,"out"]].forEach(([title,edges,dir])=>{if(!edges.length)return;const section=htmlEl("section","section");section.append(htmlEl("h4","",title));edges.forEach(e=>section.append(relationButton(e,dir)));root.append(section)});const sources=MODEL.trace.filter(e=>node.event_ids.includes(e.event_id));if(sources.length){const section=htmlEl("section","section");section.append(htmlEl("h4","",t("source")));sources.forEach(e=>section.append(htmlEl("div","relation",`#${e.sequence} · ${e.kind} · ${e.capture_mode}`)));root.append(section)}}
function renderText(){const bundle=LOCALES[locale]||{};document.documentElement.lang=locale;document.getElementById("pageTitle").textContent=bundle.title||SOURCE_TITLE;document.getElementById("subtitle").textContent=t("subtitle");document.getElementById("timelineTitle").textContent=t("timelineTitle");document.getElementById("timelineHint").textContent=`${MODEL.trace.length} ${t("events")} · ${t("timelineHint")}`;document.getElementById("detailsTitle").textContent=t("detailsTitle");document.getElementById("detailsHint").textContent=t("detailsHint");document.getElementById("fitButton").textContent=t("fit");document.querySelectorAll(".view-tab").forEach(b=>b.textContent=t(b.dataset.view));const controls=document.getElementById("sequenceControls"),scopeSelect=document.getElementById("sequenceScopeSelect"),legend=document.getElementById("legend");controls.hidden=view!=="sequence";legend.hidden=view==="sequence";document.getElementById("sequenceScopeLabel").textContent=t("sequenceScope");if(view==="sequence"){const scopes=MODEL.sequence?.scopes||[];if(!scopes.some(scope=>scope.id===sequenceScopeId))sequenceScopeId=scopes[0]?.id||null;scopeSelect.replaceChildren(...scopes.map(scope=>{const option=document.createElement("option"),aggregate=findNode(scope.id);option.value=scope.id;option.textContent=aggregate?label(aggregate):scope.label;return option}));scopeSelect.value=sequenceScopeId||""}else{const items=MODEL.phases.map(phase=>{const item=htmlEl("span"),dot=htmlEl("i","dot");dot.style.setProperty("--c",COLORS[phase]);item.append(dot,document.createTextNode(PHASES[phase]));return item});if(view==="workflow"||view==="evidence"){const counts=new Map();MODEL.edges.filter(edge=>SEMANTIC_EDGES.has(edge.type)).forEach(edge=>counts.set(edge.type,(counts.get(edge.type)||0)+1));["frames","informs","supersedes","invokes","produces","supports","checks"].filter(type=>counts.has(type)).forEach(type=>items.push(htmlEl("span","relation-chip",`${type} ${counts.get(type)}`)))}legend.replaceChildren(...items)}}
function render(){renderText();renderTimeline();renderGraph();renderDetails()}function selectNode(id){if(!findNode(id))return;selectedId=id;if(view==="sequence"){const scope=MODEL.sequence?.scopes?.find(item=>item.member_ids?.includes(id)||item.step_ids?.some(stepId=>MODEL.sequence.steps.find(step=>step.id===stepId)?.node_id===id));if(scope)sequenceScopeId=scope.id}selectionFocused=true;render()}document.querySelectorAll(".view-tab").forEach(button=>button.addEventListener("click",()=>{setView(button.dataset.view);selectionFocused=false;render()}));document.getElementById("sequenceScopeSelect").addEventListener("change",event=>{sequenceScopeId=event.target.value;selectionFocused=false;const scope=sequenceScope();if(scope?.focus_member_id&&findNode(scope.focus_member_id))selectedId=scope.focus_member_id;render()});document.getElementById("languageSelect").value=locale;document.getElementById("languageSelect").addEventListener("change",e=>{locale=e.target.value;render()});document.getElementById("fitButton").addEventListener("click",()=>document.getElementById("canvasShell").scrollTo({top:0,left:0,behavior:"smooth"}));window.addEventListener("resize",()=>{if(view!=="trace")renderGraph()});setView(view);render();
const readerReturn=htmlEl("a","reader-return","主路径 / Key path");readerReturn.href="graph.html";document.querySelector(".top-actions").prepend(readerReturn);
</script></body></html>"""


def _json_for_html(value: Any) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_html(model: dict[str, Any], *, title: str, display_locales: dict[str, dict[str, Any]] | None = None, default_locale: str = "zh-CN") -> str:
    return (HTML_TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__MODEL_JSON__", _json_for_html(model)).replace("__DISPLAY_LOCALES_JSON__", _json_for_html(display_locales or {})).replace("__SOURCE_TITLE_JSON__", _json_for_html(title)).replace("__DEFAULT_LOCALE_JSON__", _json_for_html(default_locale)))


def write_projection(out_dir: str | Path, *, graph: dict[str, Any], events: list[dict[str, Any]], findings: list[dict[str, Any]], title: str, display_locales: dict[str, dict[str, Any]] | None = None, default_locale: str = "zh-CN", presentation: dict[str, Any] | None = None) -> dict[str, Any]:
    target = Path(out_dir); target.mkdir(parents=True, exist_ok=True); (target / "graph.mmd").unlink(missing_ok=True); model = build_trace_model(graph, events); overview = build_loop_projection(graph, model); model["overview"] = overview; sequence = build_sequence_projection(model, overview); model["sequence"] = sequence
    outputs = {"graph.json": json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "runtime-advice.json": json.dumps(graph.get("runtime_advice", {}), ensure_ascii=False, indent=2, sort_keys=True) + "\n", "trace-model.json": json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "loop-model.json": json.dumps(overview, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "sequence-model.json": json.dumps(sequence, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "trace.puml": render_plantuml(model), "sequence.puml": render_sequence_plantuml(sequence), "graph.html": render_html(model, title=title, display_locales=display_locales, default_locale=default_locale), "lint.json": json.dumps(findings, ensure_ascii=False, indent=2, sort_keys=True) + "\n"}
    reader = build_reader_model(graph, model)
    outputs["workbench-legacy.html"] = outputs["graph.html"]
    workbench = build_workbench_model(reader, model)
    outputs["workbench.html"] = render_workbench_html(workbench, title=title, display_locales=display_locales, default_locale=default_locale)
    outputs["workbench-model.json"] = json.dumps(workbench, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    story = build_story_model(reader, presentation)
    outputs["reader.html"] = render_reader_html(reader, title=title, display_locales=display_locales, default_locale=default_locale)
    outputs["graph.html"] = render_story_html(story, title=title, display_locales=display_locales, default_locale=default_locale)
    outputs["story-model.json"] = json.dumps(story, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    outputs["review-model.json"] = json.dumps(reader, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    for name, content in outputs.items(): atomic_write_text(target / name, content)
    receipt = {"schema_version": SCHEMA_VERSION, "protocol_version": PROTOCOL_VERSION, "graph_id": graph["graph_id"], "projected_from": graph.get("source_ledger"), "generated_at": graph["generated_at"], "display": {"default_locale": default_locale, "locales": sorted((display_locales or {}).keys()), "style_reference": "Graph of Trace three-panel workbench plus nested-loop/sequence/workflow/evidence/trace layers"}, "outputs": {name: {"sha256": sha256_file(target / name), "size_bytes": (target / name).stat().st_size} for name in sorted(outputs)}, "lint": {"errors": sum(item["severity"] == "error" for item in findings), "warnings": sum(item["severity"] == "warning" for item in findings)}}
    receipt["display"].update(primary_view="key-path-graph", reading_view="reader.html", technical_view="workbench.html",
                              workbench_protocol_version=workbench["protocol_version"],
                              story_protocol_version=story["protocol_version"], authored_presentation=story["authored"],
                              reader_protocol_version=reader["protocol_version"],
                              style_reference="Graph-first key path with local evidence expansion; reader and technical workbench remain available")
    atomic_write_text(target / "projection-receipt.json", canonical_json(receipt) + "\n"); return receipt
