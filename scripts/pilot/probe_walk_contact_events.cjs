// Production contact driver against a LOCAL simulated ACK endpoint, no Android.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const root=path.resolve(__dirname,'../..');process.chdir(root);
const ts=require(path.join(root,'frontend/node_modules/typescript'));
const source=fs.readFileSync('frontend/src/features/stream/teachingContacts.ts','utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const holder={exports:{}};new Function('exports','require','module',compiled)(holder.exports,require,holder);
const {TeachingContacts}=holder.exports;
const output=path.resolve(root,process.argv[2]||'.local-pilot/new-contact-smoothness-probe.json');
if(!output.startsWith(root+path.sep+'.local-pilot'+path.sep))throw Error('output_outside_local_pilot');
if(fs.existsSync(output))throw Error('existing_evidence');
const wait=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const began=performance.now(),rows=[],envelope={session_id:'a'.repeat(32),capture_epoch:'e'.repeat(32),contact_protocol:1,max_pointers:3,owner:'b'.repeat(32)};
 const binding={captureEpoch:envelope.capture_epoch,width:1920,height:1080},center={x:288,y:885};
 let listener=()=>{},paused=false,lastFrame=performance.now(),ready;
 const opened=new Promise(r=>{ready=r;});const frameTimer=setInterval(()=>{if(!paused)lastFrame=performance.now();},33);
 const endpoint={session:envelope.session_id,sharedInput:true,readyState:1,bufferedAmount:0,capture:()=>binding,listen:f=>{listener=f;return()=>{};},
  send:raw=>{const v=JSON.parse(raw);rows.push({kind:'wire',ms:performance.now()-began,...v});setTimeout(()=>{
   if(v.type==='touch_open'){listener({type:'touch_session',...envelope,frame_width:1920,frame_height:1080});listener({type:'shared_input_status',...envelope,sequence:0,gesture:0,action:4,pointer_id:-1,outcome:'ready',device_uptime_ms:1000});}
   else listener({type:'shared_input_status',...envelope,sequence:v.sequence??0,gesture:v.gesture??0,action:v.type==='touch_close'?3:v.action,pointer_id:v.pointer_id??-1,outcome:v.type==='touch_close'?'closed':v.action===4?'alive':'applied',device_uptime_ms:1000});
  },8);}};
 const driver=new TeachingContacts(endpoint,binding,()=>performance.now()-lastFrame<250,
  e=>rows.push({kind:'journal',ms:performance.now()-began,...e}),state=>{if(state==='ready')ready();},undefined,()=>performance.now()-lastFrame<1000,center,true);
 try{
  await opened;driver.set(0,center);await wait(15);driver.set(0,{x:288,y:848});await wait(15);
  await driver.cameraCommand({x:1247,y:540},performance.now()+240,center);
  const turnBegan=performance.now()-began;
  const applied=await driver.cameraCommand({x:1290,y:564},performance.now()+240,center);
  const turnEnded=performance.now()-began;
  paused=true;const gapBegan=performance.now()-began;await wait(350);
  const pausedOwnerAlive=driver.isReady&&driver.isVideoPaused,neutralNoCamera=!driver.hasContact(1);
  paused=false;lastFrame=performance.now();await wait(35);driver.set(0,{x:288,y:848});await wait(20);
  const resumed=driver.isReady&&!driver.isVideoPaused;
  const closed=await driver.close();
  const moves=rows.filter(r=>r.kind==='wire'&&r.type==='touch_contact_event'&&r.pointer_id===1&&r.action===2);
  let previous={x:1247,y:540},maximumJump=0;for(const row of moves){maximumJump=Math.max(maximumJump,Math.hypot(row.x-previous.x,row.y-previous.y));previous=row;}
  const result={schema:'sphere-local-contact-smoothness-probe-v1',physicalActions:0,simulatedAcks:true,ackDelayMs:8,realVideo:false,
   contactDriverSha256:crypto.createHash('sha256').update(source).digest('hex'),turnBegan,turnEnded,turnApplied:applied,
   cameraMoves:moves.length,maximumStepPixels:maximumJump,gapBegan,gapInjectedMs:350,pausedOwnerAlive,neutralNoCamera,resumed,closed,
   stickDowns:rows.filter(r=>r.kind==='wire'&&r.pointer_id===0&&r.action===0).length,rows};
  if(!applied||moves.length<3||!pausedOwnerAlive||!neutralNoCamera||!resumed||!closed||result.stickDowns!==1)throw Error('probe_not_verified');
  fs.writeFileSync(output,JSON.stringify(result,null,2),{flag:'wx'});console.log(JSON.stringify({...result,rows:undefined}));
 }finally{clearInterval(frameTimer);if(driver.isReady)await driver.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
