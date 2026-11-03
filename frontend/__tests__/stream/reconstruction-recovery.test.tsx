import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {TeachingReconstruction} from '@/src/features/stream/TeachingReconstruction';
import {reconstructionRequest,ReconstructionResponseError,uploadReconstruction,type ReconstructionJob} from '@/src/features/stream/reconstructionClient';
import {automaticReconstructionStopped,ensureAutomaticReconstructionLink,listReconstructionLinks,readReconstructionLink,saveReconstructionLink,stopAutomaticReconstruction} from '@/src/features/stream/reconstructionLink';
jest.mock('next/dynamic',()=>()=>function Placeholder(){return null;});
jest.mock('@/src/features/stream/reconstructionLink',()=>({readReconstructionLink:jest.fn(async()=>null),listReconstructionLinks:jest.fn(async()=>[]),saveReconstructionLink:jest.fn(async()=>{}),ensureAutomaticReconstructionLink:jest.fn(),automaticReconstructionStopped:jest.fn(async()=>false),stopAutomaticReconstruction:jest.fn(async()=>{}),validReconstructionJob:(value:unknown)=>!!value}));
jest.mock('@/src/features/stream/reconstructionClient',()=>({
  ...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn(),uploadReconstruction:jest.fn(),
}));
afterEach(()=>{sessionStorage.clear();jest.clearAllMocks();jest.mocked(readReconstructionLink).mockResolvedValue(null);jest.mocked(listReconstructionLinks).mockResolvedValue([]);jest.mocked(automaticReconstructionStopped).mockResolvedValue(false);});
test('a recording marked HUD-free retains the avatar mask and 30000 iterations',async()=>{
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>null} complete hudHidden onBusyChange={()=>{}}/>);
  expect(screen.getByRole('button',{name:'Подготовить ориентиры'})).toBeInTheDocument();
  fireEvent.click(screen.getByText('Дополнительные настройки и визуальная 3D-сцена'));
  await waitFor(()=>expect(screen.getByRole('button',{name:'Построить 3D-сцену'})).toBeEnabled());
  expect(screen.getByRole('combobox',{name:/Маска/i})).toHaveValue('avatar');
  expect(screen.getByRole('combobox',{name:'Качество обработки'})).toHaveValue('30000');
  view.unmount();
});
test('one-button route preparation creates a sparse-only automatic pipeline',async()=>{
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'});
  jest.mocked(ensureAutomaticReconstructionLink).mockImplementation(async(_source,_clip,_mask,candidate)=>candidate!);
  (reconstructionRequest as jest.Mock).mockResolvedValue({json:async()=>({phase:'failed'})});
  const folder={} as FileSystemDirectoryHandle;
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>folder} complete onBusyChange={()=>{}}/>);
  const button=await screen.findByRole('button',{name:'Подготовить ориентиры'});
  await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalled());
  const request=(reconstructionRequest as jest.Mock).mock.calls.find(([path])=>path==='/jobs');
  expect(JSON.parse(String(request[2].body))).toMatchObject({prepare_route:true,route_only:true});
  expect(jest.mocked(saveReconstructionLink).mock.calls[0][2].creation).toMatchObject({prepare_route:true,route_only:true});
  view.unmount();
});

test('a first create resource refusal is a confirmed rejection of this intent, not an old error or uncertain launch',async()=>{
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'});
  jest.mocked(readReconstructionLink).mockResolvedValue(null);jest.mocked(listReconstructionLinks).mockResolvedValue([]);
  jest.mocked(ensureAutomaticReconstructionLink).mockImplementation(async(_source,_clip,_mask,candidate)=>candidate!);
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>{
    if(path==='/jobs')throw new ReconstructionResponseError(409,'resource_guard');
    return {json:async()=>({phase:'failed',error:'resource_guard'})} as Response;
  });
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>({} as FileSystemDirectoryHandle)} complete onBusyChange={()=>{}} manageAutomaticPreparation={false}/>);
  const button=await screen.findByRole('button',{name:'Подготовить ориентиры'});
  await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);
  await screen.findByText('Ресурсная проверка запроса остановила запуск. Проверяем состояние этой же попытки; исходная запись сохранена.');
  expect(screen.queryByText(/прежний ресурсный|У предыдущей попытки|Запуск не подтверждён: resource_guard/)).not.toBeInTheDocument();
  expect(uploadReconstruction).not.toHaveBeenCalled();
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(([path])=>path==='/jobs')).toHaveLength(1);
  expect(jest.mocked(reconstructionRequest).mock.calls.some(([path])=>path.endsWith('/start'))).toBe(false);
  view.unmount();
});

