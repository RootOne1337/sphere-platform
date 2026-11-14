import { auditExportReceipt, auditFilterParams, EMPTY_AUDIT_DRAFT } from '@/src/features/audit/investigation';

it.each(['2026-02-30T10:00', '2026-10-02T25:00', '2026-10-02', '2026-10-02T10:00Z'])('rejects invalid UTC form dates (%s)', from => {
  expect(() => auditFilterParams({ ...EMPTY_AUDIT_DRAFT, from })).toThrow();
});
it.each(['2026-10-02T10:00', '2026-10-02T10:00:15', '2026-10-02T10:00:15.120'])('does not depend on host timezone (%s)', from => {
  expect(auditFilterParams({ ...EMPTY_AUDIT_DRAFT, from }).from).toBe(new Date(`${from}Z`).toISOString());
});
it.each(['status:BOGUS', 'action:', 'user:', 'x '.repeat(21)])('rejects invalid search conditions (%s)', q => {
  expect(() => auditFilterParams({ ...EMPTY_AUDIT_DRAFT, q })).toThrow();
});
it('keeps literal wildcard and quoted characters without treating them as code', () => {
  expect(auditFilterParams({ ...EMPTY_AUDIT_DRAFT, action: "%_' OR 1=1", resource_type: 'groups' })).toEqual({ action: "%_' OR 1=1", resource_type: 'groups' });
});
it.each(['-1', '1.5', '', 'NaN', '5001'])('rejects an invalid export row receipt (%s)', rows => {
  expect(() => auditExportReceipt(new Blob(['x']), { 'content-type': 'text/csv', 'x-audit-rows': rows,
    'x-audit-limit': '5000', 'x-audit-truncated': 'false', 'x-audit-observed-at': '2026-10-02T10:00:00Z' })).toThrow();
});
it('requires a full cap for truncation and rejects unbounded payloads', () => {
  const headers = { 'content-type': 'text/csv', 'x-audit-rows': '1', 'x-audit-limit': '5000', 'x-audit-truncated': 'true', 'x-audit-observed-at': '2026-10-02T10:00:00Z' };
  expect(() => auditExportReceipt(new Blob(['x']), headers)).toThrow();
  expect(() => auditExportReceipt(new Blob([new Uint8Array(16 * 1024 * 1024 + 1)]), { ...headers, 'x-audit-truncated': 'false' })).toThrow();
});
