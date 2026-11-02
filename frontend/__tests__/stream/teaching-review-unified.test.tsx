import React from 'react';
import {createPortal} from 'react-dom';
import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {TeachingReview} from '@/src/features/stream/TeachingReview';
import {TeachingReconstruction} from '@/src/features/stream/TeachingReconstruction';
import RouteGeometryMap from '@/src/features/stream/RouteGeometryMap';
import {reconstructionRequest,type ReconstructionJob} from '@/src/features/stream/reconstructionClient';
import {installReviewBrowser,makeUnifiedReviewFixture} from './fixtures/teachingReviewFixture';
jest.mock('@/src/features/stream/TeachingReconstruction',()=>({TeachingReconstruction:jest.fn()}));
jest.mock('@/src/features/stream/RouteGeometryMap',()=>({__esModule:true,default:jest.fn()}));
jest.mock('@/src/features/stream/ImageRouteReview',()=>({__esModule:true,default:()=>null}));
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn()}));
const scope='b'.repeat(32),clip='a'.repeat(32),job={id:'c'.repeat(32),key:'d'.repeat(64)},nextJob={id:'e'.repeat(32),key:'f'.repeat(64)};
type InspectorProps=Parameters<typeof TeachingReconstruction>[0];
const latest=()=>jest.mocked(TeachingReconstruction).mock.calls.at(-1)![0];
let jobFor:(props:InspectorProps)=>ReconstructionJob;
function Inspector(props:InspectorProps){
  React.useEffect(()=>{props.onRouteChange?.(jobFor(props));},[props.onRouteChange,props.clip,props.scope]);
  const selected=props.selectedGeometry,geometry=selected?.geometry;
  return <><div data-testid="inspector" data-presentation={props.presentation} data-ticks={props.selectedTicks}/><button onClick={()=>props.onRouteChange?.(nextJob)}>Другая попытка</button>
    {props.sceneContainer&&createPortal(<div data-testid="scene-choice" data-choice={selected?.id??'none'} data-count={geometry?.cameras.length??'loading'} data-ticks={props.selectedTicks}>
      <button disabled={!geometry} onClick={()=>props.onSeekCamera?.(geometry!.cameras.at(-1)!.ticks_90k)}>Последняя камера 3D</button>
    </div>,props.sceneContainer)}</>;
}
beforeEach(()=>{
  jest.clearAllMocks();installReviewBrowser();jobFor=()=>job;
  jest.mocked(TeachingReconstruction).mockImplementation(props=><Inspector {...props}/>);
  jest.mocked(RouteGeometryMap).mockImplementation(props=><div data-testid="map-choice" data-count={props.cameras.length} data-ticks={props.selectedTicks}>
    <button onClick={()=>props.onSeekCamera?.(props.cameras.at(-1)!.ticks_90k)}>Последняя камера 2D</button>{props.sourcePreview}
  </div>);
});
afterEach(()=>jest.restoreAllMocks());
async function setup(){
  const source=await makeUnifiedReviewFixture(scope,clip),primary=source.geometry(144,1000),preferred=source.geometry(173,0);
  Object.defineProperty(navigator,'storage',{configurable:true,value:{getDirectory:async()=>source.root}});
  const read=async(path:string)=>{
    if(path.endsWith('/geometry-alternatives'))return {preferredAlternativeId:'loop-173',alternatives:[{id:'loop-173',label:'Проверенная геометрия · 173',cameras:173,points:1}]};
    if(path===`/jobs/${job.id}`||path===`/jobs/${nextJob.id}`)return {phase:'sparse_complete',source_manifest_sha256:source.manifestSha,geometry_available:true,navigation:{phase:'failed',error:'route_map_has_unobserved_sections'}};
    if(path.endsWith('/geometry'))return primary;
    return preferred;
  };
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>({json:async()=>read(path)}) as Response);
  return {source,primary,preferred,read};
}
const base={selected:clip,refresh:0,onSelect:jest.fn(),storageScope:scope,manageAutomaticPreparation:false};
test('the preferred173 result is the exact shared 2D/3D/source-time selection, not the primary144 model',async()=>{
  const {source}=await setup();render(<TeachingReview {...base}/>);
  await waitFor(()=>expect(screen.getByTestId('map-choice')).toHaveAttribute('data-count','173'));
  expect(screen.queryByRole('button',{name:/Открыть запись/})).not.toBeInTheDocument();
  expect(latest()).toMatchObject({presentation:'compact',clip,scope,sourceManifestSha:source.manifestSha,sceneContainer:null,selectedGeometry:{id:'loop-173',jobId:job.id,sourceKey:`${scope}:${clip}`,sourceManifestSha:source.manifestSha,diagnostic:true}});
  const map=jest.mocked(RouteGeometryMap).mock.calls.at(-1)![0];
  expect(latest().selectedGeometry?.geometry?.cameras).toBe(map.cameras);expect(map.cameras[0].center).toEqual([0,0,0]);
  fireEvent.click(screen.getByRole('button',{name:'Камеры и точки 3D'}));
  expect(await screen.findByTestId('scene-choice')).toHaveAttribute('data-count','173');
  expect(latest().sceneContainer).toBe(screen.getByLabelText('3D выбранного результата'));
  expect(latest().selectedGeometry?.geometry?.cameras).toBe(map.cameras);
  fireEvent.click(screen.getByRole('button',{name:'Последняя камера 3D'}));
  await waitFor(()=>expect(screen.getByLabelText('Время записанного прохода')).toHaveValue('172'));
  expect(latest().selectedTicks).toBe(source.rows[172].relative_ticks_90k);
  fireEvent.click(screen.getByRole('button',{name:'Исходное видео'}));
  expect(screen.getByText('Кадр 173 / 200 · 17.200 с')).toBeInTheDocument();expect(latest().sceneContainer).toBeNull();
  expect(screen.queryByTestId('scene-choice')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Карта 2D'}));
  expect(screen.getByTestId('map-choice')).toHaveAttribute('data-ticks',String(source.rows[172].relative_ticks_90k));
  expect(screen.getByLabelText('Время записи импортированной схемы')).toHaveValue('172');
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>!call[2]?.method)).toBe(true);
});
test('switching result clears both views immediately; loading and late responses never fall back or cross-wire models',async()=>{
  const {primary,preferred,read}=await setup();let releasePrimary:()=>void=()=>{},releaseAlternative:()=>void=()=>{};
  let holdPrimary=false,holdAlternative=false;
  const primaryGate=new Promise<void>(resolve=>{releasePrimary=resolve;}),alternativeGate=new Promise<void>(resolve=>{releaseAlternative=resolve;});
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>({json:async()=>{
    if(path.endsWith('/geometry')&&holdPrimary)await primaryGate;
    if(path.endsWith('/geometry-alternatives/loop-173')&&holdAlternative)await alternativeGate;
    return read(path);
  }}) as Response);
  render(<TeachingReview {...base}/>);await waitFor(()=>expect(screen.getByTestId('map-choice')).toHaveAttribute('data-count','173'));
  holdPrimary=true;fireEvent.change(screen.getByLabelText('Сохранённая схема ориентиров'),{target:{value:'primary'}});
  expect(screen.queryByTestId('map-choice')).not.toBeInTheDocument();expect(latest().selectedGeometry).toMatchObject({id:'primary',geometry:null});
  fireEvent.click(screen.getByRole('button',{name:'Камеры и точки 3D'}));expect(await screen.findByTestId('scene-choice')).toHaveAttribute('data-count','loading');
  await act(async()=>{releasePrimary();await primaryGate;});
  await waitFor(()=>expect(screen.getByTestId('scene-choice')).toHaveAttribute('data-count','144'));
  expect(latest().selectedGeometry?.geometry?.cameras[0].center).toEqual(primary.cameras[0].center);
  holdAlternative=true;fireEvent.change(screen.getByLabelText('Сохранённая схема ориентиров'),{target:{value:'loop-173'}});
  expect(screen.getByTestId('scene-choice')).toHaveAttribute('data-count','loading');expect(latest().selectedGeometry).toMatchObject({id:'loop-173',geometry:null});
  fireEvent.change(screen.getByLabelText('Сохранённая схема ориентиров'),{target:{value:'primary'}});
  await waitFor(()=>expect(screen.getByTestId('scene-choice')).toHaveAttribute('data-count','144'));
  await act(async()=>{releaseAlternative();await alternativeGate;});
  expect(screen.getByTestId('scene-choice')).toHaveAttribute('data-choice','primary');
  for(const [props] of jest.mocked(TeachingReconstruction).mock.calls){const selection=props.selectedGeometry;if(!selection?.geometry)continue;
    expect(selection.geometry.cameras.length).toBe(selection.id==='primary'?144:173);
    expect(selection.geometry.cameras[0].center).toEqual(selection.id==='primary'?primary.cameras[0].center:preferred.cameras[0].center);
  }
});
test('a changed reconstruction job never renders even one stale geometry under the new job id',async()=>{
  const {source,read}=await setup();const next=source.geometry(144,2000);
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>({json:async()=>path.startsWith(`/jobs/${nextJob.id}`)?path.endsWith('/geometry-alternatives')?{alternatives:[]}:path.endsWith('/geometry')?next:{phase:'quality_rejected',geometry_available:true,navigation:{phase:'not_prepared'}}:read(path)}) as Response);
  render(<TeachingReview {...base}/>);await waitFor(()=>expect(screen.getByTestId('map-choice')).toHaveAttribute('data-count','173'));
  const start=jest.mocked(TeachingReconstruction).mock.calls.length;fireEvent.click(screen.getByRole('button',{name:'Другая попытка'}));
  expect(screen.queryByTestId('map-choice')).not.toBeInTheDocument();
  await waitFor(()=>expect(latest().selectedGeometry?.geometry?.cameras[0].center).toEqual([2000,0,0]));
  const transitions=jest.mocked(TeachingReconstruction).mock.calls.slice(start).map(call=>call[0].selectedGeometry).filter(value=>value?.jobId===nextJob.id);
  expect(transitions.some(value=>value?.geometry===null)).toBe(true);
  expect(transitions.every(value=>!value?.geometry||value.geometry.cameras[0].center[0]===2000)).toBe(true);
});
test('account change with the same clip id cannot borrow the previous account source, job, geometry or portal',async()=>{
  const {source,read}=await setup(),otherScope='9'.repeat(32),other=await makeUnifiedReviewFixture(otherScope,clip,'Другой аккаунт'),next=other.geometry(173,3000);
  let current=source.root;Object.defineProperty(navigator,'storage',{configurable:true,value:{getDirectory:async()=>current}});
  jobFor=props=>props.scope===scope?job:nextJob;
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>({json:async()=>path.startsWith(`/jobs/${nextJob.id}`)?path.endsWith('/geometry-alternatives')?{preferredAlternativeId:'loop-173',alternatives:[{id:'loop-173',cameras:173,points:1}]}:path.endsWith('/geometry-alternatives/loop-173')?next:{phase:'sparse_complete',source_manifest_sha256:other.manifestSha,geometry_available:false,navigation:{phase:'not_prepared'}}:read(path)}) as Response);
  const view=render(<TeachingReview {...base}/>);await waitFor(()=>expect(screen.getByTestId('map-choice')).toHaveAttribute('data-count','173'));
  fireEvent.click(screen.getByRole('button',{name:'Камеры и точки 3D'}));await screen.findByTestId('scene-choice');
  const start=jest.mocked(TeachingReconstruction).mock.calls.length;current=other.root;view.rerender(<TeachingReview {...base} storageScope={otherScope}/>);
  expect(screen.queryByTestId('map-choice')).not.toBeInTheDocument();expect(screen.queryByTestId('scene-choice')).not.toBeInTheDocument();
  await waitFor(()=>expect(latest().selectedGeometry?.geometry?.cameras[0].center).toEqual([3000,0,0]));
  for(const [props] of jest.mocked(TeachingReconstruction).mock.calls.slice(start)){if(props.scope!==otherScope||!props.selectedGeometry?.geometry)continue;
    expect(props.sourceManifestSha).toBe(other.manifestSha);expect(props.selectedGeometry).toMatchObject({sourceKey:`${otherScope}:${clip}`,jobId:nextJob.id,sourceManifestSha:other.manifestSha});
    expect(props.selectedGeometry.geometry.source_manifest_sha256).toBe(other.manifestSha);
    expect(props.selectedGeometry.geometry.cameras[0].center).toEqual([3000,0,0]);
  }
});
test('primary reconstruction remains inspectable without admitted navigation and viewing never prepares or starts movement',async()=>{
  const {source,primary}=await setup();const openNavigation=jest.fn();
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>({json:async()=>path.endsWith('/geometry-alternatives')?{alternatives:[]}:path.endsWith('/geometry')?primary:{phase:'quality_rejected',source_manifest_sha256:source.manifestSha,geometry_available:true,navigation:{phase:'rejected'}}}) as Response);
  render(<TeachingReview {...base} onOpenNavigation={openNavigation}/>);
  await waitFor(()=>expect(screen.getByTestId('map-choice')).toHaveAttribute('data-count','144'));
  expect(screen.getByLabelText('Сохранённая схема ориентиров')).toHaveValue('primary');
  expect(latest().selectedGeometry).toMatchObject({id:'primary',diagnostic:true});
  expect(screen.getByText('Основная реконструкция · проверка',{selector:'span'})).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Живая проверка'}));expect(openNavigation).toHaveBeenCalledTimes(1);
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>!call[2]?.method)).toBe(true);
  expect(jest.mocked(reconstructionRequest).mock.calls.some(call=>/navigation\/(prepare|.*start)/.test(call[0]))).toBe(false);
});


test('source playback does not hold the parent operation lock or swallow navigation',async()=>{
  await setup();const busy=jest.fn(),navigate=jest.fn();
  render(<TeachingReview {...base} onBusyChange={busy} onOpenNavigation={navigate}/>);
  await waitFor(()=>expect(screen.getByTestId('map-choice')).toHaveAttribute('data-count','173'));
  busy.mockClear();fireEvent.click(screen.getByRole('button',{name:'Пройти по записи'}));
  expect(busy.mock.calls.some(([value])=>value===true)).toBe(false);
  fireEvent.click(screen.getByRole('button',{name:'Живая проверка'}));expect(navigate).toHaveBeenCalledTimes(1);
});
