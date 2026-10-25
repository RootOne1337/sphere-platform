import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { webcrypto } from 'node:crypto';
import { TextDecoder, TextEncoder } from 'node:util';
import { TeachingReview } from '@/src/features/stream/TeachingReview';
jest.mock('@/src/features/stream/TeachingReconstruction',()=>({TeachingReconstruction:()=>null}));

const id='a'.repeat(32),scope='b'.repeat(32);
const encode=(value:unknown)=>new TextEncoder().encode(typeof value==='string'?value:JSON.stringify(value));
const hash=async(data:Uint8Array)=>Buffer.from(await webcrypto.subtle.digest('SHA-256',Uint8Array.from(data).buffer)).toString('hex');
const missing=()=>Object.assign(Error('missing'),{name:'NotFoundError'});
const draw=jest.fn();

function file(data:Uint8Array):File {
  return {size:data.length,arrayBuffer:async()=>Uint8Array.from(data).buffer,
    text:async()=>new TextDecoder().decode(data),slice:(a:number,b:number)=>file(data.slice(a,b))} as unknown as File;
}

async function library() {
  const files=new Map<string,Uint8Array>();
  const unit=new Uint8Array([0,0,0,1,0x67,0x42,0xe0,0x1f,0,0,0,1,0x65,1]);
  const frames=encode([0,1].map(index=>JSON.stringify({index,offset:index*unit.length,bytes:unit.length,
    relative_ticks_90k:index*90000,key:true,seekable:true,sha256:'',worker_observed_at_ms:1000+index*1000})).join('\n'));
  const rows=new TextDecoder().decode(frames).split('\n').map(line=>({...JSON.parse(line)}));
  for(const row of rows)row.sha256=await hash(unit);
  const index=encode(rows.map(row=>JSON.stringify(row)).join('\n')),journal=encode('');
  const video=new Uint8Array([...unit,...unit]);
  const manifest=encode({schema:'sphere-browser-teaching-v2',id,started_at_ms:1793012400000,config:{title:'Маршрут 011321'},
    complete:true,release_confirmed:true,frames:2,files:{'video.h264':{bytes:video.length},
      'frames.jsonl':{bytes:index.length,sha256:await hash(index)},'inputs.jsonl':{bytes:0,sha256:await hash(journal)}}});
  for(const [name,bytes] of Object.entries({'manifest.json':manifest,'frames.jsonl':index,'inputs.jsonl':journal,
    'video.h264':video,'COMPLETE':encode({manifest_sha256:await hash(manifest)})}))files.set(name,bytes);
  const folder={getFileHandle:async(name:string,options?:{create?:boolean})=>{
    if(!files.has(name)){if(!options?.create)throw missing();files.set(name,new Uint8Array());}
    return {getFile:async()=>file(files.get(name)!),createWritable:async()=>{
      let bytes=new Uint8Array();return {write:async(raw:string)=>{bytes=encode(raw);},
        close:async()=>{files.set(name,bytes);},abort:async()=>{}};
    }};
  }};
  const clips={values:async function*(){yield {kind:'directory',name:id};},getDirectoryHandle:async(name:string)=>{if(name!==id)throw missing();return folder;}};
  const root={getDirectoryHandle:async(name:string)=>{if(name!=='sphere-teaching-'+scope)throw missing();return clips;}};
  Object.defineProperty(navigator,'storage',{configurable:true,value:{getDirectory:async()=>root}});
  return {files,manifest};
}

beforeEach(()=>{
  draw.mockClear();
  Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});
  Object.defineProperty(globalThis,'TextDecoder',{configurable:true,value:TextDecoder});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:webcrypto.subtle});
  jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockImplementation(()=>({drawImage:draw}) as never);
  Object.defineProperty(globalThis,'EncodedVideoChunk',{configurable:true,value:class {timestamp:number;constructor(args:{timestamp:number}){this.timestamp=args.timestamp;}}});
  Object.defineProperty(globalThis,'VideoDecoder',{configurable:true,value:class {
    static isConfigSupported=async()=>({supported:true});decodeQueueSize=0;
    constructor(private callbacks:{output:(frame:unknown)=>void}){}
    configure(){}close(){}async flush(){}
    decode(chunk:{timestamp:number}){this.callbacks.output({timestamp:chunk.timestamp,displayWidth:960,displayHeight:540,close:jest.fn()});}
  }});
});
afterEach(()=>{jest.restoreAllMocks();});

test('review decodes and navigates the sealed source, then renames without changing media integrity',async()=>{
  const {files,manifest}=await library();const marker=files.get('COMPLETE'),video=files.get('video.h264');
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  await waitFor(()=>expect(draw).toHaveBeenCalled());
  expect(screen.getByRole('button',{name:/Маршрут 011321.*aaaaaaaa/})).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Вперёд 1 с →'}));
  await waitFor(()=>expect(screen.getByRole('slider',{name:'Время записанного прохода'})).toHaveValue('1'));
  fireEvent.change(screen.getByLabelText('Название сохранённого маршрута'),{target:{value:'Переулок · ночь'}});
  fireEvent.click(screen.getByRole('button',{name:'Сохранить название'}));
  await screen.findByRole('button',{name:/Переулок · ночь.*aaaaaaaa/});
  expect(JSON.parse(new TextDecoder().decode(files.get('label.json'))).title).toBe('Переулок · ночь');
  expect(files.get('manifest.json')).toBe(manifest);expect(files.get('COMPLETE')).toBe(marker);expect(files.get('video.h264')).toBe(video);
});
