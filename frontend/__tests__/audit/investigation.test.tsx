import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import AuditPage from '@/app/(dashboard)/audit/page';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const actor = { id: 'actor', org_id: 'org-a', role: 'org_owner', email: 'owner@example.org' };
const row = { id: 'old-event', created_at: '2026-10-01T10:00:00Z', user_id: null,
  action: 'rare.action', resource_type: 'groups', meta: { status: 'failure' } };
const envelope = { items: [row], total: 1, page: 1, per_page: 100, pages: 1 };
const receipt = () => ({ data: new Blob(['csv'], { type: 'text/csv' }), headers: {
  'content-type': 'text/csv; charset=utf-8', 'x-audit-rows': '1', 'x-audit-limit': '5000',
  'x-audit-truncated': 'false', 'x-audit-observed-at': '2026-10-02T10:00:00Z',
} });
const clickDownload = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
beforeEach(() => {
  jest.clearAllMocks();
  useAuthStore.setState({ user: actor, sessionVersion: 1 });
  URL.createObjectURL = jest.fn(() => 'blob:audit'); URL.revokeObjectURL = jest.fn();
  jest.mocked(api.get).mockImplementation(async (path) => path === '/audit/logs/export' ? receipt() as never : { data: envelope } as never);
});
afterEach(() => useAuthStore.setState({ user: null, sessionVersion: 0 }));
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { client, ...render(<QueryClientProvider client={client}><AuditPage /></QueryClientProvider>) };
}
async function openFilters() {
  await screen.findByText(row.action);
  fireEvent.click(screen.getByRole('button', { name: 'Фильтры' }));
}
function apply() { fireEvent.click(screen.getByRole('button', { name: 'Применить фильтры' })); }

