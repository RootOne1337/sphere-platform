import type { Location } from '@/lib/hooks/useLocations';

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const fields = ['name', 'description', 'color', 'address', 'latitude', 'longitude', 'parent_location_id'] as const;
export type LocationPatch = Partial<Pick<Location, typeof fields[number]>>;
export type LocationDraft = { name: string; description: string; color: string; address: string; latitude: string; longitude: string; parent_location_id: string };
export function parseLocation(value: unknown, orgId: string, id?: string): Location {
  if (!value || typeof value !== 'object') throw new Error('Invalid location response');
  const v = value as Location;
  if (!uuid.test(v.id) || (id && v.id !== id) || v.org_id !== orgId || !v.name?.trim()
    || !['created_at', 'updated_at'].every(k => typeof v[k as keyof Location] === 'string' && Number.isFinite(Date.parse(v[k as keyof Location] as string)))
    || !['description', 'address'].every(k => v[k as keyof Location] === null || typeof v[k as keyof Location] === 'string')
    || !(v.color === null || typeof v.color === 'string' && /^#[0-9a-f]{6}$/i.test(v.color))
    || !(v.parent_location_id === null || typeof v.parent_location_id === 'string' && uuid.test(v.parent_location_id))
    || !validCoordinate(v.latitude, 90) || !validCoordinate(v.longitude, 180)
    || !Number.isInteger(v.total_devices) || !Number.isInteger(v.online_devices) || v.total_devices < 0 || v.online_devices < 0 || v.online_devices > v.total_devices) throw new Error('Invalid location response');
  return v;
}
function validCoordinate(value: unknown, limit: number) { return value === null || typeof value === 'number' && Number.isFinite(value) && Math.abs(value) <= limit; }
export const emptyLocationDraft = (): LocationDraft => ({ name: '', description: '', address: '', color: '#3b82f6', latitude: '', longitude: '', parent_location_id: '' });
export const locationDraft = (v: Location): LocationDraft => ({ name: v.name, description: v.description ?? '', address: v.address ?? '', color: v.color ?? '', latitude: v.latitude === null ? '' : String(v.latitude), longitude: v.longitude === null ? '' : String(v.longitude), parent_location_id: v.parent_location_id ?? '' });
export function locationPath(location: Location, catalog: Location[]): { label: string; valid: boolean } {
  const byId = new Map(catalog.map(v => [v.id, v]));
  const seen = new Set<string>(); const names: string[] = [];
  let current: Location | undefined = location;
  while (current) {
    if (seen.has(current.id)) return { label: 'Некорректная иерархия', valid: false };
    seen.add(current.id); names.unshift(current.name);
    if (current.parent_location_id === null) return { label: names.join(' / '), valid: true };
    current = byId.get(current.parent_location_id);
  }
  return { label: 'Родитель недоступен', valid: false };
}
export function parentChoices(catalog: Location[], editingId?: string): Location[] {
  const byId = new Map(catalog.map(v => [v.id, v]));
  return catalog.filter(v => {
    const seen = new Set<string>(); let current: Location | undefined = v;
    while (current) {
      if (current.id === editingId || seen.has(current.id)) return false;
      seen.add(current.id);
      if (current.parent_location_id === null) return true;
      current = byId.get(current.parent_location_id);
    }
    return false;
  });
}
export function validateLocationDraft(draft: LocationDraft, catalog: Location[], baseline?: Location): LocationPatch & { name?: string } {
  const name = draft.name.trim();
  if (!name || name.length > 255) throw new Error('Название: от 1 до 255 символов.');
  if (draft.description.trim().length > 1000 || draft.address.trim().length > 500) throw new Error('Описание: до 1000 символов; адрес: до 500.');
  if (draft.color && !/^#[0-9a-f]{6}$/i.test(draft.color)) throw new Error('Цвет: #RRGGBB или пустое значение.');
  const coordinate = (text: string, limit: number, label: string) => {
    if (!text.trim()) return null;
    const v = Number(text);
    if (!/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(text.trim()) || !Number.isFinite(v) || Math.abs(v) > limit) throw new Error(`${label}: число от −${limit} до ${limit} или пустое значение.`);
    return v;
  };
  const parent = draft.parent_location_id || null;
  if (parent && !parentChoices(catalog, baseline?.id).some(v => v.id === parent)) throw new Error('Родитель недоступен или образует цикл. Выберите другую локацию.');
  const result: LocationPatch = { name, description: draft.description.trim() || null, address: draft.address.trim() || null,
    color: draft.color || null, latitude: coordinate(draft.latitude, 90, 'Широта'), longitude: coordinate(draft.longitude, 180, 'Долгота'), parent_location_id: parent };
  return baseline ? Object.fromEntries(fields.filter(k => result[k] !== baseline[k]).map(k => [k, result[k]])) : result;
}
export function verifyLocationReceipt(value: unknown, orgId: string, patch: LocationPatch, baseline?: Location): Location {
  const result = parseLocation(value, orgId, baseline?.id);
  for (const field of fields) {
    if (field in patch ? result[field] !== patch[field] : baseline && result[field] !== baseline[field]) throw new Error('Unconfirmed location write');
  }
  if (baseline && (result.created_at !== baseline.created_at || Date.parse(result.updated_at) < Date.parse(baseline.updated_at))) throw new Error('Invalid location revision');
  return result;
}
export function locationFailure(error: unknown): string {
  const status = (error as { response?: { status?: number } })?.response?.status;
  if (status === 403) return 'Нет права изменять локацию. Проверьте роль и перечитайте состояние.';
  if (status === 404) return 'Локация или родитель недоступны. Перечитайте каталог.';
  if (status === 409) return 'Конфликт: локация изменена, имя занято или другая запись ещё выполняется. Черновик сохранён; перечитайте состояние.';
  if (status === 400 || status === 422) return 'Сервер отклонил поля или иерархию. Проверьте данные и перечитайте состояние.';
  return 'Результат записи неизвестен. Повтор заблокирован; сначала перечитайте состояние и проверьте результат.';
}
