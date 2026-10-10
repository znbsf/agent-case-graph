const assert=require('node:assert/strict');
const {test}=require('node:test');
const L=require('../agent_case_graph/web/workbench-layout.js');
const item=(id,width=280,height=130)=>({id,width,height});
const edge=(from,to)=>({from,to});

function nonOverlapping(layout){const rects=[...layout.rects.values()];for(let i=0;i<rects.length;i++)for(let j=i+1;j<rects.length;j++){const a=rects[i],b=rects[j];assert.ok(a.x+a.width<=b.x||b.x+b.width<=a.x||a.y+a.height<=b.y||b.y+b.height<=a.y,'nodes overlap');}}
function clearRoute(route,obstacles){for(let i=1;i<route.points.length;i++){const a=route.points[i-1],b=route.points[i];assert.ok(a[0]===b[0]||a[1]===b[1]);for(const r of obstacles)assert.ok(!L.crosses(a,b,r),'edge crosses a node');}}

test('variable node sizes never overlap',()=>{const nodes=[item('a',280,390),item('b',400,180),item('c'),item('d')],edges=[edge('a','c'),edge('b','c'),edge('c','d')];for(const direction of ['TB','LR'])nonOverlapping(L.layered(nodes,edges,{direction}));});
test('parallel nodes remain on the same layer instead of being wrapped into fake sequence',()=>{const nodes=Array.from({length:9},(_,i)=>item('n'+i)),layout=L.layered(nodes,[]);assert.equal(new Set([...layout.rects.values()].map(r=>r.rank)).size,1);nonOverlapping(layout);});
test('cycles do not remove or reverse any source edge',()=>{const nodes=[item('a'),item('b'),item('c')],edges=[edge('a','b'),edge('b','c'),edge('c','a')],before=JSON.stringify({nodes,edges}),layout=L.layered(nodes,edges);nonOverlapping(layout);assert.equal(JSON.stringify({nodes,edges}),before);for(const [i,e] of edges.entries())clearRoute(L.route(layout.rects.get(e.from),layout.rects.get(e.to),i,[...layout.rects.values()]),[...layout.rects.values()]);});
test('routing avoids intervening cards rather than drawing through them',()=>{const a={x:40,y:70,width:280,height:100},middle={x:420,y:70,width:280,height:240},b={x:800,y:70,width:280,height:120},obstacles=[a,middle,b];const routed=L.route(a,b,0,obstacles);clearRoute(routed,obstacles);assert.deepEqual(routed.points[0],[320,120]);assert.deepEqual(routed.points.at(-1),[800,130]);});
test('self loops remain visible',()=>{const a={x:40,y:40,width:280,height:130},r=L.route(a,a,0,[a]);assert.notDeepEqual(r.points[0],r.points.at(-1));clearRoute(r,[a]);});
test('layout is deterministic and includes disconnected nodes',()=>{const n=[item('a'),item('b'),item('isolated')],e=[edge('a','b')];const a=L.layered(n,e),b=L.layered(n,e);assert.deepEqual(a,b);assert.equal(a.rects.size,3);});
test('empty layout has valid bounds',()=>{const result=L.layered([],[]);assert.ok(result.width>0&&result.height>0);assert.equal(result.rects.size,0);});
