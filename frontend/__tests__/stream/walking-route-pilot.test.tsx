import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {WalkingRoutePilot} from '@/src/features/stream/WalkingRoutePilot';
import {reconstructionRequest} from '@/src/features/stream/reconstructionClient';
import type {WalkInputLease} from '@/src/features/stream/walkPilot';
import {TeachingContacts,type TeachingInput} from '@/src/features/stream/teachingContacts';
import {saveRouteDebugReport} from '@/src/features/stream/routeDebugStorage';
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn()}));
jest.mock('@/src/features/stream/routeDebugStorage',()=>({saveRouteDebugReport:jest.fn(async()=>({state:'saved'}))}));
const job={id:'a'.repeat(32),key:'b'.repeat(64)},binding={captureEpoch:'e'.repeat(32),width:960,height:540};
let frames:VideoFrameRequestCallback[],lease:WalkInputLease,open:jest.Mock,busy:jest.Mock,element:HTMLVideoElement;
let videoRef:{current:HTMLVideoElement};
beforeEach(()=>{
  jest.clearAllMocks();frames=[];busy=jest.fn();
  lease={active:()=>true,set:jest.fn(),close:jest.fn(async()=>true)};open=jest.fn(async()=>lease);
  element={requestVideoFrameCallback:(f:VideoFrameRequestCallback)=>{frames.push(f);return frames.length;},cancelVideoFrameCallback:jest.fn()} as unknown as HTMLVideoElement;
  videoRef={current:element};
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'cccccccc-cccc-cccc-cccc-cccccccccccc'});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async()=>new Uint8Array(32).fill(170).buffer}});
  jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({clearRect:jest.fn(),drawImage:jest.fn()} as never);
  jest.spyOn(HTMLCanvasElement.prototype,'toBlob').mockImplementation(callback=>{
    const blob=new Blob(['jpeg'],{type:'image/jpeg'});Object.defineProperty(blob,'arrayBuffer',{value:async()=>new ArrayBuffer(4)});callback(blob);
  });
  jest.mocked(reconstructionRequest).mockImplementation(async(path,_job,init)=>{
    if(path.endsWith('/walk-start'))return {json:async()=>({phase:'observing',id:'c'.repeat(32),physicalActions:0,mode:'foot_camera_trace_v1',maxSeconds:60,startMode:JSON.parse(String(init?.body)).startMode,cameraTracking:JSON.parse(String(init?.body)).cameraTracking,cameraControl:JSON.parse(String(init?.body)).cameraControl})} as Response;
    if(path.endsWith('/observe'))return {json:async()=>({id:'c'.repeat(32),captureEpoch:binding.captureEpoch,sequence:JSON.parse(String(init?.body)).sequence,
      jpegSha256:'aa'.repeat(32),computeMs:1,method:'descriptor_pnp',physicalActions:0,executionQualified:false,groundRoute:false,
      pose:{state:'localized',reason:'relative_camera_pose_not_clearance_or_arrival',inliers:40,segment:0,progress_units:0,polyline_px:[]},
      walk:{schema:'sphere-walk-plan-v1',phase:'following',reason:'walk_camera_relative_pursuit',stick:[.05,-.2],progressFraction:0,maxStick:.35,maxSeconds:60,groundRoute:false,executionQualified:false,cameraBodyAssumption:true}})} as Response;
    return {json:async()=>({phase:'closed'})} as Response;
  });
});
afterEach(()=>jest.restoreAllMocks());
const view=(extra:Record<string,unknown>={})=>render(<WalkingRoutePilot job={job} clip="clip" video={videoRef} ready binding={binding} assetsReady input={{issue:null,open}} observerBusy={false} onBusyChange={busy} {...extra}/>);
function fresh(){act(()=>frames.shift()!(performance.now(),{} as VideoFrameCallbackMetadata));}
function start(){fresh();fireEvent.click(screen.getByRole('checkbox',{name:/Персонаж пешком/}));fireEvent.click(screen.getByRole('button',{name:'Запустить пеший тест · 60 с'}));}

