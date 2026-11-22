import {strict as assert} from 'node:assert';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
const source=fs.readFileSync(new URL('../../scripts/pilot/live_route_viewer/viewer.js',import.meta.url),'utf8');
async function setup(){
  const elements={},requests=[],timeouts=[],intervals=[];
  for(const id of ['image','status','start','stop','confirmed','hz','tracker','tracker-control'])elements[id]={events:{},addEventListener(name,cb){this.events[name]=cb;},removeAttribute(name){delete this[name];}};
  elements.confirmed.checked=false;elements.hz.value='5';
  elements.tracker.value='anchored_flow';
  elements['tracker-control'].hidden=true;
  let data={oneShot:false,phase:'waiting_for_manual_start',sample:null},rejectStart=false;
  await vm.runInNewContext(source,{document:{getElementById:id=>elements[id]},performance:{now:()=>100},setTimeout:cb=>timeouts.push(cb),setInterval:cb=>intervals.push(cb),
    fetch:async(url,options)=>{requests.push([url,options]);if(url==='start'&&rejectStart)throw Error('lost');return {ok:true,json:async()=>data};}});
  await new Promise(resolve=>setImmediate(resolve));
  return {elements,requests,timeouts,intervals,setData:value=>{data=value;},rejectStart:()=>{rejectStart=true;}};
}
test('loading the observer never opens Android; manual confirmation is required for its one start',async()=>{
  const {elements,requests}=await setup();
  assert.equal(requests.filter(x=>x[0]==='start').length,0);
  await elements.start.events.click();assert.equal(requests.filter(x=>x[0]==='start').length,0);
  elements.confirmed.checked=true;await elements.start.events.click();
  assert.deepEqual(JSON.parse(requests.find(x=>x[0]==='start')[1].body),{hz:5,sceneConfirmed:true});
});
test('flow is an explicit manual choice only when this server advertises it',async()=>{
  const view=await setup(),{elements,requests}=view;
  assert.equal(elements['tracker-control'].hidden,true);
  view.setData({oneShot:false,phase:'waiting_for_manual_start',sample:null,trackersAvailable:['descriptor','anchored_flow']});
  await view.timeouts.shift()();assert.equal(elements['tracker-control'].hidden,false);
  assert.equal(requests.filter(x=>x[0]==='start').length,0);
  elements.confirmed.checked=true;await elements.start.events.click();
  assert.deepEqual(JSON.parse(requests.find(x=>x[0]==='start')[1].body),{hz:5,sceneConfirmed:true,tracker:'anchored_flow'});
  assert.equal(elements.tracker.disabled,true);
});

test('an uncertain start cannot be silently re-enabled by later status polling; stale images disappear',async()=>{
  const view=await setup(),{elements}=view;
  view.rejectStart();elements.confirmed.checked=true;await elements.start.events.click();
  await view.timeouts.shift()();assert.equal(elements.start.disabled,true);
  view.setData({oneShot:true,phase:'observing_without_input',sample:{epoch:'test',sequence:1,jpeg:'a',receiverAgeMs:100,state:'unknown',inliers:0,computeMs:100,reason:'pose_unverified'}});
  await view.timeouts.shift()();assert.equal(elements.image.src,'data:image/jpeg;base64,a');
  view.setData({oneShot:true,phase:'observing_without_input',sample:null});
  await view.timeouts.shift()();assert.equal(elements.image.src,undefined);assert.match(elements.status.textContent,/Нет свежего кадра/);
});
