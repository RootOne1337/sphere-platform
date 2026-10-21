const phases = ['IDLE', 'APPLYING', 'TRANSPORT_READY', 'AWAITING_HANDSHAKE', 'HANDSHAKE_CONFIRMED', 'PAUSED_GUARD_HELD', 'UNKNOWN_GUARD_HELD', 'FAILED_GUARD_HELD', 'GUARD_UNCONFIRMED', 'DISCONNECTED_CONFIRMED', 'REVOKED_GUARD_HELD', 'RECONCILIATION_REQUIRED', 'STATUS_UNKNOWN', 'OPERATION_REJECTED', 'OUTCOME_UNKNOWN', 'CONSENT_REQUIRED'] as const;
type Phase = typeof phases[number];
interface Snapshot {
  requestId: string | null; sessionId: string | null; profileRevisionId: string | null; phase: Phase;
  reason: string | null; nativeVersion: string | null; handshakeEpochSeconds: number | null; rxBytes: number | null; txBytes: number | null;
  sampledAtEpochMs: number; providerPid: number;
}
export interface VpnRuntimeDevice {
  device_id: string; name: string; model: string | null; android_version: string | null; status: string; agent_version: string | null;
  last_heartbeat: string | null; freshness: 'fresh' | 'stale' | 'unknown';
  observation: { snapshot: Snapshot; received_at: string; ws_session_id: string } | null;
}
export interface VpnRuntimePage { items: VpnRuntimeDevice[]; total: number; page: number; page_size: number; as_of: string }
const uuid = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value);
const count = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
const date = (value: unknown): value is string => typeof value === 'string' && value.length <= 40 && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
const nullable = (value: unknown, check: (v: unknown) => boolean) => value === null || check(value);
const text = (value: unknown) => typeof value === 'string' && value.length <= 255;
function object(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length !== keys.length || keys.some(k => !(k in value))) throw new Error('vpn_runtime_invalid');
  return value as Record<string, unknown>;
}
export function parseVpnRuntimePage(value: unknown, expectedPage: number): VpnRuntimePage {
  const body = object(value, ['items', 'total', 'page', 'page_size', 'as_of']);
  if (!Array.isArray(body.items) || body.items.length > 100 || !count(body.total) || body.page !== expectedPage || !count(body.page_size) || body.page_size < 1 || body.page_size > 100 || !date(body.as_of) || body.items.length > body.page_size || body.items.length > body.total) throw new Error('vpn_runtime_page_invalid');
  const ids = new Set();
  for (const item of body.items) {
    const row = object(item, ['device_id', 'name', 'model', 'android_version', 'status', 'agent_version', 'last_heartbeat', 'observation', 'freshness']);
    if (!uuid(row.device_id) || ids.has(row.device_id) || !text(row.name) || !nullable(row.model, text) || !nullable(row.android_version, text) || !nullable(row.agent_version, text) || !nullable(row.last_heartbeat, date) || !['online', 'busy', 'offline', 'connecting', 'error'].includes(row.status as string) || !['fresh', 'stale', 'unknown'].includes(row.freshness as string)) throw new Error('vpn_runtime_device_invalid');
    ids.add(row.device_id);
    if (row.observation !== null) {
      const observed = object(row.observation, ['snapshot', 'received_at', 'ws_session_id']);
      if (!date(observed.received_at) || typeof observed.ws_session_id !== 'string' || !observed.ws_session_id || observed.ws_session_id.length > 100) throw new Error('vpn_runtime_observation_invalid');
      const sample = object(observed.snapshot, ['requestId', 'sessionId', 'profileRevisionId', 'phase', 'reason', 'nativeVersion', 'handshakeEpochSeconds', 'rxBytes', 'txBytes', 'sampledAtEpochMs', 'providerPid']);
      if (!nullable(sample.requestId, uuid) || !nullable(sample.sessionId, uuid) || !nullable(sample.profileRevisionId, uuid) || !phases.includes(sample.phase as Phase) || !nullable(sample.reason, text) || !nullable(sample.nativeVersion, text) || !['handshakeEpochSeconds', 'rxBytes', 'txBytes'].every(k => nullable(sample[k], count)) || !count(sample.sampledAtEpochMs) || !count(sample.providerPid) || sample.providerPid < 1) throw new Error('vpn_runtime_snapshot_invalid');
    } else if (row.freshness !== 'unknown') throw new Error('vpn_runtime_missing_observation');
  }
  return value as VpnRuntimePage;
}
export function runtimeFreshness(row: VpnRuntimeDevice, asOf: string, now = Date.now()): 'fresh' | 'stale' | 'unknown' {
  if (!row.observation || row.freshness === 'unknown') return 'unknown';
  // Retained query data must expire even when polling is offline or paused.
  const receiptAge = now - Date.parse(row.observation.received_at);
  const sampleAge = now - row.observation.snapshot.sampledAtEpochMs;
  const responseAge = now - Date.parse(asOf);
  return row.freshness === 'fresh' && receiptAge >= 0 && receiptAge < 15000 && sampleAge >= -5000 && sampleAge < 15000 && responseAge >= -5000 && responseAge < 15000 ? 'fresh' : 'stale';
}
export const vpnPhaseLabels: Record<typeof phases[number], string> = {
  IDLE: 'Не запущен', APPLYING: 'Применяется', TRANSPORT_READY: 'Транспорт готов', AWAITING_HANDSHAKE: 'Ожидает handshake',
  HANDSHAKE_CONFIRMED: 'Handshake получен', PAUSED_GUARD_HELD: 'Пауза · трафик заблокирован', UNKNOWN_GUARD_HELD: 'Нужна сверка защиты',
  FAILED_GUARD_HELD: 'Ошибка · защита сохранена', GUARD_UNCONFIRMED: 'Защита не подтверждена', DISCONNECTED_CONFIRMED: 'Отключение подтверждено',
  REVOKED_GUARD_HELD: 'Разрешение VPN отозвано', RECONCILIATION_REQUIRED: 'Требуется сверка', STATUS_UNKNOWN: 'Состояние неизвестно',
  OPERATION_REJECTED: 'Операция отклонена', OUTCOME_UNKNOWN: 'Результат неизвестен', CONSENT_REQUIRED: 'Нужно разрешение Android',
};
