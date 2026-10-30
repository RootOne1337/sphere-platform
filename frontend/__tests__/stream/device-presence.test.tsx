import { act, fireEvent, render, screen } from '@testing-library/react';
import FleetStreamPage from '@/app/(dashboard)/stream/page';
import type { Device } from '@/lib/hooks/useDevices';

let mockDevices: Device[];
let mockIsLoading = false;
let mockIsError = false;
let mockIsFetching = false;
let mockDataAvailable = true;
let mockPresenceAvailable = true;
let mockCatalogTotal: number | null = null;
let mockDataUpdatedAt = 0;
let mockQueryParams: Record<string, unknown> = {};
let mockGroups: Array<{ id: string; name: string }> = [];
let mockLocations: Array<{ id: string; name: string }> = [];
const mockRefetch = jest.fn();
jest.mock('@/lib/hooks/useDevices', () => ({
  useDevices: (params: Record<string, unknown>) => {
    mockQueryParams = params;
    const scoped = mockDevices.filter((device) => {
      const search = String(params.search ?? '').toLocaleLowerCase();
      const matchesSearch = !search || [device.name, device.android_id, device.model]
        .some(value => value?.toLocaleLowerCase().includes(search));
      const matchesGroup = !params.group_id || device.group_id === params.group_id || device.group_ids?.includes(String(params.group_id));
      const matchesLocation = !params.location_id || device.location_ids?.includes(String(params.location_id));
      return matchesSearch && matchesGroup && matchesLocation;
    });
    const counts = {
      online: scoped.filter(device => device.status === 'online' || device.status === 'busy').length,
      busy: scoped.filter(device => device.status === 'busy').length,
      connecting: scoped.filter(device => device.status === 'connecting').length,
      offline: scoped.filter(device => device.status === 'offline').length,
      issues: scoped.filter(device => device.status === 'error' || device.status === 'maintenance' || device.status === 'unknown').length,
    };
    const filtered = scoped.filter(device => {
      if (!params.live_status) return true;
      if (params.live_status === 'online') return device.status === 'online' || device.status === 'busy';
      if (params.live_status === 'attention') return device.status === 'error' || device.status === 'maintenance' || device.status === 'unknown';
      return device.status === params.live_status;
    });
    const pageSize = Number(params.page_size ?? 50);
    const page = Number(params.page ?? 1);
    const total = mockCatalogTotal ?? filtered.length;
    const items = filtered.slice((page - 1) * pageSize, page * pageSize);
    return {
      data: mockDataAvailable ? {
        items,
        total,
        page,
        page_size: pageSize,
        pages: Math.ceil(total / pageSize),
        scope_total: scoped.length,
        status_counts: mockPresenceAvailable ? counts : undefined,
        presence_available: mockPresenceAvailable,
      } : undefined,
      dataUpdatedAt: mockDataUpdatedAt,
      isLoading: mockIsLoading,
      isError: mockIsError,
      isFetching: mockIsFetching,
      refetch: mockRefetch,
    };
  },
}));
jest.mock('@/lib/hooks/useGroups', () => ({ useGroups: () => ({ data: mockGroups }) }));
jest.mock('@/lib/hooks/useLocations', () => ({ useLocations: () => ({ data: mockLocations }) }));
jest.mock('@/components/sphere/DeviceStream', () => ({
  DeviceStream: ({ deviceId }: { deviceId: string }) => <div>Live {deviceId}</div>,
}));

beforeEach(() => {
  mockIsLoading = false;
  mockIsError = false;
  mockIsFetching = false;
  mockDataAvailable = true;
  mockPresenceAvailable = true;
  mockCatalogTotal = null;
  mockQueryParams = {};
  mockGroups = [];
  mockLocations = [];
  mockDataUpdatedAt = Date.parse('2026-09-29T12:00:00.000Z');
  mockRefetch.mockReset();
  mockDevices = [
    { id: 'a', name: 'Agent A', status: 'online', group_ids: [], location_ids: [] },
    { id: 'b', name: 'Agent B', status: 'online', group_ids: [], location_ids: [] },
  ] as unknown as Device[];
});

afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});

