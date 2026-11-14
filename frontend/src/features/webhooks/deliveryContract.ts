export const DELIVERY_STATUSES = ['pending', 'sending', 'delivered', 'dead'] as const;
export type DeliveryStatus = (typeof DELIVERY_STATUSES)[number];
const ATTEMPT_STATUSES = ['sending', 'delivered', 'retry', 'dead', 'unknown'] as const;
type AttemptStatus = (typeof ATTEMPT_STATUSES)[number];

export interface WebhookDelivery {
  id: string;
  webhook_id: string | null;
  event_type: string;
  status: DeliveryStatus;
  source: 'task_callback' | 'subscription';
  subject_id: string | null;
  attempts_count: number;
  max_attempts: number;
  next_attempt_at: string | null;
  last_http_status: number | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  replay_count: number;
  can_replay: boolean;
}

interface WebhookAttempt {
  number: number;
  status: AttemptStatus;
  http_status: number | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface WebhookDeliveryDetail extends WebhookDelivery {
  attempts: WebhookAttempt[];
}

interface DeliveryPage {
  items: WebhookDelivery[];
  total: number;
  page: number;
  per_page: number;
}

export const DELIVERY_PAGE_SIZE = 25;
export const isDeliveryId = (value: unknown): value is string =>
  typeof value === 'string' && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
const isCount = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const isTimestamp = (value: unknown): value is string =>
  typeof value === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const isHttpStatus = (value: unknown): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value >= 100 && value <= 599;
const isErrorCode = (value: unknown): value is string =>
  typeof value === 'string' && /^[a-z0-9_]{1,80}$/.test(value);

export function parseDelivery(value: unknown, id?: string): WebhookDelivery {
  if (!value || typeof value !== 'object') throw new Error('Invalid webhook delivery');
  const row = value as WebhookDelivery;
  if (!isDeliveryId(row.id) || (id && row.id !== id) || (row.webhook_id !== null && !isDeliveryId(row.webhook_id))
    || (row.subject_id !== null && !isDeliveryId(row.subject_id))
    || typeof row.event_type !== 'string' || !row.event_type || row.event_type.length > 200
    || !DELIVERY_STATUSES.includes(row.status) || (row.source !== 'task_callback' && row.source !== 'subscription')
    || !isCount(row.attempts_count) || !isCount(row.max_attempts) || row.max_attempts < 1
    || (row.next_attempt_at !== null && !isTimestamp(row.next_attempt_at))
    || (row.last_http_status !== null && !isHttpStatus(row.last_http_status))
    || (row.last_error !== null && !isErrorCode(row.last_error))
    || !isTimestamp(row.created_at) || !isTimestamp(row.updated_at) || !isCount(row.replay_count)
    || typeof row.can_replay !== 'boolean' || (row.can_replay && row.status !== 'dead')) {
    throw new Error('Invalid webhook delivery');
  }
  const { webhook_id, event_type, status, source, subject_id, attempts_count, max_attempts, next_attempt_at,
    last_http_status, last_error, created_at, updated_at, replay_count, can_replay } = row;
  return { id: row.id, webhook_id, event_type, status, source, subject_id, attempts_count, max_attempts,
    next_attempt_at, last_http_status, last_error, created_at, updated_at, replay_count, can_replay };
}

export function parseDeliveryPage(value: unknown, page: number, status: DeliveryStatus | '', webhookId?: string): DeliveryPage {
  if (!value || typeof value !== 'object') throw new Error('Invalid webhook delivery page');
  const data = value as DeliveryPage;
  if (!Array.isArray(data.items) || data.page !== page || data.per_page !== DELIVERY_PAGE_SIZE
    || !isCount(data.total) || data.items.length > Math.min(DELIVERY_PAGE_SIZE, data.total)) {
    throw new Error('Invalid webhook delivery page');
  }
  const items = data.items.map(item => parseDelivery(item));
  if (new Set(items.map(item => item.id)).size !== items.length || items.some(item =>
    (status && item.status !== status) || (webhookId && item.webhook_id !== webhookId))) {
    throw new Error('Webhook history does not match the requested filter');
  }
  return { items, total: data.total, page: data.page, per_page: data.per_page };
}

export function parseDeliveryDetail(value: unknown, id: string): WebhookDeliveryDetail {
  const delivery = parseDelivery(value, id);
  const { attempts } = value as WebhookDeliveryDetail;
  if (!Array.isArray(attempts) || attempts.length > 32 || new Set(attempts.map(attempt => attempt?.number)).size !== attempts.length
    || attempts.some(attempt => !attempt || !isCount(attempt.number) || attempt.number < 1
      || !ATTEMPT_STATUSES.includes(attempt.status) || !isTimestamp(attempt.started_at)
      || (attempt.finished_at !== null && !isTimestamp(attempt.finished_at))
      || (attempt.http_status !== null && !isHttpStatus(attempt.http_status))
      || (attempt.error !== null && !isErrorCode(attempt.error)))) {
    throw new Error('Invalid webhook delivery attempts');
  }
  return {
    ...delivery,
    attempts: attempts.map(({ number, status, http_status, error, started_at, finished_at }) =>
      ({ number, status, http_status, error, started_at, finished_at })).sort((first, second) => first.number - second.number),
  };
}

const reasonLabels: Record<string, string> = {
  receiver_not_allowed: 'Получатель не разрешён',
  subscription_disabled: 'Подписка отключена или удалена',
  transport_error: 'Не удалось связаться с получателем',
  timeout: 'Истёк срок ожидания ответа',
  worker_interrupted: 'Ответ потерян при остановке обработчика',
  retry_exhausted: 'Лимит попыток исчерпан',
  invalid_receiver: 'Некорректный получатель',
  payload_too_large: 'Тело события превышает допустимый размер',
  subscription_fanout_limit: 'Превышен лимит получателей события',
  delivery_capacity_reached: 'Очередь организации заполнена',
  delivery_storage_capacity: 'Хранилище доставок заполнено',
  rate_limited: 'Получатель ограничил частоту запросов',
  server_error: 'Ошибка сервера получателя',
  rejected: 'Получатель отклонил запрос',
};

export function deliveryReason(code: string | null): string {
  return code ? reasonLabels[code] ?? 'Причина не распознана' : '—';
}
