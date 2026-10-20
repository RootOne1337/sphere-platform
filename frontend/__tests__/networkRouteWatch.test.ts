import { NetworkRouteWatch, gatherLocalIceTopology, numericIceTopology, watchNetworkRoute } from '@/src/features/stream/networkRouteWatch';

const candidate = (address: string, port = 4000, type = 'host') =>
  ({ candidate: `candidate:random 1 udp 2113937151 ${address} ${port} typ ${type} generation 0 ufrag secret` });
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

test('numeric topology ignores transient ports, foundation, credentials and rotating mDNS names', () => {
  const first = numericIceTopology([candidate('192.168.1.2'), candidate('198.51.100.2', 7000, 'srflx'), candidate('one.local')]);
  expect(first).toBe(numericIceTopology([candidate('two.local'), candidate('198.51.100.2', 8000, 'srflx'), candidate('192.168.1.2', 9000)]));
  expect(first).not.toBe(numericIceTopology([candidate('192.168.1.2'), candidate('198.51.100.3', 7000, 'srflx')]));
  expect(numericIceTopology([candidate('one.local'), candidate('999.1.2.3')])).toBeNull();
  expect(first).not.toMatch(/secret|random|ufrag|local/);
});

test('estimate events coalesce; stable addresses keep the stream, a VPN address change notifies each active viewer once', async () => {
  const sample = jest.fn().mockResolvedValueOnce('host:10.1.1.1').mockResolvedValueOnce('host:10.1.1.1')
    .mockResolvedValue('host:10.1.1.1|srflx:198.51.100.1');
  const watch = new NetworkRouteWatch([], sample);
  const changed = jest.fn(), inactive = jest.fn();
  watch.add({ active: () => true, changed }); watch.add({ active: () => false, changed: inactive });
  for (let n = 0; n < 10; n++) watch.check();
  jest.advanceTimersByTime(200); await flush();
  expect(sample).toHaveBeenCalledTimes(1); expect(changed).not.toHaveBeenCalled();
  watch.check(); jest.advanceTimersByTime(5000); await flush();
  expect(changed).not.toHaveBeenCalled();
  watch.check(); jest.advanceTimersByTime(5000); await flush();
  expect(changed).not.toHaveBeenCalled();
  jest.advanceTimersByTime(5000); await flush();
  expect(changed).toHaveBeenCalledTimes(1); expect(inactive).not.toHaveBeenCalled();
  watch.close(); expect(jest.getTimerCount()).toBe(0);
});

test('failed or unknown gathers never replace the baseline; close cancels late work and timers', async () => {
  let complete: (value: string) => void = () => {};
  const sample = jest.fn().mockResolvedValueOnce('host:10.1.1.1').mockResolvedValueOnce(null)
    .mockImplementationOnce(() => new Promise<string>(resolve => { complete = resolve; }));
  const changed = jest.fn(), watch = new NetworkRouteWatch([], sample);
  watch.add({ active: () => true, changed });
  watch.check(); jest.advanceTimersByTime(200); await flush();
  watch.check(); jest.advanceTimersByTime(5000); await flush();
  watch.check(); jest.advanceTimersByTime(5000); await flush();
  watch.close(); complete('host:10.2.2.2'); await flush();
  expect(changed).not.toHaveBeenCalled(); expect(sample.mock.calls[2][1].aborted).toBe(true);
  expect(jest.getTimerCount()).toBe(0);
});

test('one silent network change is discovered by polling even without browser online/change events', async () => {
  const sample = jest.fn().mockResolvedValueOnce('host:10.1.1.1').mockResolvedValue('host:10.2.2.2');
  const changed = jest.fn(), watch = new NetworkRouteWatch([], sample);
  watch.add({ active: () => true, changed });
  watch.check(); jest.advanceTimersByTime(200); await flush();
  jest.advanceTimersByTime(20000); await flush();
  expect(changed).not.toHaveBeenCalled();
  jest.advanceTimersByTime(5000); await flush();
  expect(changed).toHaveBeenCalledTimes(1);
  watch.close();
});

test('one inconsistent STUN topology never resets a stable stream', async () => {
  const sample = jest.fn().mockResolvedValueOnce('host:10.1.1.1').mockResolvedValueOnce('host:10.2.2.2')
    .mockResolvedValue('host:10.1.1.1');
  const changed = jest.fn(), watch = new NetworkRouteWatch([], sample);
  watch.add({ active: () => true, changed });
  watch.check(); jest.advanceTimersByTime(200); await flush();
  watch.check(); jest.advanceTimersByTime(5000); await flush();
  jest.advanceTimersByTime(5000); await flush();
  expect(sample).toHaveBeenCalledTimes(3); expect(changed).not.toHaveBeenCalled();
  watch.close();
});

test('local gather needs no remote description or input; always closes its temporary peer', async () => {
  const close = jest.fn(), remote = jest.fn();
  let peer: { onicecandidate: ((event: unknown) => void) | null };
  Object.defineProperty(globalThis, 'RTCPeerConnection', { configurable: true, value: class {
    onicecandidate = null;
    constructor() { peer = this; }
    createDataChannel = jest.fn();
    createOffer = jest.fn(async () => ({ type: 'offer', sdp: 'local-only' }));
    setLocalDescription = jest.fn(async () => {
      peer.onicecandidate?.({ candidate: { toJSON: () => candidate('10.1.1.1') } });
      peer.onicecandidate?.({ candidate: null });
    });
    setRemoteDescription = remote;
    close = close;
  } });
  const value = await gatherLocalIceTopology([], new AbortController().signal);
  expect(value).toBe('host:10.1.1.1'); expect(remote).not.toHaveBeenCalled(); expect(close).toHaveBeenCalledTimes(1);
  expect(jest.getTimerCount()).toBe(0);
});

test('twenty viewers share one gather and the last subscriber owns cleanup', async () => {
  const created = jest.fn();
  Object.defineProperty(globalThis, 'RTCPeerConnection', { configurable: true, value: class {
    onicecandidate: ((event: unknown) => void) | null = null;
    constructor() { created(); }
    createDataChannel = jest.fn();
    createOffer = jest.fn(async () => ({ type: 'offer', sdp: 'local-only' }));
    setLocalDescription = jest.fn(async () => {
      this.onicecandidate?.({ candidate: { toJSON: () => candidate('10.1.1.1') } });
      this.onicecandidate?.({ candidate: null });
    });
    close = jest.fn();
  } });
  const viewers = Array.from({length:20}, () => watchNetworkRoute([], { active: () => true, changed: jest.fn() }));
  viewers.forEach(viewer => viewer.check());
  jest.advanceTimersByTime(200); await flush();
  expect(created).toHaveBeenCalledTimes(1);
  viewers.slice(0,19).forEach(viewer => viewer.close());
  expect(jest.getTimerCount()).toBe(1);
  viewers[19].close(); expect(jest.getTimerCount()).toBe(0);
});
