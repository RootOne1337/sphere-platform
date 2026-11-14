/** Return an API-provided explanation when safe to display, otherwise a local fallback. */
export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (typeof error !== 'object' || error === null) return fallback;

  const candidate = error as { response?: { data?: { detail?: unknown } } };
  const detail = candidate.response?.data?.detail;
  return typeof detail === 'string' && detail.trim() ? detail : fallback;
}
