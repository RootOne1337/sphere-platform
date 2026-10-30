import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {TeachingNavigation} from '@/src/features/stream/TeachingNavigation';
import {reconstructionRequest,ReconstructionResponseError} from '@/src/features/stream/reconstructionClient';
import {preparationError} from '@/src/features/stream/routePreparation';
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn()}));
const job={id:'a'.repeat(32),key:'b'.repeat(64)};
beforeEach(()=>{
  jest.clearAllMocks();
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'cccccccc-cccc-cccc-cccc-cccccccccccc'});
  jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({clearRect:jest.fn(),drawImage:jest.fn()} as never);
});
afterEach(()=>jest.restoreAllMocks());
test('the walking panel shows the actual failed automatic stage and never opens input or retries it',async()=>{
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'sparse_complete',sparse_available:true,
    quality:{registered:88,selected:99,coverage:88/99,points:11188,mean_reprojection_px:1.14},
    navigation:{phase:'failed',error:'route_camera_motion_requires_review'},camera_motion:{warning:'poses_require_temporal_review',rapid_reversals:4,speed_outliers:8,heuristic_only:true,navigation_qualified:false}})} as Response);
  const open=jest.fn();
  render(<TeachingNavigation job={job} video={{current:null}} ready binding={{captureEpoch:'e'.repeat(32),width:960,height:540}} walkInput={{issue:null,open}}/>);
  fireEvent.click(screen.getByRole('button',{name:'Пеший тест со стиком'}));
  expect((await screen.findAllByText(/Автоматическая подготовка остановлена:.*88 из 99/)).length).toBeGreaterThan(0);
  expect(screen.queryByText('Сначала подготовьте карту ориентиров выбранной записи.')).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Запустить проход'})).toBeDisabled();expect(open).not.toHaveBeenCalled();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(c=>c[2]?.method!=='POST')).toBe(true);
});
test('walk control is a separate panel and switching panels does not open an input owner',async()=>{
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'complete',sparse_available:true,navigation:{phase:'ready'}})} as Response);
  const open=jest.fn();
  render(<TeachingNavigation job={job} video={{current:null}} ready binding={{captureEpoch:'e'.repeat(32),width:960,height:540}} walkInput={{issue:'Укажите центр стика',open}}/>);
  fireEvent.click(screen.getByRole('button',{name:'Пеший тест со стиком'}));
  expect(screen.getByRole('button',{name:'Запустить проход'})).toBeDisabled();
  expect(screen.queryByRole('button',{name:'Проверить направление · 120 с'})).not.toBeInTheDocument();
  expect(open).not.toHaveBeenCalled();expect(jest.mocked(reconstructionRequest).mock.calls.every(c=>c[2]?.method!=='POST')).toBe(true);
});
test('opening a live preview reads readiness but never starts capture, a model or Android input',async()=>{
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'complete',dense_available:true,navigation:{phase:'ready'}})} as Response);
  render(<TeachingNavigation job={job} video={{current:null}} ready binding={{captureEpoch:'e'.repeat(32),width:1920,height:1080}}/>);
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalledWith(`/jobs/${job.id}`,job,expect.any(Object)));
  expect(screen.getByRole('button',{name:'Проверить направление · 120 с'})).toBeDisabled();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
});
test('a bound live observation can be exported without video or control',async()=>{
  const callbacks:VideoFrameRequestCallback[]=[];
  const element={requestVideoFrameCallback:jest.fn((callback:VideoFrameRequestCallback)=>{callbacks.push(callback);return callbacks.length;}),
    cancelVideoFrameCallback:jest.fn()} as unknown as HTMLVideoElement;
  const oldSubtle=Object.getOwnPropertyDescriptor(crypto,'subtle');
  Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async()=>new Uint8Array(32).fill(170).buffer}});
  const oldCreate=URL.createObjectURL,oldRevoke=URL.revokeObjectURL;
  URL.createObjectURL=jest.fn(()=> 'blob:route-diagnostic');URL.revokeObjectURL=jest.fn();
  const click=jest.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(()=>{});
  jest.spyOn(HTMLCanvasElement.prototype,'toBlob').mockImplementation(callback=>{
    const blob=new Blob(['jpeg'],{type:'image/jpeg'});
    Object.defineProperty(blob,'arrayBuffer',{value:async()=>new ArrayBuffer(4)});
    callback(blob);
  });
  jest.mocked(reconstructionRequest).mockImplementation(async(path,_job,init)=>{
    if(path.endsWith('/start'))return {json:async()=>({phase:'observing',id:'c'.repeat(32),physicalActions:0})} as Response;
    if(path.endsWith('/observe'))return {json:async()=>({id:'c'.repeat(32),captureEpoch:'e'.repeat(32),sequence:1,jpegSha256:'aa'.repeat(32),computeMs:10,method:'descriptor_pnp',physicalActions:0,executionQualified:false,groundRoute:false,
      pose:{state:'unknown',reason:'route_pose_not_verified',inliers:0,segment:null,progress_units:null,polyline_px:[]}})} as Response;
    if(init?.method==='POST')return {json:async()=>({phase:'closed'})} as Response;
    return {json:async()=>({phase:'complete',dense_available:true,navigation:{phase:'ready'}})} as Response;
  });
  try {
    render(<TeachingNavigation job={job} video={{current:element}} ready binding={{captureEpoch:'e'.repeat(32),width:1920,height:1080}}/>);
    fireEvent.click(screen.getByRole('checkbox'));
    const start=screen.getByRole('button',{name:'Проверить направление · 120 с'});await waitFor(()=>expect(start).toBeEnabled());fireEvent.click(start);
    await waitFor(()=>expect(screen.getByRole('button',{name:'Стоп'})).toBeEnabled());
    act(()=>callbacks[0](0,{} as VideoFrameCallbackMetadata));
    const download=await screen.findByRole('button',{name:'Скачать диагностику · 1'});
    fireEvent.click(download);
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));expect(click).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button',{name:'Стоп'}));
    expect(download).toBeEnabled();
  } finally {
    if(oldSubtle)Object.defineProperty(crypto,'subtle',oldSubtle);else Reflect.deleteProperty(crypto,'subtle');
    URL.createObjectURL=oldCreate;URL.revokeObjectURL=oldRevoke;
  }
});
test('reconnecting the same video element retires the previous frame callback',async()=>{
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'complete',dense_available:true,navigation:{phase:'ready'}})} as Response);
  const callbacks:VideoFrameRequestCallback[]=[];
  const element={requestVideoFrameCallback:jest.fn((callback:VideoFrameRequestCallback)=>{callbacks.push(callback);return callbacks.length;}),
    cancelVideoFrameCallback:jest.fn()} as unknown as HTMLVideoElement;
  const video={current:element},binding={captureEpoch:'e'.repeat(32),width:1920,height:1080};
  const view=render(<TeachingNavigation job={job} video={video} ready binding={binding}/>);
  await screen.findByText(/Карта ориентиров готова/);
  expect(callbacks).toHaveLength(1);
  view.rerender(<TeachingNavigation job={job} video={video} ready binding={{...binding,captureEpoch:'f'.repeat(32)}}/>);
  expect(element.cancelVideoFrameCallback).toHaveBeenCalledWith(1);
  expect(callbacks).toHaveLength(2);
  act(()=>callbacks[0](0,{} as VideoFrameCallbackMetadata));
  expect(callbacks).toHaveLength(2);
  act(()=>callbacks[1](0,{} as VideoFrameCallbackMetadata));
  expect(callbacks).toHaveLength(3);
});
test('unmount closes the same uncertain start intent and a late acknowledgement cannot resume it',async()=>{
  let acknowledge:(value:Response)=>void=()=>{};
  jest.mocked(reconstructionRequest).mockImplementation(async(path,_job,init)=>{
    if(path.endsWith('/start'))return new Promise(resolve=>{acknowledge=resolve;});
    if(init?.method==='POST')return {json:async()=>({phase:'closed'})} as Response;
    return {json:async()=>({phase:'complete',dense_available:true,navigation:{phase:'ready'}})} as Response;
  });
  const view=render(<TeachingNavigation job={job} video={{current:null}} ready binding={{captureEpoch:'e'.repeat(32),width:1920,height:1080}}/>);
  fireEvent.click(screen.getByRole('checkbox'));
  const start=screen.getByRole('button',{name:'Проверить направление · 120 с'});await waitFor(()=>expect(start).toBeEnabled());fireEvent.click(start);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[0].endsWith('/start'))).toBe(true));
  view.unmount();
  await act(async()=>acknowledge({json:async()=>({phase:'observing',id:'c'.repeat(32),physicalActions:0})} as Response));
  const posts=jest.mocked(reconstructionRequest).mock.calls.filter(c=>c[2]?.method==='POST');
  expect(posts.map(c=>c[0].split('/').at(-1))).toEqual(['start','stop']);
  expect(JSON.parse(String(posts[1][2]?.body))).toEqual({id:'c'.repeat(32)});
});
test('switching scenes closes the old scene intent and ignores its late acknowledgement',async()=>{
  const other={id:'f'.repeat(32),key:'9'.repeat(64)};let acknowledge:(value:Response)=>void=()=>{};
  jest.mocked(reconstructionRequest).mockImplementation(async(path,_job,init)=>{
    if(path.endsWith('/start'))return new Promise(resolve=>{acknowledge=resolve;});
    if(init?.method==='POST')return {json:async()=>({phase:'closed'})} as Response;
    return {json:async()=>({phase:'complete',dense_available:true,navigation:{phase:'ready'}})} as Response;
  });
  const binding={captureEpoch:'e'.repeat(32),width:1920,height:1080},video={current:null};
  const view=render(<TeachingNavigation job={job} video={video} ready binding={binding}/>);
  fireEvent.click(screen.getByRole('checkbox'));
  const start=screen.getByRole('button',{name:'Проверить направление · 120 с'});await waitFor(()=>expect(start).toBeEnabled());fireEvent.click(start);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[0].endsWith('/start'))).toBe(true));
  view.rerender(<TeachingNavigation job={other} video={video} ready binding={binding}/>);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[0]===`/jobs/${job.id}/navigation/stop`)).toBe(true));
  await act(async()=>acknowledge({json:async()=>({phase:'observing',id:'c'.repeat(32),physicalActions:0})} as Response));
  const posts=jest.mocked(reconstructionRequest).mock.calls.filter(c=>c[2]?.method==='POST');
  expect(posts.map(c=>c[0])).toEqual([`/jobs/${job.id}/navigation/start`,`/jobs/${job.id}/navigation/stop`]);
  expect(posts[1][1]).toEqual(job);
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  expect(screen.getByRole('button',{name:'Проверить направление · 120 с'})).toBeDisabled();
});
test('a changed stream invalidates confirmation and stops the original observer',async()=>{
  let acknowledge:(value:Response)=>void=()=>{};
  jest.mocked(reconstructionRequest).mockImplementation(async(path,_job,init)=>{
    if(path.endsWith('/start'))return new Promise(resolve=>{acknowledge=resolve;});
    if(init?.method==='POST')return {json:async()=>({phase:'closed'})} as Response;
    return {json:async()=>({phase:'complete',dense_available:true,navigation:{phase:'ready'}})} as Response;
  });
  const video={current:null},binding={captureEpoch:'e'.repeat(32),width:1920,height:1080};
  const view=render(<TeachingNavigation job={job} video={video} ready binding={binding}/>);
  fireEvent.click(screen.getByRole('checkbox'));
  const start=screen.getByRole('button',{name:'Проверить направление · 120 с'});await waitFor(()=>expect(start).toBeEnabled());fireEvent.click(start);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[0].endsWith('/start'))).toBe(true));
  view.rerender(<TeachingNavigation job={job} video={video} ready binding={{...binding,captureEpoch:'f'.repeat(32)}}/>);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[0]===`/jobs/${job.id}/navigation/stop`)).toBe(true));
  await act(async()=>acknowledge({json:async()=>({phase:'observing',id:'c'.repeat(32),physicalActions:0})} as Response));
  expect(screen.getByRole('checkbox')).not.toBeChecked();
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(c=>c[2]?.method==='POST')).toHaveLength(2);
});
test('switching after a confirmed start stops only the observer that was actually opened',async()=>{
  const other={id:'f'.repeat(32),key:'9'.repeat(64)};
  jest.mocked(reconstructionRequest).mockImplementation(async(path,_job,init)=>{
    if(path.endsWith('/start'))return {json:async()=>({phase:'observing',id:'c'.repeat(32),physicalActions:0})} as Response;
    if(init?.method==='POST')return {json:async()=>({phase:'closed'})} as Response;
    return {json:async()=>({phase:'complete',dense_available:true,navigation:{phase:'ready'}})} as Response;
  });
  const video={current:null},binding={captureEpoch:'e'.repeat(32),width:1920,height:1080};
  const view=render(<TeachingNavigation job={job} video={video} ready binding={binding}/>);
  fireEvent.click(screen.getByRole('checkbox'));
  const start=screen.getByRole('button',{name:'Проверить направление · 120 с'});await waitFor(()=>expect(start).toBeEnabled());fireEvent.click(start);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Стоп'})).toBeEnabled());
  view.rerender(<TeachingNavigation job={other} video={video} ready binding={binding}/>);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[0]===`/jobs/${job.id}/navigation/stop`)).toBe(true));
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(c=>c[2]?.method==='POST').map(c=>c[0]))
    .toEqual([`/jobs/${job.id}/navigation/start`,`/jobs/${job.id}/navigation/stop`]);
  expect(screen.getByRole('checkbox')).not.toBeChecked();
});
test('a failed read can be checked again without starting a session or retaining stale readiness',async()=>{
  jest.mocked(reconstructionRequest).mockRejectedValueOnce(Error('offline')).mockResolvedValue({json:async()=>({phase:'complete',dense_available:true,navigation:{phase:'ready'}})} as Response);
  render(<TeachingNavigation job={job} video={{current:null}} ready binding={{captureEpoch:'e'.repeat(32),width:1920,height:1080}}/>);
  const retry=await screen.findByRole('button',{name:'Проверить обработчик снова'});
  expect(screen.getByRole('button',{name:'Проверить направление · 120 с'})).toBeDisabled();
  fireEvent.click(retry);
  await screen.findByText(/Карта ориентиров готова/);
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
});
test('direction shows the failed camera gate for the chosen recording without offering unsafe preparation',async()=>{
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'failed',error:'camera_quality_gate_failed',geometry_available:true,dense_available:false,quality:{registered:65,selected:99},navigation:{phase:'not_prepared'}})} as Response);
  const select=jest.fn();
  render(<TeachingNavigation job={job} clip={'d'.repeat(32)} scope={'e'.repeat(32)} clips={[{id:'d'.repeat(32),title:'test228',frames:1311,complete:true}]} onSelectClip={select} video={{current:null}} ready binding={{captureEpoch:'e'.repeat(32),width:1920,height:1080}}/>);
  expect(screen.getByRole('combobox',{name:'Сохранённый проход для направления'})).toHaveDisplayValue(/test228/);
  await screen.findByText(/Камеры связаны частично: 65 из 99/);
  expect(screen.getByText(/карта: не подготовлена/)).toBeInTheDocument();
  expect(screen.queryByText(/not_prepared/)).not.toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Подготовить ориентиры'})).not.toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Проверить направление · 120 с'})).toBeDisabled();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
  fireEvent.change(screen.getByRole('combobox',{name:'Сохранённый проход для направления'}),{target:{value:''}});
  expect(select).toHaveBeenCalledWith(null);
});
test('a completed scene can prepare its own map directly without starting an observer',async()=>{
  sessionStorage.clear();
  jest.mocked(reconstructionRequest).mockImplementation(async(path,_job,init)=>{
    if(init?.method==='POST')return {json:async()=>({phase:'preparing'})} as Response;
    return {json:async()=>({phase:'complete',dense_available:true,navigation:{phase:'not_prepared'}})} as Response;
  });
  render(<TeachingNavigation job={job} clip={'d'.repeat(32)} scope={'e'.repeat(32)} video={{current:null}} ready binding={{captureEpoch:'e'.repeat(32),width:1920,height:1080}}/>);
  fireEvent.click(await screen.findByRole('button',{name:'Подготовить ориентиры'}));
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[0].endsWith('/navigation/prepare'))).toBe(true));
  const posts=jest.mocked(reconstructionRequest).mock.calls.filter(c=>c[2]?.method==='POST');
  expect(posts.map(c=>c[0])).toEqual([`/jobs/${job.id}/navigation/prepare`]);
});
test('sparse geometry can prepare a map after dense rendering failed',async()=>{
  sessionStorage.clear();
  jest.mocked(reconstructionRequest).mockImplementation(async(_path,_job,init)=>{
    if(init?.method==='POST')return {json:async()=>({phase:'preparing'})} as Response;
    return {json:async()=>({phase:'failed',error:'brush_failed_see_local_log',dense_available:false,
      sparse_available:true,navigation:{phase:'not_prepared'}})} as Response;
  });
  render(<TeachingNavigation job={job} clip={'d'.repeat(32)} scope={'e'.repeat(32)} video={{current:null}} ready binding={{captureEpoch:'e'.repeat(32),width:1920,height:1080}}/>);
  fireEvent.click(await screen.findByRole('button',{name:'Подготовить ориентиры'}));
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[0].endsWith('/navigation/prepare'))).toBe(true));
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(c=>c[2]?.method==='POST').map(c=>c[0])).toEqual([`/jobs/${job.id}/navigation/prepare`]);
});
test('one temporal reversal blocks preparation before consuming an attempt',async()=>{
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'complete',dense_available:true,
    camera_motion:{warning:null,rapid_reversals:1,speed_outliers:0,navigation_qualified:false},
    navigation:{phase:'not_prepared'}})} as Response);
  render(<TeachingNavigation job={job} clip={'d'.repeat(32)} scope={'e'.repeat(32)} video={{current:null}} ready binding={{captureEpoch:'e'.repeat(32),width:1920,height:1080}}/>);
  await screen.findByText(/Траекторию камер нужно проверить/);
  expect(screen.queryByRole('button',{name:'Подготовить ориентиры'})).not.toBeInTheDocument();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
});
test('a late preparation response cannot mark a newly selected scene ready',async()=>{
  sessionStorage.clear();
  const other={id:'f'.repeat(32),key:'9'.repeat(64)};let finish:(value:Response)=>void=()=>{};
  jest.mocked(reconstructionRequest).mockImplementation(async(_path,_job,init)=>{
    if(init?.method==='POST')return new Promise(resolve=>{finish=resolve;});
    return {json:async()=>({phase:'complete',dense_available:true,navigation:{phase:'not_prepared'}})} as Response;
  });
  const video={current:null},binding={captureEpoch:'e'.repeat(32),width:1920,height:1080},scope='e'.repeat(32),clip='d'.repeat(32);
  const view=render(<TeachingNavigation job={job} clip={clip} scope={scope} video={video} ready binding={binding}/>);
  fireEvent.click(await screen.findByRole('button',{name:'Подготовить ориентиры'}));
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[2]?.method==='POST')).toBe(true));
  view.rerender(<TeachingNavigation job={other} clip={clip} scope={scope} video={video} ready binding={binding}/>);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(c=>c[0]===`/jobs/${other.id}`)).toBe(true));
  await act(async()=>finish({json:async()=>({phase:'ready'})} as Response));
  expect(screen.getByText(/карта: не подготовлена/)).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Проверить направление · 120 с'})).toBeDisabled();
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(c=>c[2]?.method==='POST')).toHaveLength(1);
});
test('a motion-rejected scene explains the obstruction instead of repeatedly creating attempts',async()=>{
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'complete',dense_available:true,
    camera_motion:{warning:'poses_require_temporal_review',rapid_reversals:17},
    navigation:{phase:'failed',error:'route_camera_motion_requires_review'}})} as Response);
  render(<TeachingNavigation job={job} clip={'d'.repeat(32)} scope={'e'.repeat(32)} video={{current:null}} ready binding={{captureEpoch:'e'.repeat(32),width:1920,height:1080}}/>);
  await screen.findByText(/Траекторию камер нужно проверить/);
  expect(screen.queryByRole('button',{name:'Подготовить ориентиры'})).not.toBeInTheDocument();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
});
test('the attempt quota is explained as a confirmed rejection, not a missing response',()=>{
  expect(preparationError(new ReconstructionResponseError(409,'route_preparation_attempt_quota'))).toMatch(/Исчерпан лимит попыток/);
});

