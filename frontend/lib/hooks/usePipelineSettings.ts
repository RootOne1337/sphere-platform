import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { toast } from 'sonner';

// ── Типы ────────────────────────────────────────────────────────────────────

export interface PipelineSettings {
  id: string;
  org_id: string;

  // Главные переключатели
  orchestration_enabled: boolean;
  scheduler_enabled: boolean;

  // Регистрация
  registration_enabled: boolean;
  max_concurrent_registrations: number;
  registration_script_id: string | null;
  registration_timeout_seconds: number;

  // Фарм
  farming_enabled: boolean;
  max_concurrent_farming: number;
  farming_script_id: string | null;
  farming_session_duration_seconds: number;

  // Уровни
  default_target_level: number;
  cooldown_between_sessions_minutes: number;

  // Ники
  nick_generation_enabled: boolean;
  nick_pattern: string;

  // Мониторинг
  ban_detection_enabled: boolean;
  auto_replace_banned: boolean;

  // Мета
  notes: string | null;
  meta: Record<string, unknown>;

  created_at: string;
  updated_at: string;
}

export interface OrchestrationStatus {
  orchestration_enabled: boolean;
  scheduler_enabled: boolean;
  registration_enabled: boolean;
  farming_enabled: boolean;
  active_registrations: number;
  active_farming_sessions: number;
  pending_registrations: number;
  total_devices_with_server: number;
  total_free_accounts: number;
  total_banned_accounts: number;
  registrations_completed: number;
  registrations_failed: number;
  bans_detected: number;
}

export interface ServerInfo {
  id: number;
  name: string;
  domain: string;
  port: number;
}

// ── Запросы ─────────────────────────────────────────────────────────────────

/** Получить настройки оркестрации */
export function usePipelineSettings() {
  return useQuery<PipelineSettings>({
    queryKey: ['pipeline-settings'],
    queryFn: async () => {
      const { data } = await api.get('/pipeline-settings');
      return data;
    },
    staleTime: 10_000,
  });
}

/** Обновить настройки (partial update) */
export function useUpdatePipelineSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (updates: Partial<PipelineSettings>) => {
      const { data } = await api.patch('/pipeline-settings', updates);
      return data as PipelineSettings;
    },
    onSuccess: (data) => {
      qc.setQueryData(['pipeline-settings'], data);
      toast.success('Настройки сохранены');
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Ошибка сохранения настроек');
    },
  });
}

/** Переключить отдельную функцию */
export function useTogglePipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      feature,
      enabled,
    }: {
      feature: 'orchestration' | 'scheduler' | 'registration' | 'farming';
      enabled: boolean;
    }) => {
      const { data } = await api.post(`/pipeline-settings/toggle/${feature}`, { enabled });
      return data as PipelineSettings;
    },
    onSuccess: (data) => {
      qc.setQueryData(['pipeline-settings'], data);
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Ошибка переключения');
    },
  });
}

/** Текущий runtime-статус оркестрации */
export function useOrchestrationStatus() {
  return useQuery<OrchestrationStatus>({
    queryKey: ['orchestration-status'],
    queryFn: async () => {
      const { data } = await api.get('/pipeline-settings/status');
      return data;
    },
    staleTime: 5_000,
    refetchInterval: 10_000,
  });
}

/** Список игровых серверов */
export function useGameServers() {
  return useQuery<ServerInfo[]>({
    queryKey: ['game-servers'],
    queryFn: async () => {
      const { data } = await api.get('/pipeline-settings/servers');
      return data;
    },
    staleTime: 300_000,
  });
}

/** Генерация никнеймов */
export function useGenerateNicks() {
  return useMutation({
    mutationFn: async (params: { count?: number; pattern?: string; gender?: string }) => {
      const { data } = await api.post('/pipeline-settings/nick/generate', params);
      return data as { nicknames: string[] };
    },
    onError: (err: any) => {
      toast.error(err?.response?.data?.detail || 'Ошибка генерации ников');
    },
  });
}

/** Проверить доступность никнейма */
export function useCheckNick() {
  return useMutation({
    mutationFn: async (nickname: string) => {
      const { data } = await api.post('/pipeline-settings/nick/check', { nickname });
      return data as { nickname: string; available: boolean };
    },
  });
}
