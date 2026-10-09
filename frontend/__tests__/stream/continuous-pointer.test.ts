import { CONTINUOUS_POINTER_LIMITS as LIMITS, ContinuousPointer, attachContinuousPointer } from '@/src/features/stream/continuousPointer';
import type { CaptureFrameBinding } from '@/lib/h264-decoder';

const CAPTURE: CaptureFrameBinding = {
  captureEpoch: '71532996-5c56-4a17-b931-67f66d54abde', frameWidth: 960, frameHeight: 540,
};
const IDENTITY = { session_id: 'viewer_session_1234', owner: 'server_owner_1234', capture_epoch: CAPTURE.captureEpoch };
const POINT = { x: 100, y: 200 };

function fixture(start = true, clock?: () => number) {
  let now = 0;
  let capture: CaptureFrameBinding | null = { ...CAPTURE };
  const sent: Array<Record<string, unknown>> = [];
  const socket = { readyState: 1, bufferedAmount: 0, send: jest.fn((raw: string) => { sent.push(JSON.parse(raw)); }) };
  const onState = jest.fn(), onReceipt = jest.fn(), onFence = jest.fn();
  const controller = new ContinuousPointer({ socket, renderedCapture: () => capture, now: clock ?? (() => now), onState, onReceipt, onFence });
  const bind = () => controller.receive({ type: 'touch_session', ...IDENTITY, frame_width: 960, frame_height: 540 });
  const status = (sequence: number, code = 1, stage = 'input', overrides: Record<string, unknown> = {}) =>
    controller.receive({ type: 'continuous_input_status', ...IDENTITY, sequence, status: code,
      stage, origin: 'injector', device_uptime_ms: 50_000 + now, ...overrides });
  const ready = () => { controller.open(CAPTURE); bind(); status(0, 0, 'startup'); };
  const events = () => sent.filter(x => x.type === 'touch_event');
  const ackLatest = () => {
    const latest = events().at(-1)!;
    return status(latest.sequence as number, latest.action === 4 ? 2 : latest.action === 3 ? 3 : 1);
  };
  if (start) ready();
  return { controller, socket, sent, onState, onReceipt, onFence, bind, status, ready, events, ackLatest,
    capture: (value: CaptureFrameBinding | null) => { capture = value; },
    advance: (ms: number, tick = true) => { now += ms; if (tick) controller.tick(); },
  };
}

it('classifies only a fresh STARTUP admission busy as retryable negotiation, without touch readiness', () => {
  const f = fixture(false);
  f.controller.open(CAPTURE); f.bind();
  f.status(0, 5, 'startup', { origin: 'admission' });
  expect(f.controller.state).toBe('fenced');
  expect(f.onFence).toHaveBeenCalledWith(expect.objectContaining({ reason: 'native_startup_busy', pointerHeld: false }));
  expect(f.controller.down(1, POINT)).toBe(false);
  expect(f.events()).toEqual([]);
  expect(f.sent.filter(x => x.type === 'touch_close')).toHaveLength(1);
});

it.each([
  ['injector failure', 0, 5, 'startup', 'injector'],
  ['admission unknown', 0, 6, 'startup', 'admission'],
  ['input rejection', 1, 5, 'input', 'admission'],
  ['nonzero startup', 1, 5, 'startup', 'admission'],
])('does not downgrade %s to a harmless startup busy', (_label, sequence, code, stage, origin) => {
  const f = fixture(false);
  f.controller.open(CAPTURE); f.bind();
  f.status(sequence as number, code as number, stage as string, { origin });
  expect(f.onFence).toHaveBeenCalledWith(expect.objectContaining({ reason: 'native_input_rejected_or_unknown' }));
  expect(f.controller.recoverableIdleReceiptLoss).toBe(false);
  expect(f.controller.unknownPointerReceiptLoss).toBe(false);
  expect(f.events()).toEqual([]);
});

