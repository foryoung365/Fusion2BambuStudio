'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'../ui/app.js'),'utf8');
const start=source.indexOf('async function request(');
const end=source.indexOf('\nfunction selectOptions(',start);
const events=[],opened=[],calls=[],refreshes=[];
const proposal={token:'job-1',scope:'all',errors:[],placements:{}};
const pending={pendingPreview:{token:'job-1',kind:'arrangement_preview'}};
const complete={units:[],notices:['建议已生成'],arrangementPreview:proposal};
const context={
 busy:false,currentPlate:1,geometry:new Map(),state:complete,loadedRevision:1,demo:false,
 setBusy:value=>events.push(['busy',value]),
 rpc:async(action,data)=>{calls.push([action,data]);return action==='arrangement_preview'?pending:complete;},
 update:()=>events.push(['update']),message:value=>events.push(['message',value]),hint:()=>{},
 arrangementDialog:{open:(...args)=>opened.push(args)},orientationDialog:null,
 adsk:{fusionSendData:(action,data)=>{refreshes.push([action,data]);return 'OK';}},
 setTimeout:fn=>{fn();return 1;},setInterval:()=>1,clearInterval:()=>{},
};
context.window={adsk:context.adsk};
const request=vm.runInNewContext(source.slice(start,end)+'\nrequest',context);
request('arrangement_preview',{scope:'all'}).then(async result=>{
 assert.equal(result,complete);
 assert.equal(JSON.stringify(calls),JSON.stringify([
  ['arrangement_preview',{scope:'all',background:true}],
  ['preview_status',{token:'job-1'}],
 ]));
 assert.equal(opened.length,1);
 assert.equal(opened[0][0],proposal);
 assert.deepEqual(events[0],['busy',true]);
 assert.deepEqual(events.at(-1),['busy',false]);
 for(const action of ['arrangement_cancel','arrangement_apply','orientation_cancel','orientation_apply'])
  await request(action,{token:'job-1'});
 assert.deepEqual(refreshes,Array.from({length:4},()=>['palette_refresh','']));
 console.log('Background arrangement preview: request, poll, show proposal and unblock passed');
}).catch(error=>{console.error(error);process.exitCode=1;});