test('a newly finalized recording can prepare once automatically but a recovered intent never creates another job',async()=>{
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'});
  jest.mocked(readReconstructionLink).mockResolvedValue(null);jest.mocked(listReconstructionLinks).mockResolvedValue([]);
  const auto={id:'a'.repeat(32),key:'b'.repeat(64),creation:{mask:'game' as const,steps:30000,prepare_route:true as const,route_only:true as const}};
  jest.mocked(ensureAutomaticReconstructionLink).mockResolvedValue(auto);
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>{if(path.startsWith('/jobs/'))throw new ReconstructionResponseError(404,'job_not_found');return {json:async()=>({phase:'failed'})} as Response;});
  const consumed=jest.fn(),folder={} as FileSystemDirectoryHandle,props={clip:'c'.repeat(32),scope:'d'.repeat(32),folder:()=>folder,complete:true,onBusyChange:()=>{},autoPrepare:true,onAutoPrepareConsumed:consumed};
  const first=render(<TeachingReconstruction {...props}/>);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.filter(call=>call[0]==='/jobs')).toHaveLength(1));
  expect(consumed).toHaveBeenCalledTimes(1);first.rerender(<TeachingReconstruction {...props}/>);
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(call=>call[0]==='/jobs')).toHaveLength(1);first.unmount();
  jest.clearAllMocks();sessionStorage.clear();
  const saved={id:'a'.repeat(32),key:'b'.repeat(64)};
  jest.mocked(readReconstructionLink).mockResolvedValue(saved);jest.mocked(listReconstructionLinks).mockResolvedValue([saved]);
  const next=render(<TeachingReconstruction {...props}/>);
  await waitFor(()=>expect(consumed).toHaveBeenCalledTimes(1));
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);next.unmount();
});
test('a recovered job blocks new control until its state is actually confirmed',async()=>{
  const clip='c'.repeat(32),scope='d'.repeat(32),job={id:'a'.repeat(32),key:'b'.repeat(64)};
  sessionStorage.setItem(`sphere-reconstruction-${scope}-${clip}`,JSON.stringify(job));
  let confirm:(value:unknown)=>void=()=>{};
  (reconstructionRequest as jest.Mock).mockImplementation(()=>new Promise(resolve=>{confirm=resolve;}));
  const busy=jest.fn();
  const view=render(<TeachingReconstruction clip={clip} scope={scope} folder={()=>null} complete onBusyChange={busy}/>);
  await waitFor(()=>expect(busy).toHaveBeenLastCalledWith(true));
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalled());
  confirm({json:async()=>({phase:'failed',error:'worker_service_restarted'})});
  await waitFor(()=>expect(busy).toHaveBeenLastCalledWith(false));
  view.unmount();
});

test('automatic creation retries the same durable intent only after another confirmed 404',async()=>{
  const job={id:'a'.repeat(32),key:'b'.repeat(64),creation:{mask:'game' as const,steps:30000,prepare_route:true as const,route_only:true as const}};
  jest.mocked(readReconstructionLink).mockResolvedValue(job);jest.mocked(listReconstructionLinks).mockResolvedValue([job]);
  let posts=0;
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>{
    if(path==='/jobs'){if(++posts===1)throw new ReconstructionResponseError(409,'resource_guard');return {json:async()=>({phase:'failed'})} as Response;}
    throw new ReconstructionResponseError(404,'job_not_found');
  });
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>({} as FileSystemDirectoryHandle)} complete autoPrepare onBusyChange={()=>{}}/>);
  await waitFor(()=>expect(posts).toBe(2),{timeout:4000});
  const calls=jest.mocked(reconstructionRequest).mock.calls.filter(([path])=>path==='/jobs');
  expect(calls.map(call=>JSON.parse(String(call[2]?.body)))).toEqual([expect.objectContaining({id:job.id,key:job.key,...job.creation}),expect.objectContaining({id:job.id,key:job.key,...job.creation})]);
  view.unmount();
});

test('ambiguous create followed by processing status never sends start or repeats create',async()=>{
  const job={id:'a'.repeat(32),key:'b'.repeat(64),creation:{mask:'avatar' as const,steps:30000,prepare_route:true as const,route_only:true as const}};
  jest.mocked(readReconstructionLink).mockResolvedValue(job);jest.mocked(listReconstructionLinks).mockResolvedValue([job]);
  let gets=0;
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>{
    if(path==='/jobs')throw Error('network_timeout');
    if(++gets===1)throw new ReconstructionResponseError(404,'job_not_found');
    return {json:async()=>({phase:'matching'})} as Response;
  });
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>({} as FileSystemDirectoryHandle)} complete autoPrepare onBusyChange={()=>{}}/>);
  await waitFor(()=>expect(gets).toBeGreaterThanOrEqual(2),{timeout:4000});
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(([path])=>path==='/jobs')).toHaveLength(1);
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(([path])=>path.endsWith('/start'))).toHaveLength(0);
  view.unmount();
});

