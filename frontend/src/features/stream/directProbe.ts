/** Finite WebRTC echo canary. RTT here is neither native input ACK nor video latency. */
import { probeNetwork, type DirectProbeNetwork } from './directProbeNetwork';
import { directProbeIceConfig, type DirectProbeIceProfile } from './directProbeIce';

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
  options: { controlledStunUrl?: string } = {},
): () => void {
  const iceConfig = directProbeIceConfig(options.controlledStunUrl);
  let stopped = false;
  let result: DirectProbeResult = { state: 'gathering', samples: [], path: 'unknown', protocol: null,
    reason: null, iceProfile: iceConfig.profile };
  const peer = new RTCPeerConnection({ iceServers: iceConfig.iceServers, bundlePolicy: 'max-bundle' });
  let channel: RTCDataChannel;
  try { channel = peer.createDataChannel('sphere-probe-v1', { ordered: true }); }
  catch (error) { peer.close(); throw error; }
  let ws: WebSocket | null = null;
  let session: string | null = null;
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
    peer.onicegatheringstatechange = null; peer.onconnectionstatechange = null;
    channel.onopen = null; channel.onmessage = null; channel.onerror = null; channel.onclose = null;
    if (ws) {
      ws.onopen = null; ws.onmessage = null; ws.onerror = null; ws.onclose = null;
      if (ws.readyState === WebSocket.OPEN) ws.send('{"type":"direct_probe_close"}');
      ws.close();
    }
    channel.close(); peer.close(); pending = null;
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
  boundPhase('gathering_deadline', 8_000);
  const collectNetwork = async () => {
    if (stopped || statsInFlight || statsCalls >= 32) return;
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
    if (stopped || ws || peer.iceGatheringState !== 'complete') return;
    const sdp = peer.localDescription?.sdp;
    if (!sdp || new TextEncoder().encode(sdp).length > 32768) return stop('invalid_description');
    boundPhase('signaling_deadline', 8_000);
    result.state = 'signaling'; emit();
    ws = new WebSocket(url);
    ws.onopen = () => {
      if (stopped || !ws) return;
      ws.send(JSON.stringify({ token }));
      ws.send(JSON.stringify({ type: 'direct_probe_offer', sdp }));
    };
    ws.onmessage = event => {
      if (stopped) return;
      try {
        if (typeof event.data !== 'string' || new TextEncoder().encode(event.data).length > 36864) throw Error();
        const data = JSON.parse(event.data);
        if (session || Object.keys(data).sort().join() !== 'sdp,session_id,type'
          || data.type !== 'direct_probe_answer' || !/^[0-9a-f]{32}$/.test(data.session_id)
          || typeof data.sdp !== 'string' || new TextEncoder().encode(data.sdp).length > 32768) throw Error();
        session = data.session_id;
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
  peer.onicegatheringstatechange = gathered;
  peer.onconnectionstatechange = () => {
    if (['failed', 'disconnected', 'closed'].includes(peer.connectionState)) stop('peer_disconnected');
  };
  channel.onopen = () => {
    if (stopped || !session) return stop('missing_binding');
    clearTimeout(phaseDeadline);
    result.state = 'connected'; emit();
    interval = setInterval(() => {
      if (stopped) return;
      if (pending) return stop('echo_timeout');
      if (sequence >= 20) return stop();
      if (channel.bufferedAmount > 1024) return stop('channel_backpressure');
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
  void peer.createOffer().then(offer => { if (!stopped) return peer.setLocalDescription(offer); })
    .then(gathered).catch(() => stop('offer_failed'));
  return () => stop();
}
