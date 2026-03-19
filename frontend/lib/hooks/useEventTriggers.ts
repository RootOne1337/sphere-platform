// frontend/lib/hooks/useEventTriggers.ts
// ВЛАДЕЛЕЦ: TZ-11+ Event Triggers — React Query хуки для CRUD триггеров событий.
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

// ── Типы ──────────────────────────────────────────────────────────────

export interface EventTrigger {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  event_type_pattern: string;
  pipeline_id: string;
  input_params_template: Record<string, unknown>;
  is_active: boolean;
  cooldown_seconds: number;
  max_triggers_per_hour: number;
  last_triggered_at: string | null;
  total_triggers: number;
  created_at: string;
  updated_at: string;
}

export interface EventTriggerListResponse {
  items: EventTrigger[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface EventTriggerParams {
  page?: number;
  per_page?: number;
  is_active?: boolean;
  event_type_pattern?: string;
  pipeline_id?: string;
}

export interface CreateEventTriggerInput {
  name: string;
  description?: string;
  event_type_pattern: string;
  pipeline_id: string;
  input_params_template?: Record<string, unknown>;
  cooldown_seconds?: number;
  max_triggers_per_hour?: number;
}

export interface UpdateEventTriggerInput {
  name?: string;
  description?: string;
  event_type_pattern?: string;
  pipeline_id?: string;
  input_params_template?: Record<string, unknown>;
  is_active?: boolean;
  cooldown_seconds?: number;
  max_triggers_per_hour?: number;
}

// ── Хуки ──────────────────────────────────────────────────────────────

const QUERY_KEY = 'event-triggers';

/** Список триггеров с пагинацией и фильтрацией */
export function useEventTriggers(params: EventTriggerParams = {}) {
  return useQuery<EventTriggerListResponse>({
    queryKey: [QUERY_KEY, params],
    queryFn: async () => {
      const { data } = await api.get('/event-triggers', { params });
      return data;
    },
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}

/** Создать триггер */
export function useCreateEventTrigger() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: CreateEventTriggerInput) => {
      const { data } = await api.post('/event-triggers', input);
      return data as EventTrigger;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: [QUERY_KEY] }),
  });
}

/** Обновить триггер */
export function useUpdateEventTrigger() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: UpdateEventTriggerInput & { id: string }) => {
      const { data } = await api.patch(`/event-triggers/${id}`, body);
      return data as EventTrigger;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: [QUERY_KEY] }),
  });
}

/** Переключить is_active */
export function useToggleEventTrigger() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await api.post(`/event-triggers/${id}/toggle`);
      return data as EventTrigger;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: [QUERY_KEY] }),
  });
}

/** Удалить триггер */
export function useDeleteEventTrigger() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/event-triggers/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: [QUERY_KEY] }),
  });
}
