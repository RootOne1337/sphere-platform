import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {RecordedControlReplay} from '@/src/features/stream/RecordedControlReplay';
import {reconstructionRequest} from '@/src/features/stream/reconstructionClient';
import {readRecordedRouteFrame,type RouteSource} from '@/src/features/stream/routeSource';
import {saveRouteDebugReport} from '@/src/features/stream/routeDebugStorage';
import {TextEncoder,TextDecoder} from 'util';
jest.mock('@/src/features/stream/reconstructionClient',()=>({reconstructionRequest:jest.fn()}));
jest.mock('@/src/features/stream/routeSource',()=>({readRecordedRouteFrame:jest.fn(async()=>{})}));
jest.mock('@/src/features/stream/routeMapProjection',()=>({readImportedRouteGeometry:()=>({cameras:[]})}));
jest.mock('@/src/features/stream/routeDebugStorage',()=>({saveRouteDebugReport:jest.fn(async()=>({state:'saved'}))}));
jest.mock('@/src/features/stream/RouteDebugArchive',()=>({RouteDebugArchive:()=>null}));
const job={id:'a'.repeat(32),key:'b'.repeat(64)},source={clip:'1'.repeat(32),scope:'2'.repeat(32),manifestSha:'3'.repeat(64),folder:{},rows:[0,18000,36000].map((relative_ticks_90k,index)=>({index,relative_ticks_90k}))} as RouteSource;
let busy:jest.Mock;
beforeEach(()=>{
  jest.clearAllMocks();busy=jest.fn();
  Object.assign(globalThis,{TextEncoder,TextDecoder});
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'cccccccc-cccc-cccc-cccc-cccccccccccc'});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async()=>new Uint8Array(32).fill(170).buffer}});
  jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({clearRect:jest.fn(),drawImage:jest.fn()} as never);
  jest.spyOn(HTMLCanvasElement.prototype,'toBlob').mockImplementation(callback=>{
    const blob=new Blob(['jpeg']);Object.defineProperty(blob,'arrayBuffer',{value:async()=>new ArrayBuffer(4)});callback(blob);
  });
  jest.mocked(reconstructionRequest).mockImplementation(async(path,_job,options)=>{
    if(path.endsWith('/geometry'))return {arrayBuffer:async()=>new TextEncoder().encode('{}').buffer} as Response;
    if(path.endsWith('replay-start'))return {json:async()=>({replayOnly:true,mode:'recorded_replay',physicalActions:0})} as Response;
    if(path.endsWith('replay-observe')){
      const body=JSON.parse(String(options?.body));return {json:async()=>({...body,jpegSha256:'aa'.repeat(32),geometrySha256:'aa'.repeat(32),replayOnly:true,computeMs:1,physicalActions:0,executionQualified:false,groundRoute:false,method:'descriptor_pnp',
        pose:{state:'confirming',reason:'relative_camera_pose_not_clearance_or_arrival',inliers:30,segment:0,progress_units:0,polyline_px:[]},
        walk:{schema:'sphere-walk-plan-v1',phase:'waiting',reason:'walk_confirming_start',stick:[0,0],progressFraction:null,maxStick:.35,maxSeconds:60,groundRoute:false,executionQualified:false,cameraBodyAssumption:true}})} as Response;
    }
    return {json:async()=>({phase:'closed',physicalActions:0})} as Response;
  });
});
afterEach(()=>jest.restoreAllMocks());
const view=(extra:object={})=>render(<RecordedControlReplay job={job} source={source} assetsReady onBusyChange={busy} {...extra}/>);
test('a prepared recording starts without a live stream, native input owner or time oracle',async()=>{
  view();expect(reconstructionRequest).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'Запустить проверку записи'}));
  await waitFor(()=>expect(readRecordedRouteFrame).toHaveBeenCalled());
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[0].endsWith('replay-observe'))).toBe(true));
  const calls=jest.mocked(reconstructionRequest).mock.calls;
  expect(calls.every(c=>!c[0].includes('walk-start')&&!c[0].includes('navigation/start'))).toBe(true);
  const body=JSON.parse(String(calls.find(c=>c[0].endsWith('replay-observe'))?.[2]?.body));
  expect(Object.keys(body).sort()).toEqual(['captureEpoch','id','jpeg','sequence']);
  fireEvent.click(screen.getByRole('button',{name:'Стоп проверки записи'}));
  await waitFor(()=>expect(saveRouteDebugReport).toHaveBeenCalled());
  expect(busy).toHaveBeenLastCalledWith(false);
});
test('an unprepared route cannot be tested and mount never starts a session',()=>{
  view({assetsReady:false});expect(screen.getByRole('button',{name:'Запустить проверку записи'})).toBeDisabled();expect(reconstructionRequest).not.toHaveBeenCalled();
});
test('uncertain closure keeps the same session and blocks switching into live control',async()=>{
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  jest.mocked(reconstructionRequest).mockImplementation(async(...args)=>{if(args[0].endsWith('replay-stop'))throw Error('offline');return original(...args);});
  view();fireEvent.click(screen.getByRole('button',{name:'Запустить проверку записи'}));
  await waitFor(()=>expect(readRecordedRouteFrame).toHaveBeenCalled());
  fireEvent.click(screen.getByRole('button',{name:'Стоп проверки записи'}));
  await screen.findByText(/Закрытие проверки записи не подтверждено/);
  expect(screen.getByRole('button',{name:'Запустить проверку записи'})).toBeDisabled();expect(busy).toHaveBeenLastCalledWith(true);
});
test('a response delivered after stop is never drawn or recorded',async()=>{
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  let resolve:(value:Response)=>void=()=>{};
  jest.mocked(reconstructionRequest).mockImplementation(async(...args)=>args[0].endsWith('replay-observe')?new Promise<Response>(r=>{resolve=r;}):original(...args));
  view();fireEvent.click(screen.getByRole('button',{name:'Запустить проверку записи'}));
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[0].endsWith('replay-observe'))).toBe(true));
  fireEvent.click(screen.getByRole('button',{name:'Стоп проверки записи'}));
  await act(async()=>resolve({json:async()=>{throw Error('retired response must not be read');}} as unknown as Response));
  expect(screen.getByText('Кадров: 0')).toBeInTheDocument();
});
test('a response from another geometry is rejected even for the same recording and session',async()=>{
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  jest.mocked(reconstructionRequest).mockImplementation(async(...args)=>{
    const response=await original(...args);
    if(!args[0].endsWith('replay-observe'))return response;
    return {json:async()=>({...await response.json(),geometrySha256:'bb'.repeat(32)})} as Response;
  });
  view();fireEvent.click(screen.getByRole('button',{name:'Запустить проверку записи'}));
  await screen.findByText(/replay_reply_not_bound/);
  expect(screen.getByText('Кадров: 0')).toBeInTheDocument();
});
