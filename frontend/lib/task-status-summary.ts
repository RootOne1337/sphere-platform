type TaskStatusCounts = Record<string, number>;

function safeCount(counts: TaskStatusCounts, status: string): number {
  const value = counts[status];
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : 0;
}

/** Derives execution KPIs without rendering NaN when older APIs omit counters. */
export function summarizeTaskStatuses(counts: TaskStatusCounts | null | undefined) {
  if (!counts) return { successRate: '—', failedAndTimeout: null as number | null };

  const completed = safeCount(counts, 'completed');
  const failedAndTimeout = safeCount(counts, 'failed') + safeCount(counts, 'timeout');
  const resolved = completed + failedAndTimeout;

  return {
    successRate: resolved > 0 ? `${((completed / resolved) * 100).toFixed(1)}%` : '—',
    failedAndTimeout,
  };
}
