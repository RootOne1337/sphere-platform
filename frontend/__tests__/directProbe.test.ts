import { probePath, startDirectProbe, startDirectVideoProbe, startDirectVideoSession, type DirectProbeResult } from '@/src/features/stream/directProbe';
import { parseVideoBinding, readonlyVideoSdp } from '@/src/features/stream/directVideoProtocol';
import { TextEncoder } from 'util';

class FakeChannel {
  bufferedAmount = 0;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  send = jest.fn(); close = jest.fn();
}
class FakePeer {
  static latest: FakePeer;
  static initialGatheringState = 'complete';
  static constructions = 0;
  static initialSdp = 'v=0\r\n';
  channel = new FakeChannel();
  iceGatheringState = FakePeer.initialGatheringState; connectionState = 'connected'; iceConnectionState = 'checking';
  localDescription = { sdp: FakePeer.initialSdp };
  onicegatheringstatechange: (() => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  ontrack: ((event: { track: MediaStreamTrack }) => void) | null = null;
  constructor(readonly configuration: RTCConfiguration) { FakePeer.latest = this; FakePeer.constructions++; }
  createDataChannel = jest.fn(() => this.channel);
  addTransceiver = jest.fn();
  createOffer = jest.fn(async () => ({ type: 'offer', sdp: 'v=0\r\n' }));
  setLocalDescription = jest.fn(async () => {});
  setRemoteDescription = jest.fn(async () => {});
  getStats = jest.fn(async () => new Map());
  close = jest.fn();
}
class FakeSocket {
  static OPEN = 1; static latest: FakeSocket;
  readyState = 1;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: unknown }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor() { FakeSocket.latest = this; }
  send = jest.fn(); close = jest.fn();
}
const flush = async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); };
const sid = 'a'.repeat(32);
async function connected() {
  const reports: DirectProbeResult[] = [];
  const stop = startDirectProbe('wss://same-origin/ws/direct-probe/device', 'access', value => reports.push(value));
  await flush();
  const ws = FakeSocket.latest, peer = FakePeer.latest;
  ws.onopen?.();
  ws.onmessage?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: sid, sdp: 'v=0\r\n' }) });
  await flush(); peer.channel.onopen?.();
  return { reports, stop, ws, peer };
}
const relayReady = () => ({ type: 'direct_probe_ready', protocol: 'sphere-probe-v2', session_id: sid,
  ice: { urls: ['turn:relay.example.test:3478?transport=tcp'], username: `1791605120:${sid}:browser`,
    credential: 'A'.repeat(27) + '=', ttl_ms: 120000, policy: 'relay' } });
beforeEach(() => {
  jest.useFakeTimers();
  FakePeer.initialGatheringState = 'complete'; FakePeer.constructions = 0;
  FakePeer.initialSdp = 'v=0\r\n';
  Object.defineProperty(globalThis, 'RTCPeerConnection', { configurable: true, value: FakePeer });
  Object.defineProperty(globalThis, 'WebSocket', { configurable: true, value: FakeSocket });
  if (!globalThis.TextEncoder) Object.defineProperty(globalThis, 'TextEncoder', { configurable: true, value: TextEncoder });
});
afterEach(() => { jest.useRealTimers(); });

const appSdp = 'v=0\r\na=fingerprint:sha-256 ' + Array(32).fill('AB').join(':')
  + '\r\nm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n';
const videoSdp = appSdp + 'm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=recvonly\r\na=rtpmap:96 H264/90000\r\n';
const epoch = '12345678-1234-4234-8234-123456789abc';
async function videoConnected(live = false) {
  FakePeer.initialSdp = videoSdp;
  const reports: DirectProbeResult[] = [], onTrack = jest.fn();
  const start = live ? startDirectVideoSession : startDirectVideoProbe;
  const stop = start('wss://same-origin/ws/direct-probe/device', 'access', r => reports.push(r), { onTrack });
  await flush();
  const ws = FakeSocket.latest, peer = FakePeer.latest;
  ws.onopen?.();
  ws.onmessage?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: sid, sdp: videoSdp.replace('recvonly', 'sendonly') }) });
  await flush(); peer.channel.onopen?.();
  return { reports, stop, onTrack, ws, peer };
}

