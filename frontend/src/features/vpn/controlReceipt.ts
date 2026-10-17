export type VpnControl = 'rotate' | 'enable' | 'disable' | 'reboot';
export interface ControlOutcome { deviceId: string; outcome: string; detail: string; retryable: boolean }
const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid control receipt');
  return value as Record<string, unknown>;
};
const nullableText = (value: unknown) => value === null || typeof value === 'string';

/** Validate exact membership and counts before displaying any success. */
export function controlReceipt(kind: VpnControl, payload: unknown, ids: string[]): ControlOutcome[] {
  const data = record(payload);
  if (!ids.length || ids.length > 500 || new Set(ids).size !== ids.length || data.total !== ids.length) throw new Error('Invalid targets');
  let rows: ControlOutcome[];
  if (kind === 'rotate') {
    if (data.execution_confirmed !== false || !Array.isArray(data.details)) throw new Error('Missing rotation evidence');
    rows = data.details.map(value => {
      const v = record(value);
      if (typeof v.device_id !== 'string' || !['configured', 'rejected', 'unknown'].includes(String(v.outcome))
        || typeof v.revoke_confirmed !== 'boolean' || !nullableText(v.old_ip) || !nullableText(v.new_ip) || !nullableText(v.error)
        || (v.outcome === 'configured' && (!v.revoke_confirmed || !v.new_ip || v.error !== null))) throw new Error('Invalid rotation outcome');
      return { deviceId: v.device_id, outcome: String(v.outcome), retryable: false,
        detail: v.outcome === 'configured' ? `Router: ${v.old_ip ?? '—'} → ${v.new_ip}. Применение APK не подтверждено.`
          : v.outcome === 'rejected' ? 'Отклонено до ротации: назначенный peer не найден.'
            : `Результат неизвестен. Отзыв прежнего peer: ${v.revoke_confirmed ? 'подтверждён' : 'не подтверждён'}. Нужна сверка состояния.` };
    });
    if (data.success !== rows.filter(v => v.outcome === 'configured').length || data.failed !== rows.filter(v => v.outcome !== 'configured').length) throw new Error('Invalid rotation counts');
  } else if (kind === 'reboot') {
    if (!Array.isArray(data.results)) throw new Error('Missing reboot evidence');
    rows = data.results.map(value => {
      const v = record(value);
      if (typeof v.device_id !== 'string' || typeof v.success !== 'boolean' || !nullableText(v.error)) throw new Error('Invalid reboot outcome');
      return { deviceId: v.device_id, outcome: v.success ? 'acknowledged' : 'unknown', retryable: false,
        detail: v.success ? 'Агент подтвердил получение/запуск команды. Завершение перезагрузки проверяется новым heartbeat.'
          : 'Команда не подтверждена. Проверьте heartbeat и состояние перед новой перезагрузкой.' };
    });
    if (data.succeeded !== rows.filter(v => v.outcome === 'acknowledged').length || data.failed !== rows.filter(v => v.outcome !== 'acknowledged').length) throw new Error('Invalid reboot counts');
  } else {
    const outcomes = record(data.outcomes); const results = record(data.results);
    if (data.action !== kind || data.execution_confirmed !== false || Object.keys(results).length !== ids.length) throw new Error('Missing kill switch evidence');
    rows = Object.entries(outcomes).map(([deviceId, outcome]) => {
      if (!['submitted', 'not_sent', 'unsupported', 'unknown'].includes(String(outcome)) || results[deviceId] !== (outcome === 'submitted')) throw new Error('Invalid kill switch outcome');
      const detail = outcome === 'submitted' ? 'Отправитель принял команду; выполнение APK не подтверждено.'
        : outcome === 'not_sent' ? 'Отправитель не принял команду.'
          : outcome === 'unsupported' ? 'Kill switch не подключён к совместимому Android transport. Команда не отправлялась.'
            : 'Исход отправки неизвестен. Повтор запрещён до сверки состояния.';
      return { deviceId, outcome: String(outcome), detail, retryable: outcome === 'not_sent' };
    });
    if (data.success !== rows.filter(v => v.outcome === 'submitted').length) throw new Error('Invalid kill switch counts');
  }
  if (rows.length !== ids.length || new Set(rows.map(v => v.deviceId)).size !== ids.length
    || rows.some(v => !ids.includes(v.deviceId))) throw new Error('Mismatched receipt targets');
  return rows;
}

export function controlFailure(error: unknown): { unknown: boolean; message: string } {
  const status = (error as { response?: { status?: number } })?.response?.status;
  // These routes reject authentication, ownership or request validation before
  // provider dispatch. Other statuses/timeouts cannot establish no side effects.
  const rejected = [400, 401, 403, 404, 422].includes(status ?? 0);
  return { unknown: !rejected, message: rejected ? 'API отклонил запрос до выполнения. Проверьте права, устройства и параметры.'
    : 'Результат неизвестен: ответ не подтверждён. Повтор заблокирован; проверьте состояние устройства и VPN peer.' };
}
