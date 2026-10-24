import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {TeachingReconstruction} from '@/src/features/stream/TeachingReconstruction';
import {reconstructionRequest} from '@/src/features/stream/reconstructionClient';
jest.mock('next/dynamic',()=>()=>function Placeholder(){return null;});
jest.mock('@/src/features/stream/reconstructionLink',()=>({readReconstructionLink:jest.fn(async()=>null),saveReconstructionLink:jest.fn(async()=>{}),validReconstructionJob:(value:unknown)=>!!value}));
jest.mock('@/src/features/stream/reconstructionClient',()=>({
  reconstructionRequest:jest.fn(),terminalReconstruction:(state:{phase:string})=>['failed','cancelled','complete'].includes(state.phase),uploadReconstruction:jest.fn(),
}));
afterEach(()=>{sessionStorage.clear();jest.clearAllMocks();});
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