test('primary video negotiates a separate grant and renews beyond the finite diagnostic lifetime', async () => {
  const { stop, peer, ws, reports } = await videoConnected(true);
  expect(JSON.parse(ws.send.mock.calls[0][0])).toEqual({ token: 'access', protocol: 'sphere-video-v1' });
  expect(peer.createDataChannel).toHaveBeenCalledWith('sphere-video-v1', { ordered: true });
  peer.channel.onmessage?.({ data: `SV1 ${sid} ${epoch} 960 540` });
  for (let sequence = 1; sequence <= 24; sequence++) {
    jest.advanceTimersByTime(5000);
    expect(peer.channel.send).toHaveBeenLastCalledWith(`SL1 ${sid} ${sequence}`);
    peer.channel.onmessage?.({ data: `SL1 ${sid} ${sequence}` }); await flush();
  }
  expect(reports.at(-1)?.state).toBe('connected');
  expect(reports.at(-1)?.samples).toHaveLength(20);
  expect(peer.close).not.toHaveBeenCalled();
  const renewals = ws.send.mock.calls.map(([text]) => JSON.parse(text)).filter(row => row.type === 'direct_video_keepalive');
  expect(renewals).toHaveLength(24); expect(renewals.at(-1).sequence).toBe(24);
  stop(); expect(jest.getTimerCount()).toBe(0); expect(peer.close).toHaveBeenCalledTimes(1);
});

test('live signaling loss stops the media immediately and retires all renewals', async () => {
  const { stop, peer, ws, reports } = await videoConnected(true);
  peer.channel.onmessage?.({ data: `SV1 ${sid} ${epoch} 960 540` });
  (ws.onclose as unknown as (event: { code: number }) => void)?.({ code: 4003 });
  expect(reports.at(-1)?.reason).toBe('video_access_rejected');
  expect(peer.close).toHaveBeenCalledTimes(1);
  jest.advanceTimersByTime(60000); expect(peer.channel.send).not.toHaveBeenCalled();
  stop(); expect(jest.getTimerCount()).toBe(0);
});

test('live ICE recovers a transient disconnected state without replacing the peer or media grant', async () => {
  const { stop, peer, reports } = await videoConnected(true);
  peer.connectionState = 'disconnected'; peer.onconnectionstatechange?.();
  jest.advanceTimersByTime(2000);
  expect(peer.close).not.toHaveBeenCalled();
  peer.connectionState = 'connected'; peer.onconnectionstatechange?.(); await flush();
  jest.advanceTimersByTime(1000);
  expect(reports.at(-1)?.state).toBe('connected');
  expect(peer.close).not.toHaveBeenCalled();
  stop(); expect(jest.getTimerCount()).toBe(0);
});

