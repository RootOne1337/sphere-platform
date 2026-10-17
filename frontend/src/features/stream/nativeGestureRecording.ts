import type { PointerInputObservation, PointerObservation } from './continuousPointer';
import type { StreamInput } from './controlObservation';

export type NativeGestureRecordingEvent = { phase: 'started'; requestId: string } | {
  phase: 'finished'; requestId: string; completedAt: number;
  outcome: 'confirmed' | 'unknown' | 'interrupted' | 'cancelled' | 'unsupported';
  input: StreamInput | null;
};
type Gesture = { requestId: string; down: PointerInputObservation; points: PointerInputObservation[];
  terminal: PointerInputObservation | null; downConfirmed: boolean; overflow: boolean };
const MAX_POINTS = 4096;
const MAX_DURATION_MS = 60000;

/** One bounded, viewer-local gesture. It never sends input, schedules a move,
 * keeps wire ownership keys, or exports an arbitrary curve as a straight swipe.
 * Exact native DOWN + terminal UP confirm the gesture boundaries, not every MOVE.
 * Path timestamps describe browser submission; APK MOVE coalescing is not an execution trace.
 */
export class NativeGestureRecording {
  private gesture: Gesture | null = null;
  constructor(private readonly options: { deviceId: string; enabled: () => boolean;
    onEvent: (event: NativeGestureRecordingEvent) => void; now?: () => number }) {}
  private emit(event: NativeGestureRecordingEvent) { try { this.options.onEvent(event); } catch { /* Observation only. */ } }
  offered(input: PointerInputObservation) {
    if (input.action === 0) {
      if (this.gesture) this.retired();
      if (!this.options.enabled()) return;
      const requestId = crypto.randomUUID();
      this.gesture = { requestId, down: input, points: [input], terminal: null, downConfirmed: false, overflow: false };
      this.emit({ phase: 'started', requestId });
      return;
    }
    const g = this.gesture;
    if (!g || input.gesture !== g.down.gesture || g.terminal) return;
    const last = g.points.at(-1)!;
    if (input.capture.captureEpoch !== g.down.capture.captureEpoch
      || input.capture.frameWidth !== g.down.capture.frameWidth || input.capture.frameHeight !== g.down.capture.frameHeight
      || !Number.isFinite(input.at) || input.at < last.at) { this.retired(); return; }
    if (g.points.length < MAX_POINTS) g.points.push(input); else g.overflow = true;
    if (input.action === 1 || input.action === 3) g.terminal = input;
  }
  receipt(receipt: PointerObservation) {
    const g = this.gesture;
    if (!g) return;
    if (receipt.sequence === g.down.sequence && receipt.action === 0 && receipt.status === 1) g.downConfirmed = true;
    if (!g.terminal || receipt.sequence !== g.terminal.sequence || receipt.action !== g.terminal.action) return;
    if (g.terminal.action === 3 && receipt.status === 3) { this.finish('cancelled'); return; }
    if (receipt.status !== 1 || !g.downConfirmed) { this.finish('unknown'); return; }
    const input = this.replayable(g);
    this.finish(input ? 'confirmed' : 'unsupported', input);
  }
  interrupted(gesture: number) { if (this.gesture?.down.gesture === gesture) this.finish('interrupted'); }
  retired() { if (this.gesture) this.finish('unknown'); }
  private finish(outcome: Extract<NativeGestureRecordingEvent, {phase:'finished'}>['outcome'], input: StreamInput | null = null) {
    const g = this.gesture;
    if (!g) return;
    this.gesture = null; // Resolve exactly once, including re-entrant observers.
    this.emit({ phase: 'finished', requestId: g.requestId, completedAt: (this.options.now ?? (() => performance.now()))(), outcome, input });
  }
  private replayable(g: Gesture): StreamInput | null {
    const start = g.down, end = g.terminal!;
    const duration = Math.round(end.at - start.at);
    if (g.overflow || duration < 0 || duration > MAX_DURATION_MS) return null;
    return { deviceId:this.options.deviceId, at:start.at, endedAt:end.at,
      dimensions:{width:start.capture.frameWidth,height:start.capture.frameHeight},
      command: {type:'pointer_path',path:{schema_version:1,frame_width:start.capture.frameWidth,frame_height:start.capture.frameHeight,
        points:g.points.map(p=>({t_ms:Math.round(p.at-start.at),action:p.action as 0|1|2,x:p.x,y:p.y}))}} };
  }
}
