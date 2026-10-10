/** Finite WebRTC echo canary. RTT here is neither native input ACK nor video latency. */
import { probeNetwork, type DirectProbeNetwork } from './directProbeNetwork';
import { directProbeIceConfig, type DirectProbeIceProfile } from './directProbeIce';
import { parseTurnReady } from './directProbeTurn';

export interface DirectProbeResult {
  state: 'gathering' | 'signaling' | 'connecting' | 'connected' | 'finished' | 'stopped' | 'failed';
  samples: number[];
  path: 'host' | 'nat' | 'relay' | 'unknown';
  protocol: string | null;
  reason: string | null;
  iceProfile?: DirectProbeIceProfile;
  network?: DirectProbeNetwork;
  networkSampleAtMs?: number;
  networkAgeAtStopMs?: number;
  iceState?: RTCIceConnectionState;
}
export function probePath(stats: RTCStatsReport): Pick<DirectProbeResult, 'path' | 'protocol'> {
  let pair: RTCIceCandidatePairStats | undefined;
  stats.forEach(value => {
    if (value.type === 'transport' && value.selectedCandidatePairId) pair = stats.get(value.selectedCandidatePairId);
  });
  // An arbitrary succeeded pair is not evidence that the transport selected it.
  if (!pair || pair.type !== 'candidate-pair') return { path: 'unknown', protocol: null };
  const local = stats.get(pair.localCandidateId);
  const remote = stats.get(pair.remoteCandidateId);
  if (!local || !remote) return { path: 'unknown', protocol: null };
  const types = [local.candidateType, remote.candidateType];
  return { path: types.includes('relay') ? 'relay' : types.every(t => t === 'host') ? 'host'
    : types.every(t => ['host', 'srflx', 'prflx'].includes(t)) ? 'nat' : 'unknown',
  protocol: typeof local.protocol === 'string' ? local.protocol : null };
}

