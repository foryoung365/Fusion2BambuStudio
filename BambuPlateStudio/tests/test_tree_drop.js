'use strict';
const assert=require('node:assert/strict');
const resolve=require('../ui/tree-drop.js');
const units=[{uid:'source',placement:{plate:1}},{uid:'target',placement:{plate:2}},{uid:'pending'}];
const initial=JSON.stringify(units);
for(const mode of ['group','face','layout']){
 const result=resolve('source',{unit:'target'},units,mode);
 assert.deepEqual(result,{action:'transfer_plate',data:{unit:'source',plate:2}});
 assert.notEqual(result.action,'group_drop');
}
assert.deepEqual(resolve('source',{plate:'2'},units),resolve('source',{unit:'target'},units));
assert.match(resolve('source',{plate:'1'},units).message,/已在/);
assert.match(resolve('source',{unit:'pending'},units).message,/尚未分盘/);
assert.ok(!resolve('source',{plate:'0'},units).action);
assert.equal(JSON.stringify(units),initial);
console.log('Tree drop: model/header target always means transfer; no grouping or source mutation');
