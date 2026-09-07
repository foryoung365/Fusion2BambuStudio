(function(root){'use strict';
function state(plates,current){const ids=plates.map(p=>p.index),index=ids.indexOf(current);return {previous:index>0?ids[index-1]:null,next:index>=0&&index+1<ids.length?ids[index+1]:null,total:ids.length};}
function bindHeader(title,arrow,index,select,toggle){
 title.onclick=()=>{if(index>0)select(index);};
 title.onkeydown=e=>{if(e.target!==title)return;if(e.key==='Enter'||e.key===' '){e.preventDefault();if(index>0)select(index);}};
 arrow.onclick=e=>{e.stopPropagation();toggle(index);};
 // Prevent the parent tree item's keyboard handler from also selecting a plate.
 arrow.onkeydown=e=>e.stopPropagation();
}
const api={state,bindHeader};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.BPSPlateNavigation=api;
})(typeof window!=='undefined'?window:globalThis);
