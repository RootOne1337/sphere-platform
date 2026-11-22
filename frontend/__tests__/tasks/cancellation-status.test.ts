import { executionStatusLabel, isCancellationPending } from '@/lib/task-status';

describe('confirmed execution outcome versus cancellation request', () => {
  it.each(['queued', 'assigned', 'running', 'waiting', 'paused'])('keeps %s visible as awaiting a device result', status => {
    const task = { status, cancel_requested_at: '2026-09-20T12:00:00Z' };
    expect(isCancellationPending(task)).toBe(true);
    expect(executionStatusLabel(task)).toBe('Cancelling — awaiting device result');
  });
  it.each(['completed', 'failed', 'cancelled', 'timeout'])('preserves actual terminal %s despite an earlier request', status => {
    const task = { status, cancel_requested_at: '2026-09-20T12:00:00Z' };
    expect(isCancellationPending(task)).toBe(false);
    expect(executionStatusLabel(task)).toBe(status);
  });
  it('does not invent cancellation for a legacy or normally running task', () => {
    expect(executionStatusLabel({status: 'running'})).toBe('running');
  });
  it.each(['assigned', 'running'])('keeps overdue %s active until the device confirms its outcome', status => {
    const task = { status, cancel_requested_at: '2026-09-21T00:00:00Z', timeout_requested_at: '2026-09-21T00:00:00Z' };
    expect(isCancellationPending(task)).toBe(true);
    expect(executionStatusLabel(task)).toBe('Deadline exceeded — awaiting device result');
  });
  it.each(['timeout', 'completed', 'failed'])('shows the terminal %s after a watchdog request', status => {
    expect(executionStatusLabel({ status, cancel_requested_at: '2026-09-21T00:00:00Z', timeout_requested_at: '2026-09-21T00:00:00Z' })).toBe(status);
  });
});
