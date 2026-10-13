import type { PointerTransport } from './continuousPointer';
import type { DirectVideoBinding } from './directVideoProtocol';

/** The peer comes from authenticated signaling. This handle cannot grant native ownership. */
export interface DirectControlEndpoint extends PointerTransport {
  readonly session: string;
  readonly sharedInput?: boolean;
  capture(): DirectVideoBinding | null;
  listen(receipt: (message: unknown) => void): () => void;
}

/** One fixed route per native owner. A failed direct send is never retried over WebSocket. */
export class DirectPointerTransport implements PointerTransport {
  constructor(private readonly server: PointerTransport, readonly direct: DirectControlEndpoint) {}
  get readyState() { return (this.direct.sharedInput || this.server.readyState === 1) && this.direct.readyState === 1 ? 1 : 0; }
  get bufferedAmount() { return (this.direct.sharedInput ? 0 : this.server.bufferedAmount) + this.direct.bufferedAmount; }
  send(raw: string): void {
    if (new TextEncoder().encode(raw).length > 1024) throw Error('direct_input_message_too_large');
    const data = JSON.parse(raw);
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw Error('invalid_direct_input');
    if (data.type === 'touch_close' && Object.keys(data).length === 1) { this.closeInput(); return; }
    if (this.readyState !== 1 || this.bufferedAmount > 1024) throw Error('direct_input_unavailable');
    if (data.type === 'touch_open' && Object.keys(data).sort().join() === 'capture_epoch,frame_height,frame_width,type') {
      const binding = this.direct.capture();
      if (!binding || !/^[0-9a-f]{32}$/.test(this.direct.session) || data.capture_epoch !== binding.captureEpoch
        || data.frame_width !== binding.width || data.frame_height !== binding.height) throw Error('direct_capture_changed');
      if (this.direct.sharedInput) this.direct.send(raw);
      else this.server.send(JSON.stringify({ ...data, type: 'touch_direct_open', direct_session: this.direct.session }));
      return;
    }
    if (data.type !== 'touch_event' || Object.keys(data).sort().join() !== 'action,gesture,sequence,type,x,y') {
      throw Error('invalid_direct_input');
    }
    // Only the native single-pointer parser executes these fields. No code,
    // ordinary command, owner, tenant or alternate route is accepted here.
    if (!['sequence', 'gesture', 'action', 'x', 'y'].every(k => Number.isSafeInteger(data[k]))
      || data.sequence < 1 || data.sequence > 2147483647 || data.gesture < 0 || data.gesture > 2147483647
      || data.action < 0 || data.action > 4 || data.x < 0 || data.y < 0) throw Error('invalid_direct_input');
    this.direct.send(raw);
  }
  closeInput(cancelUnstarted = false): void {
    // Revocation stays available when the peer/data channel has already gone.
    // Sending CLOSE through both paths cancels one owner; it never replays a touch.
    if (this.direct.readyState === 1 && this.direct.bufferedAmount <= 1024) {
      try { this.direct.send('{"type":"touch_close"}'); } catch { /* Independent server revocation below. */ }
    }
    if (this.direct.sharedInput) return; // Exact participant cleanup on the same authorized media peer.
    if (this.server.readyState !== 1 || this.server.bufferedAmount > 1024) throw Error('close_transport_unavailable');
    this.server.send(cancelUnstarted ? '{"type":"touch_close","cancel_unstarted":true}' : '{"type":"touch_close"}');
  }
}
