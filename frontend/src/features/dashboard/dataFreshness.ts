export type DataFreshnessState = 'waiting' | 'refreshing' | 'fresh' | 'stale' | 'error';

export interface DataFreshnessInput {
  dataUpdatedAt: number;
  hasData: boolean;
  isError: boolean;
  isFetching: boolean;
  pollIntervalMs: number;
  now?: number;
}

export interface DataFreshness {
  state: DataFreshnessState;
  ageMs: number | null;
}

/**
 * Classify the age of the last successful browser response, not the age of the
 * underlying device heartbeat or metric sample. Two polling intervals allow a
 * single missed poll without describing the source as delayed.
 */
export function getDataFreshness({
  dataUpdatedAt,
  hasData,
  isError,
  isFetching,
  pollIntervalMs,
  now = Date.now(),
}: DataFreshnessInput): DataFreshness {
  if (!hasData || dataUpdatedAt <= 0 || !Number.isFinite(dataUpdatedAt)) {
    return { state: isError ? 'error' : 'waiting', ageMs: null };
  }

  const ageMs = Math.max(0, now - dataUpdatedAt);
  if (isError) return { state: 'error', ageMs };
  if (ageMs > pollIntervalMs * 2) return { state: 'stale', ageMs };
  if (isFetching) return { state: 'refreshing', ageMs };
  return { state: 'fresh', ageMs };
}

export function formatDataAge(ageMs: number | null): string {
  if (ageMs == null || !Number.isFinite(ageMs) || ageMs < 0) return 'нет успешного ответа';
  const seconds = Math.floor(ageMs / 1000);
  if (seconds < 5) return 'только что';
  if (seconds < 60) return `${seconds} с назад`;

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} мин назад`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ч назад`;

  const days = Math.floor(hours / 24);
  return `${days} дн. назад`;
}

export function formatDataUpdatedAt(timestamp: number): string {
  if (!Number.isFinite(timestamp) || timestamp <= 0) return 'Ещё не получено';
  return new Intl.DateTimeFormat('ru-RU', {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZoneName: 'short',
  }).format(timestamp);
}
