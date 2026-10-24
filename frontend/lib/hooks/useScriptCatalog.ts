import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { SessionChangedError, useAuthStore } from '@/lib/store';
import { parseVersion } from '@/src/features/scripts/versionWorkflow';

/** Catalog metadata is deliberately not a ScriptVersion: it has no source body. */
export interface ScriptCatalogVersion {
  id: string;
  script_id: string;
  version: number;
  dag_hash: string;
  created_at: string;
}
export interface ScriptCatalogItem {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  is_archived: boolean;
  created_at: string;
  updated_at: string;
  current_version_id: string | null;
  node_count: number | null;
  current_version: ScriptCatalogVersion | null;
}
export interface ScriptCatalogResponse {
  catalog_schema: 1;
  items: ScriptCatalogItem[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}
export interface ScriptCatalogParams {
  query?: string;
  page?: number;
  per_page?: number;
  state?: 'active' | 'archived' | 'all';
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const HASH = /^[0-9a-f]{64}$/;
const record = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === 'object' && !Array.isArray(value));
const uuid = (value: unknown): value is string => typeof value === 'string' && UUID.test(value);
const integer = (value: unknown, minimum = 0): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= minimum;
const timestamp = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value) && Number.isFinite(Date.parse(value));
function exactFields(value: Record<string, unknown>, fields: string[]) {
  return Object.keys(value).length === fields.length && fields.every(field => Object.hasOwn(value, field));
}
export class ScriptCatalogContractError extends Error {
  constructor() { super('Invalid script catalog metadata'); this.name = 'ScriptCatalogContractError'; }
}
/** Reject partial metadata, foreign tenants and legacy source-bearing responses. */
export function parseScriptCatalog(value: unknown, orgId: string, params: ScriptCatalogParams = {}): ScriptCatalogResponse {
  const page = params.page ?? 1, perPage = params.per_page ?? 50, state = params.state ?? 'active';
  if (!integer(page, 1) || !integer(perPage, 1) || perPage > 200 || !['active', 'archived', 'all'].includes(state)
    || !record(value) || !exactFields(value, ['catalog_schema', 'items', 'total', 'page', 'per_page', 'pages'])
    || value.catalog_schema !== 1 || !Array.isArray(value.items) || !integer(value.total)
    || value.page !== page || value.per_page !== perPage || value.pages !== Math.ceil(value.total / perPage)
    || value.items.length !== Math.min(perPage, Math.max(0, value.total - (page - 1) * perPage))) throw new ScriptCatalogContractError();
  const ids = new Set<string>();
  for (const item of value.items) {
    if (!record(item) || !exactFields(item, ['id', 'org_id', 'name', 'description', 'is_archived', 'created_at', 'updated_at', 'current_version_id', 'node_count', 'current_version'])
      || !uuid(item.id) || ids.has(item.id) || !uuid(item.org_id) || item.org_id !== orgId || typeof item.name !== 'string'
      || (item.description !== null && typeof item.description !== 'string') || typeof item.is_archived !== 'boolean'
      || (state === 'active' && item.is_archived) || (state === 'archived' && !item.is_archived)
      || !timestamp(item.created_at) || !timestamp(item.updated_at)) throw new ScriptCatalogContractError();
    ids.add(item.id);
    if (item.current_version_id === null) {
      if (item.current_version !== null || item.node_count !== null) throw new ScriptCatalogContractError();
    } else {
      const version = item.current_version;
      if (!uuid(item.current_version_id) || !integer(item.node_count) || !record(version)
        || !exactFields(version, ['id', 'script_id', 'version', 'dag_hash', 'created_at'])
        || version.id !== item.current_version_id || !uuid(version.id) || version.script_id !== item.id
        || !integer(version.version, 1) || typeof version.dag_hash !== 'string' || !HASH.test(version.dag_hash)
        || !timestamp(version.created_at)) throw new ScriptCatalogContractError();
    }
  }
  return value as unknown as ScriptCatalogResponse;
}

function useCatalogScope() {
  const actor = useAuthStore(state => state.user);
  const session = useAuthStore(state => state.sessionVersion);
  return { orgId: actor?.org_id, userId: actor?.id, role: actor?.role, session };
}
type CatalogScope = ReturnType<typeof useCatalogScope>;
function assertScope(scope: CatalogScope, signal: AbortSignal) {
  const current = useAuthStore.getState();
  if (!scope.orgId || !scope.userId || !current.user || signal.aborted || scope.session !== current.sessionVersion || scope.orgId !== current.user?.org_id
    || scope.userId !== current.user?.id || scope.role !== current.user?.role) throw new SessionChangedError();
}

export function useScriptCatalog(params: ScriptCatalogParams = {}) {
  const scope = useCatalogScope();
  return useQuery<ScriptCatalogResponse>({
    queryKey: ['scripts', 'catalog', scope, params],
    queryFn: async ({ signal }) => {
      assertScope(scope, signal);
      const { data } = await api.get('/scripts/catalog', { params, signal });
      assertScope(scope, signal);
      return parseScriptCatalog(data, scope.orgId!, params);
    },
    enabled: Boolean(scope.orgId && scope.userId),
    staleTime: 30_000,
    gcTime: 60_000,
    retry: false,
  });
}

/** The selected catalog receipt stays pinned even when a newer version is published. */
export function useScriptCatalogSource(script: ScriptCatalogItem) {
  const scope = useCatalogScope();
  const selected = script.current_version;
  return useQuery({
    queryKey: ['scripts', 'catalog-source', scope, script.id, selected, script.node_count],
    queryFn: async ({ signal }) => {
      assertScope(scope, signal);
      if (!selected || script.org_id !== scope.orgId) throw new ScriptCatalogContractError();
      const { data } = await api.get(`/scripts/${script.id}/versions/${selected.id}`, { signal });
      assertScope(scope, signal);
      const version = parseVersion(data, script.id, selected.id);
      if (!version.dag || version.dag_hash !== selected.dag_hash || version.version !== selected.version
        || Date.parse(version.created_at) !== Date.parse(selected.created_at)
        || !Array.isArray(version.dag.nodes) || version.dag.nodes.length !== script.node_count) throw new ScriptCatalogContractError();
      return version;
    },
    enabled: Boolean(scope.orgId && scope.userId && selected && script.org_id === scope.orgId),
    staleTime: Infinity,
    gcTime: 60_000,
    retry: false,
  });
}

export function scriptCatalogReadFailure(error: unknown): string {
  if (error instanceof ScriptCatalogContractError) return 'API вернул неполные или несогласованные метаданные каталога. Повторите чтение после восстановления API.';
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
  const detail = response?.data?.detail;
  if (response?.status === 503 && (detail === 'script_catalog_metadata_unavailable'
    || (record(detail) && detail.code === 'script_catalog_metadata_unavailable'))) return 'Метаданные опубликованных версий пока недоступны. Повторите чтение после их подготовки на сервере.';
  if (response?.status === 403) return 'API не подтвердил право читать каталог сценариев.';
  if ([404, 405, 422].includes(response?.status ?? 0)) return 'API не поддерживает этот каталог или отклонил запрос. Повторите чтение после обновления сервера.';
  return 'Каталог недоступен. Проверьте доступ к API и повторите запрос.';
}
