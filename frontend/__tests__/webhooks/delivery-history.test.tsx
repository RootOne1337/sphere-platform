import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import WebhooksPage from '@/app/(dashboard)/webhooks/page';
import { api } from '@/lib/api';
import type { WebhookDeliveryDetail } from '@/src/features/webhooks/deliveryContract';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
let mockRead = true;
let mockWrite = true;
jest.mock('@/src/features/access/Capabilities', () => ({
  useCapabilities: () => ({
    can: (permission: string) => permission === 'webhook:read' ? mockRead : permission === 'webhook:write' && mockWrite,
  }),
  PermissionNotice: () => <p>Право чтения отсутствует.</p>,
}));

const subscription = {
  id: 'ae578d0a-58ca-4df2-9ad8-d23df7fefac0',
  name: 'Завершения',
  url: 'https://receiver.example.test/hooks',
  events: ['task.completed'],
  tags: [],
  is_active: true,
  secret: null,
  last_triggered_at: null,
  failure_count: 0,
  created_at: '2026-11-13T12:00:00Z',
  receiver_allowed: true,
};
const date = '2026-11-13T12:00:00Z';
const row: WebhookDeliveryDetail = {
  id: '2bc481b0-6263-4f33-b17a-383c5359cb0a',
  webhook_id: subscription.id,
  event_type: 'task.completed',
  status: 'dead',
  source: 'subscription',
  subject_id: '3734285c-ea5a-4f4d-8231-31fec9a6d338',
  attempts_count: 2,
  max_attempts: 4,
  next_attempt_at: null,
  last_http_status: 503,
  last_error: 'retry_exhausted',
  created_at: date,
  updated_at: date,
  replay_count: 0,
  can_replay: true,
  attempts: [
    { number: 1, status: 'unknown', started_at: date, finished_at: date, http_status: null, error: 'worker_interrupted' },
    { number: 2, status: 'dead', started_at: date, finished_at: date, http_status: 503, error: 'retry_exhausted' },
  ],
};
const path = `/n8n/deliveries/${row.id}`;
const accepted = { ...row, status: 'pending', can_replay: false, replay_count: 1, max_attempts: 6, next_attempt_at: date } satisfies WebhookDeliveryDetail;

function setup({ detail = () => Promise.resolve({ data: row }), total = 1 }: {
  detail?: () => Promise<{ data: WebhookDeliveryDetail }>;
  total?: number;
} = {}) {
  jest.mocked(api.get).mockImplementation(async (url, config) => {
    if (url === '/n8n/webhooks') return { data: { items: [subscription], total: 1, publishing_enabled: true } };
    if (url === path) return detail();
    if (url === '/n8n/deliveries') {
      const params = config?.params as { page: number; per_page: number };
      return { data: { items: [row], total, ...params } };
    }
    throw new Error('Unexpected fixture route');
  });
  return render(<WebhooksPage />, { wrapper: createWrapper() });
}

async function openHistory() {
  fireEvent.mouseDown(await screen.findByRole('tab', { name: 'История доставки' }), { button: 0, ctrlKey: false });
  return screen.findByRole('region', { name: 'Журнал доставки' });
}

async function openDetails() {
  const history = await openHistory();
  fireEvent.click(await within(history).findByRole('button', { name: `Открыть доставку ${row.id}` }));
  const dialog = within(await screen.findByRole('dialog', { name: 'Сведения о доставке' }));
  await dialog.findByRole('heading', { name: 'Попытки доставки' });
  return dialog;
}

beforeEach(() => {
  jest.resetAllMocks();
  mockRead = true;
  mockWrite = true;
});