it('preserves an immutable idle failure snapshot before clearing pending receipts', () => {
  const f = fixture();
  f.advance(250); f.advance(250); f.advance(250);
  expect(f.controller.state).toBe('fenced');
  expect(f.controller.pendingReceiptCount).toBe(0);
  expect(f.onFence).toHaveBeenCalledTimes(1);
  const snapshot = f.onFence.mock.calls[0][0];
  expect(snapshot).toMatchObject({ reason: 'native_receipt_timeout', phase: 'ready', idleHeartbeatOnly: true,
    offeredSequence: 2, acknowledgedSequence: 0, pendingCount: 2, oldestSequence: 1, oldestAction: 4,
    oldestAgeMs: 500, oldestDeadlineAgeMs: 500, tickGapMs: 250, lastSendAgeMs: 250,
    terminalSequence: null, terminalAgeMs: null, pointerHeld: false,
    lastReceiptAgeMs: null, lastReceiptRoundTripMs: null, socketState: 1, bufferedBytes: 0 });
  expect(Object.isFrozen(snapshot)).toBe(true);
  expect(JSON.stringify(snapshot)).not.toMatch(/server_owner|viewer_session|71532996|"x"|"y"|captureEpoch/);
  f.status(2, 2); f.controller.retire(); f.controller.destroy();
  expect(f.onFence).toHaveBeenCalledTimes(1);
  expect(f.sent.filter(x => x.type === 'touch_close')).toHaveLength(1);
});

it('reports real browser timer starvation separately from native receipt silence', () => {
  const f = fixture(); f.advance(501);
  expect(f.onFence.mock.calls[0][0]).toMatchObject({ reason: 'scheduler_gap', tickGapMs: 501,
    pendingCount: 0, oldestAgeMs: null, idleHeartbeatOnly: false });
  expect(f.events()).toEqual([]);
});

it('captures actual RTT and age of the last ACK even when observers are throttled or throwing', () => {
  const f = fixture(); f.controller.down(1, POINT);
  f.advance(37, false); f.onReceipt.mockImplementation(() => { throw new Error('observer'); });
  f.ackLatest(); f.advance(200); f.advance(250); f.advance(250); f.advance(250);
  expect(f.onFence.mock.calls[0][0]).toMatchObject({ lastReceiptRoundTripMs: 37,
    lastReceiptAgeMs: 950, acknowledgedSequence: 1, pointerHeld: true, idleHeartbeatOnly: false });
});

it('keeps cold-start send age distinct from the deadline age started at native READY', () => {
  const f = fixture(false); f.controller.open(CAPTURE); f.bind();
  for (let i = 0; i < 5; i++) f.advance(250);
  f.status(0, 0, 'startup'); f.advance(250); f.advance(250);
  expect(f.onFence.mock.calls[0][0]).toMatchObject({ oldestAgeMs: 1500, oldestDeadlineAgeMs: 500,
    oldestSequence: 1, phase: 'ready' });
});

it('retains the exact unacknowledged terminal even after a newer heartbeat ACK', () => {
  const f = fixture(); f.controller.down(1, POINT); f.ackLatest();
  f.advance(10, false); f.controller.up(1, POINT);
  f.advance(250); f.ackLatest(); f.advance(250);
  expect(f.onFence.mock.calls[0][0]).toMatchObject({ terminalSequence: 2, terminalAgeMs: 500,
    pendingCount: 0, acknowledgedSequence: 3, pointerHeld: false, idleHeartbeatOnly: false });
});

it('a throwing fence observer cannot block the single native close or retain a MOVE', () => {
  const f = fixture(); f.onFence.mockImplementation(() => { throw new Error('observer'); });
  f.controller.down(1, POINT); f.controller.moveTo(1, { x: 50, y: 100 });
  f.advance(250); f.advance(250);
  expect(f.controller.state).toBe('fenced'); expect(f.controller.hasPendingMove).toBe(false);
  expect(f.controller.pendingReceiptCount).toBe(0);
  expect(f.sent.filter(x => x.type === 'touch_close')).toHaveLength(1);
});

it('an invalid monotonic clock leaves ages unknown rather than inventing zero', () => {
  let now = 50; const f = fixture(true, () => now);
  now = NaN; f.controller.tick();
  expect(f.onFence.mock.calls[0][0]).toMatchObject({ reason: 'scheduler_gap', tickGapMs: null,
    lastSendAgeMs: null, oldestAgeMs: null });
});

