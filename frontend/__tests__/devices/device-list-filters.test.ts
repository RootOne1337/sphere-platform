import type { Device } from '@/lib/hooks/useDevices';
import { countDeviceStatuses, filterDevicesByStatus, scopeDevices } from '@/src/features/devices/deviceListFilters';

function makeDevice(
  id: string,
  status: Device['status'],
  options: Partial<Device> = {},
): Device {
  return {
    id,
    name: id,
    android_id: `android-${id}`,
    model: 'LDPlayer',
    device_model: null,
    android_version: '9',
    tags: [],
    group_id: null,
    group_ids: [],
    group_name: null,
    location_ids: [],
    status,
    battery_level: null,
    cpu_usage: null,
    ram_usage_mb: null,
    screen_on: null,
    last_seen: null,
    last_heartbeat: null,
    adb_connected: false,
    vpn_assigned: false,
    vpn_active: null,
    server_name: null,
    ...options,
  };
}

const devices = [
  makeDevice('online-1', 'online', { group_id: 'group-a', location_ids: ['loc-1'] }),
  makeDevice('busy-1', 'busy', { group_ids: ['group-a'], location_ids: ['loc-1'] }),
  makeDevice('connecting-1', 'connecting', { group_id: 'group-b', location_ids: ['loc-2'] }),
  makeDevice('offline-1', 'offline', { group_id: 'group-a', location_ids: ['loc-2'] }),
  makeDevice('error-1', 'error'),
  makeDevice('unknown-1', 'unknown'),
  makeDevice('maintenance-1', 'maintenance'),
];

it('scopes the same real device set by group and location, including secondary groups', () => {
  expect(scopeDevices(devices, 'group-a', 'loc-1').map(({ id }) => id)).toEqual(['online-1', 'busy-1']);
  expect(scopeDevices(devices, '__all__', 'loc-2').map(({ id }) => id)).toEqual(['connecting-1', 'offline-1']);
});

it('keeps fleet status totals honest when busy overlaps the online view', () => {
  expect(countDeviceStatuses(devices)).toEqual({
    online: 2,
    busy: 1,
    connecting: 1,
    offline: 1,
    issues: 3,
  });
  expect(filterDevicesByStatus(devices, 'online').map(({ id }) => id)).toEqual(['online-1', 'busy-1']);
  expect(filterDevicesByStatus(devices, 'busy').map(({ id }) => id)).toEqual(['busy-1']);
});

it('separates handshake, offline and attention states from healthy devices', () => {
  expect(filterDevicesByStatus(devices, 'connecting').map(({ id }) => id)).toEqual(['connecting-1']);
  expect(filterDevicesByStatus(devices, 'offline').map(({ id }) => id)).toEqual(['offline-1']);
  expect(filterDevicesByStatus(devices, 'attention').map(({ id }) => id)).toEqual(['error-1', 'unknown-1', 'maintenance-1']);
  expect(filterDevicesByStatus(devices, 'all')).toHaveLength(devices.length);
});
