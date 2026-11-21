import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import WebhooksPage from '@/app/(dashboard)/webhooks/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/src/features/access/Capabilities', () => ({
  useCapabilities: () => ({ can: () => true }),
}));

const active = {
  id: 'active',
  name: 'Планировщик',
  url: 'https://recipient.example.test/hooks/tasks',
  events: ['task.completed'],
  tags: [],
  is_active: true,
  secret: null,
  last_triggered_at: null,
  failure_count: 7,
  created_at: '2026-11-13T12:00:00Z',
};
const inactive = {
  ...active,
  id: 'inactive',
  name: 'Архив',
  is_active: false,
  last_triggered_at: '2026-11-13T12:01:00Z',
  failure_count: 0,
};
const response = (...items: (typeof active | typeof inactive)[]) => ({
  data: { items, total: items.length, publishing_enabled: false, supported_events: ['task.completed', 'task.failed'] },
}) as never;

beforeEach(() => {
  jest.resetAllMocks();
  jest.mocked(api.get).mockResolvedValue(response(active, inactive));
  jest.mocked(api.patch).mockResolvedValue({ status: 200 } as never);
  jest.mocked(api.delete).mockResolvedValue({ status: 204 } as never);
});

it('shows configured state separately from stored delivery observations', async () => {
  render(<WebhooksPage />, { wrapper: createWrapper() });
  await screen.findByRole('heading', { name: active.name });
  expect(screen.getByText('Включён')).toBeInTheDocument();
  expect(screen.getByText('Успешная доставка не зафиксирована')).toBeInTheDocument();
  expect(screen.getByText('7')).toBeInTheDocument();
  expect(screen.getByText('Отключён')).toBeInTheDocument();
  expect(screen.getByText('0')).toBeInTheDocument();
  expect(screen.getAllByText('Последняя зафиксированная доставка', { selector: 'dt' })).toHaveLength(2);
  expect(document.querySelector('time')).toHaveAttribute('datetime', '2026-11-13T12:01:00.000Z');
  expect(api.get).toHaveBeenCalledWith('/n8n/webhooks', { signal: expect.any(AbortSignal) });
  expect(api.post).not.toHaveBeenCalled();
  expect(api.patch).not.toHaveBeenCalled();
  expect(api.delete).not.toHaveBeenCalled();
});

it('shows configured publication state even with no subscriptions', async () => {
  jest.mocked(api.get).mockResolvedValue(response());
  render(<WebhooksPage />, { wrapper: createWrapper() });
  await screen.findByText('Вебхуков пока нет');
  expect(screen.getByRole('heading', { name: 'Публикация событий подписок' })).toBeInTheDocument();
  expect(screen.getByText(/Публикация подписок выключена на сервере/)).toBeInTheDocument();
  expect(screen.getByText('События task.completed, task.failed')).toBeInTheDocument();
  expect(screen.queryByText(/Создайте endpoint, чтобы передавать/)).not.toBeInTheDocument();
});

it('keeps a disabled row available and confirms re-enable from a new list response', async () => {
  jest.mocked(api.get).mockResolvedValueOnce(response(active, inactive)).mockResolvedValue(response(active, { ...inactive, is_active: true }));
  let resolve!: () => void;
  jest.mocked(api.patch).mockImplementation(() => new Promise<void>((done) => { resolve = done; }) as never);
  render(<WebhooksPage />, { wrapper: createWrapper() });
  const enable = await screen.findByRole('button', { name: 'Включить вебхук Архив' });
  fireEvent.click(enable);
  fireEvent.click(enable);
  await waitFor(() => expect(api.patch).toHaveBeenCalledWith('/n8n/webhooks/inactive', { is_active: true }));
  expect(api.patch).toHaveBeenCalledTimes(1);
  expect(enable).toBeDisabled();
  expect(enable).toHaveTextContent('Включаем…');
  expect(screen.getByText('Отключён')).toBeInTheDocument();
  await act(async () => { resolve(); });
  expect(await screen.findByRole('button', { name: 'Отключить вебхук Архив' })).toBeEnabled();
  expect(await screen.findByRole('status')).toHaveTextContent('Вебхук включён.');
  expect(api.get).toHaveBeenCalledTimes(2);
});

it('retains the configured row and shows a local error when toggle fails', async () => {
  jest.mocked(api.patch).mockRejectedValue(new Error('fixture'));
  render(<WebhooksPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Отключить вебхук Планировщик' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Изменение не подтверждено.');
  expect(screen.getByText('Включён')).toBeInTheDocument();
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

it('preserves stale data and disables row controls after refresh fails', async () => {
  jest.mocked(api.get).mockResolvedValueOnce(response(active)).mockRejectedValue(new Error('fixture'));
  render(<WebhooksPage />, { wrapper: createWrapper() });
  await screen.findByRole('heading', { name: active.name });
  fireEvent.click(screen.getByRole('button', { name: 'Обновить' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Показаны данные последнего успешного запроса.');
  expect(screen.getByText('7')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Отключить вебхук Планировщик' })).toBeDisabled();
});

it('distinguishes a saved change from a failed verification read', async () => {
  jest.mocked(api.get).mockResolvedValueOnce(response(active)).mockRejectedValue(new Error('fixture'));
  render(<WebhooksPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Отключить вебхук Планировщик' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Сервер принял изменение. Обновите список, чтобы сверить результат.');
  expect(screen.getByRole('alert')).toHaveTextContent('Показаны данные последнего успешного запроса.');
  expect(screen.getByRole('button', { name: 'Отключить вебхук Планировщик' })).toBeDisabled();
});

it('confirms removal after the list no longer includes the webhook', async () => {
  jest.mocked(api.get).mockResolvedValueOnce(response(active, inactive)).mockResolvedValue(response(active));
  render(<WebhooksPage />, { wrapper: createWrapper() });
  fireEvent.click(await screen.findByRole('button', { name: 'Удалить вебхук Архив' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Удалить вебхук' }));
  expect(await screen.findByRole('status')).toHaveTextContent('Вебхук удалён.');
  expect(screen.queryByRole('heading', { name: 'Архив' })).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Обновить' })).toHaveFocus());
});

it('requires an accessible delete confirmation and keeps failed deletion visible', async () => {
  jest.mocked(api.delete).mockRejectedValue(new Error('fixture'));
  render(<WebhooksPage />, { wrapper: createWrapper() });
  const remove = await screen.findByRole('button', { name: 'Удалить вебхук Архив' });
  fireEvent.click(remove);
  const dialog = screen.getByRole('dialog', { name: 'Удалить вебхук «Архив»?' });
  expect(api.delete).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Отмена' }));
  await waitFor(() => expect(remove).toHaveFocus());
  fireEvent.click(remove);
  const confirmation = within(screen.getByRole('dialog')).getByRole('button', { name: 'Удалить вебхук' });
  fireEvent.click(confirmation);
  expect(await screen.findByRole('alert')).toHaveTextContent('Удаление не подтверждено.');
  expect(confirmation).toBeDisabled();
  expect(api.delete).toHaveBeenCalledWith('/n8n/webhooks/inactive');
});
