import { connectTeaching } from '../../src/features/stream/teachingConnection';
import { api } from '../../lib/api';
import { startDirectVideoSession } from '../../src/features/stream/directProbe';

jest.mock('../../lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('../../src/features/stream/DirectProbeAccess', () => ({ parseProbeAdmission: () => ['public-stun'] }));
jest.mock('../../src/features/stream/directProbe', () => ({ startDirectVideoSession: jest.fn(() => jest.fn()) }));

class Socket {
  static current: Socket;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror = null; onclose = null;
  send = jest.fn(); close = jest.fn();
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
    Object.defineProperty(globalThis, 'Worker', { configurable: true, value: class { onmessage = null; onerror = null; } });
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
});
