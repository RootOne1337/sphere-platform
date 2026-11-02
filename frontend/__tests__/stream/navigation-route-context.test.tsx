import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {webcrypto} from 'node:crypto';
import {TextDecoder,TextEncoder} from 'node:util';
import {NavigationRouteContext} from '@/src/features/stream/NavigationRouteContext';
import {reconstructionRequest} from '@/src/features/stream/reconstructionClient';
import {navigationReply} from '@/src/features/stream/routeNavigation';
import type {RouteSource} from '@/src/features/stream/routeSource';
jest.mock('@/src/features/stream/RecordedRouteFrame',()=>({RecordedRouteFrame:({ticks}:{ticks:number})=><div>source-frame-{ticks}</div>}));
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn()}));
const job={id:'a'.repeat(32),key:'b'.repeat(64)},manifestSha='c'.repeat(64);
const source={clip:'d'.repeat(32),scope:'e'.repeat(32),manifestSha,folder:{},rows:[{relative_ticks_90k:0},{relative_ticks_90k:90000}]} as RouteSource;
const data={schema:'sphere-recovered-scene-v1',source_manifest_sha256:manifestSha,
  cameras:[{center:[0,0,0],ticks_90k:0,camera_to_world:[[1,0,0,0],[0,1,0,0],[0,0,1,0]]},
    {center:[0,0,1],ticks_90k:90000,camera_to_world:[[1,0,0,0],[0,1,0,0],[0,0,1,1]]}],points:[[0,0,3,255,255,255]]};
beforeEach(()=>{
  Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});Object.defineProperty(globalThis,'TextDecoder',{configurable:true,value:TextDecoder});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:webcrypto.subtle});jest.clearAllMocks();
  jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue(null);
});
afterEach(()=>jest.restoreAllMocks());

test('delayed catalog cannot flash primary; preferred beats point count and manual choice survives metadata refresh',async()=>{
  const raw=new TextEncoder().encode(JSON.stringify(data));let release:()=>void=()=>{};
  const pending=new Promise<void>(resolve=>{release=resolve;});
  jest.mocked(reconstructionRequest).mockImplementation(async path=>({json:async()=>{
    if(path.endsWith('/geometry-alternatives')){await pending;return {preferredAlternativeId:'preferred',alternatives:[{id:'preferred',cameras:173,label:'Сохранённая 173'},{id:'larger',cameras:240,label:'Другая 240'}]};}
    return {source_manifest_sha256:manifestSha};
  },arrayBuffer:async()=>Uint8Array.from(raw).buffer}) as Response);
  const props={job,source,recordingTitle:'skuter1',assetsReady:false,observation:null};
  const view=render(<NavigationRouteContext {...props}/>);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(call=>call[0].endsWith('/geometry'))).toBe(true));
  expect(screen.queryByText('source-frame-0')).not.toBeInTheDocument();
  await act(async()=>{release();});await screen.findByText('source-frame-0');
  expect(screen.getByLabelText('Схема для живой проверки')).toHaveValue('preferred');
  expect(screen.getByLabelText('Запись и обработка живой карты')).toHaveTextContent('Запись: skuter1 · видео dddddddd · обработка aaaaaaaa');
  fireEvent.change(screen.getByLabelText('Схема для живой проверки'),{target:{value:'larger'}});await screen.findByText('source-frame-0');
  const reads=jest.mocked(reconstructionRequest).mock.calls.length;
  view.rerender(<NavigationRouteContext {...props} source={{...source}} assetsReady/>);
  await act(async()=>{await Promise.resolve();});
  expect(screen.getByLabelText('Схема для живой проверки')).toHaveValue('larger');expect(reconstructionRequest).toHaveBeenCalledTimes(reads);
});