test('camera mode blocks start until its separate free-screen area is calibrated',()=>{
  view({input:{issue:null,cameraIssue:'Укажите область камеры',open}});start();
  expect(screen.getByRole('button',{name:'Запустить пеший тест · 60 с'})).toBeDisabled();
  expect(open).not.toHaveBeenCalled();
});

test('negotiated binary JPEG avoids base64 and keeps session/epoch/sequence binding',async()=>{
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  jest.mocked(reconstructionRequest).mockImplementation(async(path,target,init)=>{
    if(path.endsWith('/observe-jpeg')){
      const h=new Headers(init?.headers);
      expect(init?.body).toBeInstanceOf(Blob);expect(h.get('Content-Type')).toBe('image/jpeg');
      expect(h.get('X-Route-Session')).toBe('c'.repeat(32));expect(h.get('X-Capture-Epoch')).toBe(binding.captureEpoch);
      return original(path.replace('/observe-jpeg','/observe'),target,{body:JSON.stringify({sequence:Number(h.get('X-Frame-Sequence'))})});
    }
    const response=await original(path,target,init);
    if(!path.endsWith('/walk-start'))return response;
    return {json:async()=>({...await response.json(),observationProtocol:'jpeg_binary_v1'})} as Response;
  });
  const reader=jest.spyOn(FileReader.prototype,'readAsDataURL');view();
  fireEvent.click(screen.getByRole('checkbox',{name:/Диагностика: до 60 кадров/}));start();
  await waitFor(()=>expect(lease.set).toHaveBeenCalled());
  expect(reader).not.toHaveBeenCalled();
  expect(jest.mocked(reconstructionRequest).mock.calls.some(([path])=>path.endsWith('/observe-jpeg'))).toBe(true);
  fireEvent.keyDown(window,{code:'Escape'});await screen.findByText('Освобождение: CLOSED');
});
test('camera pulse is a separate acknowledged operation while the movement stick is neutral',async()=>{
  jest.spyOn(performance,'now').mockReturnValue(1000);
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  jest.mocked(reconstructionRequest).mockImplementation(async(...args)=>{
    const response=await original(...args);if(!args[0].endsWith('/observe'))return response;
    const value=await response.json();value.pose.rotation=[1,0,0,0,1,0,0,0,1];value.walk.targetCamera=[1,0,1];
    return {json:async()=>value} as Response;
  });
  const order:string[]=[];lease.set=jest.fn(()=>{order.push('stick');});
  lease.canLook=()=>true;lease.drag=jest.fn(async()=>{order.push('camera');return true;});
  view({input:{issue:null,cameraIssue:null,open}});start();
  await waitFor(()=>expect(lease.drag).toHaveBeenCalledWith(0,1250));
  expect(order.indexOf('camera')).toBeLessThan(order.indexOf('stick'));
  expect(jest.mocked(lease.set).mock.calls.every(([v])=>Math.hypot(...v)===0)).toBe(true);
  expect(screen.getByRole('status')).toHaveTextContent(/проверяем отклик/i);
  fireEvent.keyDown(window,{code:'Escape'});await screen.findByText('Освобождение: CLOSED');
});
test('an old service cannot silently open camera-enabled input without acknowledging that mode',async()=>{
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  jest.mocked(reconstructionRequest).mockImplementation(async(...args)=>{
    const response=await original(...args);if(!args[0].endsWith('/walk-start'))return response;
    const value=await response.json();delete value.cameraTracking;return {json:async()=>value} as Response;
  });
  view({input:{issue:null,cameraIssue:null,open}});start();
  await screen.findByText('Освобождение: CLOSED');expect(open).not.toHaveBeenCalled();
});
test('a short startup video gap waits for new presentation before opening Android input',async()=>{
  let now=1000;const clock=jest.spyOn(performance,'now').mockImplementation(()=>now);
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  let settle:(response:Response)=>void=()=>{};
  jest.mocked(reconstructionRequest).mockImplementation(async(...args)=>args[0].endsWith('/walk-start')?
    new Promise(resolve=>{settle=resolve;}):original(...args));
  try{
    view();start();await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalled());
    now=1320;await act(async()=>{settle(await original(`/jobs/${job.id}/navigation/walk-start`,job,{body:JSON.stringify({startMode:'recognized_route',cameraTracking:false})}));});
    await screen.findByText('Ждём свежий кадр перед открытием ввода. Касаний ещё нет.');
    expect(open).not.toHaveBeenCalled();now=1350;fresh();
    await waitFor(()=>expect(open).toHaveBeenCalledTimes(1));
    fireEvent.keyDown(window,{code:'Escape'});await screen.findByText('Освобождение: CLOSED');
  }finally{clock.mockRestore();}
});

