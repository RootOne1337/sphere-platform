/** @jest-environment node */
import vm from 'node:vm';
import fs from 'node:fs';
import path from 'node:path';
import { webcrypto } from 'node:crypto';
class Folder {
  entries=new Map<string,Folder|MemoryFile>();
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
  async getFile(){const bytes=this.data;return{size:bytes.length,arrayBuffer:async()=>Uint8Array.from(bytes).buffer};}
}
function fixture(){
  const root=new Folder(),messages:Record<string,unknown>[]=[];let at=1000;
  const context=vm.createContext({crypto:webcrypto,TextEncoder,Uint8Array,ArrayBuffer,Set,Map,JSON,Promise,
    performance:{timeOrigin:1000000,now:()=>at},navigator:{storage:{getDirectory:async()=>root}},
    postMessage:(m:Record<string,unknown>)=>messages.push(m),self:{}});
  vm.runInContext(fs.readFileSync(path.join(process.cwd(),'public/teaching-recorder.worker.js'),'utf8'),context);
  vm.runInContext('transformer={sendKeyFrameRequest:()=>Promise.resolve()}',context);
  const config={id:'a'.repeat(32),storage_scope:'b'.repeat(32),width:960,height:540};
  const frame=(ticks:number,key=true,metadata:Record<string,unknown>={})=>context.frame({type:key?'key':'delta',data:Uint8Array.from(key?[0,0,0,1,103,66,0,31,0,0,1,104,1,0,0,1,101,9]:[0,0,0,1,65,9]).buffer,
    getMetadata:()=>({mimeType:'video/H264',width:960,height:540,rtpTimestamp:ticks,synchronizationSource:777,...metadata})});
  const folder=async()=>root.getDirectoryHandle('sphere-teaching-'+config.storage_scope).then(f=>f.getDirectoryHandle(config.id));
  return{root,messages,context,config,frame,folder,advance:()=>{at+=200;}};
}
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
