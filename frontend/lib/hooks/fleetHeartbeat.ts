import type { QueryClient } from '@tanstack/react-query';
import type { Device } from './useDevices';

type HeartbeatFields = Pick<Device, 'last_heartbeat' | 'vpn_active' | 'vpn_observed_at'
  | 'vpn_observation_state' | 'vpn_observation_max_age_seconds'>;
type DeviceReading = Pick<Device, 'id' | 'status'> & Partial<HeartbeatFields> & Pick<Device, 'connected_since'>;
const timestamp = (value: unknown): number => typeof value === 'string'
  && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? Date.parse(value) : NaN;

export function applyFleetHeartbeat(client: QueryClient, event: Record<string, unknown>): void {
  const id = event.device_id;
  const payload = event.payload as HeartbeatFields | null;
  if (typeof id !== 'string' || !id || !payload || typeof payload !== 'object') return;
  const heartbeatAt = timestamp(payload.last_heartbeat);
  if (!Number.isFinite(heartbeatAt) || heartbeatAt > Date.now() + 5000) return;
  const observedAt = timestamp(payload.vpn_observed_at);
  const vpnState = payload.vpn_observation_state;
  const maxAge = payload.vpn_observation_max_age_seconds;
  const validVpn = (vpnState === 'fresh' && Number.isFinite(observedAt) && typeof payload.vpn_active === 'boolean')
    || ((vpnState === 'stale' || vpnState === 'unknown') && payload.vpn_active === null
      && (payload.vpn_observed_at === null || Number.isFinite(observedAt)));
  const update = <T extends DeviceReading>(row: T): T => {
    if (row.id !== id || (row.status !== 'online' && row.status !== 'busy')
      || heartbeatAt < timestamp(row.connected_since) || heartbeatAt <= timestamp(row.last_heartbeat)) return row;
    const reading = { ...row, last_heartbeat: payload.last_heartbeat };
    if (validVpn && typeof maxAge === 'number' && Number.isSafeInteger(maxAge) && maxAge > 0
      && (!Number.isFinite(observedAt) || !(observedAt < timestamp(row.vpn_observed_at)))) {
      return { ...reading, vpn_active: payload.vpn_active, vpn_observed_at: payload.vpn_observed_at,
        vpn_observation_state: vpnState, vpn_observation_max_age_seconds: maxAge };
    }
    return reading;
  };
  type DeviceQuery = DeviceReading | { items: DeviceReading[] };
  for (const query of client.getQueryCache().findAll({ queryKey: ['devices'], type: 'active' })) {
    const old = query.state.data as DeviceQuery | undefined;
    if (!old || query.state.status !== 'success') continue;
    const row = 'items' in old ? old.items.find(device => device.id === id) : old;
    if (!row) continue;
    const updated = update(row);
    if (updated === row) continue;
    const data = 'items' in old ? { ...old, items: old.items.map(device => device === row ? updated : device) } : updated;
    // A heartbeat does not renew the REST authority for commands or metadata.
    query.setState({ data });
  }
}