it('sends back-and-forth MOVE before UP, with native coordinates and one gesture identity', () => {
  const f = fixture();
  expect(f.controller.down(1, POINT)).toBe(true); f.ackLatest();
  f.controller.moveTo(1, { x: 500, y: 200 }); f.advance(16); f.ackLatest();
  f.controller.moveTo(1, { x: 200, y: 250 }); f.advance(16); f.ackLatest();
  expect(f.events().map(x => x.action)).toEqual([0, 2, 2]);
  expect(f.events().map(x => x.x)).toEqual([100, 500, 200]);
  expect(f.controller.pointerHeld).toBe(true);
  expect(f.controller.up(1, { x: 210, y: 260 })).toBe(true);
  expect(f.events().at(-1)).toEqual({ type: 'touch_event', sequence: 4, gesture: 1, action: 1, x: 210, y: 260 });
  expect(new Set(f.events().map(x => x.gesture))).toEqual(new Set([1]));
  expect(f.events().every(x => !Object.hasOwn(x, 'owner') && !Object.hasOwn(x, 'session_id'))).toBe(true);
});

it('keeps cold startup alive without applying the ready receipt deadline to opening heartbeats', () => {
  const f = fixture(false);
  f.controller.open(CAPTURE); f.bind();
  for (let n = 0; n < 6; n++) f.advance(250);
  expect(f.controller.state).toBe('opening');
  expect(f.events()).toHaveLength(6);
  expect(f.events().every(event => event.action === 4)).toBe(true);
  expect(f.controller.down(1, POINT)).toBe(false);
  expect(f.status(0, 0, 'startup')).toBe(true);
  f.advance(250);
  expect(f.controller.state).toBe('ready');
  f.advance(250);
  expect(f.controller.state).toBe('fenced');
  expect(f.sent.filter(event => event.type === 'touch_close')).toHaveLength(1);
});

it('startup keepalive coalescing preserves actual RTT and still requires a native receipt after READY', () => {
  const f = fixture(false);
  f.controller.open(CAPTURE); f.bind();
  for (let n = 0; n < 5; n++) f.advance(250);
  f.status(0, 0, 'startup');
  f.advance(100);
  expect(f.status(5, 2)).toBe(true);
  expect(f.onReceipt.mock.calls.at(-1)?.[0].receiptRoundTripMs).toBe(100);
  expect(f.controller.pendingReceiptCount).toBe(0);
  expect(f.controller.down(1, POINT)).toBe(true);
  f.advance(250); f.advance(250);
  expect(f.controller.state).toBe('fenced');
});

it('cold startup remains bounded at six seconds and never sends a pointer action before STARTUP0', () => {
  const f = fixture(false);
  f.controller.open(CAPTURE); f.bind();
  for (let n = 0; n < 24; n++) f.advance(250);
  expect(f.controller.state).toBe('fenced');
  expect(f.events().every(event => event.action === 4)).toBe(true);
  expect(f.controller.pendingReceiptCount).toBe(0);
  expect(f.sent.filter(event => event.type === 'touch_close')).toHaveLength(1);
});

it('server identity alone cannot authorize DOWN; only bound injector STARTUP0 enables it', () => {
  const f = fixture(false); expect(f.controller.open(CAPTURE)).toBe(true);
  expect(f.controller.down(1, POINT)).toBe(false);
  expect(f.bind()).toBe(true); expect(f.controller.down(1, POINT)).toBe(false);
  expect(f.status(0, 0, 'startup')).toBe(true); expect(f.controller.down(1, POINT)).toBe(true);
});

it.each([
  { ...CAPTURE, captureEpoch: '00000000-0000-0000-0000-000000000000' },
  { ...CAPTURE, captureEpoch: CAPTURE.captureEpoch.toUpperCase() },
  { ...CAPTURE, frameWidth: 0 }, { ...CAPTURE, frameHeight: 16385 },
  { ...CAPTURE, frameWidth: 960.5 }, { ...CAPTURE, captureEpoch: 'not-a-capture-uuid' },
])('cannot open an invalid capture %#', binding => {
  const f = fixture(false); f.capture(binding);
  expect(f.controller.open(binding)).toBe(false); expect(f.sent).toEqual([]);
});

it('an unrendered v2 packet or a different size does not open input', () => {
  const f = fixture(false); f.capture(null); expect(f.controller.open(CAPTURE)).toBe(false);
  f.capture({ ...CAPTURE, frameWidth: 540 }); expect(f.controller.open(CAPTURE)).toBe(false);
  expect(f.sent).toEqual([]);
});

