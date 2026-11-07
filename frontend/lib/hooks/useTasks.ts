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
  cancel_requested_at?: string | null;
  timeout_requested_at?: string | null;
  wave_index: number | null;
  created_at: string;
  updated_at: string;
  device_name: string | null;
  script_name: string | null;
}

export interface TaskDetail extends Task {
  result: Record<string, unknown> | null;
  error_message: string | null;
  input_params: Record<string, unknown> | null;
  device_name: string | null;
  script_name: string | null;
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

export interface TasksResponse {
  items: Task[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
  status_counts?: Record<string, number> | null;
}

export function useTasks(params: {
  page?: number;
  per_page?: number;
  status?: string;
  device_id?: string;
  script_id?: string;
  batch_id?: string;
  search?: string;
  sort_by?: 'created_at' | 'script_name' | 'status' | 'priority';
  sort_dir?: 'asc' | 'desc';
  active_only?: boolean;
  include_counts?: boolean;
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

export function useTask(taskId: string, enabled = true) {
  return useQuery<TaskDetail>({
    queryKey: ['tasks', taskId],
    queryFn: async ({ signal }) => {
      const { data } = await api.get(`/tasks/${taskId}`, { signal });
      if (!data || data.id !== taskId) throw new Error('Ответ API относится к другому заданию');
      return data;
    },
    enabled: enabled && !!taskId,
    refetchInterval: 5_000,
  });
}

export function useTaskLogs(taskId: string, enabled = true) {
  return useQuery<NodeExecutionLog[]>({
    queryKey: ['tasks', taskId, 'logs'],
    queryFn: async ({ signal }) => {
      const { data } = await api.get(`/tasks/${taskId}/logs`, { signal });
      if (!Array.isArray(data)) throw new Error('Некорректный ответ журнала задания');
      return data;
    },
    enabled: enabled && !!taskId,
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

export interface TaskScreenshotReference {
  key: string;
  url: string | null;
  unavailable_reason: string | null;
}

export function useTaskScreenshots(taskId: string, enabled: boolean) {
  return useQuery<{ task_id: string; screenshots: TaskScreenshotReference[] }>({
    queryKey: ['tasks', taskId, 'screenshots'], enabled: enabled && !!taskId, retry: false,
    queryFn: async ({ signal }) => {
      const { data } = await api.get(`/tasks/${taskId}/screenshots`, { signal });
      if (!data || data.task_id !== taskId || !Array.isArray(data.screenshots)) throw new Error('Некорректный манифест снимков задания');
      for (const entry of data.screenshots) {
        if (!entry || typeof entry.key !== 'string'
          || !(entry.url === null || entry.url === `/tasks/${taskId}/screenshots/content?key=${encodeURIComponent(entry.key)}`)
          || !(entry.unavailable_reason === null || typeof entry.unavailable_reason === 'string')) {
          throw new Error('Некорректная ссылка на снимок задания');
        }
      }
      return data;
    },
  });
}

export function useTaskProgress(taskId: string, enabled: boolean) {
  return useQuery<TaskProgress>({
    queryKey: ['tasks', taskId, 'progress'],
    queryFn: async ({ signal }) => {
      const { data } = await api.get(`/tasks/${taskId}/progress`, { signal });
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
    queryFn: async ({ signal }) => {
      const { data } = await api.get(`/tasks/${taskId}/live-logs`, { signal });
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
      expected_current_version_id?: string;
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

/** The server owns the original pinned version, inputs and execution checks. */
export function useRetryTask() {
  const qc = useQueryClient();
  return useMutation({
    retry: false,
    mutationFn: async (taskId: string) => {
      const { data } = await api.post(`/tasks/${taskId}/rerun`);
      return data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  });
}
