import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {TeachingReconstruction} from '@/src/features/stream/TeachingReconstruction';
import {reconstructionRequest} from '@/src/features/stream/reconstructionClient';
import {listReconstructionLinks,readReconstructionLink,saveReconstructionLink} from '@/src/features/stream/reconstructionLink';
jest.mock('next/dynamic',()=>()=>function Placeholder(){return null;});
jest.mock('@/src/features/stream/reconstructionLink',()=>({readReconstructionLink:jest.fn(async()=>null),listReconstructionLinks:jest.fn(async()=>[]),saveReconstructionLink:jest.fn(async()=>{}),validReconstructionJob:(value:unknown)=>!!value}));
jest.mock('@/src/features/stream/reconstructionClient',()=>({
  ...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn(),uploadReconstruction:jest.fn(),
}));
afterEach(()=>{sessionStorage.clear();jest.clearAllMocks();});
test('a recording marked HUD-free defaults to no HUD mask and 30000 iterations',async()=>{
  const view=render(<TeachingReconstruction clip={'c'.repeat(32)} scope={'d'.repeat(32)} folder={()=>null} complete hudHidden onBusyChange={()=>{}}/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Построить 3D-сцену'})).toBeEnabled());
  expect(screen.getByRole('combobox',{name:/Маска/i})).toHaveValue('none');
  expect(screen.getByRole('combobox',{name:'Качество обработки'})).toHaveValue('30000');
  view.unmount();
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
  (readReconstructionLink as jest.Mock).mockResolvedValueOnce(first);
  (listReconstructionLinks as jest.Mock).mockResolvedValueOnce([first]);
  (saveReconstructionLink as jest.Mock).mockRejectedValueOnce(Error('disk_write_failed'));
  (reconstructionRequest as jest.Mock).mockResolvedValue({json:async()=>({phase:'failed'})});
  const view=render(<TeachingReconstruction clip={clip} scope={scope} folder={()=>folder} complete onBusyChange={()=>{}}/>);
  fireEvent.click(await screen.findByRole('button',{name:'Новое отдельное задание'}));
  fireEvent.click(screen.getByRole('button',{name:'Построить 3D-сцену'}));
  await screen.findByText(/Не удалось сохранить ссылку на новое задание/);
  expect(screen.getByRole('combobox',{name:'Сохранённая попытка реконструкции'})).toBeEnabled();
  expect((reconstructionRequest as jest.Mock).mock.calls.some(([, , init])=>init?.method==='POST')).toBe(false);
  view.unmount();
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
