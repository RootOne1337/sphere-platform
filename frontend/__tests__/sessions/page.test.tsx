import { act, fireEvent, render, screen, within } from '@testing-library/react';
import SessionsPage from '@/app/(dashboard)/sessions/page';
import { useAccountSessions, useEndSession, useSessionStats } from '@/lib/hooks/useAccountSessions';

jest.mock('@/lib/hooks/useAccountSessions', () => ({
  useAccountSessions: jest.fn(),
  useEndSession: jest.fn(),
  useSessionStats: jest.fn(),
}));

const session = (id: string, account_login: string, device_name: string) => ({
  id, org_id: 'org-1', account_id: `account-${id}`, account_login, account_game: 'game',
  device_id: `device-${id}`, device_name, started_at: '2026-09-29T10:00:00Z', ended_at: null,
  end_reason: null, error_message: null, script_id: null, task_id: null, pipeline_run_id: null,
  nodes_executed: 0, errors_count: 0, level_before: null, level_after: null,
  balance_before: null, balance_after: null, duration_seconds: 60, meta: {},
  created_at: '2026-09-29T10:00:00Z', updated_at: '2026-09-29T10:00:00Z',
});
const firstSession = session('session-1', 'pilot-account', 'LD-Remote-01');
const secondSession = session('session-2', 'backup-account', 'Pixel-02');
const refetch = jest.fn();
const mutate = jest.fn();

function renderPage() {
  return render(<SessionsPage />);
}

beforeEach(() => {
  jest.mocked(useAccountSessions).mockReturnValue({
    data: { items: [firstSession, secondSession], total: 2, page: 1, per_page: 50, pages: 1 },
    isLoading: false, isFetching: false, isError: false, refetch,
  } as unknown as ReturnType<typeof useAccountSessions>);
  jest.mocked(useSessionStats).mockReturnValue({
    data: { total_sessions: 2, active_sessions: 2, avg_duration_seconds: 60, by_end_reason: {}, total_nodes_executed: 0, total_errors: 0 },
    isError: false,
  } as unknown as ReturnType<typeof useSessionStats>);
  jest.mocked(useEndSession).mockReturnValue({ mutate, isPending: false } as unknown as ReturnType<typeof useEndSession>);
});

afterEach(() => jest.clearAllMocks());

describe('Account sessions page', () => {
  it('filters the loaded page by account/device fields and labels the scope honestly', () => {
    renderPage();
    fireEvent.change(screen.getByRole('textbox', { name: 'Поиск сессий на текущей странице' }), { target: { value: 'LD-Remote' } });

    expect(screen.getByText('pilot-account')).toBeInTheDocument();
    expect(screen.queryByText('backup-account')).not.toBeInTheDocument();
    expect(screen.getByText(/поиск ограничен загруженной страницей/i)).toBeInTheDocument();
  });

  it('returns to the first API page when local search changes', () => {
    jest.mocked(useAccountSessions).mockReturnValue({
      data: { items: [firstSession, secondSession], total: 102, page: 1, per_page: 50, pages: 3 },
      isLoading: false, isFetching: false, isError: false, refetch,
    } as unknown as ReturnType<typeof useAccountSessions>);
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }));
    expect(screen.getByText(/стр\. 2 из 3/)).toBeInTheDocument();

    fireEvent.change(screen.getByRole('textbox', { name: 'Поиск сессий на текущей странице' }), { target: { value: 'LD-Remote' } });
    expect(screen.getByText(/стр\. 1 из 3/)).toBeInTheDocument();
  });

  it('does not end an active session until the operator confirms', async () => {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Завершить сессию pilot-account' }));
    const dialog = await screen.findByRole('dialog', { name: 'Завершить активную сессию?' });
    expect(mutate).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Отмена' }));
    expect(mutate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Завершить сессию pilot-account' }));
    const confirmDialog = await screen.findByRole('dialog', { name: 'Завершить активную сессию?' });
    fireEvent.click(within(confirmDialog).getByRole('button', { name: 'Завершить сессию' }));
    expect(mutate).toHaveBeenCalledWith(
      { id: 'session-1', end_reason: 'manual' },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) }),
    );
    await act(async () => { mutate.mock.calls[0][1].onSuccess(); });
    expect(screen.queryByRole('dialog', { name: 'Завершить активную сессию?' })).not.toBeInTheDocument();
  });

  it('shows an API failure rather than reporting no sessions', async () => {
    jest.mocked(useAccountSessions).mockReturnValue({
      data: undefined, isLoading: false, isFetching: false, isError: true, refetch,
    } as unknown as ReturnType<typeof useAccountSessions>);
    renderPage();

    expect(await screen.findByText('Не удалось загрузить сессии')).toBeInTheDocument();
    expect(screen.queryByText('Нет сессий')).not.toBeInTheDocument();
  });
});
