"use strict";
const payload=JSON.parse(document.getElementById('storyData').textContent), model=payload.model, reader=model.reader;
const nodes=new Map(reader.nodes.map(n=>[n.id,n])), stages=new Map(reader.stages.map(s=>[s.id,s]));
const cards=new Map(model.cards.map(c=>[c.id,c])), mainCards=model.cards.filter(c=>!c.parent_id);
const map=document.getElementById('storyMap'), cardElements=new Map();
let locale=payload.default_locale==='en-US'?'en-US':'zh-CN', selected=null, selectedSources=[], branches=true;
const words={
 'zh-CN':{reader:'阅读页',advanced:'完整关系',eye:'关键路径 / 分支与结果',main:'主路径 · 复盘顺序',branch:'旁支 · 尝试与产物',branchShort:'旁支',branches:'显示旁支',collapse:'收起展开',legend:'虚线＝复盘顺序 / 主题分组；展开后的箭头＝原始关系',gain:'局部收益',open:'未解决',negative:'负面结果',hypothesis:'待验证',paused:'暂缓',recorded:'源记录',source:'来源',reconstructed:'历史重建，非本次实测',synthetic:'合成示例，不是实际执行',observed:'源记录视图，不新增验证',gap:'轮正文缺失',authored:'主路径、旁支和结果短句为来源绑定的编辑视图；配色不升级证据状态。',fallback:'按记录组织阶段，未自动推断成功、失败或因果。',counts:'阶段均可追溯；不同阶段的数据不能直接作公平性能对比。',details:'局部展开',detailHint:'只展开这一项的动作、结果和结论；来源字段保留原文。',actions:'做了什么',results:'得到什么',claims:'说明什么',unrecorded:'此范围没有记录',relations:'原始关系与反证',boundary:'结论限制',raw:'来源与原始字段',close:'关闭局部展开',fullReader:'阅读这一阶段',fullGraph:'查看完整关系',global:'来源边界与未归入阶段的记录',originalStatus:'原状态',expand:'展开动作与证据',supplement:'文档补充',excerpt:'会话摘录',produces:'产生',verified_by:'验证收据',supports:'支持',refutes:'反驳',informs:'提供背景',supersedes:'取代',frames:'界定',invokes:'调用',references:'引用',explains:'解释',reported:'报告结论',confirmed:'源状态：confirmed',refuted:'已被反驳',none:'暂无可投影的阶段，请查看完整关系。'},
 'en-US':{reader:'Reader',advanced:'All relations',eye:'KEY PATH / BRANCHES & OUTCOMES',main:'Main path · review order',branch:'Branches · attempts & artifacts',branchShort:'Branch',branches:'Show branches',collapse:'Collapse detail',legend:'Dashed = review order / topic grouping; expanded arrows = recorded relations',gain:'Local gain',open:'Unresolved',negative:'Negative',hypothesis:'Hypothesis',paused:'Paused',recorded:'Recorded',source:'Source',reconstructed:'Historical reconstruction, not a new measurement',synthetic:'Synthetic example, not an actual execution',observed:'Source view, no new verification',gap:'turns missing content',authored:'Path, branches and short outcomes are source-bound editorial annotations; color does not upgrade evidence status.',fallback:'Stages follow records; success, failure and causality are not inferred.',counts:'stages remain traceable; measurements across stages are not fair performance comparisons.',details:'Local expansion',detailHint:'Only this item’s actions, outputs and conclusions are expanded. Source fields remain verbatim.',actions:'Action',results:'Output',claims:'Conclusion',unrecorded:'Not recorded in this scope',relations:'Recorded relations & counterevidence',boundary:'Limitations',raw:'Sources & raw fields',close:'Close local expansion',fullReader:'Read this stage',fullGraph:'Inspect all relations',global:'Source boundaries & unscoped records',originalStatus:'Original status',expand:'Expand actions & evidence',supplement:'Document supplement',excerpt:'Conversation excerpt',produces:'produces',verified_by:'verified by',supports:'supports',refutes:'refutes',informs:'informs',supersedes:'supersedes',frames:'frames',invokes:'invokes',references:'references',explains:'explains',reported:'Reported',confirmed:'Source: confirmed',refuted:'Refuted',none:'No stages could be projected. Inspect all relations.'}
};
const t=k=>words[locale][k]||k;
const e=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
const label=id=>payload.locales[locale]?.nodes?.[id]||nodes.get(id)?.label||id;
const title=c=>!model.authored&&c.stage_ids.length===1?(payload.locales[locale]?.nodes?.[stages.get(c.stage_ids[0]).title_node_id]||c.title):c.title;
const button=(text,cls,action)=>{const b=e('button',cls,text);b.type='button';b.addEventListener('click',action);return b;};
function link(text,href){const a=e('a','',text);a.href=href;return a;}
function sourceLink(value){let safe=false;try{safe=['https:','http:','file:','codex:'].includes(new URL(value).protocol);}catch{}return safe?link(value,value):e('span','',value);}
function sourceNode(id,showBoundary=true){
 const node=nodes.get(id), box=e('article','evidence-node');box.dataset.nodeId=id;
 box.append(e('p','',label(id)),e('div','node-status',`${node.type} · ${t('originalStatus')}: ${node.status||'—'}`));
 if(node.attrs?.user_quote)box.append(e('blockquote','',node.attrs.user_quote));
 if(showBoundary&&node.attrs?.boundary)box.append(e('p','detail-boundary',node.attrs.boundary));
 const detail=e('details'), summary=e('summary','',t('raw')), list=e('ul','source-list');
 for(const ref of node.provenance?.source_refs||[]){const li=e('li');li.append(sourceLink(ref));list.append(li);}
 detail.append(summary,e('div','node-status',id),list,e('pre','',JSON.stringify(node.attrs||{},null,2)));box.append(detail);return box;
}
function scopeNodes(card){return new Set([...card.node_ids,...card.stage_ids.flatMap(id=>stages.get(id).related_node_ids)]);}
function cardResults(card){
 if(card.results.length)return card.results;
 const ids=card.stage_ids.flatMap(id=>{const s=stages.get(id);return s.conclusion_ids.length?s.conclusion_ids:s.result_ids;});
 return ids.map(id=>({tone:'recorded',text:label(id),source_ids:[id]}));
}
function cardView(card){
 const box=e('article','map-card'+(card.parent_id?' branch-card':'')+(selected===card.id?' selected':''));box.dataset.cardId=card.id;cardElements.set(card.id,box);
 const open=button(undefined,'card-open',()=>selectCard(card.id));open.dataset.branchLabel=t('branchShort');open.setAttribute('aria-expanded',String(selected===card.id));open.setAttribute('aria-label',title(card)+' · '+t('expand'));
 const heading=e('span','card-heading');heading.append(e('span','card-title',title(card)),e('span','card-toggle',selected===card.id?'−':'+'));open.append(heading);
 if(card.summary)open.append(e('span','card-summary',card.summary));
 const kinds=new Set(card.stage_ids.flatMap(id=>stages.get(id).source_kinds));
 const sourceText=[kinds.has('conversation_excerpt')?t('excerpt'):null,kinds.has('workspace_artifact_supplement')?t('supplement'):null].filter(Boolean).join(' + ');
 if(sourceText)open.append(e('span','card-source',sourceText));box.append(open);
 const results=e('div','result-list');
 for(const result of cardResults(card)){
  const b=button(undefined,'result-note tone-'+result.tone,()=>selectCard(card.id,result.source_ids));
  b.append(e('span','tone-label',t(result.tone)),e('span','result-text',result.text));b.setAttribute('aria-label',`${result.text} · ${t('source')}`);results.append(b);
 }
 box.append(results);if(card.boundary)box.append(e('p','card-boundary',card.boundary));return box;
}
function column(ids,name){const col=e('div','local-column');col.append(e('h4','',t(name)));if(!ids.length)col.append(e('p','detail-hint',t('unrecorded')));for(const id of ids)col.append(sourceNode(id,false));return col;}
function arrow(from,to,types){const matching=reader.edges.filter(edge=>from.includes(edge.from)&&to.includes(edge.to)&&types.includes(edge.type));const n=e('div','local-arrow',matching.length?'→':'');if(matching.length){n.setAttribute('role','img');n.setAttribute('aria-label',[...new Set(matching.map(edge=>t(edge.type)))].join(', '));}return n;}
function detailsView(card){
 const detail=e('section','local-detail');detail.id='localDetail';detail.setAttribute('aria-label',t('details')+' · '+title(card));
 const head=e('div','detail-heading');const close=button('×','',()=>selectCard(card.id));close.setAttribute('aria-label',t('close'));head.append(e('h2','',t('details')+' / '+title(card)),close);detail.append(head,e('p','detail-hint',t('detailHint')));
 if(selectedSources.length){const sourceDetail=e('div','selected-sources');sourceDetail.append(e('h3','',t('source')));for(const id of selectedSources)sourceDetail.append(sourceNode(id));detail.append(sourceDetail);}
 for(const stageId of card.stage_ids){
  const stage=stages.get(stageId), section=e('section','local-stage'), flow=e('div','local-flow');
  if(card.stage_ids.length>1)section.append(e('h3','',stage.title));
  flow.append(column(stage.action_ids,'actions'),arrow(stage.action_ids,stage.result_ids,['produces','verified_by']),column(stage.result_ids,'results'),arrow(stage.result_ids,stage.conclusion_ids,['supports','refutes','explains']),column(stage.conclusion_ids,'claims'));
  section.append(flow);
  for(const id of stage.decision_ids)section.append(sourceNode(id));
  for(const boundary of stage.boundaries)section.append(e('p','detail-boundary',t('boundary')+' · '+boundary));
  detail.append(section);
 }
 for(const id of card.node_ids)detail.append(sourceNode(id));
 const scope=scopeNodes(card), relationBox=e('details','local-relations'), list=e('ul');relationBox.append(e('summary','',t('relations')));
 const owned=new Set([...card.node_ids,...card.stage_ids.flatMap(id=>{const s=stages.get(id);return [...s.plan_ids,...s.action_ids,...s.result_ids,...s.conclusion_ids,...s.decision_ids];})]);
 for(const edge of reader.edges.filter(edge=>scope.has(edge.from)&&scope.has(edge.to)&&!['contains','has_run','instance_of'].includes(edge.type)&&(owned.has(edge.from)||owned.has(edge.to)))){
  const li=e('li','',`${label(edge.from)} — ${t(edge.type)} → ${label(edge.to)}`);li.dataset.edgeId=edge.id;list.append(li);
 }
 relationBox.append(list);detail.append(relationBox);
 const counters=new Set(card.stage_ids.flatMap(id=>stages.get(id).counterevidence_ids));
 const counterTargets=new Set(reader.edges.filter(edge=>counters.has(edge.id)).map(edge=>edge.to));
 for(const id of counterTargets){const note=e('div','counterevidence');note.append(e('p','detail-boundary',`${t('refutes')}: ${label(id)}`),sourceNode(id));detail.append(note);}
 const links=e('div','detail-links');for(const id of card.stage_ids)links.append(link(t('fullReader'),`reader.html#stage=${encodeURIComponent(id)}`));links.append(link(t('fullGraph'),'workbench.html'));detail.append(links);return detail;
}
function drawWires(){
 map.querySelector('.map-wires')?.remove();if(!mainCards.length)return;
 const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.classList.add('map-wires');svg.setAttribute('aria-hidden','true');
 const base=map.getBoundingClientRect(), rect=node=>{const r=node.getBoundingClientRect();return {x:r.left-base.left,y:r.top-base.top,w:r.width,h:r.height};};
 const line=(d,cls)=>{const p=document.createElementNS(ns,'path');p.setAttribute('d',d);p.setAttribute('class','map-wire '+cls);svg.append(p);};
 const numbers=[...map.querySelectorAll('.stage-number')].map(rect);
 for(const [i,card] of mainCards.entries()){const a=numbers[i],b=rect(cardElements.get(card.id));line(`M${a.x+a.w},${a.y+a.h/2} H${b.x}`,'order-tick');}
 for(let i=1;i<numbers.length;i++){const a=numbers[i-1],b=numbers[i];line(`M${a.x+a.w/2},${a.y+a.h} V${b.y}`,'order');}
 if(branches)for(const card of model.cards.filter(c=>c.parent_id)){
  const from=rect(cardElements.get(card.parent_id)),to=rect(cardElements.get(card.id));
  if(matchMedia('(max-width:620px)').matches){line(`M${from.x+12},${from.y+from.h} V${to.y+to.h/2} H${to.x}`,'branch');}
  else {const mid=(from.x+from.w+to.x)/2;line(`M${from.x+from.w},${from.y+32} H${mid} V${to.y+32} H${to.x}`,'branch');}
 }
 map.prepend(svg);
}
function render(anchor=null){
 document.documentElement.lang=locale;document.getElementById('storyLanguage').value=locale;
 for(const [id,key] of [['readerLink','reader'],['advancedLink','advanced'],['eyebrow','eye'],['branchesText','branches'],['collapseSelection','collapse'],['mapLegend','legend'],['globalEvidenceTitle','global']])document.getElementById(id).textContent=t(key);
 document.getElementById('storyTitle').textContent=model.title||payload.locales[locale]?.title||payload.title;
 const modes=reader.capture_modes;let notice=modes.includes('reconstructed')?t('reconstructed'):modes.includes('synthetic')?t('synthetic'):t('observed');
 const missing=reader.coverage.turns_without_items;if(Number.isInteger(missing))notice+=` · ${missing} ${t('gap')}`;
 document.getElementById('coverageNotice').textContent=notice;
 document.getElementById('mapFootnote').textContent=(model.authored?t('authored'):t('fallback'))+` ${reader.stages.length} `+t('counts');
 const globalBody=document.getElementById('globalEvidenceBody');globalBody.replaceChildren();if(reader.boundary)globalBody.append(e('p','',reader.boundary));
 for(const id of new Set([...reader.global_boundary_ids,...reader.unscoped_node_ids]))globalBody.append(sourceNode(id));
 const columns=document.getElementById('columnLabels');columns.replaceChildren(e('span','',t('main')),e('span','branch-heading',t('branch')));
 const hasBranches=model.cards.some(c=>c.parent_id);document.getElementById('branchesLabel').hidden=!hasBranches;document.body.classList.toggle('no-branches',!branches||!hasBranches);document.getElementById('showBranches').checked=branches;
 document.getElementById('collapseSelection').disabled=!selected;
 map.replaceChildren();cardElements.clear();
 for(const [i,card] of mainCards.entries()){
  const row=e('div','map-row');row.dataset.mainId=card.id;row.append(e('span','stage-number',String(i+1).padStart(2,'0')),cardView(card));
  const stack=e('div','branch-stack');if(branches)for(const branch of model.cards.filter(c=>c.parent_id===card.id))stack.append(cardView(branch));row.append(stack);
  if(selected&&(selected===card.id||cards.get(selected)?.parent_id===card.id))row.append(detailsView(cards.get(selected)));map.append(row);
 }
 if(!mainCards.length)map.append(e('p','empty',t('none')));
 drawWires();
 if(anchor){const target=cardElements.get(anchor.id);if(target){window.scrollBy(0,target.getBoundingClientRect().top-anchor.top);target.querySelector('.card-open').focus({preventScroll:true});}}
}
function selectCard(id,sources=[]){
 const prior=cardElements.get(id),anchor=prior?{id,top:prior.getBoundingClientRect().top}:null;
 selected=selected===id&&!sources.length?null:id;selectedSources=sources;
 history.pushState(null,'',selected?`#card=${encodeURIComponent(selected)}`:location.pathname);
 render(anchor);document.getElementById('announcer').textContent=selected?t('details')+' · '+title(cards.get(selected)):t('collapse');
}
function readHash(){const params=new URLSearchParams(location.hash.slice(1)),card=params.get('card'),stage=params.get('stage');selected=cards.has(card)?card:model.cards.find(c=>c.stage_ids.includes(stage))?.id||null;selectedSources=[];if(cards.get(selected)?.parent_id)branches=true;}
document.getElementById('showBranches').addEventListener('change',event=>{branches=event.target.checked;if(!branches&&cards.get(selected)?.parent_id){selected=null;selectedSources=[];history.replaceState(null,'',location.pathname);}render();});
document.getElementById('collapseSelection').addEventListener('click',()=>{if(selected)selectCard(selected);});
document.getElementById('storyLanguage').addEventListener('change',event=>{locale=event.target.value;render();});
window.addEventListener('hashchange',()=>{readHash();render();});
window.addEventListener('keydown',event=>{if(event.key==='Escape'&&selected)selectCard(selected);});
new ResizeObserver(()=>drawWires()).observe(map);
readHash();render();
if(selected)requestAnimationFrame(()=>cardElements.get(selected)?.scrollIntoView({block:'center'}));
