/* Pure geometry: usable by the browser and by Node regression tests.
 * Simplified layered layout, not a reproduction of dot/network simplex.
 * No edge is invented, removed, or reversed by placement.
 */
(function(root){
 'use strict';
 function layered(items,edges,{direction='TB',gap=90,pad=56}={}){
  const ids=new Set(items.map(n=>n.id)), order=new Map(items.map((n,i)=>[n.id,i]));
  const forward=new Map(items.map(n=>[n.id,[]]));
  for(const edge of edges)if(ids.has(edge.from)&&ids.has(edge.to)&&edge.from!==edge.to)forward.get(edge.from).push(edge.to);
  const visited=new Set(), active=new Set(), kept=[];
  function visit(id){visited.add(id);active.add(id);for(const next of forward.get(id)){if(active.has(next))continue;kept.push([id,next]);if(!visited.has(next))visit(next);}active.delete(id);}
  for(const item of items)if(!visited.has(item.id))visit(item.id);
  const incoming=new Map(items.map(n=>[n.id,0])), nexts=new Map(items.map(n=>[n.id,[]])), ranks=new Map(items.map(n=>[n.id,0]));
  for(const [a,b] of kept){incoming.set(b,incoming.get(b)+1);nexts.get(a).push(b);}
  const queue=items.filter(n=>!incoming.get(n.id)).map(n=>n.id);
  for(let i=0;i<queue.length;i++)for(const next of nexts.get(queue[i])){ranks.set(next,Math.max(ranks.get(next),ranks.get(queue[i])+1));incoming.set(next,incoming.get(next)-1);if(!incoming.get(next))queue.push(next);}
  const layers=new Map();for(const n of items){const r=ranks.get(n.id);if(!layers.has(r))layers.set(r,[]);layers.get(r).push(n);}
  // Stable source order is the tie-break. Median sweeps do not mix layers.
  for(let sweep=0;sweep<4;sweep++){
   const scan=[...layers.keys()].sort((a,b)=>sweep%2?b-a:a-b), positions=new Map();
   for(const group of layers.values())group.forEach((n,i)=>positions.set(n.id,i));
   for(const rank of scan)layers.get(rank).sort((a,b)=>{
    function score(n){const neighbors=edges.filter(e=>sweep%2?e.from===n.id&&ranks.get(e.to)>rank:e.to===n.id&&ranks.get(e.from)<rank).map(e=>positions.get(sweep%2?e.to:e.from)).filter(Number.isFinite).sort((x,y)=>x-y);return neighbors.length?neighbors[Math.floor(neighbors.length/2)]:positions.get(n.id);}
    return score(a)-score(b)||order.get(a.id)-order.get(b.id);
   });
  }
  const rects=new Map();let along=pad,maxCross=0;
  for(const rank of [...layers.keys()].sort((a,b)=>a-b)){
   const group=layers.get(rank), depth=Math.max(...group.map(n=>direction==='LR'?n.width:n.height));let cross=pad;
   for(const n of group){rects.set(n.id,{x:direction==='LR'?along:cross,y:direction==='LR'?cross:along,width:n.width,height:n.height,rank});cross+=(direction==='LR'?n.height:n.width)+gap;}
   maxCross=Math.max(maxCross,cross-gap+pad);along+=depth+gap;
  }
  return {rects,width:Math.max(320,direction==='LR'?along-gap+pad:maxCross),height:Math.max(180,direction==='LR'?maxCross:along-gap+pad)};
 }
 function crosses(p,q,r,margin=0){
  const l=r.x-margin,right=r.x+r.width+margin,top=r.y-margin,bottom=r.y+r.height+margin;
  if(p[0]===q[0])return p[0]>l&&p[0]<right&&Math.max(p[1],q[1])>top&&Math.min(p[1],q[1])<bottom;
  return p[1]>top&&p[1]<bottom&&Math.max(p[0],q[0])>l&&Math.min(p[0],q[0])<right;
 }
 function around(start,end,obstacles){
  const xs=[...new Set([start[0],end[0],...obstacles.flatMap(r=>[r.x-16,r.x+r.width+16])])].sort((a,b)=>a-b);
  const ys=[...new Set([start[1],end[1],...obstacles.flatMap(r=>[r.y-16,r.y+r.height+16])])].sort((a,b)=>a-b);
  const sx=xs.indexOf(start[0]),sy=ys.indexOf(start[1]),tx=xs.indexOf(end[0]),ty=ys.indexOf(end[1]);
  const heap=[],dist=new Map(),previous=new Map(),states=new Map(),key=(x,y,d)=>`${x}:${y}:${d}`;
  function push(n){heap.push(n);let i=heap.length-1;while(i){const p=(i-1)>>1;if(heap[p].score<=n.score)break;heap[i]=heap[p];i=p;}heap[i]=n;}
  function pop(){const first=heap[0],last=heap.pop();if(heap.length){let i=0;while(i*2+1<heap.length){let c=i*2+1;if(c+1<heap.length&&heap[c+1].score<heap[c].score)c++;if(heap[c].score>=last.score)break;heap[i]=heap[c];i=c;}heap[i]=last;}return first;}
  const initial={x:sx,y:sy,d:0,cost:0,score:0,key:key(sx,sy,0)};dist.set(initial.key,0);states.set(initial.key,initial);push(initial);
  while(heap.length){const state=pop();if(state.cost!==dist.get(state.key))continue;
   if(state.x===tx&&state.y===ty){const result=[];let k=state.key;while(k){const s=states.get(k);result.unshift([xs[s.x],ys[s.y]]);k=previous.get(k);}return result;}
   for(const [dx,dy] of [[1,0],[-1,0],[0,1],[0,-1]]){const x=state.x+dx,y=state.y+dy;if(x<0||y<0||x>=xs.length||y>=ys.length)continue;
    const p=[xs[state.x],ys[state.y]],q=[xs[x],ys[y]];if(obstacles.some(r=>crosses(p,q,r,5)))continue;
    const d=dx?1:2,cost=state.cost+Math.abs(p[0]-q[0])+Math.abs(p[1]-q[1])+(state.d&&state.d!==d?20:0),k=key(x,y,d);
    if(dist.has(k)&&dist.get(k)<=cost)continue;const next={x,y,d,cost,key:k,score:cost+Math.abs(q[0]-end[0])+Math.abs(q[1]-end[1])};dist.set(k,cost);previous.set(k,state.key);states.set(k,next);push(next);
   }
  }
  throw new Error('No obstacle-free route between node ports');
 }
 function route(a,b,index=0,obstacles=[]){
  const proposed=quickRoute(a,b,index);
  if(!obstacles.some(r=>proposed.points.slice(1).some((p,i)=>crosses(proposed.points[i],p,r))))return proposed;
  const horizontal=b.x>=a.x+a.width+40;
  const borderA=horizontal?[a.x+a.width,a.y+a.height/2]:[a.x+a.width/2,a.y+a.height];
  const borderB=horizontal?[b.x,b.y+b.height/2]:[b.x+b.width/2,b.y];
  const start=horizontal?[borderA[0]+16,borderA[1]]:[borderA[0],borderA[1]+16];
  const end=horizontal?[borderB[0]-16,borderB[1]]:[borderB[0],borderB[1]-16];
  const raw=[borderA,...around(start,end,obstacles),borderB],points=[];
  for(const p of raw){const a=points.at(-2),b=points.at(-1);if(b&&b[0]===p[0]&&b[1]===p[1])continue;if(a&&((a[0]===b[0]&&b[0]===p[0])||(a[1]===b[1]&&b[1]===p[1])))points.pop();points.push(p);}
  let longest=-1,label=[0,0];for(let i=1;i<points.length;i++){const p=points[i-1],q=points[i],length=Math.abs(p[0]-q[0])+Math.abs(p[1]-q[1]);if(length>longest){longest=length;label=[(p[0]+q[0])/2+5,(p[1]+q[1])/2];}}
  return {points,label};
 }
 function quickRoute(a,b,index=0){
  const offset=18+(index%5)*9;
  if(a===b)return {points:[[a.x+a.width,a.y+a.height/3],[a.x+a.width+40,a.y+a.height/3],[a.x+a.width+40,a.y+a.height*2/3],[a.x+a.width,a.y+a.height*2/3]],label:[a.x+a.width+45,a.y+a.height/2]};
  // Elbow lanes outside cards, with back/cross links routed past the graph.
  if(b.x>=a.x+a.width+40){const x=(a.x+a.width+b.x)/2;return {points:[[a.x+a.width,a.y+a.height/2],[x,a.y+a.height/2],[x,b.y+b.height/2],[b.x,b.y+b.height/2]],label:[x,(a.y+a.height/2+b.y+b.height/2)/2]};}
  if(b.y>=a.y+a.height+40&&Math.abs(b.x-a.x)<a.width/2){const y=(a.y+a.height+b.y)/2;return {points:[[a.x+a.width/2,a.y+a.height],[a.x+a.width/2,y],[b.x+b.width/2,y],[b.x+b.width/2,b.y]],label:[(a.x+a.width/2+b.x+b.width/2)/2+8,y]};}
  const x=Math.max(a.x+a.width,b.x+b.width)+offset;
  return {points:[[a.x+a.width,a.y+a.height/2],[x,a.y+a.height/2],[x,b.y+b.height/2],[b.x+b.width,b.y+b.height/2]],label:[x+5,(a.y+b.y+a.height/2+b.height/2)/2]};
 }
 function path(points){return points.map((p,i)=>(i?'L':'M')+p.join(' ')).join(' ');}
 const api={layered,route,path,crosses};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.WorkbenchLayout=api;
})(typeof globalThis!=='undefined'?globalThis:this);