it('applies server-wide DSL only on submit and finds older-page events', async () => {
  mount(); await screen.findByText(row.action);
  const search = screen.getByRole('searchbox', { name: 'Поиск по журналу аудита' });
  fireEvent.change(search, { target: { value: 'status:FAILED user:system' } });
  expect(api.get).toHaveBeenCalledTimes(1);
  apply();
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/audit/logs', {
    params: { q: 'status:FAILED user:system', page: 1, per_page: 100 }, signal: expect.any(AbortSignal),
  }));
  expect(await screen.findByText(row.action)).toBeInTheDocument();
});
it('validates time range and actor before sending then preserves UTC precision', async () => {
  mount(); await openFilters();
  fireEvent.change(screen.getByLabelText('UUID пользователя'), { target: { value: 'not-a-uuid' } }); apply();
  expect(api.get).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('alert')).toHaveTextContent('UUID');
  fireEvent.change(screen.getByLabelText('UUID пользователя'), { target: { value: '' } });
  fireEvent.change(screen.getByLabelText('С (UTC)'), { target: { value: '2026-10-02T10:00' } });
  fireEvent.change(screen.getByLabelText('По (UTC)'), { target: { value: '2026-10-01T10:00' } }); apply();
  expect(api.get).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByLabelText('По (UTC)'), { target: { value: '2026-10-02T10:00:15' } }); apply();
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/audit/logs', {
    params: { from: '2026-10-02T10:00:00.000Z', to: '2026-10-02T10:00:15.000Z', page: 1, per_page: 100 }, signal: expect.any(AbortSignal),
  }));
});
it('resets page to one on filter application and keeps paging filters', async () => {
  jest.mocked(api.get).mockResolvedValue({ data: { ...envelope, total: 101, pages: 2 } } as never);
  mount(); await screen.findByText(row.action);
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }));
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/audit/logs', expect.objectContaining({ params: { page: 2, per_page: 100 } })));
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'rare' } }); apply();
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/audit/logs', expect.objectContaining({ params: { q: 'rare', page: 1, per_page: 100 } })));
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }));
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/audit/logs', expect.objectContaining({ params: { q: 'rare', page: 2, per_page: 100 } })));
});
it('exports applied global filters with a declared cap, never current-page rows or draft', async () => {
  mount(); await screen.findByText(row.action);
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'rare' } }); apply();
  await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'unapplied-draft' } });
  await waitFor(() => expect(screen.getByRole('button', { name: /^Экспорт CSV/ })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: /^Экспорт CSV/ }));
  await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/audit/logs/export', {
    params: { q: 'rare', limit: 5000 }, responseType: 'blob', signal: expect.any(AbortSignal),
  }));
  await waitFor(() => expect(clickDownload).toHaveBeenCalledTimes(1));
  expect(screen.getByRole('status')).toHaveTextContent('1');
});
it('shows truncation explicitly and tells how to retrieve the remaining range', async () => {
  jest.mocked(api.get).mockImplementation(async path => path === '/audit/logs/export'
    ? { ...receipt(), headers: { ...receipt().headers, 'x-audit-rows': '5000', 'x-audit-truncated': 'true' } } as never : { data: envelope } as never);
  mount(); await screen.findByText(row.action);
  fireEvent.click(screen.getByRole('button', { name: /^Экспорт CSV/ }));
  expect(await screen.findByText(/Остальные события не включены/)).toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent(/Сузьте диапазон времени/);
});
it('blocks stale cached export after a failed read', async () => {
  mount(); await screen.findByText(row.action);
  jest.mocked(api.get).mockRejectedValue({ response: { status: 403 } });
  fireEvent.click(screen.getByRole('button', { name: 'Обновить' }));
  await screen.findByText('Не удалось загрузить журнал аудита');
  expect(screen.getByRole('button', { name: /^Экспорт CSV/ })).toBeDisabled();
});
it.each(['missing', 'bad-count', 'html'])('does not download an unverifiable export (%s)', async fault => {
  const bad = receipt();
  if (fault === 'missing') delete (bad.headers as Partial<typeof bad.headers>)['x-audit-truncated'];
  if (fault === 'bad-count') bad.headers['x-audit-rows'] = '6000';
  if (fault === 'html') bad.headers['content-type'] = 'text/html';
  jest.mocked(api.get).mockImplementation(async path => path === '/audit/logs/export' ? bad as never : { data: envelope } as never);
  mount(); await screen.findByText(row.action);
  fireEvent.click(screen.getByRole('button', { name: /^Экспорт CSV/ }));
  expect(await screen.findByRole('alert')).toHaveTextContent(/экспорт/i);
  expect(clickDownload).not.toHaveBeenCalled();
});
it('cancels one in-flight export and ignores a late fulfilled response', async () => {
  let resolve!: (value: unknown) => void; let signal!: AbortSignal;
  jest.mocked(api.get).mockImplementation((path, config) => path === '/audit/logs/export'
    ? (signal = config!.signal as AbortSignal, new Promise(r => { resolve = r; })) as never : Promise.resolve({ data: envelope }) as never);
  mount(); await screen.findByText(row.action);
  fireEvent.click(screen.getByRole('button', { name: /^Экспорт CSV/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Отменить экспорт' }));
  expect(api.get).toHaveBeenCalledWith('/audit/logs/export', expect.anything());
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(receipt()));
  expect(clickDownload).not.toHaveBeenCalled();
});
it('aborts export and drops drawer/draft when actor or tenant changes', async () => {
  let resolve!: (value: unknown) => void; let signal!: AbortSignal;
  jest.mocked(api.get).mockImplementation((path, config) => path === '/audit/logs/export'
    ? (signal = config!.signal as AbortSignal, new Promise(r => { resolve = r; })) as never : Promise.resolve({ data: envelope }) as never);
  mount(); await screen.findByText(row.action);
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'private-draft' } });
  fireEvent.click(screen.getByRole('button', { name: /^Экспорт CSV/ }));
  act(() => useAuthStore.setState({ user: { ...actor, org_id: 'org-b' }, sessionVersion: 2 }));
  expect(api.get).toHaveBeenCalledWith('/audit/logs/export', expect.anything());
  expect(signal.aborted).toBe(true);
  expect(screen.getByRole('searchbox')).toHaveValue('');
  await act(async () => resolve(receipt()));
  expect(clickDownload).not.toHaveBeenCalled();
});
