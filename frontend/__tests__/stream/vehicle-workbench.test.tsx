import React from 'react';
import {TextEncoder} from 'node:util';
import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {TeachingWorkbench} from '@/src/features/stream/TeachingWorkbench';
import {connectTeaching} from '@/src/features/stream/teachingConnection';
import type {VehicleInputControl,VehicleInputLease} from '@/src/features/stream/vehiclePilot';

jest.mock('@/src/features/stream/teachingConnection',()=>({connectTeaching:jest.fn()}));
jest.mock('@/src/features/stream/TeachingLocalWorker',()=>({TeachingLocalWorker:()=>null}));
jest.mock('@/lib/store',()=>({useAuthStore:(select:(s:unknown)=>unknown)=>select({accessToken:'fixture-token',sessionVersion:1,user:{id:'fixture-user',org_id:'fixture-org'}})}));
let mockLease:VehicleInputLease|null=null;
jest.mock('@/src/features/stream/TeachingNavigation',()=>({TeachingNavigation:({vehicleInput}:{vehicleInput:VehicleInputControl})=>
  <button disabled={!!vehicleInput.issue} onClick={()=>{void vehicleInput.open(new AbortController().signal,()=>{}).then(lease=>{
    mockLease=lease;lease.permit?.(performance.now()+300);lease.setVehicle({pedal:'throttle',steering:.2});
  });}}>Fixture: open calibrated vehicle lease</button>}));