test.each(['disconnected', 'failed', 'closed'])('live ICE still retires a persistent or terminal %s state', async state => {
  const { stop, peer, reports } = await videoConnected(true);
  peer.connectionState = state; peer.onconnectionstatechange?.();
  if (state === 'disconnected') {
    jest.advanceTimersByTime(2999); expect(peer.close).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1);
  }
  expect(reports.at(-1)?.reason).toBe('peer_disconnected');
  expect(peer.close).toHaveBeenCalledTimes(1);
  stop(); expect(jest.getTimerCount()).toBe(0);
});
test('video negotiates an explicit receive-only transceiver and independently bound read-only channel', async () => {
  const { reports, stop, peer, ws } = await videoConnected();
  expect(JSON.parse(ws.send.mock.calls[0][0])).toEqual({ token: 'access', protocol: 'sphere-video-probe-v1' });
  expect(peer.addTransceiver).toHaveBeenCalledWith('video', { direction: 'recvonly' });
  expect(peer.createDataChannel).toHaveBeenCalledWith('sphere-video-probe-v1', { ordered: true });
  peer.channel.onmessage?.({ data: `SV1 ${sid} ${epoch} 960 540` });
  expect(reports.at(-1)?.videoBinding).toEqual({ captureEpoch: epoch, width: 960, height: 540 });
  jest.advanceTimersByTime(1000); peer.channel.onmessage?.({ data: `SP1 ${sid} 1` }); await flush();
  expect(reports.at(-1)?.samples).toHaveLength(1);
  stop(); expect(jest.getTimerCount()).toBe(0);
});
test('video cleanup stops the remote track and late native track callbacks cannot revive a peer', async () => {
  const { onTrack, stop, peer } = await videoConnected();
  const track = { kind: 'video', onended: null, stop: jest.fn() };
  const late = peer.ontrack;
  peer.ontrack?.({ track: track as unknown as MediaStreamTrack });
  expect(onTrack).toHaveBeenCalledTimes(1);
  stop(); expect(track.stop).toHaveBeenCalledTimes(1); expect(track.onended).toBeNull();
  const orphan = { kind: 'video', stop: jest.fn() };
  late?.({ track: orphan as unknown as MediaStreamTrack });
  expect(orphan.stop).toHaveBeenCalledTimes(1); expect(onTrack).toHaveBeenCalledTimes(1);
  expect(jest.getTimerCount()).toBe(0);
});
test.each(['audio', 'duplicate'])('an unexpected media track retires the entire video experiment: %s', async kind => {
  const { stop, peer, reports } = await videoConnected();
  if (kind === 'duplicate') peer.ontrack?.({ track: { kind: 'video', stop: jest.fn() } as unknown as MediaStreamTrack });
  const orphan = { kind: kind === 'audio' ? 'audio' : 'video', stop: jest.fn() };
  peer.ontrack?.({ track: orphan as unknown as MediaStreamTrack });
  expect(orphan.stop).toHaveBeenCalledTimes(1);
  expect(reports.at(-1)?.reason).toBe('invalid_video_track'); stop(); expect(jest.getTimerCount()).toBe(0);
});
test('echo-only answers and bidirectional media never satisfy the video permission', async () => {
  for (const sdp of [appSdp, videoSdp, videoSdp.replace('recvonly', 'sendrecv')]) {
    FakePeer.initialSdp = videoSdp;
    const reports: DirectProbeResult[] = [];
    startDirectVideoProbe('wss://same-origin', 'access', r => reports.push(r), { onTrack: jest.fn() }); await flush();
    FakeSocket.latest.onmessage?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: sid, sdp }) });
    expect(reports.at(-1)?.reason).toBe('invalid_answer'); expect(jest.getTimerCount()).toBe(0);
  }
});
test('video binding rejects wrong peers, nil captures, oversized geometry and repeated metadata', async () => {
  for (const bad of [`SV1 ${'b'.repeat(32)} ${epoch} 960 540`, `SV1 ${sid} 00000000-0000-0000-0000-000000000000 960 540`,
    `SV1 ${sid} ${epoch} 1920 1080`, `SV1 ${sid} ${epoch} 0960 540`, '{}']) expect(parseVideoBinding(bad, sid)).toBeNull();
  const { reports, stop, peer } = await videoConnected();
  peer.channel.onmessage?.({ data: `SV1 ${sid} ${epoch} 960 540` });
  peer.channel.onmessage?.({ data: `SV1 ${sid} ${epoch} 960 540` });
  expect(reports.at(-1)?.reason).toBe('invalid_echo'); stop(); expect(jest.getTimerCount()).toBe(0);
});
test('read-only SDP parser rejects audio, missing codecs, weak fingerprints and scope expansion', () => {
  expect(readonlyVideoSdp(videoSdp, true)).toBe(true);
  expect(readonlyVideoSdp(videoSdp.replace('recvonly', 'sendonly'), false)).toBe(true);
  for (const bad of [appSdp, videoSdp + 'm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n', videoSdp + 'a=sendonly\r\n',
    videoSdp.replace('H264', 'VP8'), videoSdp.replace('sha-256', 'sha-1'), videoSdp + 'a=candidate:x\r\n'.repeat(65)])
    expect(readonlyVideoSdp(bad, true)).toBe(false);
});

test('relay grant handshake authenticates before allocating peer and binds the offer/answer', async () => {
  const reports: DirectProbeResult[] = [];
  const stop = startDirectProbe('wss://same-origin/ws/direct-probe/device', 'access', r => reports.push(r), { relayGrant: true });
  expect(FakePeer.constructions).toBe(0);
  const ws = FakeSocket.latest;
  ws.onopen?.();
  expect(ws.send).toHaveBeenCalledTimes(1);
  expect(JSON.parse(ws.send.mock.calls[0][0])).toEqual({ token: 'access', protocol: 'sphere-probe-v2' });
  ws.onmessage?.({ data: JSON.stringify(relayReady()) }); await flush();
  const peer = FakePeer.latest;
  expect(peer.configuration.iceTransportPolicy).toBe('relay');
  expect(ws.send).toHaveBeenCalledTimes(2);
  expect(JSON.parse(ws.send.mock.calls[1][0])).toEqual({ type: 'direct_probe_offer', sdp: 'v=0\r\n' });
  ws.onmessage?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: sid, sdp: 'v=0\r\n' }) });
  await flush(); peer.channel.onopen?.(); jest.advanceTimersByTime(1000);
  peer.channel.onmessage?.({ data: `SP1 ${sid} 1` }); await flush();
  expect(reports.at(-1)?.samples).toHaveLength(1);
  expect(JSON.stringify(reports)).not.toContain('relay.example.test');
  expect(JSON.stringify(reports)).not.toContain('A'.repeat(27));
  stop(); expect(jest.getTimerCount()).toBe(0);
});

