import {PilotCommandLoop} from '@/src/features/stream/pilotCommandLoop';
import {WalkStickSlew} from '@/src/features/stream/walkPilot';
import {TeachingContacts} from '@/src/features/stream/teachingContacts';
import {VehicleContacts,type VehicleCommand} from '@/src/features/stream/vehiclePilot';
import {blackRussiaScooterProfile} from '@/src/features/stream/teachingProfileStorage';
import type {DirectControlEndpoint} from '@/src/features/stream/directPointerTransport';

beforeEach(()=>jest.useFakeTimers());afterEach(()=>{jest.clearAllTimers();jest.useRealTimers();});

test('5Hz perception produces bounded 50Hz vector interpolation without extending its deadline',()=>{
  const sent:{at:number;value:number;until:number}[]=[],slew=new WalkStickSlew(),neutral=jest.fn();
  const loop=new PilotCommandLoop<[number,number]>({maxHoldMs:250,ready:()=>true,fresh:()=>true,neutral,failure:jest.fn(),
    apply:(target,now,until)=>sent.push({at:now,value:slew.next(target,now)[1],until})});
  loop.update([0,-.35],250);jest.advanceTimersByTime(200);
  expect(sent).toHaveLength(11);expect(sent.at(-1)!.value).toBeCloseTo(-.3);
  expect(sent.every(row=>row.until===250)).toBe(true);
  loop.update([0,-.35],450);jest.advanceTimersByTime(200);
  expect(sent.at(-1)!.value).toBeCloseTo(-.35);expect(neutral).not.toHaveBeenCalled();
  jest.advanceTimersByTime(60);expect(neutral).toHaveBeenCalledTimes(1);
  const count=sent.length;jest.advanceTimersByTime(500);expect(sent).toHaveLength(count);
  expect(sent.every(row=>row.at<row.until)).toBe(true);loop.close();
});

test('source loss, explicit neutral and close discard the target; timer cannot resume it',()=>{
  let fresh=true;const apply=jest.fn(),neutral=jest.fn();
  const loop=new PilotCommandLoop<number>({maxHoldMs:250,ready:()=>true,fresh:()=>fresh,apply,neutral,failure:jest.fn()});
  loop.update(1,200);fresh=false;jest.advanceTimersByTime(20);expect(neutral).toHaveBeenCalledTimes(1);
  fresh=true;jest.advanceTimersByTime(50);expect(apply).toHaveBeenCalledTimes(1);
  loop.update(2,250);loop.pause();jest.advanceTimersByTime(40);expect(apply).toHaveBeenCalledTimes(2);
  loop.update(3,300);loop.close();jest.advanceTimersByTime(100);expect(apply).toHaveBeenCalledTimes(3);
  expect(jest.getTimerCount()).toBe(0);
  expect(()=>loop.update(4,400)).toThrow('pilot_command_expired');
});

test('a throwing neutral still reports native closure and leaves no timer or restart path',()=>{
  let fresh=true;const failure=jest.fn(),apply=jest.fn();
  const loop=new PilotCommandLoop<number>({maxHoldMs:250,ready:()=>true,fresh:()=>fresh,apply,failure,
    neutral:()=>{throw Error('neutral_transport_failed');}});
  loop.update(1,200);fresh=false;jest.advanceTimersByTime(20);
  expect(failure).toHaveBeenCalledTimes(1);expect(jest.getTimerCount()).toBe(0);
  fresh=true;expect(()=>loop.update(2,200)).toThrow('pilot_command_expired');
  jest.advanceTimersByTime(100);expect(apply).toHaveBeenCalledTimes(1);
});

test('failed interpolation neutralizes once and reports failure without a future retry',()=>{
  let failed=false;const apply=jest.fn(()=>{if(failed)throw Error('native_failed');}),neutral=jest.fn(),failure=jest.fn();
  const loop=new PilotCommandLoop<number>({maxHoldMs:250,ready:()=>true,fresh:()=>true,apply,neutral,failure});
  loop.update(1,200);failed=true;jest.advanceTimersByTime(20);
  expect(failure).toHaveBeenCalledTimes(1);expect(neutral).toHaveBeenCalledTimes(1);
  jest.advanceTimersByTime(100);expect(apply).toHaveBeenCalledTimes(2);loop.close();
});

test('slow native ACKs coalesce steering MOVE updates; held gas and steering do not become repeated DOWNs',()=>{
  const binding={captureEpoch:'e'.repeat(32),width:1920,height:1080},sent:Record<string,unknown>[]=[],states:string[]=[];
  let listener:(value:unknown)=>void=()=>{};
  const endpoint:DirectControlEndpoint={session:'a'.repeat(32),sharedInput:true,readyState:1,bufferedAmount:0,capture:()=>binding,
    send:raw=>sent.push(JSON.parse(raw)),listen:fn=>{listener=fn;return()=>{};}};
  const envelope={session_id:endpoint.session,capture_epoch:binding.captureEpoch,contact_protocol:1,max_pointers:3,owner:'b'.repeat(32)};
  const receipt=(fields:Record<string,unknown>)=>listener({type:'shared_input_status',...envelope,device_uptime_ms:1000,...fields});
  const driver=new TeachingContacts(endpoint,binding,()=>true,()=>{},(state,reason)=>states.push(reason??state),undefined,()=>true,{x:288,y:885},true,'vehicle');
  listener({type:'touch_session',...envelope,frame_width:1920,frame_height:1080});
  receipt({sequence:0,gesture:0,action:4,pointer_id:-1,outcome:'ready'});
  const contacts=new VehicleContacts(driver,blackRussiaScooterProfile(binding),binding);
  const loop=new PilotCommandLoop<VehicleCommand>({maxHoldMs:350,ready:()=>driver.isReady,fresh:()=>true,
    neutral:()=>{contacts.neutral(performance.now());driver.neutralize();},failure:()=>{},
    apply:(command,now,until)=>contacts.apply(command,now,until)});
  loop.update({pedal:'throttle',steering:.35},350);
  let lastAck=0;
  for(let i=0;i<12;i++){
    jest.advanceTimersByTime(50);
    if(i===3||i===7)loop.update({pedal:'throttle',steering:i===3?-.2:.1},performance.now()+300);
    // One slot and a slow 100ms native response; no artificial instant ACKs.
    if(i%2===1){const event=sent.at(-1)!;
      if(Number(event.sequence)>lastAck){lastAck=Number(event.sequence);receipt({sequence:event.sequence,gesture:event.gesture,
        action:event.action,pointer_id:event.pointer_id??-1,outcome:event.action===4?'alive':'applied'});}}
  }
  expect(states).not.toContain('contact_queue_full');expect(driver.isReady).toBe(true);
  expect(sent.filter(e=>e.pointer_id===0&&e.action===0)).toHaveLength(1);
  expect(sent.filter(e=>e.pointer_id===1&&e.action===0)).toHaveLength(1);
  expect(sent.filter(e=>e.pointer_id===1&&e.action===2).length).toBeGreaterThan(2);
  expect(sent.filter(e=>e.action===1)).toHaveLength(0);loop.close();void driver.close();
});
