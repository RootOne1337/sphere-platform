import type { ScriptCatalogItem, ScriptCatalogResponse } from '@/lib/hooks/useScriptCatalog';

export const catalogOrg = '22222222-2222-4222-8222-222222222222';
export const catalogActor = {
  id: '99999999-9999-4999-8999-999999999999', org_id: catalogOrg,
  role: 'org_admin', email: 'operator@example.org',
};
export const catalogScript: ScriptCatalogItem = {
  id: '11111111-1111-4111-8111-111111111111', org_id: catalogOrg,
  name: 'Canary DAG', description: 'Безопасный сценарий проверки', is_archived: false,
  created_at: '2026-09-29T00:00:00Z', updated_at: '2026-09-29T00:00:00Z',
  current_version_id: '44444444-4444-4444-8444-444444444444', node_count: 2,
  current_version: {
    id: '44444444-4444-4444-8444-444444444444', script_id: '11111111-1111-4111-8111-111111111111',
    version: 4, dag_hash: 'a'.repeat(64), created_at: '2026-09-29T00:00:00Z',
  },
};
export const catalogSource = {
  ...catalogScript.current_version!,
  dag: { nodes: [{ id: 'start', type: 'start' }, { id: 'wait', type: 'wait' }], edges: [] },
  notes: 'Current version', created_by_id: null,
};
export function catalogEnvelope(items = [catalogScript], total = items.length, page = 1, perPage = 50): ScriptCatalogResponse {
  return { catalog_schema: 1, items, total, page, per_page: perPage, pages: Math.ceil(total / perPage) };
}