test('same camera counts cannot carry old choices or late geometry into another job identity',async()=>{
  const nextJob={id:'1'.repeat(32),key:'2'.repeat(64)},raw=new TextEncoder().encode(JSON.stringify(data));
  let release:()=>void=()=>{};const gate=new Promise<void>(resolve=>{release=resolve;});let waitOld=false;
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>({json:async()=>path.endsWith('/geometry-alternatives')?
    {preferredAlternativeId:'saved',alternatives:[{id:'saved',label:path.includes(nextJob.id)?'zaezd888 · 173':'skuter1 · 173',cameras:173}]}:{source_manifest_sha256:manifestSha},
    arrayBuffer:async()=>{if(waitOld&&!path.includes(nextJob.id))await gate;return Uint8Array.from(raw).buffer;}}) as Response);
  const view=render(<NavigationRouteContext job={job} source={source} recordingTitle="skuter1" assetsReady={false} observation={null}/>);
  await screen.findByText('source-frame-0');waitOld=true;
  fireEvent.change(screen.getByLabelText('Схема для живой проверки'),{target:{value:'primary'}});
  view.rerender(<NavigationRouteContext job={nextJob} source={source} recordingTitle="zaezd888" assetsReady={false} observation={null}/>);
  expect(screen.queryByRole('option',{name:/skuter1/})).not.toBeInTheDocument();expect(screen.queryByText('source-frame-0')).not.toBeInTheDocument();
  await screen.findByRole('option',{name:/zaezd888/});await screen.findByText('source-frame-0');
  await act(async()=>{release();});
  expect(screen.getByLabelText('Запись и обработка живой карты')).toHaveTextContent('обработка 11111111');
  expect(screen.getByLabelText('Схема для живой проверки')).toHaveValue('saved');
  expect(screen.queryByRole('option',{name:/skuter1/})).not.toBeInTheDocument();
});
test('the saved map, source frame and stream share one view while a live pin is bound to the exact geometry',async()=>{
  const raw=new TextEncoder().encode(JSON.stringify(data)),sha=Buffer.from(await webcrypto.subtle.digest('SHA-256',raw)).toString('hex');
  jest.mocked(reconstructionRequest).mockImplementation(async()=>({json:async()=>({source_manifest_sha256:manifestSha,alternatives:[]}),arrayBuffer:async()=>Uint8Array.from(raw).buffer}) as Response);
  const props={job,source,assetsReady:true,comparison:<div>live-frame</div>};
  const view=render(<NavigationRouteContext {...props} observation={null}/>);
  await screen.findByText('source-frame-0');expect(screen.getByText('live-frame')).toBeInTheDocument();
  const parsed=navigationReply({id:'s',captureEpoch:'epoch',sequence:1,jpegSha256:'f'.repeat(64),geometrySha256:sha,referenceTicks90k:90000,computeMs:10,method:'descriptor_pnp',physicalActions:0,executionQualified:false,groundRoute:false,
    pose:{state:'localized',reason:'verified',inliers:30,segment:0,progress_units:1,polyline_px:[],center:[0,0,1],rotation:[1,0,0,0,1,0,0,0,1]}},'s','epoch',1,'f'.repeat(64))!;
  const capturedAt=performance.now();view.rerender(<NavigationRouteContext {...props} observation={{reply:parsed,capturedAt,answeredAt:capturedAt+10}}/>);
  await screen.findByLabelText('Подтверждённое живое положение');await screen.findByText('source-frame-90000');
  const calls=jest.mocked(reconstructionRequest).mock.calls.length;
  view.rerender(<NavigationRouteContext {...props} job={{...job}} observation={{reply:parsed,capturedAt,answeredAt:capturedAt+10}}/>);
  await act(async()=>{await Promise.resolve();});expect(reconstructionRequest).toHaveBeenCalledTimes(calls);
  expect(screen.getByText('source-frame-90000')).toBeInTheDocument();
  view.rerender(<NavigationRouteContext {...props} observation={{reply:{...parsed,geometrySha256:'0'.repeat(64)},capturedAt,answeredAt:capturedAt+10}}/>);
  await waitFor(()=>expect(screen.queryByLabelText('Подтверждённое живое положение')).not.toBeInTheDocument());
  expect(jest.mocked(reconstructionRequest).mock.calls.every(c=>c[2]?.method!=='POST')).toBe(true);
});
test('a source mismatch never displays the unrelated map or a live pin',async()=>{
  const raw=new TextEncoder().encode(JSON.stringify({...data,source_manifest_sha256:'0'.repeat(64)}));
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({source_manifest_sha256:manifestSha,alternatives:[]}),arrayBuffer:async()=>raw.buffer} as Response);
  render(<NavigationRouteContext job={job} source={source} assetsReady observation={null} comparison={<div>live-frame</div>}/>);
  await screen.findByText(/Геометрия относится к другой записи/);
  expect(screen.queryByLabelText('Обзор ориентиров и камер')).not.toBeInTheDocument();expect(screen.getByText('live-frame')).toBeInTheDocument();
});