test('mount, confirmation and map readiness never themselves open native input',()=>{
  view({assetsReady:false});fresh();fireEvent.click(screen.getByRole('checkbox',{name:/Персонаж пешком/}));
  expect(screen.getByRole('button',{name:'Запустить пеший тест · 60 с'})).toBeDisabled();
  expect(open).not.toHaveBeenCalled();expect(reconstructionRequest).not.toHaveBeenCalled();
});

test('Stop during encoding allows a fresh restart without waiting for the old browser callback',async()=>{
  jest.spyOn(performance,'now').mockReturnValue(1000);
  const callbacks:BlobCallback[]=[];
  jest.mocked(HTMLCanvasElement.prototype.toBlob).mockImplementation(done=>{callbacks.push(done);});
  view();fireEvent.click(screen.getByRole('checkbox',{name:/Диагностика: до 60 кадров/}));start();
  await waitFor(()=>expect(callbacks).toHaveLength(1));
  fireEvent.keyDown(window,{code:'Escape'});await screen.findByText('Освобождение: CLOSED');
  fresh();fireEvent.click(screen.getByRole('button',{name:'Запустить пеший тест · 60 с'}));
  await waitFor(()=>expect(callbacks).toHaveLength(2));
  const blob=new Blob(['jpeg'],{type:'image/jpeg'});Object.defineProperty(blob,'arrayBuffer',{value:async()=>new ArrayBuffer(4)});
  await act(async()=>{callbacks[1](blob);});await waitFor(()=>expect(lease.set).toHaveBeenCalledWith([.05,-.2]));
  const commands=jest.mocked(lease.set).mock.calls.length;
  await act(async()=>{callbacks[0](blob);});expect(jest.mocked(lease.set).mock.calls.length).toBe(commands);
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(([path])=>path.endsWith('/observe'))).toHaveLength(1);
  fireEvent.keyDown(window,{code:'Escape'});await screen.findByText('Освобождение: CLOSED');
});

test('recognized-route restart is explicit and changing acquisition mode requires a new confirmation',async()=>{
  view();expect(screen.getByLabelText('Точка запуска пешего теста')).toHaveValue('recognized_route');
  fresh();fireEvent.click(screen.getByRole('checkbox',{name:/Персонаж пешком/}));
  fireEvent.change(screen.getByLabelText('Точка запуска пешего теста'),{target:{value:'beginning'}});
  expect(screen.getByRole('button',{name:'Запустить пеший тест · 60 с'})).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox',{name:/Персонаж пешком/}));
  fireEvent.click(screen.getByRole('button',{name:'Запустить пеший тест · 60 с'}));
  await waitFor(()=>expect(open).toHaveBeenCalled());
  expect(JSON.parse(String(jest.mocked(reconstructionRequest).mock.calls[0][2]?.body)).startMode).toBe('beginning');
  fireEvent.keyDown(window,{code:'Escape'});await screen.findByText('Освобождение: CLOSED');
});

