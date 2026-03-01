import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface Device {
  id: string;
  name: string;
  android_id: string;
  model: string;
  device_model: string | null;
  android_version: string;
  tags: string[];
  group_id: string | null;
  group_name: string | null;
  status: 'online' | 'offline' | 'unknown';
  battery_level: number | null;
  cpu_usage: number | null;
  ram_usage_mb: number | null;
  screen_on: boolean | null;
  last_seen: string | null;
  last_heartbeat: string | null;
  adb_connected: boolean;
  vpn_assigned: boolean;
  vpn_active: boolean | null;
}

interface DevicesResponse {
  items: Device[];
  total: number;
  page: number;
  page_size: number;
}

export function useDevices(params: {
  page?: number;
  page_size?: number;
  status?: string;
  tags?: string;
  group_id?: string;
  search?: string;
}) {
  const apiParams = {
    ...params,
    per_page: params.page_size,
    page_size: undefined,
  };
  return useQuery<DevicesResponse>({
    queryKey: ['devices', params],
    queryFn: async () => {
      const { data } = await api.get('/devices', { params: apiParams });
      return data;
    },
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export function useBulkAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      device_ids: string[];
      action: string;
      params?: object;
    }) => {
      const { data } = await api.post('/devices/bulk/action', body);
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['devices'] });
    },
  });
}