it('displays and sorts page-local stream cards by the canonical model instead of legacy metadata', () => {
  mockDevices = [
    { ...mockDevices[0], device_model: 'Zulu canonical', model: 'Alpha legacy' },
    { ...mockDevices[1], device_model: 'Alpha canonical', model: 'Zulu legacy' },
  ];
  render(<FleetStreamPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Модель' }));
  expect(screen.getAllByRole('button', { name: /Начать просмотр/ }).map(button => button.getAttribute('aria-label')))
    .toEqual(['Начать просмотр Agent B', 'Начать просмотр Agent A']);
  expect(screen.getAllByText('Alpha canonical')).toHaveLength(2);
  expect(screen.getAllByText('Zulu canonical')).toHaveLength(2);
  expect(screen.queryByText('Alpha legacy')).not.toBeInTheDocument();
  expect(screen.queryByText('Zulu legacy')).not.toBeInTheDocument();
  expect(screen.queryByText('Live a')).not.toBeInTheDocument();
});

it('shows heartbeat age and separates fresh telemetry from missing or stale heartbeat', () => {
  const now = Date.parse('2026-09-29T12:00:00.000Z');
  jest.spyOn(Date, 'now').mockReturnValue(now);
  mockDevices = [
    { id: 'fresh', name: 'Fresh device', status: 'online', last_heartbeat: new Date(now - 30_000).toISOString(), group_ids: [], location_ids: [] },
    { id: 'stale', name: 'Stale device', status: 'online', last_heartbeat: new Date(now - 90_000).toISOString(), group_ids: [], location_ids: [] },
    { id: 'missing', name: 'Missing heartbeat', status: 'online', last_heartbeat: null, group_ids: [], location_ids: [] },
    { id: 'invalid', name: 'Invalid heartbeat', status: 'online', last_heartbeat: 'not-a-date', group_ids: [], location_ids: [] },
  ] as unknown as Device[];

  render(<FleetStreamPage />);

  expect(screen.getByLabelText('Последний heartbeat: Heartbeat · 30 с назад')).toHaveClass('text-emerald-400');
  expect(screen.getByLabelText('Последний heartbeat: Heartbeat · 1 мин назад')).toHaveClass('text-amber-400');
  expect(screen.getByLabelText('Последний heartbeat: Heartbeat нет')).toBeInTheDocument();
  expect(screen.getByLabelText('Последний heartbeat: Время heartbeat неизвестно')).toBeInTheDocument();
});

it('shows the timestamp of the last successful catalog API response', () => {
  const updatedAt = Date.parse('2026-09-29T12:00:00.000Z');
  mockDataUpdatedAt = updatedAt;
  render(<FleetStreamPage />);

  const apiTimestamp = screen.getByLabelText('Время последнего успешного ответа каталога API');
  expect(apiTimestamp).toHaveAttribute('title', new Date(updatedAt).toLocaleString());
  expect(apiTimestamp.querySelector('time')).toHaveAttribute('datetime', new Date(updatedAt).toISOString());
});

it('explains that the first API response is still pending when no catalog timestamp exists', () => {
  mockDataUpdatedAt = 0;
  render(<FleetStreamPage />);

  expect(screen.getByRole('status')).toHaveTextContent('Ожидаем первый ответ API');
});

it('keeps an offline device visible, hides stale video, and resumes the selected stream on recovery', () => {
  const view = render(<FleetStreamPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Начать просмотр Agent A' }));
  expect(screen.getByText('Live a')).toBeInTheDocument();
  mockDevices = mockDevices.map(d => d.id === 'a' ? { ...d, status: 'offline' } : d);
  view.rerender(<FleetStreamPage />);
  expect(screen.getByText('Agent A')).toBeInTheDocument();
  expect(screen.getByText('Agent B')).toBeInTheDocument();
  expect(screen.queryByText('Live a')).not.toBeInTheDocument();
  expect(screen.getByText(/приостановлен до восстановления связи/)).toBeInTheDocument();
  mockDevices = mockDevices.map(d => ({ ...d, status: 'online' }));
  view.rerender(<FleetStreamPage />);
  expect(screen.getByText('Live a')).toBeInTheDocument();
  expect(screen.queryByText(/Связь потеряна/)).not.toBeInTheDocument();
});

it('shows devices already offline at page load without offering an unavailable start', () => {
  mockDevices = [{ ...mockDevices[0], status: 'offline' }];
  render(<FleetStreamPage />);
  expect(screen.getByText('Agent A')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Доступны 0' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Начать просмотр Agent A' })).toBeDisabled();
});

