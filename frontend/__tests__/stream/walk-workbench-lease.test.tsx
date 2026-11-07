import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {TeachingWorkbench} from '@/src/features/stream/TeachingWorkbench';
import {connectTeaching} from '@/src/features/stream/teachingConnection';
import type {WalkInputControl,WalkInputLease} from '@/src/features/stream/walkPilot';
import type {TeachingInput} from '@/src/features/stream/teachingContacts';
import {TextEncoder} from 'node:util';
jest.mock('@/src/features/stream/teachingConnection',()=>({connectTeaching:jest.fn()}));
jest.mock('@/src/features/stream/TeachingLocalWorker',()=>({TeachingLocalWorker:()=>null}));
jest.mock('@/lib/store',()=>({useAuthStore:(select:(s:unknown)=>unknown)=>select({accessToken:'fixture',sessionVersion:1,user:{id:'u',org_id:'o'}})}));
let mockReady=false,mockLease:WalkInputLease|undefined,mockState:(s:string)=>void=()=>{},mockJournal:(e:TeachingInput)=>void=()=>{};
const mockSet=jest.fn(),mockClose=jest.fn();
jest.mock('@/src/features/stream/TeachingNavigation',()=>({TeachingNavigation:({walkInput}:{walkInput:WalkInputControl})=><button onClick={()=>{void walkInput.open(new AbortController().signal,()=>{}).then(value=>{mockLease=value;});}}>fixture-open-walk</button>}));
jest.mock('@/src/features/stream/teachingContacts',()=>({...jest.requireActual('@/src/features/stream/teachingContacts'),TeachingContacts:jest.fn().mockImplementation((_endpoint,_binding,_fresh,journal,state)=>{
  mockState=(value:string)=>{mockReady=value==='ready';state(value);};mockJournal=journal;
  return {get isReady(){return mockReady;},set:mockSet,hasContact:()=>false,isNeutral:true,
    close:mockClose.mockImplementation(async()=>{mockReady=false;journal({stage:'closed',at_ms:1000,sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});return true;})};
})}));

test('visible emulator focus survives delayed native startup and movement telemetry requires stick receipts',async()=>{
  mockReady=false;mockLease=undefined;mockClose.mockClear();mockSet.mockClear();
  jest.spyOn(performance,'now').mockReturnValue(1000);
  Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async()=>new Uint8Array(32).buffer}});
  jest.mocked(connectTeaching).mockImplementation(async(_id,_token,_video,_signal,result,_failure,message)=>{
    result({path:'nat'} as never);message({type:'attached'});
    return {fresh:()=>true,binding:()=>({captureEpoch:'e'.repeat(32),width:960,height:540}),endpoint:()=>({}),
      close:jest.fn(),worker:{terminate:jest.fn(),postMessage:jest.fn()}} as never;
  });
  const view=render(<TeachingWorkbench deviceId="walk-lease-fixture" readOnly={false}/>);
  const connect=screen.getByRole('button',{name:'Подключить поток'});await waitFor(()=>expect(connect).toBeEnabled());fireEvent.click(connect);
  await waitFor(()=>expect(screen.getByRole('button',{name:/3 · Направление/})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:/3 · Направление/}));
  await screen.findByText('fixture-open-walk');fireEvent.click(screen.getByText('fixture-open-walk'));
  expect(mockLease).toBeUndefined();fireEvent.blur(window);await act(async()=>{await Promise.resolve();});
  expect(mockClose).not.toHaveBeenCalled();
  await act(async()=>{mockState('ready');});await waitFor(()=>expect(mockLease).toBeDefined());
  const lease=mockLease!;lease.permit!(1200);lease.set([0,-.35]);expect(lease.translating!()).toBe(false);
  const point=mockSet.mock.calls.at(-1)![1];
  act(()=>mockJournal({stage:'receipt',at_ms:1000,sequence:1,gesture:1,action:2,pointer_id:1,outcome:'applied',...point}));
  expect(lease.translating!()).toBe(false);
  act(()=>mockJournal({stage:'receipt',at_ms:1000,sequence:2,gesture:1,action:2,pointer_id:0,outcome:'applied',...point}));
  expect(lease.translating!()).toBe(true);lease.set([0,0]);expect(lease.translating!()).toBe(false);
  fireEvent.blur(window);await act(async()=>{await Promise.resolve();});expect(mockClose).not.toHaveBeenCalled();
  await act(async()=>{await lease.close();});view.unmount();jest.restoreAllMocks();
});
