/** @jest-environment node */
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { webcrypto } from 'node:crypto';
class Folder {
  entries=new Map<string,Folder|MemoryFile>();
  async removeEntry(name:string) {
    if(!this.entries.delete(name))throw Object.assign(Error(),{name:'NotFoundError'});
  }
  async *values(){for(const[name,value]of this.entries)yield{name,kind:value instanceof Folder?'directory':'file'};}
  async getDirectoryHandle(name:string,options?:{create:boolean}):Promise<Folder>{
    if(!this.entries.has(name)){if(!options?.create)throw Object.assign(Error(),{name:'NotFoundError'});this.entries.set(name,new Folder());}
    return this.entries.get(name) as Folder;
  }
  async getFileHandle(name:string,options?:{create:boolean}):Promise<MemoryFile>{
    if(!this.entries.has(name)){if(!options?.create)throw Object.assign(Error(),{name:'NotFoundError'});this.entries.set(name,new MemoryFile());}
    return this.entries.get(name) as MemoryFile;
  }
}
class MemoryFile {
  data=Buffer.alloc(0);
  async createWritable(){return{write:async(value:ArrayBuffer|string)=>{this.data=Buffer.concat([this.data,typeof value==='string'?Buffer.from(value):Buffer.from(new Uint8Array(value))]);},close:async()=>{}};}
  async getFile(){const bytes=this.data;return{size:bytes.length,arrayBuffer:async()=>Uint8Array.from(bytes).buffer,text:async()=>bytes.toString()};}
}
function fixture(origin=1000000){
  const root=new Folder(),messages:Record<string,unknown>[]=[],locks=new Set<string>();let at=1000,storageGate:Promise<void>|null=null;
  const context=vm.createContext({crypto:webcrypto,TextEncoder,Uint8Array,ArrayBuffer,Set,Map,JSON,Promise,
    performance:{timeOrigin:origin,now:()=>at},navigator:{storage:{getDirectory:async()=>{if(storageGate)await storageGate;return root;}},
      locks:{request:async(name:string,_options:unknown,callback:(lock:unknown)=>Promise<void>)=>{
        if(locks.has(name))return callback(null);
        locks.add(name);try{await callback({name});}finally{locks.delete(name);}
      }}},
    postMessage:(m:Record<string,unknown>)=>messages.push(m),self:{}});
  vm.runInContext(fs.readFileSync(path.join(process.cwd(),'public/teaching-recorder.worker.js'),'utf8'),context);
  vm.runInContext('transformer={sendKeyFrameRequest:()=>Promise.resolve()}',context);
  const config={id:'a'.repeat(32),storage_scope:'b'.repeat(32),width:960,height:540};
  const frame=(ticks:number,key=true,metadata:Record<string,unknown>={})=>context.frame({type:key?'key':'delta',data:Uint8Array.from(key?[0,0,0,1,103,66,0,31,0,0,1,104,1,0,0,1,101,9]:[0,0,0,1,65,9]).buffer,
    getMetadata:()=>({mimeType:'video/H264',width:960,height:540,rtpTimestamp:ticks,synchronizationSource:777,...metadata})});
  const folder=async()=>root.getDirectoryHandle('sphere-teaching-'+config.storage_scope).then(f=>f.getDirectoryHandle(config.id));
  return{root,messages,context,config,frame,folder,advance:()=>{at+=200;},setNow:(value:number)=>{at=value;},
    holdStorage:()=>{let release!:()=>void;storageGate=new Promise<void>(resolve=>{release=resolve;});return release;}};
}

