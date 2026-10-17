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

export function useActivePipelineRuns() {
  return useQuery<{ items: PipelineRunSummary[]; total: number }>({
    queryKey: ['pipeline-runs', { active_only: true, per_page: 10 }],
    queryFn: async () => {
      const { data } = await api.get('/pipelines/runs', {
        params: { active_only: true, per_page: 10 },
      });
      return data;
    },
    refetchInterval: 10_000,
  });
}
