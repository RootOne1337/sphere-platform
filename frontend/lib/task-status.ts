/** Cancellation request and a confirmed terminal outcome are different states. */
export function isCancellationPending(task: { status: string; cancel_requested_at?: string | null }): boolean {
  return Boolean(task.cancel_requested_at) && ['queued', 'assigned', 'running', 'waiting', 'paused'].includes(task.status);
}

export function executionStatusLabel(task: { status: string; cancel_requested_at?: string | null }): string {
  return isCancellationPending(task) ? 'Cancelling — awaiting device result' : task.status;
}
