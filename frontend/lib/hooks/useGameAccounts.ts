import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

// ── Типы ─────────────────────────────────────────────────────────────────────

export type AccountStatus =
  | 'free'
  | 'in_use'
  | 'cooldown'
  | 'banned'
  | 'captcha'
  | 'phone_verify'
  | 'disabled'
  | 'archived'
  | 'pending_registration';

export interface GameAccount {
  id: string;
  org_id: string;
  game: string;
  login: string;
  password?: string;
  status: AccountStatus;
  status_reason: string | null;
  status_changed_at: string | null;
  device_id: string | null;
  device_name: string | null;
  assigned_at: string | null;
  // Игровой сервер и персонаж
  server_name: string | null;
  nickname: string | null;
  gender: 'male' | 'female' | null;
  // Игровая статистика
  level: number | null;
  target_level: number | null;
  experience: number | null;
  balance_rub: number | null;
  balance_bc: number | null;
  last_balance_update: string | null;
  is_leveled: boolean;
  // VIP и законопослушность
  vip_type: string | null;
  vip_expires_at: string | null;
  lawfulness: number | null;
  // Статистика
  total_bans: number;
  last_ban_at: string | null;
  ban_reason: string | null;
  total_sessions: number;
  last_session_end: string | null;
  cooldown_until: string | null;
  // Регистрационные данные
  registered_at: string | null;
  registration_provider: string | null;
  meta: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface GameAccountListResponse {
  items: GameAccount[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface AccountStats {
  total: number;
  free: number;
  in_use: number;
  cooldown: number;
  banned: number;
  captcha: number;
  phone_verify: number;
  disabled: number;
  archived: number;
  pending_registration: number;
  leveled: number;
  games: string[];
  servers: string[];
}

export interface ServerInfo {
  id: number;
  name: string;
  domain: string;
  port: number;
}

export interface ImportResult {
  created: number;
  skipped: number;
  errors: string[];
}

// ── Параметры запроса ────────────────────────────────────────────────────────

export interface GameAccountParams {
  page?: number;
  per_page?: number;
  game?: string;
  status?: string;
  device_id?: string;
  server_name?: string;
  search?: string;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
}

// ── Хуки ─────────────────────────────────────────────────────────────────────

/** Список аккаунтов с пагинацией и фильтрами */
export function useGameAccounts(params: GameAccountParams) {
  return useQuery<GameAccountListResponse>({
    queryKey: ['game-accounts', params],
    queryFn: async () => {
      const { data } = await api.get('/game-accounts', { params });
      return data;
    },
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

/** Один аккаунт по ID */
export function useGameAccount(id: string | null, showPassword = false) {
  return useQuery<GameAccount>({
    queryKey: ['game-accounts', id, { showPassword }],
    queryFn: async () => {
      const { data } = await api.get(`/game-accounts/${id}`, {
        params: { show_password: showPassword },
      });
      return data;
    },
    enabled: !!id,
  });
}

/** Статистика аккаунтов */
export function useAccountStats() {
  return useQuery<AccountStats>({
    queryKey: ['game-accounts', 'stats'],
    queryFn: async () => {
      const { data } = await api.get('/game-accounts/stats');
      return data;
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

/** Список серверов */
export function useServers() {
  return useQuery<{ servers: ServerInfo[]; total: number }>({
    queryKey: ['game-accounts', 'servers'],
    queryFn: async () => {
      const { data } = await api.get('/game-accounts/servers');
      return data;
    },
    staleTime: 300_000,
  });
}

/** Создать аккаунт */
export function useCreateGameAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      game: string;
      login: string;
      password: string;
      server_name?: string;
      nickname?: string;
      gender?: string;
      level?: number;
      target_level?: number;
      balance_rub?: number;
      balance_bc?: number;
      meta?: Record<string, unknown>;
    }) => {
      const { data } = await api.post('/game-accounts', body);
      return data as GameAccount;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['game-accounts'] });
    },
  });
}

/** Обновить аккаунт */
export function useUpdateGameAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      ...body
    }: {
      id: string;
      login?: string;
      password?: string;
      status?: string;
      status_reason?: string;
      server_name?: string;
      nickname?: string;
      level?: number;
      target_level?: number;
      experience?: number;
      balance_rub?: number;
      balance_bc?: number;
      vip_type?: string;
      lawfulness?: number;
      meta?: Record<string, unknown>;
    }) => {
      const { data } = await api.patch(`/game-accounts/${id}`, body);
      return data as GameAccount;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['game-accounts'] });
    },
  });
}

/** Удалить аккаунт */
export function useDeleteGameAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/game-accounts/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['game-accounts'] });
    },
  });
}

/** Назначить аккаунт на устройство */
export function useAssignGameAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, device_id }: { id: string; device_id: string }) => {
      const { data } = await api.post(`/game-accounts/${id}/assign`, { device_id });
      return data as GameAccount;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['game-accounts'] });
    },
  });
}

/** Освободить аккаунт */
export function useReleaseGameAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      cooldown_minutes,
    }: {
      id: string;
      cooldown_minutes?: number;
    }) => {
      const { data } = await api.post(`/game-accounts/${id}/release`, { cooldown_minutes });
      return data as GameAccount;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['game-accounts'] });
    },
  });
}

/** Массовый импорт аккаунтов */
export function useImportGameAccounts() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      accounts: Array<{
        game: string;
        login: string;
        password: string;
        server_name?: string;
        nickname?: string;
        level?: number;
        balance_rub?: number;
        balance_bc?: number;
        meta?: Record<string, unknown>;
      }>;
    }) => {
      const { data } = await api.post('/game-accounts/import', body);
      return data as ImportResult;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['game-accounts'] });
    },
  });
}
