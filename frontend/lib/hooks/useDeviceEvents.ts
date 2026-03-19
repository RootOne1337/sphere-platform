// frontend/lib/hooks/useDeviceEvents.ts
// ВЛАДЕЛЕЦ: TZ-11 Device Events — React Query хуки для событий устройств.
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

// ── Типы ──────────────────────────────────────────────────────────────

export type EventSeverity = 'debug' | 'info' | 'warning' | 'error' | 'critical';

export interface DeviceEvent {
  id: string;
  org_id: string;
  device_id: string;
  device_name: string | null;
  event_type: string;
  severity: EventSeverity;
  message: string | null;
  account_id: string | null;
  account_login: string | null;
  task_id: string | null;
  pipeline_run_id: string | null;
  data: Record<string, unknown>;
  occurred_at: string;
  processed: boolean;
  created_at: string;
  updated_at: string;
}

export interface DeviceEventListResponse {
  items: DeviceEvent[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface EventStats {
  total: number;
  by_severity: Record<string, number>;
  by_type: Record<string, number>;
  unprocessed: number;
}

export interface DeviceEventParams {
  page?: number;
  per_page?: number;
  device_id?: string;
  event_type?: string;
  severity?: string;
  account_id?: string;
  processed?: boolean;
  search?: string;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
}

export interface CreateDeviceEventInput {
  device_id: string;
  event_type: string;
  severity?: string;
  message?: string;
  account_id?: string;
  task_id?: string;
  pipeline_run_id?: string;
  data?: Record<string, unknown>;
  occurred_at?: string;
}

// ── Хуки ──────────────────────────────────────────────────────────────

export function useDeviceEvents(params: DeviceEventParams) {
  return useQuery<DeviceEventListResponse>({
    queryKey: ['device-events', params],
    queryFn: async () => {
      const { data } = await api.get('/device-events', { params });
      return data;
    },
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}

export function useDeviceEvent(id: string | null) {
  return useQuery<DeviceEvent>({
    queryKey: ['device-events', id],
    queryFn: async () => {
      const { data } = await api.get(`/device-events/${id}`);
      return data;
    },
    enabled: !!id,
  });
}

export function useEventStats(deviceId?: string) {
  return useQuery<EventStats>({
    queryKey: ['device-events', 'stats', deviceId],
    queryFn: async () => {
      const params = deviceId ? { device_id: deviceId } : {};
      const { data } = await api.get('/device-events/stats', { params });
      return data;
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useCreateDeviceEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CreateDeviceEventInput) => {
      const { data } = await api.post('/device-events', body);
      return data as DeviceEvent;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['device-events'] });
    },
  });
}

export function useMarkEventProcessed() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (eventId: string) => {
      await api.post(`/device-events/${eventId}/processed`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['device-events'] });
    },
  });
}
