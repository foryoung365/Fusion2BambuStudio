'use strict';
let state={units:[],plates:[],config:{},errors:[],warnings:[]},profiles={},selected=null,currentPlate=1,mode='group',busy=false,viewer=null,loadedRevision=-1,transferConfirm=null,orientationDialog=null,arrangementDialog=null;
const $=id=>document.getElementById(id),closedPlates=new Set(),geometry=new Map(),thumbs=new Map();
const demo=new URLSearchParams(location.search).get('demo')==='1';
const MIME='application/x-bambu-plate-studio-unit';
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function message(text,error=false){$('message').textContent=text;$('message').className=text?(error?'error':'info'):'';}
function hint(text){$('dragHint').textContent=text;$('dragHint').style.display=text?'block':'none';}
function setBusy(value){busy=value;document.querySelectorAll('button').forEach(b=>b.disabled=value);if(!value){$('undo').disabled=!state.canUndo;$('redo').disabled=!state.canRedo;}syncNavigationLimits();syncOrientationControls();syncPlacementControls();orientationDialog?.refreshButtons(value);arrangementDialog?.refreshButtons(value);}
async function rpc(action,data={}){
 const payload={action,data};let response;
 if(demo){const r=await fetch('/api',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});response=await r.json();}
 else{if(!window.adsk?.fusionSendData)throw Error('Fusion 通信桥尚未就绪。');response=JSON.parse(await Promise.resolve(adsk.fusionSendData('request',JSON.stringify(payload))));}
 if(!response.ok){const error=Error(response.error);error.confirmation=response.confirmation;throw error;}return response.state;
}
async function request(action,data={}){
  if(busy)return;setBusy(true);
  const slow=['orientation_preview','arrangement_preview'].includes(action),started=Date.now();
  const ticker=slow?setInterval(()=>message(`Bambu 正在计算${action==='orientation_preview'?'朝向':'摆位'}，已等待 ${Math.floor((Date.now()-started)/1000)} 秒…`),1000):null;
  try{if(slow)await new Promise(resolve=>setTimeout(resolve,20));
   let next=await rpc(action,slow?{...data,background:true}:data),previewKind=next.pendingPreview?.kind;
   while(next.pendingPreview){await new Promise(resolve=>setTimeout(resolve,500));next=await rpc('preview_status',{token:next.pendingPreview.token});}
   if(action==='transfer_plate'){selected=data.unit;currentPlate=data.plate;closedPlates.delete(currentPlate);}update(next);if(action==='transfer_plate'){setMode('layout');renderTree();document.querySelector('.plate-title[data-plate="'+currentPlate+'"]')?.scrollIntoView({block:'nearest'});}message((next.notices||[]).join('\n'));
  if(next.units.length&&loadedRevision!==next.geometryRevision){hint('正在载入三维模型…');const data=await rpc('viewport_data');geometry.clear();for(const b of data.bodies)geometry.set(b.uid,b);loadedRevision=data.revision;thumbs.clear();viewer?.setGeometry(data);renderTree();hint('');if(!demo&&window.adsk?.fusionSendData)requestAnimationFrame(()=>adsk.fusionSendData('view_ready',JSON.stringify({webgl:!!viewer,units:state.units.length,bodies:geometry.size,drawnBodies:viewer?.items.length||0,width:$('modelCanvas').clientWidth,height:$('modelCanvas').clientHeight})));}
   if((action==='orientation_preview'||previewKind==='orientation_preview')&&next.orientationPreview){const p=next.orientationPreview;orientationDialog.open(p,state.units.find(u=>u.uid===p.unit),geometry,state,currentPlate);}
   if((action==='arrangement_preview'||previewKind==='arrangement_preview')&&next.arrangementPreview)arrangementDialog.open(next.arrangementPreview,state,geometry,currentPlate);
  return next;
  }catch(e){if(e.confirmation?.code==='mixed_plate_confirmation'&&['transfer_plate','move'].includes(action)&&data.confirmMixed!==true){message('');transferConfirm.open({action,data},e.confirmation.message);}else message(e.message,true);hint('');}finally{if(ticker)clearInterval(ticker);setBusy(false);if(!demo&&['orientation_apply','orientation_cancel','arrangement_apply','arrangement_cancel'].includes(action)&&window.adsk?.fusionSendData){try{Promise.resolve(adsk.fusionSendData('palette_refresh','')).catch(e=>message('窗口刷新失败：'+e.message,true));}catch(e){message('窗口刷新失败：'+e.message,true);}}}
}
function selectOptions(id,options,value){const el=$(id);el.replaceChildren();let found=false;for(const o of options){const p=node('option',o.name);p.value=o.key;p.selected=o.key===value||o.name===value;found||=p.selected;el.append(p);}if(value&&!found){const p=node('option',value+'（请选择兼容预设）');p.value=value;p.selected=true;el.prepend(p);}}
function setMode(value){mode=value;document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));$('modeTitle').textContent={group:'拖动模型到另一模型上，建立整体',face:'旋转查看；悬停高亮平面，点击后贴板',layout:'彩色实体排盘 · 可拖动调整位置'}[mode];$('viewHelp').textContent={group:'左键拖到另一模型上自动分组；原装配关系不变。右键旋转，Shift＋拖动平移，滚轮缩放。',face:'左键拖动或右键拖动旋转查看，滚轮缩放；单击平面后朝下贴板。视角旋转本身不会修改模型方向。',layout:'拖动模型调整盘内位置；拖动左侧树节点到目标盘换盘。整组移动，不拆散内部实体。'}[mode];syncViewer();}
function choose(uid){selected=uid;const u=selectedUnit();if(mode==='layout'&&u?.placement)currentPlate=u.placement.plate;renderTree();renderInspector();syncViewer();syncPlacementControls();}
function switchPlate(index){if(busy||!state.plates.some(p=>p.index===index))return;currentPlate=index;if(selectedUnit()?.placement?.plate!==index)selected=state.units.find(u=>u.placement?.plate===index)?.uid||null;setMode('layout');renderInspector();syncPlacementControls();}
function togglePlate(index){if(closedPlates.has(index))closedPlates.delete(index);else closedPlates.add(index);renderTree();document.querySelector('.plate-title[data-plate="'+index+'"] .plate-toggle')?.focus();}
function syncNavigationLimits(){const navigation=BPSPlateNavigation.state(state.plates,currentPlate);$('previousPlate').disabled=busy||navigation.previous===null;$('nextPlate').disabled=busy||navigation.next===null;$('previewPlate').disabled=busy||!navigation.total;}
function syncViewer(){
 viewer?.setState(state,{selected,mode,plate:currentPlate});
 $('activePlate').textContent=mode==='layout'&&state.plates.length?'第 '+currentPlate+' 盘':'';
 $('plateNavigation').hidden=mode!=='layout';
 selectOptions('previewPlate',state.plates.map(p=>({key:String(p.index),name:'第 '+p.index+' 盘 · '+state.units.filter(u=>u.placement?.plate===p.index).length+' 个单元'})),state.plates.length?String(currentPlate):'');
 $('plateTotal').textContent='共 '+state.plates.length+' 盘';syncNavigationLimits();
 for(const title of document.querySelectorAll('.plate-title')){
  const active=mode==='layout'&&Number(title.dataset.plate)===currentPlate;
  title.classList.toggle('active',active);title.setAttribute('aria-selected',String(active));
 }
 for(const row of document.querySelectorAll('.unit-row'))row.classList.toggle('selected',row.dataset.unit===selected);
 const visible=mode==='layout'?state.units.some(u=>u.placement?.plate===currentPlate):mode==='face'?!!selected:state.units.length>0;
 $('emptyView').hidden=visible;
 $('emptyView').textContent=mode==='layout'&&state.plates.length?'当前打印盘为空，可从左侧树拖入模型。':mode==='face'?'请先选择一个模型。':'读取设计后，在这里查看和操作真实模型';
}
function update(next){state=next;if(next.profiles)profiles=next.profiles;if(!state.units.some(u=>u.uid===selected))selected=state.units[0]?.uid||null;if(!state.plates.some(p=>p.index===currentPlate))currentPlate=state.plates[0]?.index||1;
 $('summary').textContent=(state.document||'尚未读取设计')+' · '+state.units.reduce((n,u)=>n+u.members.length,0)+' 个实体 · '+state.units.length+' 个打印单元 · '+state.plates.length+' 盘';
 for(const [id,list]of [['printer','machines'],['process','processes'],['filament','filaments']])selectOptions(id,profiles[list]||[],state.config[id]);
 selectOptions('bed',Object.entries(profiles.beds||{}).map(([key,name])=>({key,name})),state.config.bed);
 for(const id of ['gap','margin','refinement','nozzle'])$(id).value=state.config[id]??'';
 for(const id of ['allowZRotation','allowMixedPlates','includeHidden','enableSupport'])$(id).checked=!!state.config[id];
  $('bambuExe').value=state.exe||'';renderColors();renderTree();renderInspector();syncViewer();syncPlacementControls();
 $('footer').textContent=state.lastExport?'已导出：'+state.lastExport.path:'原设计不修改 · 分组和方向编辑可撤销';
 $('connection').textContent=demo?'离线交互测试 · 非 Fusion 实测':'Fusion 插件';
 $('undo').disabled=!state.canUndo;$('redo').disabled=!state.canRedo;
}
function renderColors(){const root=$('colorTable');root.replaceChildren();const colors=[...new Set(state.units.flatMap(u=>u.members.map(m=>m.color)))].sort();for(const color of colors){const row=node('div',undefined,'color-row'),label=node('div'),sw=node('span',undefined,'swatch');sw.style.background=color;label.append(sw,document.createTextNode(' '+(color||'未识别')));const select=node('select'),value=state.colorProfiles?.[color]||state.config.filament;let found=false;for(const p of profiles.filaments||[]){const option=node('option',p.name);option.value=p.key;option.selected=p.key===value||p.name===value;found||=option.selected;select.append(option);}if(!found){const o=node('option','请选择兼容耗材');o.value='';o.selected=true;select.prepend(o);}select.onchange=()=>select.value&&request('color_profile',{color,profile:select.value});row.append(label,select);root.append(row);}}
function dragUnit(e,uid){if(busy){e.preventDefault();return;}e.dataTransfer.setData(MIME,uid);e.dataTransfer.effectAllowed='move';}
function dragged(e){return e.dataTransfer.getData(MIME);}
function installDrop(element,onDrop){element.addEventListener('dragover',e=>{if([...e.dataTransfer.types].includes(MIME)){e.preventDefault();e.stopPropagation();element.classList.add('drop-target');}});element.addEventListener('dragleave',()=>element.classList.remove('drop-target'));element.addEventListener('drop',e=>{element.classList.remove('drop-target');const uid=dragged(e);if(!uid)return;e.preventDefault();e.stopPropagation();onDrop(uid);});}
function groupDrop(source,target){selected=target;request('group_drop',{source,target});}
function treeDrop(source,target){const intent=resolveTreeDrop(source,target,state.units);if(intent.action)request(intent.action,intent.data);else message(intent.message);}
// Use pointer capture for embedded-browser tree dragging; native HTML drag/drop
// is unreliable in some Fusion browser engines. Keep the stable tree as owner.
let treeDrag=null;
function treePointerDown(e){const row=e.target.closest('.unit-row');if(busy||e.button!==0||!row)return;e.preventDefault();const tree=$('plateTree');tree.setPointerCapture(e.pointerId);treeDrag={uid:row.dataset.unit,x:e.clientX,y:e.clientY,moved:false,target:null};}
function clearTreeTarget(){document.querySelectorAll('#plateTree .drop-target').forEach(e=>e.classList.remove('drop-target'));}
function treePointerMove(e){if(!treeDrag)return;const d=treeDrag;if(Math.hypot(e.clientX-d.x,e.clientY-d.y)<5&&!d.moved)return;d.moved=true;clearTreeTarget();const tree=$('plateTree'),r=tree.getBoundingClientRect();if(e.clientY<r.top+32)tree.scrollTop-=18;if(e.clientY>r.bottom-32)tree.scrollTop+=18;const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('.plate-title,.unit-row');d.target=target&&tree.contains(target)?target:null;if(d.target){d.target.classList.add('drop-target');const intent=resolveTreeDrop(d.uid,d.target.dataset,state.units);hint(intent.action?'松开后将整个打印单元移至第 '+intent.data.plate+' 盘；不会合成整体':intent.message);}else hint('请拖到打印盘标题或模型节点上');}
function treePointerUp(){const d=treeDrag;treeDrag=null;clearTreeTarget();hint('');if(!d)return;if(!d.moved){choose(d.uid);return;}if(d.target)treeDrop(d.uid,d.target.dataset);}
function thumbnail(canvas,u){const key=u.uid+JSON.stringify(u.rotation)+u.members.map(m=>m.uid+m.color).join('');if(thumbs.has(key)){const image=thumbs.get(key);canvas.getContext('2d').drawImage(image,0,0);return;}
 canvas.width=86;canvas.height=78;const ctx=canvas.getContext('2d'),M=BPS3D.math,triangles=[];
 const project=p=>[(p[0]-p[1])*.71,(p[0]+p[1])*.32-p[2]*.85];
 for(const member of u.members){const b=geometry.get(member.uid);if(!b)continue;for(const triangle of b.triangles){const p=triangle.map(j=>M.rot(u.rotation,b.vertices[j])),normal=M.norm(M.cross(M.sub(p[1],p[0]),M.sub(p[2],p[0]))),light=.52+.48*Math.abs(M.dot(normal,M.norm([.35,-.5,.8]))),hex=/^#[0-9a-f]{6}$/i.test(member.color||'')?member.color:'#808080',color='#'+[1,3,5].map(i=>Math.round(parseInt(hex.slice(i,i+2),16)*light).toString(16).padStart(2,'0')).join('');triangles.push({p:p.map(project),depth:p.reduce((n,v)=>n+v[0]+v[1]+v[2],0),color});}}
 if(!triangles.length)return;const lo=[Infinity,Infinity],hi=[-Infinity,-Infinity];for(const t of triangles)for(const p of t.p)for(let k=0;k<2;k++){lo[k]=Math.min(lo[k],p[k]);hi[k]=Math.max(hi[k],p[k]);}const s=Math.min(76/Math.max(1,hi[0]-lo[0]),68/Math.max(1,hi[1]-lo[1]));ctx.clearRect(0,0,86,78);triangles.sort((a,b)=>a.depth-b.depth);for(const tri of triangles){ctx.beginPath();tri.p.forEach((p,i)=>{const x=43+(p[0]-(lo[0]+hi[0])/2)*s,y=39+(p[1]-(lo[1]+hi[1])/2)*s;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.closePath();ctx.fillStyle=tri.color;ctx.fill();ctx.strokeStyle=tri.color;ctx.lineWidth=.3;ctx.stroke();}const copy=document.createElement('canvas');copy.width=86;copy.height=78;copy.getContext('2d').drawImage(canvas,0,0);thumbs.set(key,copy);
}
function unitRow(u){const wrapper=node('div'),row=node('div',undefined,'unit-row'+(u.uid===selected?' selected':''));row.setAttribute('role','treeitem');row.tabIndex=0;row.draggable=true;row.dataset.unit=u.uid;row.ondragstart=e=>dragUnit(e,u.uid);row.onclick=()=>choose(u.uid);row.onkeydown=e=>{if(e.key==='Enter')choose(u.uid);};
 const image=node('canvas',undefined,'mini-model');image.width=86;image.height=78;thumbnail(image,u);const details=node('div');details.append(node('div',u.name,'name'),node('div',u.members.length>1?'🔒 '+u.members.length+' 件整体':'独立打印单元','row-meta'));row.append(image,details);installDrop(row,source=>treeDrop(source,{unit:u.uid}));wrapper.append(row);
 if(u.members.length>1)for(const member of u.members){const c=node('div',undefined,'group-child'),sw=node('span',undefined,'swatch');sw.style.background=member.color;c.title='组内实体被锁定，请拖动所属整体；解除整体后才能单独移动。';c.append(sw,node('span',member.name));wrapper.append(c);}return wrapper;}
function renderTree(){const root=$('plateTree');root.replaceChildren();const unplaced=state.units.filter(u=>!u.placement);const branches=[...(unplaced.length?[{index:0,name:'未分盘',units:unplaced}]:[]),...state.plates.map(p=>({...p,units:state.units.filter(u=>u.placement?.plate===p.index)}))];for(const plate of branches){const branch=node('section',undefined,'plate-node'),title=node('div',undefined,'plate-title'+(plate.index===currentPlate&&mode==='layout'?' active':''));title.setAttribute('role','treeitem');title.tabIndex=0;title.dataset.plate=plate.index;title.title=plate.index?'点击切换打印盘预览，不展开或收起列表':'';const arrow=node('button',closedPlates.has(plate.index)?'▸':'▾','plate-toggle'),label=plate.index?'第 '+plate.index+' 盘':'未分盘';arrow.setAttribute('aria-label',(closedPlates.has(plate.index)?'展开':'收起')+label);arrow.setAttribute('aria-expanded',String(!closedPlates.has(plate.index)));title.append(arrow,node('strong',label),node('span',plate.units.length+' 单元','plate-count'));BPSPlateNavigation.bindHeader(title,arrow,plate.index,switchPlate,togglePlate);
 if(plate.index){installDrop(title,uid=>treeDrop(uid,{plate:plate.index}));if(!plate.units.length){const del=node('button','×','plate-delete');del.title='删除空盘';del.onclick=e=>{e.stopPropagation();request('delete_plate',{plate:plate.index});};title.append(del);}}
 branch.append(title);if(!closedPlates.has(plate.index))for(const u of plate.units)branch.append(unitRow(u));root.append(branch);}if(!branches.length)root.append(node('p','读取模型后显示打印盘与实体树。','muted'));}
function selectedUnit(){return state.units.find(u=>u.uid===selected);}
function syncOrientationControls(){const u=selectedUnit(),placed=state.units.filter(x=>x.placement),current=placed.filter(x=>x.placement.plate===currentPlate);if(!busy)$('orientationLocked').checked=!!u?.orientationLocked;$('orientationLocked').disabled=busy||!u;$('autoOrient').disabled=busy||!u||!!u.orientationLocked;$('autoOrientCurrent').disabled=busy||!current.some(x=>!x.orientationLocked);$('autoOrientAll').disabled=busy||!placed.some(x=>!x.orientationLocked);$('autoOrient').title=u?.orientationLocked?'取消朝向锁定后才能生成建议。':'为所选打印单元生成朝向预览。';}
function syncPlacementControls(){const ready=!!state.plates.length&&state.units.every(u=>!!u.placement),current=state.units.some(u=>u.placement?.plate===currentPlate);$('autoPlaceAll').disabled=busy||!ready;$('autoPlaceCurrent').disabled=busy||!ready||!current;}
function renderInspector(){const u=selectedUnit();$('selectedTitle').textContent=u?.name||'尚未选择';$('groupBadge').textContent=u?.members.length>1?'整体锁定':'';$('unitDetails').textContent=u?u.direction+'\n'+u.size.map(v=>v.toFixed(1)).join(' × ')+' mm':'';$('unitName').value=u?.name||'';$('direction').value='keep';
 selectOptions('placementPlate',state.plates.map(p=>({key:String(p.index),name:'第 '+p.index+' 盘'})),String(u?.placement?.plate||currentPlate));
 for(const [id,key]of [['placementX','x'],['placementY','y'],['placementAngle','angle']])$(id).value=u?.placement?.[key]??'';
 const root=$('memberColors');root.replaceChildren();for(const m of u?.members||[]){const box=node('div',undefined,'member-color');box.append(node('label',m.name+(m.mixedFaces?'（需明确整件颜色）':'')));const input=node('input');input.type='color';input.value=m.color||'#808080';const apply=node('button','应用打印颜色');apply.onclick=()=>request('body_color',{body:m.uid,color:input.value});box.append(input,apply);root.append(box);}
 const messages=$('validation');messages.replaceChildren();for(const error of state.errors||[])messages.append(node('p',error,'validation-error'));for(const warning of state.warnings||[])messages.append(node('p',warning,'validation-warning'));
 syncOrientationControls();
}
function withUnit(fn){const u=selectedUnit();if(!u){message('请先选择模型。',true);return;}fn(u);}
$('settingsToggle').onclick=()=>$('settingsDrawer').hidden=false;$('settingsClose').onclick=()=>$('settingsDrawer').hidden=true;
document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
$('scan').onclick=()=>request('scan');$('saveRules').onclick=()=>request('save_rules');
$('undo').onclick=()=>request('undo');$('redo').onclick=()=>request('redo');
$('fit').onclick=()=>viewer?.fit();$('iso').onclick=()=>viewer?.iso();$('top').onclick=()=>viewer?.top();
$('previewPlate').onchange=()=>switchPlate(Number($('previewPlate').value));
$('previousPlate').onclick=()=>switchPlate(BPSPlateNavigation.state(state.plates,currentPlate).previous);
$('nextPlate').onclick=()=>switchPlate(BPSPlateNavigation.state(state.plates,currentPlate).next);
$('focusUnit').onclick=()=>withUnit(()=>setMode('face'));$('highlight').onclick=()=>withUnit(u=>request('highlight',{unit:u.uid}));
$('renameUnit').onclick=()=>withUnit(u=>request('rename_unit',{unit:u.uid,name:$('unitName').value}));
$('ungroup').onclick=()=>withUnit(u=>request('ungroup',{unit:u.uid}));
$('setDirection').onclick=()=>withUnit(u=>request('direction',{unit:u.uid,mode:$('direction').value}));
$('pickFace').onclick=()=>withUnit(u=>request('pick_face',{unit:u.uid}));
function previewOrientation(scope){message('正在调用 Bambu Studio 生成朝向建议，请稍候；当前方向不会改变。');if(scope==='unit')withUnit(u=>request('orientation_preview',{scope,unit:u.uid}));else request('orientation_preview',{scope,plate:currentPlate});}
$('autoOrient').onclick=()=>previewOrientation('unit');
$('autoOrientCurrent').onclick=()=>previewOrientation('current');
$('autoOrientAll').onclick=()=>previewOrientation('all');
$('orientationLocked').onchange=()=>withUnit(u=>request('orientation_lock',{unit:u.uid,locked:$('orientationLocked').checked}));
$('arrange').onclick=async()=>{const result=await request('arrange');if(result){closedPlates.clear();setMode('layout');renderTree();}};
function previewPlacement(scope){message('正在调用 Bambu Studio 自动摆位；确认前不会改变当前盘位。');request('arrangement_preview',{scope,plate:currentPlate});}
$('autoPlaceCurrent').onclick=()=>previewPlacement('current');
$('autoPlaceAll').onclick=()=>previewPlacement('all');
$('addPlate').onclick=()=>request('add_plate');$('expandTree').onclick=()=>{closedPlates.clear();renderTree();};
$('transferUnit').onclick=()=>withUnit(u=>request('transfer_plate',{unit:u.uid,plate:Number($('placementPlate').value)}));
$('applyPlacement').onclick=()=>withUnit(u=>request('move',{unit:u.uid,plate:Number($('placementPlate').value),x:Number($('placementX').value),y:Number($('placementY').value),angle:Number($('placementAngle').value)}));
$('export').onclick=()=>{if(state.errors?.length){message('请先处理排盘错误。',true);return;}request('export');};
$('printer').onchange=()=>{const m=profiles.machines.find(m=>m.key===$('printer').value);request('config',{printer:m.key,nozzle:m.nozzle});};
$('nozzle').onchange=()=>{const current=profiles.machines?.find(m=>m.key===state.config.printer||m.name===state.config.printer),target=profiles.machines?.find(m=>m.model===current?.model&&m.nozzle===$('nozzle').value);if(target)request('config',{printer:target.key,nozzle:target.nozzle});else message('该打印机没有对应喷嘴预设。',true);};
for(const id of ['bed','process','filament','refinement'])$(id).onchange=()=>request('config',{[id]:$(id).value});
for(const id of ['gap','margin'])$(id).onchange=()=>request('config',{[id]:Number($(id).value)});
for(const id of ['allowZRotation','allowMixedPlates','includeHidden','enableSupport'])$(id).onchange=()=>request('config',{[id]:$(id).checked});
$('loadInstallation').onclick=()=>request('installation',{executable:$('bambuExe').value});$('loadProfiles').onclick=()=>request('profile_root',{path:$('profileRoot').value});
$('resetUnits').onclick=()=>{if(confirm('确认重建所有分组和方向规则？原设计不会修改。'))request('reset_units');};
window.addEventListener('keydown',e=>{if($('transferConfirm').open||$('orientationDialog').open||$('arrangementDialog').open||e.target.closest('input,select,textarea'))return;if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();request(e.shiftKey?'redo':'undo');}});
window.fusionJavaScriptHandler={handle(action,data){try{if(action==='state'){update(JSON.parse(data));if(!busy&&state.units.length&&loadedRevision!==state.geometryRevision)request('bootstrap');return 'OK';}if(action==='inspect')return JSON.stringify({title:document.title,summary:$('summary').textContent,webgl:!!viewer,units:state.units.length,plates:state.plates.length,geometryBodies:geometry.size,mode,selected});if(action==='capture_view'){if(!viewer||busy||!geometry.size)throw Error('三维视图尚未准备好。');const options=JSON.parse(data||'{}');if(options.unit&&state.units.some(u=>u.uid===options.unit))selected=options.unit;if(options.plate&&state.plates.some(p=>p.index===options.plate))currentPlate=options.plate;if(['group','face','layout'].includes(options.mode))setMode(options.mode);viewer.fit();viewer.render();return JSON.stringify({mode,selected,plate:currentPlate,bodies:geometry.size,width:$('modelCanvas').width,height:$('modelCanvas').height,image:$('modelCanvas').toDataURL('image/png')});}return 'UNSUPPORTED';}catch(e){return JSON.stringify({error:e.message});}}};
window.addEventListener('DOMContentLoaded',()=>{
 transferConfirm=new TransferConfirmation($('transferConfirm'),$('transferConfirmText'),$('transferAccept'),$('transferCancel'),(action,data)=>request(action,data));
 orientationDialog=new OrientationPreview({dialog:$('orientationDialog'),title:$('orientationTitle'),intro:$('orientationIntro'),status:$('orientationStatus'),platePicker:$('orientationPlatePicker'),plate:$('orientationPreviewPlate'),beforeSize:$('orientationBeforeSize'),afterSize:$('orientationAfterSize'),beforeCanvas:$('orientationBeforeCanvas'),afterCanvas:$('orientationAfterCanvas'),beforeLabels:$('orientationBeforeLabels'),afterLabels:$('orientationAfterLabels'),apply:$('orientationApply'),cancel:$('orientationCancel')},(canvas,labels)=>new BPS3D.Viewer(canvas,labels),async p=>{const result=await request('orientation_apply',{token:p.token});if(result){if(p.batch)setMode('layout');else{selected=p.unit;setMode('face');renderInspector();}}},p=>request('orientation_cancel',{token:p.token}));
 arrangementDialog=new ArrangementPreview({dialog:$('arrangementDialog'),title:$('arrangementTitle'),status:$('arrangementStatus'),plate:$('arrangementPreviewPlate'),beforeCanvas:$('arrangementBeforeCanvas'),afterCanvas:$('arrangementAfterCanvas'),beforeLabels:$('arrangementBeforeLabels'),afterLabels:$('arrangementAfterLabels'),apply:$('arrangementApply'),cancel:$('arrangementCancel')},(canvas,labels)=>new BPS3D.Viewer(canvas,labels),async(p,acceptBambuSpacing)=>{const result=await request('arrangement_apply',{token:p.token,acceptBambuSpacing});if(result)setMode('layout');},p=>request('arrangement_cancel',{token:p.token}));
 document.querySelector('.tree-help').textContent='此处拖动仅用于换盘，不会合成整体。拖到模型上即移入它所在的盘。';
 $('ungroup').title='成员保留在当前盘并保持原位置和方向；不重新排盘。';
 const tree=$('plateTree');tree.addEventListener('pointerdown',treePointerDown);tree.addEventListener('pointermove',treePointerMove);tree.addEventListener('pointerup',treePointerUp);tree.addEventListener('pointercancel',()=>{treeDrag=null;clearTreeTarget();hint('');});tree.addEventListener('dragstart',e=>e.preventDefault());
 try{viewer=new BPS3D.Viewer($('modelCanvas'),$('modelLabels'),{isBusy:()=>busy,hint,select:uid=>{selected=uid;renderTree();renderInspector();},group:groupDrop,move:data=>request('move',data),face:data=>request('viewer_face',{...data,revision:loadedRevision})});}
 catch(e){message(e.message,true);}
 let attempts=0;const connect=()=>{if(demo||window.adsk?.fusionSendData){request('bootstrap');return;}if(++attempts<50)setTimeout(connect,200);else message('Fusion 通信尚未就绪。请关闭旧测试对话框后重新加载新版窗口。',true);};connect();
});
