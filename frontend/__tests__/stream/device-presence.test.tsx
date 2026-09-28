import { fireEvent, render, screen } from '@testing-library/react';
import FleetStreamPage from '@/app/(dashboard)/stream/page';
import type { Device } from '@/lib/hooks/useDevices';

let mockDevices: Device[];
let mockIsLoading = false;
let mockIsError = false;
let mockIsFetching = false;
let mockDataAvailable = true;
let mockCatalogTotal: number | null = null;
const mockRefetch = jest.fn();
jest.mock('@/lib/hooks/useDevices', () => ({
  useDevices: (params: { status?: string }) => {
    // The real API filters offline rows out of an online-only query.
    const items = mockDevices.filter(d => !params.status || d.status === params.status);
    return {
      data: mockDataAvailable ? { items, total: mockCatalogTotal ?? items.length } : undefined,
      isLoading: mockIsLoading,
      isError: mockIsError,
      isFetching: mockIsFetching,
      refetch: mockRefetch,
    };
  },
}));
jest.mock('@/lib/hooks/useGroups', () => ({ useGroups: () => ({ data: [] }) }));
jest.mock('@/lib/hooks/useLocations', () => ({ useLocations: () => ({ data: [] }) }));
jest.mock('@/components/sphere/DeviceStream', () => ({
  DeviceStream: ({ deviceId }: { deviceId: string }) => <div>Live {deviceId}</div>,
}));

beforeEach(() => {
  mockIsLoading = false;
  mockIsError = false;
  mockIsFetching = false;
  mockDataAvailable = true;
  mockCatalogTotal = null;
  mockRefetch.mockReset();
  mockDevices = [
    { id: 'a', name: 'Agent A', status: 'online', group_ids: [], location_ids: [] },
    { id: 'b', name: 'Agent B', status: 'online', group_ids: [], location_ids: [] },
  ] as unknown as Device[];
});

afterEach(() => {
  jest.restoreAllMocks();
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

  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }));
  expect(screen.getByText('Agent 65')).toBeInTheDocument();
  expect(screen.getByText('Показано 1 из 65 устройств · страница 2 из 2')).toBeInTheDocument();
});

it('shows loading and retryable API error states instead of a false empty result', () => {
  mockIsLoading = true;
  mockDataAvailable = false;
  const view = render(<FleetStreamPage />);
  expect(screen.getByRole('status', { name: '' })).toHaveTextContent('Загружаем список устройств');

  mockIsLoading = false;
  mockIsError = true;
  view.rerender(<FleetStreamPage />);
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось обновить список устройств');
  expect(screen.getByText('Список устройств недоступен')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
  expect(mockRefetch).toHaveBeenCalledTimes(1);
});

it('warns when the API reports more devices than the loaded sample', () => {
  mockCatalogTotal = 3;
  render(<FleetStreamPage />);

  expect(screen.getByRole('status')).toHaveTextContent('Загружено 2 из 3 устройств');
});

it('lets stream cards expand into the available grid width instead of capping them at 21rem', () => {
  const { container } = render(<FleetStreamPage />);
  const grid = container.querySelector('[style*="grid-template-columns"]');

  expect(grid).toHaveStyle({ gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 17rem), 1fr))' });
});