test('invalid relay grant never allocates a peer and stop before grant leaves no timers', async () => {
  const reports: DirectProbeResult[] = [];
  const stop = startDirectProbe('wss://same-origin', 'access', r => reports.push(r), { relayGrant: true });
  const ws = FakeSocket.latest, late = ws.onmessage;
  ws.onmessage?.({ data: JSON.stringify({ ...relayReady(), session_id: 'wrong' }) });
  expect(reports.at(-1)?.reason).toBe('invalid_ice_grant'); expect(FakePeer.constructions).toBe(0);
  late?.({ data: JSON.stringify(relayReady()) }); await flush(); stop();
  expect(FakePeer.constructions).toBe(0); expect(jest.getTimerCount()).toBe(0);
});

test('relay ready cannot replace binding with a different answer or a second ready', async () => {
  const reports: DirectProbeResult[] = [];
  startDirectProbe('wss://same-origin', 'access', r => reports.push(r), { relayGrant: true });
  const ws = FakeSocket.latest;
  ws.onmessage?.({ data: JSON.stringify(relayReady()) }); await flush();
  ws.onmessage?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: 'b'.repeat(32), sdp: 'v=0\r\n' }) });
  expect(FakePeer.latest.setRemoteDescription).not.toHaveBeenCalled();
  expect(reports.at(-1)?.reason).toBe('invalid_signal'); expect(jest.getTimerCount()).toBe(0);
});

test('missing server grant expires without allocating native browser resources', () => {
  const reports: DirectProbeResult[] = [];
  startDirectProbe('wss://same-origin', 'access', r => reports.push(r), { relayGrant: true });
  jest.advanceTimersByTime(8000);
  expect(FakePeer.constructions).toBe(0); expect(reports.at(-1)?.reason).toBe('signaling_deadline');
  expect(jest.getTimerCount()).toBe(0);
});

test('browser constructor failure after a valid grant closes signaling and all timers', () => {
  const reports: DirectProbeResult[] = [];
  startDirectProbe('wss://same-origin', 'access', r => reports.push(r), { relayGrant: true });
  Object.defineProperty(globalThis, 'RTCPeerConnection', { configurable: true,
    value: class { constructor() { throw Error('native allocation failed'); } } });
  const ws = FakeSocket.latest;
  ws.onmessage?.({ data: JSON.stringify(relayReady()) });
  expect(reports.at(-1)?.reason).toBe('webrtc_unavailable');
  expect(ws.close).toHaveBeenCalledTimes(1);
  expect(jest.getTimerCount()).toBe(0);
});

test('controlled profile configures exactly one STUN server and reports only its class', async () => {
  const reports: DirectProbeResult[] = [];
  const stop = startDirectProbe('wss://same-origin/ws/direct-probe/device', 'access', value => reports.push(value),
    { controlledStunUrl: 'stun:10.0.2.2:3478' });
  await flush();
  expect(FakePeer.latest.configuration).toEqual({ iceServers: [{ urls: 'stun:10.0.2.2:3478' }], bundlePolicy: 'max-bundle' });
  expect(reports[0].iceProfile).toBe('controlled-stun');
  expect(JSON.stringify(reports)).not.toContain('10.0.2.2');
  stop();
});

test('invalid diagnostic configuration allocates no peer, signaling or timer', () => {
  expect(() => startDirectProbe('wss://same-origin', 'access', jest.fn(),
    { controlledStunUrl: 'stun:unowned.example:3478' })).toThrow('invalid_controlled_stun');
  expect(FakePeer.constructions).toBe(0);
  expect(jest.getTimerCount()).toBe(0);
});