it('copies the rendered binding and rejects duplicate open, preventing owner takeover', () => {
  const f = fixture(false); const binding = { ...CAPTURE };
  f.controller.open(binding); binding.frameWidth = 100;
  expect(f.bind()).toBe(true); expect(f.controller.open(CAPTURE)).toBe(false);
  expect(f.sent).toEqual([{ type: 'touch_open', capture_epoch: CAPTURE.captureEpoch, frame_width: 960, frame_height: 540 }]);
});

it('coalesces 1000 unsent moves into one sample without allocating a trajectory', () => {
  const f = fixture(); f.controller.down(1, POINT); f.ackLatest();
  for (let i = 0; i < 1000; i++) f.controller.moveTo(1, { x: i % 900, y: 201 });
  expect(f.events()).toHaveLength(1); expect(f.controller.hasPendingMove).toBe(true);
  f.advance(16);
  expect(f.events()).toHaveLength(2); expect(f.events()[1].x).toBe(99);
  expect(f.controller.hasPendingMove).toBe(false); expect(f.controller.pendingReceiptCount).toBe(1);
});

it('UP immediately supersedes an unsent MOVE and waits for its exact receipt before another DOWN', () => {
  const f = fixture(); f.controller.down(1, POINT); f.ackLatest();
  f.controller.moveTo(1, { x: 500, y: 210 });
  f.controller.up(1, { x: 600, y: 220 });
  expect(f.events().map(x => x.action)).toEqual([0, 1]);
  expect(f.events()[1].x).toBe(600); expect(f.controller.down(2, POINT)).toBe(false);
  f.ackLatest(); expect(f.controller.down(2, POINT)).toBe(true); expect(f.events().at(-1)?.gesture).toBe(2);
});

it('ignores secondary pointer events and cancels the actual pointer using native CANCEL3', () => {
  const f = fixture(); f.controller.down(1, POINT); f.ackLatest();
  expect(f.controller.down(2, POINT)).toBe(false);
  expect(f.controller.moveTo(2, { x: 500, y: 220 })).toBe(false);
  expect(f.controller.up(2, POINT)).toBe(false); expect(f.controller.cancel(2)).toBe(false);
  expect(f.controller.cancel(1)).toBe(true); expect(f.events().map(x => x.action)).toEqual([0, 3]);
  expect(f.ackLatest()).toBe(true); expect(f.onReceipt.mock.calls.at(-1)?.[0].status).toBe(3);
  expect(f.controller.down(1, POINT)).toBe(true);
});

it.each([{ x: 960, y: 1 }, { x: -1, y: 0 }, { x: 2, y: 540 }, { x: 1.5, y: 2 }, { x: NaN, y: 2 }])(
  'rejects DOWN outside capture without clamping %#', point => {
    const f = fixture(); expect(f.controller.down(1, point)).toBe(false); expect(f.events()).toEqual([]);
  });

it('an invalid point during a held gesture fences the owner and does not inject a fake UP', () => {
  const f = fixture(); f.controller.down(1, POINT);
  expect(f.controller.moveTo(1, { x: 960, y: 0 })).toBe(false);
  expect(f.controller.state).toBe('fenced'); expect(f.sent.at(-1)).toEqual({ type: 'touch_close' });
  expect(f.events().map(x => x.action)).toEqual([0]);
});

it.each(['epoch', 'size', 'decoder', 'socket'])('fences held input immediately after %s loss', cause => {
  const f = fixture(); f.controller.down(1, POINT); f.ackLatest(); f.controller.moveTo(1, { x: 500, y: 250 });
  if (cause === 'epoch') f.capture({ ...CAPTURE, captureEpoch: '15ce7215-36ac-4aee-bd0b-c84d29c313a9' });
  if (cause === 'size') f.capture({ ...CAPTURE, frameWidth: 540, frameHeight: 960 });
  if (cause === 'decoder') f.capture(null);
  if (cause === 'socket') f.socket.readyState = 3;
  f.advance(16);
  expect(f.controller.state).toBe('fenced'); expect(f.controller.pointerHeld).toBe(false);
  expect(f.events().map(x => x.action)).toEqual([0]);
  f.capture({ ...CAPTURE }); f.socket.readyState = 1; f.advance(16);
  expect(f.controller.down(1, POINT)).toBe(false); expect(f.events()).toHaveLength(1);
});

