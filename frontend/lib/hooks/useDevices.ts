import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface Device {
  id: string;
  name: string;
  android_id: string;
  model: string | null;
  device_model: string | null;
  android_version: string | null;
  tags: string[];
  group_id: string | null;
  group_ids: string[];
  group_name: string | null;
  location_ids: string[];
  status: 'online' | 'offline' | 'connecting' | 'busy' | 'error' | 'maintenance' | 'unknown';
  agent_version?: string | null;
  agent_version_code?: number | null;
  battery_level: number | null;
  cpu_usage: number | null;
  ram_usage_mb: number | null;
  screen_on: boolean | null;
  last_seen: string | null;
  last_heartbeat: string | null;
  connected_since?: string | null;
  adb_connected: boolean;
  vpn_assigned: boolean;
  vpn_active: boolean | null;
  server_name: string | null;
}

export interface BulkActionResponse {
  total: number;
  succeeded: number;
  failed: number;
  results: Array<{ device_id: string; success: boolean; error: string | null }>;
}

interface DevicesResponse {
  items: Device[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  scope_total?: number | null;
  as_of?: string | null;
  status_counts?: {
    online: number;
    busy: number;
    connecting: number;
    offline: number;
    issues: number;
  };
  presence_available?: boolean;
}

export function useDevices(params: {
  page?: number;
  page_size?: number;
  status?: string;
  live_status?: 'online' | 'busy' | 'connecting' | 'offline' | 'attention';
  tags?: string;
  type?: string;
  group_id?: string;
  location_id?: string;
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
      // The API contract names this field `per_page`; keep `page_size` as the
      // stable frontend shape used by existing device screens.
      const payload = data as DevicesResponse & { per_page?: number };
      const pageSize = payload.page_size ?? payload.per_page ?? params.page_size ?? 50;
      return {
        ...payload,
        page_size: pageSize,
        pages: payload.pages ?? Math.ceil(payload.total / pageSize),
      };
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
    }): Promise<BulkActionResponse> => {
      const { data } = await api.post('/devices/bulk/action', body);
      return data as BulkActionResponse;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['devices'] });
    },
  });
}

export function useUpdateDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: { id: string; name?: string; tags?: string[]; is_active?: boolean; notes?: string; server_name?: string | null }) => {
      const { data } = await api.put(`/devices/${id}`, body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['devices'] }),
  });
}

export function useDeleteDevice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deviceId: string) => api.delete(`/devices/${deviceId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['devices'] }),
  });
}

/** Массовое удаление устройств одним запросом. Бекенд: DELETE /devices/bulk */
export function useBulkDeleteDevices() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (deviceIds: string[]) => {
      const { data } = await api.delete('/devices/bulk', { data: { device_ids: deviceIds } });
      return data as { deleted: number };
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['devices'] }),
  });
}