export function startDirectProbe(
  url: string, token: string, report: (value: DirectProbeResult) => void,
  options: { controlledStunUrl?: string; relayGrant?: boolean } = {},
): () => void {
  const iceConfig = directProbeIceConfig(options.controlledStunUrl);
  let stopped = false;
  if (options.relayGrant && options.controlledStunUrl) throw new Error('conflicting_ice_profiles');
  let result: DirectProbeResult = { state: options.relayGrant ? 'signaling' : 'gathering', samples: [], path: 'unknown', protocol: null,
    reason: null, iceProfile: options.relayGrant ? 'turn' : iceConfig.profile };
  let peer: RTCPeerConnection | null = null;
  let channel: RTCDataChannel | null = null;
  let ws: WebSocket | null = null;
  let session: string | null = null;
  let answered = false, offered = false;
  let sequence = 0;
  let pending: { sequence: number; sent: number } | null = null;
  let interval: ReturnType<typeof setInterval> | undefined;
  let networkInterval: ReturnType<typeof setInterval> | undefined;
  let phaseDeadline: ReturnType<typeof setTimeout> | undefined;
  let statsInFlight = false, statsCalls = 0;
  const startedAt = performance.now();
  const emit = () => report({ ...result, samples: [...result.samples] });
  const stop = (reason: string | null = null) => {
    if (stopped) return;
    stopped = true;
    clearTimeout(deadline); clearTimeout(phaseDeadline);
    if (interval) clearInterval(interval);
    if (networkInterval) clearInterval(networkInterval);
    if (peer) { peer.onicegatheringstatechange = null; peer.onconnectionstatechange = null; }
    if (channel) { channel.onopen = null; channel.onmessage = null; channel.onerror = null; channel.onclose = null; }
    if (ws) {
      ws.onopen = null; ws.onmessage = null; ws.onerror = null; ws.onclose = null;
      try { if (ws.readyState === WebSocket.OPEN) ws.send('{"type":"direct_probe_close"}'); }
      catch { /* Signaling may disappear during cleanup; native TTL remains bounded. */ }
      try { ws.close(); } catch { /* Close the local native resources independently. */ }
    }
    try { channel?.close(); } catch { /* Peer cleanup must still run. */ }
    try { peer?.close(); } catch { /* Timers and callbacks have already been retired. */ }
    pending = null;
    result = { ...result, state: reason ? 'failed' : result.samples.length === 20 ? 'finished' : 'stopped', reason,
      networkAgeAtStopMs: result.networkSampleAtMs === undefined ? undefined :
        Math.max(0, performance.now() - startedAt - result.networkSampleAtMs) }; emit();
  };
  const deadline = setTimeout(() => stop('probe_deadline'), 30_000);
  const boundPhase = (reason: string, milliseconds: number) => {
    clearTimeout(phaseDeadline);
    phaseDeadline = setTimeout(() => stop(reason), milliseconds);
  };
  // A slow gathering/signaling phase must not masquerade as failed ICE connectivity.
  // The 30-second overall lease is never extended by a phase transition.
  boundPhase(options.relayGrant ? 'signaling_deadline' : 'gathering_deadline', 8_000);
  const collectNetwork = async () => {
    if (stopped || !peer || statsInFlight || statsCalls >= 32) return;
    statsInFlight = true; statsCalls++;
    const iceState = peer.iceConnectionState, sampledAt = performance.now() - startedAt;
    try {
      const stats = await peer.getStats();
      if (!stopped) {
        result = { ...result, ...probePath(stats), network: probeNetwork(stats),
          networkSampleAtMs: sampledAt, iceState }; emit();
      }
    } catch { /* Missing stats retain the previous sample or unknown. */ }
    finally { statsInFlight = false; }
  };
  const gathered = () => {
    if (stopped || offered || !peer || peer.iceGatheringState !== 'complete') return;
    const sdp = peer.localDescription?.sdp;
    if (!sdp || new TextEncoder().encode(sdp).length > 32768) return stop('invalid_description');
    boundPhase('signaling_deadline', 8_000);
    result.state = 'signaling'; emit();
    offered = true;
    if (options.relayGrant) {
      if (!ws || ws.readyState !== WebSocket.OPEN || !session) return stop('missing_binding');
      try { ws.send(JSON.stringify({ type: 'direct_probe_offer', sdp })); }
      catch { stop('signaling_unavailable'); }
    } else openSignaling(sdp);
  };
  const openSignaling = (sdp?: string) => {
    ws = new WebSocket(url);
    ws.onopen = () => {
      if (stopped || !ws) return;
      try {
        ws.send(JSON.stringify(options.relayGrant ? { token, protocol: 'sphere-probe-v2' } : { token }));
        if (sdp) ws.send(JSON.stringify({ type: 'direct_probe_offer', sdp }));
      } catch { stop('signaling_unavailable'); }
    };
    ws.onmessage = event => {
      if (stopped) return;
      try {
        if (typeof event.data !== 'string' || new TextEncoder().encode(event.data).length > 36864) throw Error();
        const data = JSON.parse(event.data);
        if (options.relayGrant && !session) {
          const ready = parseTurnReady(data);
          if (!ready) return stop('invalid_ice_grant');
          session = ready.session;
          createPeer(ready.configuration);
          return;
        }
        if (answered || !peer || Object.keys(data).sort().join() !== 'sdp,session_id,type'
          || data.type !== 'direct_probe_answer' || !/^[0-9a-f]{32}$/.test(data.session_id)
          || session !== null && data.session_id !== session
          || typeof data.sdp !== 'string' || new TextEncoder().encode(data.sdp).length > 32768) throw Error();
        session = data.session_id;
        answered = true;
        boundPhase('connection_deadline', 12_000);
        void peer.setRemoteDescription({ type: 'answer', sdp: data.sdp }).then(() => {
          if (stopped) return;
          if (result.state === 'signaling') { result.state = 'connecting'; emit(); }
          collectNetwork(); networkInterval = setInterval(collectNetwork, 1000);
        }).catch(() => stop('invalid_answer'));
      } catch { stop('invalid_signal'); }
    };
    ws.onerror = () => stop('signaling_unavailable');
    ws.onclose = () => stop('signaling_closed');
  };
  const createPeer = (configuration: RTCConfiguration) => {
    if (stopped || peer) return;
    boundPhase('gathering_deadline', 8_000);
    result.state = 'gathering';
    try { peer = new RTCPeerConnection(configuration); }
    catch { stop('webrtc_unavailable'); return; }
    try { channel = peer.createDataChannel('sphere-probe-v1', { ordered: true }); }
    catch { stop('webrtc_unavailable'); return; }
    peer.onicegatheringstatechange = gathered;
    peer.onconnectionstatechange = () => {
      if (peer && ['failed', 'disconnected', 'closed'].includes(peer.connectionState)) stop('peer_disconnected');
    };
    channel.onopen = () => {
      if (stopped || !session) return stop('missing_binding');
      clearTimeout(phaseDeadline);
      result.state = 'connected'; emit();
      interval = setInterval(() => {
        if (stopped) return;
        if (pending) return stop('echo_timeout');
        if (sequence >= 20) return stop();
        if (!channel || channel.bufferedAmount > 1024) return stop('channel_backpressure');
        pending = { sequence: ++sequence, sent: performance.now() };
        try { channel.send(`SP1 ${session} ${sequence}`); } catch { stop('echo_send_failed'); }
      }, 1000);
    };
    channel.onmessage = event => {
      if (stopped) return;
      if (!pending || event.data !== `SP1 ${session} ${pending.sequence}`) return stop('invalid_echo');
      result.samples.push(performance.now() - pending.sent); pending = null; emit();
      collectNetwork();
    };
    channel.onerror = () => stop('channel_failed');
    channel.onclose = () => stop('channel_closed');
    emit();
    void peer.createOffer().then(offer => { if (!stopped && peer) return peer.setLocalDescription(offer); })
      .then(gathered).catch(() => stop('offer_failed'));
  };
  emit();
  try {
    if (options.relayGrant) openSignaling();
    else createPeer({ iceServers: iceConfig.iceServers, bundlePolicy: 'max-bundle' });
  } catch { stop('webrtc_unavailable'); }
  return () => stop();
}
