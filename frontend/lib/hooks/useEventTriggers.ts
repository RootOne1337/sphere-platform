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

export const TRIGGER_SIMULATION_REASONS = [
  'eligible', 'pattern_mismatch', 'trigger_disabled', 'pipeline_unavailable', 'cooldown', 'hour_limit',
  'duplicate_event', 'causal_cycle', 'depth_limit', 'root_limit', 'cause_unavailable',
] as const;

type TriggerSimulationReason = (typeof TRIGGER_SIMULATION_REASONS)[number];

export interface TriggerSimulationResult {
  trigger_id: string;
  event_type: string;
  event_id?: string | null;
  event_origin?: 'independent' | 'pipeline' | null;
  root_event_id?: string | null;
  matches: boolean;
  would_admit: boolean;
  reason: TriggerSimulationReason;
  observed_at: string;
  retry_at: string | null;
  recent_runs: number;
  max_triggers_per_hour: number;
  cause_depth?: number | null;
  max_cause_depth?: number;
  root_runs?: number | null;
  max_root_runs?: number;
}

// ── Хуки ──────────────────────────────────────────────────────────────

const QUERY_KEY = 'event-triggers';

const isTimestamp = (value: unknown): value is string =>
  typeof value === 'string' && Number.isFinite(Date.parse(value));
const isCount = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;

/** Read one saved rule on demand. A simulation never updates the trigger catalog. */
export function useSimulateEventTrigger() {
  return useMutation({
    mutationFn: async ({ id, eventType, eventId }: { id: string; eventType?: string; eventId?: string }) => {
      const { data } = await api.get<TriggerSimulationResult>(`/event-triggers/${encodeURIComponent(id)}/simulate`, {
        params: eventId ? { event_id: eventId } : { event_type: eventType },
      });
      if (!data || data.trigger_id !== id || typeof data.event_type !== 'string' || !data.event_type
        || (eventId ? data.event_id !== eventId : data.event_type !== eventType || data.event_id != null)
        || typeof data.matches !== 'boolean' || typeof data.would_admit !== 'boolean'
        || !TRIGGER_SIMULATION_REASONS.includes(data.reason)
        || data.would_admit !== (data.reason === 'eligible') || (data.would_admit && !data.matches)
        || !isTimestamp(data.observed_at) || (data.retry_at !== null && !isTimestamp(data.retry_at))
        || !isCount(data.recent_runs) || !isCount(data.max_triggers_per_hour)
        || (data.event_origin != null && data.event_origin !== 'independent' && data.event_origin !== 'pipeline')
        || (data.root_event_id != null && typeof data.root_event_id !== 'string')
        || (data.cause_depth != null && (!isCount(data.cause_depth) || !isCount(data.max_cause_depth)))
        || (data.root_runs != null && (!isCount(data.root_runs) || !isCount(data.max_root_runs)))) {
        throw new Error('Некорректная квитанция проверки триггера');
      }
      return data;
    },
    retry: false,
    gcTime: 0,
  });
}

/** Список триггеров с пагинацией и фильтрацией */
export function useEventTriggers(params: EventTriggerParams = {}) {
  return useQuery<EventTriggerListResponse>({
    queryKey: [QUERY_KEY, params],
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/event-triggers', { params, signal });
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
    mutationFn: async ({ id, active }: { id: string; active: boolean }) => {
      const { data } = await api.post(`/event-triggers/${id}/toggle`, undefined, { params: { active } });
      if (data?.id !== id || data.is_active !== active) throw new Error('Некорректная квитанция изменения триггера');
      return data as EventTrigger;
    },
    retry: false,
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
