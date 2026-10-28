import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {WalkingRoutePilot} from '@/src/features/stream/WalkingRoutePilot';
import {reconstructionRequest} from '@/src/features/stream/reconstructionClient';
import type {WalkInputLease} from '@/src/features/stream/walkPilot';
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn()}));
const job={id:'a'.repeat(32),key:'b'.repeat(64)},binding={captureEpoch:'e'.repeat(32),width:960,height:540};
let frames:VideoFrameRequestCallback[],lease:WalkInputLease,open:jest.Mock,busy:jest.Mock,element:HTMLVideoElement;
beforeEach(()=>{
  jest.clearAllMocks();frames=[];busy=jest.fn();
  lease={active:()=>true,set:jest.fn(),close:jest.fn(async()=>true)};open=jest.fn(async()=>lease);
  element={requestVideoFrameCallback:(f:VideoFrameRequestCallback)=>{frames.push(f);return frames.length;},cancelVideoFrameCallback:jest.fn()} as unknown as HTMLVideoElement;
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'cccccccc-cccc-cccc-cccc-cccccccccccc'});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async()=>new Uint8Array(32).fill(170).buffer}});
  jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({clearRect:jest.fn(),drawImage:jest.fn()} as never);
  jest.spyOn(HTMLCanvasElement.prototype,'toBlob').mockImplementation(callback=>{
    const blob=new Blob(['jpeg'],{type:'image/jpeg'});Object.defineProperty(blob,'arrayBuffer',{value:async()=>new ArrayBuffer(4)});callback(blob);
  });
  jest.mocked(reconstructionRequest).mockImplementation(async(path,_job,init)=>{
    if(path.endsWith('/walk-start'))return {json:async()=>({phase:'observing',id:'c'.repeat(32),physicalActions:0,mode:'foot_camera_trace_v1',maxSeconds:60})} as Response;
    if(path.endsWith('/observe'))return {json:async()=>({id:'c'.repeat(32),captureEpoch:binding.captureEpoch,sequence:JSON.parse(String(init?.body)).sequence,
      jpegSha256:'aa'.repeat(32),computeMs:1,method:'descriptor_pnp',physicalActions:0,executionQualified:false,groundRoute:false,
      pose:{state:'localized',reason:'relative_camera_pose_not_clearance_or_arrival',inliers:40,segment:0,progress_units:0,polyline_px:[]},
      walk:{schema:'sphere-walk-plan-v1',phase:'following',reason:'walk_camera_relative_pursuit',stick:[.05,-.2],progressFraction:0,maxStick:.35,maxSeconds:60,groundRoute:false,executionQualified:false,cameraBodyAssumption:true}})} as Response;
    return {json:async()=>({phase:'closed'})} as Response;
  });
});
afterEach(()=>jest.restoreAllMocks());
const view=(extra:Record<string,unknown>={})=>render(<WalkingRoutePilot job={job} clip="clip" video={{current:element}} ready binding={binding} assetsReady input={{issue:null,open}} observerBusy={false} onBusyChange={busy} {...extra}/>);
function fresh(){act(()=>frames.shift()!(performance.now(),{} as VideoFrameCallbackMetadata));}
function start(){fresh();fireEvent.click(screen.getByRole('checkbox',{name:/Персонаж пешком/}));fireEvent.click(screen.getByRole('button',{name:'Запустить пеший тест · 60 с'}));}

test('mount, confirmation and map readiness never themselves open native input',()=>{
  view({assetsReady:false});fresh();fireEvent.click(screen.getByRole('checkbox',{name:/Персонаж пешком/}));
  expect(screen.getByRole('button',{name:'Запустить пеший тест · 60 с'})).toBeDisabled();
  expect(open).not.toHaveBeenCalled();expect(reconstructionRequest).not.toHaveBeenCalled();
});
test('explicit start sends a fresh bound correction and stop waits for native closure',async()=>{
  view();start();await waitFor(()=>expect(lease.set).toHaveBeenCalledWith([.05,-.2]));
  expect(jest.mocked(reconstructionRequest).mock.calls[0][0]).toMatch(/walk-start$/);
  expect(screen.getByRole('status')).toHaveTextContent(/Идём к ближайшей точке/);
  fireEvent.click(screen.getByRole('button',{name:'Стоп пешего теста · Esc'}));
  await waitFor(()=>expect(lease.close).toHaveBeenCalled());
  await screen.findByText('Освобождение: CLOSED');
  expect(busy).toHaveBeenLastCalledWith(false);
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(c=>c[0].endsWith('/walk-start'))).toHaveLength(1);
});
test('unknown native close blocks another start and never claims successful release',async()=>{
  lease.close=jest.fn(async()=>false);view();start();await waitFor(()=>expect(lease.set).toHaveBeenCalled());
  fireEvent.keyDown(window,{code:'Escape'});
  await screen.findByText(/Освобождение ввода НЕ подтверждено/);
  expect(screen.getByText('Освобождение: UNKNOWN')).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Запустить пеший тест · 60 с'})).toBeDisabled();
});
test('stopping an uncertain native open awaits that same lease and never sends its late plan',async()=>{
  let settle:(lease:WalkInputLease)=>void=()=>{};open.mockImplementation(()=>new Promise(resolve=>{settle=resolve;}));
  view();start();await waitFor(()=>expect(open).toHaveBeenCalled());
  fireEvent.keyDown(window,{code:'Escape'});
  expect(screen.getByText('Освобождение: ожидается')).toBeInTheDocument();
  await act(async()=>{settle(lease);});
  await waitFor(()=>expect(screen.getByText('Освобождение: CLOSED')).toBeInTheDocument());
  expect(lease.set).not.toHaveBeenCalled();
  expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[0].endsWith('/observe'))).toBe(false);
});
test('unmount retires the session and closes its input lease',async()=>{
  const rendered=view();start();await waitFor(()=>expect(lease.set).toHaveBeenCalled());
  rendered.unmount();await waitFor(()=>expect(lease.close).toHaveBeenCalled());
});
test('a late localization reply after Stop cannot produce a physical correction',async()=>{
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  let finish:(value:Response)=>void=()=>{};
  jest.mocked(reconstructionRequest).mockImplementation(async(...args)=>args[0].endsWith('/observe')?new Promise(resolve=>{finish=resolve;}):original(...args));
  view();start();await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[0].endsWith('/observe'))).toBe(true));
  fireEvent.keyDown(window,{code:'Escape'});await screen.findByText('Освобождение: CLOSED');
  const response=await original(`/jobs/${job.id}/navigation/observe`,job,{body:JSON.stringify({sequence:1})});
  await act(async()=>{finish(response);});expect(lease.set).not.toHaveBeenCalled();
});
test('an expired bound result closes input before applying its vector',async()=>{
  let now=1000;const clock=jest.spyOn(performance,'now').mockImplementation(()=>now);
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  jest.mocked(reconstructionRequest).mockImplementation(async(...args)=>{
    const value=await original(...args);if(args[0].endsWith('/observe'))now=1300;return value;
  });
  view();start();await screen.findByText('Освобождение: CLOSED');
  expect(lease.set).not.toHaveBeenCalled();expect(screen.getByRole('status')).toHaveTextContent('Нет свежего решения');clock.mockRestore();
});
