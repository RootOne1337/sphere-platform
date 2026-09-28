import type { Device } from '@/lib/hooks/useDevices';

export type DeviceStatusFilter = 'all' | 'online' | 'busy' | 'connecting' | 'offline' | 'attention';

export interface DeviceStatusCounts {
  online: number;
  busy: number;
  connecting: number;
  offline: number;
  issues: number;
}

export function scopeDevices(
  devices: Device[],
  groupId: string,
  locationId: string,
): Device[] {
  return devices.filter((device) => {
    const matchesGroup = !groupId || groupId === '__all__'
      || device.group_id === groupId
      || device.group_ids?.includes(groupId);
    const matchesLocation = !locationId || locationId === '__all__'
      || device.location_ids?.includes(locationId);
    return matchesGroup && matchesLocation;
  });
}

export function countDeviceStatuses(devices: Device[]): DeviceStatusCounts {
  return {
    online: devices.filter((device) => device.status === 'online' || device.status === 'busy').length,
    busy: devices.filter((device) => device.status === 'busy').length,
    connecting: devices.filter((device) => device.status === 'connecting').length,
    offline: devices.filter((device) => device.status === 'offline').length,
    issues: devices.filter((device) => device.status === 'error' || device.status === 'unknown' || device.status === 'maintenance').length,
  };
}

export function filterDevicesByStatus(devices: Device[], status: DeviceStatusFilter): Device[] {
  if (status === 'all') return devices;
  if (status === 'online') return devices.filter((device) => device.status === 'online' || device.status === 'busy');
  if (status === 'busy') return devices.filter((device) => device.status === 'busy');
  if (status === 'connecting') return devices.filter((device) => device.status === 'connecting');
  if (status === 'offline') return devices.filter((device) => device.status === 'offline');
  return devices.filter((device) => device.status === 'error' || device.status === 'unknown' || device.status === 'maintenance');
}
