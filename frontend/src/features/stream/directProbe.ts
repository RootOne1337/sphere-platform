/** Finite WebRTC echo canary. RTT here is neither native input ACK nor video latency. */
import { probeNetwork, type DirectProbeNetwork } from './directProbeNetwork';
import { directProbeIceConfig, type DirectProbeIceProfile } from './directProbeIce';
import { parseTurnReady } from './directProbeTurn';
import { parseVideoBinding, readonlyVideoSdp, type DirectVideoBinding } from './directVideoProtocol';
import { DirectVideoStatsSampler, preferLowVideoDelay, type DirectVideoStats } from './directVideoStats';
import type { DirectControlEndpoint } from './directPointerTransport';
import { h264ReceiverOffer } from './h264ReceiverOffer';

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
  videoBinding?: DirectVideoBinding;
  videoStats?: DirectVideoStats;
  /** Exact signaling nonce; never included in public diagnostic scalar samples. */
  session?: string;
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
  return startDirectSession(url, token, report, options);
}

export function startDirectVideoProbe(
  url: string, token: string, report: (value: DirectProbeResult) => void,
  options: { controlledStunUrl?: string; relayGrant?: boolean; historySession?: string; onTrack: (track: MediaStreamTrack) => void },
): () => void {
  return startDirectSession(url, token, report, options, options.onTrack);
}

/** Primary video has its own renewable grant; the finite diagnostic remains unchanged. */
export function startDirectVideoSession(
  url: string, token: string, report: (value: DirectProbeResult) => void,
  options: { controlledStunUrl?: string; onTrack: (track: MediaStreamTrack) => void;
    receiverSize?: { width: number; height: number };
    historySession?: string; controlSession?: string; onControlChannel?: (channel: DirectControlEndpoint | null) => void;
    /** Actual recent presentation, independently bounded by the renderer watchdog. */
    hasRecentVideoFrame?: () => boolean },
): () => void {
  return startDirectSession(url, token, report, options, options.onTrack, true);
}

