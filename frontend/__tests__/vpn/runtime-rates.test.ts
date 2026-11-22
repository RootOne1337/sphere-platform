import { currentVpnRate, observeVpnRates, type VpnRateHistory } from '@/src/features/vpn/runtimeRates';
import type { VpnRuntimeDevice, VpnRuntimePage } from '@/src/features/vpn/runtimeTypes';

const start = Date.parse('2026-10-22T00:00:00Z');
const id = (n: number) => `018d83cc-1111-4444-8888-${String(n).padStart(12, '0')}`;
function page(offset = 0, rx = 100, tx = 200): VpnRuntimePage {
  const at = start + offset;
  return { page: 1, page_size: 25, total: 1, as_of: new Date(at).toISOString(), items: [{ device_id: id(1), name: 'Device',
    model: null, android_version: '9', status: 'online', agent_version: '1.2.84', last_heartbeat: new Date(at).toISOString(), freshness: 'fresh',
    observation: { received_at: new Date(at).toISOString(), ws_session_id: 'control-1', snapshot: { requestId: id(2), sessionId: id(3),
      profileRevisionId: id(4), phase: 'HANDSHAKE_CONFIRMED', reason: null, nativeVersion: '3.1', handshakeEpochSeconds: null,
      rxBytes: rx, txBytes: tx, sampledAtEpochMs: at, providerPid: 123 } } }] };
}
function measured() {
  const first = observeVpnRates(new Map(), page(), start); const next = page(5000, 10340, 5320);
  return { next, history: observeVpnRates(first, next, start + 5000) };
}
it('uses native elapsed time and preserves held counters as a real zero rate', () => {
  const { next, history } = measured();
  expect(currentVpnRate(history, next.items[0], next.as_of, start + 5000)).toEqual({ rx: 2048, tx: 1024, intervalMs: 5000, sampledAt: start + 5000 });
  const held = page(10000, 10340, 5320);
  const updated = observeVpnRates(history, held, start + 10000);
  expect(currentVpnRate(updated, held.items[0], held.as_of, start + 10000)).toMatchObject({ rx: 0, tx: 0 });
});
it('does not invent a rate from one sample or renew the sample time on duplicate polls', () => {
  const first = page(); const once = observeVpnRates(new Map(), first, start);
  expect(currentVpnRate(once, first.items[0], first.as_of, start)).toBeNull();
  const { history, next } = measured(); const repeated = { ...next, as_of: new Date(start + 9000).toISOString() };
  expect(observeVpnRates(history, repeated, start + 9000).get(id(1))).toEqual(history.get(id(1)));
  expect(currentVpnRate(history, next.items[0], repeated.as_of, start + 20000)).toBeNull();
});
it.each([
  ['provider', (d: VpnRuntimeDevice) => { d.observation!.snapshot.providerPid++; }],
  ['tunnel', (d: VpnRuntimeDevice) => { d.observation!.snapshot.sessionId = id(30); }],
  ['revision', (d: VpnRuntimeDevice) => { d.observation!.snapshot.profileRevisionId = id(40); }],
  ['control', (d: VpnRuntimeDevice) => { d.observation!.ws_session_id = 'control-2'; }],
  ['missing identity', (d: VpnRuntimeDevice) => { d.observation!.snapshot.sessionId = null; }],
  ['missing counter', (d: VpnRuntimeDevice) => { d.observation!.snapshot.rxBytes = null; }],
  ['paused', (d: VpnRuntimeDevice) => { d.observation!.snapshot.phase = 'PAUSED_GUARD_HELD'; }],
  ['unknown', (d: VpnRuntimeDevice) => { d.freshness = 'unknown'; }],
] as const)('clears rates after %s changes', (_name, change) => {
  const { history } = measured(); const next = page(10000, 20000, 20000); change(next.items[0]);
  const updated = observeVpnRates(history, next, start + 10000);
  expect(currentVpnRate(updated, next.items[0], next.as_of, start + 10000)).toBeNull();
});
it.each([[6000, 50, 60], [5500, 11000, 11000], [25000, 20000, 20000], [4000, 20000, 20000]])(
  'rejects resets, short/long intervals and backwards samples (%i)', (at, rx, tx) => {
    const { history } = measured(); const next = page(at, rx, tx);
    const updated = observeVpnRates(history, next, start + Math.max(5000, at));
    expect(currentVpnRate(updated, next.items[0], next.as_of, start + Math.max(5000, at))).toBeNull();
  });
it('bounds history to the current page, and does not show old rates while a new sample is rendering', () => {
  const { history, next } = measured(); const newer = page(10000, 20000, 20000);
  expect(currentVpnRate(history, newer.items[0], newer.as_of, start + 10000)).toBeNull();
  const empty: VpnRateHistory = observeVpnRates(history, { ...next, items: [], total: 0 }, start + 5000);
  expect(empty.size).toBe(0);
});
