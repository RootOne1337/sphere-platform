/** @jest-environment node */
import { webcrypto } from 'node:crypto';
import { exportTeachingFolder, type ExportProgress } from '@/src/features/stream/teachingExport';
Object.defineProperty(globalThis,'crypto',{configurable:true,value:webcrypto});
const encode=(value:unknown)=>new TextEncoder().encode(typeof value==='string'?value:JSON.stringify(value));
const digest=async(data:Uint8Array)=>Buffer.from(await webcrypto.subtle.digest('SHA-256',Uint8Array.from(data).buffer)).toString('hex');
class MemoryFile {
  data:Uint8Array;noWholeRead=false;
  constructor(public name:string,data:Uint8Array,private log:string[],private corrupt=false){this.data=data;}
  async getFile(){const file=new File([Uint8Array.from(this.data).buffer],this.name);if(this.noWholeRead)file.arrayBuffer=async()=>{throw Error('video_must_be_read_in_slices');};return file;}
  async createWritable(){const chunks:Uint8Array[]=[];return{write:async(data:ArrayBuffer)=>{chunks.push(new Uint8Array(data));},abort:async()=>{},close:async()=>{
    this.data=new Uint8Array(chunks.reduce((n,c)=>n+c.length,0));let at=0;for(const chunk of chunks){this.data.set(chunk,at);at+=chunk.length;}
    if(this.corrupt&&this.data.length)this.data[0]^=255;this.log.push(this.name);
  }};}
}
class Folder {
  folders=new Map<string,Folder>();files=new Map<string,MemoryFile>();log:string[]=[];
  constructor(private corruptVideo=false){}
  async getDirectoryHandle(name:string,options?:{create?:boolean}):Promise<Folder>{
    if(!this.folders.has(name)){if(!options?.create)throw Object.assign(Error(),{name:'NotFoundError'});this.folders.set(name,new Folder(this.corruptVideo));}
    return this.folders.get(name)!;
  }
  async getFileHandle(name:string,options?:{create?:boolean}){
    if(!this.files.has(name)){if(!options?.create)throw Object.assign(Error(),{name:'NotFoundError'});this.files.set(name,new MemoryFile(name,new Uint8Array(),this.log,this.corruptVideo&&name==='video.h264'));}
    return this.files.get(name)!;
  }
}
const handle=(folder:Folder)=>folder as unknown as FileSystemDirectoryHandle;
async function fixture(corruptDestination=false){
  const id='a'.repeat(32),exportId='b'.repeat(32),source=new Folder(),root=new Folder(corruptDestination);
  const units=[new Uint8Array([1,2,3]),new Uint8Array([4,5])],rows=[];let offset=0;
  for(let index=0;index<units.length;index++){const unit=units[index];rows.push({index,offset,bytes:unit.length,sha256:await digest(unit)});offset+=unit.length;}
  const index=encode(rows.map((row:unknown)=>JSON.stringify(row)).join('\n'));
  const input=encode(JSON.stringify({stage:'closed',outcome:'closed'})+'\n');
  const manifest=encode({schema:'sphere-browser-teaching-v2',id,frames:2,complete:true,release_confirmed:true,files:{
    'video.h264':{bytes:5},'frames.jsonl':{bytes:index.length,sha256:await digest(index)},'inputs.jsonl':{bytes:input.length,sha256:await digest(input)},
  }});
  const payloads:Record<string,Uint8Array>={'video.h264':new Uint8Array([1,2,3,4,5]),'frames.jsonl':index,'inputs.jsonl':input,'manifest.json':manifest,'COMPLETE':encode({manifest_sha256:await digest(manifest)})};
  for(const [name,data] of Object.entries(payloads))source.files.set(name,new MemoryFile(name,data,source.log));
  source.files.get('video.h264')!.noWholeRead=true;
  const progress:ExportProgress[]=[];
  return{id,exportId,source,root,progress,run:(signal?:AbortSignal)=>exportTeachingFolder(handle(source),id,async()=>handle(root),p=>progress.push(p),signal,exportId)};
}
test('completed bundle is streamed and re-read, COMPLETE is written last and the source remains intact',async()=>{
  const f=await fixture(),result=await f.run();const target=f.root.folders.get(result.folder)!;
  expect(result.frames).toBe(2);expect(target.log.at(-1)).toBe('COMPLETE');expect(f.progress.at(-1)?.stage).toBe('complete');
  for(const [name,file] of f.source.files)expect(target.files.get(name)?.data).toEqual(file.data);
  expect(f.source.log).toEqual([]);
});
test('a corrupted saved video is rejected before any completion marker is written',async()=>{
  const f=await fixture(true);await expect(f.run()).rejects.toThrow('Сохранённый видеокадр');
  const target=[...f.root.folders.values()][0];expect(target.files.has('COMPLETE')).toBe(false);expect(f.source.files.has('COMPLETE')).toBe(true);
});
test('an existing destination is never overwritten',async()=>{
  const f=await fixture();const target=new Folder();f.root.folders.set(`sphere-route-${f.id}-${f.exportId}`,target);
  await expect(f.run()).rejects.toThrow('уже существует');expect(target.files.size).toBe(0);
});
test('cancelling export before the chooser touches no files',async()=>{
  const f=await fixture(),abort=new AbortController();abort.abort();await expect(f.run(abort.signal)).rejects.toMatchObject({name:'AbortError'});
  expect(f.root.folders.size).toBe(0);expect(f.source.log).toEqual([]);
});

test('cancel during copying leaves the source and an unsealed destination',async()=>{
  const f=await fixture(),abort=new AbortController();
  await expect(exportTeachingFolder(handle(f.source),f.id,async()=>handle(f.root),p=>{if(p.stage==='copy')abort.abort();},abort.signal,f.exportId)).rejects.toMatchObject({name:'AbortError'});
  expect([...f.root.folders.values()][0].files.has('COMPLETE')).toBe(false);expect(f.source.files.has('COMPLETE')).toBe(true);
});