const binding={captureEpoch:'00112233-4455-6677-8899-aabbccddeeff',width:960,height:540};
let sent:Record<string,unknown>[];
beforeEach(()=>{
  jest.clearAllMocks();localStorage.clear();sent=[];mockLease=null;
  Object.defineProperty(globalThis,'TextEncoder',{configurable:true,value:TextEncoder});
  Object.defineProperty(window,'PointerEvent',{configurable:true,value:MouseEvent});
  Object.defineProperty(crypto,'subtle',{configurable:true,value:{digest:async()=>new Uint8Array(32).fill(170).buffer}});
  Object.defineProperty(crypto,'randomUUID',{configurable:true,value:()=> 'cccccccc-cccc-cccc-cccc-cccccccccccc'});
  jest.mocked(connectTeaching).mockImplementation(async(_id,_token,_video,_signal,onResult,_fault,onMessage)=>{
    let listener:(v:unknown)=>void=()=>{};
    const envelope={session_id:'a'.repeat(32),owner:'b'.repeat(32),capture_epoch:binding.captureEpoch,contact_protocol:1,max_pointers:3};
    const reply=(fields:Record<string,unknown>)=>listener({type:'shared_input_status',...envelope,device_uptime_ms:1000,...fields});
    const endpoint={session:'a'.repeat(32),sharedInput:true,readyState:1,bufferedAmount:0,capture:()=>binding,
      listen:(callback:(v:unknown)=>void)=>{listener=callback;return()=>{};},send:(raw:string)=>{
        const event=JSON.parse(raw);sent.push(event);
        queueMicrotask(()=>{
          if(event.type==='touch_open'){
            listener({type:'touch_session',...envelope,frame_width:binding.width,frame_height:binding.height});
            reply({sequence:0,gesture:0,action:4,pointer_id:-1,outcome:'ready'});
          }else if(event.type==='touch_close')reply({sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
          else reply({sequence:event.sequence,gesture:event.gesture,action:event.action,pointer_id:event.pointer_id??-1,outcome:event.action===4?'alive':'applied'});
        });
      }};
    onResult({path:'host',state:'ready'} as never);onMessage({type:'attached'});
    return {fresh:()=>true,idleInputFresh:()=>true,binding:()=>binding,endpoint:()=>endpoint,
      worker:{postMessage:jest.fn(),terminate:jest.fn()},close:jest.fn()} as never;
  });
});
afterEach(()=>jest.restoreAllMocks());

async function driveFixture(){
  const view=render(<TeachingWorkbench deviceId="vehicle-lease-fixture" readOnly={false}/>);
  const connect=screen.getByRole('button',{name:'Подключить поток'});await waitFor(()=>expect(connect).toBeEnabled());fireEvent.click(connect);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Включить управление'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:/3 · Направление/}));
  fireEvent.click(screen.getByRole('button',{name:'Настроить скутер · педали и стик'}));
  const start=screen.getByRole('button',{name:'Fixture: open calibrated vehicle lease'});await waitFor(()=>expect(start).toBeEnabled());fireEvent.click(start);
  await waitFor(()=>expect(sent.some(e=>e.pointer_id===0&&e.action===0)).toBe(true));
  const video=screen.getByLabelText('Игровой экран: назначенные клавиши и мышь; Escape — остановить запись');
  jest.spyOn(video,'getBoundingClientRect').mockReturnValue({left:0,top:0,width:960,height:540,right:960,bottom:540,x:0,y:0,toJSON:()=>({})});
  return {view,video};
}

test('the real vehicle lease uses pedal0/steering1 and a web camera attempt releases it without injecting a swipe',async()=>{
  const {view,video}=await driveFixture();
  expect(sent.filter(e=>e.pointer_id===1&&e.action===0)).toHaveLength(1);
  expect(sent.filter(e=>e.pointer_id===0&&e.action===0)).toHaveLength(1);
  fireEvent.pointerDown(video,{button:0,clientX:700,clientY:200,pointerId:7});
  await waitFor(()=>expect(sent.some(e=>e.type==='touch_close')).toBe(true));
  expect(mockLease?.failure?.()).toBe('vehicle_manual_override');
  expect(sent.filter(e=>e.pointer_id===2)).toHaveLength(0);
  await act(async()=>{await mockLease?.close();});view.unmount();
});

test('a mapped movement key is an explicit vehicle override, not a second native input owner',async()=>{
  const {view,video}=await driveFixture();fireEvent.keyDown(video,{code:'KeyW'});
  await waitFor(()=>expect(sent.some(e=>e.type==='touch_close')).toBe(true));
  expect(sent.filter(e=>e.type==='touch_open')).toHaveLength(1);
  expect(sent.filter(e=>e.pointer_id===0&&e.action===0)).toHaveLength(1);
  expect(mockLease?.failure?.()).toBe('vehicle_manual_override');
  await act(async()=>{await mockLease?.close();});view.unmount();
});

test('one admitted vehicle target ramps between replies and expiry cannot restart gas from a renewed permit alone',async()=>{
  const {view}=await driveFixture();
  // Fixture submits exactly one target; extra steering MOVEs must come from
  // the bounded actuator loop, not fabricated localization replies.
  await waitFor(()=>expect(sent.filter(e=>e.pointer_id===1&&e.action===2).length).toBeGreaterThanOrEqual(3));
  expect(sent.filter(e=>e.pointer_id===0&&e.action===0)).toHaveLength(1);
  expect(sent.filter(e=>e.pointer_id===1&&e.action===0)).toHaveLength(1);
  await waitFor(()=>expect(sent.some(e=>e.pointer_id===0&&e.action===1)).toBe(true));
  mockLease!.permit!(performance.now()+250);
  await act(async()=>{await new Promise(resolve=>setTimeout(resolve,60));});
  expect(sent.filter(e=>e.pointer_id===0&&e.action===0)).toHaveLength(1);
  expect(mockLease!.translating!()).toBe(false);
  await act(async()=>{await mockLease?.close();});view.unmount();
});

test('ten fresh throttle decisions keep one native pedal DOWN until explicit neutral',async()=>{
  const {view}=await driveFixture();
  for(let observation=0;observation<10;observation++){
    mockLease!.permit!(performance.now()+300);
    mockLease!.setVehicle({pedal:'throttle',steering:.2});
    await act(async()=>{await new Promise(resolve=>setTimeout(resolve,15));});
  }
  const pedal=()=>sent.filter(e=>e.type==='touch_contact_event'&&e.pointer_id===0);
  expect(pedal().filter(e=>e.action===0)).toHaveLength(1);
  expect(pedal().filter(e=>e.action===1)).toHaveLength(0);
  mockLease!.neutral!();
  await waitFor(()=>expect(pedal().filter(e=>e.action===1)).toHaveLength(1));
  expect(pedal().filter(e=>e.action===0)).toHaveLength(1);
  await act(async()=>{await mockLease?.close();});view.unmount();
});
