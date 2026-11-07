import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import ScriptsPage from '@/app/(dashboard)/scripts/page';
import { api } from '@/lib/api';
import { createWrapper } from '../helpers';
import { useAuthStore } from '@/lib/store';
import { catalogActor, catalogOrg, catalogEnvelope } from './catalog-fixtures';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/components/sphere/RunScriptModal', () => ({ RunScriptModal: () => null }));

const scripts = Array.from({ length: 51 }, (_, index) => ({
  id: `11111111-1111-4111-8111-${String(index + 1).padStart(12, '0')}`, org_id: catalogOrg, current_version_id: null, current_version: null, node_count: null, name: `Scenario ${index + 1}`, description: null,
  is_archived: false, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
}));
const envelope = (page: number, items = scripts.slice((page - 1) * 50, page * 50), total = 51) => ({ data: catalogEnvelope(items, total, page) });
const requestParams = (config: { params?: unknown } | undefined) => (config?.params ?? {}) as { query?: string; page?: number };

beforeEach(() => {
  jest.resetAllMocks(); localStorage.clear();
  useAuthStore.setState({ user: catalogActor, sessionVersion: 0 });
});

it('reaches the 51st script through paging and keeps its original editor link', async () => {
  jest.mocked(api.get).mockImplementation(async (_url, config) => envelope(requestParams(config).page ?? 1) as never);
  render(<ScriptsPage />, { wrapper: createWrapper() });
  await screen.findByText('Scenario 1');
  expect(screen.queryByText('Scenario 51')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница: сценарии' }));
  expect(await screen.findByText('Scenario 51')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Открыть' })).toHaveAttribute('href', `/scripts/builder?id=${scripts[50].id}`);
  expect(screen.getByRole('button', { name: 'Следующая страница: сценарии' })).toBeDisabled();
  expect(api.get).toHaveBeenLastCalledWith('/scripts/catalog', { params: { query: undefined, page: 2, per_page: 50 }, signal: expect.any(AbortSignal) });
  fireEvent.click(screen.getByRole('button', { name: 'Предыдущая страница: сценарии' }));
  expect(await screen.findByText('Scenario 1')).toBeInTheDocument();
});

it('searches the full backend catalog and resets page two to page one', async () => {
  jest.mocked(api.get).mockImplementation(async (_url, config) => requestParams(config).query ? envelope(1, [scripts[50]], 1) as never : envelope(requestParams(config).page ?? 1) as never);
  render(<ScriptsPage />, { wrapper: createWrapper() });
  await screen.findByText('Scenario 1');
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница: сценарии' }));
  await screen.findByText('Scenario 51');
  fireEvent.change(screen.getByRole('textbox', { name: 'Поиск сценариев во всём каталоге' }), { target: { value: 'Scenario 51' } });
  expect(screen.queryByRole('button', { name: 'Запустить' })).not.toBeInTheDocument();
  await waitFor(() => expect(api.get).toHaveBeenCalledWith('/scripts/catalog', { params: { query: 'Scenario 51', page: 1, per_page: 50 }, signal: expect.any(AbortSignal) }));
  expect(await screen.findByText('Scenario 51')).toBeInTheDocument();
  expect(screen.getByText('Страница 1 из 1 · всего 1')).toBeInTheDocument();
});

it('shows a failed next page as a read failure rather than keeping actionable previous rows', async () => {
  jest.mocked(api.get).mockResolvedValueOnce(envelope(1) as never).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(envelope(2) as never);
  render(<ScriptsPage />, { wrapper: createWrapper() });
  await screen.findByText('Scenario 1');
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница: сценарии' }));
  expect(await screen.findByText('Не удалось загрузить сценарии')).toBeInTheDocument();
  expect(screen.queryByText('Scenario 1')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Запустить' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
  expect(await screen.findByText('Scenario 51')).toBeInTheDocument();
});

it('cancels a retired page request when server search changes and ignores its late response', async () => {
  let resolvePage!: (value: ReturnType<typeof envelope>) => void;
  const pendingPage = new Promise<ReturnType<typeof envelope>>(resolve => { resolvePage = resolve; });
  jest.mocked(api.get).mockImplementation((_url, config) => {
    if (requestParams(config).query) return Promise.resolve(envelope(1, [scripts[50]], 1)) as never;
    if (requestParams(config).page === 2) return pendingPage as never;
    return Promise.resolve(envelope(1)) as never;
  });
  render(<ScriptsPage />, { wrapper: createWrapper() });
  await screen.findByText('Scenario 1');
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница: сценарии' }));
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  const signal = jest.mocked(api.get).mock.calls[1][1]?.signal;
  fireEvent.change(screen.getByRole('textbox', { name: 'Поиск сценариев во всём каталоге' }), { target: { value: '51' } });
  expect(await screen.findByText('Scenario 51')).toBeInTheDocument();
  expect(signal?.aborted).toBe(true);
  await act(async () => { resolvePage(envelope(2, [{ ...scripts[50], name: 'Retired page' }])); });
  expect(screen.queryByText('Retired page')).not.toBeInTheDocument();
});
