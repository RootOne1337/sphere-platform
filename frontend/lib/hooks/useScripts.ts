import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

// ── Типы ────────────────────────────────────────────────────────────────────

export interface Script {
  id: string;
  name: string;
  description: string | null;
  is_archived: boolean;
  node_count: number;
  created_at: string;
  updated_at: string;
}

export interface ScriptDetail extends Script {
  dag: Record<string, unknown> | null;
  current_version: number;
  versions: ScriptVersion[];
}

export interface ScriptVersion {
  id: string;
  script_id: string;
  version: number;
  dag: Record<string, unknown> | null;
  dag_hash: string | null;
  notes: string | null;
  created_by_id: string | null;
  created_at: string;
}

interface ScriptsResponse {
  items: Script[];
  total: number;
  page: number;
  per_page: number;
}

// ── Запросы (Query) ─────────────────────────────────────────────────────────

/** Список скриптов с пагинацией и поиском */
export function useScripts(params?: { query?: string; page?: number; per_page?: number }) {
  return useQuery<ScriptsResponse>({
    queryKey: ['scripts', params],
    queryFn: async () => {
      const { data } = await api.get('/scripts', { params });
      // Обратная совместимость: бекенд может вернуть массив или {items}
      if (Array.isArray(data)) return { items: data, total: data.length, page: 1, per_page: data.length };
      return data;
    },
    staleTime: 30_000,
  });
}

/** Детали скрипта с текущим DAG и историей версий */
export function useScript(scriptId: string, options?: { includeDag?: boolean }) {
  return useQuery<ScriptDetail>({
    queryKey: ['scripts', scriptId],
    queryFn: async () => {
      const { data } = await api.get(`/scripts/${scriptId}`, {
        params: { include_dag: options?.includeDag ?? true },
      });
      return data;
    },
    enabled: !!scriptId,
  });
}

/** История версий скрипта */
export function useScriptVersions(scriptId: string, options?: { includeDag?: boolean }) {
  return useQuery<ScriptVersion[]>({
    queryKey: ['scripts', scriptId, 'versions'],
    queryFn: async () => {
      const { data } = await api.get(`/scripts/${scriptId}/versions`, {
        params: { include_dag: options?.includeDag ?? false },
      });
      return data;
    },
    enabled: !!scriptId,
  });
}

// ── Мутации ─────────────────────────────────────────────────────────────────

/** Создать скрипт с DAG. Бекенд: POST /scripts */
export function useCreateScript() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      name: string;
      description?: string;
      dag: Record<string, unknown>;
      changelog?: string;
    }) => {
      const { data } = await api.post('/scripts', body);
      return data as Script;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scripts'] }),
  });
}

/** Обновить скрипт (создаёт новую версию при изменении DAG). Бекенд: PUT /scripts/{id} */
export function useUpdateScript() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ scriptId, ...body }: {
      scriptId: string;
      name?: string;
      description?: string;
      dag?: Record<string, unknown>;
      changelog?: string;
    }) => {
      const { data } = await api.put(`/scripts/${scriptId}`, body);
      return data as Script;
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['scripts'] });
      qc.invalidateQueries({ queryKey: ['scripts', vars.scriptId] });
    },
  });
}

/** Архивировать скрипт (soft delete). Бекенд: DELETE /scripts/{id} */
export function useArchiveScript() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (scriptId: string) => api.delete(`/scripts/${scriptId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['scripts'] }),
  });
}

/** Откатить скрипт к указанной версии. Бекенд: POST /scripts/{id}/versions/{versionId}/rollback */
export function useRollbackScript() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ scriptId, versionId }: { scriptId: string; versionId: string }) => {
      const { data } = await api.post(`/scripts/${scriptId}/versions/${versionId}/rollback`);
      return data as Script;
    },
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['scripts'] });
      qc.invalidateQueries({ queryKey: ['scripts', vars.scriptId] });
    },
  });
}
