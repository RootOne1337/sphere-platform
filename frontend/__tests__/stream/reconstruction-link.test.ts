/** @jest-environment node */
import {readReconstructionLink,saveReconstructionLink} from '@/src/features/stream/reconstructionLink';
const clip='a'.repeat(32),job={id:'b'.repeat(32),key:'c'.repeat(64)};
function memoryFolder(){
  const files=new Map<string,string>([['video.h264','original-video']]);
  const folder={getFileHandle:async(name:string,options?:{create?:boolean})=>{
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
  expect([...files.keys()]).toEqual(['video.h264','reconstruction-link.json']);
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
