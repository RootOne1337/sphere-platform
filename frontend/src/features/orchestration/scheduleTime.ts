/** A one-shot is an absolute instant. The editor explicitly uses UTC, independently of browser and CRON zones. */
export function isoToUtcDateTimeInput(value: string): string {
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(value)) throw new Error('Дата запуска API должна содержать часовой пояс.');
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new Error('Некорректная дата запуска API.');
  return date.toISOString().slice(0, -1);
}

export function utcDateTimeInputToIso(value: string): string {
  const parts = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/.exec(value);
  if (!parts) throw new Error('Укажите дату и время запуска в UTC.');
  const iso = `${parts[1]}T${parts[2]}:${parts[3] ?? '00'}.${(parts[4] ?? '').padEnd(3, '0')}Z`;
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime()) || date.toISOString() !== iso) throw new Error('Проверьте дату и время запуска в UTC.');
  return iso;
}

export function isValidUtcDateTimeInput(value: string): boolean {
  try { utcDateTimeInputToIso(value); return true; } catch { return false; }
}
