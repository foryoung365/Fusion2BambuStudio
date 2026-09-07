/* Local WebGL renderer: real colored triangles, orbit/pan/zoom and CPU ray picking.
   Display transforms are never written to source geometry. No external packages. */
(function(root){'use strict';
const add=(a,b)=>a.map((v,i)=>v+b[i]), sub=(a,b)=>a.map((v,i)=>v-b[i]), scale=(a,s)=>a.map(v=>v*s);
const dot=(a,b)=>a.reduce((n,v,i)=>n+v*b[i],0), cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const norm=a=>{const d=Math.hypot(...a);return d>1e-12?scale(a,1/d):[0,0,1];};
const identity=()=>[[1,0,0],[0,1,0],[0,0,1]], mul=(a,b)=>a.map(row=>b[0].map((_,c)=>row.reduce((n,v,k)=>n+v*b[k][c],0)));
const rot=(r,p)=>r.map(row=>dot(row,p)), rz=d=>{const a=d*Math.PI/180,c=Math.cos(a),s=Math.sin(a);return [[c,-s,0],[s,c,0],[0,0,1]];};
function bbox(points){const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];for(const p of points)for(let i=0;i<3;i++){lo[i]=Math.min(lo[i],p[i]);hi[i]=Math.max(hi[i],p[i]);}return [lo,hi];}
function modelMatrix(r,t,s=1){return [r[0][0]*s,r[1][0]*s,r[2][0]*s,0,r[0][1]*s,r[1][1]*s,r[2][1]*s,0,r[0][2]*s,r[1][2]*s,r[2][2]*s,0,...t,1];}
function point(m,p){return [0,1,2].map(r=>m[r]*p[0]+m[r+4]*p[1]+m[r+8]*p[2]+m[r+12]);}
function inverseRay(m,origin,direction){const squared=m[0]**2+m[1]**2+m[2]**2;const apply=p=>[0,1,2].map(c=>(m[c*4]*p[0]+m[c*4+1]*p[1]+m[c*4+2]*p[2])/squared);return {origin:apply(sub(origin,m.slice(12,15))),direction:apply(direction)};}
function triangleHit(o,d,a,b,c){const e1=sub(b,a),e2=sub(c,a),h=cross(d,e2),det=dot(e1,h);if(Math.abs(det)<1e-10)return null;const v=sub(o,a),u=dot(v,h)/det;if(u<0||u>1)return null;const q=cross(v,e1),w=dot(d,q)/det;if(w<0||u+w>1)return null;const t=dot(e2,q)/det;return t>1e-7?t:null;}
function boxHit(o,d,box){let low=0,high=Infinity;for(let i=0;i<3;i++){if(Math.abs(d[i])<1e-12){if(o[i]<box[0][i]||o[i]>box[1][i])return false;continue;}let a=(box[0][i]-o[i])/d[i],b=(box[1][i]-o[i])/d[i];if(a>b)[a,b]=[b,a];low=Math.max(low,a);high=Math.min(high,b);if(low>high)return false;}return true;}
function transformedBox(box,m){const points=[];for(const x of [box[0][0],box[1][0]])for(const y of [box[0][1],box[1][1]])for(const z of [box[0][2],box[1][2]])points.push(point(m,[x,y,z]));return bbox(points);}
const rgb=hex=>/^#[0-9a-f]{6}$/i.test(hex||'')?[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255):[.6,.25,.75];

class Viewer{
 constructor(canvas,labels,callbacks={}){
  this.canvas=canvas;this.labels=labels;this.callbacks=callbacks;this.bodies=new Map();this.items=[];this.unitBoxes=new Map();
  this.mode='group';this.selected=null;this.plate=1;this.hover=null;this.drag=null;this.state={units:[],plates:[]};this.sceneKey='';
  this.camera={target:[0,0,0],span:300,yaw:-Math.PI/3,pitch:Math.PI/3};
  const gl=this.gl=canvas.getContext('webgl',{antialias:true,alpha:false,preserveDrawingBuffer:true});
  if(!gl)throw Error('当前内嵌浏览器不支持 WebGL，无法显示三维模型。请使用兼容界面的 Fusion 视图区预览。');
  const vs='attribute vec3 aPosition;attribute vec3 aNormal;uniform mat4 uModel;uniform mat4 uView;varying vec3 vNormal;void main(){vNormal=normalize(mat3(uModel)*aNormal);gl_Position=uView*uModel*vec4(aPosition,1.0);}';
  const fs='precision mediump float;varying vec3 vNormal;uniform vec4 uColor;void main(){float light=0.52+0.48*abs(dot(normalize(vNormal),normalize(vec3(0.35,-0.5,0.8))));gl_FragColor=vec4(uColor.rgb*light,uColor.a);}';
  const shader=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
  this.program=gl.createProgram();gl.attachShader(this.program,shader(gl.VERTEX_SHADER,vs));gl.attachShader(this.program,shader(gl.FRAGMENT_SHADER,fs));gl.linkProgram(this.program);
  if(!gl.getProgramParameter(this.program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(this.program));
  this.locations={position:gl.getAttribLocation(this.program,'aPosition'),normal:gl.getAttribLocation(this.program,'aNormal'),model:gl.getUniformLocation(this.program,'uModel'),view:gl.getUniformLocation(this.program,'uView'),color:gl.getUniformLocation(this.program,'uColor')};
  gl.enable(gl.DEPTH_TEST);gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
  canvas.oncontextmenu=e=>e.preventDefault();canvas.addEventListener('pointerdown',e=>this.down(e));canvas.addEventListener('pointermove',e=>this.move(e));
  canvas.addEventListener('pointerup',e=>this.up(e));canvas.addEventListener('pointercancel',()=>{this.drag=null;this.invalidate();});
  canvas.addEventListener('wheel',e=>{e.preventDefault();this.camera.span=Math.max(2,Math.min(5000,this.camera.span*Math.exp(e.deltaY*.001)));this.invalidate();},{passive:false});
  new ResizeObserver(()=>this.invalidate()).observe(canvas);this.invalidate();
 }
 buffer(data){const g=this.gl,b=g.createBuffer();g.bindBuffer(g.ARRAY_BUFFER,b);g.bufferData(g.ARRAY_BUFFER,new Float32Array(data),g.STATIC_DRAW);return {buffer:b,count:data.length/6};}
 setGeometry(data){for(const b of this.bodies.values())this.gl.deleteBuffer(b.gpu.buffer);this.bodies.clear();
  for(const b of data.bodies){const packed=[];for(const tri of b.triangles){const p=tri.map(i=>b.vertices[i]),n=norm(cross(sub(p[1],p[0]),sub(p[2],p[0])));for(const v of p)packed.push(...v,...n);}this.bodies.set(b.uid,{...b,gpu:this.buffer(packed),box:bbox(b.vertices)});}this.sceneKey='';this.rebuild(true);
 }
 setState(state,options={}){this.state=state;Object.assign(this,options);const key=[this.mode,this.plate,this.mode==='face'?this.selected:'',state.geometryRevision,state.units.map(u=>u.uid).join(',')].join('|');const refit=key!==this.sceneKey;this.sceneKey=key;this.rebuild(refit);}
 rebuild(refit=false){this.items=[];this.unitBoxes.clear();this.hover=null;
  let units=this.state.units||[];if(this.mode==='face')units=units.filter(u=>u.uid===this.selected);if(this.mode==='layout')units=units.filter(u=>u.placement?.plate===this.plate);
  const columns=Math.max(1,Math.ceil(Math.sqrt(units.length)));
  for(let index=0;index<units.length;index++){const u=units[index],r=mul(rz(this.mode==='layout'?(u.placement?.angle||0):0),u.rotation||identity());
   const boxes=u.members.map(m=>this.bodies.get(m.uid)).filter(Boolean).map(b=>bbox(b.vertices.map(p=>rot(r,p))));if(!boxes.length)continue;
   const box=bbox(boxes.flat()),size=sub(box[1],box[0]);let factor=1,t;
   if(this.mode==='group'){factor=88/Math.max(1,...size);t=[(index%columns)*125-factor*(box[0][0]+box[1][0])/2,-Math.floor(index/columns)*125-factor*(box[0][1]+box[1][1])/2,-factor*box[0][2]];}
   else if(this.mode==='layout')t=[u.placement.x-box[0][0],u.placement.y-box[0][1],(u.placement.z||0)-box[0][2]];
   else t=[-(box[0][0]+box[1][0])/2,-(box[0][1]+box[1][1])/2,-box[0][2]];
   const matrix=modelMatrix(r,t,factor),unitBox=bbox(u.members.map(m=>this.bodies.get(m.uid)).filter(Boolean).flatMap(b=>transformedBox(b.box,matrix)));
   this.unitBoxes.set(u.uid,unitBox);for(const member of u.members){const b=this.bodies.get(member.uid);if(b)this.items.push({unit:u.uid,body:b,matrix,color:rgb(member.color),box:transformedBox(b.box,matrix)});}
  }
  this.labels.replaceChildren();for(const [uid,box]of this.unitBoxes){const u=this.state.units.find(u=>u.uid===uid),label=document.createElement('div');label.className='model-label';label.dataset.uid=uid;label.textContent=u.name+(u.members.length>1?` · ${u.members.length} 件整体`:'');label.title=u.name;this.labels.append(label);}
  if(refit)this.fit();this.invalidate();
 }
 axes(){const c=this.camera,dir=[Math.cos(c.pitch)*Math.cos(c.yaw),Math.cos(c.pitch)*Math.sin(c.yaw),Math.sin(c.pitch)],right=norm(cross(scale(dir,-1),[0,0,1])),up=cross(dir,right);return {dir,right,up};}
 view(){const {dir,right,up}=this.axes(),c=this.camera,aspect=this.canvas.clientWidth/Math.max(1,this.canvas.clientHeight),w=c.span*aspect/2,h=c.span/2,z=c.span*8;const rows=[scale(right,1/w),scale(up,1/h),scale(dir,-1/z)];return modelMatrix(rows,rows.map(row=>-dot(row,c.target)));}
 fit(){let boxes=[...this.unitBoxes.values()];if(this.mode==='layout'&&this.state.bed){const b=this.state.bed;boxes.push([[b.origin_x,b.origin_y,0],[b.origin_x+b.width,b.origin_y+b.depth,0]]);}if(!boxes.length)return;const b=bbox(boxes.flat());this.camera.target=scale(add(b[0],b[1]),.5);const {right,up}=this.axes(),aspect=this.canvas.clientWidth/Math.max(1,this.canvas.clientHeight);let halfWidth=0,halfHeight=0;for(const box of boxes)for(const x of [box[0][0],box[1][0]])for(const y of [box[0][1],box[1][1]])for(const z of [box[0][2],box[1][2]]){const p=sub([x,y,z],this.camera.target);halfWidth=Math.max(halfWidth,Math.abs(dot(p,right)));halfHeight=Math.max(halfHeight,Math.abs(dot(p,up)));}this.camera.span=Math.max(20,2*Math.max(halfHeight,halfWidth/aspect)*1.18);this.invalidate();}
 top(){this.camera.pitch=Math.PI/2-.001;this.camera.yaw=-Math.PI/2;this.fit();}
 iso(){this.camera.pitch=Math.PI/3;this.camera.yaw=-Math.PI/3;this.fit();}
 ray(event){const box=this.canvas.getBoundingClientRect(),nx=(event.clientX-box.left)/box.width*2-1,ny=1-(event.clientY-box.top)/box.height*2;const {dir,right,up}=this.axes(),span=this.camera.span;return {origin:add(add(add(this.camera.target,scale(dir,span*4)),scale(right,nx*span*box.width/box.height/2)),scale(up,ny*span/2)),direction:scale(dir,-1)};}
 pick(event,exclude=null){const ray=this.ray(event);let found=null,best=Infinity;for(const item of this.items){if(item.unit===exclude||!boxHit(ray.origin,ray.direction,item.box))continue;const local=inverseRay(item.matrix,ray.origin,ray.direction);for(let i=0;i<item.body.triangles.length;i++){const tri=item.body.triangles[i],p=tri.map(j=>item.body.vertices[j]),t=triangleHit(local.origin,local.direction,...p);if(t!==null&&t<best){best=t;found={unit:item.unit,body:item.body.uid,triangle:i,item,point:add(ray.origin,scale(ray.direction,t))};}}}return found;}
 plane(event,z=0){const r=this.ray(event);if(Math.abs(r.direction[2])<1e-7)return null;return add(r.origin,scale(r.direction,(z-r.origin[2])/r.direction[2]));}
 down(e){if(this.callbacks.isBusy?.())return;e.preventDefault();this.canvas.setPointerCapture(e.pointerId);const hit=this.pick(e);this.drag={start:[e.clientX,e.clientY],last:[e.clientX,e.clientY],hit,button:e.button,shift:e.shiftKey,plane:this.plane(e),moved:false,delta:[0,0,0]};if(hit){this.selected=hit.unit;this.callbacks.select?.(hit.unit);}this.invalidate();}
 move(e){const d=this.drag;if(!d){if(this.mode==='face'){const hit=this.pick(e);if((hit?.body+':'+hit?.triangle)!==(this.hover?.body+':'+this.hover?.triangle)){this.hover=hit;this.makeHighlight();this.invalidate();}}return;}
  const dx=e.clientX-d.last[0],dy=e.clientY-d.last[1];d.last=[e.clientX,e.clientY];if(Math.hypot(e.clientX-d.start[0],e.clientY-d.start[1])>4)d.moved=true;
  if(d.button!==0||!d.hit||this.mode==='face'||d.shift){if(d.shift){const a=this.axes(),s=this.camera.span/Math.max(1,this.canvas.clientHeight);this.camera.target=add(this.camera.target,add(scale(a.right,-dx*s),scale(a.up,dy*s)));}else{this.camera.yaw-=dx*.008;this.camera.pitch=Math.max(-Math.PI/2+.001,Math.min(Math.PI/2-.001,this.camera.pitch+dy*.008));}}
  else{const p=this.plane(e);if(p&&d.plane)d.delta=sub(p,d.plane);if(this.mode==='group'){d.target=this.pick(e,d.hit.unit);this.callbacks.hint?.(d.target?'松开并入「'+this.state.units.find(u=>u.uid===d.target.unit).name+'」 · 保持原装配关系，采用目标方向':'拖到另一模型上以建立整体；松开空白处则不修改');}}
  this.invalidate();
 }
 up(e){const d=this.drag;this.drag=null;if(!d)return;this.callbacks.hint?.('');if(d.button===0&&d.hit){
  if(this.mode==='face'&&!d.moved){const hit=this.pick(e);if(hit)this.callbacks.face?.({unit:hit.unit,body:hit.body,triangle:hit.triangle});}
  else if(this.mode==='group'&&d.moved&&d.target)this.callbacks.group?.(d.hit.unit,d.target.unit);
  else if(this.mode==='layout'&&d.moved){const u=this.state.units.find(u=>u.uid===d.hit.unit),p=u.placement;this.callbacks.move?.({unit:u.uid,plate:p.plate,x:p.x+d.delta[0],y:p.y+d.delta[1],angle:p.angle});}}
  this.invalidate();
 }
 makeHighlight(){if(this.highlight)this.gl.deleteBuffer(this.highlight.buffer);this.highlight=null;if(!this.hover)return;const b=this.hover.item.body,tri=b.triangles[this.hover.triangle],p=tri.map(i=>b.vertices[i]),n=norm(cross(sub(p[1],p[0]),sub(p[2],p[0]))),data=[];
  for(const t of b.triangles){const q=t.map(i=>b.vertices[i]),m=norm(cross(sub(q[1],q[0]),sub(q[2],q[0])));if(dot(n,m)>1-1e-5&&q.every(v=>Math.abs(dot(n,sub(v,p[0])))<.02))for(const v of q)data.push(...v,...n);}this.highlight=this.buffer(data);
 }
 drawBuffer(buffer,matrix,color,mode){const gl=this.gl,l=this.locations;gl.bindBuffer(gl.ARRAY_BUFFER,buffer.buffer);gl.enableVertexAttribArray(l.position);gl.enableVertexAttribArray(l.normal);gl.vertexAttribPointer(l.position,3,gl.FLOAT,false,24,0);gl.vertexAttribPointer(l.normal,3,gl.FLOAT,false,24,12);gl.uniformMatrix4fv(l.model,false,new Float32Array(matrix));gl.uniform4fv(l.color,new Float32Array(color));gl.drawArrays(mode??gl.TRIANGLES,0,buffer.count);}
 lines(points,color){const data=[];for(const p of points)data.push(...p,0,0,1);const b=this.buffer(data);this.drawBuffer(b,modelMatrix(identity(),[0,0,0]),color,this.gl.LINES);this.gl.deleteBuffer(b.buffer);}
 render(){this.pending=false;const gl=this.gl,dpr=Math.min(2,window.devicePixelRatio||1),w=Math.max(1,Math.round(this.canvas.clientWidth*dpr)),h=Math.max(1,Math.round(this.canvas.clientHeight*dpr));if(this.canvas.width!==w||this.canvas.height!==h){this.canvas.width=w;this.canvas.height=h;}gl.viewport(0,0,w,h);gl.clearColor(.925,.95,.95,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.useProgram(this.program);const view=this.view();gl.uniformMatrix4fv(this.locations.view,false,new Float32Array(view));
  if(this.mode==='layout'&&this.state.bed){const b=this.state.bed,x=b.origin_x,y=b.origin_y,pts=[];for(let a=0;a<=b.width;a+=10)pts.push([x+a,y,-.1],[x+a,y+b.depth,-.1]);for(let a=0;a<=b.depth;a+=10)pts.push([x,y+a,-.1],[x+b.width,y+a,-.1]);this.lines(pts,[.65,.77,.73,1]);this.lines([[x,y,0],[x+b.width,y,0],[x+b.width,y,0],[x+b.width,y+b.depth,0],[x+b.width,y+b.depth,0],[x,y+b.depth,0],[x,y+b.depth,0],[x,y,0]],[.2,.45,.4,1]);}
  for(const item of this.items){const m=item.matrix.slice();let alpha=1;if(this.drag?.hit?.unit===item.unit&&this.drag.moved&&this.mode!=='face'&&this.drag.button===0){for(let k=0;k<3;k++)m[12+k]+=this.drag.delta[k];alpha=.5;}this.drawBuffer(item.body.gpu,m,[...item.color,alpha]);}
  const target=this.drag?.target?.unit||this.selected;if(target&&this.unitBoxes.has(target)){const b=this.unitBoxes.get(target),v=[];for(const x of [b[0][0],b[1][0]])for(const y of [b[0][1],b[1][1]])v.push([x,y,b[0][2]],[x,y,b[1][2]]);for(const z of [b[0][2],b[1][2]])v.push([b[0][0],b[0][1],z],[b[1][0],b[0][1],z],[b[1][0],b[0][1],z],[b[1][0],b[1][1],z],[b[1][0],b[1][1],z],[b[0][0],b[1][1],z],[b[0][0],b[1][1],z],[b[0][0],b[0][1],z]);this.lines(v,[1,.65,.1,1]);}
  if(this.hover&&this.highlight&&this.mode==='face'){gl.enable(gl.POLYGON_OFFSET_FILL);gl.polygonOffset(-1,-1);this.drawBuffer(this.highlight,this.hover.item.matrix,[1,.68,.12,.85]);gl.disable(gl.POLYGON_OFFSET_FILL);}
  for(const label of this.labels.children){const box=this.unitBoxes.get(label.dataset.uid);if(!box)continue;const p=point(view,[(box[0][0]+box[1][0])/2,(box[0][1]+box[1][1])/2,box[1][2]+3]);label.style.left=((p[0]+1)*this.canvas.clientWidth/2)+'px';label.style.top=((1-p[1])*this.canvas.clientHeight/2)+'px';label.hidden=this.mode==='face';}
 }
 invalidate(){if(this.pending)return;this.pending=true;requestAnimationFrame(()=>this.render());}
}
const api={Viewer,math:{add,sub,scale,dot,cross,norm,mul,rot,rz,bbox,modelMatrix,point,inverseRay,triangleHit,boxHit,transformedBox}};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.BPS3D=api;
})(typeof window!=='undefined'?window:globalThis);
