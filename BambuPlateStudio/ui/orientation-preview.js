(function(root){'use strict';
class OrientationPreview {
 constructor(elements,makeViewer,onApply,onCancel){
  this.e=elements;this.makeViewer=makeViewer;this.onApply=onApply;this.onCancel=onCancel;
  this.views=[];this.pending=null;this.ready=false;
  elements.apply.addEventListener('click',()=>this.apply());
  elements.cancel.addEventListener('click',()=>this.cancel());
  elements.plate?.addEventListener('change',()=>this.showPlate());
  elements.dialog.addEventListener('cancel',e=>{e.preventDefault();this.cancel();});
 }
 open(proposal,unit,geometry,state,currentPlate){
  this.pending=proposal;this.ready=false;
  this.e.dialog.classList?.toggle('batch',!!proposal.batch);
  this.e.platePicker.hidden=!proposal.batch;
  this.e.status.classList?.toggle('invalid',!!proposal.batch&&!!proposal.errors.length);
  this.e.dialog.showModal();
  try{
   if(proposal.batch)this.openBatch(proposal,state,geometry,currentPlate);
   else this.openSingle(proposal,unit,geometry);
   this.ready=true;
  }catch(error){this.e.status.textContent='无法显示预览，未应用：'+error.message;}
  this.refreshButtons(false);
 }
 openSingle(proposal,unit,geometry){
  this.e.title.textContent='自动朝向预览 · '+proposal.name;
  this.e.apply.textContent='确认应用，可撤销';
  this.e.intro.textContent='拖动模型旋转查看。当前只是建议预览，确认前不会改变盘位或朝向。';
  this.e.status.textContent=proposal.warning;
  this.e.beforeSize.textContent=proposal.beforeSize.map(v=>v.toFixed(1)).join(' × ')+' mm';
  this.e.afterSize.textContent=proposal.afterSize.map(v=>v.toFixed(1)).join(' × ')+' mm';
  const bodies=unit.members.map(m=>geometry.get(m.uid));
  if(bodies.some(b=>!b))throw Error('模型预览数据不完整，请重新读取设计。');
  if(!this.views.length)this.views=[this.makeViewer(this.e.beforeCanvas,this.e.beforeLabels),this.makeViewer(this.e.afterCanvas,this.e.afterLabels)];
  this.views.forEach((view,i)=>{
   const shown={...unit,rotation:i?proposal.rotation:proposal.beforeRotation,placement:null};
   view.setState({units:[shown],plates:[]},{mode:'face',selected:unit.uid});
   view.setGeometry({bodies});view.iso();
  });
 }
 openBatch(proposal,state,geometry,currentPlate){
  this.e.title.textContent='自动朝向预览 · '+(proposal.scope==='all'?'所有盘':'当前盘');
  this.e.apply.textContent=proposal.errors.length?'应用朝向，稍后重新摆位':'确认应用，可撤销';
  this.e.intro.textContent='右键拖动可旋转视角，逐盘比较。确认前不会修改任何模型；确认后可能需要重新摆位。';
  const skipped=proposal.skipped.map(item=>item.name+'：'+item.reason);
  this.e.status.textContent=`建议调整 ${proposal.moved} / ${proposal.total} 个打印单元。${proposal.warning}`+
   (proposal.errors.length?'\n新出现的排盘错误：'+proposal.errors.join('；'):'')+
   (skipped.length?'\n未调整：'+skipped.join('；'):'');
  this.e.plate.replaceChildren();
  for(const number of proposal.plates){const option=document.createElement('option');option.value=String(number);option.textContent='第 '+number+' 盘';this.e.plate.append(option);}
  this.e.plate.value=String(proposal.plates.includes(currentPlate)?currentPlate:proposal.plates[0]);
  this.before=state;
  this.after={...state,units:state.units.map(u=>{
   const changed=proposal.units[u.uid];
   return changed?{...u,rotation:changed.rotation,placement:{...u.placement,...proposal.placements[u.uid]}}:u;
  })};
  const members=state.units.filter(u=>proposal.plates.includes(u.placement?.plate)).flatMap(u=>u.members);
  if(members.some(m=>!geometry.has(m.uid)))throw Error('模型预览数据不完整，请重新读取设计。');
  if(!this.views.length)this.views=[this.makeViewer(this.e.beforeCanvas,this.e.beforeLabels),this.makeViewer(this.e.afterCanvas,this.e.afterLabels)];
  const bodies=members.map(m=>geometry.get(m.uid));
  this.views.forEach(view=>view.setGeometry({bodies}));
  this.showPlate();
 }
 showPlate(){
  if(!this.pending?.batch||!this.views.length||!this.before)return;
  const plate=Number(this.e.plate.value),count=this.before.units.filter(u=>u.placement?.plate===plate).length;
  const changed=this.before.units.filter(u=>u.placement?.plate===plate&&this.pending.units[u.uid]).length;
  this.e.beforeSize.textContent=`第 ${plate} 盘 · ${count} 个打印单元`;
  this.e.afterSize.textContent=`第 ${plate} 盘 · ${changed} 个朝向建议`;
  this.views[0].setState(this.before,{mode:'layout',plate});
  this.views[1].setState(this.after,{mode:'layout',plate});
  this.views.forEach(view=>view.top());
 }
 refreshButtons(busy){this.e.apply.disabled=busy||!this.ready||(!!this.pending?.batch&&!Object.keys(this.pending.units).length);this.e.cancel.disabled=busy;}
 apply(){if(!this.pending||!this.ready||this.e.apply.disabled)return;const p=this.pending;this.pending=null;this.ready=false;this.e.dialog.close();this.onApply(p);}
 cancel(){const p=this.pending;this.pending=null;this.ready=false;this.e.dialog.close();if(p)this.onCancel(p);}
}
if(typeof module!=='undefined'&&module.exports)module.exports=OrientationPreview;else root.OrientationPreview=OrientationPreview;
})(typeof window!=='undefined'?window:globalThis);
