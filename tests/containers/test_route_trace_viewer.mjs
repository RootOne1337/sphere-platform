import { strict as assert } from 'node:assert';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source=fs.readFileSync(new URL('../../scripts/pilot/route_trace_viewer/viewer.js',import.meta.url),'utf8');
async function setup(surface=false,diagnostics=null){
  const calls=[];
  const overlay={clearRect(){calls.length=0;},beginPath(){},moveTo(...p){calls.push(['move',...p]);},lineTo(...p){calls.push(['line',...p]);},stroke(){}};
  const map={clearRect(){},beginPath(){},moveTo(){},lineTo(){},stroke(){},arc(){},fill(){}};
  const elements={};
  for(const id of ['video','overlay','map','enabled','thickness','opacity','mode','status'])elements[id]={events:{},addEventListener(name,handler){this.events[name]=handler;}};
  Object.assign(elements.overlay,{getContext:()=>overlay});Object.assign(elements.map,{getContext:()=>map});
  Object.assign(elements.enabled,{checked:true});Object.assign(elements.thickness,{value:'1.5'});Object.assign(elements.opacity,{value:'.65'});Object.assign(elements.mode,{value:'camera',options:[{},{}]});
  Object.assign(elements.video,{currentTime:0,pause(){this.paused=true;},requestVideoFrameCallback(callback){this.callback=callback;}});
  Object.assign(elements.map,{getBoundingClientRect:()=>({left:0,top:0,width:500,height:500}),setPointerCapture(){}});
  if(diagnostics)elements.diagnostics={textContent:JSON.stringify(diagnostics)};
  const data={sourceManifestSha256:'a'.repeat(64),geometrySha256:'b'.repeat(64),width:960,height:540,trace:[[0,0],[1,1]],lookaheadMs:1200,surfaceLookaheadMs:5000,
    frames:[0,1,2].map((seconds,index)=>({seconds,index:index*10,poseSource:'reconstruction_reference_pose',mapPoint:[0,0],points:[[.1+index*.1,.5],[.3+index*.1,.6]],
      ...(surface?{surfacePreview:{segments:[],reason:'no_local_surface_support'}}:{})}))};
  await vm.runInNewContext(source,{document:{getElementById:id=>elements[id]},fetch:async()=>({ok:true,json:async()=>data})});
  return {calls,elements,data};
}

test('overlay uses decoded media time, while paused settings redraw the current sought frame',async()=>{
  const {calls,elements}=await setup();
  elements.video.callback(500,{mediaTime:1.1});
  assert.match(elements.status.textContent,/Исходный кадр: 10/);
  assert.deepEqual(calls[0],['move',192,270]);
  elements.video.currentTime=2;elements.opacity.events.input();
  assert.match(elements.status.textContent,/Исходный кадр: 20/);
  elements.enabled.checked=false;elements.enabled.events.input();assert.equal(calls.length,0);
});

test('missing surface support shows no invented line; camera comparison remains explicit',async()=>{
  const {calls,elements}=await setup(true);
  assert.equal(elements.mode.value,'surface');assert.equal(calls.length,0);
  assert.match(elements.status.textContent,/Нет опоры поверхности/);
  elements.mode.value='camera';elements.mode.events.input();
  assert.equal(calls.length,2);assert.match(elements.status.textContent,/Путь камеры/);
});

test('map click seeks the source recording; dragging only pans, wheel zoom does not seek',async()=>{
  const {elements}=await setup(),map=elements.map,video=elements.video;
  const event=(clientX,clientY)=>({button:0,pointerId:1,clientX,clientY,preventDefault(){}});
  video.currentTime=2;map.events.pointerdown(event(30,470));map.events.pointerup(event(30,470));
  assert.equal(video.currentTime,0);assert.equal(video.paused,true);
  video.currentTime=2;map.events.pointerdown(event(30,470));map.events.pointermove(event(80,470));map.events.pointerup(event(80,470));
  assert.equal(video.currentTime,2);
  map.events.wheel({...event(80,470),deltaY:-100});assert.equal(video.currentTime,2);
  map.events.dblclick();assert.equal(video.currentTime,2);
});

test('a rejected source-frame localization hides both route modes instead of painting over the gap',async()=>{
  const {calls,elements,data}=await setup();
  data.frames[1].localizationCheck={state:'unknown'};
  elements.video.callback(0,{mediaTime:1});assert.equal(calls.length,0);
  assert.match(elements.status.textContent,/ПРИВЯЗКА ПОТЕРЯНА/);
  elements.video.callback(0,{mediaTime:2});assert.equal(calls.length,2);
});

test('diagnostics must belong to the exact capture and camera geometry',async()=>{
  const extra={schemaVersion:1,sourceManifestSha256:'a'.repeat(64),geometrySha256:'WRONG',frames:[],traceTimes:[]};
  const {calls,elements}=await setup(false,extra);
  assert.equal(calls.length,0);assert.match(elements.status.textContent,/Не удалось прочитать/);
  assert.equal(elements.video.callback,undefined);
});
