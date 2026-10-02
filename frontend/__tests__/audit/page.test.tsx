import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import AuditLogsPage from '@/app/(dashboard)/audit/page';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));

const record = (overrides: Record<string, unknown> = {}) => ({
  id: 'event-001',
  created_at: '2026-09-29T08:30:00Z',
  user_id: 'user-uuid-001',
  action: 'POST /devices/one/reboot',
  resource_type: 'device',
  resource_id: 'device-001',
  ip_address: '203.0.113.10',
  meta: { status: 'failure', http_status: 503, duration_ms: 42 },
  ...overrides,
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><AuditLogsPage /></QueryClientProvider>);
}

beforeEach(() => {
  jest.mocked(api.get).mockResolvedValue({ data: { items: [record()], total: 1, page: 1, per_page: 100, pages: 1 } });
});

afterEach(() => jest.clearAllMocks());

describe('Audit page', () => {
  it('uses the backend pagination contract and maps failure from meta.status', async () => {
    renderPage();

    expect(await screen.findByText('POST /devices/one/reboot')).toBeInTheDocument();
    expect(screen.getByText('Ошибка')).toBeInTheDocument();
    expect(screen.getAllByText('1', { selector: 'p' })).toHaveLength(2);
    expect(api.get).toHaveBeenCalledWith('/audit/logs', {
      params: { page: 1, per_page: 100 },
      signal: expect.any(AbortSignal),
    });
  });

  it('opens an inspector containing actual response metadata without fake replay controls', async () => {
    renderPage();
    fireEvent.click(await screen.findByText('POST /devices/one/reboot'));

    const dialog = await screen.findByRole('dialog', { name: 'POST /devices/one/reboot' });
    expect(within(dialog).getByText('203.0.113.10')).toBeInTheDocument();
    expect(within(dialog).getByText('503')).toBeInTheDocument();
    expect(within(dialog).getByText('42')).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: /повтор/i })).not.toBeInTheDocument();
    expect(within(dialog).getByText(/поля, которые фактически вернул endpoint/i)).toBeInTheDocument();
  });

  it('shows backend failure instead of presenting it as an empty healthy journal', async () => {
    jest.mocked(api.get).mockRejectedValue(new Error('permission denied'));
    renderPage();

    expect(await screen.findByText('Не удалось загрузить журнал аудита')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('audit:read');
    expect(screen.queryByText('В журнале пока нет событий')).not.toBeInTheDocument();
    expect(screen.getAllByText('—', { selector: 'p' })).toHaveLength(5);
  });

  it('distinguishes an actual empty response from an API error', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { items: [], total: 0, page: 1, pages: 0 } });
    renderPage();

    expect(await screen.findByText('В журнале пока нет событий')).toBeInTheDocument();
    expect(screen.queryByText('Не удалось загрузить журнал аудита')).not.toBeInTheDocument();
  });

  it('keeps an absent backend status unknown instead of raising a false warning', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { items: [record({ meta: {} })], total: 1, page: 1, pages: 1 } });
    renderPage();

    const row = await screen.findByRole('row', { name: /Открыть событие/ });
    expect(within(row).getByText('Не указано')).toBeInTheDocument();
    expect(within(row).queryByText('Успешно')).not.toBeInTheDocument();
    expect(within(row).queryByText('Предупреждение')).not.toBeInTheDocument();
    expect(screen.getByText('Без результата')).toBeInTheDocument();
  });

  it('loads another API page and keeps pagination controls aligned with the server response', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { items: [record()], total: 101, page: 1, pages: 2 } });
    renderPage();
    await screen.findByText('POST /devices/one/reboot');

    fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/audit/logs', {
      params: { page: 2, per_page: 100 },
      signal: expect.any(AbortSignal),
    }));
  });

  it('applies global query DSL and renders the server-filtered result', async () => {
    renderPage();
    await screen.findByText('POST /devices/one/reboot');
    fireEvent.change(screen.getByRole('searchbox', { name: 'Поиск по журналу аудита' }), { target: { value: 'status:FAILED' } });
    fireEvent.click(screen.getByRole('button', { name: 'Применить фильтры' }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/audit/logs', expect.objectContaining({ params: { q: 'status:FAILED', page: 1, per_page: 100 } })));
    expect(await screen.findByText('POST /devices/one/reboot')).toBeInTheDocument();
    jest.mocked(api.get).mockResolvedValue({ data: { items: [], total: 0, page: 1, pages: 0 } });
    fireEvent.change(screen.getByRole('searchbox', { name: 'Поиск по журналу аудита' }), { target: { value: 'status:SUCCESS' } });
    fireEvent.click(screen.getByRole('button', { name: 'Применить фильтры' }));
    await screen.findByText('По этим условиям событий нет');
    expect(screen.queryByText('POST /devices/one/reboot')).not.toBeInTheDocument();
    expect(screen.getByText('По этим условиям событий нет')).toBeInTheDocument();
  });
});
