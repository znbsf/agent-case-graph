/* Source-model and pure geometry checks, NOT a browser or readability test.
 * Card heights below are deliberately synthetic stress inputs, not font metrics.
 * Usage: node scripts/check_workbench_geometry.cjs path/to/workbench-model.json
 */
'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict');
const L=require('../agent_case_graph/web/workbench-layout.js');
const model=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const nodeIds=model.nodes.map(n=>n.id),edgeIds=model.edges.map(e=>e.id);
assert.deepEqual(model.groups.flatMap(g=>g.member_ids).sort(),[...nodeIds].sort());
assert.deepEqual([...model.groups.flatMap(g=>g.internal_edge_ids),...model.group_edges.flatMap(e=>e.source_edge_ids)].sort(),[...edgeIds].sort());
const edges=new Map(model.edges.map(e=>[e.id,e]));
for(const e of model.group_edges)for(const id of e.source_edge_ids){const original=edges.get(id);assert.equal(e.from,model.node_owner[original.from]);assert.equal(e.to,model.node_owner[original.to]);assert.equal(e.type,original.type);}
const checks=[];
function check(name,items,links,options){
 const before=JSON.stringify(links),start=performance.now(),layout=L.layered(items,links,options),rects=[...layout.rects.values()];
 for(let i=0;i<rects.length;i++)for(let j=i+1;j<rects.length;j++){const a=rects[i],b=rects[j];assert.ok(a.x+a.width<=b.x||b.x+b.width<=a.x||a.y+a.height<=b.y||b.y+b.height<=a.y,`${name}: overlap`);}
 let routed=0;
 for(const [i,e] of links.entries()){
  const route=L.route(layout.rects.get(e.from),layout.rects.get(e.to),i,rects);
  assert.ok(route.points.flat().every(Number.isFinite));
  for(let p=1;p<route.points.length;p++)for(const r of rects)assert.ok(!L.crosses(route.points[p-1],route.points[p],r),`${name}: ${e.id} crosses a card`);
  routed++;
 }
 assert.equal(JSON.stringify(links),before);
 checks.push({name,nodes:items.length,routed,width:layout.width,height:layout.height,elapsed_ms:Math.round(performance.now()-start)});
}
const dimensions=(items,width)=>items.map((n,i)=>({id:n.id,width,height:90+(i%5)*47}));
check('summary with every relation',dimensions(model.groups,400),model.group_edges,{gap:84});
for(const scope of model.scopes){const ids=new Set(scope.related_node_ids);check(scope.id,dimensions(model.nodes.filter(n=>ids.has(n.id)),280),model.edges.filter(e=>ids.has(e.from)&&ids.has(e.to)),{direction:'TB',gap:76});}
console.log(JSON.stringify({passed:true,basis:'Canonical coverage and synthetic card dimensions; not browser QA or measured readability',source_ledger:model.source_ledger,node_count:nodeIds.length,edge_count:edgeIds.length,trace_count:model.trace.length,checks},null,2));
