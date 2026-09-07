'use strict';
const assert=require('node:assert/strict');
const TransferConfirmation=require('../ui/transfer-confirm.js');
class Element {constructor(){this.events={};this.open=false;}addEventListener(k,f){this.events[k]=f;}showModal(){this.open=true;}close(){this.open=false;}}
const dialog=new Element(),message={},accept=new Element(),cancel=new Element(),sent=[];
const ui=new TransferConfirmation(dialog,message,accept,cancel,(a,d)=>sent.push([a,d]));
const transaction={action:'transfer_plate',data:{unit:'whole-group',plate:2}};
ui.open(transaction,'确认跨色？');assert.equal(dialog.open,true);assert.equal(message.textContent,'确认跨色？');
cancel.events.click();assert.equal(dialog.open,false);assert.equal(sent.length,0);
ui.open(transaction,'确认跨色？');dialog.events.cancel();accept.events.click();assert.equal(sent.length,0);
dialog.close();ui.open(transaction,'确认跨色？');transaction.data.plate=99;
accept.events.click();accept.events.click();
assert.deepEqual(sent,[['transfer_plate',{unit:'whole-group',plate:2,confirmMixed:true}]]);
assert.equal(dialog.open,false);
console.log('Mixed-transfer confirmation: cancel, Escape, immutable request and single confirmation passed');