test('an incomplete upload is resumed but a job already processing is not started again',async()=>{
  const job={id:'a'.repeat(32),key:'b'.repeat(64),creation:{mask:'game' as const,steps:30000,prepare_route:true as const,route_only:true as const}};
  jest.mocked(readReconstructionLink).mockResolvedValue(job);jest.mocked(listReconstructionLinks).mockResolvedValue([job]);
  const oldLocks=Object.getOwnPropertyDescriptor(navigator,'locks');
  Object.defineProperty(navigator,'locks',{configurable:true,value:{request:async(_name:string,options:{ifAvailable?:boolean;signal?:AbortSignal},fn:(lock:object)=>unknown)=>{if(options.ifAvailable&&options.signal)throw new DOMException('Invalid Web Locks options','NotSupportedError');return fn({});}}});
  let gets=0;jest.mocked(uploadReconstruction).mockResolvedValue();
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>{
    expect(path).toBe(`/jobs/${job.id}`);gets++;
    return {json:async()=>({phase:gets>=3?'matching':'uploading'})} as Response;
  });
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>({} as FileSystemDirectoryHandle)} complete autoPrepare onBusyChange={()=>{}}/>);
  await waitFor(()=>expect(gets).toBeGreaterThanOrEqual(3));
  expect(uploadReconstruction).toHaveBeenCalledTimes(1);
  expect(jest.mocked(reconstructionRequest).mock.calls.every(([, , init])=>init?.method!=='POST')).toBe(true);
  view.unmount();if(oldLocks)Object.defineProperty(navigator,'locks',oldLocks);else Reflect.deleteProperty(navigator,'locks');
});

test('a recording without automatic intent never starts preparation by itself',async()=>{
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'failed'})} as Response);
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>({} as FileSystemDirectoryHandle)} complete autoPrepare={false} onBusyChange={()=>{}}/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Подготовить ориентиры'})).toBeEnabled());
  expect(ensureAutomaticReconstructionLink).not.toHaveBeenCalled();expect(reconstructionRequest).not.toHaveBeenCalled();view.unmount();
});
test('legacy ambiguous job_not_found 409 is not treated as confirmed absence',async()=>{
  const job={id:'a'.repeat(32),key:'b'.repeat(64),creation:{mask:'game' as const,steps:30000,prepare_route:true as const,route_only:true as const}};
  jest.mocked(readReconstructionLink).mockResolvedValue(job);jest.mocked(listReconstructionLinks).mockResolvedValue([job]);
  jest.mocked(reconstructionRequest).mockRejectedValue(new ReconstructionResponseError(409,'job_not_found'));
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>({} as FileSystemDirectoryHandle)} complete autoPrepare onBusyChange={()=>{}}/>);
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalled());
  expect(jest.mocked(reconstructionRequest).mock.calls.every(([, , init])=>init?.method!=='POST')).toBe(true);view.unmount();
});
test('confirmed missing legacy job allows explicit sparse recovery using the original capability',async()=>{
  const job={id:'a'.repeat(32),key:'b'.repeat(64)};
  jest.mocked(readReconstructionLink).mockResolvedValue(job);jest.mocked(listReconstructionLinks).mockResolvedValue([job]);
  jest.mocked(reconstructionRequest).mockImplementation(async(path,_job,init)=>{
    if(path==='/jobs'&&init?.method==='POST')return {json:async()=>({phase:'failed'})} as Response;
    throw new ReconstructionResponseError(404,'job_not_found');
  });
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>({} as FileSystemDirectoryHandle)} complete autoPrepare onBusyChange={()=>{}}/>);
  const button=await screen.findByRole('button',{name:'Подготовить ориентиры'});
  await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(([path])=>path==='/jobs')).toBe(true));
  const request=jest.mocked(reconstructionRequest).mock.calls.find(([path])=>path==='/jobs')!;
  expect(JSON.parse(String(request[2]?.body))).toMatchObject({id:job.id,key:job.key,mask:'game',steps:30000,prepare_route:true,route_only:true});
  view.unmount();
});
test('queued automatic intent can be durably stopped and is not restarted after remount',async()=>{
  const job={id:'a'.repeat(32),key:'b'.repeat(64),creation:{mask:'game' as const,steps:30000,prepare_route:true as const,route_only:true as const}};
  jest.mocked(readReconstructionLink).mockResolvedValue(job);jest.mocked(listReconstructionLinks).mockResolvedValue([job]);
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>{
    if(path==='/jobs')throw new ReconstructionResponseError(409,'resource_guard');
    throw new ReconstructionResponseError(404,'job_not_found');
  });
  const props={clip:'c'.repeat(32),scope:'d'.repeat(32),folder:()=>({} as FileSystemDirectoryHandle),complete:true,autoPrepare:true,onBusyChange:()=>{}};
  const first=render(<TeachingReconstruction {...props}/>);
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(([path])=>path==='/jobs')).toBe(true));
  fireEvent.click(screen.getByRole('button',{name:'Остановить ожидание'}));
  await waitFor(()=>expect(stopAutomaticReconstruction).toHaveBeenCalledWith(expect.anything(),job));
  first.unmount();jest.clearAllMocks();jest.mocked(automaticReconstructionStopped).mockResolvedValue(true);
  const second=render(<TeachingReconstruction {...props}/>);
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalled());
  expect(jest.mocked(reconstructionRequest).mock.calls.every(([, , init])=>init?.method!=='POST')).toBe(true);
  expect(screen.queryByRole('button',{name:'Остановить ожидание'})).not.toBeInTheDocument();second.unmount();
});

