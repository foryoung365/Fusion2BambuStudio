(function(root){'use strict';
class ArrangementPreview {
 constructor(elements,makeViewer,onApply,onCancel){
  this.e=elements;this.makeViewer=makeViewer;this.onApply=onApply;this.onCancel=onCancel;
  this.views=[];this.pending=null;this.ready=false;
  elements.apply.addEventListener('click',()=>this.apply());
  elements.cancel.addEventListener('click',()=>this.cancel());
  elements.plate.addEventListener('change',()=>this.showPlate());
  elements.dialog.addEventListener('cancel',event=>{event.preventDefault();this.cancel();});
 }
 open(proposal,state,geometry,currentPlate){
  this.pending=proposal;this.ready=false;
  this.before=state;
  this.after={...state,plates:[...state.plates,...(proposal.newPlates||[])],units:state.units.map(unit=>{
   const position=proposal.placements[unit.uid];
   return position?{...unit,placement:{...unit.placement,...position}}:unit;
  })};
  this.e.title.textContent=(proposal.newPlates?.length?'Bambu 自动分盘与摆位预览':'Bambu 自动摆位预览')+' · '+(proposal.scope==='all'?'所有盘':'当前盘');
  this.e.plate.replaceChildren();
  for(const number of proposal.plates){const option=document.createElement('option');option.value=String(number);option.textContent='第 '+number+' 盘'+(proposal.newPlates?.some(plate=>plate.index===number)?'（新增）':'');this.e.plate.append(option);}
  this.e.plate.value=String(proposal.plates.includes(currentPlate)?currentPlate:proposal.plates[0]);
  const skipped=(proposal.skipped||[]).map(item=>`第 ${item.plate} 盘未改动：${item.reason}`);
  const added=(proposal.newPlates||[]).map(plate=>`新增第 ${plate.index} 盘：`+state.units.filter(unit=>proposal.placements[unit.uid]?.plate===plate.index).map(unit=>unit.name).join('、'));
  const acceptSpacing=!!(proposal.errors.length&&proposal.canAcceptBambuSpacing);
  this.e.apply.textContent=acceptSpacing?'按 Bambu 间距确认（当前件间距改为 0 mm）':'确认应用，可撤销';
  this.e.status.textContent=proposal.errors.length?
   (acceptSpacing?'当前件间距规则不符合 Bambu 建议。可明确选择将当前文档件间距改为 0 mm 后确认；实体重叠与出板仍被拦截。\n':'不能应用：')+
   proposal.errors.join('\n')+(added.length?'\n'+added.join('\n'):'')+(skipped.length?'\n'+skipped.join('\n'):''):
   `建议移动 ${proposal.moved} / ${proposal.total} 个可处理打印单元。${proposal.warning}`+
   (added.length?'\n'+added.join('\n'):'')+(skipped.length?'\n'+skipped.join('\n'):'');
  this.e.status.classList.toggle('invalid',proposal.errors.length>0&&!acceptSpacing);
  this.e.dialog.showModal();
  try{
   const members=state.units.filter(unit=>proposal.plates.includes(unit.placement?.plate)).flatMap(unit=>unit.members);
   if(members.some(member=>!geometry.has(member.uid)))throw Error('模型预览数据不完整，请重新读取设计。');
   if(!this.views.length)this.views=[this.makeViewer(this.e.beforeCanvas,this.e.beforeLabels),this.makeViewer(this.e.afterCanvas,this.e.afterLabels)];
   const bodies=members.map(member=>geometry.get(member.uid));
   this.views.forEach(view=>view.setGeometry({bodies}));
   this.showPlate();this.ready=true;
  }catch(error){this.e.status.textContent='无法显示预览，未应用：'+error.message;this.e.status.classList.add('invalid');}
  this.refreshButtons(false);
 }
 showPlate(){
  if(!this.views.length||!this.before)return;
  const plate=Number(this.e.plate.value);
  this.views[0].setState(this.before,{mode:'layout',plate});
  this.views[1].setState(this.after,{mode:'layout',plate});
  this.views.forEach(view=>view.top());
 }
 refreshButtons(busy){this.e.apply.disabled=busy||!this.ready||!!(this.pending?.errors.length&&!this.pending.canAcceptBambuSpacing);this.e.cancel.disabled=busy;}
 apply(){if(!this.pending||!this.ready||this.pending.errors.length&&!this.pending.canAcceptBambuSpacing)return;const proposal=this.pending,acceptSpacing=!!(proposal.errors.length&&proposal.canAcceptBambuSpacing);this.pending=null;this.ready=false;this.e.dialog.close();this.onApply(proposal,acceptSpacing);}
 cancel(){const proposal=this.pending;this.pending=null;this.ready=false;this.e.dialog.close();if(proposal)this.onCancel(proposal);}
}
if(typeof module!=='undefined'&&module.exports)module.exports=ArrangementPreview;else root.ArrangementPreview=ArrangementPreview;
})(typeof window!=='undefined'?window:globalThis);
