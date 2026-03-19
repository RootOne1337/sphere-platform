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
  created_at: string;
  updated_at: string;
}

export function useStartBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      script_id: string;
      device_ids: string[];
      wave_size?: number;
      wave_delay_ms?: number;
      name?: string;
      priority?: number;
    }) => {
      const { data } = await api.post('/batches', body);
      return data as Batch;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  });
}

export function useBatch(batchId: string) {
  return useQuery<Batch>({
    queryKey: ['batches', batchId],
    queryFn: async () => {
      const { data } = await api.get(`/batches/${batchId}`);
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ['batches'] }),
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
