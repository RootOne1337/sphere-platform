import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { webcrypto } from 'node:crypto';
import { TextDecoder, TextEncoder } from 'node:util';
import { TeachingReview, chooseReviewGeometry } from '@/src/features/stream/TeachingReview';
import { TeachingReconstruction } from '@/src/features/stream/TeachingReconstruction';
import ImageRouteReview from '@/src/features/stream/ImageRouteReview';
import {reconstructionRequest,ReconstructionResponseError} from '@/src/features/stream/reconstructionClient';
jest.mock('@/src/features/stream/TeachingReconstruction',()=>({TeachingReconstruction:jest.fn(()=>null)}));
jest.mock('@/src/features/stream/ImageRouteReview',()=>({__esModule:true,default:jest.fn(()=>null)}));
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn()}));

const id='a'.repeat(32),scope='b'.repeat(32);
const encode=(value:unknown)=>new TextEncoder().encode(typeof value==='string'?value:JSON.stringify(value));
const hash=async(data:Uint8Array)=>Buffer.from(await webcrypto.subtle.digest('SHA-256',Uint8Array.from(data).buffer)).toString('hex');
const missing=()=>new DOMException('missing','NotFoundError');
const draw=jest.fn(),clear=jest.fn();
const openCatalog=async()=>{const button=screen.queryByRole('button',{name:'Сменить запись'})??await screen.findByRole('button',{name:'Сменить запись'});fireEvent.click(button);};
const openArchive=async()=>{const summary=await screen.findByText('Название, экспорт и диагностика');if(!summary.closest('details')?.open)fireEvent.click(summary);};

function file(data:Uint8Array):File {
  return {size:data.length,arrayBuffer:async()=>Uint8Array.from(data).buffer,
    text:async()=>new TextDecoder().decode(data),slice:(a:number,b:number)=>file(data.slice(a,b))} as unknown as File;
}

async function library(prepareAfterRecording?:boolean) {
  const files=new Map<string,Uint8Array>();
  const unit=new Uint8Array([0,0,0,1,0x67,0x42,0xe0,0x1f,0,0,0,1,0x65,1]);
  const frames=encode([0,1].map(index=>JSON.stringify({index,offset:index*unit.length,bytes:unit.length,
    relative_ticks_90k:index*90000,key:true,seekable:true,sha256:'',worker_observed_at_ms:1000+index*1000})).join('\n'));
  const rows=new TextDecoder().decode(frames).split('\n').map(line=>({...JSON.parse(line)}));
  for(const row of rows)row.sha256=await hash(unit);
  const index=encode(rows.map(row=>JSON.stringify(row)).join('\n')),journal=encode('');
  const video=new Uint8Array([...unit,...unit]);
  const manifest=encode({schema:'sphere-browser-teaching-v2',id,started_at_ms:1793012400000,config:{title:'Маршрут 011321',...(prepareAfterRecording===undefined?{}:{prepare_after_recording:prepareAfterRecording})},
    complete:true,release_confirmed:true,frames:2,events:0,files:{'video.h264':{bytes:video.length},
      'frames.jsonl':{bytes:index.length,sha256:await hash(index)},'inputs.jsonl':{bytes:0,sha256:await hash(journal)}}});
  for(const [name,bytes] of Object.entries({'manifest.json':manifest,'frames.jsonl':index,'inputs.jsonl':journal,
    'video.h264':video,'COMPLETE':encode({manifest_sha256:await hash(manifest)})}))files.set(name,bytes);
  const makeFolder=(contents:Map<string,Uint8Array>)=>({entries:async function*(){for(const name of contents.keys())yield [name,{kind:'file',name}];},getFileHandle:async(name:string,options?:{create?:boolean})=>{
    if(!contents.has(name)){if(!options?.create)throw missing();contents.set(name,new Uint8Array());}
    return {getFile:async()=>file(contents.get(name)!),createWritable:async()=>{
      let bytes=new Uint8Array();return {write:async(raw:string)=>{bytes=encode(raw);},
        close:async()=>{contents.set(name,bytes);},abort:async()=>{}};
    }};
  }});
  const folder=makeFolder(files),folders=new Map([[id,folder]]);
  const remove=jest.fn(async()=>{});
  const clips={entries:async function*(){for(const name of folders.keys())yield [name,{kind:'directory',name}];},getDirectoryHandle:async(name:string)=>{if(!folders.has(name))throw missing();return folders.get(name);},removeEntry:remove};
  const root={getDirectoryHandle:async(name:string)=>{if(name!=='sphere-teaching-'+scope)throw missing();return clips;}};
  Object.defineProperty(navigator,'storage',{configurable:true,value:{getDirectory:async()=>root}});
  const addClip=async(otherId:string,title:string)=>{
    const copy=new Map(files),data=JSON.parse(new TextDecoder().decode(manifest));data.id=otherId;data.config.title=title;
    const otherManifest=encode(data);copy.set('manifest.json',otherManifest);copy.set('COMPLETE',encode({manifest_sha256:await hash(otherManifest)}));
    folders.set(otherId,makeFolder(copy));return {files:copy,manifest:otherManifest};
  };
  return {files,manifest,remove,addClip};
}

