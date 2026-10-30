// Deterministic CLOSED LOOP of production camera/contact classes and a
// simulated camera plant. No game, browser profile, Android, network or GPU.
const fs=require('fs'),path=require('path'),vm=require('vm'),crypto=require('crypto');
const root=path.resolve(__dirname,'../..'),ts=require(path.join(root,'frontend/node_modules/typescript'));
const output=path.resolve(root,process.argv[2]||'.local-pilot/new-camera-loop.json');
if(!output.startsWith(root+path.sep+'.local-pilot'+path.sep)||fs.existsSync(output))throw Error('output_scope_or_exists');

class Clock{
 now=1000;id=0;jobs=new Map();live=new Set();
 add(fn,delay,repeat=0){const id=++this.id;this.live.add(id);this.jobs.set(id,{id,fn,at:this.now+Math.max(1,delay),repeat});return id;}
 clear(id){this.jobs.delete(id);this.live.delete(id);}
 async until(end){let count=0;while(true){const job=[...this.jobs.values()].sort((a,b)=>a.at-b.at||a.id-b.id)[0];if(!job||job.at>end)break;
  if(++count>50000)throw Error('timer_quota');this.jobs.delete(job.id);this.now=job.at;job.fn();
  if(job.repeat&&this.live.has(job.id)){job.at+=job.repeat;this.jobs.set(job.id,job);}else this.live.delete(job.id);
  await Promise.resolve();await Promise.resolve();
 }this.now=end;await Promise.resolve();}
}
function loadRuntime(clock){
 const context=vm.createContext({performance:{now:()=>clock.now,timeOrigin:0},console,
  setTimeout:(f,ms)=>clock.add(f,ms),clearTimeout:id=>clock.clear(id),
  setInterval:(f,ms)=>clock.add(f,ms,ms),clearInterval:id=>clock.clear(id)}),cache=new Map();
 function load(file){file=path.resolve(file);if(cache.has(file))return cache.get(file).exports;
  if(!file.startsWith(path.join(root,'frontend/src/features/stream')+path.sep))throw Error('module_scope');
  const module={exports:{}};cache.set(file,module);
  const source=fs.readFileSync(file,'utf8'),code=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
  vm.runInContext('(function(require,module,exports){'+code+'\n})',context,{filename:file})(name=>load(path.resolve(path.dirname(file),name+'.ts')),module,module.exports);
  return module.exports;
 }
 return {Contacts:load(path.join(root,'frontend/src/features/stream/teachingContacts.ts')).TeachingContacts,
  Servo:load(path.join(root,'frontend/src/features/stream/walkCameraDrag.ts')).WalkCameraDrag};
}
const rotation=(h,v)=>[Math.cos(h),0,-Math.sin(h),-Math.sin(h)*Math.sin(v),Math.cos(v),-Math.cos(h)*Math.sin(v),Math.sin(h)*Math.cos(v),Math.sin(v),Math.cos(h)*Math.cos(v)];
const forward=(h,v)=>[Math.sin(h)*Math.cos(v),Math.sin(v),Math.cos(h)*Math.cos(v)];
const angular=(a,b)=>Math.acos(Math.max(-1,Math.min(1,a.reduce((sum,n,i)=>sum+n*b[i],0))));

