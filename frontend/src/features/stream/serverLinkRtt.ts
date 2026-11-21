/** Viewer ↔ server WebSocket echo. It never measures Android or video latency. */
export type ServerLinkSample = { rttMs: number; ageMs: number };
const MAX_SEQUENCE = 2_147_483_647;
const INTERVAL_MS = 5_000;
const STALE_MS = 15_000;

export class ServerLinkRtt {
  private sequence = 0;
  private pending: { sequence: number; at: number } | null = null;
  private measured: { rttMs: number; at: number } | null = null;
  private lastSent = -Infinity;
  private lastTick: number | null = null;
  private stopped = false;
  constructor(private socket: Pick<WebSocket, 'readyState' | 'bufferedAmount' | 'send'>,
    private clock = () => performance.now()) {}

  /** Reuses the viewer watchdog; no additional timer or retry queue. */
  tick(visible: boolean): void {
    if (this.stopped) return;
    const now = this.clock();
    if (!Number.isFinite(now)) return;
    if (this.lastTick !== null && (now < this.lastTick || now - this.lastTick > STALE_MS)) {
      this.pending = null; this.measured = null;
    }
    this.lastTick = now;
    if (!visible || this.socket.readyState !== 1 || this.socket.bufferedAmount > 65_536) {
      this.pending = null; this.measured = null; return;
    }
    if (this.pending && now - this.pending.at >= INTERVAL_MS) {
      this.pending = null; this.measured = null;
    }
    if (this.pending || now - this.lastSent < INTERVAL_MS || this.sequence >= MAX_SEQUENCE) return;
    const sequence = ++this.sequence;
    this.pending = { sequence, at: now };
    this.lastSent = now;
    try { this.socket.send(JSON.stringify({ type: 'stream_link_probe', sequence })); }
    catch { this.pending = null; this.measured = null; }
  }

  receive(value: unknown): void {
    if (this.stopped || !value || typeof value !== 'object') return;
    const message = value as Record<string, unknown>;
    if (message.type !== 'stream_link_result' || !this.pending
      || message.sequence !== this.pending.sequence || !Number.isSafeInteger(message.sequence)) return;
    const now = this.clock(), rttMs = now - this.pending.at;
    this.pending = null;
    // A suspended/background page cannot turn scheduling delay into network RTT.
    this.measured = Number.isFinite(rttMs) && rttMs >= 0 && rttMs < INTERVAL_MS
      ? { rttMs, at: now } : null;
  }

  sample(): ServerLinkSample | null {
    if (this.stopped || this.socket.readyState !== 1 || !this.measured) return null;
    const ageMs = this.clock() - this.measured.at;
    return Number.isFinite(ageMs) && ageMs >= 0 && ageMs < STALE_MS
      ? { rttMs: this.measured.rttMs, ageMs } : null;
  }
  stop(): void { this.stopped = true; this.pending = null; this.measured = null; }
}
