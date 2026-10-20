/** A shared, bounded local ICE gather detects silent VPN/interface changes.
 * No signaling, remote peer or input authority. Addresses stay in memory only.
 */
export function numericIceTopology(candidates: readonly RTCIceCandidateInit[]): string | null {
  if (candidates.length > 64) return null;
  const entries = new Set<string>();
  for (const item of candidates) {
    const parts = item.candidate?.split(/\s+/);
    if (!parts || parts.length < 8 || parts[2]?.toLowerCase() !== 'udp'
      || parts[6] !== 'typ' || !['host', 'srflx'].includes(parts[7])) continue;
    const address = parts[4].toLowerCase();
    const ipv4 = address.split('.');
    const valid4 = ipv4.length === 4 && ipv4.every(v => /^(0|[1-9]\d{0,2})$/.test(v) && +v <= 255);
    let valid6 = false;
    if (address.includes(':') && /^[a-f0-9:]{2,64}$/.test(address)) {
      try { valid6 = new URL(`http://[${address}]/`).hostname.startsWith('['); } catch { /* Unknown. */ }
    }
    // mDNS names can rotate between peers. They cannot identify an interface change.
    if (valid4 || valid6) entries.add(`${parts[7]}:${address}`);
  }
  return entries.size ? [...entries].sort().join('|') : null;
}

export async function gatherLocalIceTopology(iceServers: RTCIceServer[], signal: AbortSignal): Promise<string | null> {
  if (signal.aborted) return null;
  let peer: RTCPeerConnection | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let abort: (() => void) | undefined;
  try {
    peer = new RTCPeerConnection({ iceServers, iceCandidatePoolSize: 0 });
    peer.createDataChannel('sphere-local-route-check');
    const candidates: RTCIceCandidateInit[] = [];
    return await new Promise<string | null>(resolve => {
      let ended = false;
      const finish = (complete: boolean) => {
        if (ended) return;
        ended = true;
        resolve(complete && !signal.aborted ? numericIceTopology(candidates) : null);
      };
      abort = () => finish(false);
      signal.addEventListener('abort', abort, { once: true });
      timer = setTimeout(() => finish(false), 3000);
      peer!.onicecandidate = event => {
        if (ended) return;
        if (!event.candidate) { finish(true); return; }
        if (candidates.length >= 64) { finish(false); return; }
        candidates.push(event.candidate.toJSON());
      };
      void peer!.createOffer().then(offer => {
        if (!ended) return peer!.setLocalDescription(offer);
      }).catch(() => finish(false));
    });
  } catch { return null; }
  finally {
    clearTimeout(timer);
    if (abort) signal.removeEventListener('abort', abort);
    if (peer) { peer.onicecandidate = null; peer.close(); }
  }
}

type Listener = { active: () => boolean; changed: () => void };
type Sampler = typeof gatherLocalIceTopology;

/** One observer per ICE profile, shared by all players/video-wall tiles. */
export class NetworkRouteWatch {
  private listeners = new Set<Listener>();
  private baseline: string | null = null;
  private suspected: string | null = null;
  private pending: AbortController | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private periodic: ReturnType<typeof setInterval>;
  private lastStarted = -Infinity;
  private retired = false;
  constructor(private servers: RTCIceServer[], private sample: Sampler = gatherLocalIceTopology) {
    this.periodic = setInterval(() => this.check(), 20000);
  }
  add(listener: Listener) { this.listeners.add(listener); }
  remove(listener: Listener) { this.listeners.delete(listener); return this.listeners.size; }
  reset() {
    this.baseline = this.suspected = null; this.lastStarted = -Infinity;
    this.pending?.abort(); this.pending = null;
    clearTimeout(this.timer); this.timer = undefined;
  }
  check() {
    if (this.retired || this.pending || this.timer || ![...this.listeners].some(v => v.active())) return;
    const wait = Math.max(200, 5000 - (performance.now() - this.lastStarted));
    this.timer = setTimeout(() => { this.timer = undefined; void this.inspect(); }, wait);
  }
  private async inspect() {
    if (this.retired || ![...this.listeners].some(v => v.active())) return;
    const controller = this.pending = new AbortController();
    this.lastStarted = performance.now();
    let confirm = false;
    try {
      const topology = await this.sample(this.servers, controller.signal);
      if (this.retired || controller.signal.aborted || !topology) return;
      const changed = this.baseline !== null && this.baseline !== topology;
      if (changed && this.suspected !== topology) {
        // A transient STUN/CGNAT result must not reset twenty working streams.
        // Confirm the same changed topology in a second bounded gather.
        this.suspected = topology; confirm = true;
      } else {
        this.baseline = topology; this.suspected = null;
        if (changed) for (const listener of [...this.listeners]) if (listener.active()) listener.changed();
      }
    } catch { /* A failed local gather cannot tear down working video. */ }
    finally {
      if (this.pending === controller) this.pending = null;
      if (confirm && !controller.signal.aborted) this.check();
    }
  }
  close() {
    this.retired = true;
    clearInterval(this.periodic); clearTimeout(this.timer);
    this.pending?.abort(); this.pending = null; this.listeners.clear(); this.baseline = this.suspected = null;
  }
}

const shared = new Map<string, NetworkRouteWatch>();
export function watchNetworkRoute(iceServers: RTCIceServer[], listener: Listener) {
  const key = JSON.stringify(iceServers);
  let watch = shared.get(key);
  if (!watch) { watch = new NetworkRouteWatch(iceServers); shared.set(key, watch); }
  const owned = watch;
  owned.add(listener);
  return {
    check: () => owned.check(), reset: () => owned.reset(),
    close: () => { if (!owned.remove(listener)) { owned.close(); if (shared.get(key) === owned) shared.delete(key); } },
  };
}
