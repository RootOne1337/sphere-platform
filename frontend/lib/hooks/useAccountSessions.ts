// frontend/lib/hooks/useAccountSessions.ts
// ВЛАДЕЛЕЦ: TZ-11 Account Sessions — React Query хуки для истории сессий аккаунтов.
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

// ── Типы ──────────────────────────────────────────────────────────────

export type SessionEndReason =
  | 'completed'
  | 'banned'
  | 'captcha'
  | 'error'
  | 'manual'
  | 'rotation'
  | 'timeout'
  | 'device_offline';

export interface AccountSession {
  id: string;
  org_id: string;
  account_id: string;
  account_login: string | null;
  account_game: string | null;
  device_id: string;
  device_name: string | null;
  started_at: string;
  ended_at: string | null;
  end_reason: SessionEndReason | null;
  error_message: string | null;
  script_id: string | null;
  task_id: string | null;
  pipeline_run_id: string | null;
  nodes_executed: number;
  errors_count: number;
  level_before: number | null;
  level_after: number | null;
  balance_before: number | null;
  balance_after: number | null;
  duration_seconds: number | null;
  meta: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface AccountSessionListResponse {
  items: AccountSession[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface SessionStats {
  total_sessions: number;
  active_sessions: number;
  avg_duration_seconds: number | null;
  by_end_reason: Record<string, number>;
  total_nodes_executed: number;
  total_errors: number;
}

export interface AccountSessionParams {
  page?: number;
  per_page?: number;
  account_id?: string;
  device_id?: string;
  end_reason?: string;
  active_only?: boolean;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
}

export interface StartSessionInput {
  account_id: string;
  device_id: string;
  script_id?: string;
  task_id?: string;
  pipeline_run_id?: string;
  meta?: Record<string, unknown>;
}

export interface EndSessionInput {
  id: string;
  end_reason: string;
  error_message?: string;
  nodes_executed?: number;
  errors_count?: number;
  level_after?: number;
  balance_after?: number;
  meta?: Record<string, unknown>;
}

// ── Хуки ──────────────────────────────────────────────────────────────

export function useAccountSessions(params: AccountSessionParams) {
  return useQuery<AccountSessionListResponse>({
    queryKey: ['account-sessions', params],
    queryFn: async () => {
      const { data } = await api.get('/account-sessions', { params });
      return data;
    },
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

export function useAccountSession(id: string | null) {
  return useQuery<AccountSession>({
    queryKey: ['account-sessions', id],
    queryFn: async () => {
      const { data } = await api.get(`/account-sessions/${id}`);
      return data;
    },
    enabled: !!id,
  });
}

export function useSessionStats(accountId?: string, deviceId?: string) {
  return useQuery<SessionStats>({
    queryKey: ['account-sessions', 'stats', accountId, deviceId],
    queryFn: async () => {
      const params: Record<string, string> = {};
      if (accountId) params.account_id = accountId;
      if (deviceId) params.device_id = deviceId;
      const { data } = await api.get('/account-sessions/stats', { params });
      return data;
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useStartSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: StartSessionInput) => {
      const { data } = await api.post('/account-sessions', body);
      return data as AccountSession;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['account-sessions'] });
    },
  });
}

export function useEndSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: EndSessionInput) => {
      const { data } = await api.post(`/account-sessions/${id}/end`, body);
      return data as AccountSession;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['account-sessions'] });
      qc.invalidateQueries({ queryKey: ['game-accounts'] });
    },
  });
}
