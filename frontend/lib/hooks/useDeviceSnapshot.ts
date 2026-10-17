import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Device } from './useDevices';

export type DeviceSnapshot = Partial<Omit<Device, 'id' | 'name' | 'status'>> & {
  id: string;
  name: string;
  status: Device['status'];
  serial?: string | null;
  type?: string | null;
  notes?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export function validateDeviceSnapshot(value: unknown, expectedId: string): DeviceSnapshot {
  if (!value || typeof value !== 'object') throw new Error('Некорректная карточка устройства.');
  const data = value as DeviceSnapshot;
  if (data.id !== expectedId || typeof data.name !== 'string' || typeof data.status !== 'string') {
    throw new Error('API вернул карточку другого устройства или некорректный ответ.');
  }
  for (const field of ['serial', 'android_id', 'model', 'device_model', 'android_version', 'agent_version', 'group_name', 'server_name', 'notes', 'last_seen', 'last_heartbeat', 'connected_since', 'created_at', 'updated_at'] as const) {
    if (data[field] != null && typeof data[field] !== 'string') throw new Error('Некорректное поле карточки устройства.');
  }
  for (const field of ['group_ids', 'location_ids'] as const) {
    if (data[field] != null && (!Array.isArray(data[field]) || data[field]?.some((id) => typeof id !== 'string'))) throw new Error('Некорректные группы или локации.');
  }
  const statuses: string[] = ['online', 'offline', 'busy', 'connecting', 'error', 'maintenance', 'unknown'];
  return {
    ...data,
    status: statuses.includes(data.status) ? data.status : 'unknown',
    tags: Array.isArray(data.tags) ? data.tags.filter((tag): tag is string => typeof tag === 'string') : [],
  };
}

export function useDeviceSnapshot(deviceId: string) {
  return useQuery<DeviceSnapshot>({
    queryKey: ['devices', deviceId],
    queryFn: async ({ signal }) => {
      const { data } = await api.get<unknown>(`/devices/${encodeURIComponent(deviceId)}`, { signal });
      return validateDeviceSnapshot(data, deviceId);
    },
    enabled: !!deviceId,
    staleTime: 10_000,
    refetchInterval: 15_000,
    refetchOnMount: 'always',
    retry: false,
  });
}
