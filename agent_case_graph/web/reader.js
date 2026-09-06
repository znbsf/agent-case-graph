"use strict";
const payload = JSON.parse(document.getElementById("readerData").textContent);
const model = payload.model;
const nodes = new Map(model.nodes.map(node => [node.id, node]));
const edges = new Map(model.edges.map(edge => [edge.id, edge]));
const ui = {
  "zh-CN": {
    brand:"决策历程", advanced:"技术视图 ↗", main:"先看主线", stages:"阶段索引", overview:"工作如何走到这里",
    intro:"按阶段读问题、尝试与结果。这里只整理已有记录，不把先后顺序当作因果。",
    start:"最初关注的问题", latest:"这份记录停在哪里", path:"关键过程", why:"要解决什么", action:"做了什么",
    result:"得到什么结果", conclusion:"记录中的结论", decisions:"为什么调整方向", boundary:"不能据此声称什么",
    evidence:"查看本阶段的证据与来源", relations:"查看本阶段的关联", records:"检查原始字段", sources:"来源入口",
    unknown:"没有记录，不能补推。", noStages:"还没有可整理的执行阶段。可到技术视图检查已有节点。",
    order:"阅读顺序，不是耗时或真实迭代计数", prev:"← 上一阶段", next:"下一阶段 →", all:"返回主线",
    reconstructed:"历史重建", synthetic:"合成示例", live:"现场记录", mixed:"混合来源", provenance:"来源未标明",
    captureHint:"页面是记录的只读整理，不是新的执行或验收。", missing:"轮正文未返回", readable:"轮有正文", total:"轮元数据",
    conversation:"会话节选", supplement:"工程材料补充", counter:"含反证", excerpt:"相关记录", unscoped:"节点仍保留在技术视图；未硬塞进阶段。",
    boundaryTitle:"阅读边界", stage:"阶段", sourceOrder:"最近不等于已完成", reported:"记录所述 · 未重新验证", open:"仍开放",
    hypothesis:"待验证假设", refuted:"被反证的主张", rejected:"记录为拒绝", failed:"记录为失败", confirmed:"记录为确认",
    completed:"记录为完成", passed:"记录为通过", verified:"记录为已验证", accepted:"记录为接受", recorded:"已有记录",
    supports:"支持 →", refutes:"反证 →", informs:"影响 →", frames:"设定目标 →", invokes:"调用 →", produces:"产生 →",
    precedes:"先于 →", supersedes:"替代 / 收敛 →", references:"引用 →", checks:"检查 →", otherRelation:"关联 →"
  },
  "en-US": {
    brand:"Decision journey", advanced:"Technical view ↗", main:"Read the main path", stages:"STAGES", overview:"How the work got here",
    intro:"Read each question, attempt and result. This organizes existing records; order is not proof of causality.",
    start:"Initial question", latest:"Where these records leave off", path:"The main path", why:"What was the question?", action:"What was done?",
    result:"What was observed?", conclusion:"Recorded conclusions", decisions:"Why the direction changed", boundary:"What this does not establish",
    evidence:"Inspect this stage's evidence and sources", relations:"Inspect this stage's relationships", records:"Inspect raw fields", sources:"Source references",
    unknown:"Not recorded; no inference supplied.", noStages:"No execution spans are available. Inspect the existing nodes in the technical view.",
    order:"Reading order, not duration or an observed iteration count", prev:"← Previous stage", next:"Next stage →", all:"Back to the main path",
    reconstructed:"Historical reconstruction", synthetic:"Synthetic example", live:"Live records", mixed:"Mixed sources", provenance:"Provenance unavailable",
    captureHint:"Read-only organization, not a new execution or verification.", missing:"turns without returned content", readable:"turns with content", total:"turn metadata entries",
    conversation:"Conversation excerpts", supplement:"Workspace supplement", counter:"Counterevidence present", excerpt:"Related records", unscoped:"nodes remain in the technical view, without forced stage assignment.",
    boundaryTitle:"Reading boundaries", stage:"Stage", sourceOrder:"Latest does not mean complete", reported:"As reported · not reverified", open:"Open",
    hypothesis:"Hypothesis", refuted:"Refuted claim", rejected:"Recorded as rejected", failed:"Recorded as failed", confirmed:"Recorded as confirmed",
    completed:"Recorded as complete", passed:"Recorded as passed", verified:"Recorded as verified", accepted:"Recorded as accepted", recorded:"Recorded",
    supports:"supports →", refutes:"refutes →", informs:"informs →", frames:"frames →", invokes:"invokes →", produces:"produces →",
    precedes:"precedes →", supersedes:"supersedes →", references:"references →", checks:"checks →", otherRelation:"relates to →"
  }
};
let language = ui[payload.default_locale] ? payload.default_locale : "zh-CN";
const t = key => ui[language][key] || key;
const nodeLabel = id => payload.locales[language]?.nodes?.[id] || nodes.get(id)?.label || "";
const cleanTitle = text => String(text).replace(/^\d{1,2}\s+/, "");
const stageTitle = stage => cleanTitle(stage.title_node_id ? nodeLabel(stage.title_node_id) : stage.title);
const stageHref = stage => "#stage=" + encodeURIComponent(stage.id);

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function link(text, href, className) {
  const node = element("a", className, text);
  node.href = href;
  return node;
}
function currentStage() {
  const id = new URLSearchParams(location.hash.slice(1)).get("stage");
  return model.stages.find(stage => stage.id === id) || null;
}
function sourceKind(stage) {
  const kinds = stage.source_kinds || [];
  const labels = [];
  if (kinds.includes("conversation_excerpt")) labels.push(t("conversation"));
  if (kinds.includes("workspace_artifact_supplement")) labels.push(t("supplement"));
  return labels.length ? labels.join(" + ") : stage.capture_modes.map(mode => t(mode)).join(" / ");
}
function statusNode(node) {
  const status = node.status || "recorded";
  const label = ui[language][status] || status;
  return element("span", "status" + (["refuted", "failed", "rejected"].includes(status) ? " negative" : ""), label);
}
function addNodeText(parent, ids, fallback = true) {
  const unique = [...new Set(ids)].filter(id => nodes.has(id));
  for (const id of unique) {
    const paragraph = element("p", "node-text", nodeLabel(id));
    paragraph.dataset.sourceNode = id;
    parent.append(paragraph);
  }
  if (!unique.length && fallback) parent.append(element("p", "empty", t("unknown")));
}
function heading(text) {
  return element("h2", "section-caption", text);
}
function disclosure(title, className = "") {
  const details = element("details", "disclosure " + className);
  details.append(element("summary", "", title));
  return details;
}
function renderNavigation(selected) {
  const nav = document.getElementById("stageNav");
  nav.replaceChildren(element("p", "nav-caption", t("stages")));
  const home = link(t("main"), "#", "stage-link");
  if (!selected) home.setAttribute("aria-current", "page");
  nav.append(home);
  const select = element("select");
  select.id = "mobileStageSelect";
  select.setAttribute("aria-label", t("stages"));
  select.append(new Option(t("main"), ""));
  model.stages.forEach((stage, index) => {
    const anchor = link("", stageHref(stage), "stage-link");
    anchor.dataset.stage = stage.id;
    if (selected?.id === stage.id) anchor.setAttribute("aria-current", "page");
    anchor.append(element("span", "stage-number", String(index + 1).padStart(2, "0")), element("span", "", stageTitle(stage)));
    nav.append(anchor);
    select.append(new Option(`${index + 1}. ${stageTitle(stage)}`, stage.id));
  });
  select.value = selected?.id || "";
  select.addEventListener("change", () => { location.hash = select.value ? "stage=" + encodeURIComponent(select.value) : ""; });
  nav.append(select);
}
function renderCoverage() {
  const notice = document.getElementById("coverageNotice");
  const modes = model.capture_modes;
  notice.replaceChildren(element("strong", "", modes.length ? modes.map(mode => t(mode)).join(" / ") : t("provenance")));
  notice.append(document.createTextNode(" · " + t("captureHint")));
  const counts = model.coverage, values = [];
  for (const [key, label] of [["returned_turn_metadata", "total"], ["turns_with_visible_items", "readable"], ["turns_without_items", "missing"]]) {
    if (Number.isInteger(counts[key])) values.push(`${counts[key]} ${t(label)}`);
  }
  if (values.length) notice.append(element("p", "coverage-counts", values.join(" · ")));
}
function renderOverview(root) {
  root.append(element("p", "eyebrow", t("overview")));
  root.append(element("h1", "", payload.locales[language]?.title || payload.title));
  root.append(element("p", "lede", t("intro")));
  if (!model.stages.length) { root.append(element("p", "empty", t("noStages"))); return; }
  const first = model.stages[0], last = model.stages[model.stages.length - 1];
  const orientation = element("section", "orientation");
  for (const [caption, id] of [["start", first.goal_ids[0]], ["latest", last.conclusion_ids.find(key => nodes.get(key)?.status !== "refuted") || last.result_ids[0]]]) {
    const box = element("div");
    box.append(element("h2", "", t(caption)), element("p", "", caption === "latest" ? stageTitle(last) : id ? nodeLabel(id) : t("unknown")));
    if (caption === "latest" && id) box.append(element("small", "empty", nodeLabel(id)));
    orientation.append(box);
  }
  root.append(orientation, element("h2", "", t("path")), element("p", "eyebrow", t("order")));
  const list = element("ol", "path-list");
  model.stages.forEach((stage, index) => {
    const item = element("li", "path-item"); item.dataset.stage = stage.id;
    item.append(element("span", "path-index", String(index + 1).padStart(2, "0")));
    const title = element("div", "path-heading");
    title.append(link(stageTitle(stage), stageHref(stage)), element("span", "source-tag", sourceKind(stage)));
    if (stage.counterevidence_ids.length) title.append(element("span", "counter-tag", t("counter")));
    item.append(title);
    const conclusion = stage.conclusion_ids.find(id => nodes.get(id)?.status !== "refuted");
    if (conclusion) item.append(element("p", "path-conclusion", nodeLabel(conclusion)));
    if (stage.result_ids.length) item.append(element("p", "path-result", nodeLabel(stage.result_ids[0])));
    stage.decision_ids.forEach(id => item.append(element("p", "decision-note", nodeLabel(id))));
    list.append(item);
  });
  root.append(list);
  const boundary = disclosure(t("boundaryTitle"));
  if (model.boundary) boundary.append(element("p", "node-text", model.boundary));
  addNodeText(boundary, model.global_boundary_ids, false);
  boundary.append(element("p", "empty", `${model.unscoped_node_ids.length} ${t("unscoped")}`));
  root.append(boundary);
}
function safeSource(ref) {
  // No auto-loading. Unknown schemes, including javascript/data, stay inert.
  if (/[\u0000-\u001f\u007f]/.test(ref)) return null;
  try { const url = new URL(ref); return ["https:", "http:", "codex:", "file:"].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}
function sourceLabel(ref) {
  try {
    const url = new URL(ref);
    if (url.protocol === "codex:") return language === "zh-CN" ? "源会话 / 回合定位" : "Source conversation / turn reference";
    if (url.protocol === "file:") return decodeURIComponent(url.pathname.split("/").pop()) || ref;
    return url.hostname + url.pathname;
  } catch { return ref; }
}
function renderEvidence(stage, parent) {
  const evidence = disclosure(t("evidence"), "stage-evidence");
  evidence.append(element("p", "empty", sourceKind(stage)));
  const relations = stage.relation_ids.map(id => edges.get(id)).filter(Boolean);
  const artifactIds = stage.related_node_ids.filter(id => nodes.get(id)?.type === "Artifact");
  const refs = [...new Set(stage.source_refs)];
  for (const id of artifactIds) {
    const artifact = nodes.get(id), attrs = artifact.attrs || {};
    const section = element("div");
    section.append(element("h3", "", nodeLabel(id)));
    for (const key of ["boundary", "sha256"]) if (attrs[key]) section.append(element("p", "empty", `${key === "sha256" ? "SHA256 · " : ""}${attrs[key]}`));
    evidence.append(section);
  }
  evidence.append(element("h3", "", t("sources")));
  const sources = element("ul", "source-list");
  refs.forEach(ref => {
    const item = element("li"), href = safeSource(ref);
    const label = href ? link(sourceLabel(ref), href) : element("span", "", ref);
    if (href) label.setAttribute("rel", "noreferrer noopener");
    item.append(label, element("small", "", ref)); sources.append(item);
  });
  if (!refs.length) sources.append(element("li", "empty", t("unknown")));
  evidence.append(sources);
  parent.append(evidence);
  const relationPanel = disclosure(t("relations"), "stage-relations");
  relationPanel.append(element("p", "empty", t("intro")));
  const list = element("ul", "relation-list");
  relations.forEach(edge => {
    const row = element("li"); row.dataset.relationId = edge.id;
    row.append(element("span", "", nodeLabel(edge.from)), element("span", "relation-verb" + (edge.type === "refutes" ? " negative" : ""), ui[language][edge.type] || `${edge.type} →`), element("span", "", nodeLabel(edge.to)));
    list.append(row);
  });
  relationPanel.append(list); parent.append(relationPanel);
  const raw = disclosure(t("records"), "raw-fields");
  raw.addEventListener("toggle", () => {
    if (raw.open && !raw.querySelector("pre")) {
      raw.append(element("pre", "tech-fields", JSON.stringify(stage.related_node_ids.map(id => nodes.get(id)), null, 2)));
    }
  });
  parent.append(raw);
}
function renderStage(root, stage) {
  const index = model.stages.indexOf(stage);
  root.append(element("p", "eyebrow", `${t("stage")} ${String(index + 1).padStart(2, "0")} / ${model.stages.length} · ${sourceKind(stage)}`), element("h1", "", stageTitle(stage)));
  const question = element("section", "stage-section"); question.append(heading(t("why"))); addNodeText(question, stage.goal_ids); root.append(question);
  if (stage.decision_ids.length) {
    const decisions = element("section", "stage-section"); decisions.append(heading(t("decisions")));
    for (const id of stage.decision_ids) {
      decisions.append(element("p", "decision-note", nodeLabel(id)));
      const quote = nodes.get(id)?.attrs?.user_quote;
      if (quote) decisions.append(element("blockquote", "", quote));
    }
    root.append(decisions);
  }
  const action = element("section", "stage-section"); action.append(heading(t("action")));
  for (const id of stage.plan_ids) {
    const summary = nodes.get(id)?.attrs?.summary;
    if (summary) action.append(element("p", "node-text", summary));
  }
  addNodeText(action, stage.action_ids); root.append(action);
  const results = element("section", "stage-section result-section"); results.append(element("h2", "", t("result"))); addNodeText(results, stage.result_ids);
  for (const id of stage.conclusion_ids) {
    const claim = element("p", "claim-row");
    claim.append(statusNode(nodes.get(id)), document.createTextNode(nodeLabel(id))); results.append(claim);
  }
  root.append(results);
  const boundary = element("section", "stage-section boundary"); boundary.append(element("h2", "", t("boundary")));
  stage.boundaries.forEach(text => boundary.append(element("p", "", text)));
  addNodeText(boundary, stage.uncertainty_ids, !stage.boundaries.length); root.append(boundary);
  renderEvidence(stage, root);
  const footer = element("nav", "stage-footer"); footer.setAttribute("aria-label", t("stages"));
  footer.append(index ? link(t("prev"), stageHref(model.stages[index - 1])) : link(t("all"), "#"));
  footer.append(index < model.stages.length - 1 ? link(t("next"), stageHref(model.stages[index + 1])) : link(t("all"), "#"));
  root.append(footer);
}
function render() {
  document.documentElement.lang = language;
  document.getElementById("readerLanguage").value = language;
  document.getElementById("brand").textContent = t("brand");
  document.getElementById("advancedLink").textContent = t("advanced");
  const selected = currentStage();
  renderNavigation(selected); renderCoverage();
  const root = document.getElementById("readerContent"); root.replaceChildren();
  if (selected) renderStage(root, selected); else renderOverview(root);
}
document.getElementById("readerLanguage").addEventListener("change", event => { language = event.target.value; render(); });
window.addEventListener("hashchange", () => { render(); document.getElementById("content").focus({preventScroll:true}); window.scrollTo(0,0); });
render();
