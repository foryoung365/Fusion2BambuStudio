'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

class Element {
 constructor(){this.children=[];this.style={};this.hidden=false;}
 append(...children){this.children.push(...children);}
 replaceChildren(){this.children=[];}
 scrollIntoView(){this.scrolled=true;}
 focus(){this.focused=true;}
}
const elements={colorReview:new Element(),memberColorsPanel:new Element(),'bodyColor_mixed':new Element()};
const source=fs.readFileSync(path.join(__dirname,'../ui/app.js'),'utf8');
const start=source.indexOf('function renderColorReview(');
const end=source.indexOf('\nfunction renderColors(',start);
assert.ok(start>=0&&end>start,'The app must render the primary-color review after state updates');
const selected=[],modes=[];
const context={
 state:{units:[{uid:'whole',placement:{plate:2},members:[
  {uid:'mixed',name:'多色零件',path:'组件:1',color:'#FF0000',mixedFaces:true,colorOverridden:false},
  {uid:'confirmed',name:'已确认零件',color:'#000000',mixedFaces:true,colorOverridden:true},
 ]}]},busy:false,currentPlate:1,closedPlates:new Set([2]),
 $:id=>elements[id],
 node:(tag,text,cls)=>Object.assign(new Element(),{tag,textContent:text,className:cls}),
 choose:uid=>selected.push(uid),setMode:mode=>modes.push(mode),
};
const render=vm.runInNewContext(source.slice(start,end)+'\nrenderColorReview',context);
render();
const root=elements.colorReview;
assert.equal(root.hidden,false);
const items=root.children[1];
assert.equal(items.children.length,1);
const item=items.children[0];
assert.match(item.children[1].textContent,/第 2 盘.*多色零件.*#FF0000/);
item.onclick();
assert.deepEqual(selected,['whole']);
assert.deepEqual(modes,['layout']);
assert.equal(context.currentPlate,2);
assert.equal(context.closedPlates.has(2),false);
assert.equal(elements.memberColorsPanel.open,true);
assert.equal(elements.bodyColor_mixed.focused,true);
context.busy=true;item.onclick();assert.equal(selected.length,1);context.busy=false;
render();assert.equal(root.children[1].children.length,1,'Warnings survive subsequent state rendering');
context.state.units[0].placement.plate=3;
render();assert.match(root.children[1].children[0].children[1].textContent,/第 3 盘/);
context.state.units[0].members[0].colorOverridden=true;
render();assert.equal(root.hidden,true);
context.state.units[0].members[0].colorOverridden=false;
context.state.units[0].placement=null;
render();assert.equal(root.hidden,true,'The review is shown after placement');
const update=source.slice(source.indexOf('function update('),source.indexOf('\nfunction renderColorReview('));
assert.match(update,/renderColorReview\(\)/,'Each server state must refresh the color review');
const html=fs.readFileSync(path.join(__dirname,'../ui/index.html'),'utf8');
assert.match(html,/id="colorReview"/);
assert.match(html,/id="memberColorsPanel"/);
console.log('Primary-color review: per-part warning, plate updates, selection, color controls and manual resolution passed');