it('does not queue close behind a congested socket or replay gesture when the buffer drains', () => {
  const f = fixture(); f.controller.down(1, POINT); f.ackLatest();
  f.socket.bufferedAmount = LIMITS.bufferedBytes + 1;
  f.controller.moveTo(1, { x: 400, y: 200 }); f.advance(16);
  expect(f.controller.state).toBe('fenced'); expect(f.sent.at(-1)?.type).toBe('touch_event');
  f.socket.bufferedAmount = 0; f.advance(16); f.controller.up(1, POINT); f.controller.destroy();
  expect(f.events().map(x => x.action)).toEqual([0]); expect(f.sent.filter(x => x.type === 'touch_close')).toHaveLength(0);
});

it('unknown DOWN write is not repeated, even if send threw after accepting its bytes', () => {
  const f = fixture();
  f.socket.send.mockImplementation(raw => { const message = JSON.parse(raw); f.sent.push(message);
    if (message.type === 'touch_event') throw new Error('after_write'); });
  expect(f.controller.down(1, POINT)).toBe(false); expect(f.controller.state).toBe('fenced');
  f.controller.down(1, POINT); f.controller.retire(); f.controller.destroy();
  expect(f.events().map(x => x.action)).toEqual([0]); expect(f.sent.filter(x => x.type === 'touch_close')).toHaveLength(1);
});

it('native receipt silence fences after 500ms despite a successful socket send', () => {
  const f = fixture(); f.controller.down(1, POINT);
  f.advance(250); f.advance(250);
  expect(f.controller.state).toBe('fenced'); expect(f.controller.pointerHeld).toBe(false);
  expect(f.onState).toHaveBeenLastCalledWith('fenced', 'native_receipt_timeout');
  expect(f.controller.recoverableIdleReceiptLoss).toBe(false);
});
it('classifies only an idle heartbeat timeout as eligible for reconciliation after known release', () => {
  const f = fixture();
  f.advance(250); f.advance(250); f.advance(250);
  expect(f.controller.state).toBe('fenced');
  expect(f.controller.recoverableIdleReceiptLoss).toBe(true);
  expect(f.controller.unknownPointerReceiptLoss).toBe(false);
});

it.each(['down', 'move', 'up', 'cancel'])('preserves an unknown %s outcome across retirement and native release', phase => {
  const f = fixture();
  f.controller.down(1, POINT);
  if (phase !== 'down') {
    f.ackLatest();
    if (phase === 'move') { f.controller.moveTo(1, { x: 400, y: 200 }); f.advance(16); }
    else if (phase === 'up') f.controller.up(1, POINT);
    else f.controller.cancel(1);
  }
  f.advance(250); f.advance(250);
  expect(f.controller.state).toBe('fenced');
  expect(f.controller.unknownPointerReceiptLoss).toBe(true);
  expect(f.controller.recoverableIdleReceiptLoss).toBe(false);
  expect(f.sent.filter(x => x.type === 'touch_close')).toHaveLength(1);
  const events = f.events().length;
  f.status(0, 3, 'release');
  expect(f.controller.state).toBe('closed');
  expect(f.controller.unknownPointerReceiptLoss).toBe(true);
  expect(f.controller.down(2, POINT)).toBe(false);
  expect(f.events()).toHaveLength(events);
});

it('a background scheduling gap cancels instead of flushing the old pending move', () => {
  const f = fixture(); f.controller.down(1, POINT); f.ackLatest();
  f.controller.moveTo(1, { x: 500, y: 200 }); f.advance(501);
  expect(f.onState).toHaveBeenLastCalledWith('fenced', 'scheduler_gap');
  expect(f.events().map(x => x.action)).toEqual([0]);
});

it('drops a move older than 100ms without declaring that it was applied', () => {
  const f = fixture(); f.controller.down(1, POINT); f.ackLatest();
  f.controller.moveTo(1, { x: 500, y: 200 }); f.advance(101);
  expect(f.events().map(x => x.action)).toEqual([0]); expect(f.controller.hasPendingMove).toBe(false);
});

