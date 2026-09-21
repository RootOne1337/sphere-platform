// Active DeviceStream decoder. The legacy src/lib/streaming implementation is not used here.
export type FrameCallback = (frame: VideoFrame) => void;
type PendingDecode = { timestamp: number; receivedAt: number; bytes: number };

const HEADER_BYTES = 14;
const MAX_FRAME_BYTES = 1024 * 1024;
const MAX_DECODE_FRAMES = 8;
const MAX_DECODE_BYTES = 2 * 1024 * 1024;
const MAX_DECODE_AGE_MS = 500;
const RECOVERY_COOLDOWN_MS = 1000;

export class H264Decoder {
  private decoder: VideoDecoder | null = null;
  private configured = false;
  private needsKeyFrame = true;
  private destroyed = false;
  private generation = 0;
  private retryAt = 0;
  private pending: PendingDecode[] = [];
  private pendingBytes = 0;
  private spsNal: Uint8Array | null = null;
  private ppsNal: Uint8Array | null = null;
  private lastTimestamp: number | null = null;

  constructor(private onFrame: FrameCallback, private onRecovery: () => void = () => {}) {}

  init() {
    if (!this.destroyed && !this.decoder) this.createDecoder();
  }

  private createDecoder(): boolean {
    if (this.destroyed || performance.now() < this.retryAt) return false;
    const generation = ++this.generation;
    try {
      this.decoder = new VideoDecoder({
        output: frame => {
          try {
            if (this.destroyed || generation !== this.generation) return;
            const index = this.pending.findIndex(p => p.timestamp === frame.timestamp);
            if (index < 0) return;
            const [entry] = this.pending.splice(index, 1);
            this.pendingBytes -= entry.bytes;
            if (performance.now() - entry.receivedAt > MAX_DECODE_AGE_MS) {
              this.recover();
              return;
            }
            this.onFrame(frame);
          } finally {
            frame.close(); // Includes stale callbacks, unmount and canvas exceptions.
          }
        },
        error: () => {
          if (!this.destroyed && generation === this.generation) this.recover();
        },
      });
      return true;
    } catch {
      this.recover();
      return false;
    }
  }

  private retireDecoder() {
    ++this.generation; // Fence callbacks before closing a previous codec.
    const previous = this.decoder;
    this.decoder = null;
    this.configured = false;
    this.needsKeyFrame = true;
    this.pending = [];
    this.pendingBytes = 0;
    this.lastTimestamp = null;
    if (previous && previous.state !== 'closed') previous.close();
  }

  private recover() {
    this.retireDecoder();
    this.retryAt = performance.now() + RECOVERY_COOLDOWN_MS;
    this.onRecovery();
  }

  /** A new socket/encoder must never reuse the previous stream's references. */
  reset() {
    this.retireDecoder();
    this.spsNal = this.ppsNal = null;
    this.retryAt = 0;
  }