beforeEach(()=>{
  draw.mockClear();clear.mockClear();
  Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});
  Object.defineProperty(globalThis,'TextDecoder',{configurable:true,value:TextDecoder});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:webcrypto.subtle});
  jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockImplementation(()=>({drawImage:draw,clearRect:clear,setTransform:jest.fn(),beginPath:jest.fn(),arc:jest.fn(),fill:jest.fn()}) as never);
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
  await openCatalog();await openArchive();
  await screen.findByRole('button',{name:'Открыть запись «Маршрут 011321»'});
  fireEvent.change(screen.getByLabelText('Найти запись'),{target:{value:'нет такого'}});
  expect(screen.getByText('Записи не найдены')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Найти запись'),{target:{value:'011321'}});
  expect(screen.getByRole('button',{name:'Открыть запись «Маршрут 011321»'})).toBeInTheDocument();
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

test('an attempt with no geometry still displays the actual saved source beside the empty result',async()=>{
  await library();render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  await screen.findByRole('button',{name:'Смотреть исходное видео'});
  expect(screen.getByLabelText('Исходный кадр сохранённой записи')).toBeInTheDocument();
  await waitFor(()=>expect(draw).toHaveBeenCalled());
  fireEvent.click(screen.getByRole('button',{name:'Смотреть исходное видео'}));
  expect(screen.getByLabelText('Записанный видеокадр')).toBeVisible();
});
afterEach(()=>{jest.mocked(TeachingReconstruction).mockReset().mockImplementation(()=> <></>);jest.mocked(ImageRouteReview).mockReset().mockImplementation(()=>null);jest.mocked(reconstructionRequest).mockReset();jest.restoreAllMocks();});

test.each([true,false,undefined])('selected verified recording restores only its declared automatic intent: %s',async declared=>{
  await library(declared);
  jest.mocked(TeachingReconstruction).mockImplementation(props=><div data-testid="auto-intent">{String(props.autoPrepare)}</div>);
  const props={selected:id,refresh:0,onSelect:jest.fn(),storageScope:scope,visible:false};
  const first=render(<TeachingReview {...props}/>);
  expect(await screen.findByTestId('auto-intent')).toHaveTextContent(String(declared===true));first.unmount();
  const reloaded=render(<TeachingReview {...props}/>);
  expect(await screen.findByTestId('auto-intent')).toHaveTextContent(String(declared===true));reloaded.unmount();
});

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
  await openArchive();
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
    {preferredAlternativeId:'improved-v1',alternatives:[{id:'improved-v1',cameras:2,points:1}]}:scene}) as Response);
  function Linked(props:Parameters<typeof TeachingReconstruction>[0]){React.useEffect(()=>{props.onRouteChange?.(job);},[props.onRouteChange]);return <></>;}
  jest.mocked(TeachingReconstruction).mockImplementation(props=><Linked {...props}/>);
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  fireEvent.click(await screen.findByRole('button',{name:/исходный кадр 2/i}));
  await waitFor(()=>expect(screen.getByLabelText('Время записанного прохода')).toHaveValue('1'));
  expect(screen.getByText(/Сохранённая экспериментальная схема связана/)).toBeInTheDocument();
  const props=jest.mocked(TeachingReconstruction).mock.calls.at(-1)![0];
  expect(props.alternativeCameraCount).toBe(2);
  await openArchive();
  await waitFor(()=>expect(ImageRouteReview).toHaveBeenCalled());
  const imageProps=jest.mocked(ImageRouteReview).mock.calls.at(-1)![0];
  expect(imageProps.job).toEqual(job);
  expect(imageProps.manifestSha).toBe(source);
  expect([...imageProps.frames]).toEqual([[0,0],[1,90000]]);
  act(()=>imageProps.onSeek(0));
  expect(screen.getByLabelText('Время записанного прохода')).toHaveValue('0');
  expect(jest.mocked(reconstructionRequest).mock.calls.map(call=>call[0])).toEqual([
    `/jobs/${job.id}/geometry-alternatives`,`/jobs/${job.id}`,`/jobs/${job.id}/geometry-alternatives/improved-v1`]);
});