it('opens history with the selected subscription, allows clearing it and pages the status filter', async () => {
  setup({ total: 26 });
  expect(await screen.findByText('Публикация включена для разрешённых получателей.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'История доставки вебхука Завершения' }));
  const history = within(await screen.findByRole('region', { name: 'Журнал доставки' }));
  expect(await screen.findByText('Подписка «Завершения»')).toBeInTheDocument();
  await history.findByText('task.completed');
  expect(api.get).toHaveBeenCalledWith('/n8n/deliveries', {
    params: { page: 1, per_page: 25, webhook_id: subscription.id }, signal: expect.any(AbortSignal),
  });
  fireEvent.click(screen.getByRole('button', { name: 'Все доставки' }));
  fireEvent.change(screen.getByLabelText('Статус доставки'), { target: { value: 'dead' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Следующая страница: доставки' }));
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/n8n/deliveries', {
    params: { page: 2, per_page: 25, status: 'dead' }, signal: expect.any(AbortSignal),
  }));
  expect(api.post).not.toHaveBeenCalled();
});

it('shows actual attempts, safe outcomes, and supports copying the stable ID', async () => {
  const writeText = jest.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
  setup();
  const dialog = await openDetails();
  expect(dialog.getByText(row.id)).toBeInTheDocument();
  expect(dialog.getByText(/Исход неизвестен/)).toBeInTheDocument();
  expect(dialog.getByText('Ответ потерян при остановке обработчика')).toBeInTheDocument();
  expect(dialog.getAllByText(/HTTP 503/)).toHaveLength(2);
  fireEvent.click(dialog.getByRole('button', { name: 'Скопировать ID' }));
  expect(await dialog.findByRole('button', { name: 'ID скопирован' })).toBeInTheDocument();
  expect(writeText).toHaveBeenCalledWith(row.id);
});

it('requires confirmed write access and server replay eligibility', async () => {
  mockWrite = false;
  setup();
  expect(screen.queryByRole('button', { name: 'Добавить вебхук' })).not.toBeInTheDocument();
  const dialog = await openDetails();
  expect(dialog.queryByRole('button', { name: 'Повторить доставку' })).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('never loads history or the registry without confirmed read access', () => {
  mockRead = false;
  setup();
  expect(screen.getByText('Право чтения отсутствует.')).toBeInTheDocument();
  expect(screen.queryByRole('tab', { name: 'История доставки' })).not.toBeInTheDocument();
  expect(api.get).not.toHaveBeenCalled();
});

it('requires explicit confirmation and verifies a receipt using the same delivery ID', async () => {
  let response = row;
  let complete!: (receipt: { data: WebhookDeliveryDetail }) => void;
  jest.mocked(api.post).mockImplementation(() => new Promise(resolve => { complete = resolve; }));
  setup({ detail: () => Promise.resolve({ data: response }) });
  const dialog = await openDetails();
  fireEvent.click(dialog.getByRole('button', { name: 'Повторить доставку' }));
  expect(api.post).not.toHaveBeenCalled();
  expect(dialog.getByText(/Получатель может обработать событие повторно/)).toBeInTheDocument();
  const button = dialog.getByRole('button', { name: 'Подтвердить повтор' });
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${path}/replay`));
  expect(api.post).toHaveBeenCalledTimes(1);
  response = accepted;
  await act(async () => complete({ data: accepted }));
  expect(await dialog.findByText('Повтор поставлен в очередь с тем же ID доставки.')).toBeInTheDocument();
  expect(dialog.queryByRole('button', { name: 'Повторить доставку' })).not.toBeInTheDocument();
});

it('blocks a second POST after losing its response until a successful exact reread', async () => {
  let readCount = 0;
  jest.mocked(api.post).mockRejectedValue(new Error('connection lost'));
  setup({ detail: async () => {
    readCount += 1;
    if (readCount === 2) throw new Error('connection lost');
    return { data: readCount > 2 ? accepted : row };
  } });
  const dialog = await openDetails();
  fireEvent.click(dialog.getByRole('button', { name: 'Повторить доставку' }));
  fireEvent.click(dialog.getByRole('button', { name: 'Подтвердить повтор' }));
  expect(await dialog.findByText(/Исход запроса повтора неизвестен/)).toBeInTheDocument();
  expect(dialog.queryByRole('button', { name: 'Повторить доставку' })).not.toBeInTheDocument();
  fireEvent.click(dialog.getByRole('button', { name: 'Обновить сведения' }));
  expect(await dialog.findByText('Сведения о доставке недоступны.')).toBeInTheDocument();
  expect(dialog.getByText(/Исход запроса повтора неизвестен/)).toBeInTheDocument();
  fireEvent.click(dialog.getByRole('button', { name: 'Обновить сведения' }));
  expect(await dialog.findByText('Повтор поставлен в очередь с тем же ID доставки.')).toBeInTheDocument();
  expect(dialog.queryByText(/Исход запроса повтора неизвестен/)).not.toBeInTheDocument();
  expect(dialog.queryByRole('button', { name: 'Повторить доставку' })).not.toBeInTheDocument();
  expect(api.post).toHaveBeenCalledTimes(1);
});