test('a service that does not acknowledge acquisition mode cannot open Android input',async()=>{
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  jest.mocked(reconstructionRequest).mockImplementation(async(...args)=>{
    const response=await original(...args);if(!args[0].endsWith('/walk-start'))return response;
    const value=await response.json();delete value.startMode;return {json:async()=>value} as Response;
  });
  view();start();await screen.findByText('Освобождение: CLOSED');expect(open).not.toHaveBeenCalled();
});
test('explicit start sends a fresh bound correction and stop waits for native closure',async()=>{
  // Freshness failures have separate tests. This fixture supplies one RVFC,
  // so its clock must not age while unrelated suites/GC are running.
  jest.spyOn(performance,'now').mockReturnValue(1000);
  view();start();await waitFor(()=>expect(lease.set).toHaveBeenCalledWith([.05,-.2]));
  expect(jest.mocked(reconstructionRequest).mock.calls[0][0]).toMatch(/walk-start$/);
  expect(screen.getByRole('status')).toHaveTextContent(/Идём к ближайшей точке/);
  fireEvent.click(screen.getByRole('button',{name:'Стоп пешего теста · Esc'}));
  await waitFor(()=>expect(lease.close).toHaveBeenCalled());
  await screen.findByText('Освобождение: CLOSED');
  expect(busy).toHaveBeenLastCalledWith(false);
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(c=>c[0].endsWith('/walk-start'))).toHaveLength(1);
});

