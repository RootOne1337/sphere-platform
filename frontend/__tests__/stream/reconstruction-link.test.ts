/** @jest-environment node */
import {listReconstructionLinks,readReconstructionLink,saveReconstructionLink} from '@/src/features/stream/reconstructionLink';
const clip='a'.repeat(32),job={id:'b'.repeat(32),key:'c'.repeat(64)};
beforeEach(()=>{Object.defineProperty(globalThis,'navigator',{configurable:true,value:{locks:{request:async(_name:string,callback:()=>Promise<void>)=>callback()}}});});
function memoryFolder(){
  const files=new Map<string,string>([['video.h264','original-video']]);
  const folder={async *entries(){for(const name of files.keys())yield [name,{}];},getFileHandle:async(name:string,options?:{create?:boolean})=>{
    if(!files.has(name)&&!options?.create)throw new DOMException('Missing','NotFoundError');
    return {getFile:async()=>new File([files.get(name)??''],name),createWritable:async()=>{
      let pending='';return {write:async(value:string)=>{pending=value;},close:async()=>{files.set(name,pending);},abort:async()=>{}};
    }};
  }} as unknown as FileSystemDirectoryHandle;
  return {folder,files};
}
test('a saved scene capability survives a new component session without changing raw video',async()=>{
  const {folder,files}=memoryFolder();expect(await readReconstructionLink(folder,clip)).toBeNull();
  await saveReconstructionLink(folder,clip,job);
  expect(await readReconstructionLink(folder,clip)).toEqual(job);
  expect(files.get('video.h264')).toBe('original-video');
  expect([...files.keys()]).toEqual(['video.h264',`reconstruction-attempt-${job.id}.json`,'reconstruction-link.json']);
});
test('a legacy link and a new attempt remain selectable after switching back',async()=>{
  const {folder,files}=memoryFolder(),next={id:'e'.repeat(32),key:'f'.repeat(64)};
  files.set('reconstruction-link.json',JSON.stringify({schema:'sphere-local-reconstruction-link-v1',clip,job}));
  await saveReconstructionLink(folder,clip,next);
  expect(await readReconstructionLink(folder,clip)).toEqual(next);
  expect(await listReconstructionLinks(folder,clip)).toEqual([job,next]);
  await saveReconstructionLink(folder,clip,job);
  expect(await readReconstructionLink(folder,clip)).toEqual(job);
  expect(await listReconstructionLinks(folder,clip)).toEqual([job,next]);
  expect(files.get('video.h264')).toBe('original-video');
});
test('a conflicting key does not replace either the current or archived attempt',async()=>{
  const {folder,files}=memoryFolder();await saveReconstructionLink(folder,clip,job);
  const before=new Map(files);
  await expect(saveReconstructionLink(folder,clip,{...job,key:'f'.repeat(64)})).rejects.toThrow('reconstruction_link_conflict');
  expect(files).toEqual(before);
});
test('without cross-tab locking a different job cannot replace a legacy current link',async()=>{
  const {folder,files}=memoryFolder();
  files.set('reconstruction-link.json',JSON.stringify({schema:'sphere-local-reconstruction-link-v1',clip,job}));
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{}});
  const before=new Map(files);
  await expect(saveReconstructionLink(folder,clip,{id:'e'.repeat(32),key:'f'.repeat(64)})).rejects.toThrow('reconstruction_lock_unavailable');
  expect(files).toEqual(before);
});
test('an attempt filename and its capability must have the same identifier',async()=>{
  const {folder,files}=memoryFolder();
  files.set(`reconstruction-attempt-${'e'.repeat(32)}.json`,JSON.stringify({schema:'sphere-local-reconstruction-link-v1',clip,job}));
  await expect(listReconstructionLinks(folder,clip)).rejects.toThrow('reconstruction_link_binding');
});
test('an interrupted first archive write can be completed without touching the legacy link',async()=>{
  const {folder,files}=memoryFolder();
  files.set('reconstruction-link.json',JSON.stringify({schema:'sphere-local-reconstruction-link-v1',clip,job}));
  files.set(`reconstruction-attempt-${job.id}.json`,'');
  expect(await listReconstructionLinks(folder,clip)).toEqual([job]);
  await saveReconstructionLink(folder,clip,job);
  expect(await listReconstructionLinks(folder,clip)).toEqual([job]);
  expect(await readReconstructionLink(folder,clip)).toEqual(job);
  expect(files.get('video.h264')).toBe('original-video');
});
test('a missing current link can be recovered from a committed attempt',async()=>{
  const {folder,files}=memoryFolder();await saveReconstructionLink(folder,clip,job);
  files.set('reconstruction-link.json','');
  expect(await readReconstructionLink(folder,clip)).toBeNull();
  expect(await listReconstructionLinks(folder,clip)).toEqual([job]);
  await saveReconstructionLink(folder,clip,job);
  expect(await readReconstructionLink(folder,clip)).toEqual(job);
});
test('a link cannot be restored for another clip',async()=>{
  const {folder}=memoryFolder();await saveReconstructionLink(folder,clip,job);
  await expect(readReconstructionLink(folder,'d'.repeat(32))).rejects.toThrow('reconstruction_link_binding');
});
test('corrupt or oversized metadata cannot become a new job',async()=>{
  const {folder,files}=memoryFolder();files.set('reconstruction-link.json','x'.repeat(2049));
  await expect(readReconstructionLink(folder,clip)).rejects.toThrow('reconstruction_link_quota');
  files.set('reconstruction-link.json',JSON.stringify({schema:'sphere-local-reconstruction-link-v1',clip,job:{...job,key:'short'}}));
  await expect(readReconstructionLink(folder,clip)).rejects.toThrow('reconstruction_link_binding');
});
