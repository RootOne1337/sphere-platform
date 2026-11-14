import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface Batch {
  id: string;
  org_id: string;
  script_id: string;
  name: string | null;
  status: string;
  total: number;
  succeeded: number;
  failed: number;
  wave_config: Record<string, unknown>;
  script_version_id?: string | null;
  next_wave_index?: number;
  next_wave_at?: string | null;
  admission_state?: 'pending' | 'submitted' | 'cancelled' | 'legacy_unknown' | 'review_required';
  created_at: string;
  updated_at: string;
}

export const batchTargetStates = [
  'pending_admission', 'queued', 'assigned', 'running', 'completed', 'failed',
  'timeout', 'cancelled', 'rejected', 'not_admitted_cancelled', 'unknown',
] as const;

export type BatchTargetState = typeof batchTargetStates[number];

export interface BatchTarget {
  device_id: string;
  device_name: string | null;
  wave_index: number;
  state: BatchTargetState;
  task_id: string | null;
  admission_http_status: number | null;
  cancel_requested_at: string | null;
  timeout_requested_at: string | null;
}

export interface BatchSummary extends Batch {
  script_name: string | null;
  wave_count: number | null;
}

export interface BatchDetail extends BatchSummary {
  targets: BatchTarget[] | null;
  target_counts: Partial<Record<BatchTargetState, number>> | null;
}

interface BatchList {
  items: BatchSummary[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export function useBatchList(page: number) {
  return useQuery({
    queryKey: ['batches', 'list', page],
    queryFn: async ({ signal }) => {
      const { data } = await api.get<BatchList>('/batches', { params: { page, per_page: 25 }, signal });
      return data;
    },
    refetchInterval: 10_000,
  });
}

export function useStartBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      script_id: string;
      expected_current_version_id?: string;
      device_ids: string[];
      wave_size?: number;
      wave_delay_ms?: number;
      name?: string;
      priority?: number;
    }) => {
      const { data } = await api.post('/batches', body);
      return data as Batch;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] });
      qc.invalidateQueries({ queryKey: ['batches'] });
    },
  });
}

export function useBatch(batchId: string) {
  return useQuery<BatchDetail>({
    queryKey: ['batches', batchId],
    queryFn: async ({ signal }) => {
      const { data } = await api.get<BatchDetail>(`/batches/${encodeURIComponent(batchId)}`, { signal });
      return data;
    },
    enabled: !!batchId,
    refetchInterval: 5_000,
  });
}

export function useCancelBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (batchId: string) => {
      await api.delete(`/batches/${batchId}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['batches'] });
      qc.invalidateQueries({ queryKey: ['tasks'] });
    },
  });
}

/** Ответ broadcast-эндпоинта — батч + кол-во онлайн-устройств */
export interface BroadcastBatchResponse extends Batch {
  online_devices: number;
}

/**
 * Запуск скрипта на ВСЕХ онлайн-устройствах организации.
 * Бэкенд автоматически определяет онлайн-устройства через Redis status cache.
 */
export function useBroadcastBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      script_id: string;
      expected_current_version_id?: string;
      wave_size?: number;
      wave_delay_ms?: number;
      jitter_ms?: number;
      priority?: number;
      name?: string;
    }) => {
      const { data } = await api.post('/batches/broadcast', body);
      return data as BroadcastBatchResponse;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] });
      qc.invalidateQueries({ queryKey: ['batches'] });
    },
  });
}
