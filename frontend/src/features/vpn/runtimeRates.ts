import { runtimeFreshness, type VpnRuntimeDevice, type VpnRuntimePage } from './runtimeTypes';

export interface VpnRate { rx: number; tx: number; intervalMs: number; sampledAt: number }
interface Sample { identity: string; at: number; rx: number; tx: number; rate: VpnRate | null }
export type VpnRateHistory = ReadonlyMap<string, Sample>;
const active = new Set(['TRANSPORT_READY', 'AWAITING_HANDSHAKE', 'HANDSHAKE_CONFIRMED']);

/** Two native samples in one provider/tunnel/control epoch; never server polling time. */
export function observeVpnRates(previous: VpnRateHistory, page: VpnRuntimePage, now: number): VpnRateHistory {
  const result = new Map<string, Sample>();
  for (const row of page.items) {
    const observation = row.observation; const sample = observation?.snapshot;
    if (!sample || !observation || runtimeFreshness(row, page.as_of, now) !== 'fresh'
      || !active.has(sample.phase) || !sample.sessionId || !sample.profileRevisionId
      || sample.rxBytes === null || sample.txBytes === null) continue;
    const identity = JSON.stringify([observation.ws_session_id, sample.providerPid, sample.sessionId, sample.profileRevisionId]);
    const before = previous.get(row.device_id);
    const next: Sample = { identity, at: sample.sampledAtEpochMs, rx: sample.rxBytes, tx: sample.txBytes, rate: null };
    if (before?.identity === identity) {
      const intervalMs = next.at - before.at;
      if (intervalMs === 0 && next.rx === before.rx && next.tx === before.tx) next.rate = before.rate;
      else if (intervalMs >= 1000 && intervalMs < 15000 && next.rx >= before.rx && next.tx >= before.tx) {
        next.rate = { rx: (next.rx - before.rx) * 1000 / intervalMs, tx: (next.tx - before.tx) * 1000 / intervalMs,
          intervalMs, sampledAt: next.at };
      }
    }
    result.set(row.device_id, next);
  }
  return result;
}

export function currentVpnRate(history: VpnRateHistory, row: VpnRuntimeDevice, asOf: string, now: number): VpnRate | null {
  if (runtimeFreshness(row, asOf, now) !== 'fresh') return null;
  const sample = row.observation?.snapshot; const entry = history.get(row.device_id);
  if (!sample || !active.has(sample.phase) || !entry || entry.at !== sample.sampledAtEpochMs || entry.rx !== sample.rxBytes || entry.tx !== sample.txBytes
    || entry.identity !== JSON.stringify([row.observation?.ws_session_id, sample.providerPid, sample.sessionId, sample.profileRevisionId])) return null;
  return entry.rate;
}