test('incomplete gathering expires before any offer is sent and retires late callbacks', async () => {
  FakePeer.initialGatheringState = 'gathering';
  const reports: DirectProbeResult[] = [];
  startDirectProbe('wss://same-origin', 'access', value => reports.push(value));
  await flush();
  const peer = FakePeer.latest, late = peer.onicegatheringstatechange;
  jest.advanceTimersByTime(8000);
  expect(reports.at(-1)?.reason).toBe('gathering_deadline');
  expect(peer.setRemoteDescription).not.toHaveBeenCalled();
  const count = reports.length;
  peer.iceGatheringState = 'complete'; late?.(); await flush();
  expect(reports).toHaveLength(count);
  expect(peer.close).toHaveBeenCalledTimes(1);
  expect(jest.getTimerCount()).toBe(0);
});

test('signaling expires independently without calling it an ICE failure', async () => {
  const reports: DirectProbeResult[] = [];
  startDirectProbe('wss://same-origin', 'access', value => reports.push(value));
  await flush();
  const late = FakeSocket.latest.onmessage;
  jest.advanceTimersByTime(8000);
  expect(reports.at(-1)?.reason).toBe('signaling_deadline');
  late?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: sid, sdp: 'v=0\r\n' }) });
  await flush();
  expect(FakePeer.latest.setRemoteDescription).not.toHaveBeenCalled();
  expect(jest.getTimerCount()).toBe(0);
});

test('ICE gets its bounded interval after gathering and signaling, without extending the total lease', async () => {
  FakePeer.initialGatheringState = 'gathering';
  const reports: DirectProbeResult[] = [];
  startDirectProbe('wss://same-origin', 'access', value => reports.push(value)); await flush();
  jest.advanceTimersByTime(7000);
  FakePeer.latest.iceGatheringState = 'complete'; FakePeer.latest.onicegatheringstatechange?.();
  jest.advanceTimersByTime(7000);
  FakeSocket.latest.onmessage?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: sid, sdp: 'v=0\r\n' }) });
  await flush();
  jest.advanceTimersByTime(11000); await flush();
  expect(reports.at(-1)?.state).toBe('connecting');
  jest.advanceTimersByTime(1000); await flush();
  expect(reports.at(-1)?.reason).toBe('connection_deadline');
  expect(jest.getTimerCount()).toBe(0);
});

test('an open channel cannot extend the thirty-second overall lease after slow setup', async () => {
  FakePeer.initialGatheringState = 'gathering';
  const reports: DirectProbeResult[] = [];
  startDirectProbe('wss://same-origin', 'access', value => reports.push(value)); await flush();
  jest.advanceTimersByTime(7000);
  const peer = FakePeer.latest;
  peer.iceGatheringState = 'complete'; peer.onicegatheringstatechange?.();
  jest.advanceTimersByTime(7000);
  FakeSocket.latest.onmessage?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: sid, sdp: 'v=0\r\n' }) });
  await flush();
  jest.advanceTimersByTime(11000); await flush(); peer.channel.onopen?.();
  for (let i = 1; i <= 4; i++) {
    jest.advanceTimersByTime(1000); peer.channel.onmessage?.({ data: `SP1 ${sid} ${i}` }); await flush();
  }
  expect(reports.at(-1)?.samples).toHaveLength(4);
  jest.advanceTimersByTime(1000); await flush();
  expect(reports.at(-1)?.reason).toBe('probe_deadline');
  expect(peer.close).toHaveBeenCalledTimes(1);
  expect(jest.getTimerCount()).toBe(0);
});

test('auth travels only in signaling and successful echoes never forward to the server', async () => {
  const { peer, ws, reports, stop } = await connected();
  expect(ws.send.mock.calls.map(([v]) => JSON.parse(v).type)).toEqual([undefined, 'direct_probe_offer']);
  jest.advanceTimersByTime(1000);
  expect(peer.channel.send).toHaveBeenCalledWith(`SP1 ${sid} 1`);
  jest.advanceTimersByTime(23);
  peer.channel.onmessage?.({ data: `SP1 ${sid} 1` }); await flush();
  expect(reports.at(-1)?.samples).toEqual([23]);
  expect(ws.send).toHaveBeenCalledTimes(2);
  stop(); expect(peer.close).toHaveBeenCalledTimes(1); expect(peer.channel.close).toHaveBeenCalledTimes(1);
  expect(ws.close).toHaveBeenCalledTimes(1);
  expect(reports.at(-1)?.state).toBe('stopped');
});

