import { validSaveReceipt, type ProfileSaveReceipt } from './profileTypes';

export type BatchItem = { request_id: string; name: string };
export type BatchCheck = { request_id: string; config_valid: boolean; issues: { code: string; line: number | null }[] };

function envelope(value: unknown, expected: BatchItem[]) {
  if (!value || typeof value !== 'object') throw new Error('invalid_batch_receipt');
  const data = value as { items: unknown[]; apply_allowed?: boolean; execution_confirmed?: boolean; persisted?: boolean; config_valid?: boolean };
  if (!Array.isArray(data.items) || data.items.length !== expected.length || data.items.length > 100) throw new Error('invalid_batch_length');
  return data;
}

export function parseBatchCheck(value: unknown, expected: BatchItem[]): BatchCheck[] {
  const data = envelope(value, expected);
  if (data.apply_allowed !== false || data.execution_confirmed !== false || data.persisted !== false || typeof data.config_valid !== 'boolean') throw new Error('invalid_batch_check');
  const items = data.items.map((value, i) => {
    const row = value as BatchCheck;
    if (!row || row.request_id !== expected[i].request_id || typeof row.config_valid !== 'boolean'
      || !Array.isArray(row.issues) || row.issues.length > 64 || row.config_valid !== (row.issues.length === 0)
      || row.issues.some(issue => !issue || typeof issue.code !== 'string' || issue.code.length > 128 || (issue.line !== null && (!Number.isInteger(issue.line) || issue.line < 1)))) throw new Error('invalid_batch_item');
    return { request_id: row.request_id, config_valid: row.config_valid, issues: row.issues.map(v => ({ code: v.code, line: v.line })) };
  });
  if (data.config_valid !== items.every(v => v.config_valid)) throw new Error('invalid_batch_verdict');
  return items;
}

export function parseBatchSaved(value: unknown, expected: BatchItem[]): ProfileSaveReceipt[] {
  const data = envelope(value, expected);
  if (data.persisted !== true || data.apply_allowed !== false || data.execution_confirmed !== false) throw new Error('invalid_batch_saved');
  return data.items.map((row, i) => {
    if (!validSaveReceipt(row, expected[i].request_id)) throw new Error('invalid_batch_saved_item');
    return { request_id: row.request_id, profile_id: row.profile_id, revision_id: row.revision_id, revision: row.revision,
      persisted: true, apply_allowed: false, execution_confirmed: false };
  });
}

export function parseBatchStatus(value: unknown, expected: BatchItem[]): (ProfileSaveReceipt | null)[] {
  const data = envelope(value, expected);
  return data.items.map((value, i) => {
    const row = value as { request_id: string; receipt: unknown };
    if (!row || row.request_id !== expected[i].request_id) throw new Error('invalid_batch_status');
    if (row.receipt === null) return null;
    if (!validSaveReceipt(row.receipt, expected[i].request_id)) throw new Error('invalid_batch_status_item');
    const r = row.receipt;
    return { request_id: r.request_id, profile_id: r.profile_id, revision_id: r.revision_id, revision: r.revision,
      persisted: true, apply_allowed: false, execution_confirmed: false };
  });
}
