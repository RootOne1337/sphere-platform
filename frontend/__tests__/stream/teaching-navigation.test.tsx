import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {TeachingNavigation} from '@/src/features/stream/TeachingNavigation';
import {reconstructionRequest} from '@/src/features/stream/reconstructionClient';
jest.mock('@/src/features/stream/reconstructionClient',()=>({...jest.requireActual('@/src/features/stream/reconstructionClient'),reconstructionRequest:jest.fn()}));
const job={id:'a'.repeat(32),key:'b'.repeat(64)};
beforeEach(()=>{
  jest.clearAllMocks();
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'cccccccc-cccc-cccc-cccc-cccccccccccc'});
  jest.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({clearRect:jest.fn(),drawImage:jest.fn()} as never);
});
afterEach(()=>jest.restoreAllMocks());
test('opening a live preview reads readiness but never starts capture, a model or Android input',async()=>{
  jest.mocked(reconstructionRequest).mockResolvedValue({json:async()=>({phase:'ready'})} as Response);
  render(<TeachingNavigation job={job} video={{current:null}} ready binding={{captureEpoch:'e'.repeat(32),width:1920,height:1080}}/>);
  await waitFor(()=>expect(reconstructionRequest).toHaveBeenCalledWith(`/jobs/${job.id}/navigation`,job,expect.any(Object)));
  expect(screen.getByRole('button',{name:'Проверить направление · 120 с'})).toBeDisabled();
  expect(jest.mocked(reconstructionRequest).mock.calls.every(call=>call[2]?.method!=='POST')).toBe(true);
});
test('unmount closes the same uncertain start intent and a late acknowledgement cannot resume it',async()=>{
  let acknowledge:(value:Response)=>void=()=>{};
  jest.mocked(reconstructionRequest).mockImplementation(async(path,_job,init)=>{
    if(path.endsWith('/start'))return new Promise(resolve=>{acknowledge=resolve;});
    if(init?.method==='POST')return {json:async()=>({phase:'closed'})} as Response;
    return {json:async()=>({phase:'ready'})} as Response;
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