test('an incomplete map shows measured coverage and opens recovery without wasting another export',async()=>{
  const review=jest.fn();
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'sparse_complete',sparse_available:true,
    navigation:{phase:'rejected',error:'route_map_has_unobserved_sections',resourceProfile:{kind:'route_features',minRamGiB:6.25},
      summary:{cameras:54,landmarks:1236,camera_trace_only:true,last_seconds:28.258,
        source_coverage:{recording_start_seconds:0,recording_end_seconds:33.258,uncovered_start_seconds:0,uncovered_end_seconds:5,endpoints_observed:false},
        map_support:{all_reference_neighborhoods_supported:true,unobserved_intervals:[{start_seconds:10.807,end_seconds:12.341}]}}}})} as Response);
  render(<TeachingNavigation job={job} video={{current:null}} ready binding={null} onReview={review}/>);
  expect(await screen.findByText(/карта до 28.26 с из 33.26 с записи/)).toHaveTextContent('10.81–12.34 с');
  expect(screen.queryByRole('button',{name:'Подготовить ориентиры'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Открыть восстановление камер'}));
  expect(review).toHaveBeenCalledTimes(1);
  expect(reconstructionRequest).toHaveBeenCalledTimes(1);
});
test('confirmed attempt quota remains visible after refresh and prevents another POST',async()=>{
  sessionStorage.clear();
  jest.mocked(reconstructionRequest).mockImplementation(async(_path,_job,init)=>{
    if(init?.method==='POST')throw new ReconstructionResponseError(409,'route_preparation_attempt_quota');
    return {json:async()=>({phase:'complete',dense_available:true,navigation:{phase:'failed'}})} as Response;
  });
  render(<TeachingNavigation job={job} clip={'d'.repeat(32)} scope={'e'.repeat(32)} video={{current:null}} ready binding={{captureEpoch:'e'.repeat(32),width:1920,height:1080}}/>);
  fireEvent.click(await screen.findByRole('button',{name:'Подготовить ориентиры'}));
  await screen.findByText(/Исчерпан лимит попыток для этой сцены/);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.filter(c=>c[2]?.method!=='POST').length).toBeGreaterThanOrEqual(2));
  expect(screen.getByText(/Исчерпан лимит попыток для этой сцены/)).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Подготовить ориентиры'})).not.toBeInTheDocument();
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(c=>c[2]?.method==='POST')).toHaveLength(1);
});
