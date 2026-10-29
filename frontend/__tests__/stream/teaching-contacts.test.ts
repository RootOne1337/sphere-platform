import { TeachingContacts, stickPoint, type TeachingInput } from '@/src/features/stream/teachingContacts';
import type { DirectControlEndpoint } from '@/src/features/stream/directPointerTransport';

const binding={captureEpoch:'00112233-4455-6677-8899-aabbccddeeff',width:960,height:540};
function fixture(observedRtt?: (milliseconds:number)=>void,idleFresh?:()=>boolean) {
  const sent: Record<string,unknown>[]=[],journal:TeachingInput[]=[],states:string[]=[];
  let listener:(v:unknown)=>void=()=>{};let fresh=true;
  const endpoint:DirectControlEndpoint={session:'a'.repeat(32),sharedInput:true,readyState:1,bufferedAmount:0,
    capture:()=>binding,send:raw=>sent.push(JSON.parse(raw)),listen:fn=>{listener=fn;return()=>{};}};
  const driver=new TeachingContacts(endpoint,binding,()=>fresh,event=>journal.push(event),(state,reason)=>states.push(reason??state),observedRtt,idleFresh);
  const envelope={session_id:endpoint.session,capture_epoch:binding.captureEpoch,contact_protocol:1,max_pointers:3,owner:'b'.repeat(32)};
  const receipt=(fields:Record<string,unknown>)=>listener({type:'shared_input_status',...envelope,device_uptime_ms:1000,...fields});
  const ready=()=>{listener({type:'touch_session',...envelope,frame_width:960,frame_height:540});receipt({sequence:0,gesture:0,action:4,pointer_id:-1,outcome:'ready'});};
  const ack=()=>{const p=sent.at(-1)!;receipt({sequence:p.sequence,gesture:p.gesture,action:p.action,pointer_id:p.pointer_id??-1,outcome:p.action===4?'alive':'applied'});};
  return {driver,sent,journal,states,ready,receipt,ack,stale:()=>{fresh=false;},resume:()=>{fresh=true;}};
}
beforeEach(()=>jest.useFakeTimers());afterEach(()=>{jest.clearAllTimers();jest.useRealTimers();});
test('W remains held while camera and action acquire independent contacts; one physical gesture',()=>{
  const f=fixture();f.ready();f.driver.set(0,{x:100,y:350});f.ack();
  f.driver.set(1,{x:700,y:200});f.ack();f.driver.set(2,{x:850,y:450});f.ack();
  f.driver.set(1,{x:750,y:210});f.ack();f.driver.set(2,null);f.ack();
  const events=f.sent.filter(e=>e.type==='touch_contact_event');
  expect(events.map(e=>[e.pointer_id,e.action])).toEqual([[0,0],[1,0],[2,0],[1,2],[2,1]]);
  expect(events.every(e=>e.gesture===1)).toBe(true);expect(f.driver.isNeutral).toBe(false);
});
test('W direction corrections only emit MOVE; adjacent camera moves coalesce without dropping UP',()=>{
  const f=fixture();f.ready();f.driver.set(0,{x:100,y:350});
  f.driver.set(0,{x:110,y:350});f.driver.set(0,{x:120,y:350});f.driver.set(0,null);
  f.ack();expect(f.sent.at(-1)).toMatchObject({action:2,x:120});f.ack();expect(f.sent.at(-1)).toMatchObject({action:1});f.ack();
  expect(f.driver.isNeutral).toBe(true);expect(f.journal.filter(e=>e.stage==='receipt')).toHaveLength(3);
});
test('heartbeat extends hold without another DOWN and native release is required to complete',async()=>{
  const f=fixture();f.ready();f.driver.set(0,{x:100,y:350});f.ack();jest.advanceTimersByTime(325);
  expect(f.sent.at(-1)).toMatchObject({type:'touch_event',action:4,gesture:1});f.ack();
  const close=f.driver.close();expect(f.sent.at(-1)).toEqual({type:'touch_close'});
  f.receipt({sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed'});
  await expect(close).resolves.toBe(true);expect(f.journal.at(-1)?.outcome).toBe('closed');
});

test('closing a held control records native CANCEL time and preserves confirmed release on subsequent close',async()=>{
  const f=fixture();f.ready();f.driver.set(0,{x:100,y:350});f.ack();
  const close=f.driver.close();f.receipt({sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed',device_uptime_ms:2500});
  await expect(close).resolves.toBe(true);await expect(f.driver.close()).resolves.toBe(true);
  expect(f.journal.at(-1)).toMatchObject({stage:'closed',outcome:'closed',device_uptime_ms:2500,cancelled_pointers:[0]});
});

test('unsolicited native CLOSED remains authoritative and never reopens a contact',async()=>{
  const f=fixture();f.ready();f.driver.set(0,{x:100,y:350});f.ack();
  f.receipt({sequence:0,gesture:0,action:3,pointer_id:-1,outcome:'closed',device_uptime_ms:3500});
  expect(f.driver.isReady).toBe(false);await expect(f.driver.close()).resolves.toBe(true);
  f.driver.set(0,{x:120,y:350});expect(f.sent.filter(e=>e.action===0)).toHaveLength(1);
});
test('lost frames revoke all contacts; unanswered close stays unknown and is never replayed',async()=>{
  const f=fixture();f.ready();f.driver.set(0,{x:100,y:350});f.ack();f.stale();jest.advanceTimersByTime(25);
  expect(f.states).toContain('contact_video_stale');const close=f.driver.close();jest.advanceTimersByTime(2600);
  await expect(close).resolves.toBe(false);expect(f.journal.at(-1)?.outcome).toBe('unknown');
  f.driver.set(0,{x:100,y:350});expect(f.sent.filter(e=>e.action===0)).toHaveLength(1);
});

test('an empty pedestrian owner can wait through a short gap, but cannot send stale DOWN',()=>{
  const f=fixture(undefined,()=>true);f.ready();f.stale();jest.advanceTimersByTime(325);
  expect(f.sent.at(-1)).toMatchObject({action:4});f.ack();
  expect(f.driver.isReady).toBe(true);expect(f.states).not.toContain('contact_video_stale');
  f.driver.set(0,{x:100,y:350});
  expect(f.driver.failureReason).toBe('stale_contact');
  expect(f.sent.filter(e=>e.type==='touch_contact_event')).toHaveLength(0);
});

test('empty owner resumes only on new video and still closes when the idle allowance ends',()=>{
  let allowed=true;const f=fixture(undefined,()=>allowed);f.ready();f.stale();jest.advanceTimersByTime(325);f.ack();
  f.resume();f.driver.set(0,{x:100,y:350});f.ack();f.driver.set(0,null);f.ack();
  f.stale();allowed=false;jest.advanceTimersByTime(25);
  expect(f.driver.failureReason).toBe('contact_video_stale');expect(f.sent.at(-1)).toEqual({type:'touch_close'});
});

test('idle allowance never protects held or unconfirmed movement from stale video',()=>{
  const f=fixture(undefined,()=>true);f.ready();f.driver.set(0,{x:100,y:350});
  f.stale();jest.advanceTimersByTime(25);
  expect(f.driver.failureReason).toBe('contact_video_stale');expect(f.sent.at(-1)).toEqual({type:'touch_close'});
});
test('legacy ready cannot masquerade as three-contact support',()=>{
  const f=fixture();f.receipt({sequence:0,outcome:'ready',contact_protocol:undefined});
  expect(f.states).toContain('contact_protocol_required');expect(f.driver.isReady).toBe(false);
  expect(f.sent.filter(e=>e.type==='touch_contact_event')).toHaveLength(0);
});

test('unanswered applied receipt keeps its 500ms fence and reports ACK timeout separately',()=>{
  const f=fixture();f.ready();f.driver.set(0,{x:100,y:350});jest.advanceTimersByTime(500);
  expect(f.states).toContain('contact_ack_timeout');expect(f.sent.at(-1)?.type).toBe('touch_close');
});

test('missing READY keeps its six-second fence and does not pretend video was stale',()=>{
  const f=fixture();jest.advanceTimersByTime(6000);
  expect(f.states).toContain('contact_ready_timeout');expect(f.states).not.toContain('contact_video_stale');
});
test('wrong pointer receipt retires owner; no queued correction runs after uncertainty',()=>{
  const f=fixture();f.ready();f.driver.set(0,{x:100,y:350});f.driver.set(0,{x:120,y:350});
  f.receipt({sequence:1,gesture:1,action:0,pointer_id:1,outcome:'applied'});
  expect(f.states).toContain('contact_receipt_unknown');expect(f.sent.at(-1)?.type).toBe('touch_close');
  expect(f.sent.filter(e=>e.action===2)).toHaveLength(0);
});
test('old input queue is rejected rather than executed late',()=>{
  const f=fixture();f.ready();f.driver.set(0,{x:100,y:350});f.driver.set(1,{x:700,y:200});jest.advanceTimersByTime(225);f.ack();
  expect(f.states).toContain('stale_contact');expect(f.sent.at(-1)?.type).toBe('touch_close');
});

test('a late ACK delivered before an overdue timer cannot authorize queued movement',()=>{
  const observe=jest.fn(),f=fixture(observe);f.ready();
  f.driver.set(0,{x:100,y:350});f.driver.set(0,{x:120,y:350});
  const now=jest.spyOn(performance,'now').mockReturnValue(600);
  try {
    f.ack();
    expect(f.states).toContain('contact_ack_timeout');
    expect(f.sent.at(-1)?.type).toBe('touch_close');
    expect(f.sent.filter(e=>e.action===2)).toHaveLength(0);
    expect(observe).not.toHaveBeenCalled();
  } finally { now.mockRestore(); }
});

test('RTT telemetry is measured from the command and cannot interrupt an applied receipt',()=>{
  const observe=jest.fn(()=>{throw Error('optional_observer_failed');}),f=fixture(observe);f.ready();
  f.driver.set(0,{x:100,y:350});jest.advanceTimersByTime(12);f.ack();
  expect(f.driver.lastReceiptRttMs).toBe(12);expect(observe).toHaveBeenCalledWith(12);
  f.driver.set(0,{x:120,y:350});f.ack();
  expect(f.sent.at(-1)).toMatchObject({action:2,x:120});
  expect(f.states).not.toContain('contact_ack_timeout');
  expect(f.journal.filter(e=>e.stage==='receipt')).toHaveLength(2);
});
test('analog stick normalizes diagonal and Shift reduces amplitude without releasing',()=>{
  expect(stickPoint(new Set(['KeyW']),{x:100,y:300},50)).toEqual({x:100,y:250});
  expect(stickPoint(new Set(['KeyW']),{x:100,y:300},50,true)).toEqual({x:100,y:280});
  expect(stickPoint(new Set(['KeyW','KeyS']),{x:100,y:300},50)).toBeNull();
  expect(stickPoint(new Set(['KeyW','KeyD']),{x:100,y:300},50)).toEqual({x:135,y:265});
});