  handleBinary(data: ArrayBuffer) {
    if (this.destroyed || data.byteLength <= HEADER_BYTES || data.byteLength > HEADER_BYTES + MAX_FRAME_BYTES) return;
    const view = new DataView(data);
    if (view.getUint8(0) !== 1 || view.getUint32(10, false) !== data.byteLength - HEADER_BYTES) return;
    const timestamp = Number(view.getBigInt64(2, false)) * 1000;
    if (!Number.isSafeInteger(timestamp) || timestamp < 0) return;
    const nals = splitAccessUnit(new Uint8Array(data, HEADER_BYTES));
    if (!nals) return;

    for (const nal of nals) {
      const type = nal[0] & 0x1f;
      if (type === 7 || type === 8) this.parameterSet(type, nal);
    }
    const picture = nals.filter(nal => ![7, 8].includes(nal[0] & 0x1f));
    const isKeyFrame = picture.some(nal => (nal[0] & 0x1f) === 5);
    if (!picture.some(nal => [1, 5].includes(nal[0] & 0x1f))) return;

    // No pre-config frame queue: discard until valid SPS/PPS and a fresh IDR.
    if (!this.spsNal || !this.ppsNal || performance.now() < this.retryAt) return;
    if (isKeyFrame && this.lastTimestamp !== null && timestamp < this.lastTimestamp) this.retireDecoder();
    if (this.needsKeyFrame && !isKeyFrame) return;

    const bytes = picture.reduce((n, nal) => n + 4 + nal.length, 0);
    const now = performance.now();
    // decodeQueueSize excludes work already consumed by the codec. Track input
    // until output too, so a stalled GPU cannot hide an unbounded internal queue.
    if ((this.decoder?.decodeQueueSize ?? 0) >= MAX_DECODE_FRAMES ||
        this.pending.length >= MAX_DECODE_FRAMES || this.pendingBytes + bytes > MAX_DECODE_BYTES ||
        (this.pending.length > 0 && now - this.pending[0].receivedAt > MAX_DECODE_AGE_MS)) {
      this.recover();
      return; // Drop the entire reference chain; never resume on a delta frame.
    }
    if (!this.decoder && !this.createDecoder()) return;
    const codec = this.decoder!;
    try {
      if (!this.configured) {
        const [sps, pps] = [this.spsNal, this.ppsNal];
        const codecName = 'avc1.' + Array.from(sps.subarray(1, 4), n => n.toString(16).padStart(2, '0')).join('').toUpperCase();
        codec.configure({ codec: codecName, hardwareAcceleration: 'prefer-hardware',
          optimizeForLatency: true, description: buildAVCCExtradata(sps, pps) });
        this.configured = true;
      }
      // One access unit / picture per chunk; every Annex-B NAL gets an AVCC length.
      const avcc = new Uint8Array(bytes);
      let offset = 0;
      for (const nal of picture) {
        new DataView(avcc.buffer).setUint32(offset, nal.length, false);
        avcc.set(nal, offset + 4); offset += nal.length + 4;
      }
      this.pending.push({ timestamp, receivedAt: now, bytes });
      this.pendingBytes += bytes;
      codec.decode(new EncodedVideoChunk({ type: isKeyFrame ? 'key' : 'delta', timestamp, data: avcc }));
      this.needsKeyFrame = false;
      this.lastTimestamp = timestamp;
    } catch {
      this.recover();
    }
  }

  private parameterSet(type: number, nal: Uint8Array) {
    if (nal.length < (type === 7 ? 4 : 2) || nal.length > 65535) return;
    const previous = type === 7 ? this.spsNal : this.ppsNal;
    if (previous && previous.length === nal.length && previous.every((byte, i) => byte === nal[i])) return;
    if (previous) {
      this.retireDecoder();
      // A changed SPS cannot be paired with an old PPS while waiting for its mate.
      if (type === 7) this.ppsNal = null;
      this.onRecovery();
    }
    // Copy only the parameter set, not the backing buffer of a large access unit.
    if (type === 7) this.spsNal = nal.slice();
    else this.ppsNal = nal.slice();
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this.reset();
  }
}

/** MediaCodec may send several Annex-B NALs in one encoded picture. */
function splitAccessUnit(data: Uint8Array): Uint8Array[] | null {
  const nals: Uint8Array[] = [];
  let start = -1;
  for (let i = 0; i + 2 < data.length; i++) {
    if (data[i] !== 0 || data[i + 1] !== 0) continue;
    const prefix = data[i + 2] === 1 ? 3 : data[i + 2] === 0 && data[i + 3] === 1 ? 4 : 0;
    if (!prefix) continue;
    if (start >= 0) nals.push(data.subarray(start, i));
    else if (i !== 0) return null;
    start = i + prefix; i += prefix - 1;
    if (nals.length >= 128) return null;
  }
  nals.push(data.subarray(start < 0 ? 0 : start));
  if (nals.some(nal => !nal.length || (nal[0] & 0x80) !== 0 || (nal[0] & 0x1f) === 0)) return null;
  return nals;
}

function buildAVCCExtradata(sps: Uint8Array, pps: Uint8Array): Uint8Array {
  const buf = new Uint8Array(11 + sps.length + pps.length);
  let off = 0;
  buf[off++] = 1;
  buf[off++] = sps[1]; buf[off++] = sps[2]; buf[off++] = sps[3];
  buf[off++] = 0xff; buf[off++] = 0xe1;
  buf[off++] = (sps.length >> 8) & 0xff; buf[off++] = sps.length & 0xff;
  buf.set(sps, off); off += sps.length;
  buf[off++] = 1;
  buf[off++] = (pps.length >> 8) & 0xff; buf[off++] = pps.length & 0xff;
  buf.set(pps, off);
  return buf;
}
