export const AUDIT_EXPORT_LIMIT = 5000;
export type AuditFilters = Record<string, string>;
export interface AuditDraft { q: string; status: string; action: string; user_id: string; resource_type: string; from: string; to: string }
export const EMPTY_AUDIT_DRAFT: AuditDraft = { q: '', status: '', action: '', user_id: '', resource_type: '', from: '', to: '' };

function utcTimestamp(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,3})?)?$/.test(value)) throw new Error('Укажите корректные дату и время UTC.');
  const date = new Date(`${value}Z`);
  const calendar = value.slice(0, value.includes('.') ? value.indexOf('.') : value.length);
  if (Number(value.slice(0, 4)) < 1 || !Number.isFinite(date.getTime()) || date.toISOString().slice(0, calendar.length) !== calendar) throw new Error('Укажите корректные дату и время UTC.');
  return date.toISOString();
}

export function auditFilterParams(draft: AuditDraft): AuditFilters {
  const params: AuditFilters = {};
  for (const [key, raw] of Object.entries(draft)) { if (raw.trim()) params[key] = raw.trim(); }
  if (params.user_id && !/^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(params.user_id)) throw new Error('Введите полный UUID пользователя; system доступен через user:system в поиске.');
  const terms = (params.q ?? '').split(/\s+/).filter(Boolean);
  if ((params.q?.length ?? 0) > 500 || terms.length > 20) throw new Error('Поиск: до 500 символов и 20 условий.');
  for (const term of terms) {
    const match = term.match(/^(status|action|user):(.*)$/i);
    if (match && (!match[2] || (match[1].toLowerCase() === 'status' && !['SUCCESS', 'FAILED', 'WARNING', 'UNKNOWN'].includes(match[2].toUpperCase())))) throw new Error('Проверьте условия status:, action: и user: в поиске.');
  }
  if (params.from) params.from = utcTimestamp(params.from);
  if (params.to) params.to = utcTimestamp(params.to);
  if (params.from && params.to && params.from > params.to) throw new Error('Конец диапазона не может быть раньше начала.');
  return params;
}

export interface AuditExportReceipt { rows: number; limit: number; truncated: boolean; observedAt: string }
export function auditExportReceipt(blob: unknown, headers: Record<string, unknown>): AuditExportReceipt {
  const rows = Number(headers['x-audit-rows']);
  const limit = Number(headers['x-audit-limit']);
  const truncated = headers['x-audit-truncated'];
  const observedAt = String(headers['x-audit-observed-at'] ?? '');
  if (!(blob instanceof Blob) || blob.size === 0 || blob.size > 16 * 1024 * 1024
    || String(headers['content-type']).toLowerCase().split(';')[0].trim() !== 'text/csv'
    || !/^\d+$/.test(String(headers['x-audit-rows'])) || !Number.isInteger(rows) || rows < 0 || rows > AUDIT_EXPORT_LIMIT
    || limit !== AUDIT_EXPORT_LIMIT || !['true', 'false'].includes(String(truncated))
    || (truncated === 'true' && rows !== limit)
    || !/(Z|[+-]\d{2}:\d{2})$/.test(observedAt) || !Number.isFinite(Date.parse(observedAt))) {
    throw new Error('Backend не подтвердил состав и формат экспорта. Файл не скачан.');
  }
  return { rows, limit, truncated: truncated === 'true', observedAt };
}

export function downloadAuditCsv(blob: Blob, receipt: AuditExportReceipt) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `sphere-audit-${new Date(receipt.observedAt).toISOString().slice(0, 10)}.csv`;
  try { document.body.appendChild(anchor); anchor.click(); }
  finally { anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 0); }
}
