import {PilotCommandLoop} from '@/src/features/stream/pilotCommandLoop';
import {WalkStickSlew,applyWalkingStick,walkDecisionDeadline} from '@/src/features/stream/walkPilot';
import {calibrateProfile,defaultTeachingProfile} from '@/src/features/stream/teachingKeymap';
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


/** Real contact owner/ACK queue with raw RGB independent of slower perception. */
function pedestrianReplay(ackMs=5){
  const binding={captureEpoch:'e'.repeat(32),width:960,height:540},center={x:150,y:400};
  const profile=calibrateProfile(defaultTeachingProfile,binding,'stick',center);
  const sent:(Record<string,unknown>&{at:number})[]=[],states:string[]=[],neutralAt:number[]=[];
  let listener:(value:unknown)=>void=()=>{},lastRgbAt=performance.now(),source=true,acknowledge=true;
  const fresh=()=>source&&performance.now()-lastRgbAt<=250;
  const envelope={session_id:'a'.repeat(32),capture_epoch:binding.captureEpoch,contact_protocol:1,max_pointers:3,owner:'b'.repeat(32)};
  const endpoint:DirectControlEndpoint={session:envelope.session_id,sharedInput:true,readyState:1,bufferedAmount:0,capture:()=>binding,
    send:raw=>{const event=JSON.parse(raw);sent.push({...event,at:performance.now()});
      if(acknowledge&&(event.type==='touch_contact_event'||event.type==='touch_event'))setTimeout(()=>listener({type:'shared_input_status',...envelope,
        device_uptime_ms:Math.round(performance.now()),sequence:event.sequence,gesture:event.gesture,action:event.action,
        pointer_id:event.pointer_id??-1,outcome:event.action===4?'alive':'applied'}),ackMs);
      if(event.type==='touch_close')setTimeout(()=>listener({type:'shared_input_status',...envelope,device_uptime_ms:Math.round(performance.now()),
        sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'}),5);
    },listen:fn=>{listener=fn;return()=>{};}};
  const driver=new TeachingContacts(endpoint,binding,fresh,()=>{},(state,reason)=>states.push(reason??state),undefined,()=>source,center,true);
  listener({type:'touch_session',...envelope,frame_width:binding.width,frame_height:binding.height});
  listener({type:'shared_input_status',...envelope,device_uptime_ms:0,sequence:0,gesture:0,action:4,pointer_id:-1,outcome:'ready'});
  const slew=new WalkStickSlew(),failure=jest.fn();
  const loop=new PilotCommandLoop<[number,number]>({maxHoldMs:250,ready:()=>driver.isReady,fresh,
    neutral:()=>{neutralAt.push(performance.now());slew.next([0,0],performance.now());driver.neutralize();},failure,
    apply:(target,now,until)=>applyWalkingStick({hasContact:id=>driver.hasContact(id),set:(id,point)=>driver.set(id,point,until)},profile,binding,slew.next(target,now))});
  const rgb=setInterval(()=>{lastRgbAt=performance.now();},33);
  return {sent,states,neutralAt,driver,loop,failure,center,
    observe(capturedAt:number,target:[number,number]){const deadline=walkDecisionDeadline(capturedAt,performance.now());
      if(deadline!==null&&fresh())loop.update(target,deadline);return deadline;},
    dropAcks:()=>{acknowledge=false;},stopRgb:()=>clearInterval(rgb),presentRgb:()=>{lastRgbAt=performance.now();},loseSource:()=>{source=false;},
    dispose:()=>{loop.close();clearInterval(rgb);void driver.close();jest.advanceTimersByTime(5);}};
}

test.each([150,175,200].flatMap(compute=>[0,7,19].map(phase=>[compute,phase])))
('5Hz captured observations with %i ms processing and %i ms phase hold forward through forward-left without contact gaps',(compute,phase)=>{
  const run=pedestrianReplay();
  for(let capture=phase;capture<phase+2000;capture+=200){
    // A reply is scheduled by capture, not pre-installed ahead of the 50Hz loop.
    setTimeout(()=>setTimeout(()=>run.observe(capture,capture<phase+1000?[0,-.35]:[-.2,-.25]),compute),capture);
  }
  jest.advanceTimersByTime(phase+2000);
  expect(run.failure).not.toHaveBeenCalled();expect(run.driver.isReady).toBe(true);
  expect(run.neutralAt).toEqual([]);
  const contacts=run.sent.filter(e=>e.type==='touch_contact_event');
  expect(contacts.filter(e=>e.action===0&&e.pointer_id===0)).toHaveLength(1);
  expect(contacts.some(e=>e.action===2&&Number(e.x)<run.center.x&&Number(e.y)<run.center.y)).toBe(true);
  expect(contacts.filter(e=>e.action===1)).toHaveLength(0);
  expect(contacts.filter(e=>e.action===2&&e.x===run.center.x&&e.y===run.center.y)).toHaveLength(0);
  // No observation after the final capture: raw video alone cannot renew motion.
  const expires=Math.min(phase+1800+450,phase+1800+compute+250);
  jest.advanceTimersByTime(expires+25-performance.now());
  expect(run.neutralAt).toHaveLength(1);expect(run.neutralAt[0]).toBeGreaterThanOrEqual(expires);
  expect(run.neutralAt[0]).toBeLessThanOrEqual(expires+20);
  expect(run.sent.some(e=>e.type==='touch_contact_event'&&e.action===2&&e.x===run.center.x&&e.y===run.center.y&&e.at>=expires)).toBe(true);
  const ended=run.sent.length;jest.advanceTimersByTime(400);
  expect(run.sent.slice(ended).some(e=>e.type==='touch_contact_event'&&e.action!==1&&(e.x!==run.center.x||e.y!==run.center.y))).toBe(false);
  run.dispose();expect(jest.getTimerCount()).toBe(0);
});


test('a missing perception reply centers the held contact at the last permit; fresh RGB cannot replay it',()=>{
  const run=pedestrianReplay();
  setTimeout(()=>run.observe(0,[0,-.35]),150);
  setTimeout(()=>run.observe(200,[0,-.35]),350);
  // Capture 400 has no reply. Capture 600 is independently verified at 750.
  setTimeout(()=>run.observe(600,[-.2,-.25]),750);
  jest.advanceTimersByTime(635);
  expect(run.neutralAt).toEqual([610]);
  expect(run.sent.some(e=>e.type==='touch_contact_event'&&e.action===2&&e.x===150&&e.y===400&&e.at===610)).toBe(true);
  jest.advanceTimersByTime(114);
  expect(run.sent.some(e=>e.type==='touch_contact_event'&&e.at>610&&e.at<750&&(e.x!==150||e.y!==400))).toBe(false);
  jest.advanceTimersByTime(101);
  expect(run.sent.some(e=>e.type==='touch_contact_event'&&e.action===2&&e.at>=750&&Number(e.x)<150)).toBe(true);
  expect(run.sent.filter(e=>e.type==='touch_contact_event'&&e.action===0)).toHaveLength(1);
  expect(run.sent.filter(e=>e.type==='touch_contact_event'&&e.action===1)).toHaveLength(0);
  expect(run.failure).not.toHaveBeenCalled();run.dispose();expect(jest.getTimerCount()).toBe(0);
});

test('a raw-frame pause overrides the unexpired pose permit, and source recovery alone cannot resume motion',()=>{
  const run=pedestrianReplay();setTimeout(()=>run.observe(0,[0,-.35]),150);
  jest.advanceTimersByTime(150);run.stopRgb(); // Last raw RGB at 132; permit still valid until 400.
  jest.advanceTimersByTime(245);
  expect(run.neutralAt).toEqual([390]);
  expect(run.sent.some(e=>e.type==='touch_contact_event'&&e.action===2&&e.x===150&&e.y===400&&e.at===390)).toBe(true);
  run.presentRgb();jest.advanceTimersByTime(200);
  expect(run.sent.some(e=>e.type==='touch_contact_event'&&e.at>390&&(e.x!==150||e.y!==400))).toBe(false);
  // An actual fresh reply is required again; a 250 ms old reply is still rejected.
  expect(run.observe(performance.now()-250,[0,-.35])).toBeNull();
  run.presentRgb();expect(run.observe(performance.now()-150,[0,-.35])).not.toBeNull();
  jest.advanceTimersByTime(40);
  expect(run.sent.some(e=>e.type==='touch_contact_event'&&e.action===2&&e.at>=595&&Number(e.y)<400)).toBe(true);
  expect(run.sent.filter(e=>e.type==='touch_contact_event'&&e.action===0)).toHaveLength(1);
  expect(run.failure).not.toHaveBeenCalled();run.dispose();expect(jest.getTimerCount()).toBe(0);
});

test('loss of the bound source closes contacts even while the old pose permit has time remaining',()=>{
  const run=pedestrianReplay();setTimeout(()=>run.observe(0,[0,-.35]),150);
  jest.advanceTimersByTime(200);run.loseSource();jest.advanceTimersByTime(25);
  expect(run.driver.isReady).toBe(false);expect(run.states).toContain('contact_video_stale');
  const at=performance.now();jest.advanceTimersByTime(500);
  expect(run.sent.some(e=>e.type==='touch_contact_event'&&e.at>=at)).toBe(false);
  run.dispose();expect(jest.getTimerCount()).toBe(0);
});


test('5Hz replies with 150–200 ms processing jitter and 150 ms ACKs keep one owner through a turn',()=>{
  const run=pedestrianReplay(150),processing=[150,200,175,150,200,150,175,200,150,200];
  for(let i=0;i<10;i++){
    const capture=7+i*200;
    setTimeout(()=>setTimeout(()=>run.observe(capture,i<5?[0,-.35]:[-.2,-.25]),processing[i]),capture);
  }
  jest.advanceTimersByTime(2007);
  expect(run.neutralAt).toEqual([]);expect(run.failure).not.toHaveBeenCalled();expect(run.driver.isReady).toBe(true);
  const contacts=run.sent.filter(e=>e.type==='touch_contact_event');
  expect(contacts.filter(e=>e.action===0)).toHaveLength(1);expect(contacts.some(e=>e.action===1)).toBe(false);
  expect(contacts.some(e=>e.action===2&&Number(e.x)<150&&Number(e.y)<400)).toBe(true);
  expect(contacts.some(e=>e.action===2&&e.x===150&&e.y===400)).toBe(false);
  run.dispose();jest.advanceTimersByTime(150);expect(jest.getTimerCount()).toBe(0);
});

test('missing native ACK retires the owner; repeated fresh perception replies cannot replay its pending DOWN',()=>{
  const run=pedestrianReplay();run.dropAcks();
  for(let capture=0;capture<1000;capture+=200)setTimeout(()=>{
    if(run.driver.isReady)run.observe(capture,[0,-.35]);
  },capture+150);
  jest.advanceTimersByTime(1000);
  expect(run.states).toContain('contact_ack_timeout');expect(run.driver.isReady).toBe(false);
  expect(run.sent.filter(e=>e.type==='touch_contact_event'&&e.action===0)).toHaveLength(1);
  expect(run.sent.filter(e=>e.type==='touch_contact_event'&&e.at>=650)).toHaveLength(0);
  run.dispose();expect(jest.getTimerCount()).toBe(0);
});