test('a fresh job is not polled before POST creation is acknowledged',async()=>{
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'});
  let confirm:(value:unknown)=>void=()=>{};
  (reconstructionRequest as jest.Mock).mockImplementation((path:string, _job:unknown, init?:RequestInit)=>{
    if(path==='/jobs')return new Promise(resolve=>{confirm=resolve;});
    if(init?.method==='POST')return Promise.resolve({json:async()=>({phase:'failed'})});
    return Promise.resolve({json:async()=>({phase:'uploading'})});
  });
  const busy=jest.fn(),folder={} as FileSystemDirectoryHandle;
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>folder} complete onBusyChange={busy}/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Построить 3D-сцену'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Построить 3D-сцену'}));
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalledTimes(1));
  expect((reconstructionRequest as jest.Mock).mock.calls[0][0]).toBe('/jobs');
  confirm({json:async()=>({phase:'uploading'})});
  await waitFor(()=>expect((reconstructionRequest as jest.Mock).mock.calls.some(([path])=>path==='/jobs/'+'a'.repeat(32))).toBe(true));
  view.unmount();
});

test('surface construction stays with the saved job, blocks recording and cancels only its own stage',async()=>{
  const clip='c'.repeat(32),scope='d'.repeat(32),job={id:'a'.repeat(32),key:'b'.repeat(64)};
  sessionStorage.setItem(`sphere-reconstruction-${scope}-${clip}`,JSON.stringify(job));
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'cccccccc-cccc-cccc-cccc-cccccccccccc'});
  let current={phase:'complete',geometry_available:true,dense_available:true,surface_supported:true,fragments:[] as unknown[]};
  (reconstructionRequest as jest.Mock).mockImplementation(async(path:string)=>{
    if(path.endsWith('/start'))current={...current,fragments:[{id:'c'.repeat(32),phase:'densifying'}]};
    if(path.endsWith('/cancel'))current={...current,fragments:[{id:'c'.repeat(32),phase:'cancelled'}]};
    return {json:async()=>current};
  });
  const busy=jest.fn();const view=render(<TeachingReconstruction clip={clip} scope={scope} folder={()=>null} complete onBusyChange={busy}/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Построить поверхности'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Построить поверхности'}));
  await waitFor(()=>expect(busy).toHaveBeenLastCalledWith(true));
  await screen.findByText('Многовидовое восстановление глубины');
  fireEvent.click(screen.getByRole('button',{name:'Отменить обработку'}));
  await waitFor(()=>expect(busy).toHaveBeenLastCalledWith(false));
  const mutations=(reconstructionRequest as jest.Mock).mock.calls.filter(([, , init])=>init?.method==='POST').map(([path])=>path);
  expect(mutations).toEqual([`/jobs/${job.id}/fragments/${'c'.repeat(32)}/start`,`/jobs/${job.id}/fragments/${'c'.repeat(32)}/cancel`]);
  view.unmount();
});

