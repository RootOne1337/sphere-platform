import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { webcrypto } from 'node:crypto';
import { TextDecoder, TextEncoder } from 'node:util';
import { TeachingReview } from '@/src/features/stream/TeachingReview';
import { TeachingReconstruction } from '@/src/features/stream/TeachingReconstruction';
import {reconstructionRequest} from '@/src/features/stream/reconstructionClient';
jest.mock('@/src/features/stream/TeachingReconstruction',()=>({TeachingReconstruction:jest.fn(()=>null)}));
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn()}));

const id='a'.repeat(32),scope='b'.repeat(32);
const encode=(value:unknown)=>new TextEncoder().encode(typeof value==='string'?value:JSON.stringify(value));
const hash=async(data:Uint8Array)=>Buffer.from(await webcrypto.subtle.digest('SHA-256',Uint8Array.from(data).buffer)).toString('hex');
const missing=()=>Object.assign(Error('missing'),{name:'NotFoundError'});
const draw=jest.fn(),clear=jest.fn();

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
  const remove=jest.fn(async()=>{});
  const clips={values:async function*(){yield {kind:'directory',name:id};},getDirectoryHandle:async(name:string)=>{if(name!==id)throw missing();return folder;},removeEntry:remove};
  const root={getDirectoryHandle:async(name:string)=>{if(name!=='sphere-teaching-'+scope)throw missing();return clips;}};
  Object.defineProperty(navigator,'storage',{configurable:true,value:{getDirectory:async()=>root}});
  return {files,manifest,remove};
}

beforeEach(()=>{
  draw.mockClear();clear.mockClear();
  Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});
  Object.defineProperty(globalThis,'TextDecoder',{configurable:true,value:TextDecoder});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:webcrypto.subtle});
  jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockImplementation(()=>({drawImage:draw,clearRect:clear}) as never);
  Object.defineProperty(globalThis,'EncodedVideoChunk',{configurable:true,value:class {timestamp:number;constructor(args:{timestamp:number}){this.timestamp=args.timestamp;}}});
  Object.defineProperty(globalThis,'VideoDecoder',{configurable:true,value:class {
    static isConfigSupported=async()=>({supported:true});decodeQueueSize=0;
    constructor(private callbacks:{output:(frame:unknown)=>void}){}
    configure(){}close(){}async flush(){}
    decode(chunk:{timestamp:number}){this.callbacks.output({timestamp:chunk.timestamp,displayWidth:960,displayHeight:540,close:jest.fn()});}
  }});
});

