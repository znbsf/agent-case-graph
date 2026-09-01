from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from .ledger import atomic_write_text, canonical_json, sha256_file
from .model import SCHEMA_VERSION
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
    evidence_edges = {"supports", "checks", "explains", "derived_from", "uses", "produces"}
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
.legend{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px;color:var(--muted);font-size:10px}.legend span{display:inline-flex;align-items:center;gap:4px}.dot{width:8px;height:8px;border-radius:2px;background:var(--c)}.canvas-shell{min-height:0;overflow:auto;background:linear-gradient(#f4f7fa 1px,transparent 1px),linear-gradient(90deg,#f4f7fa 1px,transparent 1px),#fbfcfe;background-size:24px 24px}#graphSvg{display:block;min-width:100%;min-height:100%}
.edge{fill:none;stroke:#94a3b8;stroke-width:1.2}.edge.evidence{stroke-dasharray:5 4}.edge.quiet{stroke:#cbd5e1}.edge.dim{opacity:.20}.edge.active{stroke:var(--selected);stroke-width:2.2;opacity:1}.node{cursor:pointer}.node rect{stroke:#8493a6;stroke-width:1;rx:9;filter:url(#nodeShadow)}.node:hover rect,.node.active rect{stroke:var(--selected);stroke-width:2}.node.dim{opacity:.44}.node .phase{font-size:8px;font-weight:750;letter-spacing:.08em;fill:#526173}.node .label{font-size:11px;font-weight:650;fill:var(--ink)}.node .meta{font-size:8.5px;fill:#64748b}
.trace-cards{padding:28px;display:grid;gap:10px;max-width:820px;margin:0 auto}.trace-card{display:grid;grid-template-columns:50px 1fr;gap:12px;border:1px solid var(--line);border-radius:10px;background:#fff;padding:12px}.trace-card strong{font-size:12px}.trace-card p{margin:4px 0 0;color:var(--muted);font-size:11px}.details{height:calc(100vh - 135px);overflow:auto;padding:16px}.detail-empty{color:var(--muted);padding:20px 0}.badge{display:inline-flex;border-radius:999px;padding:3px 7px;background:var(--soft);color:var(--muted);font-size:10px;font-weight:700}.details h3{margin:10px 0 5px;font-size:16px}.node-id{color:var(--muted);font:10px/1.5 ui-monospace,monospace;overflow-wrap:anywhere}
.section{margin-top:18px;padding-top:14px;border-top:1px solid var(--line)}.section h4{margin:0 0 8px;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}.kv{display:grid;grid-template-columns:72px 1fr;gap:6px;font-size:11px}.kv dt{color:var(--muted)}.kv dd{margin:0;overflow-wrap:anywhere}.relation{display:block;width:100%;border:0;border-radius:7px;background:var(--soft);text-align:left;padding:7px 8px;margin:5px 0;color:var(--ink);cursor:pointer;font-size:10px}.capture-note{margin:10px 0 0;border-left:3px solid #f59e0b;padding:7px 9px;background:#fff8e8;color:#72510d;font-size:10px}
@media(max-width:1050px){.workspace{grid-template-columns:220px minmax(420px,1fr)}.details-panel{display:none}}@media(max-width:720px){.topbar{padding:13px 14px}.workspace{grid-template-columns:1fr}.timeline-panel{display:none}.center-head{align-items:flex-start;flex-direction:column}.legend{justify-content:flex-start}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
</style></head><body><div class="app"><header class="topbar"><div class="brand"><h1 id="pageTitle">__TITLE__</h1><p id="subtitle"></p></div><div class="top-actions"><select id="languageSelect" aria-label="显示语言"><option value="zh-CN">中文</option><option value="en-US">English</option></select><button id="fitButton" type="button">适合画布</button></div></header>
<main class="workspace"><aside class="panel timeline-panel"><div class="panel-head"><h2 id="timelineTitle"></h2><p id="timelineHint"></p></div><div class="timeline" id="timeline"></div></aside><section class="panel center"><div class="center-head"><div class="view-tabs" role="tablist"><button class="view-tab active" data-view="workflow" role="tab" aria-selected="true"></button><button class="view-tab" data-view="evidence" role="tab" aria-selected="false"></button><button class="view-tab" data-view="trace" role="tab" aria-selected="false"></button></div><div class="legend" id="legend"></div></div><div class="canvas-shell" id="canvasShell"><svg id="graphSvg" role="img" aria-label="Layered agent workflow graph"></svg></div></section><aside class="panel details-panel"><div class="panel-head"><h2 id="detailsTitle"></h2><p id="detailsHint"></p></div><div class="details" id="details"></div></aside></main></div>
<script>
const MODEL=__MODEL_JSON__,LOCALES=__DISPLAY_LOCALES_JSON__,SOURCE_TITLE=__SOURCE_TITLE_JSON__,DEFAULT_LOCALE=__DEFAULT_LOCALE_JSON__;
const UI={"zh-CN":{subtitle:"论文式 Trace：从结论反查动作、产物和原始记录",timelineTitle:"原始 Trace",timelineHint:"保留顺序，不把时间当成因果",detailsTitle:"节点证据",detailsHint:"选择节点查看输入、产出与关系",fit:"适合画布",workflow:"工作流",evidence:"证据链",trace:"原始记录",tool:"工具",output:"产出",status:"状态",phase:"阶段",type:"类型",incoming:"上游关系",outgoing:"下游关系",source:"源记录",reconstructed:"历史重建：可审阅，但不等同于原生执行遥测。",events:"项记录"},"en-US":{subtitle:"Paper-style trace: audit actions, artifacts, and source records from a claim",timelineTitle:"Source trace",timelineHint:"Sequence is preserved without claiming causality",detailsTitle:"Node evidence",detailsHint:"Select a node to inspect inputs, outputs, and relations",fit:"Fit canvas",workflow:"Workflow",evidence:"Evidence",trace:"Trace records",tool:"Tool",output:"Output",status:"Status",phase:"Phase",type:"Type",incoming:"Incoming",outgoing:"Outgoing",source:"Source records",reconstructed:"Historical reconstruction: reviewable, but not native execution telemetry.",events:"records"}};
const PHASES={context:"Context",plan:"Plan",inspect:"Inspect",execute:"Execute",validate:"Validate",claim:"Claim"},COLORS={context:"#dbeafe",plan:"#e0e7ff",inspect:"#ede9fe",execute:"#ffedd5",validate:"#dcfce7",claim:"#fce7f3"},EVIDENCE_EDGES=new Set(["supports","refutes","checks","explains","derived_from","uses","produces","approved_by","verified_by","references","tested_by","satisfies"]),QUIET_EDGES=new Set(["contains","has_run"]);
let locale=LOCALES[DEFAULT_LOCALE]?DEFAULT_LOCALE:"zh-CN",view="workflow",selectedId=MODEL.root_id||MODEL.nodes[0]?.id||null,selectionFocused=false;const svg=document.getElementById("graphSvg"),ns="http://www.w3.org/2000/svg";
function t(key){return (UI[locale]||UI["zh-CN"])[key]||key}function label(node){return LOCALES[locale]?.nodes?.[node.id]||node.label}function el(name,attrs={}){const node=document.createElementNS(ns,name);Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,String(v)));return node}function htmlEl(name,className,text){const node=document.createElement(name);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node}function relatedIds(id){const ids=new Set([id]);MODEL.edges.forEach(e=>{if(e.from===id)ids.add(e.to);if(e.to===id)ids.add(e.from)});return ids}
function visibleGraph(){if(view==="workflow"){const nodes=MODEL.nodes.filter(n=>n.primary),ids=new Set(nodes.map(n=>n.id)),candidates=MODEL.edges.filter(e=>e.layout&&ids.has(e.from)&&ids.has(e.to)),incoming=new Set(candidates.filter(e=>!QUIET_EDGES.has(e.type)).map(e=>e.to)),edges=candidates.filter(e=>e.type!=="contains"||!incoming.has(e.to));return{nodes,edges}}const ids=new Set(MODEL.nodes.filter(n=>n.level==="evidence").map(n=>n.id));MODEL.edges.filter(e=>EVIDENCE_EDGES.has(e.type)&&(ids.has(e.from)||ids.has(e.to))).forEach(e=>{ids.add(e.from);ids.add(e.to)});return{nodes:MODEL.nodes.filter(n=>ids.has(n.id)),edges:MODEL.edges.filter(e=>ids.has(e.from)&&ids.has(e.to)&&!QUIET_EDGES.has(e.type))}}
function wrap(text,max=29){if(text.length<=max)return[text];const cut=text.lastIndexOf(" ",max),at=cut>12?cut:max,tail=text.slice(at).trim();return[text.slice(0,at),tail.slice(0,max)+(tail.length>max?"…":"")]}
function renderGraph(){svg.replaceChildren();if(view==="trace"){renderTraceCards();return}const{nodes,edges}=visibleGraph(),byRank=new Map();nodes.forEach(n=>{const rank=n.rank||0;if(!byRank.has(rank))byRank.set(rank,[]);byRank.get(rank).push(n)});const ranks=[...byRank.keys()].sort((a,b)=>a-b),cardW=176,cardH=62,minGap=22,maxColumns=3,maxAcross=Math.max(1,...[...byRank.values()].map(group=>Math.min(maxColumns,group.length))),contentWidth=80+maxAcross*cardW+(maxAcross-1)*minGap,width=Math.max(680,document.getElementById("canvasShell").clientWidth,contentWidth),rowGap=106,top=58,pos=new Map();let visualRow=0;ranks.forEach(rank=>{const group=byRank.get(rank).sort((a,b)=>a.phase.localeCompare(b.phase)||a.id.localeCompare(b.id));for(let offset=0;offset<group.length;offset+=maxColumns){const chunk=group.slice(offset,offset+maxColumns),gap=Math.max(minGap,(width-80-chunk.length*cardW)/Math.max(1,chunk.length-1)),total=chunk.length*cardW+(chunk.length-1)*gap,start=Math.max(40,(width-total)/2);chunk.forEach((n,i)=>pos.set(n.id,{x:start+i*(cardW+gap),y:top+visualRow*rowGap}));visualRow++}});const height=Math.max(520,top+visualRow*rowGap+80);svg.setAttribute("viewBox",`0 0 ${width} ${height}`);svg.setAttribute("width",width);svg.setAttribute("height",height);const defs=el("defs"),marker=el("marker",{id:"arrow",viewBox:"0 0 10 10",refX:9,refY:5,markerWidth:6,markerHeight:6,orient:"auto-start-reverse"});marker.append(el("path",{d:"M 0 0 L 10 5 L 0 10 z",fill:"#94a3b8"}));const filter=el("filter",{id:"nodeShadow",x:"-20%",y:"-20%",width:"140%",height:"160%"});filter.append(el("feDropShadow",{dx:0,dy:2,stdDeviation:2,"flood-color":"#21364d","flood-opacity":".10"}));defs.append(marker,filter);svg.append(defs);const active=selectionFocused&&selectedId?relatedIds(selectedId):new Set();edges.forEach(edge=>{const a=pos.get(edge.from),b=pos.get(edge.to);if(!a||!b)return;const x1=a.x+cardW/2,y1=a.y+cardH,x2=b.x+cardW/2,y2=b.y,mid=(y1+y2)/2;svg.append(el("path",{d:`M ${x1} ${y1} C ${x1} ${mid}, ${x2} ${mid}, ${x2} ${y2}`,"marker-end":"url(#arrow)",class:`edge ${EVIDENCE_EDGES.has(edge.type)?"evidence":""} ${QUIET_EDGES.has(edge.type)?"quiet":""} ${selectionFocused&&selectedId&&!(edge.from===selectedId||edge.to===selectedId)?"dim":""} ${selectionFocused&&(edge.from===selectedId||edge.to===selectedId)?"active":""}`}))});nodes.forEach(node=>{const p=pos.get(node.id),group=el("g",{class:`node ${node.id===selectedId?"active":""} ${selectionFocused&&selectedId&&!active.has(node.id)?"dim":""}`,tabindex:"0",role:"button","aria-label":label(node)});group.setAttribute("transform",`translate(${p.x} ${p.y})`);group.append(el("rect",{width:cardW,height:cardH,fill:COLORS[node.phase]||"#fff"}));const phase=el("text",{x:12,y:15,class:"phase"});phase.textContent=PHASES[node.phase]||node.phase;group.append(phase);wrap(label(node),26).forEach((line,i)=>{const text=el("text",{x:12,y:33+i*14,class:"label"});text.textContent=line;group.append(text)});const meta=el("text",{x:cardW-10,y:15,class:"meta","text-anchor":"end"});meta.textContent=node.type;group.append(meta);group.addEventListener("click",()=>selectNode(node.id));group.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" ")selectNode(node.id)});svg.append(group)})}
function renderTraceCards(){const height=Math.max(600,MODEL.trace.length*82);svg.setAttribute("viewBox",`0 0 900 ${height}`);svg.setAttribute("height",height);const foreign=el("foreignObject",{x:0,y:0,width:900,height}),list=htmlEl("div","trace-cards");MODEL.trace.forEach(item=>{const card=htmlEl("div","trace-card");card.append(htmlEl("strong","",`#${item.sequence}`));const body=htmlEl("div");body.append(htmlEl("strong","",item.kind),htmlEl("p","",`${item.actor.type}:${item.actor.id} · ${item.capture_mode} · ${item.occurred_at}`));card.append(body);if(item.node_id){card.style.cursor="pointer";card.onclick=()=>selectNode(item.node_id)}list.append(card)});foreign.append(list);svg.append(foreign)}
function renderTimeline(){const root=document.getElementById("timeline");root.replaceChildren();MODEL.trace.forEach(item=>{const button=htmlEl("button",`event ${item.node_id===selectedId?"active":""}`),seq=htmlEl("span","event-seq",`#${item.sequence}`),body=htmlEl("span");body.append(htmlEl("span","event-kind",item.kind),htmlEl("div","event-meta",`${item.actor.type}:${item.actor.id} · ${item.capture_mode}`));button.append(seq,body);if(item.node_id)button.onclick=()=>selectNode(item.node_id);root.append(button)})}
function relationButton(edge,direction){const otherId=direction==="in"?edge.from:edge.to,other=MODEL.nodes.find(n=>n.id===otherId),button=htmlEl("button","relation",`${edge.type} · ${other?label(other):otherId}`);button.onclick=()=>selectNode(otherId);return button}
function renderDetails(){const root=document.getElementById("details");root.replaceChildren();const node=MODEL.nodes.find(n=>n.id===selectedId);if(!node){root.append(htmlEl("div","detail-empty",t("noDetails")));return}root.append(htmlEl("span","badge",PHASES[node.phase]||node.phase),htmlEl("h3","",label(node)),htmlEl("div","node-id",node.id));const dl=htmlEl("dl","kv");[[t("type"),node.type],[t("status"),node.status],[t("phase"),node.phase],[t("tool"),node.tool],[t("output"),node.output]].filter(x=>x[1]!==null&&x[1]!==undefined&&x[1]!=="").forEach(([k,v])=>dl.append(htmlEl("dt","",k),htmlEl("dd","",String(v))));root.append(dl);const captures=new Set(MODEL.trace.filter(e=>node.event_ids.includes(e.event_id)).map(e=>e.capture_mode));if(captures.has("reconstructed"))root.append(htmlEl("p","capture-note",t("reconstructed")));const incoming=MODEL.edges.filter(e=>e.to===node.id),outgoing=MODEL.edges.filter(e=>e.from===node.id);[[t("incoming"),incoming,"in"],[t("outgoing"),outgoing,"out"]].forEach(([title,edges,dir])=>{if(!edges.length)return;const section=htmlEl("section","section");section.append(htmlEl("h4","",title));edges.forEach(e=>section.append(relationButton(e,dir)));root.append(section)});const sources=MODEL.trace.filter(e=>node.event_ids.includes(e.event_id));if(sources.length){const section=htmlEl("section","section");section.append(htmlEl("h4","",t("source")));sources.forEach(e=>section.append(htmlEl("div","relation",`#${e.sequence} · ${e.kind} · ${e.capture_mode}`)));root.append(section)}}
function renderText(){const bundle=LOCALES[locale]||{};document.documentElement.lang=locale;document.getElementById("pageTitle").textContent=bundle.title||SOURCE_TITLE;document.getElementById("subtitle").textContent=t("subtitle");document.getElementById("timelineTitle").textContent=t("timelineTitle");document.getElementById("timelineHint").textContent=`${MODEL.trace.length} ${t("events")} · ${t("timelineHint")}`;document.getElementById("detailsTitle").textContent=t("detailsTitle");document.getElementById("detailsHint").textContent=t("detailsHint");document.getElementById("fitButton").textContent=t("fit");document.querySelectorAll(".view-tab").forEach(b=>b.textContent=t(b.dataset.view));const legend=document.getElementById("legend");legend.replaceChildren(...MODEL.phases.map(phase=>{const item=htmlEl("span"),dot=htmlEl("i","dot");dot.style.setProperty("--c",COLORS[phase]);item.append(dot,document.createTextNode(PHASES[phase]));return item}))}
function render(){renderText();renderTimeline();renderGraph();renderDetails()}function selectNode(id){if(!MODEL.nodes.some(n=>n.id===id))return;selectedId=id;selectionFocused=true;render()}document.querySelectorAll(".view-tab").forEach(button=>button.addEventListener("click",()=>{view=button.dataset.view;document.querySelectorAll(".view-tab").forEach(b=>{b.classList.toggle("active",b===button);b.setAttribute("aria-selected",String(b===button))});renderGraph()}));document.getElementById("languageSelect").value=locale;document.getElementById("languageSelect").addEventListener("change",e=>{locale=e.target.value;render()});document.getElementById("fitButton").addEventListener("click",()=>document.getElementById("canvasShell").scrollTo({top:0,left:0,behavior:"smooth"}));window.addEventListener("resize",()=>{if(view!=="trace")renderGraph()});render();
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


def write_projection(out_dir: str | Path, *, graph: dict[str, Any], events: list[dict[str, Any]], findings: list[dict[str, Any]], title: str, display_locales: dict[str, dict[str, Any]] | None = None, default_locale: str = "zh-CN") -> dict[str, Any]:
    target = Path(out_dir); target.mkdir(parents=True, exist_ok=True); (target / "graph.mmd").unlink(missing_ok=True); model = build_trace_model(graph, events)
    outputs = {"graph.json": json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "trace-model.json": json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "trace.puml": render_plantuml(model), "graph.html": render_html(model, title=title, display_locales=display_locales, default_locale=default_locale), "lint.json": json.dumps(findings, ensure_ascii=False, indent=2, sort_keys=True) + "\n"}
    for name, content in outputs.items(): atomic_write_text(target / name, content)
    receipt = {"schema_version": SCHEMA_VERSION, "protocol_version": PROTOCOL_VERSION, "graph_id": graph["graph_id"], "projected_from": graph.get("source_ledger"), "generated_at": graph["generated_at"], "display": {"default_locale": default_locale, "locales": sorted((display_locales or {}).keys()), "style_reference": "Graph of Trace three-panel DAG plus LEDGER workflow/evidence/trace layers"}, "outputs": {name: {"sha256": sha256_file(target / name), "size_bytes": (target / name).stat().st_size} for name in sorted(outputs)}, "lint": {"errors": sum(item["severity"] == "error" for item in findings), "warnings": sum(item["severity"] == "warning" for item in findings)}}
    atomic_write_text(target / "projection-receipt.json", canonical_json(receipt) + "\n"); return receipt
