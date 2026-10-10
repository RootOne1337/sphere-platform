export type AuditStatus = 'SUCCESS' | 'FAILED' | 'WARNING' | 'UNKNOWN';

export interface AuditEvent {
  id: string;
  timestamp: string;
  user: string;
  action: string;
  resource: string;
  status: AuditStatus;
  ip: string;
  meta: Record<string, unknown>;
}

function normalizeStatus(value: unknown): AuditStatus {
  const status = String(value ?? '').toLowerCase();
  if (['success', 'succeeded', 'ok', 'completed'].includes(status)) return 'SUCCESS';
  if (['failed', 'failure', 'error', 'rejected'].includes(status)) return 'FAILED';
  if (['warning', 'degraded', 'partial'].includes(status)) return 'WARNING';
  return 'UNKNOWN';
}

/** Convert the documented audit response without inventing client-side fields. */
export function normalizeAuditEvent(value: unknown): AuditEvent {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Backend вернул некорректную запись журнала аудита.');
  }

  const item = value as Record<string, unknown>;
  const meta = item.meta && typeof item.meta === 'object' && !Array.isArray(item.meta)
    ? item.meta as Record<string, unknown>
    : {};
  const resourceType = String(item.resource_type ?? item.resource ?? '').trim();
  const resourceId = String(item.resource_id ?? '').trim();
  const resource = [resourceType, resourceId].filter(Boolean).join(' · ') || '—';
  const timestamp = String(item.created_at ?? item.timestamp ?? '');

  if (!item.id || !timestamp || !item.action) {
    throw new Error('Backend вернул запись аудита без обязательных полей.');
  }

  return {
    id: String(item.id),
    timestamp,
    user: String(item.user_id ?? item.user ?? 'system'),
    action: String(item.action),
    resource,
    status: normalizeStatus(item.status ?? meta.status),
    ip: String(item.ip_address ?? item.ip ?? ''),
    meta,
  };
}

export function normalizeAuditResponse(data: unknown): { items: AuditEvent[]; total: number; page: number; pages: number } {
  const envelope = Array.isArray(data) ? { items: data, total: data.length, page: 1, pages: data.length ? 1 : 0 }
    : data && typeof data === 'object' ? data as Record<string, unknown> : null;
  if (!envelope || !Array.isArray(envelope.items)) {
    throw new Error('Backend вернул некорректный список событий аудита.');
  }

  return {
    items: envelope.items.map(normalizeAuditEvent),
    total: Number.isFinite(Number(envelope.total)) ? Number(envelope.total) : envelope.items.length,
    page: Number.isFinite(Number(envelope.page)) ? Number(envelope.page) : 1,
    pages: Number.isFinite(Number(envelope.pages)) ? Number(envelope.pages) : (envelope.items.length ? 1 : 0),
  };
}
