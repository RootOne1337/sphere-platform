import { ContinuousPointer } from '@/src/features/stream/continuousPointer';
import { DirectPointerTransport, type DirectControlEndpoint } from '@/src/features/stream/directPointerTransport';
import { TextEncoder } from 'node:util';

Object.defineProperty(globalThis, 'TextEncoder', { value: TextEncoder, configurable: true });
const epoch = '00112233-4455-6677-8899-aabbccddeeff';
const capture = { captureEpoch: epoch, frameWidth: 960, frameHeight: 540 };
const session = 'a'.repeat(32), owner = 'b'.repeat(32);
function fixture(sharedInput = true, nativeKeys = false) {
  const server = { readyState: 1, bufferedAmount: 0, send: jest.fn() };
  const direct: DirectControlEndpoint = { session, sharedInput, nativeKeys, readyState: 1, bufferedAmount: 0,
    capture: () => ({ captureEpoch: epoch, width: 960, height: 540 }), send: jest.fn(), listen: jest.fn(() => jest.fn()) };
  const transport = new DirectPointerTransport(server, direct);
  const now = { value: 0 };
  const onState = jest.fn(), onReceipt = jest.fn(), onFence = jest.fn();
  const pointer = new ContinuousPointer({ socket: transport, sharedInput, nativeKeys, renderedCapture: () => capture,
    now: () => now.value, onState, onReceipt, onFence });
  pointer.open(capture);
  pointer.receive({ type: 'touch_session', session_id: session, owner, capture_epoch: epoch, frame_width: 960, frame_height: 540 });
  const receipt = (outcome: string, sequence = 0, action = 4, gesture = 0, overrides = {}) => pointer.receive({
    type: 'shared_input_status', session_id: session, owner, capture_epoch: epoch,
    outcome, sequence, action, gesture, device_uptime_ms: 1000, ...overrides });
  return { server, direct, transport, pointer, receipt, onState, onReceipt, onFence, now };
}

test('shared OPEN, touch and close use only the same direct media peer', () => {
  const f = fixture();
  expect(f.server.send).not.toHaveBeenCalled();
  expect(JSON.parse((f.direct.send as jest.Mock).mock.calls[0][0]).type).toBe('touch_open');
  expect(f.receipt('ready')).toBe(true);
  expect(f.pointer.down(1, { x: 10, y: 20 })).toBe(true);
  f.receipt('applied', 1, 0, 1);
  f.pointer.close();
  expect(f.server.send).not.toHaveBeenCalled();
  expect((f.direct.send as jest.Mock).mock.calls.map(c => JSON.parse(c[0]).type)).toEqual(['touch_open', 'touch_event', 'touch_close']);
});

test('native Home uses the same participant and only its exact key receipt confirms completion', async () => {
  const f = fixture(true, true); f.receipt('ready');
  const result = f.pointer.keyTap(3);
  expect(JSON.parse((f.direct.send as jest.Mock).mock.calls.at(-1)[0])).toEqual({ type: 'key_event', sequence: 1, keycode: 3 });
  expect(f.receipt('applied', 1, 5, 0, { owner: 'foreign_owner_1234' })).toBe(false);
  expect(f.receipt('alive', 1, 5, 0)).toBe(false);
  expect(f.receipt('applied', 1, 5, 0)).toBe(true);
  expect(await result).toEqual({ outcome: 'applied', receiptRoundTripMs: 0 });
  expect(f.pointer.state).toBe('ready'); expect(f.onFence).not.toHaveBeenCalled();
  expect(f.server.send).not.toHaveBeenCalled();
});

test('later heartbeat cannot erase a missing native key acknowledgement', async () => {
  const f = fixture(true, true); f.receipt('ready');
  const result = f.pointer.keyTap(4);
  f.now.value = 250; f.pointer.tick();
  expect(f.receipt('alive', 2, 4, 0)).toBe(true);
  expect(f.pointer.pendingReceiptCount).toBe(1);
  expect(f.receipt('applied', 1, 5, 0)).toBe(true);
  expect(await result).toEqual({ outcome: 'applied', receiptRoundTripMs: 250 });
  expect(f.server.send).not.toHaveBeenCalled();
});

