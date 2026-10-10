import { probePath, startDirectProbe, type DirectProbeResult } from '@/src/features/stream/directProbe';
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
  channel = new FakeChannel();
  iceGatheringState = FakePeer.initialGatheringState; connectionState = 'connected'; iceConnectionState = 'checking';
  localDescription = { sdp: 'v=0\r\n' };
  onicegatheringstatechange: (() => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  constructor(readonly configuration: RTCConfiguration) { FakePeer.latest = this; FakePeer.constructions++; }
  createDataChannel = jest.fn(() => this.channel);
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
beforeEach(() => {
  jest.useFakeTimers();
  FakePeer.initialGatheringState = 'complete'; FakePeer.constructions = 0;
  Object.defineProperty(globalThis, 'RTCPeerConnection', { configurable: true, value: FakePeer });
  Object.defineProperty(globalThis, 'WebSocket', { configurable: true, value: FakeSocket });
  if (!globalThis.TextEncoder) Object.defineProperty(globalThis, 'TextEncoder', { configurable: true, value: TextEncoder });
});
afterEach(() => { jest.useRealTimers(); });

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