test('an installed answer reports ICE checking without granting a channel or sending input', async () => {
  const reports: DirectProbeResult[] = [];
  const stop = startDirectProbe('wss://same-origin/ws/direct-probe/device', 'access', value => reports.push(value));
  await flush();
  FakeSocket.latest.onopen?.();
  FakeSocket.latest.onmessage?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: sid, sdp: 'v=0\r\n' }) });
  await flush();
  expect(reports.at(-1)?.state).toBe('connecting');
  expect(reports.at(-1)?.samples).toEqual([]);
  expect(FakePeer.latest.channel.send).not.toHaveBeenCalled();
  stop();
  expect(reports.at(-1)?.state).toBe('stopped');
});

test('late remote-description completion cannot downgrade an open or stopped probe', async () => {
  const reports: DirectProbeResult[] = [];
  const stop = startDirectProbe('wss://same-origin/ws/direct-probe/device', 'access', value => reports.push(value));
  await flush();
  const peer = FakePeer.latest;
  let finishAnswer!: () => void;
  peer.setRemoteDescription.mockImplementation(() => new Promise<void>(resolve => { finishAnswer = resolve; }));
  FakeSocket.latest.onmessage?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: sid, sdp: 'v=0\r\n' }) });
  peer.channel.onopen?.();
  expect(reports.at(-1)?.state).toBe('connected');
  stop();
  const count = reports.length;
  finishAnswer(); await flush();
  expect(reports).toHaveLength(count);
  expect(reports.at(-1)?.state).toBe('stopped');
  expect(peer.channel.send).not.toHaveBeenCalled();
});

test('echo timeout retires all timers and callbacks without retries', async () => {
  const { peer, reports } = await connected();
  jest.advanceTimersByTime(2000);
  expect(reports.at(-1)?.reason).toBe('echo_timeout');
  jest.advanceTimersByTime(60000);
  expect(peer.channel.send).toHaveBeenCalledTimes(1);
  expect(peer.close).toHaveBeenCalledTimes(1);
  expect(jest.getTimerCount()).toBe(0);
});

test('signaling failure during Stop cannot leak the DataChannel or peer', async () => {
  const { peer, ws, reports, stop } = await connected();
  ws.send.mockImplementation(() => { throw Error('socket closed'); });
  ws.close.mockImplementation(() => { throw Error('close unavailable'); });
  peer.channel.close.mockImplementation(() => { throw Error('channel close unavailable'); });
  expect(stop).not.toThrow();
  expect(peer.close).toHaveBeenCalledTimes(1);
  expect(reports.at(-1)?.state).toBe('stopped');
  expect(jest.getTimerCount()).toBe(0);
});

test('wrong nonce or duplicate echo closes rather than marking RTT successful', async () => {
  const { peer, reports } = await connected();
  jest.advanceTimersByTime(1000);
  peer.channel.onmessage?.({ data: `SP1 ${'b'.repeat(32)} 1` });
  expect(reports.at(-1)?.samples).toEqual([]);
  expect(reports.at(-1)?.reason).toBe('invalid_echo');
});

test('stopped signaling callbacks cannot reopen a retired peer', async () => {
  const { peer, ws, stop } = await connected();
  const late = ws.onmessage;
  stop();
  late?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: sid, sdp: 'v=0' }) });
  expect(peer.setRemoteDescription).toHaveBeenCalledTimes(1);
});

test('finite successful probe closes after twenty samples and does not retain further messages', async () => {
  const { peer, reports } = await connected();
  for (let i = 1; i <= 20; i++) {
    jest.advanceTimersByTime(1000);
    peer.channel.onmessage?.({ data: `SP1 ${sid} ${i}` }); await flush();
  }
  jest.advanceTimersByTime(1000);
  expect(reports.at(-1)?.state).toBe('finished');
  expect(reports.at(-1)?.samples).toHaveLength(20);
  expect(peer.channel.send).toHaveBeenCalledTimes(20);
  expect(jest.getTimerCount()).toBe(0);
});

test('only selected candidate pair proves host/NAT/relay; endpoint IPs are excluded', () => {
  const stats = new Map<string, Record<string, unknown>>([
    ['t', { type: 'transport', selectedCandidatePairId: 'p' }],
    ['p', { type: 'candidate-pair', localCandidateId: 'l', remoteCandidateId: 'r' }],
    ['l', { candidateType: 'host', protocol: 'udp', address: '10.0.0.1' }],
    ['r', { candidateType: 'host', address: '10.0.0.2' }],
  ]);
  expect(probePath(stats as unknown as RTCStatsReport)).toEqual({ path: 'host', protocol: 'udp' });
  stats.set('r', { candidateType: 'srflx' });
  expect(probePath(stats as unknown as RTCStatsReport).path).toBe('nat');
  stats.set('l', { candidateType: 'relay', protocol: 'tcp' });
  expect(probePath(stats as unknown as RTCStatsReport).path).toBe('relay');
  stats.delete('t');
  expect(probePath(stats as unknown as RTCStatsReport)).toEqual({ path: 'unknown', protocol: null });
});

