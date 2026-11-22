export type InputAvailability = { revision: number; state: 'manual' | 'preparing' | 'automation' | 'cleanup_unknown'; taskId: string | null };

/** A state snapshot on the authenticated media peer, never an input execution receipt. */
export function parseInputAvailability(value: unknown, session: string, epoch: string | null): InputAvailability | null {
  if (!value || typeof value !== 'object' || Array.isArray(value) || !epoch) return null;
  const m = value as Record<string, unknown>;
  if (Object.keys(m).sort().join() !== 'capture_epoch,revision,schema_version,session_id,state,task_id,type'
    || m.type !== 'input_availability' || m.schema_version !== 1 || m.session_id !== session || m.capture_epoch !== epoch
    || typeof m.revision !== 'number' || !Number.isSafeInteger(m.revision) || m.revision < 0
    || !['manual','preparing','automation','cleanup_unknown'].includes(String(m.state))
    || m.task_id !== null && (typeof m.task_id !== 'string' || !/^[A-Za-z0-9_-]{8,128}$/.test(m.task_id))
    || ['preparing','automation'].includes(String(m.state)) && m.task_id === null
    || m.state === 'manual' && m.task_id !== null) return null;
  return { revision: m.revision, state: m.state as InputAvailability['state'], taskId: m.task_id as string | null };
}