test('the current prepared map takes precedence over a stale experimental geometry',async()=>{
  const {manifest}=await library(),source=await hash(manifest),job={id:'c'.repeat(32),key:'d'.repeat(64)};
  const scene={schema:'sphere-recovered-scene-v1',source_manifest_sha256:source,
    cameras:[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:90000}],points:[[1,2,3,255,255,255]]};
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>({json:async()=>path.endsWith('/geometry-alternatives')?
    {alternatives:[{id:'old-experiment',cameras:2,points:1}]}:path===`/jobs/${job.id}`?
    {source_manifest_sha256:source,navigation:{phase:'ready'},geometry_available:true}:scene}) as Response);
  function Linked(props:Parameters<typeof TeachingReconstruction>[0]){React.useEffect(()=>{props.onRouteChange?.(job);},[props.onRouteChange]);return <></>;}
  jest.mocked(TeachingReconstruction).mockImplementation(props=><Linked {...props}/>);
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  await screen.findByText('Текущая подготовленная карта связана с исходной записью.');
  const select=screen.getByLabelText('Сохранённая схема ориентиров');
  expect(select).toHaveValue('primary');
  expect(jest.mocked(reconstructionRequest).mock.calls.map(call=>call[0])).toContain(`/jobs/${job.id}/geometry`);
  expect(jest.mocked(reconstructionRequest).mock.calls.map(call=>call[0])).not.toContain(`/jobs/${job.id}/geometry-alternatives/old-experiment`);
  fireEvent.change(select,{target:{value:'old-experiment'}});
  await screen.findByText('Сохранённая экспериментальная схема связана с исходной записью.');
  fireEvent.change(select,{target:{value:'primary'}});
  await screen.findByText('Текущая подготовленная карта связана с исходной записью.');
});
test('recommendation is explicit and never overrides operator or an accepted primary',()=>{
  const items=[{id:'old',cameras:163,points:5544},{id:'new',cameras:163,points:15041}];
  expect(chooseReviewGeometry(items,'new',false,null)).toBe('new');
  expect(chooseReviewGeometry(items,undefined,false,null)).toBeNull();
  expect(chooseReviewGeometry(items,'missing',false,null)).toBeNull();
  expect(chooseReviewGeometry(items,'new',null,null)).toBeNull();
  expect(chooseReviewGeometry(items,'new',true,null)).toBe('primary');
  expect(chooseReviewGeometry(items,'new',true,'old')).toBe('old');
  expect(chooseReviewGeometry(items,'new',false,'removed')).toBeNull();
});
test('refresh reads the updated list but preserves the manual choice',async()=>{
  const {manifest}=await library(),source=await hash(manifest),job={id:'c'.repeat(32),key:'d'.repeat(64)};
  const scene={schema:'sphere-recovered-scene-v1',source_manifest_sha256:source,
    cameras:[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:90000}],points:[[1,2,3,255,255,255]]};
  const preferred='new';
  let listCalls=0,releaseRefresh:()=>void=()=>{};
  const refreshGate=new Promise<void>(resolve=>{releaseRefresh=resolve;});
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>({json:async()=>path.endsWith('/geometry-alternatives')?
    (await (++listCalls===2?refreshGate:Promise.resolve()),{preferredAlternativeId:preferred,alternatives:[{id:'old',cameras:163,points:5544},{id:'new',label:'Новая диагностика',cameras:163,points:15041}]}):
    path===`/jobs/${job.id}`?{source_manifest_sha256:source,navigation:{phase:'review'},geometry_available:false}:scene}) as Response);
  function Linked(props:Parameters<typeof TeachingReconstruction>[0]){React.useEffect(()=>{props.onRouteChange?.(job);},[props.onRouteChange]);return <></>;}
  jest.mocked(TeachingReconstruction).mockImplementation(props=><Linked {...props}/>);
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  await screen.findByText('Сохранённая экспериментальная схема связана с исходной записью.');
  const select=screen.getByLabelText('Сохранённая схема ориентиров');expect(select).toHaveValue('new');
  await waitFor(()=>expect(screen.getByLabelText('Источник геометрии всех просмотров')).toHaveTextContent(/Новая диагностика.*2 камер.*1 точек/));
  fireEvent.click(screen.getByRole('button',{name:'Обновить результаты'}));
  await waitFor(()=>expect(listCalls).toBe(2));
  fireEvent.change(select,{target:{value:'old'}});
  await waitFor(()=>expect(screen.getByLabelText('Источник геометрии всех просмотров')).toHaveTextContent(/Дополнительная реконструкция.*2 камер.*1 точек/));
  const before=jest.mocked(reconstructionRequest).mock.calls.filter(call=>call[0].endsWith('/geometry-alternatives/old')).length;
  releaseRefresh();
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.filter(call=>call[0].endsWith('/geometry-alternatives/old')).length).toBeGreaterThan(before));
  expect(select).toHaveValue('old');
});
test('a recommended alternative from another source cannot open',async()=>{
  const {manifest}=await library(),source=await hash(manifest),job={id:'c'.repeat(32),key:'d'.repeat(64)};
  const scene={schema:'sphere-recovered-scene-v1',source_manifest_sha256:'f'.repeat(64),
    cameras:[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:90000}],points:[[1,2,3,255,255,255]]};
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>({json:async()=>path.endsWith('/geometry-alternatives')?
    {preferredAlternativeId:'other',alternatives:[{id:'other',cameras:2,points:1}]}:path===`/jobs/${job.id}`?
    {source_manifest_sha256:source,navigation:{phase:'review'},geometry_available:false}:scene}) as Response);
  function Linked(props:Parameters<typeof TeachingReconstruction>[0]){React.useEffect(()=>{props.onRouteChange?.(job);},[props.onRouteChange]);return <></>;}
  jest.mocked(TeachingReconstruction).mockImplementation(props=><Linked {...props}/>);
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  await screen.findByText('Схема не прошла проверку привязки или недоступна.');
  expect(screen.queryByRole('button',{name:/исходный кадр 2/i})).not.toBeInTheDocument();
});
test('deselect clears the diagnostic map and late geometry cannot restore it',async()=>{
  const {manifest}=await library(),source=await hash(manifest),job={id:'c'.repeat(32),key:'d'.repeat(64)};
  const scene={schema:'sphere-recovered-scene-v1',source_manifest_sha256:source,
    cameras:[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:90000}],points:[[1,2,3,255,255,255]]};
  let geometryCalls=0,listCalls=0,release:()=>void=()=>{};const pending=new Promise<void>(resolve=>{release=resolve;});
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>({json:async()=>{
    if(path.endsWith('/geometry-alternatives')){listCalls++;return {preferredAlternativeId:'preferred',alternatives:[{id:'preferred',cameras:2,points:1}]};}
    if(path===`/jobs/${job.id}`)return {source_manifest_sha256:source,navigation:{phase:'review'},geometry_available:false};
    if(++geometryCalls===2)await pending;return scene;
  }}) as Response);
  function Linked(props:Parameters<typeof TeachingReconstruction>[0]){React.useEffect(()=>{props.onRouteChange?.(job);},[props.onRouteChange]);return <></>;}
  jest.mocked(TeachingReconstruction).mockImplementation(props=><Linked {...props}/>);
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  await screen.findByText('Сохранённая экспериментальная схема связана с исходной записью.');
  expect(screen.getByLabelText('Источник геометрии всех просмотров')).toHaveTextContent('Дополнительная реконструкция');
  expect(screen.getByText(/Это результат для проверки геометрии/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Сохранённая схема ориентиров'),{target:{value:''}});
  expect(screen.queryByLabelText('Проекция опорных точек и положений камеры')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Источник геометрии всех просмотров')).toHaveTextContent('Результат не выбран');
  expect(screen.queryByText(/Это результат для проверки геометрии/)).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Сохранённая схема ориентиров'),{target:{value:'preferred'}});
  await waitFor(()=>expect(geometryCalls).toBe(2));
  fireEvent.change(screen.getByLabelText('Сохранённая схема ориентиров'),{target:{value:''}});
  expect(screen.queryByLabelText('Проекция опорных точек и положений камеры')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Источник геометрии всех просмотров')).toHaveTextContent('Результат не выбран');
  expect(screen.queryByText(/Это результат для проверки геометрии/)).not.toBeInTheDocument();
  await act(async()=>{release();await pending;});
  expect(screen.queryByLabelText('Проекция опорных точек и положений камеры')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Обновить результаты'}));
  await waitFor(()=>expect(listCalls).toBe(2));
  await screen.findByText('Выберите схему.');
  expect(screen.getByLabelText('Сохранённая схема ориентиров')).toHaveValue('');
  expect(geometryCalls).toBe(2);
  expect(screen.queryByLabelText('Проекция опорных точек и положений камеры')).not.toBeInTheDocument();
});
test('switching the linked reconstruction clears a previously shown alternate',async()=>{
  const {manifest}=await library(),source=await hash(manifest),first={id:'c'.repeat(32),key:'d'.repeat(64)},second={id:'e'.repeat(32),key:'f'.repeat(64)};
  const scene={schema:'sphere-recovered-scene-v1',source_manifest_sha256:source,
    cameras:[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:90000}],points:[[1,2,3,255,255,255]]};
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>({json:async()=>path.startsWith(`/jobs/${second.id}`)?{source_manifest_sha256:source,alternatives:[]}:path.endsWith('/geometry-alternatives')?{preferredAlternativeId:'improved-v1',alternatives:[{id:'improved-v1',cameras:2,points:1}]}:scene}) as Response);
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
  await openCatalog();await openArchive();
  expect(screen.getByRole('button',{name:'Открыть запись «Маршрут 011321»'})).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Вперёд 1 с →'}));
  await waitFor(()=>expect(screen.getByRole('slider',{name:'Время записанного прохода'})).toHaveValue('1'));
  fireEvent.change(screen.getByLabelText('Название сохранённого маршрута'),{target:{value:'Переулок · ночь'}});
  fireEvent.click(screen.getByRole('button',{name:'Сохранить название'}));
  await screen.findByRole('button',{name:'Открыть запись «Переулок · ночь»'});
  expect(JSON.parse(new TextDecoder().decode(files.get('label.json'))).title).toBe('Переулок · ночь');
  expect(files.get('manifest.json')).toBe(manifest);expect(files.get('COMPLETE')).toBe(marker);expect(files.get('video.h264')).toBe(video);
});

test('search can find a recording older than the newest twenty without deleting it',async()=>{
  const items=Array.from({length:25},(_,n)=>({id:n.toString(16).padStart(32,'0'),title:`Маршрут ${n}`,at:1000+n}));
  const root={getDirectoryHandle:async()=>({
    entries:async function*(){for(const item of items)yield [item.id,{kind:'directory',name:item.id}];},
    getDirectoryHandle:async(name:string)=>{const item=items.find(row=>row.id===name)!;return {getFileHandle:async(fileName:string)=>{
      if(fileName!=='manifest.json')throw missing();
      return {getFile:async()=>file(encode({schema:'sphere-browser-teaching-v2',id:item.id,started_at_ms:item.at,complete:false,frames:10,events:0,config:{title:item.title}}))};
    }};},
  })};
  Object.defineProperty(navigator,'storage',{configurable:true,value:{getDirectory:async()=>root}});
  render(<TeachingReview selected={null} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  await screen.findByText(/Найдено 25 из 25 прочитанных записей/);
  fireEvent.change(screen.getByLabelText('Найти запись'),{target:{value:'Маршрут 0'}});
  expect(screen.getByRole('button',{name:'Открыть запись «Маршрут 0»'})).toBeInTheDocument();
});

test('the account queue job is passed to the inspector without enabling a second automatic owner',async()=>{
  await library(true);const jobId='e'.repeat(32);
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope} visible={false}
    manageAutomaticPreparation={false} processingQueue={{scope,activeClip:id,items:[{clip:id,jobId,phase:'processing',updatedAt:Date.now()}]}}/>);
  await waitFor(()=>expect(jest.mocked(TeachingReconstruction)).toHaveBeenCalledWith(expect.objectContaining({clip:id,processingJobId:jobId,manageAutomaticPreparation:false}),undefined));
});

