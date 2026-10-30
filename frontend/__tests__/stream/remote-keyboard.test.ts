import { TextEncoder } from 'node:util';
import { ContinuousPointer } from '@/src/features/stream/continuousPointer';
import { DirectPointerTransport, type DirectControlEndpoint } from '@/src/features/stream/directPointerTransport';
import { androidPhysicalKey,validKeyboardCommand,validRemoteText } from '@/src/features/stream/remoteKeyboardProtocol';
Object.defineProperty(globalThis,'TextEncoder',{value:TextEncoder,configurable:true});
const epoch='00112233-4455-6677-8899-aabbccddeeff',session='a'.repeat(32),owner='b'.repeat(32);
function fixture(keyboard=true) {
  const server={readyState:1,bufferedAmount:0,send:jest.fn()};
  const direct: DirectControlEndpoint={session,sharedInput:true,nativeKeys:true,keyboard,readyState:1,bufferedAmount:0,
    capture:()=>({captureEpoch:epoch,width:960,height:540}),send:jest.fn(),listen:jest.fn(()=>()=>{})};
  const capture={captureEpoch:epoch,frameWidth:960,frameHeight:540},now={value:0};
  const pointer=new ContinuousPointer({socket:new DirectPointerTransport(server,direct),sharedInput:true,nativeKeys:true,keyboard,
    renderedCapture:()=>capture,now:()=>now.value});
  pointer.open(capture);pointer.receive({type:'touch_session',session_id:session,owner,capture_epoch:epoch,frame_width:960,frame_height:540});
  pointer.receive({type:'shared_input_status',session_id:session,owner,capture_epoch:epoch,sequence:0,gesture:0,action:4,outcome:'ready',device_uptime_ms:1000});
  const reply=(type:string,extra:object)=>pointer.receive({type,session_id:session,owner,capture_epoch:epoch,...extra});
  const state=()=>reply('keyboard_state',{enabled:true,editor_generation:7,editor_active:true,reason:'ready'});
  const result=(sequence:number,outcome='accepted',extra={})=>reply('keyboard_result',{sequence,outcome,device_uptime_ms:1000,...extra});
  return {pointer,server,direct,now,state,result,reply};
}
test('Unicode requires the explicit keyboard mode and exact native receipt on the same peer',async()=>{
  const f=fixture();const command={operation:'commit' as const,editor_generation:7,text:'Привет 🙂 你好'};
  await expect(f.pointer.keyboard(command)).resolves.toEqual({outcome:'not_sent'});
  expect(f.pointer.keyboardMode(true)).toBe(true);f.state();const result=f.pointer.keyboard(command);
  expect(f.result(1,'accepted',{owner:'foreign_owner'})).toBe(false);
  expect(f.result(1)).toBe(true);await expect(result).resolves.toEqual({outcome:'accepted',receiptRoundTripMs:0});
  expect(f.server.send).not.toHaveBeenCalled();
  expect(JSON.parse((f.direct.send as jest.Mock).mock.calls.at(-1)[0])).toEqual({type:'keyboard_event',sequence:1,...command});
});
test.each(['no_editor','stale_editor','unknown','unavailable','interrupted'])('%s stays explicit and does not falsely claim text acceptance',async outcome=>{
  const f=fixture();f.state();const sent=f.pointer.keyboard({operation:'compose',editor_generation:7,text:'仮'});
  f.result(1,outcome);await expect(sent).resolves.toEqual({outcome});expect(f.pointer.state).toBe('ready');
});
test('a later pointer receipt does not resolve an earlier text command and reconnection never replays it',async()=>{
  const f=fixture();f.state();const sent=f.pointer.keyboard({operation:'commit',editor_generation:7,text:'secret fixture'});
  f.pointer.down(1,{x:10,y:20});
  f.reply('shared_input_status',{sequence:2,gesture:1,action:0,outcome:'applied',device_uptime_ms:1000});
  expect(f.pointer.pendingReceiptCount).toBe(1);(f.direct as {readyState:number}).readyState=0;
  f.pointer.retire('server_runtime_retry');await expect(sent).resolves.toEqual({outcome:'unknown'});
  expect(f.pointer.canRejoinRetiredSharedPeer).toBe(true);expect(f.pointer.canRejoinIdleSharedPeer).toBe(false);
  expect(f.pointer.down(2,{x:10,y:20})).toBe(false);expect(f.server.send).not.toHaveBeenCalled();
});
test('disabling mode waits for exact RESET receipt before IME restoration',async()=>{
  const f=fixture();f.state();const promise=f.pointer.disableKeyboard();
  const messages=()=> (f.direct.send as jest.Mock).mock.calls.map(c=>JSON.parse(c[0]));
  expect(messages().at(-1)).toMatchObject({type:'keyboard_event',operation:'reset'});
  expect(messages().some(m=>m.type==='keyboard_mode'&&!m.enabled)).toBe(false);
  f.result(1);await promise;expect(messages().at(-1)).toEqual({type:'keyboard_mode',enabled:false});
});

test('an acknowledged held keyboard key is not an idle timeout replacement proof', async () => {
  const f = fixture(); f.state();
  const held = f.pointer.keyboard({ operation:'key_down', keycode:29, editor_generation:7, meta:0 });
  f.result(1); await expect(held).resolves.toMatchObject({ outcome:'accepted' });
  for (let i=0; i<7; i++) { f.now.value += 250; f.pointer.tick(); }
  expect(f.pointer.state).toBe('fenced');
  (f.direct as {readyState:number}).readyState=3;
  expect(f.pointer.canRejoinRetiredSharedPeer).toBe(false);
});
test('old capabilities and malformed private fields cannot use text transport',async()=>{
  const f=fixture(false);expect(f.pointer.keyboardMode(true)).toBe(false);
  await expect(f.pointer.keyboard({operation:'commit',editor_generation:7,text:'text'})).resolves.toEqual({outcome:'not_sent'});
  expect(validKeyboardCommand({operation:'commit',editor_generation:1,text:'okay',shell:'ignored?'})).toBe(false);
  expect(validRemoteText('\ud800')).toBe(false);expect(validRemoteText('🙂'.repeat(513))).toBe(false);
  expect(validRemoteText('Привет\tworld\n🙂')).toBe(true);
  expect(androidPhysicalKey('KeyA')).toBe(29);expect(androidPhysicalKey('ControlLeft')).toBe(113);
  expect(androidPhysicalKey('Power')).toBe(null);
});
