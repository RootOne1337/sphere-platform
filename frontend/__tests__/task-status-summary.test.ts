import { summarizeTaskStatuses } from '@/lib/task-status-summary';

describe('summarizeTaskStatuses', () => {
  it('returns an unavailable success rate when the API has no resolved tasks', () => {
    expect(summarizeTaskStatuses(undefined)).toEqual({ successRate: '—', failedAndTimeout: null });
    expect(summarizeTaskStatuses({})).toEqual({ successRate: '—', failedAndTimeout: 0 });
  });

  it('counts only finite non-negative resolved task counters', () => {
    expect(summarizeTaskStatuses({ completed: 7, failed: 2, timeout: 1 })).toEqual({
      successRate: '70.0%',
      failedAndTimeout: 3,
    });
    expect(summarizeTaskStatuses({ completed: 4, failed: Number.NaN, timeout: -1 })).toEqual({
      successRate: '100.0%',
      failedAndTimeout: 0,
    });
  });
});