it('heartbeats preserve held gesture identity, then use gesture0 while idle, with native status2', () => {
  const f = fixture(); f.controller.down(1, POINT); f.ackLatest(); f.advance(250);
  expect(f.events().at(-1)).toMatchObject({ action: 4, gesture: 1, x: 100, y: 200 }); expect(f.ackLatest()).toBe(true);
  f.controller.up(1, POINT); f.ackLatest(); f.advance(250);
  expect(f.events().at(-1)).toMatchObject({ action: 4, gesture: 0, x: 0, y: 0 }); expect(f.ackLatest()).toBe(true);
});

it('sparse MOVE receipts do not report coalesced samples as applied or retain their old deadlines', () => {
  const f = fixture(); f.controller.down(1, POINT); f.ackLatest();
  for (let i = 1; i <= 3; i++) { f.controller.moveTo(1, { x: 100 + i * 100, y: 200 }); f.advance(16); }
  f.status(4);
  expect(f.onReceipt.mock.calls.map(([x]) => x.sequence)).toEqual([1, 4]);
  expect(f.controller.pendingReceiptCount).toBe(0); expect(f.status(3)).toBe(false);
});

it('a later heartbeat receipt cannot replace the required exact terminal receipt', () => {
  const f = fixture(); f.controller.down(1, POINT); f.ackLatest(); f.controller.up(1, POINT);
  f.advance(250); f.ackLatest(); expect(f.controller.down(1, POINT)).toBe(false);
  f.advance(250); expect(f.controller.state).toBe('fenced');
  expect(f.controller.recoverableIdleReceiptLoss).toBe(false);
});

it('a late exact terminal receipt remains valid after a later heartbeat without replaying any command', () => {
  const f = fixture(); f.controller.down(1, POINT); f.ackLatest(); f.controller.up(1, POINT);
  f.advance(250); f.ackLatest(); expect(f.controller.down(1, POINT)).toBe(false);
  expect(f.status(2)).toBe(true); expect(f.status(2)).toBe(false);
  expect(f.onReceipt.mock.calls.map(([x]) => x.sequence)).toEqual([1, 3, 2]);
  expect(f.controller.down(1, POINT)).toBe(true);
  expect(f.events().map(x => x.action)).toEqual([0, 1, 4, 0]);
});

it('a duplicated bound STARTUP0 receipt neither opens a second owner nor fences the ready owner', () => {
  const f = fixture(); expect(f.status(0, 0, 'startup')).toBe(false);
  expect(f.controller.state).toBe('ready'); expect(f.controller.down(1, POINT)).toBe(true);
  expect(f.sent.filter(x => x.type === 'touch_open')).toHaveLength(1);
});

it.each(['owner', 'session_id', 'capture_epoch'])('ignores a foreign %s receipt without touching the real owner', field => {
  const f = fixture(); f.controller.down(1, POINT);
  expect(f.status(0, 3, 'release', { [field]: 'foreign_identity_1234' })).toBe(false);
  expect(f.controller.state).toBe('ready'); expect(f.controller.pointerHeld).toBe(true);
  expect(f.ackLatest()).toBe(true);
});

it.each([
  { sequence: 99 }, { sequence: 1.2 }, { status: 2 }, { origin: 'admission' },
  { device_uptime_ms: Number.MAX_SAFE_INTEGER + 1 }, { ignored: 'metadata' },
])('a malformed or impossible bound receipt fences rather than authorizing input %#', override => {
  const f = fixture(); f.controller.down(1, POINT); expect(f.status(1, 1, 'input', override)).toBe(false);
  expect(f.controller.state).toBe('fenced'); expect(f.controller.pointerHeld).toBe(false);
});

it.each([4, 5, 6])('native failure status%s retires owner without replay', status => {
  const f = fixture(); f.controller.down(1, POINT); expect(f.status(1, status)).toBe(false);
  expect(f.controller.state).toBe('fenced'); expect(f.controller.down(1, POINT)).toBe(false);
});

it('only known injector RELEASE3 closes an owner; unknown release cannot reopen the controller', () => {
  const f = fixture(); f.controller.down(1, POINT); f.controller.close();
  expect(f.controller.state).toBe('closing'); f.status(0, 6, 'release');
  expect(f.controller.state).toBe('fenced'); expect(f.controller.open(CAPTURE)).toBe(false);
  expect(f.status(0, 3, 'release')).toBe(true); expect(f.controller.state).toBe('closed');
  expect(f.controller.open(CAPTURE)).toBe(false); expect(f.controller.down(1, POINT)).toBe(false);
});