test('a 320 ms source pause neutralizes without restarting and resumes only on a new reply',async()=>{
  let now=1000;const clock=jest.spyOn(performance,'now').mockImplementation(()=>now);lease.neutral=jest.fn();
  try{
    view();start();await waitFor(()=>expect(lease.set).toHaveBeenCalled());
    const before=jest.mocked(lease.set).mock.calls.length;now=1320;
    await waitFor(()=>expect(lease.neutral).toHaveBeenCalled());expect(lease.close).not.toHaveBeenCalled();
    expect(jest.mocked(lease.set).mock.calls).toHaveLength(before);
    now=1360;fresh();await waitFor(()=>expect(jest.mocked(lease.set).mock.calls.length).toBeGreaterThan(before));
    expect(lease.close).not.toHaveBeenCalled();fireEvent.keyDown(window,{code:'Escape'});await screen.findByText('Освобождение: CLOSED');
  }finally{clock.mockRestore();}
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
test('an expired bound result neutralizes input and never applies its vector',async()=>{
  let now=1000;const clock=jest.spyOn(performance,'now').mockImplementation(()=>now);
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  jest.mocked(reconstructionRequest).mockImplementation(async(...args)=>{
    const value=await original(...args);if(args[0].endsWith('/observe'))now=1300;return value;
  });
  view();start();await screen.findByText(/Стик в центре: ждём новое свежее решение/);now=2400;
  await screen.findByText('Освобождение: CLOSED');
  expect(jest.mocked(lease.set).mock.calls.every(([v])=>v[0]===0&&v[1]===0)).toBe(true);clock.mockRestore();
});

test('four delivery expirations never replay old vectors or exhaust geometric recovery',async()=>{
  let now=1000,queries=0;const clock=jest.spyOn(performance,'now').mockImplementation(()=>now);
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  jest.mocked(reconstructionRequest).mockImplementation(async(...args)=>{
    const response=await original(...args);
    if(args[0].endsWith('/observe')){
      queries++;now+=queries%2===0?300:110;
      frames.shift()?.(now,{} as VideoFrameCallbackMetadata);
    }
    return response;
  });
  try{
    view();start();
    await waitFor(()=>expect(jest.mocked(lease.set).mock.calls.filter(([v])=>Math.hypot(...v)>0).length).toBeGreaterThanOrEqual(5),{timeout:2500});
    expect(jest.mocked(lease.set).mock.calls.filter(([v])=>Math.hypot(...v)===0).length).toBeGreaterThanOrEqual(4);
    expect(lease.close).not.toHaveBeenCalled();
    fireEvent.keyDown(window,{code:'Escape'});await screen.findByText('Освобождение: CLOSED');
  }finally{clock.mockRestore();}
});
test('fresh UNKNOWN replies end a transport wait without acquiring movement or forcing a two-second restart',async()=>{
  let now=1000,queries=0;const clock=jest.spyOn(performance,'now').mockImplementation(()=>now);
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  jest.mocked(reconstructionRequest).mockImplementation(async(...args)=>{
    const response=await original(...args);if(!args[0].endsWith('/observe'))return response;
    const value=await response.json();queries++;now+=queries===1?300:200;
    value.pose={...value.pose,state:'unknown',inliers:0};value.walk={...value.walk,phase:'waiting',stick:[0,0],reason:'walk_confirming_start'};
    if(queries<=15)frames.shift()?.(now,{} as VideoFrameCallbackMetadata);
    return {json:async()=>value} as Response;
  });
  try{
    view();start();await waitFor(()=>expect(queries).toBeGreaterThanOrEqual(15));
    expect(lease.close).not.toHaveBeenCalled();
    expect(jest.mocked(lease.set).mock.calls.every(([v])=>Math.hypot(...v)===0)).toBe(true);
    fireEvent.keyDown(window,{code:'Escape'});await screen.findByText('Освобождение: CLOSED');
  }finally{clock.mockRestore();}
});

test('a localized start refusal is not presented as an Android ACK failure',async()=>{
  jest.spyOn(performance,'now').mockReturnValue(1000);
  const original=jest.mocked(reconstructionRequest).getMockImplementation()!;
  jest.mocked(reconstructionRequest).mockImplementation(async(...args)=>{
    const response=await original(...args);if(!args[0].endsWith('/observe'))return response;
    const value=await response.json();value.walk={...value.walk,phase:'stopped',reason:'walk_start_outside_recorded_beginning',stick:[0,0]};
    return {json:async()=>value} as Response;
  });
  view();start();await screen.findByText('Освобождение: CLOSED');
  expect(screen.getByText(/Место узнано, но команда движения не выдавалась/)).toBeInTheDocument();
  expect(screen.queryByText(/Android ещё не подтвердил касание/)).not.toBeInTheDocument();
});

test('diagnostic canvas painting is not performed inside the live input cycle',async()=>{
  let now=1000;const clock=jest.spyOn(performance,'now').mockImplementation(()=>now);
  const paintTimes:number[]=[];
  jest.mocked(HTMLCanvasElement.prototype.getContext).mockReturnValue({clearRect:jest.fn(),drawImage:jest.fn((source:CanvasImageSource)=>{
    if(source instanceof HTMLCanvasElement){paintTimes.push(now);now+=300;}
  })} as never);
  try{
    view();start();await waitFor(()=>expect(lease.set).toHaveBeenCalled());
    expect(paintTimes).toEqual([]);expect(now).toBe(1000);
    expect(jest.mocked(lease.set).mock.calls.some(([v])=>Math.hypot(...v)>0)).toBe(true);
    fireEvent.keyDown(window,{code:'Escape'});await screen.findByText('Освобождение: CLOSED');
  }finally{clock.mockRestore();}
});

test('fresh pose plans go through the real contact protocol and Android applied receipts',async()=>{
  jest.spyOn(performance,'now').mockReturnValue(1000);
  const messages:Record<string,unknown>[]=[],events:TeachingInput[]=[];
  let receive:(value:unknown)=>void=()=>{};
  const envelope={session_id:'f'.repeat(32),capture_epoch:binding.captureEpoch,contact_protocol:1,max_pointers:3,owner:'d'.repeat(32),device_uptime_ms:1000};
  const endpoint={session:envelope.session_id,sharedInput:true,readyState:1,bufferedAmount:0,capture:()=>binding,
    listen:(callback:(value:unknown)=>void)=>{receive=callback;return()=>{};},
    send:(raw:string)=>{const v=JSON.parse(raw);messages.push(v);queueMicrotask(()=>{
      if(v.type==='touch_open'){receive({type:'touch_session',...envelope,frame_width:960,frame_height:540});receive({type:'shared_input_status',...envelope,sequence:0,gesture:0,action:4,pointer_id:-1,outcome:'ready'});}
      else receive({type:'shared_input_status',...envelope,sequence:v.sequence??0,gesture:v.gesture??0,action:v.type==='touch_close'?3:v.action,pointer_id:v.pointer_id??-1,outcome:v.type==='touch_close'?'closed':v.action===4?'alive':'applied'});
    });}};
  open.mockImplementation(async(_signal,journal)=>{
    let resolve:()=>void=()=>{};const ready=new Promise<void>(r=>{resolve=r;});
    const control=new TeachingContacts(endpoint,binding,()=>true,e=>{events.push(e);journal(e);},state=>{if(state==='ready')resolve();});
    await ready;
    return {active:()=>control.isReady,set:(v:[number,number])=>{
      if(Math.hypot(...v)===0){control.set(0,null);return;}
      if(!control.hasContact(0))control.set(0,{x:144,y:442});
      control.set(0,{x:Math.round(144+v[0]*65),y:Math.round(442+v[1]*65)});
    },close:()=>control.close()};
  });
  view();start();await waitFor(()=>expect(events.filter(e=>e.stage==='receipt'&&e.action===2&&e.outcome==='applied')).toHaveLength(1));
  expect(messages.filter(e=>e.type==='touch_contact_event').map(e=>[e.action,e.pointer_id])).toEqual([[0,0],[2,0]]);
  expect(messages.find(e=>e.action===2)).toMatchObject({x:147,y:429});
  fireEvent.click(screen.getByRole('button',{name:'Стоп пешего теста · Esc'}));
  await screen.findByText('Освобождение: CLOSED');
  expect(screen.getByLabelText('Подтверждение движения')).toHaveTextContent('Android применил: 2');
});

test('temporary readiness sampling does not reset actual source frames or stop a fresh run',async()=>{
  const rendered=view();start();await waitFor(()=>expect(lease.set).toHaveBeenCalled());
  rendered.rerender(<WalkingRoutePilot job={job} clip="clip" video={videoRef} ready={false} binding={binding} assetsReady input={{issue:null,open}} observerBusy={false} onBusyChange={busy}/>);
  fresh();await act(async()=>{await new Promise(r=>setTimeout(r,35));});
  expect(lease.close).not.toHaveBeenCalled();
  fireEvent.keyDown(window,{code:'Escape'});await screen.findByText('Освобождение: CLOSED');
});

test('archives the stop-time frame count and exact native failure instead of later reset state',async()=>{
  let complete:(value:boolean)=>void=()=>{};lease.close=jest.fn(()=>new Promise(r=>{complete=r;}));
  lease.failure=()=> 'contact_video_stale';
  view({scope:'e'.repeat(32)});start();await waitFor(()=>expect(lease.set).toHaveBeenCalled());
  fresh();const framesBeforeStop=2;
  fireEvent.keyDown(window,{code:'Escape'});fresh();
  await act(async()=>{complete(true);});await screen.findByText('Освобождение: CLOSED');
  await waitFor(()=>expect(saveRouteDebugReport).toHaveBeenCalled());
  expect(jest.mocked(saveRouteDebugReport).mock.calls.at(-1)?.[3]).toMatchObject({stopFrameSequence:framesBeforeStop,stopReason:'contact_video_stale',inputFailure:'contact_video_stale'});
  expect(screen.getByRole('status')).toHaveTextContent('браузер не подтвердил новый видеокадр');
});

test('source frames are visible before a plan arrives and stopping preserves a source preview',async()=>{
  const rendered=view();fresh();
  const context=jest.mocked(HTMLCanvasElement.prototype.getContext).mock.results.at(-1)?.value;
  expect(context?.drawImage).toHaveBeenCalled();
  start();await waitFor(()=>expect(lease.set).toHaveBeenCalled());
  fireEvent.click(screen.getByRole('button',{name:'Стоп пешего теста · Esc'}));
  await screen.findByText('Освобождение: CLOSED');
  expect(screen.getByText(/Просмотр источника.*движение выключено/)).toBeInTheDocument();
  expect(screen.getByText(/Кадров источника:.*ответов локализации:/)).toBeInTheDocument();
  rendered.unmount();
});
