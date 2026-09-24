'use strict';
const assert=require('node:assert/strict');
const Preview=require('../ui/arrangement-preview.js');
class Element{
 constructor(){this.events={};this.children=[];this.classList={toggle(){},add(){}};this.value='';}
 addEventListener(name,fn){this.events[name]=fn;}
 showModal(){this.open=true;}
 close(){this.open=false;}
 replaceChildren(){this.children=[];}
 append(child){this.children.push(child);if(!this.value)this.value=child.value;}
}
global.document={createElement:()=>new Element()};
const elements=Object.fromEntries(['dialog','title','status','plate','beforeCanvas','afterCanvas','beforeLabels','afterLabels','apply','cancel'].map(key=>[key,new Element()]));
const shown=[],applied=[],accepted=[],cancelled=[];
const preview=new Preview(elements,()=>({setGeometry(){},setState:(state,options)=>shown.push({state,options}),top(){}}),
 (p,accept)=>{applied.push(p.token);accepted.push(accept);},p=>cancelled.push(p.token));
const units=[{uid:'u',name:'part',members:[{uid:'body'}],placement:{plate:2,x:15,y:20,angle:0,z:0}}];
const state={units,plates:[{index:2}],bed:{width:256,depth:256,origin_x:0,origin_y:0}};
const proposal={token:'first',scope:'current',plates:[2],placements:{u:{x:120,y:130}},moved:1,total:1,errors:[],warning:'positions only'};
preview.open(proposal,state,new Map([['body',{}]]),2);
assert.equal(elements.dialog.open,true);
assert.equal(elements.apply.disabled,false);
assert.equal(shown[0].state.units[0].placement.x,15);
assert.equal(shown[1].state.units[0].placement.x,120);
assert.equal(units[0].placement.x,15);
elements.cancel.events.click();assert.deepEqual(cancelled,['first']);assert.deepEqual(applied,[]);
preview.open({...proposal,token:'second',errors:['gap']},state,new Map([['body',{}]]),2);
assert.equal(elements.apply.disabled,true);
elements.apply.events.click();assert.deepEqual(applied,[]);
elements.dialog.events.cancel({preventDefault(){}});assert.deepEqual(cancelled,['first','second']);
preview.open({...proposal,token:'third'},state,new Map([['body',{}]]),2);
elements.apply.events.click();elements.apply.events.click();assert.deepEqual(applied,['third']);
const split={...proposal,token:'split',plates:[2,3],newPlates:[{index:3,name:'由第 2 盘拆出',allow_mixed:false}],placements:{u:{plate:3,x:120,y:130}}};
preview.open(split,state,new Map([['body',{}]]),2);
assert.equal(elements.apply.disabled,false);
assert.match(elements.title.textContent,/自动分盘/);
assert.match(elements.status.textContent,/新增第 3 盘：part/);
assert.equal(elements.plate.children[1].textContent,'第 3 盘（新增）');
elements.plate.value='3';elements.plate.events.change();
assert.equal(shown.at(-1).state.units[0].placement.plate,3);
assert.equal(shown.at(-2).state.units[0].placement.plate,2);
elements.cancel.events.click();assert.equal(units[0].placement.plate,2);
preview.open(split,state,new Map([['body',{}]]),2);
elements.apply.events.click();assert.deepEqual(applied,['third','split']);
preview.open({...split,token:'override',errors:['当前 5 mm 件间距不足'],canAcceptBambuSpacing:true},state,new Map([['body',{}]]),2);
assert.equal(elements.apply.disabled,false);
assert.match(elements.apply.textContent,/改为 0 mm/);
elements.apply.events.click();assert.deepEqual(applied,['third','split','override']);
assert.deepEqual(accepted,[false,false,true]);
console.log('Arrangement preview: before/after, plate selection, cancel and invalid-result guard passed');