test('startup ICE samples survive failure with age while selected path and RTT remain unknown', async () => {
  const reports: DirectProbeResult[] = [];
  startDirectProbe('wss://same-origin/ws/direct-probe/device', 'access', value => reports.push(value));
  await flush();
  FakePeer.latest.getStats.mockResolvedValue(new Map([
    ['p', { type: 'candidate-pair', state: 'in-progress', requestsSent: 4, responsesReceived: 0 }],
  ]));
  FakeSocket.latest.onmessage?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: sid, sdp: 'v=0\r\n' }) });
  await flush();
  jest.advanceTimersByTime(500); await flush();
  const calls = FakePeer.latest.getStats.mock.calls.length;
  jest.advanceTimersByTime(11500); await flush();
  const last = reports.at(-1)!;
  expect(last.reason).toBe('connection_deadline');
  expect(last.network).toMatchObject({ checkingPairs: 1, requestsSent: 4, responsesReceived: 0 });
  expect(last.iceState).toBe('checking');
  expect(last.networkAgeAtStopMs).toBe(12000);
  expect(last.path).toBe('unknown'); expect(last.samples).toEqual([]);
  jest.advanceTimersByTime(60000); await flush();
  expect(FakePeer.latest.getStats.mock.calls.length).toBe(calls + 1);
  expect(jest.getTimerCount()).toBe(0);
});

test('unresolved diagnostic call cannot pile up or delay Stop and late results stay retired', async () => {
  const reports: DirectProbeResult[] = [];
  const stop = startDirectProbe('wss://same-origin/ws/direct-probe/device', 'access', value => reports.push(value));
  await flush();
  let finish!: (value: Map<string, Record<string, unknown>>) => void;
  FakePeer.latest.getStats.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  FakeSocket.latest.onmessage?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: sid, sdp: 'v=0\r\n' }) });
  await flush(); jest.advanceTimersByTime(9000); await flush();
  expect(FakePeer.latest.getStats).toHaveBeenCalledTimes(1);
  stop();
  expect(FakePeer.latest.close).toHaveBeenCalledTimes(1);
  const count = reports.length;
  finish(new Map([['t', { type: 'transport', dtlsState: 'connected' }]])); await flush();
  expect(reports).toHaveLength(count);
  expect(reports.at(-1)?.network).toBeUndefined();
  expect(jest.getTimerCount()).toBe(0);
});

test('diagnostic rejection does not misclassify a valid answer or stop the echo channel', async () => {
  const reports: DirectProbeResult[] = [];
  const stop = startDirectProbe('wss://same-origin/ws/direct-probe/device', 'access', value => reports.push(value));
  await flush();
  FakePeer.latest.getStats.mockImplementation(() => { throw new Error('stats unavailable'); });
  FakeSocket.latest.onmessage?.({ data: JSON.stringify({ type: 'direct_probe_answer', session_id: sid, sdp: 'v=0\r\n' }) });
  await flush();
  expect(reports.at(-1)?.state).toBe('connecting');
  FakePeer.latest.channel.onopen?.(); jest.advanceTimersByTime(1000);
  FakePeer.latest.channel.onmessage?.({ data: `SP1 ${sid} 1` }); await flush();
  expect(reports.at(-1)?.samples).toHaveLength(1);
  expect(reports.at(-1)?.network).toBeUndefined();
  stop();
});

test('diagnostic sampling has a hard call budget across scheduled checks and twenty echo replies', async () => {
  const { peer, reports } = await connected();
  for (let i = 1; i <= 20; i++) {
    jest.advanceTimersByTime(1000); await flush();
    peer.channel.onmessage?.({ data: `SP1 ${sid} ${i}` }); await flush();
  }
  jest.advanceTimersByTime(1000); await flush();
  expect(reports.at(-1)?.state).toBe('finished');
  expect(peer.getStats).toHaveBeenCalledTimes(32);
  expect(jest.getTimerCount()).toBe(0);
});