it('honors Stop while offline instead of resuming a cancelled viewer', () => {
  const view = render(<FleetStreamPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Начать просмотр Agent A' }));
  mockDevices = mockDevices.map(d => d.id === 'a' ? { ...d, status: 'offline' } : d);
  view.rerender(<FleetStreamPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Остановить просмотр Agent A' }));
  mockDevices = mockDevices.map(d => ({ ...d, status: 'online' }));
  view.rerender(<FleetStreamPage />);
  expect(screen.queryByText('Live a')).not.toBeInTheDocument();
});

it('allows viewing a busy device because busy means reachable while it runs a task', () => {
  mockDevices = [{ ...mockDevices[0], status: 'busy' }];
  render(<FleetStreamPage />);

  fireEvent.click(screen.getByRole('button', { name: 'Начать просмотр Agent A' }));

  expect(screen.getByText('Live a')).toBeInTheDocument();
  expect(screen.getAllByText('В работе')).toHaveLength(2);
});

it('filters the stream catalog by API reachability status and shows matching counts', () => {
  mockDevices = [
    { id: 'a', name: 'Online agent', status: 'online', group_ids: [], location_ids: [] },
    { id: 'b', name: 'Busy agent', status: 'busy', group_ids: [], location_ids: [] },
    { id: 'c', name: 'Connecting agent', status: 'connecting', group_ids: [], location_ids: [] },
    { id: 'd', name: 'Offline agent', status: 'offline', group_ids: [], location_ids: [] },
    { id: 'e', name: 'Error agent', status: 'error', group_ids: [], location_ids: [] },
  ] as unknown as Device[];
  render(<FleetStreamPage />);

  expect(screen.getByRole('button', { name: 'Доступны 2' })).toHaveAttribute('aria-pressed', 'false');
  fireEvent.click(screen.getByRole('button', { name: 'Доступны 2' }));
  expect(screen.getByText('Online agent')).toBeInTheDocument();
  expect(screen.getByText('Busy agent')).toBeInTheDocument();
  expect(screen.queryByText('Connecting agent')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Подключаются 1' }));
  expect(screen.getByText('Connecting agent')).toBeInTheDocument();
  expect(screen.queryByText('Online agent')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Офлайн 1' }));
  expect(screen.getByText('Offline agent')).toBeInTheDocument();
  expect(screen.queryByText('Error agent')).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Проблемы 1' }));
  expect(screen.getByText('Error agent')).toBeInTheDocument();
  expect(screen.queryByText('Offline agent')).not.toBeInTheDocument();
});

it('keeps stream selection across a status filter and resumes it when the device is shown again', () => {
  mockDevices = [
    { id: 'a', name: 'Agent A', status: 'online', group_ids: [], location_ids: [] },
    { id: 'b', name: 'Agent B', status: 'error', group_ids: [], location_ids: [] },
  ] as unknown as Device[];
  render(<FleetStreamPage />);

  fireEvent.click(screen.getByRole('button', { name: 'Начать просмотр Agent A' }));
  expect(screen.getByText('Live a')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Проблемы 1' }));
  expect(screen.queryByText('Live a')).not.toBeInTheDocument();
  expect(screen.getByText('Agent B')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'Все 2' }));
  expect(screen.getByText('Live a')).toBeInTheDocument();
});

it('uses the selected capacity as the page size so 64-device mode can reach every row', () => {
  mockDevices = Array.from({ length: 65 }, (_, index) => ({
    id: `device-${String(index + 1).padStart(2, '0')}`,
    name: `Agent ${String(index + 1).padStart(2, '0')}`,
    status: 'online',
    group_ids: [],
    location_ids: [],
  })) as unknown as Device[];
  render(<FleetStreamPage />);

  fireEvent.click(screen.getByRole('button', { name: 'Показывать до 64 устройств' }));
  expect(screen.getByText('Показано 64 из 65 устройств · страница 1 из 2')).toBeInTheDocument();
  expect(screen.getByText('Agent 64')).toBeInTheDocument();
  expect(screen.queryByText('Agent 65')).not.toBeInTheDocument();
  expect(mockQueryParams).toEqual(expect.objectContaining({ page: 1, page_size: 64 }));

  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }));
  expect(screen.getByText('Agent 65')).toBeInTheDocument();
  expect(screen.getByText('Показано 1 из 65 устройств · страница 2 из 2')).toBeInTheDocument();
  expect(mockQueryParams).toEqual(expect.objectContaining({ page: 2, page_size: 64 }));
});

