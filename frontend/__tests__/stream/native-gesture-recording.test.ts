import { ContinuousPointer, type PointerInputObservation } from '@/src/features/stream/continuousPointer';
import { NativeGestureRecording, type NativeGestureRecordingEvent } from '@/src/features/stream/nativeGestureRecording';
import { appendNativeRecording, recordingActions } from '@/src/features/scripts/studio/recording';

const capture = {captureEpoch:'71532996-5c56-4a17-b931-67f66d54abde',frameWidth:960,frameHeight:540};
function fixture() {
  let now=0,enabled=true;
  const events: NativeGestureRecordingEvent[]=[];
  const recorder=new NativeGestureRecording({deviceId:'owned',enabled:()=>enabled,onEvent:e=>events.push(e),now:()=>now});
  const offer=(action:0|1|2|3,x=100,y=200,at=now,sequence=action+1,gesture=1)=>{
    now=at; recorder.offered({action,x,y,at,sequence,gesture,capture});
  };
  const ack=(sequence:number,action:number,status:1|2|3=1)=>recorder.receipt({sequence,action,status,deviceUptimeMs:100,receiptRoundTripMs:1});
  return {events,recorder,offer,ack,enable:(value:boolean)=>{enabled=value;}};
}
it('records a tap only after exact DOWN and UP receipts, retaining submission time',()=>{
  const f=fixture(); f.offer(0);f.ack(1,0);f.offer(1,100,200,30,2);
  expect(f.events.map(e=>e.phase)).toEqual(['started']);
  f.ack(99,1); expect(f.events).toHaveLength(1);
  f.ack(2,1);f.ack(2,1);
  expect(f.events).toHaveLength(2);
  expect(f.events[1]).toMatchObject({phase:'finished',outcome:'confirmed',input:{at:0,endedAt:30,command:{type:'pointer_path',path:{points:[{t_ms:0,action:0,x:100,y:200},{t_ms:30,action:1,x:100,y:200}]}}}});
});
it('retains the actual pause between gestures even when the first native receipt arrives late',()=>{
  const f=fixture(); f.offer(0); f.ack(1,0); f.offer(1,100,200,30,2);
  // A second gesture starts locally while the first terminal ACK is in flight.
  f.offer(2,100,200,80,99,2); f.ack(2,1);
  const event=f.events[1]; if(event.phase!=='finished'||!event.input)throw Error('missing terminal');
  const first=appendNativeRecording([],event.input,'owned',event.requestId,event.completedAt);
  const second=appendNativeRecording(first,{deviceId:'owned',at:80,endedAt:100,dimensions:{width:960,height:540},
    command:{type:'click',x:200,y:200}},'owned','second',120);
  expect(first[0]).toMatchObject({endedAt:30,completedAt:80});
  expect(recordingActions(second)).toEqual([
    {type:'pointer_path',path:event.input.command.type==='pointer_path'?event.input.command.path:null}, {type:'sleep',ms:50}, {type:'tap',x:266,y:266},
  ]);
});
it.each([Number.NaN,Number.POSITIVE_INFINITY,-1,200])('rejects a terminal timestamp outside submission and native confirmation: %s',endedAt=>{
  expect(()=>appendNativeRecording([],{deviceId:'owned',at:0,endedAt,dimensions:{width:960,height:540},
    command:{type:'click',x:100,y:200}},'owned','invalid',100)).toThrow();
});
it('exports a confirmed straight swipe without adding ACK latency to replay pauses',()=>{
  const f=fixture();f.offer(0);f.ack(1,0);f.offer(2,200,200,100,2);f.offer(1,300,200,200,3);f.ack(3,1);
  const event=f.events[1];if(event.phase!=='finished'||!event.input)throw Error('missing terminal');
  const entries=appendNativeRecording([],event.input,'owned',event.requestId,event.completedAt);
  expect(recordingActions(entries)).toEqual([{type:'pointer_path',path:{schema_version:1,frame_width:960,frame_height:540,points:[{t_ms:0,action:0,x:100,y:200},{t_ms:100,action:2,x:200,y:200},{t_ms:200,action:1,x:300,y:200}]}}]);
  expect(entries[0].outcome).toBe('android-confirmed');
});
it('preserves a stationary hold as a duration-bearing gesture instead of a tap',()=>{
  const f=fixture();f.offer(0);f.ack(1,0);f.offer(1,101,200,500,2);f.ack(2,1);
  expect(f.events[1]).toMatchObject({outcome:'confirmed',input:{command:{type:'pointer_path',path:{points:[{t_ms:0,action:0,x:100,y:200},{t_ms:500,action:1,x:101,y:200}]}}}});
});
it.each(['curve','out-and-back','reversed-line'])('preserves %s in a single path without flattening',variant=>{
  const f=fixture();f.offer(0);f.ack(1,0);
  f.offer(2,variant==='curve'?150:250,variant==='curve'?250:200,40,2);
  f.offer(1,variant==='out-and-back'?100:200,200,100,3);f.ack(3,1);
  expect(f.events[1]).toMatchObject({outcome:'confirmed',input:{command:{type:'pointer_path'}}});
});
it.each(['points','duration'])('bounds recorder %s without altering native transport',limit=>{
  const f=fixture();f.offer(0);f.ack(1,0);
  if(limit==='points')for(let i=0;i<4096;i++)f.offer(2,100,200,i+1,i+2);
  f.offer(1,100,200,limit==='duration'?60001:4097,5000);f.ack(5000,1);
  expect(f.events[1]).toMatchObject({outcome:'unsupported',input:null});
});
it('drains an offered gesture after Stop but never starts another recording while disabled',()=>{
  const f=fixture();f.offer(0);f.ack(1,0);f.offer(1,100,200,30,2);f.enable(false);f.ack(2,1);
  f.offer(0,100,200,40,3,2);
  expect(f.events).toHaveLength(2);expect(f.events[1]).toMatchObject({outcome:'confirmed'});
});
it.each(['retire','interrupted','cancel'])('reports %s once and ignores late terminal success',reason=>{
  const f=fixture();f.offer(0);f.ack(1,0);
  if(reason==='cancel'){f.offer(3,100,200,30,2);f.ack(2,3,3);}
  else if(reason==='retire')f.recorder.retired();else f.recorder.interrupted(1);
  f.ack(2,1);f.recorder.retired();
  expect(f.events).toHaveLength(2);
  expect(f.events[1]).toMatchObject({outcome:reason==='retire'?'unknown':reason==='cancel'?'cancelled':'interrupted',input:null});
});
it('does not confirm terminal execution without the native DOWN receipt',()=>{
  const f=fixture();f.offer(0);f.offer(1,100,200,30,2);f.ack(2,1);
  expect(f.events[1]).toMatchObject({outcome:'unknown',input:null});
});
it('rejects a changed capture instead of combining two surfaces',()=>{
  const f=fixture();f.offer(0);f.ack(1,0);
  f.recorder.offered({action:1,x:100,y:200,at:20,sequence:2,gesture:1,capture:{...capture,frameWidth:540}});
  expect(f.events[1]).toMatchObject({outcome:'unknown',input:null});
});
it('registers observation before synchronous native ACKs without changing the delivered wire trace',()=>{
  let now=0;const events:NativeGestureRecordingEvent[]=[],wire:Record<string,unknown>[]=[];
  const recorder=new NativeGestureRecording({deviceId:'owned',enabled:()=>true,onEvent:e=>events.push(e),now:()=>now});
  const identity={session_id:'viewer_session_1234',owner:'server_owner_1234',capture_epoch:capture.captureEpoch};
  const status=(sequence:number,status:number,stage='input')=>controller.receive({type:'continuous_input_status',...identity,
    sequence,status,stage,origin:'injector',device_uptime_ms:now});
  const socket={readyState:1,bufferedAmount:0,send:(raw:string)=>{const message=JSON.parse(raw);wire.push(message);
    if(message.type==='touch_event')status(message.sequence,message.action===3?3:1);}};
  const controller=new ContinuousPointer({socket,renderedCapture:()=>capture,now:()=>now,
    onInput:e=>recorder.offered(e),onReceipt:e=>recorder.receipt(e)});
  controller.open(capture);controller.receive({type:'touch_session',...identity,frame_width:960,frame_height:540});status(0,0,'startup');
  controller.down(1,{x:100,y:200});now=30;controller.up(1,{x:100,y:200});
  expect(events[1]).toMatchObject({outcome:'confirmed'});
  expect(wire.filter(e=>e.type==='touch_event')).toEqual([
    {type:'touch_event',sequence:1,gesture:1,action:0,x:100,y:200},
    {type:'touch_event',sequence:2,gesture:1,action:1,x:100,y:200},
  ]);
  expect(controller.state).toBe('ready');
});

it('retains a 30-second hold and late reversal as one path and one DAG node',()=>{
  const f=fixture(); f.offer(0);f.ack(1,0);f.offer(2,300,400,30000,2);f.offer(2,100,200,45000,3);f.offer(1,100,200,55000,4);f.ack(4,1);
  const event=f.events[1];if(event.phase!=='finished'||!event.input)throw Error('missing path');
  const actions=recordingActions(appendNativeRecording([],event.input,'owned',event.requestId,event.completedAt));
  expect(actions).toHaveLength(1);expect(actions[0]).toMatchObject({type:'pointer_path',path:{points:[{t_ms:0,action:0},{t_ms:30000,action:2},{t_ms:45000,action:2},{t_ms:55000,action:1}]}});
});