test('search filters the local list and deletion requires an explicit second action',async()=>{
  const {remove}=await library();const onSelect=jest.fn();
  render(<TeachingReview selected={id} refresh={0} onSelect={onSelect} storageScope={scope}/>);
  await screen.findByRole('button',{name:/Маршрут 011321.*aaaaaaaa/});
  fireEvent.change(screen.getByLabelText('Поиск по названию или идентификатору'),{target:{value:'нет такого'}});
  expect(screen.getByText('По этому запросу записи не найдены.')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Поиск по названию или идентификатору'),{target:{value:'011321'}});
  expect(screen.getByRole('button',{name:/Маршрут 011321.*aaaaaaaa/})).toBeInTheDocument();
  await waitFor(()=>expect(screen.getByRole('button',{name:'Удалить выбранный локальный материал'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Удалить выбранный локальный материал'}));
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Удалить навсегда'}));
  await waitFor(()=>expect(remove).toHaveBeenCalledTimes(1));
  expect(remove).toHaveBeenCalledWith(id,{recursive:true});
  expect(onSelect).toHaveBeenCalledWith(null);
});

test('the shared source is verified and cannot be relabeled as a newly selected clip',async()=>{
  const {manifest}=await library(),changed=jest.fn();
  const props={selected:id,refresh:0,onSelect:jest.fn(),storageScope:scope,onSourceChange:changed,visible:false};
  const view=render(<TeachingReview {...props}/>);
  await waitFor(()=>expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({clip:id,scope,rows:expect.any(Array)})));
  expect(changed.mock.calls.at(-1)![0].manifestSha).toBe(await hash(manifest));
  const other='c'.repeat(32);view.rerender(<TeachingReview {...props} selected={other}/>);
  await waitFor(()=>expect(changed).toHaveBeenLastCalledWith(null));
  expect(changed.mock.calls.some(([value])=>value?.clip===other)).toBe(false);
});
afterEach(()=>{jest.mocked(TeachingReconstruction).mockReset().mockImplementation(()=> <></>);jest.mocked(reconstructionRequest).mockReset();jest.restoreAllMocks();});

test('selected camera seeks the verified source and updates the adjacent original-frame viewer',async()=>{
  const {manifest}=await library();
  jest.mocked(TeachingReconstruction).mockImplementation(props=><div>
    <span data-testid="manifest">{props.sourceManifestSha}</span>
    <span data-testid="selected-ticks">{props.selectedTicks}</span>
    <button onClick={()=>props.onSeekCamera?.(90000)}>Выбрать камеру</button>
    <button onClick={()=>props.onSeekCamera?.(90001)}>Неизвестная камера</button>
    {props.sourcePreview}
  </div>);
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  await waitFor(async()=>expect(screen.getByTestId('manifest')).toHaveTextContent(await hash(manifest)));
  expect(screen.getByTestId('selected-ticks')).toHaveTextContent('0');
  expect(screen.getByLabelText('Исходный кадр выбранной точки')).toBeInTheDocument();
  await waitFor(()=>expect(draw.mock.calls.length).toBeGreaterThanOrEqual(2));
  fireEvent.click(screen.getByRole('button',{name:'Неизвестная камера'}));
  expect(screen.getByLabelText('Время записанного прохода')).toHaveValue('0');
  fireEvent.click(screen.getByRole('button',{name:'Выбрать камеру'}));
  await waitFor(()=>expect(screen.getByLabelText('Время записи рядом со схемой')).toHaveValue('1'));
  expect(screen.getByLabelText('Время записанного прохода')).toHaveValue('1');
  expect(screen.getByTestId('selected-ticks')).toHaveTextContent('90000');
  fireEvent.change(screen.getByLabelText('Время записи рядом со схемой'),{target:{value:'0'}});
  expect(screen.getByLabelText('Время записанного прохода')).toHaveValue('0');
});
test('a selected local geometry file opens the matching route and rejects other recordings',async()=>{
  const {manifest}=await library(),source=await hash(manifest);
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  fireEvent.click(await screen.findByText('Открыть геометрию из файла'));
  const picker=await screen.findByLabelText('Выбрать geometry.json для выбранной записи');
  const scene={schema:'sphere-recovered-scene-v1',source_manifest_sha256:source,
    cameras:[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:90000}],points:[[1,2,3,255,255,255]]};
  const makeFile=(value:unknown)=>{const content=JSON.stringify(value),result=new File([content],'geometry.json',{type:'application/json'});Object.defineProperty(result,'text',{value:async()=>content});return result;};
  fireEvent.change(picker,{target:{files:[makeFile(scene)]}});
  fireEvent.click(await screen.findByRole('button',{name:/исходный кадр 2/i}));
  await waitFor(()=>expect(screen.getByLabelText('Время записи импортированной схемы')).toHaveValue('1'));
  expect(screen.getByLabelText('Время записанного прохода')).toHaveValue('1');
  fireEvent.change(picker,{target:{files:[makeFile({...scene,source_manifest_sha256:'f'.repeat(64)})]}});
  await screen.findByText(/Геометрия относится к другой записи/);
  expect(screen.queryByLabelText('Время записи импортированной схемы')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Время записанного прохода')).toHaveValue('1');
});
test('a saved alternative opens automatically from the linked job without a file picker',async()=>{
  const {manifest}=await library(),source=await hash(manifest),job={id:'c'.repeat(32),key:'d'.repeat(64)};
  const scene={schema:'sphere-recovered-scene-v1',source_manifest_sha256:source,
    cameras:[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:90000}],points:[[1,2,3,255,255,255]]};
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>({json:async()=>path.endsWith('/geometry-alternatives')?
    {alternatives:[{id:'improved-v1',cameras:2,points:1}]}:scene}) as Response);
  function Linked(props:Parameters<typeof TeachingReconstruction>[0]){React.useEffect(()=>{props.onRouteChange?.(job);},[props.onRouteChange]);return <></>;}
  jest.mocked(TeachingReconstruction).mockImplementation(props=><Linked {...props}/>);
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  fireEvent.click(await screen.findByRole('button',{name:/исходный кадр 2/i}));
  await waitFor(()=>expect(screen.getByLabelText('Время записанного прохода')).toHaveValue('1'));
  expect(screen.getByText(/Сохранённая экспериментальная схема связана/)).toBeInTheDocument();
  const props=jest.mocked(TeachingReconstruction).mock.calls.at(-1)![0];
  expect(props.alternativeCameraCount).toBe(2);
  expect(jest.mocked(reconstructionRequest).mock.calls.map(call=>call[0])).toEqual([
    `/jobs/${job.id}/geometry-alternatives`,`/jobs/${job.id}/geometry-alternatives/improved-v1`]);
});
test('switching the linked reconstruction clears a previously shown alternate',async()=>{
  const {manifest}=await library(),source=await hash(manifest),first={id:'c'.repeat(32),key:'d'.repeat(64)},second={id:'e'.repeat(32),key:'f'.repeat(64)};
  const scene={schema:'sphere-recovered-scene-v1',source_manifest_sha256:source,
    cameras:[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:90000}],points:[[1,2,3,255,255,255]]};
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>({json:async()=>path.startsWith(`/jobs/${second.id}`)?{alternatives:[]}:path.endsWith('/geometry-alternatives')?{alternatives:[{id:'improved-v1',cameras:2,points:1}]}:scene}) as Response);
  function Linked(props:Parameters<typeof TeachingReconstruction>[0]){
    React.useEffect(()=>{props.onRouteChange?.(first);},[props.onRouteChange]);
    return <button onClick={()=>props.onRouteChange?.(second)}>Другая реконструкция</button>;
  }
  jest.mocked(TeachingReconstruction).mockImplementation(props=><Linked {...props}/>);
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  await screen.findByRole('button',{name:/исходный кадр 2/i});
  fireEvent.click(screen.getByRole('button',{name:'Другая реконструкция'}));
  await screen.findByText('Дополнительных схем для этой реконструкции нет.');
  expect(screen.queryByRole('button',{name:/исходный кадр 2/i})).not.toBeInTheDocument();
  expect(jest.mocked(TeachingReconstruction).mock.calls.at(-1)![0].alternativeCameraCount).toBeNull();
});
test('seeking clears the previous image before a failed decode',async()=>{
  await library();
  let supported=true;
  Object.defineProperty(globalThis,'VideoDecoder',{configurable:true,value:class {
    static isConfigSupported=async()=>({supported});decodeQueueSize=0;
    constructor(private callbacks:{output:(frame:unknown)=>void}){}
    configure(){}close(){}async flush(){}
    decode(chunk:{timestamp:number}){this.callbacks.output({timestamp:chunk.timestamp,displayWidth:960,displayHeight:540,close:jest.fn()});}
  }});
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  await waitFor(()=>expect(draw).toHaveBeenCalled());
  const clearsBefore=clear.mock.calls.length;supported=false;
  fireEvent.change(screen.getByLabelText('Время записанного прохода'),{target:{value:'1'}});
  await screen.findByText('Профиль H264 не поддерживается декодером.');
  expect(clear.mock.calls.length).toBeGreaterThan(clearsBefore);
});

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

test('search can find a recording older than the newest twenty without deleting it',async()=>{
  const items=Array.from({length:25},(_,n)=>({id:n.toString(16).padStart(32,'0'),title:`Маршрут ${n}`,at:1000+n}));
  const root={getDirectoryHandle:async()=>({
    values:async function*(){for(const item of items)yield {kind:'directory',name:item.id};},
    getDirectoryHandle:async(name:string)=>{const item=items.find(row=>row.id===name)!;return {getFileHandle:async(fileName:string)=>{
      if(fileName!=='manifest.json')throw missing();
      return {getFile:async()=>file(encode({schema:'sphere-browser-teaching-v2',id:item.id,started_at_ms:item.at,complete:true,frames:10,config:{title:item.title}}))};
    }};},
  })};
  Object.defineProperty(navigator,'storage',{configurable:true,value:{getDirectory:async()=>root}});
  render(<TeachingReview selected={null} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  await screen.findByText('Показано 25 из 25');
  fireEvent.change(screen.getByLabelText('Поиск по названию или идентификатору'),{target:{value:'Маршрут 0'}});
  expect(screen.getByRole('button',{name:/Маршрут 0.*Готов/})).toBeInTheDocument();
});