async function runCase(config){
 const clock=new Clock(),{Contacts,Servo}=loadRuntime(clock),servo=new Servo(),rows=[],wire=[],history=[{at:clock.now,h:0,v:0}];
 const begin=clock.now,center={x:288,y:885},anchor={x:1247,y:540},short=1080;
 let h=0,v=0,contact=null,receive=()=>{},lastFrame=clock.now,sequence=0,ready=false,inFlight=false,terminal=null,alignedAt=null,paused=0,faultAt=null;
 let desired=forward(config.yaw??1.1,config.pitch??.3);const binding={captureEpoch:'e'.repeat(32),width:1920,height:1080};
 const envelope={session_id:'a'.repeat(32),capture_epoch:binding.captureEpoch,owner:'b'.repeat(32),contact_protocol:1,max_pointers:3,device_uptime_ms:1000};
 const endpoint={session:envelope.session_id,sharedInput:true,readyState:1,bufferedAmount:0,capture:()=>binding,listen:f=>{receive=f;return()=>{};},send:raw=>{
  const message=JSON.parse(raw);wire.push({at:clock.now-begin,...message});
  if(message.type==='touch_contact_event'&&message.pointer_id===1){
   if(message.action===0)contact={origin:{x:message.x,y:message.y},last:{x:message.x,y:message.y},activated:false};
   if(message.action===2&&contact){
    let dx=message.x-contact.last.x,dy=message.y-contact.last.y;
    if(!contact.activated){const x=message.x-contact.origin.x,y=message.y-contact.origin.y,length=Math.hypot(x,y);
     const scale=length?Math.max(0,length-config.slopPx)/length:0;dx=x*scale;dy=y*scale;contact.activated=length>config.slopPx;}
    const calibrated=servo.snapshot();
    if(config.fault&&calibrated.gainRadiansPerShortSide!==null&&calibrated.pitchGainRadiansPerShortSide!==null&&faultAt===null)faultAt=clock.now-begin;
    const response=faultAt===null?1:config.fault==='frozen'?0:-1;
    h+=response*dx/short*config.gainX;v+=response*dy/short*config.gainY;contact.last={x:message.x,y:message.y};history.push({at:clock.now,h,v});
   }
   if(message.action===1)contact=null;
  }
  clock.add(()=>{
   if(message.type==='touch_open'){receive({type:'touch_session',...envelope,frame_width:1920,frame_height:1080});receive({type:'shared_input_status',...envelope,sequence:0,gesture:0,action:4,pointer_id:-1,outcome:'ready'});}
   else receive({type:'shared_input_status',...envelope,sequence:message.sequence??0,gesture:message.gesture??0,action:message.type==='touch_close'?3:message.action,
    pointer_id:message.pointer_id??-1,outcome:message.type==='touch_close'?'closed':message.action===4?'alive':'applied'});
  },config.ackMs??8);
 }};
 const control=new Contacts(endpoint,binding,()=>clock.now-lastFrame<250,()=>{},(state,reason)=>{if(state==='ready')ready=true;if(state==='failed'&&!terminal)terminal=reason;},undefined,()=>clock.now-lastFrame<1000,center,true);
 const neutral=()=>{paused++;servo.interrupt();control.neutralize();};
 const frameTimer=clock.add(()=>{
  if(terminal)return;const elapsed=clock.now-begin;
  if(config.movingReference)desired=forward(1.1+.35*Math.sin(elapsed/2500),.3+.12*Math.sin(elapsed/3000));
  if(config.gap&&elapsed>=config.gap[0]&&elapsed<config.gap[0]+config.gap[1])return;
  lastFrame=clock.now;if(!ready||inFlight)return;
  const observed=[...history].reverse().find(p=>p.at<=clock.now-config.visualMs)||history[0];
  const noise=(config.noise??0)*Math.sin(++sequence*1.91),R=rotation(observed.h+noise,observed.v-noise*.5),capturedAt=clock.now,seq=sequence;
  inFlight=true;const cost=config.descriptorMs&&sequence%12===0?config.descriptorMs:10;
  clock.add(()=>{
   inFlight=false;if(terminal||!control.isReady)return;
   if(clock.now-capturedAt>=250){neutral();return;}
   const target=[0,1,2].map(k=>R.slice(k*3,k*3+3).reduce((sum,n,i)=>sum+n*desired[i],0));
   const step=servo.update({rotation:R,target,sequence:seq,capturedAt,now:clock.now,canStroke:control.canCameraCommand(center),referenceView:true,alignmentRequired:alignedAt===null});
   rows.push({ms:clock.now-begin,yaw:step.yaw,pitch:step.pitch,physicalError:angular(forward(h,v),desired),reason:step.reason,action:step.action??null,x:step.fraction,y:step.verticalFraction});
   if(step.failed){terminal=step.reason;void control.close();return;}
   if(step.action){
    const generation=servo.generation,until=capturedAt+250;
    control.cameraCommand(step.action==='up'?null:{x:anchor.x+Math.round((step.fraction??0)*short),y:anchor.y+Math.round((step.verticalFraction??0)*short)},until,center).then(applied=>{
     if(terminal||generation!==servo.generation)return;
     if(!applied&&(control.isVideoPaused||clock.now>=until)){neutral();return;}
     servo.finishStroke(applied,clock.now);if(!applied){terminal=control.failureReason||'camera_unconfirmed';void control.close();}
    });
   }
   if(step.reason==='walk_camera_aligned'&&angular(forward(h,v),desired)<.12&&alignedAt===null)alignedAt=clock.now-begin;
  },cost);
 },50,50);
 const guard=clock.add(()=>{if(!terminal&&ready&&!control.isReady)terminal=control.failureReason||'owner_closed';if(control.isVideoPaused)neutral();},25,25);
 await clock.until(begin+(config.durationMs??12000));clock.clear(frameTimer);clock.clear(guard);
 const closing=control.close();await clock.until(clock.now+1000);const closed=await closing;
 const tracking=rows.filter(row=>row.ms>5000).map(row=>row.physicalError);
 return {config,terminal,alignedAtMs:alignedAt,faultAtMs:faultAt,finalAngularError:angular(forward(h,v),desired),neutralizations:paused,closed,
  trackingError:tracking.length?{maximum:Math.max(...tracking),mean:tracking.reduce((sum,n)=>sum+n,0)/tracking.length}:null,
  cameraDowns:wire.filter(e=>e.pointer_id===1&&e.action===0).length,moves:wire.filter(e=>e.pointer_id===1&&e.action===2).length,servo:servo.snapshot(),rows};
}
(async()=>{
 const cases=[];for(const gain of [[3,4],[12,-8],[-6,10]])for(const visualMs of [60,160])for(const slopPx of [8,16]){
  const config={gainX:gain[0],gainY:gain[1],visualMs,slopPx,descriptorMs:130,noise:.004};
  cases.push(await runCase(config));
 }
 cases.push(await runCase({gainX:6,gainY:-5,visualMs:100,slopPx:16,gap:[1100,350],noise:.004,descriptorMs:130}));
 for(const yaw of [-1.1,1.5])for(const pitch of [-.4,.55])cases.push(await runCase({gainX:6,gainY:-5,visualMs:160,slopPx:16,yaw,pitch,noise:.004,descriptorMs:130}));
 for(const fault of ['frozen','reversed'])cases.push(await runCase({gainX:6,gainY:-5,visualMs:100,slopPx:16,yaw:1.5,pitch:.55,noise:.004,descriptorMs:130,fault}));
 cases.push(await runCase({gainX:6,gainY:-5,visualMs:100,slopPx:16,noise:.004,descriptorMs:130,movingReference:true,durationMs:50000}));
 for(const c of cases)c.passed=c.closed&&(c.config.fault?
  c.faultAtMs!==null&&['walk_camera_response_not_observed','walk_camera_response_wrong_direction'].includes(c.terminal):
  c.terminal===null&&c.alignedAtMs!==null&&(c.config.movingReference?
   // A moving setpoint is evaluated over time, including the 0.20-rad entry
   // deadband and calibration after re-touch; it cannot have zero final error.
   c.servo.pulses>120&&c.trackingError.maximum<.35&&c.trackingError.mean<.15&&c.finalAngularError<.25:
   c.finalAngularError<.12));
 const result={schema:'sphere-camera-closed-loop-simulation-v1',physicalActions:0,simulatedPlant:true,realGame:false,actualLocalization:false,
  productionSources:Object.fromEntries(['walkCameraDrag.ts','teachingContacts.ts','walkCamera.ts'].map(name=>[name,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'frontend/src/features/stream',name))).digest('hex')])),cases};
 fs.writeFileSync(output,JSON.stringify(result,null,2),{flag:'wx'});
 for(const c of cases)console.log(JSON.stringify({config:c.config,terminal:c.terminal,alignedAtMs:c.alignedAtMs,finalAngularError:c.finalAngularError,moves:c.moves,cameraDowns:c.cameraDowns,passed:c.passed}));
 if(cases.some(c=>!c.passed))process.exitCode=1;
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
