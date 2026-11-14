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
  jest.mocked(api.get).mockResolvedValue({ data: { items: [record()], next_cursor: null } });
});

afterEach(() => jest.clearAllMocks());

describe('Audit page', () => {
  it('uses the backend pagination contract and maps failure from meta.status', async () => {
    renderPage();

    expect(await screen.findByText('POST /devices/one/reboot')).toBeInTheDocument();
    expect(screen.getByText('Ошибка')).toBeInTheDocument();
    expect(screen.getByText('1', { selector: 'p' })).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/audit/logs/cursor', {
      params: { per_page: 100 },
      signal: expect.any(AbortSignal),
    });
  });

  it('opens an inspector containing actual response metadata without fake replay controls', async () => {
    renderPage();
    fireEvent.click(await screen.findByText('POST /devices/one/reboot'));

    const dialog = await screen.findByRole('dialog', { name: 'POST /devices/one/reboot' });
    expect(within(dialog).getByText('Ответ HTTP')).toBeInTheDocument();
    expect(within(dialog).getByText(/отдельно от результата операции/)).toBeInTheDocument();
    expect(within(dialog).getByText('203.0.113.10')).toBeInTheDocument();
    expect(within(dialog).getByText('503')).toBeInTheDocument();
    expect(within(dialog).getByText('42')).toBeInTheDocument();
    expect(within(dialog).queryByRole('button', { name: /повтор/i })).not.toBeInTheDocument();
    expect(within(dialog).getByText(/поля, которые фактически вернул endpoint/i)).toBeInTheDocument();
  });

  it('renders the committed role effect and correlation without showing arbitrary old payloads', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { items: [record({
      action: 'user.role_change', resource_type: 'user',
      old_value: { role: 'viewer', token: 'never-show-this' },
      new_value: { role: 'script_runner' },
      meta: { status: 'success', request_id: 'change-fixture:3' },
    })], next_cursor: null } });
    renderPage();
    fireEvent.click(await screen.findByText('user.role_change'));
    const dialog = await screen.findByRole('dialog', { name: 'user.role_change' });
    expect(within(dialog).getByText('Изменение сохранено')).toBeInTheDocument();
    const diff = within(dialog).getByRole('region', { name: 'Роль пользователя' });
    expect(within(diff).getByText('Наблюдатель')).toBeInTheDocument();
    expect(within(diff).getByText('Запуск сценариев')).toBeInTheDocument();
    expect(within(dialog).queryByText('never-show-this')).not.toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Открыть события этого запроса' })).toHaveAttribute(
      'href', '/audit?request_id=change-fixture%3A3',
    );
  });

  it('shows backend failure instead of presenting it as an empty healthy journal', async () => {
    jest.mocked(api.get).mockRejectedValue(new Error('permission denied'));
    renderPage();

    expect(await screen.findByText('Не удалось загрузить журнал аудита')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('audit:read');
    expect(screen.queryByText('В журнале пока нет событий')).not.toBeInTheDocument();
    expect(screen.getAllByText('—', { selector: 'p' })).toHaveLength(4);
  });

  it('shows Android as the receipt source and keeps an HTTP result distinct', async () => {
    const taskId = 'd494b5f6-39ec-41de-970d-9228a3b51588';
    jest.mocked(api.get).mockResolvedValue({ data: { items: [record(), record({
      id: 'agent-receipt', action: 'task.agent_result', resource_type: 'task', resource_id: taskId,
      user_id: null, ip_address: null, meta: {
        status: 'success', agent_outcome: 'completed', receipt_id: taskId,
        device_id: 'c69ac427-01df-43be-bd95-bfbd24aad28f',
      },
    })], next_cursor: null } });
    renderPage();
    const row = await screen.findByRole('row', { name: 'Открыть событие task.agent_result' });
    expect(within(row).getByText('Android-агент')).toBeInTheDocument();
    expect(within(row).queryByText('system')).not.toBeInTheDocument();
    const http = screen.getByRole('row', { name: 'Открыть событие POST /devices/one/reboot' });
    expect(within(http).getByText('203.0.113.10')).toBeInTheDocument();
  });

  it('distinguishes an actual empty response from an API error', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { items: [], next_cursor: null } });
    renderPage();

    expect(await screen.findByText('В журнале пока нет событий')).toBeInTheDocument();
    expect(screen.queryByText('Не удалось загрузить журнал аудита')).not.toBeInTheDocument();
  });

  it('keeps an absent backend status unknown instead of raising a false warning', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { items: [record({ meta: {} })], next_cursor: null } });
    renderPage();

    const row = await screen.findByRole('row', { name: /Открыть событие/ });
    expect(within(row).getByText('Не указано')).toBeInTheDocument();
    expect(within(row).queryByText('Успешно')).not.toBeInTheDocument();
    expect(within(row).queryByText('Предупреждение')).not.toBeInTheDocument();
    expect(screen.getByText('Без результата')).toBeInTheDocument();
  });

  it('seeks with the returned cursor, stops at the last page, and returns to newer entries', async () => {
    jest.mocked(api.get).mockResolvedValueOnce({ data: { items: [record()], next_cursor: 'page-two' } });
    jest.mocked(api.get).mockResolvedValueOnce({ data: { items: [record({ action: 'old record' })], next_cursor: null } });
    renderPage();
    await screen.findByText('POST /devices/one/reboot');

    fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/audit/logs/cursor', {
      params: { cursor: 'page-two', per_page: 100 },
      signal: expect.any(AbortSignal),
    }));
    expect(await screen.findByText('old record')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Следующая страница' })).toBeDisabled();
    expect(screen.queryByText(/Автообновление каждые/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'К новым записям' }));
    expect(await screen.findByText('POST /devices/one/reboot')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Предыдущая страница' })).toBeDisabled();
  });

  it('does not silently accept a malformed cursor response as an empty page', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { items: [], next_cursor: 5 } });
    renderPage();
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось загрузить журнал аудита');
    expect(screen.queryByText('В журнале пока нет событий')).not.toBeInTheDocument();
  });

  it('applies global query DSL and renders the server-filtered result', async () => {
    renderPage();
    await screen.findByText('POST /devices/one/reboot');
    fireEvent.change(screen.getByRole('searchbox', { name: 'Поиск по журналу аудита' }), { target: { value: 'status:FAILED' } });
    fireEvent.click(screen.getByRole('button', { name: 'Применить фильтры' }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/audit/logs/cursor', expect.objectContaining({ params: { q: 'status:FAILED', per_page: 100 } })));
    expect(await screen.findByText('POST /devices/one/reboot')).toBeInTheDocument();
    jest.mocked(api.get).mockResolvedValue({ data: { items: [], next_cursor: null } });
    fireEvent.change(screen.getByRole('searchbox', { name: 'Поиск по журналу аудита' }), { target: { value: 'status:SUCCESS' } });
    fireEvent.click(screen.getByRole('button', { name: 'Применить фильтры' }));
    await screen.findByText('По этим условиям событий нет');
    expect(screen.queryByText('POST /devices/one/reboot')).not.toBeInTheDocument();
    expect(screen.getByText('По этим условиям событий нет')).toBeInTheDocument();
  });
});