test('message arrival clocks enclose early page heartbeat while OPFS and command execution are delayed',async()=>{
  const f=fixture(),release=f.holdStorage();
  // A page and its worker have distinct timeOrigin values. Their epoch-relative
  // performance timestamps describe the same clock, but emission != receipt.
  let pageNow=1495;
  const page=vm.createContext({performance:{timeOrigin:999500,now:()=>pageNow}});
  const sourceStamp=()=>vm.runInContext('performance.timeOrigin+performance.now()',page) as number;
  const event={sequence:1,gesture:0,action:4,pointer_id:-1};
  f.context.self.onmessage({data:{type:'arm',config:{...f.config,input_capture:'external_unobserved'}}});
  await Promise.resolve();
  const submitted={...event,stage:'submitted',at_ms:sourceStamp()};
  f.setNow(1001);f.context.self.onmessage({data:{type:'input',event:submitted}});
  pageNow=1498;
  const receipt={...event,stage:'receipt',at_ms:sourceStamp(),outcome:'alive',device_uptime_ms:618759230};
  f.setNow(1002);f.context.self.onmessage({data:{type:'input',event:receipt}});
  pageNow=1503;
  const closed={stage:'closed',at_ms:sourceStamp(),sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed',device_uptime_ms:618759243,cancelled_pointers:[]};
  f.setNow(1004);f.context.self.onmessage({data:{type:'input',event:closed}});
  f.setNow(1020);release();await vm.runInContext('command',f.context);
  f.setNow(1030);f.frame(90000);f.setNow(1060);f.frame(93000,false);
  f.setNow(1070);f.context.self.onmessage({data:{type:'stop',confirmed:true}});
  await vm.runInContext('command',f.context);
  const dir=await f.folder(),manifest=JSON.parse((dir.entries.get('manifest.json') as MemoryFile).data.toString());
  const rows=(dir.entries.get('inputs.jsonl') as MemoryFile).data.toString().trim().split('\n').map(line=>JSON.parse(line));
  const frames=(dir.entries.get('frames.jsonl') as MemoryFile).data.toString().trim().split('\n').map(line=>JSON.parse(line));
  expect(manifest).toMatchObject({complete:true,started_at_ms:1001000,worker_ready_at_ms:1001020,finalized_at_ms:1001070});
  expect(manifest.clock).toMatchObject({input:'worker_message_received_performance_timeOrigin_plus_now',source_input:'page_performance_timeOrigin_plus_now'});
  expect(rows.map(row=>row.at_ms)).toEqual([1001001,1001002,1001004]);
  expect(rows.map(row=>row.source_at_ms)).toEqual([submitted.at_ms,receipt.at_ms,closed.at_ms]);
  expect(rows[0].source_at_ms).toBeLessThan(manifest.started_at_ms);
  expect(rows.every(row=>row.at_ms>=manifest.started_at_ms&&row.at_ms<=manifest.finalized_at_ms)).toBe(true);
  expect(frames.map(row=>row.worker_observed_at_ms)).toEqual([1001030,1001060]);
  expect(frames.map(row=>row.relative_ticks_90k)).toEqual([0,3000]);
  expect(rows[1].device_uptime_ms).toBe(618759230);
  expect(submitted).not.toHaveProperty('source_at_ms');
  expect(dir.entries.has('COMPLETE')).toBe(true);
});

test('keeps the last two complete original-video captures without changing the recording library',async()=>{
  const f=fixture();
  const library=await f.root.getDirectoryHandle('sphere-teaching-'+f.config.storage_scope,{create:true});
  await library.getDirectoryHandle(f.config.id,{create:true});
  const command=async(data:Record<string,unknown>)=>{
    f.context.self.onmessage({data});await vm.runInContext('command',f.context);
  };
  const config={scope:f.config.storage_scope,clip:f.config.id,job:'c'.repeat(32),captureEpoch:'9dbe1c39-9d2a-4d8c-93f8-12982d6f0202',geometrySha256:'e'.repeat(64),width:960,height:540};
  const successfulIds=['1','2','3'].map(value=>value.repeat(32));
  for(const [index,id] of successfulIds.entries()){
    await command({type:'diagnostic_video_start',config:{...config,id,beganAtMs:1001000+index*200}});
    f.frame(100,false); // no IDR yet
    f.frame(90000);f.advance();f.frame(108000,false);
    await command({type:'diagnostic_video_stop',id,reason:'walk_manual_stop'});
    expect(f.messages.at(-1)).toMatchObject({type:'diagnostic_video_finalized',id,saved:true,retentionConfirmed:true,endedEarly:null});
  }
  const archive=await f.root.getDirectoryHandle('sphere-vehicle-video-'+config.scope);
  expect([...archive.entries.keys()]).toEqual(successfulIds.slice(1));
  const latest=await archive.getDirectoryHandle(successfulIds[2]);
  const marker=JSON.parse((latest.entries.get('COMPLETE') as MemoryFile).data.toString());
  const index=(latest.entries.get('frames.jsonl') as MemoryFile).data.toString().trim().split('\n').map(line=>JSON.parse(line));
  expect(marker).toMatchObject({schema:'sphere-vehicle-video-v1',frames:2,clip:config.clip,job:config.job,geometrySha256:config.geometrySha256,durationTicks90k:18000});
  expect(marker.indexSha256).toMatch(/^[0-9a-f]{64}$/);
  expect(index[0]).toMatchObject({rtp_timestamp:90000,seekable:true});
  expect((latest.entries.get('video.h264') as MemoryFile).data).toEqual(Buffer.from([0,0,0,1,103,66,0,31,0,0,1,104,1,0,0,1,101,9,0,0,0,1,65,9]));
  expect(latest.entries.has('inputs.jsonl')).toBe(false);
  expect([...library.entries.keys()]).toEqual([f.config.id]);
  // No usable frame in the next run leaves the previous pair in place.
  const emptyId='4'.repeat(32);
  await command({type:'diagnostic_video_start',config:{...config,id:emptyId,beganAtMs:1001800}});
  await command({type:'diagnostic_video_stop',id:emptyId});
  expect(f.messages.at(-1)).toMatchObject({type:'diagnostic_video_finalized',id:emptyId,saved:false});
  expect([...archive.entries.keys()]).toEqual(successfulIds.slice(1));
  expect(f.messages.some(message=>['failed','limit_reached','recording'].includes(String(message.type)))).toBe(false);
});

test.each(['source','worker-input','worker-frame','worker-finalize'])('never clamps a %s clock rollback into a completed recording',async kind=>{
  const f=fixture();await f.context.arm(f.config);
  f.setNow(1002);f.frame(90000);
  const event={sequence:1,gesture:0,action:4,pointer_id:-1};
  f.setNow(1003);f.context.input({...event,stage:'submitted',at_ms:1001003});
  if(kind==='worker-frame') {f.setNow(1001);f.frame(93000,false);}
  f.setNow(kind==='worker-input'?1002:1004);
  f.context.input({...event,stage:'receipt',at_ms:kind==='source'?1001002:1001004,outcome:'alive',device_uptime_ms:1000});
  f.setNow(1005);f.context.input({stage:'closed',at_ms:1001005,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
  if(kind==='worker-finalize')f.setNow(1001);
  await f.context.stop(true,null);
  const dir=await f.folder(),manifest=JSON.parse((dir.entries.get('manifest.json') as MemoryFile).data.toString());
  expect(manifest.complete).toBe(false);expect(manifest.failure).toBe('browser_clock_regressed');
  expect(dir.entries.has('COMPLETE')).toBe(false);
  if(kind==='source'||kind==='worker-input') {
    const rows=(dir.entries.get('inputs.jsonl') as MemoryFile).data.toString().trim().split('\n').map(line=>JSON.parse(line));
    expect(rows.some(row=>row.stage==='receipt')).toBe(false);
  }
});

test('Date wall-clock rollback does not change the declared performance recording clock',async()=>{
  const f=fixture();await f.context.arm(f.config);f.frame(90000);
  vm.runInContext('Date.now=()=>-100000',f.context);
  f.setNow(1200);f.frame(108000,false);
  f.context.input({stage:'closed',at_ms:1001200,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
  await f.context.stop(true,null);
  const manifest=JSON.parse(((await f.folder()).entries.get('manifest.json') as MemoryFile).data.toString());
  expect(manifest.complete).toBe(true);
  expect(manifest).toMatchObject({started_at_ms:1001000,finalized_at_ms:1001200});
});

test('external capture heartbeat is emitted only while encoded frames arrive',async()=>{
  const f=fixture();
  f.context.self.onmessage({data:{type:'external_capture',enabled:true}});
  await vm.runInContext('command',f.context);
  f.frame(90000);expect(f.messages.filter(m=>m.type==='encoded_heartbeat')).toHaveLength(1);
  f.frame(93000,false);expect(f.messages.filter(m=>m.type==='encoded_heartbeat')).toHaveLength(1);
  f.advance();f.frame(95000,false,{mimeType:'video/VP8'});expect(f.messages.filter(m=>m.type==='encoded_heartbeat')).toHaveLength(1);
  f.frame(96000,false);expect(f.messages.filter(m=>m.type==='encoded_heartbeat')).toHaveLength(2);
  f.context.self.onmessage({data:{type:'external_capture',enabled:false}});
  await vm.runInContext('command',f.context);
  f.advance();f.frame(99000,false);expect(f.messages.filter(m=>m.type==='encoded_heartbeat')).toHaveLength(3);
  expect(f.messages.filter(m=>m.type==='encoded_heartbeat').at(-1)).toMatchObject({receivedAtMs:1001400});
});

test('twenty existing videos do not prevent a new video; library scans remain bounded at 100',async()=>{
  const f=fixture(),library=await f.root.getDirectoryHandle('sphere-teaching-'+f.config.storage_scope,{create:true});
  for(let n=1;n<=20;n++)await library.getDirectoryHandle(n.toString(16).padStart(32,'0'),{create:true});
  await f.context.arm({...f.config,input_capture:'external_unobserved'});
  expect(f.messages).toContainEqual(expect.objectContaining({type:'armed'}));
  const full=fixture(),folder=await full.root.getDirectoryHandle('sphere-teaching-'+full.config.storage_scope,{create:true});
  for(let n=1;n<=100;n++)await folder.getDirectoryHandle(n.toString(16).padStart(32,'0'),{create:true});
  full.context.self.onmessage({data:{type:'arm',config:full.config}});await vm.runInContext('command',full.context);
  expect(full.messages).toContainEqual({type:'failed',reason:'recording_library_limit'});
  expect(folder.entries.size).toBe(100);
});

test('external video keeps its explicit provenance after early confirmed input release',async()=>{
  const f=fixture();await f.context.arm({...f.config,input_capture:'external_unobserved'});
  f.context.input({stage:'closed',at_ms:1001000,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
  f.frame(90000);f.advance();f.frame(108000,false);
  await f.context.stop(true,null);const dir=await f.folder();
  const manifest=JSON.parse((dir.entries.get('manifest.json') as MemoryFile).data.toString());
  expect(manifest.complete).toBe(true);expect(manifest.release_confirmed).toBe(true);
  expect(manifest.config.input_capture).toBe('external_unobserved');expect(manifest.frames).toBe(2);
  expect((dir.entries.get('inputs.jsonl') as MemoryFile).data.toString()).not.toContain('"stage":"submitted"');
});
test('does not save frames before explicit start; stores original H264 and 90k clock with completion proof',async()=>{
  const f=fixture();f.frame(1);expect(f.root.entries.size).toBe(0);await f.context.arm(f.config);
  f.frame(123,false);expect(f.messages.some(m=>m.type==='recording')).toBe(false);
  f.frame(90000);f.advance();f.frame(108000,false);
  f.context.input({stage:'closed',at_ms:1001000,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
  await f.context.stop(true,null);const dir=await f.folder();expect(dir.entries.has('COMPLETE')).toBe(true);
  const lines=(dir.entries.get('frames.jsonl') as MemoryFile).data.toString().trim().split('\n').map(l=>JSON.parse(l));
  expect(lines.map(l=>l.relative_ticks_90k)).toEqual([0,18000]);expect(lines[0].sha256).toMatch(/^[0-9a-f]{64}$/);
  expect((dir.entries.get('video.h264') as MemoryFile).data.length).toBe(lines.reduce((n,l)=>n+l.bytes,0));
});

test('quality uses actual RTP cadence, never the declared target or synthetic frame duplication',async()=>{
  const f=fixture();await f.context.arm({...f.config,target_fps:30});
  for(let i=0;i<41;i++){f.frame(90000+i*9000,i===0);await vm.runInContext('recording.tail',f.context);}
  f.context.input({stage:'closed',at_ms:1001000,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
  await f.context.stop(true,null);const dir=await f.folder();
  const manifest=JSON.parse((dir.entries.get('manifest.json') as MemoryFile).data.toString());
  expect(manifest.complete).toBe(true);expect(manifest.capture_quality.received_encoded_fps).toBe(10);
  expect(manifest.capture_quality.cadence_30fps_confirmed).toBe(false);
  expect(manifest.capture_quality.max_media_gap_ms).toBe(100);
  expect(manifest.capture_quality.transcoding).toBe(false);expect(manifest.capture_quality.synthetic_frames).toBe(0);
  expect(manifest.capture_quality.disk_queue_high_water_bytes).toBeGreaterThan(0);
});
test('a good average cannot hide an irregular interval in the received RTP stream',async()=>{
  const f=fixture();await f.context.arm({...f.config,target_fps:30});
  let ticks=90000;f.frame(ticks);
  for(let i=0;i<120;i++){ticks+=i===45?6000:2975;f.frame(ticks,false);await vm.runInContext('recording.tail',f.context);}
  f.context.input({stage:'closed',at_ms:1001000,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
  await f.context.stop(true,null);const manifest=JSON.parse(((await f.folder()).entries.get('manifest.json') as MemoryFile).data.toString());
  const quality=manifest.capture_quality;
  expect(quality.received_encoded_fps).toBeGreaterThan(29.5);
  expect(quality.cadence_policy).toBe('rtp-30fps-gap50-v1');
  expect(quality.gaps_over_50ms).toBe(1);expect(quality.gaps_over_100ms).toBe(0);
  expect(quality.p95_media_gap_ms).toBe(34);expect(quality.cadence_30fps_confirmed).toBe(false);
});
test('steady received 30 FPS passes the bounded RTP cadence check',async()=>{
  const f=fixture();await f.context.arm({...f.config,target_fps:30});
  for(let i=0;i<100;i++){f.frame(90000+i*3000,i===0);await vm.runInContext('recording.tail',f.context);}
  f.context.input({stage:'closed',at_ms:1001000,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
  await f.context.stop(true,null);const manifest=JSON.parse(((await f.folder()).entries.get('manifest.json') as MemoryFile).data.toString());
  expect(manifest.capture_quality.cadence_30fps_confirmed).toBe(true);
  expect(manifest.capture_quality.gaps_over_50ms).toBe(0);expect(manifest.capture_quality.p95_media_gap_ms).toBe(34);
});
test('60 FPS is measured independently and does not follow the requested target',async()=>{
  const f=fixture();await f.context.arm({...f.config,target_fps:60});
  for(let i=0;i<181;i++){f.frame(90000+i*1500,i===0);await vm.runInContext('recording.tail',f.context);}
  f.context.input({stage:'closed',at_ms:1001000,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
  await f.context.stop(true,null);const manifest=JSON.parse(((await f.folder()).entries.get('manifest.json') as MemoryFile).data.toString());
  expect(manifest.capture_quality.received_encoded_fps).toBe(60);
  expect(manifest.capture_quality.gaps_over_25ms).toBe(0);
  expect(manifest.capture_quality.cadence_60fps_confirmed).toBe(true);
});
test.each(['pending','unknown','clock'])('never writes COMPLETE after %s uncertainty',async mode=>{
  const f=fixture();await f.context.arm(f.config);f.frame(90000);
  if(mode==='pending')f.context.input({stage:'submitted',at_ms:1001000,sequence:1,gesture:1,action:0,pointer_id:0,x:100,y:300});
  if(mode==='clock')f.frame(89999,false);
  f.context.input({stage:'closed',at_ms:1001000,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:mode==='unknown'?'unknown':'closed'});
  await f.context.stop(mode!=='unknown',null);const dir=await f.folder();expect(dir.entries.has('COMPLETE')).toBe(false);
  expect(JSON.parse((dir.entries.get('manifest.json') as MemoryFile).data.toString()).complete).toBe(false);
});
test('bounded disk queue refuses a burst and never marks the truncated file complete',async()=>{
  const f=fixture();await f.context.arm(f.config);for(let n=0;n<40;n++)f.frame(90000+n*3000);
  expect(f.messages).toContainEqual({type:'failed',reason:'disk_queue_budget'});
  await f.context.stop(true,null);expect((await f.folder()).entries.has('COMPLETE')).toBe(false);
});
test('existing recording cannot be reopened or overwritten',async()=>{
  const f=fixture();await f.context.arm(f.config);await expect(f.context.arm(f.config)).rejects.toThrow('recorder_already_used');
});
test('heartbeat crossing first IDR keeps its submission and matching receipt in the same journal',async()=>{
  const f=fixture();await f.context.arm(f.config);
  const event={at_ms:1001000,sequence:1,gesture:0,action:4,pointer_id:-1};
  f.context.input({...event,stage:'submitted'});f.frame(90000);
  f.context.input({...event,stage:'receipt',outcome:'alive',device_uptime_ms:1000});
  f.context.input({stage:'closed',at_ms:1001000,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
  await f.context.stop(true,null);expect((await f.folder()).entries.has('COMPLETE')).toBe(true);
});
test('Chromium zero delta dimensions inherit bound IDR but a changed source or explicit geometry is rejected',async()=>{
  for(const metadata of [{width:0,height:0},{width:480,height:270},{synchronizationSource:778}]) {
    const f=fixture();await f.context.arm(f.config);f.frame(90000);f.frame(93000,false,metadata);
    f.context.input({stage:'closed',at_ms:1001000,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
    await f.context.stop(true,null);const manifest=JSON.parse(((await f.folder()).entries.get('manifest.json') as MemoryFile).data.toString());
    expect(manifest.complete).toBe(metadata.width===0);expect(manifest.release_confirmed).toBe(true);
  }
});
test('starting mid-stream skips zero-geometry deltas until a real matching SPS PPS IDR arrives',async()=>{
  const f=fixture();await f.context.arm(f.config);f.frame(87000,false,{width:0,height:0});f.frame(90000);
  f.context.input({stage:'closed',at_ms:1001000,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
  await f.context.stop(true,null);const manifest=JSON.parse(((await f.folder()).entries.get('manifest.json') as MemoryFile).data.toString());
  expect(manifest.complete).toBe(true);expect(manifest.frames).toBe(1);
});

test('chosen duration limit stops intake and still completes after confirmed native release',async()=>{
  const f=fixture();await f.context.arm({...f.config,max_duration_ms:1000});f.frame(90000);
  for(let i=0;i<6;i++)f.advance();f.frame(93000,false);
  expect(f.messages).toContainEqual({type:'limit_reached',reason:'duration_or_frame_limit'});
  expect(f.messages.some(m=>m.type==='failed')).toBe(false);
  f.context.input({stage:'closed',at_ms:1002200,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
  await f.context.stop(true,null);const dir=await f.folder();expect(dir.entries.has('COMPLETE')).toBe(true);
  const manifest=JSON.parse((dir.entries.get('manifest.json') as MemoryFile).data.toString());
  expect(manifest.ended_at_limit).toBe('duration_or_frame_limit');expect(manifest.frames).toBe(1);
});

test('configured ten-minute budget accepts frames beyond the old two-minute cutoff',async()=>{
  const f=fixture();await f.context.arm({...f.config,max_duration_ms:600000,max_frames:36000,max_bytes:2*1024**3});f.frame(90000);
  for(let i=0;i<605;i++)f.advance();f.frame(93000,false);
  f.context.input({stage:'closed',at_ms:1122000,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
  await f.context.stop(true,null);const manifest=JSON.parse(((await f.folder()).entries.get('manifest.json') as MemoryFile).data.toString());
  expect(manifest.complete).toBe(true);expect(manifest.frames).toBe(2);expect(manifest.media_duration_ticks_90k).toBe(3000);
});

test.each([{max_duration_ms:600001},{max_bytes:2*1024**3+1},{max_frames:36001}])('rejects unbounded recording budget %p before writing files',async budget=>{
  const f=fixture();await expect(f.context.arm({...f.config,...budget})).rejects.toThrow('invalid_recording_budget');expect(f.root.entries.size).toBe(0);
});
