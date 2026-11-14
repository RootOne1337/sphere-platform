export type DeviceLogError = {
  message: string;
  requestId: string | null;
  retryAfterSeconds: number | null;
  discardSnapshot: boolean;
};

export function describeDeviceLogError(
  error: unknown, operation: 'read' | 'delete' = 'read', receivedHeaders?: Record<string, unknown>,
): DeviceLogError {
  const failure = error as {
    message?: unknown;
    response?: { status?: number; data?: { detail?: unknown; reason?: unknown }; headers?: Record<string, unknown> };
  } | null;
  const response = failure?.response;
  const headers = response?.headers ?? receivedHeaders;
  const rawId = headers?.['x-request-id'] ?? headers?.['X-Request-ID'];
  const requestId = typeof rawId === 'string' && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/.test(rawId) ? rawId : null;
  const rawRetry = headers?.['retry-after'] ?? headers?.['Retry-After'];
  const retrySeconds = typeof rawRetry === 'string' && /^\d{1,4}$/.test(rawRetry) ? Number(rawRetry) : 0;
  const detail = response?.data?.detail;
  const reason = response?.data?.reason;

  let message: string;
  let retryAfterSeconds: number | null = null;
  switch (response?.status) {
    case 401:
      message = 'Сеанс истёк. Войдите снова.';
      break;
    case 403:
      message = 'Недостаточно прав для этой операции с журналом.';
      break;
    case 404:
      message = 'Устройство недоступно или отсутствует в каталоге.';
      break;
    case 422:
      message = 'Сервер отклонил параметры запроса.';
      break;
    case 503:
      if (reason === 'log_read_busy' || detail === 'Log read capacity is busy' || detail === 'Log write capacity is busy') {
        message = operation === 'read' ? 'Чтение журнала временно перегружено.' : 'Хранилище журналов временно перегружено.';
        retryAfterSeconds = Math.min(retrySeconds || 1, 60);
      } else if (reason === 'log_source_unavailable' || detail === 'Log source is unavailable' || detail === 'Log storage is unavailable') {
        message = 'Источник журнала недоступен. Проверьте хранилище.';
      } else {
        message = 'Сервис журналов недоступен (HTTP 503).';
      }
      break;
    default:
      if (Number.isInteger(response?.status)) {
        message = `Запрос журнала завершился ошибкой HTTP ${response?.status}.`;
      } else if (typeof failure?.message === 'string' && /^Backend (вернул|превысил)/.test(failure.message)) {
        message = failure.message;
      } else {
        message = 'Не удалось выполнить запрос к серверу журналов.';
      }
  }
  return { message, requestId, retryAfterSeconds, discardSnapshot: [401, 403, 404].includes(response?.status ?? 0) };
}