it('bounds outstanding scalar receipts and refuses UP instead of growing the queue', () => {
  const f = fixture(); f.controller.down(1, POINT);
  for (let i = 1; i <= 31; i++) { f.controller.moveTo(1, { x: 100 + i, y: 200 }); f.advance(16); }
  expect(f.controller.pendingReceiptCount).toBe(32);
  expect(f.controller.up(1, POINT)).toBe(false); expect(f.controller.state).toBe('fenced');
  expect(f.controller.pendingReceiptCount).toBe(0); expect(f.events()).toHaveLength(32);
});

it('exhausted sequence or gesture counters refuse rather than wrapping native identity', () => {
  for (const counter of ['sequence', 'gesture']) {
    const f = fixture(); Object.assign(f.controller, { [counter]: LIMITS.maxSequence });
    expect(f.controller.down(1, POINT)).toBe(false); expect(f.controller.state).toBe('fenced');
    expect(f.events()).toEqual([]);
  }
});

it('retire/destroy clears one move and all deadlines; subsequent ticks and events stay silent', () => {
  const f = fixture(); f.controller.down(1, POINT); f.controller.moveTo(1, { x: 500, y: 200 });
  f.controller.retire('blur'); f.controller.retire('hidden'); f.controller.destroy();
  f.advance(250); f.controller.up(1, POINT); f.controller.moveTo(1, POINT);
  expect(f.controller.state).toBe('destroyed'); expect(f.controller.hasPendingMove).toBe(false);
  expect(f.controller.pendingReceiptCount).toBe(0); expect(f.sent.filter(x => x.type === 'touch_close')).toHaveLength(1);
});

it('input delivered before the delayed scheduler resumes still fences a 501ms background gap', () => {
  const f = fixture(); f.advance(501, false);
  expect(f.controller.down(1, POINT)).toBe(false); expect(f.controller.state).toBe('fenced');
  expect(f.events()).toEqual([]);
});

it('a receipt returned synchronously by a transport does not leave a phantom terminal deadline', () => {
  const f = fixture();
  f.socket.send.mockImplementation(raw => { const message = JSON.parse(raw); f.sent.push(message);
    if (message.type === 'touch_event') f.status(message.sequence, message.action === 4 ? 2 : message.action === 3 ? 3 : 1); });
  expect(f.controller.down(1, POINT)).toBe(true); expect(f.controller.up(1, POINT)).toBe(true);
  expect(f.controller.down(2, POINT)).toBe(true); expect(f.controller.pendingReceiptCount).toBe(0);
});

