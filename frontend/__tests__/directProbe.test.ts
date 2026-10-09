import { probePath, startDirectProbe, type DirectProbeResult } from '@/src/features/stream/directProbe';

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
  channel = new FakeChannel();
  iceGatheringState = 'complete'; connectionState = 'connected';
  localDescription = { sdp: 'v=0\r\n' };
  onicegatheringstatechange: (() => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  constructor() { FakePeer.latest = this; }
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
  Object.defineProperty(globalThis, 'RTCPeerConnection', { configurable: true, value: FakePeer });
  Object.defineProperty(globalThis, 'WebSocket', { configurable: true, value: FakeSocket });
  if (!globalThis.TextEncoder) Object.defineProperty(globalThis, 'TextEncoder', { configurable: true, value: require('util').TextEncoder });
});
afterEach(() => { jest.useRealTimers(); });

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
  const stats = new Map<string, any>([
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