it('shows loading and retryable API error states instead of a false empty result', () => {
  mockIsLoading = true;
  mockDataAvailable = false;
  const view = render(<FleetStreamPage />);
  expect(screen.getByRole('status', { name: '' })).toHaveTextContent('Загружаем список устройств');

  mockIsLoading = false;
  mockIsError = true;
  mockDataUpdatedAt = 0;
  view.rerender(<FleetStreamPage />);
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось обновить список устройств');
  expect(screen.getByRole('status')).toHaveTextContent('Нет успешного ответа API');
  expect(screen.getByText('Список устройств недоступен')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
  expect(mockRefetch).toHaveBeenCalledTimes(1);
});

it('uses the server-reported filtered total instead of deriving totals from the current page', () => {
  mockCatalogTotal = 3;
  render(<FleetStreamPage />);

  expect(screen.getByText('Показано 2 из 3 устройств · страница 1 из 1')).toBeInTheDocument();
});

it('sends live status to the API instead of filtering only the loaded page', () => {
  mockDevices = [
    { id: 'a', name: 'Online agent', status: 'online', group_ids: [], location_ids: [] },
    { id: 'b', name: 'Busy agent', status: 'busy', group_ids: [], location_ids: [] },
    { id: 'c', name: 'Connecting agent', status: 'connecting', group_ids: [], location_ids: [] },
  ] as unknown as Device[];
  render(<FleetStreamPage />);

  fireEvent.click(screen.getByRole('button', { name: 'Подключаются 1' }));

  expect(mockQueryParams).toEqual(expect.objectContaining({ page: 1, page_size: 4, live_status: 'connecting' }));
  expect(screen.getByText('Connecting agent')).toBeInTheDocument();
  expect(screen.queryByText('Online agent')).not.toBeInTheDocument();
});

it('debounces search and sends search, group and location filters to the API', () => {
  jest.useFakeTimers();
  mockGroups = [{ id: 'g1', name: 'Remote group' }, { id: 'g2', name: 'Local group' }];
  mockLocations = [{ id: 'l1', name: 'Remote location' }, { id: 'l2', name: 'Local location' }];
  mockDevices = [
    { id: 'a', name: 'Remote Pixel', model: 'Pixel 7', status: 'online', group_id: 'g1', group_ids: ['g1'], location_ids: ['l1'] },
    { id: 'b', name: 'Local Pixel', model: 'Pixel 8', status: 'online', group_id: 'g2', group_ids: ['g2'], location_ids: ['l2'] },
  ] as unknown as Device[];
  render(<FleetStreamPage />);

  fireEvent.change(screen.getByRole('searchbox', { name: 'Поиск устройств' }), { target: { value: 'Remote' } });
  expect(mockQueryParams.search).toBeUndefined();
  act(() => jest.advanceTimersByTime(300));
  expect(mockQueryParams.search).toBe('Remote');

  fireEvent.change(screen.getByLabelText('Фильтр по группе'), { target: { value: 'g1' } });
  fireEvent.change(screen.getByLabelText('Фильтр по локации'), { target: { value: 'l1' } });
  expect(mockQueryParams).toEqual(expect.objectContaining({ search: 'Remote', group_id: 'g1', location_id: 'l1' }));
  expect(screen.getByText('Remote Pixel')).toBeInTheDocument();
  expect(screen.queryByText('Local Pixel')).not.toBeInTheDocument();
  jest.useRealTimers();
});

it('does not present missing live presence as a healthy zero-count fleet', () => {
  mockPresenceAvailable = false;
  render(<FleetStreamPage />);

  expect(screen.getByRole('status')).toHaveTextContent('Live-presence недоступен');
  expect(screen.getByRole('button', { name: 'Доступны —' })).toBeInTheDocument();
});

it('lets stream cards expand into the available grid width instead of capping them at 21rem', () => {
  const { container } = render(<FleetStreamPage />);
  const grid = container.querySelector('[style*="grid-template-columns"]');

  expect(grid).toHaveStyle({ gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 17rem), 1fr))' });
});
