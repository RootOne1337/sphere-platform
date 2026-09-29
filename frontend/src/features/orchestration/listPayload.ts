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
