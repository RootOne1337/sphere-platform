export interface OtaRelease {
  id: string; platform: string; flavor: string; version_code: number; version_name: string;
  download_url: string; sha256: string; mandatory: boolean; changelog: string | null; created_at: string;
}
export interface RecoveryGrant {
  command_id: string; sha256: string; version_name: string; version_code: number; created_at: number; expires_at: number;
}
export interface RecoveryReceipt {
  command_id: string; sha256: string; version_name: string; version_code: number;
  status: 'completed' | 'failed'; failure_code: string | null; installed_version_code: number | null;
  recovered_after_process_restart: boolean; recorded_at: string;
}
export interface RecoveryStatus {
  device_id: string; state: 'none' | 'active' | 'expired' | 'invalid' | 'completed' | 'failed';
  active: RecoveryGrant | null; last_result: RecoveryReceipt | null; recent_results: RecoveryReceipt[]; observed_at: string;
}
export interface OtaDevice {
  id: string; name: string; status: string; is_active: boolean; agent_version?: string | null;
  agent_version_code?: number | null; last_heartbeat?: string | null;
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SHA = /^[0-9a-f]{64}$/;
const record = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === 'object');
const integer = (value: unknown, min = 0): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= min && value <= 2_147_483_647;
const text = (value: unknown, max: number): value is string => typeof value === 'string' && value.length > 0 && value.length <= max;
export const awareTime = (value: unknown): value is string => typeof value === 'string' && /(Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
export function isManagedAndroidRelease(release: OtaRelease): boolean {
  return ['android', 'android-canary'].includes(release.platform) && SHA.test(release.sha256)
    && release.download_url === '/api/v1/updates/artifacts/' + release.sha256 && integer(release.version_code, 1);
}
export function isOtaDevice(value: unknown): value is OtaDevice {
  return record(value) && typeof value.id === 'string' && UUID.test(value.id) && text(value.name, 255)
    && typeof value.is_active === 'boolean' && typeof value.status === 'string'
    && (value.agent_version_code == null || integer(value.agent_version_code))
    && (value.agent_version == null || text(value.agent_version, 100))
    && (value.last_heartbeat == null || awareTime(value.last_heartbeat));
}
function isGrant(value: unknown): value is RecoveryGrant {
  return record(value) && typeof value.command_id === 'string' && UUID.test(value.command_id)
    && typeof value.sha256 === 'string' && SHA.test(value.sha256) && text(value.version_name, 100)
    && integer(value.version_code) && integer(value.created_at, 1) && integer(value.expires_at, 1)
    && value.expires_at > value.created_at && value.expires_at - value.created_at <= 3600;
}
function isReceipt(value: unknown): value is RecoveryReceipt {
  return record(value) && typeof value.command_id === 'string' && UUID.test(value.command_id)
    && typeof value.sha256 === 'string' && SHA.test(value.sha256) && text(value.version_name, 100)
    && integer(value.version_code) && ['completed', 'failed'].includes(String(value.status))
    && (value.installed_version_code === null || integer(value.installed_version_code))
    && (value.failure_code === null || typeof value.failure_code === 'string' && /^[a-z0-9_]{1,80}$/.test(value.failure_code))
    && typeof value.recovered_after_process_restart === 'boolean' && awareTime(value.recorded_at);
}
export function parseRecoveryStatus(value: unknown, deviceId: string): RecoveryStatus {
  if (!record(value) || value.device_id !== deviceId || !['none', 'active', 'expired', 'invalid', 'completed', 'failed'].includes(String(value.state))
    || !(value.active === null || isGrant(value.active)) || !(value.last_result === null || isReceipt(value.last_result))
    || !Array.isArray(value.recent_results) || value.recent_results.length > 32 || !value.recent_results.every(isReceipt)
    || !awareTime(value.observed_at) || (['active', 'expired'].includes(String(value.state)) && value.active === null)
    || (value.state === 'invalid' && value.active !== null)
    || (['completed', 'failed'].includes(String(value.state)) && (!record(value.last_result) || value.last_result.status !== value.state))) throw new Error('Invalid recovery status');
  // Explicit allowlist prevents an old server's authorization tag entering UI state.
  const grant = value.active as RecoveryGrant | null;
  return { device_id: deviceId, state: value.state as RecoveryStatus['state'], active: grant && {
    command_id: grant.command_id, sha256: grant.sha256, version_name: grant.version_name,
    version_code: grant.version_code, created_at: grant.created_at, expires_at: grant.expires_at,
  }, last_result: value.last_result ? sanitizeReceipt(value.last_result as RecoveryReceipt) : null,
    recent_results: value.recent_results.map(sanitizeReceipt), observed_at: value.observed_at };
}
function sanitizeReceipt(value: RecoveryReceipt): RecoveryReceipt {
  return { command_id: value.command_id, sha256: value.sha256, version_name: value.version_name, version_code: value.version_code,
    status: value.status, failure_code: value.failure_code, installed_version_code: value.installed_version_code,
    recovered_after_process_restart: value.recovered_after_process_restart, recorded_at: value.recorded_at };
}
export function verifyCreatedGrant(value: unknown, deviceId: string, release: OtaRelease, duration: number): RecoveryGrant {
  if (!record(value) || value.device_id !== deviceId || !isGrant(value) || value.sha256 !== release.sha256
    || value.version_code !== release.version_code || value.version_name !== release.version_name
    || value.expires_at - value.created_at !== duration || !['wake_published', 'awaiting_connection'].includes(String(value.delivery_hint))) {
    throw new Error('Unconfirmed grant');
  }
  return { command_id: value.command_id, sha256: value.sha256, version_name: value.version_name,
    version_code: value.version_code, created_at: value.created_at, expires_at: value.expires_at };
}
export function installEvidence(device: OtaDevice, status: RecoveryStatus, release: OtaRelease, now = Date.now()): 'different' | 'failed' | 'waiting' | 'confirmed' | 'none' {
  const result = status.last_result;
  if (!result) return 'none';
  if (result.sha256 !== release.sha256 || result.version_code !== release.version_code) return 'different';
  if (result.status === 'failed') return 'failed';
  const heartbeat = device.last_heartbeat ? Date.parse(device.last_heartbeat) : NaN;
  const fresh = ['online', 'busy'].includes(device.status) && heartbeat <= now + 5000 && now - heartbeat <= 60_000
    && heartbeat >= Date.parse(result.recorded_at) && Date.parse(status.observed_at) <= now + 5000;
  return fresh && device.agent_version_code === release.version_code && result.installed_version_code === release.version_code
    ? 'confirmed' : 'waiting';
}
export function recoveryError(error: unknown): string {
  const code = (error as { response?: { status?: number } } | null)?.response?.status;
  if (code === 403) return 'Нет права управлять OTA. Требуется super_admin.';
  if (code === 404) return 'Устройство или APK недоступны. Перечитайте состояние.';
  if (code === 409) return 'Разрешение изменилось или уже существует. Перечитайте состояние перед действием.';
  if (code === 422) return 'Сервер отклонил разрешение. Проверьте APK, цель и срок.';
  return 'Результат запроса неизвестен. Обновите состояние перед повторным действием.';
}