test('a short display gap retains only a labelled past measurement, never a fresh live pin',async()=>{
  const raw=new TextEncoder().encode(JSON.stringify(data)),sha=Buffer.from(await webcrypto.subtle.digest('SHA-256',raw)).toString('hex');
  jest.mocked(reconstructionRequest).mockImplementation(async()=>({json:async()=>({source_manifest_sha256:manifestSha,alternatives:[]}),arrayBuffer:async()=>Uint8Array.from(raw).buffer}) as Response);
  const props={job,source,assetsReady:true,busy:true};
  const view=render(<NavigationRouteContext {...props} observation={null}/>);
  await screen.findByText('source-frame-0');
  jest.useFakeTimers();
  try{
    const parsed=navigationReply({id:'s',captureEpoch:'epoch',sequence:1,jpegSha256:'f'.repeat(64),geometrySha256:sha,referenceTicks90k:90000,computeMs:10,method:'descriptor_pnp',physicalActions:0,executionQualified:false,groundRoute:false,
      pose:{state:'localized',reason:'verified',inliers:30,segment:0,progress_units:1,polyline_px:[],center:[0,0,1],rotation:[1,0,0,0,1,0,0,0,1]}},'s','epoch',1,'f'.repeat(64))!;
    const capturedAt=performance.now(),observation={reply:parsed,capturedAt,answeredAt:capturedAt+10};
    view.rerender(<NavigationRouteContext {...props} observation={observation}/>);
    expect(screen.getByLabelText('Подтверждённое живое положение')).toBeInTheDocument();
    act(()=>jest.advanceTimersByTime(260));
    expect(screen.queryByLabelText('Подтверждённое живое положение')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Последняя измеренная позиция · ожидаем обновление')).toBeInTheDocument();
    expect(screen.getByText('Слежение за маршрутом')).toBeInTheDocument();
    expect(screen.getByLabelText('Состояние локализации')).toHaveClass('h-10');
    expect(screen.getByLabelText('Состояние живого маркера')).toHaveClass('h-10');
    expect(screen.queryByText(/Положение сейчас не подтверждено/)).not.toBeInTheDocument();
    view.rerender(<NavigationRouteContext {...props} observation={{...observation,reply:{...parsed,geometrySha256:'0'.repeat(64)}}}/>);
    expect(screen.queryByLabelText('Последняя измеренная позиция · ожидаем обновление')).not.toBeInTheDocument();
    view.rerender(<NavigationRouteContext {...props} observation={observation}/>);
    act(()=>jest.advanceTimersByTime(750));
    expect(screen.queryByLabelText('Последняя измеренная позиция · ожидаем обновление')).not.toBeInTheDocument();
    expect(screen.getByText(/Положение сейчас не подтверждено/)).toBeInTheDocument();
    view.rerender(<NavigationRouteContext {...props} busy={false} observation={observation}/>);
    expect(screen.queryByText(/Положение сейчас не подтверждено/)).not.toBeInTheDocument();
  }finally{view.unmount();jest.useRealTimers();}
});