function startDirectSession(
  url: string, token: string, report: (value: DirectProbeResult) => void,
  options: { controlledStunUrl?: string; relayGrant?: boolean; controlSession?: string; historySession?: string;
    onControlChannel?: (channel: DirectControlEndpoint | null) => void;
    receiverSize?: { width: number; height: number };
    hasRecentVideoFrame?: () => boolean }, onVideoTrack?: (track: MediaStreamTrack) => void, live = false,
): () => void {
  const video = !!onVideoTrack;
  if (options.historySession !== undefined && (!video || !/^[0-9a-f]{16}$/.test(options.historySession)))
    throw new Error('invalid_history_session');
  const iceConfig = directProbeIceConfig(options.controlledStunUrl);
  let stopped = false;
  if (options.relayGrant && options.controlledStunUrl) throw new Error('conflicting_ice_profiles');
  let result: DirectProbeResult = { state: options.relayGrant ? 'signaling' : 'gathering', samples: [], path: 'unknown', protocol: null,
    reason: null, iceProfile: options.relayGrant ? 'turn' : iceConfig.profile };
  let peer: RTCPeerConnection | null = null;
  let channel: RTCDataChannel | null = null;
  let controlChannel: RTCDataChannel | null = null;
  let controlListener: ((message: unknown) => void) | null = null;
  let ws: WebSocket | null = null;
  let videoTrack: MediaStreamTrack | null = null;
  let session: string | null = null;
  let answered = false, offered = false;
  let sequence = 0;
  let pending: { sequence: number; sent: number } | null = null;
  let interval: ReturnType<typeof setInterval> | undefined;
  let networkInterval: ReturnType<typeof setInterval> | undefined;
  let renewalInterval: ReturnType<typeof setInterval> | undefined;
  let phaseDeadline: ReturnType<typeof setTimeout> | undefined;
  let disconnectDeadline: ReturnType<typeof setTimeout> | undefined;
  let statsInFlight = false, statsCalls = 0;
  let renewal = 0;
  const videoStats = new DirectVideoStatsSampler();
  const startedAt = performance.now();
  const emit = () => report({ ...result, samples: [...result.samples] });
  const stop = (reason: string | null = null) => {
    if (stopped) return;
    stopped = true;
    clearTimeout(deadline); clearTimeout(phaseDeadline); clearTimeout(disconnectDeadline);
    if (interval) clearInterval(interval);
    if (networkInterval) clearInterval(networkInterval);
    if (renewalInterval) clearInterval(renewalInterval);
    if (peer) { peer.onicegatheringstatechange = null; peer.onconnectionstatechange = null; peer.ontrack = null; }
    if (videoTrack) { videoTrack.onended = null; try { videoTrack.stop(); } catch { /* Independent native cleanup. */ } }
    if (channel) { channel.onopen = null; channel.onmessage = null; channel.onerror = null; channel.onclose = null; }
    if (controlChannel) {
      controlChannel.onopen = null; controlChannel.onmessage = null; controlChannel.onerror = null; controlChannel.onclose = null;
      options.onControlChannel?.(null); controlListener = null;
    }
    if (ws) {
      ws.onopen = null; ws.onmessage = null; ws.onerror = null; ws.onclose = null;
      try { if (ws.readyState === WebSocket.OPEN) ws.send('{"type":"direct_probe_close"}'); }
      catch { /* Signaling may disappear during cleanup; native TTL remains bounded. */ }
      try { ws.close(); } catch { /* Close the local native resources independently. */ }
    }
    try { channel?.close(); } catch { /* Peer cleanup must still run. */ }
    try { controlChannel?.close(); } catch { /* Independent control cleanup. */ }
    try { peer?.close(); } catch { /* Timers and callbacks have already been retired. */ }
    pending = null;
    result = { ...result, state: reason ? 'failed' : !live && result.samples.length === 20 ? 'finished' : 'stopped', reason,
      networkAgeAtStopMs: result.networkSampleAtMs === undefined ? undefined :
        Math.max(0, performance.now() - startedAt - result.networkSampleAtMs) }; emit();
  };
  let deadline = setTimeout(() => stop('probe_deadline'), 30_000);
  const boundPhase = (reason: string, milliseconds: number) => {
    clearTimeout(phaseDeadline);
    phaseDeadline = setTimeout(() => stop(reason), milliseconds);
  };
  // A slow gathering/signaling phase must not masquerade as failed ICE connectivity.
  // The 30-second overall lease is never extended by a phase transition.
  boundPhase(options.relayGrant ? 'signaling_deadline' : 'gathering_deadline', 8_000);
  const collectNetwork = async () => {
    if (stopped || !peer || statsInFlight || !live && statsCalls >= 32) return;
    statsInFlight = true; statsCalls++;
    const iceState = peer.iceConnectionState, sampledAt = performance.now() - startedAt;
    try {
      const stats = await peer.getStats();
      if (!stopped) {
        result = { ...result, ...probePath(stats), network: probeNetwork(stats), ...(live ? { videoStats: videoStats.sample(stats) } : {}),
          networkSampleAtMs: sampledAt, iceState }; emit();
      }
    } catch { /* Missing stats retain the previous sample or unknown. */ }
    finally { statsInFlight = false; }
  };
  const gathered = () => {
    if (stopped || offered || !peer || peer.iceGatheringState !== 'complete') return;
    const sdp = peer.localDescription?.sdp;
    if (!sdp || new TextEncoder().encode(sdp).length > 32768) return stop('invalid_description');
    if (video && !readonlyVideoSdp(sdp, true)) return stop('invalid_description');
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
        ws.send(JSON.stringify(video ? { token, protocol: live ? 'sphere-video-v1' : 'sphere-video-probe-v1', ...(options.relayGrant ? { relay: true } : {}),
          ...(live && options.controlSession ? { control_session: options.controlSession } : {}),
          ...(options.historySession ? { history_session: options.historySession } : {}) }
          : options.relayGrant ? { token, protocol: 'sphere-probe-v2' } : { token }));
        if (sdp) ws.send(JSON.stringify({ type: 'direct_probe_offer', sdp }));
      } catch { stop('signaling_unavailable'); }
    };
    ws.onmessage = event => {
      if (stopped) return;
      try {
        if (typeof event.data !== 'string' || new TextEncoder().encode(event.data).length > 36864) throw Error();
        const data = JSON.parse(event.data);
        if (options.relayGrant && !session) {
          const ready = parseTurnReady(data, video ? 'sphere-video-probe-v1' : 'sphere-probe-v2');
          if (!ready) return stop('invalid_ice_grant');
          session = ready.session;
          createPeer(ready.configuration);
          return;
        }
        if (answered || !peer || Object.keys(data).sort().join() !== 'sdp,session_id,type'
          || data.type !== 'direct_probe_answer' || !/^[0-9a-f]{32}$/.test(data.session_id)
          || session !== null && data.session_id !== session
          || typeof data.sdp !== 'string' || new TextEncoder().encode(data.sdp).length > 32768) throw Error();
        if (video && !readonlyVideoSdp(data.sdp, false)) return stop('invalid_answer');
        session = data.session_id;
        result.session = session ?? undefined;
        answered = true;
        boundPhase('connection_deadline', 12_000);
        void peer.setRemoteDescription({ type: 'answer', sdp: data.sdp }).then(() => {
          if (stopped) return;
          if (result.state === 'signaling') { result.state = 'connecting'; emit(); }
          collectNetwork(); networkInterval = setInterval(collectNetwork, live ? 5000 : 1000);
        }).catch(() => stop('invalid_answer'));
      } catch { stop('invalid_signal'); }
    };
    ws.onerror = () => stop('signaling_unavailable');
    ws.onclose = event => stop(live && event.code === 4003 ? 'video_access_rejected' : 'signaling_closed');
  };
  const createPeer = (configuration: RTCConfiguration) => {
    if (stopped || peer) return;
    boundPhase('gathering_deadline', 8_000);
    result.state = 'gathering';
    try { peer = new RTCPeerConnection(configuration); }
    catch { stop('webrtc_unavailable'); return; }
    try {
      channel = peer.createDataChannel(live ? 'sphere-video-v1' : video ? 'sphere-video-probe-v1' : 'sphere-probe-v1', { ordered: true });
      if (live && options.controlSession && options.onControlChannel) {
        if (!/^[0-9a-f]{16}$/.test(options.controlSession)) throw Error('invalid_control_session');
        const direct = peer.createDataChannel('sphere-control-v1', { ordered: true });
        controlChannel = direct;
        let retired = false;
        const retire = (reason: string) => {
          if (retired) return;
          retired = true; controlListener = null; options.onControlChannel?.(null);
          // A closed SCTP channel cannot be reopened. Retire this exact media
          // grant so LiveDirectVideo negotiates a fresh peer/channel and the
          // server/native owner is released before another input OPEN.
          // No queued touch is sent on the replacement transport.
          stop(reason);
        };
        direct.onopen = () => {
          if (stopped || retired) return;
          if (!session) return retire('missing_binding');
          options.onControlChannel?.({ session,
            get readyState() { return !stopped && !retired && direct.readyState === 'open' ? 1 : 0; },
            get bufferedAmount() { return direct.bufferedAmount; },
            capture: () => result.videoBinding ?? null,
            send: data => { if (retired || stopped || direct.readyState !== 'open') throw Error('direct_input_closed'); direct.send(data); },
            listen: listener => {
              if (stopped || retired) return () => {};
              controlListener = listener;
              return () => { if (controlListener === listener) controlListener = null; };
            },
          });
        };
        direct.onmessage = event => {
          if (stopped || retired) return;
          if (typeof event.data !== 'string' || new TextEncoder().encode(event.data).length > 1024) {
            retire('invalid_control_message'); return;
          }
          try { controlListener?.(JSON.parse(event.data)); } catch { retire('invalid_control_message'); }
        };
        direct.onerror = () => retire('control_channel_failed');
        direct.onclose = () => retire('control_channel_closed');
      }
      if (video) {
        peer.addTransceiver('video', { direction: 'recvonly' });
        peer.ontrack = event => {
          if (stopped) { event.track.stop(); return; }
          if (videoTrack || event.track.kind !== 'video') { event.track.stop(); return stop('invalid_video_track'); }
          videoTrack = event.track;
          if (live && event.receiver) preferLowVideoDelay(event.receiver);
          videoTrack.onended = () => stop('video_track_ended');
          try { onVideoTrack?.(videoTrack); } catch { stop('video_renderer_failed'); }
        };
      }
    }
    catch { stop('webrtc_unavailable'); return; }
    peer.onicegatheringstatechange = gathered;
    peer.onconnectionstatechange = () => {
      if (!peer || stopped) return;
      if (['failed', 'closed'].includes(peer.connectionState)) return stop('peer_disconnected');
      if (peer.connectionState === 'connected') {
        clearTimeout(disconnectDeadline); disconnectDeadline = undefined;
        void collectNetwork();
      } else if (peer.connectionState === 'disconnected') {
        // ICE can recover a brief connectivity loss on the same encrypted
        // transport. Input retains its independent native/server deadlines;
        // no media grant is renewed
        // past its own authorization/lease by this short recovery window.
        if (!live || result.state !== 'connected') return stop('peer_disconnected');
        disconnectDeadline ??= setTimeout(() => stop('peer_disconnected'), 3000);
      }
    };
    channel.onopen = () => {
      if (stopped || !session) return stop('missing_binding');
      clearTimeout(phaseDeadline);
      result.state = 'connected'; emit();
      if (live) {
        clearTimeout(deadline);
        deadline = setTimeout(() => stop('session_lifetime'), 8 * 3600_000);
        renewalInterval = setInterval(() => {
          if (stopped) return;
          if (!ws || ws.readyState !== WebSocket.OPEN || ws.bufferedAmount > 1024) return stop('signaling_unavailable');
          try { ws.send(JSON.stringify({ type: 'direct_video_keepalive', sequence: ++renewal })); }
          catch { stop('signaling_unavailable'); }
        }, 5000);
      }
      interval = setInterval(() => {
        if (stopped) return;
        if (pending) {
          // Echo measures SCTP turnaround, not video health. A delayed reply
          // must not discard a peer that is still presenting fresh video.
          // Keep the one outstanding packet: no queue, retransmission, invented
          // RTT or relaxation of input/authorization/ICE/renderer deadlines.
          let presenting = false;
          try { presenting = live && options.hasRecentVideoFrame?.() === true; } catch { /* Unknown is not progress. */ }
          if (presenting && peer?.connectionState === 'connected') return;
          return stop('echo_timeout');
        }
        if (!live && sequence >= 20) return stop();
        if (!channel || channel.bufferedAmount > 1024) return stop('channel_backpressure');
        pending = { sequence: ++sequence, sent: performance.now() };
        try { channel.send(`${live ? 'SL1' : 'SP1'} ${session} ${sequence}`); } catch { stop('echo_send_failed'); }
      }, live ? 5000 : 1000);
    };
    channel.onmessage = event => {
      if (stopped) return;
      if (video && !result.videoBinding) {
        const binding = session ? parseVideoBinding(event.data, session) : null;
        if (!binding) return stop('invalid_video_binding');
        result = { ...result, videoBinding: binding }; emit(); return;
      }
      if (!pending || event.data !== `${live ? 'SL1' : 'SP1'} ${session} ${pending.sequence}`) return stop('invalid_echo');
      result.samples.push(performance.now() - pending.sent);
      if (result.samples.length > 20) result.samples.shift();
      pending = null; emit();
      // Live video has one periodic sampler. Sampling again after its echo can
      // replace a useful frame interval with zero deltas from the same instant.
      if (!live) void collectNetwork();
    };
    channel.onerror = () => stop('channel_failed');
    channel.onclose = () => stop('channel_closed');
    emit();
    void peer.createOffer().then(offer => {
      if (live && video && options.receiverSize) return h264ReceiverOffer(offer, options.receiverSize)
        .then(prepared => { if (!stopped && peer) return peer.setLocalDescription(prepared); });
      if (!stopped && peer) return peer.setLocalDescription(offer);
    })
      .then(gathered).catch(() => stop('offer_failed'));
  };
  emit();
  try {
    if (options.relayGrant) openSignaling();
    else createPeer({ iceServers: iceConfig.iceServers, bundlePolicy: 'max-bundle' });
  } catch { stop('webrtc_unavailable'); }
  return () => stop();
}
