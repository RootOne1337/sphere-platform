import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface Task {
  id: string;
  org_id: string;
  script_id: string;
  device_id: string;
  script_version_id: string | null;
  batch_id: string | null;
  status: string;
  priority: number;
  started_at: string | null;
  finished_at: string | null;
  wave_index: number | null;
  created_at: string;
  updated_at: string;
}

export interface TaskDetail extends Task {
  result: Record<string, unknown> | null;
  error_message: string | null;
  input_params: Record<string, unknown> | null;
}

export interface NodeExecutionLog {
  node_id: string;
  action_type: string;
  success: boolean;
  duration_ms: number;
  started_at: string | null;
  screenshot_key: string | null;
  error: string | null;
  output: unknown;
}

interface TasksResponse {
  items: Task[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export function useTasks(params: {
  page?: number;
  per_page?: number;
  status?: string;
  device_id?: string;
  script_id?: string;
  batch_id?: string;
}) {
  return useQuery<TasksResponse>({
    queryKey: ['tasks', params],
    queryFn: async () => {
      const { data } = await api.get('/tasks', { params });
      return data;
    },
    refetchInterval: 10_000,
  });
}

export function useTask(taskId: string) {
  return useQuery<TaskDetail>({
    queryKey: ['tasks', taskId],
    queryFn: async () => {
      const { data } = await api.get(`/tasks/${taskId}`);
      return data;
    },
    enabled: !!taskId,
    refetchInterval: 5_000,
  });
}

export function useTaskLogs(taskId: string) {
  return useQuery<NodeExecutionLog[]>({
    queryKey: ['tasks', taskId, 'logs'],
    queryFn: async () => {
      const { data } = await api.get(`/tasks/${taskId}/logs`);
      return data;
    },
    enabled: !!taskId,
    refetchInterval: 5_000,
  });
}

export interface TaskProgress {
  nodes_done: number;
  total_nodes: number;
  current_node: string;
  progress: number;
  cycles: number;
  started_at: number | null;
}

export function useTaskProgress(taskId: string, enabled: boolean) {
  return useQuery<TaskProgress>({
    queryKey: ['tasks', taskId, 'progress'],
    queryFn: async () => {
      const { data } = await api.get(`/tasks/${taskId}/progress`);
      return data;
    },
    enabled: enabled && !!taskId,
    refetchInterval: 2_000,
  });
}

export interface LiveLogEntry {
  node_id: string;
  nodes_done: number;
  ts: number;
}

export function useTaskLiveLogs(taskId: string, enabled: boolean) {
  return useQuery<LiveLogEntry[]>({
    queryKey: ['tasks', taskId, 'live-logs'],
    queryFn: async () => {
      const { data } = await api.get(`/tasks/${taskId}/live-logs`);
      return data;
    },
    enabled: enabled && !!taskId,
    refetchInterval: 3_000,
  });
}

export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      script_id: string;
      device_id: string;
      priority?: number;
    }) => {
      const { data } = await api.post('/tasks', body);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  });
}

export function useCancelTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (taskId: string) => {
      await api.delete(`/tasks/${taskId}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  });
}

export function useStopTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (taskId: string) => {
      const { data } = await api.post(`/tasks/${taskId}/stop`);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  });
}
