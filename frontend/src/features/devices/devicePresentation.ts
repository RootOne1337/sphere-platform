import type { Device } from '@/lib/hooks/useDevices';

/** API metadata is canonical; `model` is a compatibility fallback for older responses. */
export function getReportedDeviceModel(device: { device_model?: unknown; model?: unknown }): string | null {
  for (const value of [device.device_model, device.model]) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

const HEARTBEAT_MAX_AGE_MS = 120_000;
const CLOCK_SKEW_MS = 5_000;

type DevicePresence = Pick<Device, 'status'> & Partial<Pick<Device, 'last_heartbeat'>>;
type DeviceAccess = DevicePresence & Partial<Pick<Device,
  'vpn_active' | 'vpn_observation_state' | 'vpn_observed_at' | 'vpn_observation_max_age_seconds'>>;

function observationAge(timestamp: unknown, now: number): number | null {
  if (typeof timestamp !== 'string' || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(timestamp)) return null;
  const age = now - Date.parse(timestamp);
  return Number.isFinite(age) && age >= -CLOCK_SKEW_MS ? Math.max(0, age) : null;
}

export function hasFreshDevicePresence(device: DevicePresence, now: number): boolean {
  if (device.status !== 'online' && device.status !== 'busy') return false;
  const age = observationAge(device.last_heartbeat, now);
  return age !== null && age < HEARTBEAT_MAX_AGE_MS;
}

export function getObservedDeviceStatus(device: DevicePresence, now: number): Device['status'] {
  if ((device.status === 'online' || device.status === 'busy') && !hasFreshDevicePresence(device, now)) return 'unknown';
  return device.status;
}

export function getDeviceAccess(device: DeviceAccess, now: number) {
  // The legacy ADB flag has no per-device receipt time or observation owner.
  const adb = { label: 'Не подтверждён', detail: 'ADB · источник измерения канала не подключён.' };

  const age = observationAge(device.vpn_observed_at, now);
  const maxAge = device.vpn_observation_max_age_seconds;
  const deadline = typeof maxAge === 'number' && Number.isSafeInteger(maxAge) && maxAge > 0
    ? Math.min(maxAge * 1000, HEARTBEAT_MAX_AGE_MS) : null;
  const observedAt = age !== null && device.vpn_observed_at ? new Date(device.vpn_observed_at).toISOString() : null;
  const source = 'VPN по отчёту APK. Трафик и внешний IP не проверены.';
  const detail = observedAt ? `${source} · ${observedAt}` : source;

  if (device.vpn_observation_state === 'stale' || (device.vpn_observation_state === 'fresh'
    && age !== null && deadline !== null && age >= deadline)) {
    return { adb, vpn: { label: 'Отчёт устарел', detail, observedAt, positive: false } };
  }
  if (hasFreshDevicePresence(device, now) && device.vpn_observation_state === 'fresh' && age !== null && deadline !== null
    && typeof device.vpn_active === 'boolean') {
    return { adb, vpn: { label: device.vpn_active ? 'Активен' : 'Не активен', detail, observedAt, positive: device.vpn_active } };
  }
  return { adb, vpn: { label: 'Не подтверждён', detail: `${detail} · нет актуального подтверждения.`, observedAt, positive: false } };
}