test('saved fragments are selectable without retraining and keep the original result',async()=>{
  const clip='c'.repeat(32),scope='d'.repeat(32),job={id:'a'.repeat(32),key:'b'.repeat(64)};
  sessionStorage.setItem(`sphere-reconstruction-${scope}-${clip}`,JSON.stringify(job));
  const result={triangles:99076,textures:18,bytes:14337876,unknown_faces:488};
  (reconstructionRequest as jest.Mock).mockResolvedValue({json:async()=>({phase:'complete',geometry_available:true,surface_supported:true,
    surface:{phase:'review_required',available:true,fragment:{first_view:20,view_count:18},result},
    fragments:[{id:'e'.repeat(32),phase:'review_required',available:true,fragment:{first_view:0,view_count:18},result:{...result,triangles:60912}}]})});
  const view=render(<TeachingReconstruction clip={clip} scope={scope} folder={()=>null} complete onBusyChange={()=>{}}/>);
  const selector=await screen.findByRole('combobox',{name:'Сохранённый фрагмент маршрута'});
  expect(selector).toHaveValue('legacy');
  fireEvent.change(selector,{target:{value:'e'.repeat(32)}});
  expect(selector).toHaveValue('e'.repeat(32));
  expect((reconstructionRequest as jest.Mock).mock.calls.some(([, , init])=>init?.method==='POST')).toBe(false);
  view.unmount();
});

test('a saved reconstruction attempt can be reopened without starting another job',async()=>{
  const clip='c'.repeat(32),scope='d'.repeat(32),folder={} as FileSystemDirectoryHandle;
  const first={id:'a'.repeat(32),key:'b'.repeat(64)},second={id:'e'.repeat(32),key:'f'.repeat(64)};
  (readReconstructionLink as jest.Mock).mockResolvedValueOnce(first);
  (listReconstructionLinks as jest.Mock).mockResolvedValueOnce([first,second]);
  (reconstructionRequest as jest.Mock).mockResolvedValue({json:async()=>({phase:'failed',error:'camera_quality_gate_failed'})});
  const view=render(<TeachingReconstruction clip={clip} scope={scope} folder={()=>folder} complete onBusyChange={()=>{}}/>);
  const selector=await screen.findByRole('combobox',{name:'Сохранённая попытка реконструкции'});
  await waitFor(()=>expect(selector).toBeEnabled());
  expect(selector).toHaveValue(first.id);
  fireEvent.change(selector,{target:{value:second.id}});
  await waitFor(()=>expect(selector).toHaveValue(second.id));
  expect(saveReconstructionLink).toHaveBeenCalledWith(folder,clip,second);
  await waitFor(()=>expect((reconstructionRequest as jest.Mock).mock.calls.some(([path])=>path===`/jobs/${second.id}`)).toBe(true));
  expect((reconstructionRequest as jest.Mock).mock.calls.some(([, , init])=>init?.method==='POST')).toBe(false);
  view.unmount();
});

test('a failed new capability save sends no POST and keeps the prior attempt selectable',async()=>{
  const clip='c'.repeat(32),scope='d'.repeat(32),folder={} as FileSystemDirectoryHandle;
  const first={id:'a'.repeat(32),key:'b'.repeat(64)};
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'});
  (readReconstructionLink as jest.Mock).mockResolvedValueOnce(first);
  (listReconstructionLinks as jest.Mock).mockResolvedValueOnce([first]);
  (saveReconstructionLink as jest.Mock).mockRejectedValueOnce(Error('disk_write_failed'));
  (reconstructionRequest as jest.Mock).mockResolvedValue({json:async()=>({phase:'failed'})});
  const view=render(<TeachingReconstruction clip={clip} scope={scope} folder={()=>folder} complete onBusyChange={()=>{}}/>);
  fireEvent.click(await screen.findByRole('button',{name:'Повторить подготовку записи'}));
  await screen.findByText(/Не удалось сохранить ссылку на новое задание/);
  expect(screen.getByRole('button',{name:'Повторить подготовку записи'})).toBeEnabled();
  expect(jest.mocked(saveReconstructionLink).mock.calls.at(-1)?.[2].id).not.toBe(first.id);
  expect((reconstructionRequest as jest.Mock).mock.calls.some(([, , init])=>init?.method==='POST')).toBe(false);
  view.unmount();
});