test('queue processing protects its source from deletion while another recording remains selectable',async()=>{
  const {addClip,remove}=await library(true),other='f'.repeat(32);await addClip(other,'Другой спокойный проход');
  const onSelect=jest.fn();
  render(<TeachingReview selected={id} refresh={0} onSelect={onSelect} storageScope={scope} manageAutomaticPreparation={false}
    processingQueue={{scope,activeClip:id,items:[{clip:id,jobId:'e'.repeat(32),phase:'processing',updatedAt:Date.now()}]}}/>);
  await openCatalog();await openArchive();
  await waitFor(()=>expect(screen.getByRole('button',{name:'Удалить выбранный локальный материал'})).toBeDisabled());
  const another=await screen.findByRole('button',{name:'Открыть запись «Другой спокойный проход»'});
  expect(another).toBeEnabled();fireEvent.click(another);
  expect(onSelect).toHaveBeenCalledWith(other);expect(remove).not.toHaveBeenCalled();
});

test('a queue from another account cannot bind its job or block the selected source',async()=>{
  await library(true);
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope} manageAutomaticPreparation={false}
    processingQueue={{scope:'c'.repeat(32),activeClip:id,items:[{clip:id,jobId:'e'.repeat(32),phase:'processing',updatedAt:Date.now()}]}}/>);
  await openArchive();
  await waitFor(()=>expect(jest.mocked(TeachingReconstruction).mock.calls.at(-1)![0].processingJobId).toBeUndefined());
  await waitFor(()=>expect(screen.getByRole('button',{name:'Удалить выбранный локальный материал'})).toBeEnabled());
});