describe('native canvas event lifecycle', () => {
  let dispose: (() => void) | null;
  beforeEach(() => { jest.useFakeTimers(); dispose = null; });
  afterEach(() => { dispose?.(); document.body.replaceChildren(); jest.useRealTimers(); });
  function surface() {
    const f = fixture(true, () => performance.now());
    const canvas = document.createElement('canvas'); document.body.append(canvas);
    canvas.setPointerCapture = jest.fn();
    let enabled = true, geometry = true;
    const mapper = jest.fn((event: PointerEvent) => geometry ? { x: event.clientX, y: event.clientY } : null);
    dispose = attachContinuousPointer({ canvas, controller: f.controller, allowed: () => enabled, point: mapper });
    const event = (type: string, x = 100, extras: Record<string, unknown> = {}) => {
      const value = new MouseEvent(type, { clientX: x, clientY: 200, button: 0, buttons: 1, cancelable: true });
      Object.defineProperties(value, { pointerId: { value: 1, configurable: true }, isPrimary: { value: true, configurable: true } });
      for (const [key, extra] of Object.entries(extras)) Object.defineProperty(value, key, { value: extra });
      canvas.dispatchEvent(value); return value;
    };
    return { ...f, canvas, event, mapper, enabled: (value: boolean) => { enabled = value; }, geometry: (value: boolean) => { geometry = value; } };
  }
  it('native pointermove sends before pointerup and keeps reverse movement intact', () => {
    const f = surface(); f.event('pointerdown'); f.ackLatest();
    expect(f.canvas.setPointerCapture).toHaveBeenCalledWith(1);
    f.event('pointermove', 500); jest.advanceTimersByTime(16); f.ackLatest();
    f.event('pointermove', 200); jest.advanceTimersByTime(16); f.ackLatest();
    expect(f.events().map(x => x.action)).toEqual([0, 2, 2]);
    f.event('pointerup', 220); f.ackLatest(); f.event('lostpointercapture');
    expect(f.events().map(x => x.action)).toEqual([0, 2, 2, 1]);
  });
  it('uses the last browser-coalesced sample without growing an intermediate list', () => {
    const f = surface(); f.event('pointerdown'); f.ackLatest();
    f.event('pointermove', 200, { getCoalescedEvents: () => [{ pointerId: 1, clientX: 300, clientY: 200 }, { pointerId: 1, clientX: 700, clientY: 200 }] });
    jest.advanceTimersByTime(16); expect(f.events().at(-1)?.x).toBe(700);
  });
  it.each(['pointercancel', 'lostpointercapture', 'buttons_lost'])('cancels %s without synthesizing UP', cause => {
    const f = surface(); f.event('pointerdown'); f.ackLatest();
    if (cause === 'buttons_lost') f.event('pointermove', 300, { buttons: 0 });
    else f.event(cause);
    expect(f.events().map(x => x.action)).toEqual([0, 3]); expect(f.ackLatest()).toBe(true);
  });
  it.each(['blur', 'hidden', 'readonly', 'geometry'])('closes the owner for %s, clearing pending movement', cause => {
    const f = surface(); f.event('pointerdown'); f.ackLatest(); f.event('pointermove', 500);
    if (cause === 'blur') window.dispatchEvent(new Event('blur'));
    if (cause === 'hidden') {
      const visibility = jest.spyOn(document, 'hidden', 'get').mockReturnValue(true);
      document.dispatchEvent(new Event('visibilitychange')); visibility.mockRestore();
    }
    if (cause === 'readonly') { f.enabled(false); jest.advanceTimersByTime(16); }
    if (cause === 'geometry') { f.geometry(false); f.event('pointermove', 600); }
    expect(f.controller.state).toBe('fenced'); expect(f.sent.at(-1)).toEqual({ type: 'touch_close' });
    expect(f.events().map(x => x.action)).toEqual([0]);
    expect(f.controller.hasPendingMove).toBe(false);
  });
  it('failed setPointerCapture after accepted DOWN retires rather than leaving a held finger', () => {
    const f = surface(); f.canvas.setPointerCapture = jest.fn(() => { throw new Error('capture_failed'); });
    f.event('pointerdown'); expect(f.controller.state).toBe('fenced');
    expect(f.events().map(x => x.action)).toEqual([0]); expect(f.sent.at(-1)?.type).toBe('touch_close');
  });
  it('refuses letterbox/secondary input without starting or preventing the unrelated pointer', () => {
    const f = surface(); f.geometry(false);
    expect(f.event('pointerdown').defaultPrevented).toBe(false);
    f.geometry(true); expect(f.event('pointerdown', 100, { isPrimary: false }).defaultPrevented).toBe(false);
    expect(f.event('pointerdown', 100, { button: 2 }).defaultPrevented).toBe(false);
    expect(f.events()).toEqual([]);
  });
  it('disposal removes every listener and its scheduler; a retired surface stays silent', () => {
    const f = surface(); f.event('pointerdown'); f.ackLatest(); dispose?.();
    const count = f.sent.length;
    f.event('pointerdown'); f.event('pointermove', 600); f.event('pointerup', 600);
    window.dispatchEvent(new Event('blur')); document.dispatchEvent(new Event('visibilitychange'));
    jest.advanceTimersByTime(2000); dispose?.();
    expect(f.sent).toHaveLength(count); expect(f.controller.state).toBe('destroyed'); expect(jest.getTimerCount()).toBe(0);
  });
  it('a failed owner stops its own scheduler while the surface remains mounted', () => {
    const f = surface(); f.event('pointerdown');
    jest.advanceTimersByTime(512);
    expect(f.controller.state).toBe('fenced'); expect(jest.getTimerCount()).toBe(0);
    expect(f.events().map(x => x.action)).toEqual([0, 4]);
  });
});
