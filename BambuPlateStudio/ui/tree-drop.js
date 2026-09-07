/* Tree dragging always changes plate membership; grouping belongs to the 3D view. */
(function(root){'use strict';
function resolveTreeDrop(sourceId,target,units){
 const source=units.find(u=>u.uid===sourceId);
 if(!source)return {message:'拖动的模型已失效，请重新选择。'};
 let plate;
 if(target.plate!==undefined)plate=Number(target.plate);
 else{const unit=units.find(u=>u.uid===target.unit);if(!unit?.placement)return {message:'目标模型尚未分盘，请拖到打印盘标题或已分盘的模型上。'};plate=unit.placement.plate;}
 if(!Number.isInteger(plate)||plate<1)return {message:'请拖到有效的打印盘标题或已分盘的模型上。'};
 if(source.placement?.plate===plate)return {message:'该模型已在第 '+plate+' 盘，无需换盘。'};
 return {action:'transfer_plate',data:{unit:sourceId,plate}};
}
if(typeof module!=='undefined'&&module.exports)module.exports=resolveTreeDrop;else root.resolveTreeDrop=resolveTreeDrop;
})(typeof window!=='undefined'?window:globalThis);
