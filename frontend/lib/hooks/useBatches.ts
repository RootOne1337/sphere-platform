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
