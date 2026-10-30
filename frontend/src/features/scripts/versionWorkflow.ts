import type { Script, ScriptDetail, ScriptVersion } from '@/lib/hooks/useScripts';
import { redactScriptDag } from './scriptPresentation';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const HASH = /^[0-9a-f]{64}$/;
const record = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === 'object' && !Array.isArray(value));
export function canWriteScript(role: string | undefined) {
  return ['device_manager', 'org_admin', 'org_owner', 'super_admin'].includes(role ?? '');
}
export function parseVersion(value: unknown, scriptId: string, versionId?: string): ScriptVersion {
  if (!record(value) || typeof value.id !== 'string' || !UUID.test(value.id) || (versionId && value.id !== versionId)
    || value.script_id !== scriptId || !Number.isSafeInteger(value.version) || (value.version as number) < 1
    || (value.dag !== null && !record(value.dag)) || (value.dag_hash !== null && (typeof value.dag_hash !== 'string' || !HASH.test(value.dag_hash)))
    || (value.notes !== null && typeof value.notes !== 'string')
    || (value.created_by_id !== null && (typeof value.created_by_id !== 'string' || !UUID.test(value.created_by_id)))
    || typeof value.created_at !== 'string' || !Number.isFinite(Date.parse(value.created_at))) throw new Error('Invalid script version');
  return value as unknown as ScriptVersion;
}
export function parseScript(value: unknown, scriptId: string, orgId: string): Script {
  if (!record(value) || value.id !== scriptId || value.org_id !== orgId || typeof value.name !== 'string'
    || typeof value.is_archived !== 'boolean' || typeof value.created_at !== 'string' || typeof value.updated_at !== 'string'
    || !Number.isFinite(Date.parse(value.created_at)) || !Number.isFinite(Date.parse(value.updated_at))) throw new Error('Invalid script');
  if (value.current_version_id !== null) parseVersion(value.current_version, scriptId, String(value.current_version_id));
  else if (value.current_version !== null) throw new Error('Invalid current version');
  return value as unknown as Script;
}
export function parseDetail(value: unknown, scriptId: string, orgId: string): ScriptDetail {
  const script = parseScript(value, scriptId, orgId);
  if (!record(value) || !Array.isArray(value.versions)) throw new Error('Invalid history');
  const versions = value.versions.map(v => parseVersion(v, scriptId));
  if (new Set(versions.map(v => v.id)).size !== versions.length || new Set(versions.map(v => v.version)).size !== versions.length
    || (script.current_version_id && !versions.some(v => v.id === script.current_version_id))) throw new Error('Invalid history identity');
  return { ...script, versions };
}
export function verifyRollback(value: unknown, scriptId: string, orgId: string, target: ScriptVersion, baseline: ScriptDetail): ScriptVersion {
  const script = parseScript(value, scriptId, orgId);
  const version = script.current_version as ScriptVersion | null;
  if (!version || script.is_archived || !version.dag || !target.dag_hash || version.dag_hash !== target.dag_hash
    || JSON.stringify(canonical(version.dag)) !== JSON.stringify(canonical(target.dag))
    || baseline.versions.some(v => v.id === version.id) || version.version <= Math.max(...baseline.versions.map(v => v.version))) {
    throw new Error('Unconfirmed rollback receipt');
  }
  return version;
}
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (!record(value)) return value;
  return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
}
/** Compare redacted structure. Never expose values or unbounded diffs in a control panel. */
export function changedDagPaths(current: unknown, selected: unknown): { paths: string[]; truncated: boolean } {
  const paths: string[] = [];
  let truncated = false;
  function walk(a: unknown, b: unknown, path: string) {
    if (paths.length >= 200) { truncated = true; return; }
    if (record(a) && record(b)) {
      for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) walk(a[key], b[key], path ? `${path}.${key}` : key);
    } else if (Array.isArray(a) && Array.isArray(b)) {
      for (let i = 0; i < Math.max(a.length, b.length); i++) walk(a[i], b[i], `${path}[${i}]`);
    } else if (JSON.stringify(a) !== JSON.stringify(b)) paths.push(path || '$');
  }
  walk(redactScriptDag(current), redactScriptDag(selected), '');
  return { paths, truncated };
}
export function scriptWriteFailure(error: unknown): { message: string; uncertain: boolean } {
  const status = (error as { response?: { status?: number } })?.response?.status;
  if (status === 403) return { message: 'Нет права изменять этот сценарий. Обновите состояние и проверьте свою роль.', uncertain: false };
  if (status === 404) return { message: 'Сценарий или версия недоступны. Обновите состояние.', uncertain: false };
  if (status === 409) return { message: 'Сценарий изменён, архивирован или сейчас занят другой записью. Обновите состояние и подтвердите действие заново.', uncertain: false };
  if (status === 422) return { message: 'Сервер отклонил параметры записи. Обновите состояние.', uncertain: false };
  return { message: 'Результат записи неизвестен. Не повторяйте действие до чтения текущего состояния.', uncertain: true };
}
