import { connectTeaching } from '../../src/features/stream/teachingConnection';
import { api } from '../../lib/api';
import { startDirectVideoSession } from '../../src/features/stream/directProbe';

jest.mock('../../lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('../../src/features/stream/DirectProbeAccess', () => ({ parseProbeAdmission: () => ['public-stun'] }));
jest.mock('../../src/features/stream/directProbe', () => ({ startDirectVideoSession: jest.fn(() => jest.fn()) }));

class Socket {
  static current: Socket;
  static OPEN = 1;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror = null; onclose = null;
  send = jest.fn(); close = jest.fn();
  readyState = 1;
  bufferedAmount = 0;
  constructor() { Socket.current = this; }
  receive(value: unknown) { this.onmessage?.({ data: JSON.stringify(value) }); }
}

describe('teaching capture-only liveness', () => {
  const originals = Object.getOwnPropertyDescriptors(globalThis);
  const storage = Object.getOwnPropertyDescriptor(navigator, 'storage');
  beforeEach(() => {
    jest.useFakeTimers(); jest.clearAllMocks();
    Object.defineProperty(globalThis, 'isSecureContext', { configurable: true, value: true });
    Object.defineProperty(globalThis, 'RTCRtpScriptTransform', { configurable: true, value: class {} });
    Object.defineProperty(globalThis, 'WebSocket', { configurable: true, value: Socket });
    Object.defineProperty(globalThis, 'Worker', { configurable: true, value: class { onmessage = null; onerror = null; postMessage = jest.fn(); } });
    Object.defineProperty(navigator, 'storage', { configurable: true, value: { getDirectory: jest.fn() } });
    (api.get as jest.Mock).mockResolvedValue({ data: { live_video_enabled: true, direct_input_enabled: true, shared_input_enabled: true } });
  });
  afterEach(() => {
    jest.useRealTimers();
    for (const name of ['isSecureContext', 'RTCRtpScriptTransform', 'WebSocket', 'Worker']) {
      if (originals[name]) Object.defineProperty(globalThis, name, originals[name]);
      else Reflect.deleteProperty(globalThis, name);
    }
    if (storage) Object.defineProperty(navigator, 'storage', storage);
    else Reflect.deleteProperty(navigator, 'storage');
  });
  async function setup() {
    const failed = jest.fn();
    const video = { requestVideoFrameCallback: jest.fn(), cancelVideoFrameCallback: jest.fn(), pause: jest.fn(), srcObject: null } as unknown as HTMLVideoElement;
    const connection = await connectTeaching('device', 'test-only-token', video, new AbortController().signal, jest.fn(), failed, jest.fn());
    Socket.current.onopen?.();
    return { connection, failed, socket: Socket.current };
  }
  it('does not send a rejected application pong on server liveness notices', async () => {
    const { connection, failed, socket } = await setup();
    socket.receive({ type: 'ping' }); socket.receive({ type: 'ping' });
    expect(socket.send.mock.calls.map(([text]) => JSON.parse(text))).toEqual([{ token: 'test-only-token', delivery: 'capture_only' }]);
    expect(failed).not.toHaveBeenCalled(); connection.close();
  });
  it('still refuses unknown server messages instead of weakening the protocol', async () => {
    const { connection, failed, socket } = await setup();
    socket.receive({ type: 'unexpected' });
    expect(failed).toHaveBeenCalledWith('invalid_capture_message'); connection.close();
  });
  it('keeps the capture binding and creates only one peer across heartbeat notices', async () => {
    const { connection, failed, socket } = await setup();
    socket.receive({ type: 'stream_session', schema_version: 1, delivery: 'capture_only', session_id: '1234567890abcdef' });
    socket.receive({ type: 'ping' });
    socket.receive({ type: 'capture_ready', schema_version: 1, session_id: '1234567890abcdef', width: 960, height: 540 });
    socket.receive({ type: 'ping' });
    expect(startDirectVideoSession).toHaveBeenCalledTimes(1);
    expect(failed).not.toHaveBeenCalled(); connection.close();
  });
  it('reports teaching receiver and native ACK scalars through the admitted history socket',async()=>{
    const {connection,socket}=await setup();
    socket.receive({type:'stream_session',schema_version:1,delivery:'capture_only',session_id:'1234567890abcdef',
      history_enabled:true,report_interval_seconds:10});
    socket.receive({type:'capture_ready',schema_version:1,session_id:'1234567890abcdef',width:960,height:540});
    const call=(startDirectVideoSession as jest.Mock).mock.calls[0];
    call[2]({state:'connected',samples:[],path:'host',protocol:'udp',session:'a'.repeat(32),
      videoBinding:{captureEpoch:'private-epoch',width:960,height:540},
      videoStats:{fps:10,decoded:25,networkRttMs:2,jitterBufferMs:4,decodeMs:3}});
    connection.observeControl?.('ready',undefined,7);
    jest.advanceTimersByTime(10000);
    const samples=socket.send.mock.calls.map(([raw])=>JSON.parse(raw)).filter(v=>v.type==='viewer_telemetry');
    expect(samples.at(-1)?.sample).toMatchObject({transport:'direct_webrtc',control_transport:'direct_webrtc',
      direct_path:'host',direct_fps:10,control_state:'ready',control_rtt_ms:7,received_bytes:0});
    expect(JSON.stringify(samples)).not.toMatch(/test-only-token|private-epoch/);
    connection.observeControl?.('fenced','contact_ack_timeout');
    connection.observeControl?.('closing');
    const failedSample=socket.send.mock.calls.map(([raw])=>JSON.parse(raw)).filter(v=>v.type==='viewer_telemetry').at(-1)?.sample;
    expect(failedSample).toMatchObject({control_state:'fenced',control_failure:'timeout',control_failure_detail:'native_receipt_timeout'});
    connection.close();
    const closedSample=socket.send.mock.calls.map(([raw])=>JSON.parse(raw)).filter(v=>v.type==='viewer_telemetry').at(-1)?.sample;
    expect(closedSample.control_failure_detail).toBe('native_receipt_timeout');
  });
  it('a terminal failure stays fenced even if later media or peer messages arrive',async()=>{
    const {connection,socket,failed}=await setup();
    socket.receive({type:'stream_session',schema_version:1,delivery:'capture_only',session_id:'1234567890abcdef'});
    socket.receive({type:'capture_ready',schema_version:1,session_id:'1234567890abcdef',width:960,height:540});
    const call=(startDirectVideoSession as jest.Mock).mock.calls[0];
    call[2]({state:'connected',samples:[],path:'host',videoBinding:{captureEpoch:'epoch',width:960,height:540}});
    socket.receive({type:'unexpected'});
    call[2]({state:'connected',samples:[],path:'host',videoBinding:{captureEpoch:'epoch',width:960,height:540}});
    socket.receive({type:'unexpected'});
    expect(failed).toHaveBeenCalledTimes(1);expect(connection.fresh()).toBe(false);
    expect(startDirectVideoSession).toHaveBeenCalledTimes(1);connection.close();
  });
  it('renews capture presence only for the bound peer with fresh presented video', async () => {
    const failed = jest.fn(); let present: ((at: number, frame: object) => void) | undefined;
    const video = { requestVideoFrameCallback: jest.fn(cb => { present = cb; return 1; }), cancelVideoFrameCallback: jest.fn(), pause: jest.fn(), play: jest.fn(() => Promise.resolve()), srcObject: null } as unknown as HTMLVideoElement;
    const mediaStream = Object.getOwnPropertyDescriptor(globalThis, 'MediaStream');
    Object.defineProperty(globalThis, 'MediaStream', { configurable: true, value: class {} });
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    try {
      const connection = await connectTeaching('device', 'test-only-token', video, new AbortController().signal, jest.fn(), failed, jest.fn());
      const socket = Socket.current;
      socket.receive({ type: 'stream_session', schema_version: 1, delivery: 'capture_only', session_id: '1234567890abcdef' });
      socket.receive({ type: 'capture_ready', schema_version: 1, session_id: '1234567890abcdef', width: 960, height: 540 });
      const call = (startDirectVideoSession as jest.Mock).mock.calls[0];
      call[2]({ state: 'connected', session: 'a'.repeat(32), videoBinding: { captureEpoch: 'epoch', width: 960, height: 540 } });
      call[3].onTrack({ kind: 'video' });
      jest.advanceTimersByTime(1); present?.(1, { width: 960, height: 540 });
      for (let n = 0; n < 45; n++) {
        jest.advanceTimersByTime(500); present?.(n, { width: 960, height: 540 });
        const requests = socket.send.mock.calls.filter(([text]) => JSON.parse(text).type === 'video_delivery');
        if (requests.length && n % 6 === 0) socket.receive({ type: 'video_delivery_ack', mode: 'direct' });
      }
      expect(socket.send.mock.calls.some(([text]) => JSON.parse(text).peer_session === 'a'.repeat(32))).toBe(true);
      expect(failed).not.toHaveBeenCalled(); connection.close();
    } finally {
      Reflect.deleteProperty(document, 'hidden');
      if (mediaStream) Object.defineProperty(globalThis, 'MediaStream', mediaStream); else Reflect.deleteProperty(globalThis, 'MediaStream');
    }
  });
  it('external capture uses actual encoded heartbeats while hidden and still fails on a stalled stream', async () => {
    const failed=jest.fn();let present:((at:number,frame:object)=>void)|undefined;
    const video={requestVideoFrameCallback:jest.fn(cb=>{present=cb;return 1;}),cancelVideoFrameCallback:jest.fn(),pause:jest.fn(),play:jest.fn(()=>Promise.resolve()),srcObject:null} as unknown as HTMLVideoElement;
    const mediaStream=Object.getOwnPropertyDescriptor(globalThis,'MediaStream');
    Object.defineProperty(globalThis,'MediaStream',{configurable:true,value:class {}});
    Object.defineProperty(document,'hidden',{configurable:true,value:false});
    try {
      const connection=await connectTeaching('device','test-only-token',video,new AbortController().signal,jest.fn(),failed,jest.fn());
      const socket=Socket.current;
      socket.receive({type:'stream_session',schema_version:1,delivery:'capture_only',session_id:'1234567890abcdef'});
      socket.receive({type:'capture_ready',schema_version:1,session_id:'1234567890abcdef',width:960,height:540});
      const call=(startDirectVideoSession as jest.Mock).mock.calls[0];
      call[2]({state:'connected',session:'a'.repeat(32),videoBinding:{captureEpoch:'epoch',width:960,height:540}});
      call[3].onTrack({kind:'video'});jest.advanceTimersByTime(1);present?.(1,{width:960,height:540});
      connection.setExternalCapture?.(true);
      expect(connection.worker.postMessage).toHaveBeenCalledWith({type:'external_capture',enabled:true});
      Object.defineProperty(document,'hidden',{configurable:true,value:true});
      jest.advanceTimersByTime(100);
      connection.worker.onmessage?.({data:{type:'encoded_heartbeat'}} as MessageEvent);
      jest.advanceTimersByTime(100);expect(connection.fresh()).toBe(true);expect(failed).not.toHaveBeenCalled();
      let renewals=0;
      for(let n=0;n<600;n++){
        connection.worker.onmessage?.({data:{type:'encoded_heartbeat'}} as MessageEvent);
        jest.advanceTimersByTime(100);
        const sent=socket.send.mock.calls.filter(([raw])=>JSON.parse(raw).type==='video_delivery').length;
        if(sent>renewals){renewals=sent;socket.receive({type:'video_delivery_ack',mode:'direct'});}
      }
      expect(renewals).toBeGreaterThan(15);expect(failed).not.toHaveBeenCalled();
      jest.advanceTimersByTime(1100);expect(failed).toHaveBeenCalledWith('video_stalled');expect(connection.fresh()).toBe(false);
      connection.close();
    } finally {
      Reflect.deleteProperty(document,'hidden');
      if(mediaStream)Object.defineProperty(globalThis,'MediaStream',mediaStream);else Reflect.deleteProperty(globalThis,'MediaStream');
    }
  });
});
