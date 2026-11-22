import { awareTime } from './recovery';

export interface ReleaseDraft {
  platform: string; flavor: string; version_code: string; version_name: string;
  download_url: string; sha256: string; mandatory: boolean; changelog: string;
}
export interface ReleaseIntent {
  platform: string; flavor: string; version_code: number; version_name: string;
  download_url: string; sha256: string; mandatory: boolean; changelog: string | null;
}
export type ReleaseErrors = Partial<Record<keyof ReleaseDraft, string>>;
const digest = /^[a-f0-9]{64}$/;
const managed = '/api/v1/updates/artifacts/';
export function validateReleaseDraft(draft: ReleaseDraft): { errors: ReleaseErrors; intent?: ReleaseIntent } {
  const errors: ReleaseErrors = {};
  if (!['android', 'android-canary', 'pc'].includes(draft.platform)) errors.platform = 'Выберите поддерживаемую платформу.';
  if (!['enterprise', 'dev'].includes(draft.flavor)) errors.flavor = 'Выберите enterprise или dev.';
  const version = Number(draft.version_code);
  if (!/^\d+$/.test(draft.version_code) || !Number.isSafeInteger(version) || version < 1 || version > 2_147_483_647) errors.version_code = 'Нужен целый номер версии от 1 до 2147483647.';
  if (!draft.version_name.trim() || draft.version_name.length > 128 || /[\x00-\x1f]/.test(draft.version_name)) errors.version_name = 'Укажите точное имя версии из APK, до 128 символов.';
  if (!digest.test(draft.sha256)) errors.sha256 = 'SHA-256: ровно 64 символа 0–9 и a–f.';
  let validUrl = draft.download_url === managed + draft.sha256 && digest.test(draft.sha256);
  try {
    const url = new URL(draft.download_url);
    validUrl ||= url.protocol === 'https:' && Boolean(url.hostname) && !url.username && !url.password && !url.hash;
  } catch { /* Managed relative paths are checked above. */ }
  if (!validUrl || draft.download_url.length > 4096 || /[\s\x00-\x1f\\]/.test(draft.download_url)) errors.download_url = 'Нужен HTTPS URL без пароля и фрагмента либо managed-путь с тем же SHA-256.';
  if (draft.changelog.length > 16_384) errors.changelog = 'Описание не должно превышать 16384 символа.';
  return Object.keys(errors).length ? { errors } : { errors, intent: { ...draft, version_code: version, changelog: draft.changelog || null } };
}

export function verifyReleaseReceipt(value: unknown, intent: ReleaseIntent): string {
  if (!value || typeof value !== 'object') throw new Error('Invalid publication receipt');
  const row = value as Record<string, unknown>;
  if (typeof row.id !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(row.id)
    || !awareTime(row.created_at) || Object.entries(intent).some(([key, expected]) => row[key] !== expected)) {
    throw new Error('Publication receipt does not match the requested release');
  }
  return row.id;
}

export function publicationFailure(error: unknown): { unknown: boolean; message: string } {
  const status = (error as { response?: { status?: number } } | null)?.response?.status;
  if (status === 409) return { unknown: true, message: 'Эта версия уже есть в канале. Сверьте каталог; повторная публикация заблокирована.' };
  if (status === 422) return { unknown: false, message: 'Сервер отклонил метаданные или managed APK. Проверьте файл, SHA-256 и поля релиза.' };
  if (status === 401 || status === 403) return { unknown: false, message: 'Нет права публиковать релиз. Требуется активная сессия super_admin.' };
  return { unknown: true, message: 'Результат публикации неизвестен. Сверьте каталог перед любым повтором.' };
}
