/** HTTP success is not enough: interactive endpoints return either a string
 * result (including an empty successful output) or an explicit device error. */
export function interactiveResult(value: unknown, field: 'output' | 'logcat'): string {
  if (!value || typeof value !== 'object') throw new Error('API не подтвердил результат команды.');
  const data = value as Record<string, unknown>;
  if (typeof data.error === 'string' && data.error) throw new Error(data.error);
  if (typeof data[field] !== 'string') throw new Error('API вернул неполный результат команды.');
  return data[field] as string;
}
// Backend waits 30 s for shell, 15 s for logs and 10 s for reboot receipts.
// Keep the HTTP wait longer than those deadlines without changing read queries.
export const DEVICE_COMMAND_TIMEOUT = { shell: 35_000, logs: 20_000, reboot: 15_000 } as const;

