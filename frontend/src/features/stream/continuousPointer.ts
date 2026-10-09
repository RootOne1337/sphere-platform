import type { CaptureFrameBinding } from '@/lib/h264-decoder';

/** Single-pointer transport. Activation requires scoped capability and a rendered v2 capture. */
export const CONTINUOUS_POINTER_LIMITS = Object.freeze({
  moveIntervalMs: 16, moveAgeMs: 100, heartbeatMs: 250, receiptMs: 500,
  startupMs: 6000, schedulingGapMs: 500, bufferedBytes: 1024, pendingReceipts: 32,
  maxSequence: 2_147_483_647,
});
export type ContinuousPointerState = 'idle' | 'opening' | 'ready' | 'closing' | 'fenced' | 'closed' | 'destroyed';
type Point = { x: number; y: number };
type Pointer = Point & { id: number; gesture: number };
type Pending = { sequence: number; action: number; at: number; deadlineAt?: number };
type Session = { session: string; owner: string };
export interface PointerTransport {
  readonly readyState: number;
  readonly bufferedAmount: number;
  send(data: string): void;
}
export interface PointerObservation {
  sequence: number; action: number; status: 1 | 2 | 3; deviceUptimeMs: number; receiptRoundTripMs: number;
}
/** One scalar failure snapshot, never a trajectory, frame, owner ID or replay queue. */
export type PointerFenceObservation = Readonly<{
  reason: string; phase: ContinuousPointerState; idleHeartbeatOnly: boolean;
  offeredSequence: number; acknowledgedSequence: number; pendingCount: number;
  oldestSequence: number | null; oldestAction: number | null;
  oldestAgeMs: number | null; oldestDeadlineAgeMs: number | null;
  terminalSequence: number | null; terminalAgeMs: number | null; pointerHeld: boolean;
  tickGapMs: number | null; lastSendAgeMs: number | null;
  lastReceiptAgeMs: number | null; lastReceiptRoundTripMs: number | null;
  socketState: number; bufferedBytes: number | null;
}>;
type Options = {
  /** Exact socket instance; replacing the outer ref must destroy this controller. */
  socket: PointerTransport;
  /** Only the decoder's successfully rendered v2 binding, owned by this socket. */
  renderedCapture: () => CaptureFrameBinding | null;
  now?: () => number;
  onState?: (state: ContinuousPointerState, reason: string | null) => void;
  onReceipt?: (observation: PointerObservation) => void;
  onFence?: (observation: PointerFenceObservation) => void;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ID = /^[A-Za-z0-9_-]{8,128}$/;
const NIL_UUID = '00000000-0000-0000-0000-000000000000';
const integer = (value: unknown, min: number, max: number): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const exact = (value: Record<string, unknown>, keys: string[]) =>
  Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const validCapture = (value: CaptureFrameBinding) => typeof value.captureEpoch === 'string'
  && UUID.test(value.captureEpoch) && value.captureEpoch !== NIL_UUID
  && integer(value.frameWidth, 1, 16384) && integer(value.frameHeight, 1, 16384);
const sameCapture = (a: CaptureFrameBinding | null, b: CaptureFrameBinding | null) =>
  !!a && !!b && a.captureEpoch === b.captureEpoch && a.frameWidth === b.frameWidth && a.frameHeight === b.frameHeight;

/**
 * No timers, event listeners, trajectories or reconnect queue are retained here.
 * The owning UI must tick while mounted and retire on blur/hidden/lost socket.
 * send() completion is never an Android receipt. At most one unsent MOVE and
 * 32 scalar receipt records are held; DOWN/terminal are never deferred/replayed.
 */
export class ContinuousPointer {
  private stateValue: ContinuousPointerState = 'idle';
  private capture: CaptureFrameBinding | null = null;
  private session: Session | null = null;
  private held: Pointer | null = null;
  private move: (Point & { at: number }) | null = null;
  private sequence = 0;
  private gesture = 0;
  private pending: Pending[] = [];
  private terminal: Pending | null = null;
  private openedAt = 0;
  private lastSentAt = 0;
  private lastMoveAt = -Infinity;
  private lastTickAt = 0;
  private acknowledged = 0;
  private closeSent = false;
  private idleReceiptLoss = false;
  private lastReceipt: { at: number; roundTripMs: number } | null = null;
  private readonly now: () => number;

  constructor(private readonly options: Options) { this.now = options.now ?? (() => performance.now()); }
  get state() { return this.stateValue; }
  get pendingReceiptCount() { return this.pending.length; }
  get hasPendingMove() { return this.move !== null; }
  get pointerHeld() { return this.held !== null; }
  /** No Android touch or terminal outcome is unknown in this narrowly scoped failure. */
  get recoverableIdleReceiptLoss() { return this.idleReceiptLoss; }

  private transition(state: ContinuousPointerState, reason: string | null = null) {
    this.stateValue = state;
    try { this.options.onState?.(state, reason); } catch { /* UI observers do not own the transport. */ }
  }

  private current(): boolean {
    const now = this.now();
    if (!Number.isFinite(now) || now < this.lastTickAt || now - this.lastTickAt > CONTINUOUS_POINTER_LIMITS.schedulingGapMs) {
      this.retire('scheduler_gap'); return false;
    }
    if (this.options.socket.readyState !== 1 || !sameCapture(this.capture, this.options.renderedCapture())) {
      this.retire('capture_or_socket_lost');
      return false;
    }
    return true;
  }

  private writable(): boolean {
    const buffered = this.options.socket.bufferedAmount;
    return this.options.socket.readyState === 1 && Number.isFinite(buffered) && buffered >= 0
      && buffered <= CONTINUOUS_POINTER_LIMITS.bufferedBytes;
  }

  private write(message: Record<string, unknown>): boolean {
    if (!this.writable()) { this.retire('transport_backpressure'); return false; }
    try { this.options.socket.send(JSON.stringify(message)); return true; }
    catch { this.retire('socket_send_unknown'); return false; }
  }

  /** Called only after a scoped server capability matches this rendered binding. */
  open(binding: CaptureFrameBinding): boolean {
    if (this.stateValue !== 'idle' || !validCapture(binding)
      || !sameCapture(binding, this.options.renderedCapture())) return false;
    this.capture = { ...binding };
    const now = this.now();
    this.openedAt = this.lastSentAt = this.lastTickAt = now;
    this.transition('opening');
    return this.write({ type: 'touch_open', capture_epoch: binding.captureEpoch,
      frame_width: binding.frameWidth, frame_height: binding.frameHeight });
  }

  /** Trusted server replies, received on the same socket, never browser-selected owner metadata. */
  receive(message: unknown): boolean {
    if (!object(message) || !['touch_session', 'continuous_input_status'].includes(String(message.type))) return false;
    if (this.stateValue === 'idle' || this.stateValue === 'closed' || this.stateValue === 'destroyed') return false;
    if (message.type === 'touch_session') {
      if (this.stateValue !== 'opening' || this.session) return false;
      if (!exact(message, ['type', 'session_id', 'owner', 'capture_epoch', 'frame_width', 'frame_height'])
        || typeof message.session_id !== 'string' || !ID.test(message.session_id)
        || typeof message.owner !== 'string' || !ID.test(message.owner)
        || message.capture_epoch !== this.capture?.captureEpoch || message.frame_width !== this.capture?.frameWidth
        || message.frame_height !== this.capture?.frameHeight || !this.current()) {
        this.retire('invalid_session_binding'); return false;
      }
      this.session = { session: message.session_id, owner: message.owner };
      return true; // This is identity, not native readiness.
    }
    // Foreign, stale and unsolicited receipts cannot release or fail another owner.
    if (!this.session || message.owner !== this.session.owner || message.session_id !== this.session.session
      || message.capture_epoch !== this.capture?.captureEpoch) return false;
    if (!exact(message, ['type', 'session_id', 'owner', 'capture_epoch', 'sequence', 'status', 'stage', 'origin', 'device_uptime_ms'])
      || !integer(message.sequence, 0, CONTINUOUS_POINTER_LIMITS.maxSequence)
      || !integer(message.device_uptime_ms, 0, Number.MAX_SAFE_INTEGER)
      || !integer(message.status, 0, 6) || !['startup', 'input', 'release'].includes(String(message.stage))
      || !['injector', 'admission'].includes(String(message.origin))) {
      this.retire('invalid_native_receipt'); return false;
    }
    if (message.stage === 'release') {
      if (message.origin === 'injector' && message.sequence === 0 && message.status === 3) {
        this.held = this.move = this.terminal = null;
        this.pending = [];
        this.transition('closed');
        return true;
      }
      this.retire('release_unknown');
      this.transition('fenced', 'release_unknown'); return false;
    }
    if (!this.current()) return false;
    if (message.status >= 4) { this.retire('native_input_rejected_or_unknown'); return false; }
    if (message.stage === 'startup') {
      if (this.stateValue === 'ready' && message.origin === 'injector' && message.status === 0 && message.sequence === 0) return false;
      if (this.stateValue === 'opening' && message.origin === 'injector' && message.status === 0 && message.sequence === 0) {
        // Only keepalives can be sent before STARTUP0. Cold root startup has its own
        // deadline; their receipt deadline starts at READY, while RTT retains send time.
        this.pending = this.pending.map(p => ({ ...p, deadlineAt: this.now() }));
        this.transition('ready'); return true;
      }
      this.retire('invalid_startup_receipt'); return false;
    }
    if (message.origin !== 'injector' || (message.status !== 1 && message.status !== 2 && message.status !== 3)
      || message.sequence < 1 || message.sequence > this.sequence) {
      this.retire('invalid_input_receipt'); return false;
    }
    const terminalReceipt = this.terminal?.sequence === message.sequence;
    if (message.sequence <= this.acknowledged && !terminalReceipt) return false;
    const offered = terminalReceipt ? this.terminal : this.pending.find(p => p.sequence === message.sequence);
    if (!offered || (offered.action === 4 ? message.status !== 2 : offered.action === 3 ? message.status !== 3 : message.status !== 1)) {
      this.retire('receipt_action_mismatch'); return false;
    }
    // Sparse native receipts may result from MOVE coalescing. Removing earlier
    // scalar deadlines does NOT report those earlier MOVE as applied.
    const receiptSequence = message.sequence;
    this.acknowledged = Math.max(this.acknowledged, receiptSequence);
    this.pending = this.pending.filter(p => p.sequence > receiptSequence);
    if (this.terminal?.sequence === message.sequence) this.terminal = null;
    const receivedAt = this.now();
    this.lastReceipt = { at: receivedAt, roundTripMs: Math.max(0, receivedAt - offered.at) };
    try { this.options.onReceipt?.({ sequence: message.sequence, action: offered.action,
      status: message.status, deviceUptimeMs: message.device_uptime_ms,
      receiptRoundTripMs: this.lastReceipt.roundTripMs }); } catch { /* Observation only. */ }
    return true;
  }

  private point(point: Point): boolean {
    return !!this.capture && integer(point.x, 0, this.capture.frameWidth - 1)
      && integer(point.y, 0, this.capture.frameHeight - 1);
  }

  private event(action: number, point: Point, gesture: number): Pending | null {
    if (!this.current() || !this.point(point)) return null;
    if (this.sequence >= CONTINUOUS_POINTER_LIMITS.maxSequence
      || this.pending.length >= CONTINUOUS_POINTER_LIMITS.pendingReceipts) {
      this.retire('sequence_or_receipt_budget'); return null;
    }
    const entry = { sequence: ++this.sequence, action, at: this.now() };
    // Register before write: synchronous test transports and future adapters
    // may deliver a receipt during send(). Unknown writes are not repeated.
    this.pending.push(entry);
    this.lastSentAt = entry.at;
    if (!this.write({ type: 'touch_event', sequence: entry.sequence, gesture, action, x: point.x, y: point.y })) return null;
    return entry;
  }

  down(pointerId: number, point: Point): boolean {
    if (this.stateValue !== 'ready' || this.held || this.terminal || !integer(pointerId, 0, CONTINUOUS_POINTER_LIMITS.maxSequence)) return false;
    if (!this.current() || !this.point(point)) return false;
    if (this.gesture >= CONTINUOUS_POINTER_LIMITS.maxSequence) { this.retire('gesture_budget'); return false; }
    this.held = { ...point, id: pointerId, gesture: ++this.gesture };
    return this.event(0, point, this.gesture) !== null;
  }

  /** Replace one unsent MOVE, preserving the actual back-and-forth order of flushed samples. */
  moveTo(pointerId: number, point: Point): boolean {
    if (this.stateValue !== 'ready' || this.held?.id !== pointerId || !this.current()) return false;
    if (!this.point(point)) { this.retire('point_outside_capture'); return false; }
    this.move = { ...point, at: this.now() };
    return true;
  }

  private finish(pointerId: number, point: Point, action: 1 | 3): boolean {
    if (this.stateValue !== 'ready' || this.held?.id !== pointerId || !this.current()) return false;
    if (!this.point(point)) { this.retire('point_outside_capture'); return false; }
    const gesture = this.held.gesture;
    this.move = null;
    this.held = null;
    // Terminal point supersedes an unsent MOVE. Never queue it behind a delayed timer.
    const entry = this.event(action, point, gesture);
    this.terminal = entry && entry.sequence > this.acknowledged ? entry : null;
    return entry !== null;
  }
  up(pointerId: number, point: Point) { return this.finish(pointerId, point, 1); }
  cancel(pointerId: number) {
    return this.held ? this.finish(pointerId, this.move ?? this.held, 3) : false;
  }

  tick(): void {
    if (this.stateValue !== 'opening' && this.stateValue !== 'ready') return;
    if (!this.current()) return;
    const now = this.now();
    if (!Number.isFinite(now) || now < this.lastTickAt || now - this.lastTickAt > CONTINUOUS_POINTER_LIMITS.schedulingGapMs) {
      this.retire('scheduler_gap'); return;
    }
    if ((this.stateValue === 'opening' && now - this.openedAt >= CONTINUOUS_POINTER_LIMITS.startupMs)
      || (this.stateValue === 'ready' && this.pending.length > 0 && now - (this.pending[0].deadlineAt ?? this.pending[0].at) >= CONTINUOUS_POINTER_LIMITS.receiptMs)
      || (this.terminal && now - this.terminal.at >= CONTINUOUS_POINTER_LIMITS.receiptMs)) {
      this.retire('native_receipt_timeout'); return;
    }
    // Keep the preceding tick until after the deadline check so a failure
    // snapshot measures the actual timer gap rather than a freshly reset zero.
    this.lastTickAt = now;
    if (this.move && this.held && now - this.lastMoveAt >= CONTINUOUS_POINTER_LIMITS.moveIntervalMs) {
      const point = this.move;
      this.move = null;
      if (now - point.at <= CONTINUOUS_POINTER_LIMITS.moveAgeMs) {
        this.held = { ...this.held, x: point.x, y: point.y };
        this.lastMoveAt = now;
        this.event(2, point, this.held.gesture);
      }
    }
    if (this.stateValue !== 'opening' && this.stateValue !== 'ready') return;
    if (now - this.lastSentAt >= CONTINUOUS_POINTER_LIMITS.heartbeatMs) {
      this.event(4, this.held ?? { x: 0, y: 0 }, this.held?.gesture ?? 0);
    }
  }

  /** Blur, hidden, changed capture/auth/permissions or loss of pointer/socket ownership. */
  retire(reason = 'viewer_retired'): void {
    if (this.stateValue === 'idle' || this.stateValue === 'closed' || this.stateValue === 'destroyed'
      || this.stateValue === 'closing' || this.stateValue === 'fenced') return;
    this.idleReceiptLoss = reason === 'native_receipt_timeout' && this.held === null
      && this.terminal === null && this.pending.length > 0 && this.pending.every(p => p.action === 4);
    const now = this.now();
    const age = (at: number | undefined): number | null => at !== undefined
      && Number.isFinite(now) && Number.isFinite(at) && now >= at ? now - at : null;
    const oldest = this.pending[0];
    const snapshot: PointerFenceObservation = Object.freeze({ reason, phase: this.stateValue,
      idleHeartbeatOnly: this.idleReceiptLoss, offeredSequence: this.sequence,
      acknowledgedSequence: this.acknowledged, pendingCount: this.pending.length,
      oldestSequence: oldest?.sequence ?? null, oldestAction: oldest?.action ?? null,
      oldestAgeMs: age(oldest?.at), oldestDeadlineAgeMs: age(oldest?.deadlineAt ?? oldest?.at),
      terminalSequence: this.terminal?.sequence ?? null, terminalAgeMs: age(this.terminal?.at),
      pointerHeld: this.held !== null, tickGapMs: age(this.lastTickAt), lastSendAgeMs: age(this.lastSentAt),
      lastReceiptAgeMs: age(this.lastReceipt?.at), lastReceiptRoundTripMs: this.lastReceipt?.roundTripMs ?? null,
      socketState: this.options.socket.readyState,
      bufferedBytes: Number.isFinite(this.options.socket.bufferedAmount) && this.options.socket.bufferedAmount >= 0
        ? this.options.socket.bufferedAmount : null });
    this.held = this.move = this.terminal = null;
    this.pending = [];
    this.transition('fenced', reason);
    try { this.options.onFence?.(snapshot); } catch { /* Diagnostics never postpone release or replay input. */ }
    if (!this.closeSent && this.writable()) {
      this.closeSent = true;
      try { this.options.socket.send(JSON.stringify({ type: 'touch_close' })); }
      catch { /* Unknown close is not retried; native watchdog remains mandatory. */ }
    }
  }

  close(): void {
    if (this.stateValue === 'idle' || this.stateValue === 'closed' || this.stateValue === 'destroyed') return;
    const active = this.stateValue === 'opening' || this.stateValue === 'ready';
    this.retire('viewer_closed');
    if (active && this.closeSent) this.transition('closing');
  }

  destroy(): void {
    this.retire('viewer_destroyed');
    this.session = this.capture = this.held = this.move = this.terminal = null;
    this.pending = [];
    this.transition('destroyed');
  }
}

/** Native DOM adapter. Its owner supplies the existing fit/letterbox coordinate mapper. */
export function attachContinuousPointer(options: {
  canvas: HTMLCanvasElement;
  controller: ContinuousPointer;
  allowed: () => boolean;
  point: (event: PointerEvent, clamp: boolean) => Point | null;
}): () => void {
  const { canvas, controller } = options;
  const document = canvas.ownerDocument;
  const window = document.defaultView;
  if (!window) { controller.retire('surface_window_missing'); return () => controller.destroy(); }
  let pointer: number | null = null;
  let disposed = false;
  const allowed = () => {
    if (!options.allowed() || document.hidden) { controller.retire('surface_control_lost'); return false; }
    return true;
  };
  const down = (event: PointerEvent) => {
    if (disposed || event.button !== 0 || event.isPrimary === false || pointer !== null || !allowed()) return;
    const point = options.point(event, false);
    if (!point || !controller.down(event.pointerId, point)) return;
    pointer = event.pointerId;
    event.preventDefault();
    try { canvas.setPointerCapture(event.pointerId); }
    catch { pointer = null; controller.retire('pointer_capture_failed'); }
  };
  const move = (event: PointerEvent) => {
    if (disposed || event.pointerId !== pointer || !allowed()) return;
    if (event.buttons === 0) { controller.cancel(event.pointerId); pointer = null; return; }
    const samples = typeof event.getCoalescedEvents === 'function' ? event.getCoalescedEvents() : [];
    const latest = samples.at(-1) ?? event;
    if (latest.pointerId !== pointer) { controller.retire('coalesced_pointer_changed'); pointer = null; return; }
    const point = options.point(latest, true);
    if (!point) { controller.retire('surface_geometry_lost'); pointer = null; return; }
    controller.moveTo(event.pointerId, point);
    event.preventDefault();
  };
  const up = (event: PointerEvent) => {
    if (disposed || event.pointerId !== pointer) return;
    pointer = null;
    if (allowed()) {
      const point = options.point(event, true);
      if (point) controller.up(event.pointerId, point);
      else controller.retire('surface_geometry_lost');
    }
    event.preventDefault();
  };
  const cancel = (event: PointerEvent) => {
    if (disposed || event.pointerId !== pointer) return;
    pointer = null;
    controller.cancel(event.pointerId);
  };
  const blur = () => { pointer = null; controller.retire('surface_blur'); };
  const visibility = () => { if (document.hidden) { pointer = null; controller.retire('surface_hidden'); } };
  canvas.addEventListener('pointerdown', down);
  canvas.addEventListener('pointermove', move);
  canvas.addEventListener('pointerup', up);
  canvas.addEventListener('pointercancel', cancel);
  canvas.addEventListener('lostpointercapture', cancel);
  window.addEventListener('blur', blur);
  document.addEventListener('visibilitychange', visibility);
  // One bounded scheduler per mounted surface. A failed/closed owner cannot
  // become active again; stop ticking it rather than running a forever loop.
  const timer = window.setInterval(() => {
    if (allowed()) controller.tick();
    if (['fenced', 'closing', 'closed', 'destroyed'].includes(controller.state)) window.clearInterval(timer);
  }, CONTINUOUS_POINTER_LIMITS.moveIntervalMs);
  return () => {
    if (disposed) return;
    disposed = true;
    window.clearInterval(timer);
    canvas.removeEventListener('pointerdown', down);
    canvas.removeEventListener('pointermove', move);
    canvas.removeEventListener('pointerup', up);
    canvas.removeEventListener('pointercancel', cancel);
    canvas.removeEventListener('lostpointercapture', cancel);
    window.removeEventListener('blur', blur);
    document.removeEventListener('visibilitychange', visibility);
    pointer = null;
    controller.destroy();
  };
}
