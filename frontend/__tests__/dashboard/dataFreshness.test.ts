import { formatDataAge, getDataFreshness } from '@/src/features/dashboard/dataFreshness';

const now = Date.parse('2026-09-30T00:00:00.000Z');

function describe(overrides: Partial<Parameters<typeof getDataFreshness>[0]> = {}) {
  return getDataFreshness({
    dataUpdatedAt: now - 10_000,
    hasData: true,
    isError: false,
    isFetching: false,
    pollIntervalMs: 15_000,
    now,
    ...overrides,
  });
}

it('distinguishes a source that has not returned data from an API error', () => {
  expect(describe({ hasData: false, dataUpdatedAt: 0 }).state).toBe('waiting');
  expect(describe({ hasData: false, dataUpdatedAt: 0, isError: true }).state).toBe('error');
});

it('reports the age of the last successful response while a refresh is running', () => {
  expect(describe({ isFetching: true })).toEqual({ state: 'refreshing', ageMs: 10_000 });
});

it('allows one missed polling interval, then marks the response delayed', () => {
  expect(describe({ dataUpdatedAt: now - 30_000 }).state).toBe('fresh');
  expect(describe({ dataUpdatedAt: now - 30_001 }).state).toBe('stale');
});

it('does not present cached data as fresh after a failed refresh', () => {
  expect(describe({ isError: true })).toEqual({ state: 'error', ageMs: 10_000 });
});

it('clamps future client timestamps and formats age at seconds, minutes, hours and days', () => {
  expect(describe({ dataUpdatedAt: now + 60_000 }).ageMs).toBe(0);
  expect(formatDataAge(59_000)).toBe('59 с назад');
  expect(formatDataAge(60_000)).toBe('1 мин назад');
  expect(formatDataAge(3_600_000)).toBe('1 ч назад');
  expect(formatDataAge(86_400_000)).toBe('1 дн. назад');
  expect(formatDataAge(null)).toBe('нет успешного ответа');
});
