"use strict";
const payload=JSON.parse(document.getElementById('workbenchData').textContent), M=payload.model;
const nodes=new Map(M.nodes.map(n=>[n.id,n])), edges=new Map(M.edges.map(e=>[e.id,e]));
const groups=new Map(M.groups.map(g=>[g.id,g])), scopes=new Map(M.scopes.map(s=>[s.id,s]));
const summaryEdges=new Map(M.group_edges.map(e=>[e.id,e]));
const $=id=>document.getElementById(id), ns='http://www.w3.org/2000/svg';
const canvas=$('canvasShell'),world=$('graphWorld'),svg=$('graphSvg'),nodeLayer=$('graphNodes');
let locale=payload.default_locale==='en-US'?'en-US':'zh-CN',view='overview',scopeId='all',selected=null,focusId=null;
let zoom=1,dimensions={width:800,height:500},rects=new Map(),shownNodes=[],shownEdges=[],tracePage=0,drag=null,detailMode=null;
const UI={
 'zh-CN':{overview:'阶段总览',workflow:'阶段关系',evidence:'证据链',sequence:'单次执行',trace:'原始记录',all:'全部阶段',stages:'阶段',stageCaption:'按阶段定位 · 不代表已完成',scope:'查看范围',focus:'只看相邻关系',clear:'退出聚焦',filters:'关系筛选',structure:'结构关系',order:'顺序关系',fit:'适合宽度',fitAll:'适合全图',canvasHint:'拖动空白平移 · Ctrl + 滚轮缩放 · 100% 阅读',search:'搜索节点 / ID',legend:'虚线：顺序 / 证据　实线：记录关系　箭头不代表因果已证实',overviewHint:'阶段是展示分组；每条聚合边可展开到原始边。点击卡片下方进入局部关系。',workflowHint:'同阶段节点放在一起；位置只为阅读，不补画不存在的关系。',evidenceHint:'从结论追溯支持、反证与检查；原始状态不等于本次验证。',sequenceHint:'按已有时序约束排列；相邻消息不代表因果。',traceHint:'保留源记录顺序；含节点、边和状态事件。',expand:'展开此阶段 →',shared:'共享节点',unscoped:'未归入阶段的记录',derived:'展示分组',explicit:'显式迭代',members:'成员',relations:'原始关系',sources:'来源记录',raw:'原始字段',details:'节点与证据',basis:'结构依据',basisIntro:'研究支持的是设计原则，不是本工作台的验收结论。',basisOwn:'本项目设计：确定性阶段分组、共享节点单列、聚合边绑定原始边。没有自动补因果，没有新增验收。',boundary:'证据边界',close:'关闭',empty:'此范围没有匹配的节点。可返回全部阶段或调整关系筛选。',context:'关联上下文',status:'源状态',recorded:'已记录',reported:'报告结论',hypothesis:'待验证',open:'未闭合',refuted:'已反驳',failed:'失败',rejected:'已拒绝',blocked:'受阻',passed:'记录为通过',verified:'记录为验证',confirmed:'记录为确认',completed:'记录为完成',synthetic:'合成示例',reconstructed:'历史重建 · 非本次实测',live:'现场记录 · 非新增验证',missing:'轮正文缺失',nodeCount:'节点',edgeCount:'关系',hidden:'当前未展示',returnAll:'返回全局',from:'起点',to:'终点',witness:'聚合依据',unavailable:'未提供',claim:'结论',action:'动作',output:'输出 / 检查',plan:'目标 / 计划',counter:'反证',precedes:'顺序',informs:'提供背景',supersedes:'取代 / 收敛',invokes:'调用',produces:'产生',supports:'支持',refutes:'反驳',checks:'检查',verified_by:'验证依据',references:'引用',frames:'界定',contains:'包含',has_run:'所属运行',instance_of:'实例',uses:'使用',derived_from:'派生自',tested_by:'测试依据',explains:'解释',retry_of:'重试',user:'用户',agent:'Agent',tool:'工具',world:'证据 / 外界',evaluator:'评估器',noMatches:'没有匹配节点',searchMore:'仅显示前 30 项，请继续输入缩小范围。'},
 'en-US':{overview:'Stages',workflow:'Stage relations',evidence:'Evidence',sequence:'Sequence',trace:'Source records',all:'All stages',stages:'Stages',stageCaption:'Navigate stages · not completion',scope:'Scope',focus:'Focus neighbors',clear:'Clear focus',filters:'Relations',structure:'Structure',order:'Sequence relations',fit:'Fit width',fitAll:'Fit all',canvasHint:'Drag background to pan · Ctrl + wheel to zoom · Read at 100%',search:'Search nodes / IDs',legend:'Dashed: order / evidence · Solid: recorded relation · Not verified causality',overviewHint:'Stages are display groups. Every summary edge expands to original edges. Expand a card to inspect its local graph.',workflowHint:'Related work stays together. Placement does not invent relations.',evidenceHint:'Trace claims to support, counterevidence and checks. Source status is not new verification.',sequenceHint:'Existing temporal constraints order the messages; adjacency is not causality.',traceHint:'Original order, including node, edge and state events.',expand:'Expand stage →',shared:'Shared nodes',unscoped:'Unscoped records',derived:'Display group',explicit:'Explicit iteration',members:'Members',relations:'Original relations',sources:'Source records',raw:'Raw fields',details:'Node & evidence',basis:'Research basis',basisIntro:'Research informs the design; it does not validate this implementation.',basisOwn:'Project-specific design: deterministic scopes, separate shared nodes, and canonical witnesses for summary edges. No inferred causality or new verification.',boundary:'Evidence boundary',close:'Close',empty:'No matching nodes in this scope. Return to all stages or adjust the filters.',context:'Related context',status:'Source status',recorded:'Recorded',reported:'Reported',hypothesis:'Hypothesis',open:'Open',refuted:'Refuted',failed:'Failed',rejected:'Rejected',blocked:'Blocked',passed:'Recorded pass',verified:'Recorded verification',confirmed:'Recorded confirmation',completed:'Recorded completion',synthetic:'Synthetic example',reconstructed:'Historical reconstruction · not a new measurement',live:'Live records · no new verification',missing:'turns missing content',nodeCount:'nodes',edgeCount:'relations',hidden:'not displayed',returnAll:'Return to overview',from:'From',to:'To',witness:'Canonical witnesses',unavailable:'Not provided',claim:'Conclusion',action:'Action',output:'Output / check',plan:'Goal / plan',counter:'Counterevidence',precedes:'precedes',informs:'informs',supersedes:'supersedes',invokes:'invokes',produces:'produces',supports:'supports',refutes:'refutes',checks:'checks',verified_by:'verified by',references:'references',frames:'frames',contains:'contains',has_run:'has run',instance_of:'instance of',uses:'uses',derived_from:'derived from',tested_by:'tested by',explains:'explains',retry_of:'retry of',user:'User',agent:'Agent',tool:'Tool',world:'Evidence / world',evaluator:'Evaluator',noMatches:'No matching nodes',searchMore:'Showing the first 30 matches. Refine your search.'}
};
const t=k=>UI[locale][k]||k;
const label=id=>payload.locales[locale]?.nodes?.[id]||nodes.get(id)?.label||groups.get(id)?.label||id;
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
const se=(tag,attrs={})=>{const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));return n;};
const btn=(text,cls,fn)=>{const n=el('button',cls,text);n.type='button';n.addEventListener('click',fn);return n;};
const structureTypes=new Set(['contains','has_run','instance_of']);
const evidenceTypes=new Set(['supports','refutes','checks','verified_by','tested_by','references','uses','derived_from','explains','produces','invokes']);
const roleOf=n=>['Goal','Plan','Task','UserFeedback'].includes(n.type)?0:['Action','ToolCall','Step'].includes(n.type)?1:['Claim','RootCause','Outcome','AgentResponse','Decision','Uncertainty'].includes(n.type)?3:2;
function groupLabel(group){return group.kind==='stage'?(scopes.get(group.scope_id)?.title_node_id?label(scopes.get(group.scope_id).title_node_id):group.label):t(group.kind);}
function status(value){const n=el('span','status',t(value||'recorded'));if(['failed','refuted','rejected'].includes(value))n.classList.add('negative');else if(['open','blocked','hypothesis'].includes(value))n.classList.add('open');else if(['passed','verified','confirmed','completed'].includes(value))n.classList.add('positive');return n;}
function relationClass(edge){if(edge.relation_class)return edge.relation_class;if(structureTypes.has(edge.type))return 'structure';if(edge.type==='precedes')return 'order';if(evidenceTypes.has(edge.type)&&!['produces','invokes'].includes(edge.type))return 'evidence';return 'recorded';}
function allowed(edge){return ($('showStructure').checked||!structureTypes.has(edge.type))&&($('showOrder').checked||edge.type!=='precedes')&&(view!=='overview'||$('showEvidence').checked||relationClass(edge)!=='evidence');}
function baseScope(){if(scopeId==='all')return new Set(nodes.keys());if(scopes.has(scopeId))return new Set(scopes.get(scopeId).related_node_ids);return new Set(groups.get(scopeId)?.member_ids||[]);}
function visible(){
 if(view==='overview'){
  const list=scopeId==='all'?M.groups:M.groups.filter(g=>g.scope_id===scopeId||g.id===scopeId);
  const ids=new Set(list.map(g=>g.id));return {items:list,links:M.group_edges.filter(e=>ids.has(e.from)&&ids.has(e.to)&&allowed(e))};
 }
 let ids=baseScope();
 if(focusId&&ids.has(focusId)){const local=new Set([focusId]);for(const e of M.edges)if(allowed(e)&&ids.has(e.from)&&ids.has(e.to)&&(e.from===focusId||e.to===focusId)){local.add(e.from);local.add(e.to);}ids=local;}
 if(view==='evidence'){
  const links=M.edges.filter(e=>evidenceTypes.has(e.type)&&ids.has(e.from)&&ids.has(e.to)&&allowed(e));
  const relevant=new Set(links.flatMap(e=>[e.from,e.to]));for(const id of ids)if(['Claim','RootCause','Outcome','Uncertainty'].includes(nodes.get(id).type))relevant.add(id);
  return {items:M.nodes.filter(n=>relevant.has(n.id)),links};
 }
 return {items:M.nodes.filter(n=>ids.has(n.id)),links:M.edges.filter(e=>ids.has(e.from)&&ids.has(e.to)&&allowed(e))};
}
function makeNode(item,isGroup=false){
 const card=el('article','graph-node'+(selected===item.id?' selected':''));card.dataset.nodeId=item.id;card.dataset.kind=isGroup?'Group':item.type;
 if(!isGroup&&scopeId!=='all'&&scopes.has(scopeId)&&!scopes.get(scopeId).own_ids.includes(item.id)){card.classList.add('context-node');card.append(el('div','context-tag',t('context')));}
 card.style.width=(isGroup?400:280)+'px';
 const button=btn(undefined,'node-button',()=>select(item.id));button.setAttribute('aria-label',isGroup?groupLabel(item):label(item.id));
 const meta=el('span','node-meta');meta.append(el('span','node-type',isGroup?t(item.explicit?'explicit':'derived'):item.type),isGroup?el('span','',`${item.member_ids.length} ${t('nodeCount')}`):status(item.status));
 button.append(meta,el('span','node-title',isGroup?groupLabel(item):label(item.id)));
 if(isGroup){for(const id of item.conclusion_ids){const result=el('div','node-result');result.append(status(nodes.get(id).status),document.createTextNode(label(id)));button.append(result);}}
 card.append(button);if(isGroup)card.append(btn(t('expand'),'node-expand',()=>{scopeId=item.scope_id||item.id;view='workflow';selected=null;focusId=null;navigate(true);}));
 nodeLayer.append(card);return card;
}
function measure(card){return {width:card.offsetWidth,height:card.offsetHeight};}
function setRect(card,r){card.style.left=r.x+'px';card.style.top=r.y+'px';}
function drawEdges(links){
 svg.replaceChildren();const defs=se('defs');for(const [key,color] of [['normal','#7f91ab'],['refutes','#a73e44'],['active','#315da7']]){const marker=se('marker',{id:'arrow-'+key,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'});marker.append(se('path',{d:'M0 0 L10 5 L0 10 Z',fill:color}));defs.append(marker);}svg.append(defs);
 let maxX=dimensions.width,maxY=dimensions.height;
 for(const [i,edge] of links.entries()){
  const a=rects.get(edge.from),b=rects.get(edge.to);if(!a||!b)continue;
  const route=WorkbenchLayout.route(a,b,i,[...rects.values()]),active=selected===edge.from||selected===edge.to||selected===edge.id;
  for(const [x,y] of route.points){maxX=Math.max(maxX,x+90);maxY=Math.max(maxY,y+35);}
  const path=se('path',{d:WorkbenchLayout.path(route.points),class:`graph-edge ${relationClass(edge)} ${edge.type==='refutes'?'refutes':''} ${active?'active':''}`,'marker-end':`url(#arrow-${active?'active':edge.type==='refutes'?'refutes':'normal'})`,'data-edge-id':edge.id,'data-from':edge.from,'data-to':edge.to,'data-type':edge.type,role:'button',tabindex:0,'aria-label':`${t(edge.type)}: ${label(edge.from)} → ${label(edge.to)}`});
  path.addEventListener('click',()=>selectEdge(edge));path.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectEdge(edge);}});svg.append(path);
  const show=links.length<=22||active||edge.type==='refutes';if(show){const text=se('text',{x:route.label[0],y:route.label[1]-5,class:'edge-label','data-edge-label':edge.type});text.textContent=t(edge.type)+(edge.source_edge_ids?.length>1?` ×${edge.source_edge_ids.length}`:'');text.addEventListener('click',()=>selectEdge(edge));svg.append(text);}
 }
 dimensions={width:maxX,height:maxY};svg.setAttribute('width',maxX);svg.setAttribute('height',maxY);svg.setAttribute('viewBox',`0 0 ${maxX} ${maxY}`);
}
function drawGraph(){
 nodeLayer.replaceChildren();rects=new Map();const data=visible();shownNodes=data.items;shownEdges=data.links;
 const elements=new Map(data.items.map(item=>[item.id,makeNode(item,view==='overview')]));
 if(view==='overview'){
  const inputs=data.items.map(item=>({id:item.id,...measure(elements.get(item.id))}));
  const layout=WorkbenchLayout.layered(inputs,data.links.filter(e=>['precedes','informs','invokes'].includes(e.type)),{gap:84});rects=layout.rects;dimensions={width:layout.width,height:layout.height};
 }else if(scopeId==='all'&&!focusId){
  // Compound boxes keep one stage's work together. Their vertical order is a
  // reading index, explicitly not an additional dependency relation.
  let y=52,maxWidth=0;
  for(const group of M.groups){const members=data.items.filter(n=>M.node_owner[n.id]===group.id);if(!members.length)continue;
   const box=el('div','group-box'),caption=el('div','group-label',groupLabel(group));caption.append(el('small','',t('derived')));box.append(caption);box.style.cssText=`left:22px;top:${y}px;width:1390px`;nodeLayer.prepend(box);
   const headerHeight=caption.offsetHeight+30;let bottom=y+headerHeight;const columns=[[],[],[],[]];for(const n of members)columns[roleOf(n)].push(n);
   columns.forEach((items,col)=>{if(!items.length)return;const heading=el('div','column-label',t(['plan','action','output','claim'][col]));heading.style.cssText=`left:${20+col*350}px;top:${headerHeight-26}px`;box.append(heading);let ny=y+headerHeight;for(const n of items){const size=measure(elements.get(n.id));rects.set(n.id,{x:42+col*350,y:ny,...size});ny+=size.height+40;}bottom=Math.max(bottom,ny);});
   box.style.cssText=`left:22px;top:${y}px;width:1390px;height:${bottom-y+12}px`;y=bottom+65;maxWidth=1440;
  }
  dimensions={width:maxWidth,height:y};
 }else{
  const rankEdges=data.links.filter(e=>['frames','invokes','produces','supports','explains','verified_by'].includes(e.type));
  const layout=WorkbenchLayout.layered(data.items.map(n=>({id:n.id,...measure(elements.get(n.id))})),rankEdges,{direction:'TB',gap:76,pad:56});rects=layout.rects;dimensions={width:layout.width,height:layout.height};
 }
 for(const [id,r] of rects)setRect(elements.get(id),r);
 if(!data.items.length)nodeLayer.append(el('p','empty-state',t('empty')));
 drawEdges(data.links);applyZoom();updateCounts();
}
function currentSequence(){const available=M.sequence.scopes||[];if(scopeId!=='all')return available.find(s=>s.id===scopes.get(scopeId)?.sequence_scope_id);return available.find(s=>s.member_ids?.includes(selected))||available[0];}
function renderSequence(){
 nodeLayer.replaceChildren();svg.replaceChildren();rects=new Map();const scope=currentSequence(),stepsById=new Map((M.sequence.steps||[]).map(s=>[s.id,s]));
 const steps=(scope?.step_ids||[]).map(id=>stepsById.get(id)).filter(Boolean),participants=M.sequence.participants||[],positions=new Map();
 dimensions={width:Math.max(1000,participants.length*210+100),height:160};
 participants.forEach((p,i)=>{const x=60+i*210;positions.set(p.id,x+70);const n=el('div','participant',t(p.id));n.style.left=x+'px';n.style.top='30px';nodeLayer.append(n);});
 const defs=se('defs'),marker=se('marker',{id:'seqArrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto'});marker.append(se('path',{d:'M0 0 L10 5 L0 10 Z',fill:'#7f91ab'}));defs.append(marker);svg.append(defs);
 let y=120;for(const [i,step] of steps.entries()){
  const from=positions.get(step.from),to=positions.get(step.to);if(from===undefined||to===undefined)continue;
  const box=btn(`${i+1}. ${nodes.has(step.node_id)?label(step.node_id):step.label}`,'sequence-step',()=>select(step.node_id));box.dataset.nodeId=step.node_id;box.style.width='340px';nodeLayer.append(box);
  const height=box.offsetHeight;let x=Math.max(24,Math.min((from+to)/2-170,dimensions.width-370));box.style.left=x+'px';box.style.top=y+'px';
  y+=height+12;const d=from===to?`M${from} ${y} H${from+60} V${y+24} H${from}`:`M${from} ${y} H${to}`;
  svg.append(se('path',{d,class:'graph-edge','marker-end':'url(#seqArrow)'}));y+=70;
 }
 dimensions.height=Math.max(350,y);participants.forEach(p=>{const x=positions.get(p.id);const line=se('line',{x1:x,x2:x,y1:70,y2:y,class:'sequence-lifeline'});svg.insertBefore(line,svg.firstChild);});
 if(!steps.length)nodeLayer.append(el('p','empty-state',t('empty')));
 $('scopeHint').textContent=t('sequenceHint')+(scope?' · '+scope.label:'');
 svg.setAttribute('width',dimensions.width);svg.setAttribute('height',dimensions.height);svg.setAttribute('viewBox',`0 0 ${dimensions.width} ${dimensions.height}`);shownNodes=steps;shownEdges=[];applyZoom();updateCounts();
}
function applyZoom(){world.style.width=dimensions.width+'px';world.style.height=dimensions.height+'px';world.style.transform=`scale(${zoom})`;$('canvasSizer').style.width=Math.ceil(dimensions.width*zoom)+'px';$('canvasSizer').style.height=Math.ceil(dimensions.height*zoom)+'px';$('zoomReset').textContent=Math.round(zoom*100)+'%';}
function setZoom(value,point){const p=point||{x:canvas.clientWidth/2,y:canvas.clientHeight/2};const x=(canvas.scrollLeft+p.x)/zoom,y=(canvas.scrollTop+p.y)/zoom;zoom=Math.max(.2,Math.min(2.5,value));applyZoom();canvas.scrollLeft=x*zoom-p.x;canvas.scrollTop=y*zoom-p.y;}
function fit(all=false){const value=(canvas.clientWidth-30)/dimensions.width;setZoom(Math.min(1,all?Math.min(value,(canvas.clientHeight-30)/dimensions.height):value),{x:0,y:0});canvas.scrollTo(0,0);}
function updateCounts(){const count=view==='overview'?shownNodes.reduce((sum,g)=>sum+g.member_ids.length,0):shownNodes.length;const countEdges=view==='overview'?shownEdges.reduce((sum,e)=>sum+e.source_edge_ids.length,0):shownEdges.length;$('graphCounts').textContent=view==='trace'?`${M.trace.length} ${t('sources')}`:view==='sequence'?`${shownNodes.length} ${locale==='zh-CN'?'时序步骤 · 非原始边计数':'sequence steps · not canonical edge counts'}`:`${count} / ${M.nodes.length} ${t('nodeCount')} · ${countEdges} / ${M.edges.length} ${t('edgeCount')} · ${t('hidden')} ${Math.max(0,M.edges.length-countEdges)}`;}
function safeLink(value,text=value){let safe=false;try{safe=['http:','https:','file:','codex:'].includes(new URL(value).protocol);}catch{}const n=el(safe?'a':'span','',text);if(safe)n.href=value;return n;}
function openDetails(){detailMode='node';$('detailsPanel').hidden=false;$('detailsTitle').textContent=t('details');}
function detailSources(node){const refs=el('ul','source-list');for(const ref of node.provenance?.source_refs||[]){const li=el('li');li.append(safeLink(ref));refs.append(li);}return refs;}
function relationButton(edge){return btn(`${t(edge.type)} · ${label(edge.from)} → ${label(edge.to)}`,'detail-relation',()=>selectEdge(edge));}
function nodeDetail(node){
 const root=$('details');root.replaceChildren(el('h2','',label(node.id)),el('div','node-id',node.id),status(node.status));
 const actions=el('div','detail-tools');actions.append(btn(t('focus'),'',()=>{if(view==='overview'||view==='trace')view='workflow';scopeId='all';focusId=node.id;navigate(true);}));root.append(actions);
 if(node.attrs?.boundary)root.append(el('p','detail-boundary',node.attrs.boundary));
 if(node.attrs?.user_quote)root.append(el('blockquote','',node.attrs.user_quote));
 const incident=M.edges.filter(e=>e.from===node.id||e.to===node.id);root.append(el('h3','',t('relations')));for(const edge of incident)root.append(relationButton(edge));
 root.append(el('h3','',t('sources')),detailSources(node));
 for(const record of M.trace.filter(r=>(node.event_ids||[]).includes(r.event_id)))root.append(btn(`#${record.sequence} · ${record.kind}`,'detail-relation',()=>{view='trace';tracePage=Math.floor(M.trace.indexOf(record)/40);navigate();}));
 const raw=el('details');raw.append(el('summary','',t('raw')),el('pre','',JSON.stringify(node,null,2)));root.append(raw);
}
function groupDetail(group){
 const root=$('details');root.replaceChildren(el('h2','',groupLabel(group)),el('div','node-id',group.id),el('p','detail-boundary',t(group.explicit?'explicit':'derived')));
 root.append(btn(t('expand'),'',()=>{scopeId=group.scope_id||group.id;view='workflow';selected=null;navigate(true);}));
 root.append(el('h3','',`${t('members')} · ${group.member_ids.length}`));for(const id of group.member_ids)root.append(btn(label(id),'detail-relation',()=>select(id)));
 root.append(el('h3','',t('relations')));for(const edge of M.group_edges.filter(e=>e.from===group.id||e.to===group.id))root.append(relationButton(edge));
}
function select(id){if(!nodes.has(id)&&!groups.has(id))return;selected=id;openDetails();if(nodes.has(id))nodeDetail(nodes.get(id));else groupDetail(groups.get(id));highlight();saveHash();$('announcer').textContent=t('details')+' · '+label(id);}
function selectEdge(edge){
 selected=edge.id;openDetails();const root=$('details');root.replaceChildren(el('h2','',t(edge.type)),el('div','node-id',edge.id));
 root.append(el('p','detail-boundary',edge.source_edge_ids?t('derived')+' · '+t('witness'):t('legend')));
 for(const [name,id] of [[t('from'),edge.from],[t('to'),edge.to]])root.append(btn(`${name} · ${label(id)}`,'detail-relation',()=>select(id)));
 if(edge.source_edge_ids){root.append(el('h3','',`${t('witness')} · ${edge.source_edge_ids.length}`));for(const id of edge.source_edge_ids)root.append(relationButton(edges.get(id)));}
 else{root.append(el('h3','',t('sources')),detailSources(edge));for(const record of M.trace.filter(r=>(edge.event_ids||[]).includes(r.event_id)))root.append(el('p','',`#${record.sequence} · ${record.kind} · ${record.capture_mode}`));const raw=el('details');raw.append(el('summary','',t('raw')),el('pre','',JSON.stringify(edge,null,2)));root.append(raw);}
 highlight();saveHash();
}
function highlight(){for(const n of nodeLayer.querySelectorAll('.graph-node'))n.classList.toggle('selected',n.dataset.nodeId===selected);for(const p of svg.querySelectorAll('.graph-edge'))p.classList.toggle('active',p.dataset.edgeId===selected||p.dataset.from===selected||p.dataset.to===selected);for(const n of $('timeline').children)n.classList.toggle('active',n.dataset.nodeId===selected);$('focusButton').disabled=!nodes.has(selected)||view==='sequence';}
function showBasis(){detailMode='basis';$('detailsPanel').hidden=false;$('detailsTitle').textContent=t('basis');const root=$('details');root.replaceChildren(el('p','detail-boundary',t('basisIntro')),el('p','',t('basisOwn')));for(const paper of M.papers){const item=el('section','basis-item');item.append(safeLink(paper.url,paper.title),el('p','',paper.publication+' · '+paper.sections),el('p','',paper.basis),el('p','detail-boundary',paper.limit));root.append(item);}}
function renderTrace(){
 const records=M.trace;tracePage=Math.max(0,Math.min(tracePage,Math.max(0,Math.ceil(records.length/40)-1)));$('timeline').replaceChildren();
 for(const record of records.slice(tracePage*40,(tracePage+1)*40)){
  const event=btn(undefined,'event'+(selected===record.node_id?' active':''),()=>{if(record.node_id)select(record.node_id);else if(record.edge_id&&edges.has(record.edge_id))selectEdge(edges.get(record.edge_id));else{openDetails();$('details').replaceChildren(el('h2','',record.kind),el('pre','',JSON.stringify(record,null,2)));}});
  event.dataset.nodeId=record.node_id||'';const text=el('span');text.append(el('strong','',record.node_id?label(record.node_id):record.edge_id&&edges.has(record.edge_id)?t(edges.get(record.edge_id).type):record.kind),el('small','',`${record.kind} · ${record.capture_mode} · ${record.occurred_at}`));event.append(el('span','node-id','#'+record.sequence),text);$('timeline').append(event);
 }
 $('traceCount').textContent=`${records.length?tracePage*40+1:0}–${Math.min(records.length,(tracePage+1)*40)} / ${records.length}`;$('tracePrev').disabled=tracePage===0;$('traceNext').disabled=(tracePage+1)*40>=records.length;updateCounts();
}
function renderText(){
 document.documentElement.lang=locale;$('languageSelect').value=locale;$('pageTitle').textContent=payload.locales[locale]?.title||payload.title;
 for(const [id,key] of [['basisButton','basis'],['stageCaption','stageCaption'],['scopeLabel','scope'],['toggleStages','stages'],['focusButton','focus'],['clearFocus','clear'],['filterTitle','filters'],['structureLabel','structure'],['orderLabel','order'],['fitButton','fit'],['fitAllButton','fitAll'],['canvasHint','canvasHint'],['relationLegend','legend']])$(id).textContent=t(key);
 $('storyLink').textContent=locale==='zh-CN'?'主路径':'Key path';$('readerLink').textContent=locale==='zh-CN'?'阅读页':'Reader';$('searchInput').placeholder=t('search');
 $('coverageNotice').textContent=M.capture_modes.map(t).join(' + ')+(Number.isInteger(M.coverage.turns_without_items)?` · ${M.coverage.turns_without_items} ${t('missing')}`:'');
 $('scopeHint').textContent=t(view+'Hint');$('clearFocus').hidden=!focusId;$('focusButton').disabled=!nodes.has(selected)||view==='sequence';
 $('evidenceLabel').textContent=t('evidence');$('overviewEvidence').hidden=view!=='overview';
 for(const tab of document.querySelectorAll('.view-tab')){tab.textContent=t(tab.dataset.view);tab.setAttribute('aria-selected',String(tab.dataset.view===view));}
 const options=[{id:'all',text:t('all')},...M.groups.map(g=>({id:g.scope_id||g.id,text:groupLabel(g)}))];$('scopeSelect').replaceChildren(...options.map(item=>{const n=el('option','',item.text);n.value=item.id;return n;}));$('scopeSelect').value=scopeId;
 $('stageNav').replaceChildren();options.forEach((item,i)=>{const b=btn(undefined,'stage-button',()=>{scopeId=item.id;focusId=null;selected=null;view=item.id==='all'?'overview':'workflow';$('detailsPanel').hidden=true;navigate(true);});b.setAttribute('aria-current',String(scopeId===item.id));b.append(el('span','stage-index',i?String(i).padStart(2,'0'):'◉'),el('span','',item.text));$('stageNav').append(b);});
 canvas.hidden=view==='trace';$('tracePanel').hidden=view!=='trace';document.querySelector('.zoom-tools').hidden=view==='trace';
 $('scopeSelect').disabled=view==='trace';document.querySelector('.filters').hidden=['sequence','trace'].includes(view);
 $('toggleStages').setAttribute('aria-expanded',String(!$('stagePanel').hidden&&(!matchMedia('(max-width:850px)').matches||$('stagePanel').classList.contains('mobile-open'))));
}
function restoreDetails(){if(detailMode==='basis'){showBasis();return;}if(!selected){$('detailsPanel').hidden=true;detailMode=null;return;}if(nodes.has(selected)||groups.has(selected))select(selected);else if(edges.has(selected)||summaryEdges.has(selected))selectEdge(edges.get(selected)||summaryEdges.get(selected));}
function render(fitView=false){renderText();if(view==='sequence')renderSequence();else if(view==='trace')renderTrace();else drawGraph();if(fitView&&view!=='trace'){zoom=1;applyZoom();canvas.scrollTo(0,0);}if(!$('detailsPanel').hidden)restoreDetails();highlight();}
function saveHash(){const p=new URLSearchParams({view,scope:scopeId});if(selected)p.set('node',selected);if(focusId)p.set('focus',focusId);const hash='#'+p.toString();if(location.hash!==hash)history.pushState(null,'',hash);}
function navigate(fitView=false){saveHash();render(fitView);}
function readHash(){const p=new URLSearchParams(location.hash.slice(1));view=['overview','workflow','evidence','sequence','trace'].includes(p.get('view'))?p.get('view'):'overview';scopeId=scopes.has(p.get('scope'))||groups.has(p.get('scope'))?p.get('scope'):'all';selected=[nodes,groups,edges,summaryEdges].some(map=>map.has(p.get('node')))?p.get('node'):null;focusId=nodes.has(p.get('focus'))?p.get('focus'):null;detailMode=null;}
for(const tab of document.querySelectorAll('.view-tab'))tab.addEventListener('click',()=>{view=tab.dataset.view;focusId=null;tracePage=0;navigate(true);});
document.querySelector('.view-tabs').addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;const tabs=[...document.querySelectorAll('.view-tab')],i=tabs.indexOf(document.activeElement);if(i<0)return;event.preventDefault();const target=tabs[(i+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length];target.focus();target.click();});
$('scopeSelect').addEventListener('change',event=>{scopeId=event.target.value;focusId=null;selected=null;navigate(true);});
$('languageSelect').addEventListener('change',event=>{locale=event.target.value;render();});
$('focusButton').addEventListener('click',()=>{if(nodes.has(selected)){focusId=selected;if(!baseScope().has(selected))scopeId='all';if(['overview','trace','sequence'].includes(view))view='workflow';navigate(true);}});
$('clearFocus').addEventListener('click',()=>{focusId=null;navigate(true);});
$('showStructure').addEventListener('change',()=>render());$('showOrder').addEventListener('change',()=>render());$('showEvidence').addEventListener('change',()=>render());
$('zoomOut').addEventListener('click',()=>setZoom(zoom/1.2));$('zoomIn').addEventListener('click',()=>setZoom(zoom*1.2));$('zoomReset').addEventListener('click',()=>setZoom(1));$('fitButton').addEventListener('click',()=>fit());$('fitAllButton').addEventListener('click',()=>fit(true));
$('basisButton').addEventListener('click',showBasis);$('closeDetails').addEventListener('click',()=>{$('detailsPanel').hidden=true;detailMode=null;});
$('toggleStages').addEventListener('click',()=>{if(matchMedia('(max-width:850px)').matches){$('stagePanel').classList.toggle('mobile-open');$('toggleStages').setAttribute('aria-expanded',String($('stagePanel').classList.contains('mobile-open')));}else{$('stagePanel').hidden=!$('stagePanel').hidden;$('toggleStages').setAttribute('aria-expanded',String(!$('stagePanel').hidden));}});
$('tracePrev').addEventListener('click',()=>{tracePage--;renderTrace();});$('traceNext').addEventListener('click',()=>{tracePage++;renderTrace();});
$('searchInput').addEventListener('input',event=>{const q=event.target.value.trim().toLocaleLowerCase(),root=$('searchResults');root.replaceChildren();root.hidden=!q;if(!q)return;const matches=M.nodes.filter(n=>(label(n.id)+' '+n.id).toLocaleLowerCase().includes(q));for(const n of matches.slice(0,30))root.append(btn(`${n.type} · ${label(n.id)}`,'',()=>{scopeId='all';view='workflow';focusId=n.id;selected=n.id;root.hidden=true;navigate(true);select(n.id);}));if(!matches.length)root.append(el('p','',t('noMatches')));if(matches.length>30)root.append(el('p','',t('searchMore')));});
canvas.addEventListener('wheel',event=>{if(!event.ctrlKey)return;event.preventDefault();const r=canvas.getBoundingClientRect();setZoom(zoom*(event.deltaY>0?.9:1.1),{x:event.clientX-r.left,y:event.clientY-r.top});},{passive:false});
canvas.addEventListener('pointerdown',event=>{if(event.button!==0||event.target.closest('button,.graph-edge,.edge-label'))return;drag={x:event.clientX,y:event.clientY,left:canvas.scrollLeft,top:canvas.scrollTop};canvas.setPointerCapture(event.pointerId);canvas.classList.add('dragging');});
canvas.addEventListener('pointermove',event=>{if(drag){canvas.scrollLeft=drag.left-(event.clientX-drag.x);canvas.scrollTop=drag.top-(event.clientY-drag.y);}});
for(const event of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>{drag=null;canvas.classList.remove('dragging');});
window.addEventListener('hashchange',()=>{readHash();render(true);restoreDetails();});
window.addEventListener('keydown',event=>{if(event.key==='Escape'){if(focusId){focusId=null;navigate(true);}else{$('detailsPanel').hidden=true;detailMode=null;}}});
readHash();render(true);restoreDetails();
