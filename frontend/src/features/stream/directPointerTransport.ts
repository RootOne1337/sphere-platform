import type { PointerTransport } from './continuousPointer';
import type { DirectVideoBinding } from './directVideoProtocol';
import { validKeyboardCommand } from './remoteKeyboardProtocol';

/** The peer comes from authenticated signaling. This handle cannot grant native ownership. */
export interface DirectControlEndpoint extends PointerTransport {
  readonly session: string;
  readonly sharedInput?: boolean;
  readonly nativeKeys?: boolean;
  readonly keyboard?: boolean;
  capture(): DirectVideoBinding | null;
  listen(receipt: (message: unknown) => void): () => void;
}

/** One fixed route per native owner. A failed direct send is never retried over WebSocket. */
export class DirectPointerTransport implements PointerTransport {
  constructor(private readonly server: PointerTransport, readonly direct: DirectControlEndpoint) {}
  get readyState() { return (this.direct.sharedInput || this.server.readyState === 1) && this.direct.readyState === 1 ? 1 : 0; }
  get bufferedAmount() { return (this.direct.sharedInput ? 0 : this.server.bufferedAmount) + this.direct.bufferedAmount; }
  send(raw: string): void {
    if (new TextEncoder().encode(raw).length > (this.direct.keyboard ? 8192 : 1024)) throw Error('direct_input_message_too_large');
    const data = JSON.parse(raw);
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw Error('invalid_direct_input');
    if (data.type === 'touch_close' && Object.keys(data).length === 1) { this.closeInput(); return; }
    if (this.readyState !== 1 || this.bufferedAmount > (this.direct.keyboard ? 8192 : 1024)) throw Error('direct_input_unavailable');
    if (data.type === 'keyboard_mode' && Object.keys(data).sort().join() === 'enabled,type' && typeof data.enabled === 'boolean') {
      if (!this.direct.sharedInput || !this.direct.keyboard) throw Error('keyboard_unavailable');
      this.direct.send(raw); return;
    }
    if (data.type === 'keyboard_event') {
      const { type: _type, sequence, ...command } = data;
      if (!this.direct.sharedInput || !this.direct.keyboard || !Number.isInteger(sequence) || sequence < 1 || sequence > 2147483647
        || !validKeyboardCommand(command)) throw Error('invalid_keyboard_input');
      this.direct.send(raw); return;
    }
    if (data.type === 'touch_open' && Object.keys(data).sort().join() === 'capture_epoch,frame_height,frame_width,type') {
      const binding = this.direct.capture();
      if (!binding || !/^[0-9a-f]{32}$/.test(this.direct.session) || data.capture_epoch !== binding.captureEpoch
        || data.frame_width !== binding.width || data.frame_height !== binding.height) throw Error('direct_capture_changed');
      if (this.direct.sharedInput) this.direct.send(raw);
      else this.server.send(JSON.stringify({ ...data, type: 'touch_direct_open', direct_session: this.direct.session }));
      return;
    }
    if (data.type === 'key_event' && Object.keys(data).sort().join() === 'keycode,sequence,type') {
      if (!this.direct.sharedInput || !this.direct.nativeKeys || !Number.isSafeInteger(data.sequence)
        || data.sequence < 1 || data.sequence > 2147483647 || !supportedDirectKey(data.keycode)) throw Error('invalid_direct_key');
      this.direct.send(raw);
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

export const DIRECT_KEY_CODES = Object.freeze([3, 4, 187, 82, 67, 112, 66, 61,
  19, 20, 21, 22, 23, 111, 122, 123, 92, 93, 278, 277, 279]);
export const supportedDirectKey = (code: unknown): code is number =>
  typeof code === 'number' && Number.isSafeInteger(code) && DIRECT_KEY_CODES.includes(code);