test('one terminal retry durably saves a distinct sparse intent then uploads the SAME recording and starts once',async()=>{
  const clip='c'.repeat(32),scope='d'.repeat(32),folder={} as FileSystemDirectoryHandle;
  const old={id:'a'.repeat(32),key:'b'.repeat(64)},events:string[]=[];
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'});
  jest.mocked(readReconstructionLink).mockResolvedValue(old);jest.mocked(listReconstructionLinks).mockResolvedValue([old]);
  jest.mocked(saveReconstructionLink).mockImplementation(async(_folder,_clip,next)=>{
    events.push('durable');expect(next.id).not.toBe(old.id);jest.mocked(listReconstructionLinks).mockResolvedValue([old,next]);
  });
  let nextPhase='uploading';jest.mocked(uploadReconstruction).mockImplementation(async()=>{events.push('upload');});
  jest.mocked(reconstructionRequest).mockImplementation(async(path,j,init)=>{
    if(path==='/jobs'){expect(events[0]).toBe('durable');events.push('create');return {json:async()=>({phase:'uploading'})} as Response;}
    if(path.endsWith('/start')){events.push('start');nextPhase='matching';return {json:async()=>({phase:'matching'})} as Response;}
    return {json:async()=>({phase:j?.id===old.id?'failed':nextPhase,error:j?.id===old.id?'resource_guard':undefined})} as Response;
  });
  const view=render(<TeachingReconstruction clip={clip} scope={scope} folder={()=>folder} complete onBusyChange={()=>{}}/>);
  const retry=await screen.findByRole('button',{name:'Повторить подготовку записи'});fireEvent.click(retry);fireEvent.click(retry);
  await waitFor(()=>expect(events).toEqual(['durable','create','upload','start']));
  expect(jest.mocked(uploadReconstruction).mock.calls[0][0]).toBe(folder);
  const creation=jest.mocked(reconstructionRequest).mock.calls.find(([path])=>path==='/jobs')!;
  expect(JSON.parse(String(creation[2]?.body))).toMatchObject({id:'e'.repeat(32),prepare_route:true,route_only:true,steps:30000});
  expect(jest.mocked(saveReconstructionLink)).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('combobox',{name:'Сохранённая попытка реконструкции'})).toHaveValue('e'.repeat(32));
  view.unmount();
});

test('a lost retry start response reads the NEW intent and never repeats create or start',async()=>{
  const old={id:'a'.repeat(32),key:'b'.repeat(64)},folder={} as FileSystemDirectoryHandle;
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'});
  jest.mocked(readReconstructionLink).mockResolvedValue(old);jest.mocked(listReconstructionLinks).mockResolvedValue([old]);
  let started=false;
  jest.mocked(saveReconstructionLink).mockImplementation(async(_folder,_clip,next)=>{jest.mocked(listReconstructionLinks).mockResolvedValue([old,next]);});
  jest.mocked(uploadReconstruction).mockResolvedValue();
  jest.mocked(reconstructionRequest).mockImplementation(async(path,j)=>{
    if(path==='/jobs')return {json:async()=>({phase:'uploading'})} as Response;
    if(path.endsWith('/start')){started=true;throw Error('lost_start_response');}
    return {json:async()=>({phase:j?.id===old.id?'cancelled':started?'matching':'uploading'})} as Response;
  });
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>folder} complete autoPrepare={false} onBusyChange={()=>{}}/>);
  fireEvent.click(await screen.findByRole('button',{name:'Повторить подготовку записи'}));
  await waitFor(()=>expect(jest.mocked(reconstructionRequest).mock.calls.some(([path])=>path===`/jobs/${'e'.repeat(32)}`)).toBe(true),{timeout:2000});
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(([path])=>path==='/jobs')).toHaveLength(1);
  expect(jest.mocked(reconstructionRequest).mock.calls.filter(([path])=>path.endsWith('/start'))).toHaveLength(1);
  expect(jest.mocked(saveReconstructionLink)).toHaveBeenCalledTimes(1);view.unmount();
});

test('terminal retry cannot run without the original OPFS source and is absent for unconfirmed processing',async()=>{
  const old={id:'a'.repeat(32),key:'b'.repeat(64)};
  jest.mocked(readReconstructionLink).mockResolvedValue(old);jest.mocked(listReconstructionLinks).mockResolvedValue([old]);
  sessionStorage.setItem(`sphere-reconstruction-${'d'.repeat(32)}-${'c'.repeat(32)}`,JSON.stringify(old));
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'failed',error:'resource_guard'})} as Response);
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>null} complete onBusyChange={()=>{}}/>);
  expect(await screen.findByRole('button',{name:'Повторить подготовку записи'})).toBeDisabled();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);view.unmount();
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'matching'})} as Response);
  const next=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>({} as FileSystemDirectoryHandle)} complete onBusyChange={()=>{}}/>);
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalled());
  expect(screen.queryByRole('button',{name:'Повторить подготовку записи'})).not.toBeInTheDocument();next.unmount();
});