test('a failed direct key write resolves unknown without an HTTP or WebSocket replay', async () => {
  const f = fixture(true, true); f.receipt('ready');
  (f.direct.send as jest.Mock).mockImplementation(() => { throw Error('fixture'); });
  expect(await f.pointer.keyTap(187)).toEqual({ outcome: 'unknown' });
  expect(f.server.send).not.toHaveBeenCalled();
  expect(f.pointer.state).toBe('fenced');
});

test('older agents, forbidden keys and another pending key cannot receive a native key event', async () => {
  const legacy = fixture(); legacy.receipt('ready');
  expect(await legacy.pointer.keyTap(3)).toEqual({ outcome: 'not_sent' });
  const f = fixture(true, true); f.receipt('ready');
  expect(await f.pointer.keyTap(26)).toEqual({ outcome: 'not_sent' });
  const first = f.pointer.keyTap(82);
  expect(await f.pointer.keyTap(3)).toEqual({ outcome: 'not_sent' });
  f.pointer.destroy(); expect(await first).toEqual({ outcome: 'unknown' });
  expect(f.server.send).not.toHaveBeenCalled();
});

test('takeover clears only the interrupted gesture without fencing or reconnecting the controller', () => {
  const f = fixture(); f.receipt('ready'); f.pointer.down(1, { x: 10, y: 20 });
  expect(f.receipt('applied', 1, 0, 1)).toBe(true);
  expect(f.receipt('interrupted', 1, 4, 1)).toBe(true);
  expect(f.pointer.state).toBe('ready'); expect(f.pointer.pointerHeld).toBe(false);
  expect(f.onFence).not.toHaveBeenCalled();
  expect(f.pointer.down(2, { x: 20, y: 30 })).toBe(true);
  expect(f.receipt('interrupted', 1, 4, 1)).toBe(false);
  expect(f.pointer.pointerHeld).toBe(true);
  expect(f.receipt('applied', 2, 0, 2)).toBe(true);
  expect(f.onReceipt).toHaveBeenCalledTimes(2);
});

test('interrupted queued UP is removed without claiming an applied terminal receipt', () => {
  const f = fixture(); f.receipt('ready'); f.pointer.down(1, { x: 10, y: 20 });
  f.pointer.up(1, { x: 10, y: 20 });
  expect(f.receipt('interrupted', 1, 4, 1)).toBe(true);
  expect(f.pointer.pendingReceiptCount).toBe(0);
  expect(f.onReceipt).not.toHaveBeenCalled();
  expect(f.pointer.down(2, { x: 20, y: 30 })).toBe(true);
});

test('foreign participant, malformed outcome and mismatched gesture cannot acknowledge input', () => {
  const f = fixture(); f.receipt('ready'); f.pointer.down(1, { x: 10, y: 20 });
  expect(f.receipt('applied', 1, 0, 1, { owner: 'c'.repeat(32) })).toBe(false);
  expect(f.receipt('applied', 1, 0, 2)).toBe(false);
  expect(f.receipt('alive', 1, 0, 1)).toBe(false);
  expect(f.receipt('invented', 1, 0, 1)).toBe(false);
  expect(f.onReceipt).not.toHaveBeenCalled(); expect(f.pointer.pointerHeld).toBe(true);
});

test('v1 controller never accepts v2 readiness or participant release', () => {
  const f = fixture(false);
  expect(f.receipt('ready')).toBe(false); expect(f.receipt('closed')).toBe(false);
  expect(f.pointer.state).toBe('opening');
});

test('unknown direct write is never retried through server or interpreted as applied', () => {
  const f = fixture(); f.receipt('ready');
  (f.direct.send as jest.Mock).mockImplementation(() => { throw Error('unknown'); });
  expect(f.pointer.down(1, { x: 20, y: 30 })).toBe(false);
  expect(f.pointer.state).toBe('fenced'); expect(f.onReceipt).not.toHaveBeenCalled();
  expect(f.server.send).not.toHaveBeenCalled();
});
