import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import EventTriggersPage from '@/app/(dashboard)/event-triggers/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn(), patch: jest.fn(), delete: jest.fn() } }));
jest.mock('@/src/features/access/Capabilities', () => ({
  useCapabilities: () => ({ can: () => true }),
  PermissionNotice: () => null,
}));

const makeTrigger = (number: number) => ({
  id: `trigger-${number}`, org_id: 'org-a', name: `Trigger ${number}`, description: null,
  event_type_pattern: 'task.*', pipeline_id: 'pipeline-a', input_params_template: {},
  is_active: true, cooldown_seconds: 10, max_triggers_per_hour: 5,
  last_triggered_at: null, total_triggers: number, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
});
const triggers = Array.from({ length: 101 }, (_, index) => makeTrigger(index + 1));
const envelope = (page: number) => ({ data: { items: triggers.slice((page - 1) * 100, page * 100), total: 101, page, per_page: 100, pages: 2 } });
const params = (config: { params?: unknown } | undefined) => (config?.params ?? {}) as { page?: number };

beforeEach(() => jest.resetAllMocks());

it('retries failed pipeline catalog reads, reaches later pages and excludes inactive targets', async () => {
  let activeReads = 0;
  jest.mocked(api.get).mockImplementation(async (url, config) => {
    if (url === '/event-triggers') return envelope(1) as never;
    const query = config?.params as { page: number; is_active?: boolean };
    if (!query.is_active) return { data: { items: [], total: 0 } } as never;
    if (++activeReads === 1) throw new Error('offline');
    return { data: { total: 51, items: query.page === 1
      ? [{ id: 'a', name: 'First option', is_active: true }, { id: 'b', name: 'Inactive option', is_active: false }]
      : [{ id: 'c', name: 'Later option', is_active: true }] } } as never;
  });
  render(<EventTriggersPage />, { wrapper: createWrapper() });
  fireEvent.click(screen.getByRole('button', { name: 'Создать триггер' }));
  const form = within(await screen.findByRole('dialog'));
  await form.findByText('Не удалось загрузить каталог пайплайнов.');
  expect(form.getByRole('button', { name: 'Создать' })).toBeDisabled();
  fireEvent.click(form.getByRole('button', { name: 'Повторить загрузку пайплайнов' }));
  expect(await form.findByRole('option', { name: 'First option' })).toBeInTheDocument();
  expect(form.queryByRole('option', { name: 'Inactive option' })).not.toBeInTheDocument();
  fireEvent.click(form.getByRole('button', { name: 'Следующая страница: пайплайны' }));
  expect(await form.findByRole('option', { name: 'Later option' })).toBeInTheDocument();
  fireEvent.change(form.getByRole('combobox', { name: 'Пайплайн для запуска *' }), { target: { value: 'c' } });
  fireEvent.change(form.getByLabelText('Имя *'), { target: { value: 'Later trigger' } });
  fireEvent.change(form.getByLabelText('Шаблон события (glob) *'), { target: { value: 'task.failed' } });
  fireEvent.change(form.getByLabelText('Шаблон параметров (JSON)'), { target: { value: '[]' } });
  fireEvent.click(form.getByRole('button', { name: 'Создать' }));
  expect(form.getByRole('alert')).toHaveTextContent('Шаблон параметров должен быть JSON-объектом.');
  expect(api.post).not.toHaveBeenCalled();
});

it('reaches and opens the 101st trigger while keeping the server total', async () => {
  jest.mocked(api.get).mockImplementation(async (url, config) => url === '/event-triggers' ? envelope(params(config).page ?? 1) as never : { data: { items: [] } } as never);
  render(<EventTriggersPage />, { wrapper: createWrapper() });
  await screen.findByText('Trigger 1');
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница: триггеры' }));
  expect(await screen.findByText('Trigger 101')).toBeInTheDocument();
  expect(screen.queryByText('Trigger 1')).not.toBeInTheDocument();
  expect(screen.getByText('Страница 2 из 2 · всего 101')).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/event-triggers', { params: { page: 2, per_page: 100, is_active: undefined }, signal: expect.any(AbortSignal) });
  fireEvent.click(within(screen.getByText('Trigger 101').closest('tr')!).getByTitle('Редактировать'));
  expect(await screen.findByRole('dialog')).toBeInTheDocument();
  expect(screen.getByDisplayValue('Trigger 101')).toBeInTheDocument();
});

it('labels local search and permits continuing to pages outside the current local match set', async () => {
  jest.mocked(api.get).mockImplementation(async (url, config) => url === '/event-triggers' ? envelope(params(config).page ?? 1) as never : { data: { items: [] } } as never);
  render(<EventTriggersPage />, { wrapper: createWrapper() });
  await screen.findByText('Trigger 1');
  fireEvent.change(screen.getByRole('textbox', { name: 'Поиск триггеров на текущей странице' }), { target: { value: 'Trigger 101' } });
  expect(screen.getByText('Ничего не найдено на этой странице')).toBeInTheDocument();
  expect(screen.getByText(/Текстовый поиск действует на текущую страницу/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница: триггеры' }));
  expect(await screen.findByText('Trigger 101')).toBeInTheDocument();
});

it('retries a failed later page without offering actions from the preceding page', async () => {
  let pageTwoReads = 0;
  jest.mocked(api.get).mockImplementation(async (url, config) => {
    if (url !== '/event-triggers') return { data: { items: [] } } as never;
    const page = params(config).page ?? 1;
    if (page === 2 && ++pageTwoReads === 1) throw new Error('offline');
    return envelope(page) as never;
  });
  render(<EventTriggersPage />, { wrapper: createWrapper() });
  await screen.findByText('Trigger 1');
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница: триггеры' }));
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  expect(screen.queryByTitle('Редактировать')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить загрузку триггеров' }));
  await waitFor(() => expect(screen.getByText('Trigger 101')).toBeInTheDocument());
});
