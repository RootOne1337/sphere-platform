/** Validate paginated API envelopes instead of treating malformed data as an empty catalog. */
export function parseListItems<T>(payload: unknown, resource: string): T[] {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error(`Invalid ${resource} list response`);
  }

  const items = (payload as { items?: unknown }).items;
  if (!Array.isArray(items)) {
    throw new Error(`Invalid ${resource} list response`);
  }

  return items as T[];
}

export interface CatalogPage<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

/** Keep the requested page's evidence; never infer catalog size from items.length. */
export function parseCatalogPage<T extends { id: string }>(payload: unknown, resource: string, page: number, perPage: number): CatalogPage<T> {
  const items = parseListItems<T>(payload, resource);
  const data = payload as CatalogPage<T>;
  if (!Number.isInteger(data.total) || data.total < 0 || data.page !== page || data.per_page !== perPage ||
      data.pages !== Math.ceil(data.total / perPage) || items.length > perPage || items.length > data.total ||
      items.some(item => !item || typeof item.id !== 'string' || !item.id) ||
      new Set(items.map(item => item.id)).size !== items.length) {
    throw new Error(`Invalid ${resource} page response`);
  }
  // Check fields consumed by row renderers before admitting controls for this response.
  for (const item of items) {
    const row = item as Record<string, unknown>;
    const valid = resource === 'pipelines'
      ? typeof row.name === 'string' && Array.isArray(row.steps) && Array.isArray(row.tags) && row.tags.every(tag => typeof tag === 'string')
      : resource === 'pipeline-runs'
        ? typeof row.status === 'string' && typeof row.pipeline_id === 'string' && typeof row.device_id === 'string' && Array.isArray(row.step_logs)
        : resource === 'schedules'
          ? typeof row.name === 'string' && typeof row.target_type === 'string'
          : true;
    if (!valid) throw new Error(`Invalid ${resource} row response`);
  }
  return data;
}
