export type ControlLatencySnapshot = { samples: number; p95Ms: number; maxMs: number };

/** Last 128 acknowledged actions. Idle heartbeats never hide a click burst. */
export class ControlLatencyWindow {
  private readonly values = new Float64Array(128);
  private next = 0;
  private size = 0;

  record(action: number, milliseconds: number): void {
    if (action === 4 || !Number.isFinite(milliseconds) || milliseconds < 0 || milliseconds > 10_000) return;
    this.values[this.next] = milliseconds;
    this.next = (this.next + 1) % this.values.length;
    this.size = Math.min(this.size + 1, this.values.length);
  }

  snapshot(): ControlLatencySnapshot | null {
    if (!this.size) return null;
    const values = this.values.slice(0, this.size).sort();
    return { samples: this.size, p95Ms: values[Math.ceil(this.size * .95) - 1], maxMs: values[this.size - 1] };
  }
}
