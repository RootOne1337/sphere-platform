/** Local receive-stage measurements. None is capture-to-display latency. */
export interface DirectVideoStats {
  packets: number | null; bytes: number | null; decoded: number | null; dropped: number | null;
  fps: number | null; jitterBufferMs: number | null; decodeMs: number | null; networkRttMs: number | null;
  bitrateBps?: number | null; width?: number | null; height?: number | null;
}
const count = (value: unknown): number | null => typeof value === 'number' && Number.isSafeInteger(value)
  && value >= 0 ? value : null;
const finite = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value)
  && value >= 0 ? value : null;
type Previous = { id: string; at: number; decoded: number | null; bytes: number | null; delay: number | null; emitted: number | null; decode: number | null };
export class DirectVideoStatsSampler {
  private previous: Previous | null = null;
  sample(report: RTCStatsReport): DirectVideoStats {
    const result: DirectVideoStats = { packets: null, bytes: null, decoded: null, dropped: null,
      fps: null, jitterBufferMs: null, decodeMs: null, networkRttMs: null, bitrateBps: null, width: null, height: null };
    const videos: RTCInboundRtpStreamStats[] = [];
    report.forEach(row => {
      if (row.type === 'inbound-rtp' && row.kind === 'video') videos.push(row);
      if (row.type === 'transport' && row.selectedCandidatePairId) {
        const pair = report.get(row.selectedCandidatePairId);
        const seconds = pair?.type === 'candidate-pair' ? finite(pair.currentRoundTripTime) : null;
        if (seconds !== null && seconds <= 86400) result.networkRttMs = seconds * 1000;
      }
    });
    if (videos.length !== 1) { this.previous = null; return result; }
    const row = videos[0], at = finite(row.timestamp);
    result.packets = count(row.packetsReceived); result.bytes = count(row.bytesReceived);
    result.decoded = count(row.framesDecoded); result.dropped = count(row.framesDropped);
    const width = count(row.frameWidth), height = count(row.frameHeight);
    if (width !== null && height !== null && width > 0 && height > 0 && width <= 8192 && height <= 8192) {
      result.width = width; result.height = height;
    }
    const next: Previous = { id: row.id, at: at ?? 0, decoded: result.decoded, bytes: result.bytes,
      delay: finite(row.jitterBufferDelay), emitted: count(row.jitterBufferEmittedCount), decode: finite(row.totalDecodeTime) };
    const old = this.previous;
    if (at !== null && old?.id === next.id && at > old.at) {
      const mean = (total: number | null, before: number | null, n: number | null, earlier: number | null) => {
        if (total === null || before === null || n === null || earlier === null || total < before || n <= earlier) return null;
        const milliseconds = (total - before) / (n - earlier) * 1000;
        return milliseconds <= 86400000 ? milliseconds : null;
      };
      result.jitterBufferMs = mean(next.delay, old.delay, next.emitted, old.emitted);
      result.decodeMs = mean(next.decode, old.decode, next.decoded, old.decoded);
      if (next.bytes !== null && old.bytes !== null && next.bytes >= old.bytes) {
        const bitrate = (next.bytes - old.bytes) * 8000 / (at - old.at);
        if (bitrate <= 1_000_000_000) result.bitrateBps = bitrate;
      }
      if (next.decoded !== null && old.decoded !== null && next.decoded >= old.decoded) {
        const fps = (next.decoded - old.decoded) * 1000 / (at - old.at);
        if (fps <= 1024) result.fps = fps;
      }
    }
    this.previous = at === null ? null : next;
    return result;
  }
}

/** Optional browser target, never a promise of zero buffering or zero latency. */
export function preferLowVideoDelay(receiver: RTCRtpReceiver): void {
  if ('jitterBufferTarget' in receiver) {
    try { (receiver as RTCRtpReceiver & { jitterBufferTarget: number }).jitterBufferTarget = 0; }
    catch { /* Keep interoperable defaults if the browser rejects this optional setting. */ }
  }
  // Chromium releases also expose this older receive control in seconds. Some
  // builds hide jitterBufferTarget behind a runtime feature. Set independently:
  // rejection of one API must not suppress the other supported control.
  if ('playoutDelayHint' in receiver) {
    try { (receiver as RTCRtpReceiver & { playoutDelayHint: number }).playoutDelayHint = 0; }
    catch { /* A receive hint is optional and never a reason to drop the track. */ }
  }
}
