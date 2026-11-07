import { act, fireEvent, render, screen } from '@testing-library/react';
import EventsPage from '@/app/(dashboard)/events/page';
import { useDeviceEvents, useEventStats, useMarkEventProcessed } from '@/lib/hooks/useDeviceEvents';

jest.mock('@/lib/hooks/useDeviceEvents', () => ({
  useDeviceEvents: jest.fn(),
  useEventStats: jest.fn(),
  useMarkEventProcessed: jest.fn(),
}));

const event = {
  id: 'event-1', org_id: 'org-1', device_id: 'device-1', device_name: 'Phone 1',
  event_type: 'device.reconnected', severity: 'info' as const, message: 'Connected',
  account_id: null, account_login: null, task_id: null, pipeline_run_id: null,
  data: {}, occurred_at: '2026-09-29T10:00:00Z', processed: false,
  created_at: '2026-09-29T10:00:00Z', updated_at: '2026-09-29T10:00:00Z',
};
const refetch = jest.fn();
const mutate = jest.fn();

function renderPage() {
  return render(<EventsPage />);
}

beforeEach(() => {
  jest.mocked(useDeviceEvents).mockReturnValue({
    data: { items: [event], total: 1, page: 1, per_page: 50, pages: 1 },
    isLoading: false, isFetching: false, isError: false, refetch,
  } as unknown as ReturnType<typeof useDeviceEvents>);
  jest.mocked(useEventStats).mockReturnValue({
    data: { total: 1, by_severity: { info: 1 }, by_type: {}, unprocessed: 1 },
    isError: false,
  } as unknown as ReturnType<typeof useEventStats>);
  jest.mocked(useMarkEventProcessed).mockReturnValue({ mutate, isPending: false } as unknown as ReturnType<typeof useMarkEventProcessed>);
});

afterEach(() => {
  jest.clearAllMocks();
  jest.useRealTimers();
});

describe('Device events page', () => {
  it('uses a cancellable debounce and sends the search to the API hook', async () => {
    jest.useFakeTimers();
    renderPage();
    fireEvent.change(screen.getByRole('textbox', { name: 'Поиск событий' }), { target: { value: 'reconnected' } });

    await act(async () => { jest.advanceTimersByTime(300); });

    expect(jest.mocked(useDeviceEvents).mock.calls.some(([params]) => params.search === 'reconnected')).toBe(true);
  });

  it('keeps the event inspector open until the processed mutation succeeds', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Открыть событие device.reconnected' }));
    const dialog = await screen.findByRole('dialog', { name: 'Событие: device.reconnected' });
    fireEvent.click(screen.getByRole('button', { name: 'Отметить обработанным' }));

    expect(mutate).toHaveBeenCalledWith('event-1', expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) }));
    expect(dialog).toBeInTheDocument();

    await act(async () => { mutate.mock.calls[0][1].onSuccess(); });
    expect(screen.queryByRole('dialog', { name: 'Событие: device.reconnected' })).not.toBeInTheDocument();
  });

  it('shows an API failure instead of an empty-event message', async () => {
    jest.mocked(useDeviceEvents).mockReturnValue({
      data: undefined, isLoading: false, isFetching: false, isError: true, refetch,
    } as unknown as ReturnType<typeof useDeviceEvents>);
    renderPage();

    expect(await screen.findByText('Не удалось загрузить события')).toBeInTheDocument();
    expect(screen.queryByText('Нет событий')).not.toBeInTheDocument();
  });
});
