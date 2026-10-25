/** @jest-environment node */
import { webcrypto } from 'node:crypto';
import { parseTeachingLabel, renameTeachingLabel, seekTeachingSecond, teachingTitle } from '@/src/features/stream/teachingMetadata';
Object.defineProperty(globalThis,'crypto',{configurable:true,value:webcrypto});
const id='a'.repeat(32),manifestSha='b'.repeat(64);
const encoded=(value:unknown)=>new TextEncoder().encode(JSON.stringify(value));

test('blank titles are readable and distinguish recordings made in the same second',()=>{
  const at=new Date(2026,9,26,12,34,56).getTime();
  expect(teachingTitle('',id,at)).toBe('Маршрут 26.10.2026 12:34:56 · aaaaaaaa');
  expect(teachingTitle('Маршрут','c'.repeat(32),at)).not.toBe(teachingTitle('',id,at));
  expect(teachingTitle(' Маршрут 011321 ',id,at)).toBe('Маршрут 011321');
});

test('time navigation uses media timestamps across variable cadence and clamps to endpoints',()=>{
  const rows=[0,9000,31500,171000].map(relative_ticks_90k=>({relative_ticks_90k}));
  expect(seekTeachingSecond(rows,1,1)).toBe(3);
  expect(seekTeachingSecond(rows,3,-1)).toBe(2);
  expect(seekTeachingSecond(rows,0,-1)).toBe(0);
  expect(seekTeachingSecond(rows,3,1)).toBe(3);
});

test('a label from another clip or manifest is not accepted as the selected route name',()=>{
  const label={schema:'sphere-teaching-label-v1',id,manifest_sha256:manifestSha,title:'Переулок',updated_at_ms:42};
  expect(parseTeachingLabel(JSON.stringify(label),id,manifestSha)).toBe('Переулок');
  expect(parseTeachingLabel(JSON.stringify(label),'c'.repeat(32),manifestSha)).toBeNull();
  expect(parseTeachingLabel(JSON.stringify(label),id,'d'.repeat(64))).toBeNull();
  expect(parseTeachingLabel(JSON.stringify({...label,title:'x\ncontrol'}),id,manifestSha)).toBeNull();
});

test('rename only writes a sidecar and leaves a sealed manifest and completion marker untouched',async()=>{
  const manifest=encoded({schema:'sphere-browser-teaching-v2',id,config:{title:'Первое имя'}});
  const writes=new Map<string,ArrayBuffer>();
  const getFileHandle=jest.fn(async(name:string,options?:{create?:boolean})=>{
    if(name==='manifest.json')return {getFile:async()=>new File([Uint8Array.from(manifest).buffer],name)};
    expect(name).toBe('label.json');expect(options).toEqual({create:true});
    return {createWritable:async()=>({write:async(raw:string)=>{writes.set(name,new TextEncoder().encode(raw).buffer);},close:async()=>{},abort:async()=>{}})};
  });
  await renameTeachingLabel({getFileHandle} as unknown as FileSystemDirectoryHandle,id,'Новое имя');
  expect([...writes.keys()]).toEqual(['label.json']);
  const hash=Buffer.from(await webcrypto.subtle.digest('SHA-256',Uint8Array.from(manifest).buffer)).toString('hex');
  expect(parseTeachingLabel(new TextDecoder().decode(writes.get('label.json')!),id,hash)).toBe('Новое имя');
  expect(getFileHandle).not.toHaveBeenCalledWith('COMPLETE',expect.anything());
});
