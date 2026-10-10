import { ContinuousPointer } from '@/src/features/stream/continuousPointer';
import { DirectPointerTransport, type DirectControlEndpoint } from '@/src/features/stream/directPointerTransport';
import { TextEncoder } from 'node:util';

Object.defineProperty(globalThis, 'TextEncoder', { value: TextEncoder, configurable: true });

const epoch = '00112233-4455-6677-8899-aabbccddeeff';
const capture = { captureEpoch: epoch, frameWidth: 960, frameHeight: 540 };
function fixture() {
  const server = { readyState: 1, bufferedAmount: 0, send: jest.fn() };
  const direct: DirectControlEndpoint = { session: 'a'.repeat(32), readyState: 1, bufferedAmount: 0,
    capture: () => ({ captureEpoch: epoch, width: 960, height: 540 }), send: jest.fn(), listen: jest.fn(() => jest.fn()) };
  const transport = new DirectPointerTransport(server, direct);
  return { server, direct, transport };
}
const open = { type: 'touch_open', capture_epoch: epoch, frame_width: 960, frame_height: 540 };
const down = { type: 'touch_event', sequence: 1, gesture: 1, action: 0, x: 30, y: 40 };
test('server grants the exact peer, touch and heartbeat use only its data channel', () => {
  const { server, direct, transport } = fixture();
  transport.send(JSON.stringify(open));
  expect(JSON.parse(server.send.mock.calls[0][0])).toEqual({ ...open, type: 'touch_direct_open', direct_session: direct.session });
  server.send.mockClear();
  transport.send(JSON.stringify(down));
  transport.send(JSON.stringify({ ...down, sequence: 2, action: 4 }));
  expect(direct.send).toHaveBeenCalledTimes(2); expect(server.send).not.toHaveBeenCalled();
});
test('an ambiguous direct write never falls back or retries the click', () => {
  const { server, direct, transport } = fixture();
  (direct.send as jest.Mock).mockImplementation(() => { throw Error('fixture'); });
  expect(() => transport.send(JSON.stringify(down))).toThrow('fixture');
  expect(direct.send).toHaveBeenCalledTimes(1); expect(server.send).not.toHaveBeenCalled();
});
test.each([{ ...open, capture_epoch: 'different' }, { ...open, frame_width: 540 },
  { ...down, owner: 'injected' }, { type: 'EXECUTE_DAG', code: 'fixture' }, { ...down, sequence: '1' }])(
  'invalid geometry or extra authority never reaches either route: %j', value => {
    const { server, direct, transport } = fixture();
    expect(() => transport.send(JSON.stringify(value))).toThrow();
    expect(direct.send).not.toHaveBeenCalled(); expect(server.send).not.toHaveBeenCalled();
  });
test('native revocation survives a lost data channel, without sending a touch through the server', () => {
  const { server, direct, transport } = fixture();
  const pointer = new ContinuousPointer({ socket: transport, renderedCapture: () => capture, now: () => 0 });
  pointer.open(capture); server.send.mockClear();
  Object.defineProperty(direct, 'readyState', { value: 0 });
  pointer.retire('server_runtime_retry');
  expect(server.send).toHaveBeenCalledTimes(1);
  expect(JSON.parse(server.send.mock.calls[0][0])).toEqual({ type: 'touch_close' });
  expect(direct.send).not.toHaveBeenCalled();
  expect(pointer.state).toBe('fenced');
});
