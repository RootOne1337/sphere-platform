import type { PointerInputObservation, PointerObservation } from './continuousPointer';
import type { StreamInput } from './controlObservation';

export type NativeGestureRecordingEvent = { phase: 'started'; requestId: string } | {
  phase: 'finished'; requestId: string; completedAt: number;
  outcome: 'confirmed' | 'unknown' | 'interrupted' | 'cancelled' | 'unsupported';
  input: StreamInput | null;
};
type Gesture = { requestId: string; down: PointerInputObservation; points: PointerInputObservation[];
  terminal: PointerInputObservation | null; downConfirmed: boolean; overflow: boolean };
const MAX_POINTS = 1024;
const MAX_DURATION_MS = 10000;

/** One bounded, viewer-local gesture. It never sends input, schedules a move,
 * keeps wire ownership keys, or exports an arbitrary curve as a straight swipe.
 * Only exact native DOWN + terminal UP receipts can produce a replayable entry.
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
    const dx = end.x - start.x, dy = end.y - start.y, distance = Math.hypot(dx,dy);
    const tolerance = Math.max(2, Math.min(start.capture.frameWidth,start.capture.frameHeight) * .004);
    const stationary = g.points.every(p => Math.hypot(p.x-start.x,p.y-start.y) <= tolerance);
    if (!stationary) {
      if (distance <= tolerance) return null; // Out-and-back is never a tap.
      let progress = 0;
      for (const p of g.points) {
        const along = ((p.x-start.x)*dx+(p.y-start.y)*dy)/distance;
        const deviation = Math.abs((p.x-start.x)*dy-(p.y-start.y)*dx)/distance;
        if (deviation > tolerance || along < progress-tolerance || along > distance+tolerance) return null;
        progress = Math.max(progress,along);
      }
    }
    return { deviceId:this.options.deviceId, at:start.at, endedAt:end.at,
      dimensions:{width:start.capture.frameWidth,height:start.capture.frameHeight},
      command: stationary && duration < 250 ? {type:'click',x:start.x,y:start.y}
        : {type:'swipe',x1:start.x,y1:start.y,x2:stationary?start.x:end.x,y2:stationary?start.y:end.y,duration_ms:Math.max(1,duration)} };
  }
}