test('camera-motion rejection disables repeated route preparation on the scene page',async()=>{
  const clip='c'.repeat(32),scope='d'.repeat(32),job={id:'a'.repeat(32),key:'b'.repeat(64)};
  sessionStorage.setItem(`sphere-reconstruction-${scope}-${clip}`,JSON.stringify(job));
  (reconstructionRequest as jest.Mock).mockResolvedValue({json:async()=>({phase:'complete',geometry_available:true,dense_available:true,
    camera_motion:{warning:'poses_require_temporal_review',rapid_reversals:17},navigation:{phase:'failed',error:'route_camera_motion_requires_review'}})});
  const view=render(<TeachingReconstruction clip={clip} scope={scope} folder={()=>null} complete onBusyChange={()=>{}}/>);
  expect(await screen.findByRole('button',{name:'Подготовить маршрут'})).toBeDisabled();
  expect(screen.getByText(/повторная подготовка не исправит/)).toBeInTheDocument();
  expect((reconstructionRequest as jest.Mock).mock.calls.every(([, , init])=>init?.method!=='POST')).toBe(true);
  view.unmount();
});
test('scene retains confirmed route preparation refusal after a status poll',async()=>{
  const clip='c'.repeat(32),scope='d'.repeat(32),job={id:'a'.repeat(32),key:'b'.repeat(64)};
  sessionStorage.setItem(`sphere-reconstruction-${scope}-${clip}`,JSON.stringify(job));
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'});
  (reconstructionRequest as jest.Mock).mockImplementation(async(_path:string,_job:unknown,init?:RequestInit)=>{
    if(init?.method==='POST')throw new ReconstructionResponseError(409,'route_preparation_attempt_quota');
    return {json:async()=>({phase:'complete',geometry_available:true,dense_available:true,navigation:{phase:'failed'}})};
  });
  const view=render(<TeachingReconstruction clip={clip} scope={scope} folder={()=>null} complete onBusyChange={()=>{}}/>);
  const button=await screen.findByRole('button',{name:'Подготовить маршрут'});
  await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);
  await screen.findByText(/Исчерпан лимит попыток для этой сцены/);
  await waitFor(()=>expect((reconstructionRequest as jest.Mock).mock.calls.filter(([, , init])=>init?.method!=='POST').length).toBeGreaterThanOrEqual(2));
  expect(screen.getByText(/Исчерпан лимит попыток для этой сцены/)).toBeInTheDocument();
  expect(button).toBeDisabled();
  expect((reconstructionRequest as jest.Mock).mock.calls.filter(([, , init])=>init?.method==='POST')).toHaveLength(1);
  view.unmount();
});
test('a new manual sparse intent preserves the selected none mask durably before HTTP',async()=>{
  const events:string[]=[];
  jest.mocked(ensureAutomaticReconstructionLink).mockImplementation(async(_folder,_clip,_mask,candidate)=>{events.push('intent');return candidate!;});
  jest.mocked(saveReconstructionLink).mockImplementation(async(_folder,_clip,next)=>{expect(next.creation).toEqual({mask:'none',steps:30000,prepare_route:true,route_only:true});events.push('durable');});
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>{if(path==='/jobs')events.push('create');return {json:async()=>({phase:'failed'})} as Response;});
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>({} as FileSystemDirectoryHandle)} complete onBusyChange={()=>{}}/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Подготовить ориентиры'})).toBeEnabled());
  fireEvent.change(screen.getByRole('combobox',{name:'Маска записи'}),{target:{value:'none'}});
  fireEvent.click(screen.getByRole('button',{name:'Подготовить ориентиры'}));
  await waitFor(()=>expect(events).toEqual(['intent','durable','create']));view.unmount();
  jest.mocked(saveReconstructionLink).mockResolvedValue();
});
test('transient auto intent persistence retries the same id and consumes only after durable confirmation',async()=>{
  const candidates:ReconstructionJob[]=[];let committed=false;
  jest.mocked(ensureAutomaticReconstructionLink).mockImplementation(async(_folder,_clip,_mask,candidate)=>{
    candidates.push(candidate!);if(candidates.length===1)throw Error('close_unconfirmed');committed=true;return candidate!;
  });
  jest.mocked(reconstructionRequest).mockImplementation(async()=>{expect(committed).toBe(true);return {json:async()=>({phase:'failed'})} as Response;});
  const consumed=jest.fn(()=>expect(committed).toBe(true));
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>({} as FileSystemDirectoryHandle)} complete autoPrepare onAutoPrepareConsumed={consumed} onBusyChange={()=>{}}/>);
  await waitFor(()=>expect(candidates).toHaveLength(1));expect(consumed).not.toHaveBeenCalled();
  await waitFor(()=>expect(consumed).toHaveBeenCalledTimes(1),{timeout:2500});
  expect(candidates[1]).toBe(candidates[0]);view.unmount();
});
test('queue-owned selected views are read-only and long processing does not lock browsing',async()=>{
  const saved={id:'a'.repeat(32),key:'b'.repeat(64),creation:{mask:'game' as const,steps:30000,prepare_route:true as const,route_only:true as const}};
  jest.mocked(readReconstructionLink).mockResolvedValue(saved);jest.mocked(listReconstructionLinks).mockResolvedValue([saved]);
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'matching'})} as Response);
  const busy=jest.fn(),view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>({} as FileSystemDirectoryHandle)} complete autoPrepare manageAutomaticPreparation={false} onBusyChange={busy}/>);
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalled());
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>!call[2]?.method)).toBe(true);
  expect(ensureAutomaticReconstructionLink).not.toHaveBeenCalled();expect(busy).toHaveBeenLastCalledWith(false);view.unmount();
});
test('a background durable intent is read back by id without remounting or starting the selected scene',async()=>{
  const saved={id:'a'.repeat(32),key:'b'.repeat(64),creation:{mask:'game' as const,steps:30000,prepare_route:true as const,route_only:true as const}},route=jest.fn();
  jest.mocked(readReconstructionLink).mockResolvedValue(null);jest.mocked(listReconstructionLinks).mockResolvedValue([]);
  const props={clip:'c'.repeat(32),scope:'d'.repeat(32),folder:()=>({} as FileSystemDirectoryHandle),complete:true,manageAutomaticPreparation:false,onBusyChange:()=>{},onRouteChange:route};
  const view=render(<TeachingReconstruction {...props}/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Подготовить ориентиры'})).toBeEnabled());
  jest.mocked(readReconstructionLink).mockResolvedValue(saved);jest.mocked(listReconstructionLinks).mockResolvedValue([saved]);
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'matching'})} as Response);
  view.rerender(<TeachingReconstruction {...props} processingJobId={saved.id}/>);
  await waitFor(()=>expect(route).toHaveBeenLastCalledWith(saved));
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>!call[2]?.method)).toBe(true);view.unmount();
});
test('continue transfer works for an existing durable creation without allocating a replacement',async()=>{
  const saved={id:'a'.repeat(32),key:'b'.repeat(64),creation:{mask:'game' as const,steps:30000,prepare_route:true as const,route_only:true as const}};
  jest.mocked(readReconstructionLink).mockResolvedValue(saved);jest.mocked(listReconstructionLinks).mockResolvedValue([saved]);
  let started=false;
  jest.mocked(reconstructionRequest).mockImplementation(async(path)=>{if(path.endsWith('/start'))started=true;return {json:async()=>({phase:started?'matching':'uploading'})} as Response;});
  jest.mocked(uploadReconstruction).mockResolvedValue();jest.mocked(saveReconstructionLink).mockResolvedValue();
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>({} as FileSystemDirectoryHandle)} complete manageAutomaticPreparation={false} onBusyChange={()=>{}}/>);
  fireEvent.click(await screen.findByRole('button',{name:'Продолжить передачу'}));
  await waitFor(()=>expect(uploadReconstruction).toHaveBeenCalledTimes(1));
  await waitFor(()=>expect(started).toBe(true));
  expect(jest.mocked(saveReconstructionLink).mock.calls[0][2]).toBe(saved);
  expect(ensureAutomaticReconstructionLink).not.toHaveBeenCalled();view.unmount();
});
test('the explicit new-attempt action creates a distinct durable sparse intent only after a terminal result',async()=>{
  const saved={id:'a'.repeat(32),key:'b'.repeat(64),creation:{mask:'game' as const,steps:30000,prepare_route:true as const,route_only:true as const}};
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'});
  jest.mocked(readReconstructionLink).mockResolvedValue(saved);jest.mocked(listReconstructionLinks).mockResolvedValue([saved]);jest.mocked(saveReconstructionLink).mockResolvedValue();
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'quality_rejected'})} as Response);
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>({} as FileSystemDirectoryHandle)} complete manageAutomaticPreparation={false} onBusyChange={()=>{}}/>);
  fireEvent.click(await screen.findByRole('button',{name:'Новое отдельное задание'}));
  fireEvent.click(await screen.findByRole('button',{name:'Подготовить ориентиры'}));
  await waitFor(()=>expect(saveReconstructionLink).toHaveBeenCalled());
  expect(jest.mocked(saveReconstructionLink).mock.calls[0][2]).toMatchObject({id:'e'.repeat(32),creation:{mask:'game',prepare_route:true,route_only:true}});
  expect(ensureAutomaticReconstructionLink).not.toHaveBeenCalled();view.unmount();
});
