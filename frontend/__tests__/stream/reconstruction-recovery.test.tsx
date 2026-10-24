import {render,waitFor} from '@testing-library/react';
import {TeachingReconstruction} from '@/src/features/stream/TeachingReconstruction';
import {reconstructionRequest} from '@/src/features/stream/reconstructionClient';
jest.mock('next/dynamic',()=>()=>function Placeholder(){return null;});
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
  confirm({json:async()=>({phase:'failed',error:'worker_service_restarted'})});
  await waitFor(()=>expect(busy).toHaveBeenLastCalledWith(false));
  view.unmount();
});