test('processing that begins after delete confirmation opens still fences the destructive action',async()=>{
  const {remove}=await library(true),onSelect=jest.fn();
  const props={selected:id,refresh:0,onSelect,storageScope:scope,manageAutomaticPreparation:false};
  const view=render(<TeachingReview {...props}/>);
  await openArchive();
  await waitFor(()=>expect(screen.getByRole('button',{name:'Удалить выбранный локальный материал'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Удалить выбранный локальный материал'}));
  expect(screen.getByRole('button',{name:'Удалить навсегда'})).toBeEnabled();
  view.rerender(<TeachingReview {...props} processingQueue={{scope,activeClip:id,items:[{clip:id,jobId:'e'.repeat(32),phase:'processing',updatedAt:Date.now()}]}}/>);
  expect(screen.getByRole('button',{name:'Удалить навсегда'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Удалить навсегда'}));
  expect(remove).not.toHaveBeenCalled();expect(onSelect).not.toHaveBeenCalledWith(null);
});

test('a late ready result for an old job cannot freshen navigation for a different job now processing in the queue',async()=>{
  const {files,manifest}=await library(true),oldJob={id:'c'.repeat(32),key:'d'.repeat(64)},newJobId='e'.repeat(32),source=await hash(manifest);
  files.set('reconstruction-link.json',encode({schema:'sphere-local-reconstruction-link-v1',clip:id,job:oldJob}));
  let now=Date.now(),reads=0,release:()=>void=()=>{};
  jest.spyOn(Date,'now').mockImplementation(()=>now);
  const gate=new Promise<void>(resolve=>{release=resolve;});
  jest.mocked(reconstructionRequest).mockImplementation(async()=>{
    if(++reads>1)await gate;
    return {json:async()=>({phase:'sparse_complete',source_manifest_sha256:source,navigation:{phase:'ready'},geometry_available:true})} as Response;
  });
  const props={selected:id,refresh:0,onSelect:jest.fn(),storageScope:scope,manageAutomaticPreparation:false};
  const view=render(<TeachingReview {...props}/>);
  await openCatalog();
  await screen.findByRole('button',{name:/Карта для проверки 1/});
  now+=100;
  view.rerender(<TeachingReview {...props} processingQueue={{scope,activeClip:id,items:[{clip:id,jobId:newJobId,phase:'processing',updatedAt:now}]}}/>);
  await waitFor(()=>expect(reads).toBeGreaterThanOrEqual(2));
  now+=100;
  await act(async()=>{release();await gate;await new Promise<void>(resolve=>setTimeout(resolve,0));});
  expect(screen.getByRole('button',{name:/Карта для проверки 0/})).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Открыть карту'})).not.toBeInTheDocument();
  expect(jest.mocked(TeachingReconstruction).mock.calls.at(-1)![0].processingJobId).toBe(newJobId);
});
test('a hidden archive mounts no image-review poller; opening starts it and closing cancels its scheduled retry',async()=>{
  const {manifest}=await library(),source=await hash(manifest),job={id:'c'.repeat(32),key:'d'.repeat(64)};
  const scene={schema:'sphere-recovered-scene-v1',source_manifest_sha256:source,cameras:[{center:[0,0,0],ticks_90k:0},{center:[1,0,0],ticks_90k:90000}],points:[[1,2,3,255,255,255]]};
  const ActualImageReview=jest.requireActual<typeof import('@/src/features/stream/ImageRouteReview')>('@/src/features/stream/ImageRouteReview').default;
  jest.mocked(ImageRouteReview).mockImplementation(props=><ActualImageReview {...props}/>);
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>{
    if(path.endsWith('/image-route-review'))throw new ReconstructionResponseError(404,'image_review_not_ready');
    return {json:async()=>path.endsWith('/geometry-alternatives')?{preferredAlternativeId:'preferred',alternatives:[{id:'preferred',cameras:2,points:1}]}:path===`/jobs/${job.id}`?{phase:'matching',source_manifest_sha256:source,geometry_available:false,navigation:{phase:'not_prepared'}}:scene} as Response;
  });
  function Linked(props:Parameters<typeof TeachingReconstruction>[0]){React.useEffect(()=>{props.onRouteChange?.(job);},[props.onRouteChange]);return <></>;}
  jest.mocked(TeachingReconstruction).mockImplementation(props=><Linked {...props}/>);
  render(<TeachingReview selected={id} refresh={0} onSelect={jest.fn()} storageScope={scope}/>);
  await screen.findByText('Сохранённая экспериментальная схема связана с исходной записью.');
  const reads=()=>jest.mocked(reconstructionRequest).mock.calls.filter(call=>call[0].endsWith('/image-route-review')).length;
  expect(ImageRouteReview).not.toHaveBeenCalled();expect(reads()).toBe(0);
  jest.useFakeTimers();
  try{
    const summary=screen.getByText('Название, экспорт и диагностика');
    await act(async()=>{fireEvent.click(summary);await jest.advanceTimersByTimeAsync(0);});
    await waitFor(()=>expect(reads()).toBe(1));
    expect(jest.mocked(ImageRouteReview).mock.calls.at(-1)![0]).toMatchObject({job,manifestSha:source,visible:true});
    await act(async()=>{fireEvent.click(summary);await jest.advanceTimersByTimeAsync(0);});
    expect(summary.closest('details')).not.toHaveAttribute('open');
    await act(async()=>{await jest.advanceTimersByTimeAsync(5000);});
    expect(reads()).toBe(1);
    await act(async()=>{fireEvent.click(summary);await jest.advanceTimersByTimeAsync(0);});
    await waitFor(()=>expect(reads()).toBe(2));
  }finally{jest.useRealTimers();}
});
