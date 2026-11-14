import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface PipelineRunSummary {
  id: string;
  pipeline_id: string;
  device_id: string;
  status: string;
  cancel_requested_at?: string | null;
  current_step_id: string | null;
  current_task_id: string | null;
}

export function useActivePipelineRuns(deviceId?: string, enabled = true) {
  const params = { active_only: true, per_page: 10, ...(deviceId ? { device_id: deviceId } : {}) };
  return useQuery<{ items: PipelineRunSummary[]; total: number }>({
    queryKey: ['pipeline-runs', params],
    queryFn: async () => {
      const { data } = await api.get('/pipelines/runs', {
        params,
      });
      return data;
    },
    enabled,
    refetchInterval: 10_000,
  });
}
