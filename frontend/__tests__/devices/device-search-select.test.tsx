import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DeviceSearchSelect } from '@/components/sphere/DeviceSearchSelect';
import { useDevices, type Device } from '@/lib/hooks/useDevices';

const mockUseDevices = jest.mocked(useDevices);
const mockOnChange = jest.fn();

jest.mock('@/lib/hooks/useDevices', () => ({ useDevices: jest.fn() }));

it('shows canonical model metadata in the single-device picker without changing its selected ID', async () => {
  const canonical = { ...devices[0], device_model: 'Canonical emulator', model: 'Legacy emulator' };
  setDeviceQuery([canonical]);
  const user = userEvent.setup();
  render(<DeviceSearchSelect value="" onChange={mockOnChange} />);
  await user.click(screen.getByRole('combobox'));
  expect(screen.getByText('Canonical emulator')).toBeInTheDocument();
  expect(screen.queryByText('Legacy emulator')).not.toBeInTheDocument();
  await user.click(screen.getByRole('option', { name: /Canonical emulator/ }));
  expect(mockOnChange).toHaveBeenCalledWith(canonical.id);
});

beforeAll(() => {
  class ResizeObserverMock implements ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  Object.defineProperty(globalThis, 'ResizeObserver', { configurable: true, value: ResizeObserverMock });
  Object.defineProperty(HTMLElement.prototype, 'hasPointerCapture', { configurable: true, value: () => false });
  Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', { configurable: true, value: () => undefined });
  Object.defineProperty(HTMLElement.prototype, 'releasePointerCapture', { configurable: true, value: () => undefined });
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() });
});

const devices: Device[] = [
  {
    id: 'device-1', name: 'Remote Alpha', android_id: 'serial-a', model: 'LDPlayer',
    device_model: 'LDPlayer', android_version: '9', tags: [], group_id: null, group_ids: [],
    group_name: null, location_ids: [], status: 'online', battery_level: 90, cpu_usage: 10,
    ram_usage_mb: 512, screen_on: true, last_seen: null, last_heartbeat: null,
    adb_connected: false, vpn_assigned: false, vpn_active: null, server_name: null,
  },
  {
    id: 'device-2', name: 'Remote Beta', android_id: 'serial-b', model: 'LDPlayer',
    device_model: 'LDPlayer', android_version: '9', tags: [], group_id: null, group_ids: [],
    group_name: null, location_ids: [], status: 'offline', battery_level: null, cpu_usage: null,
    ram_usage_mb: null, screen_on: null, last_seen: null, last_heartbeat: null,
    adb_connected: false, vpn_assigned: false, vpn_active: null, server_name: null,
  },
];

function setDeviceQuery(items = devices, total = items.length) {
  mockUseDevices.mockReturnValue({
    data: { items, total, page: 1, page_size: 100, pages: Math.ceil(total / 100) },
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: jest.fn(),
  } as never);
}

beforeEach(() => {
  jest.clearAllMocks();
  setDeviceQuery();
});

afterEach(() => {
  jest.useRealTimers();
});

it('uses a bounded server lookup and returns the chosen device ID', async () => {
  const user = userEvent.setup();
  render(<DeviceSearchSelect value="" onChange={mockOnChange} />);

  expect(mockUseDevices).toHaveBeenCalledWith({ page: 1, page_size: 100, search: undefined });
  await user.click(screen.getByRole('combobox'));
  await user.click(await screen.findByRole('option', { name: /Remote Alpha/ }));

  expect(mockOnChange).toHaveBeenCalledWith('device-1');
});

it('debounces search and disables selection until the server result is current', async () => {
  jest.useFakeTimers();
  const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
  render(<DeviceSearchSelect value="" onChange={mockOnChange} />);

  await user.type(screen.getByRole('textbox', { name: 'Поиск устройства' }), 'serial-b');
  expect(screen.getByRole('combobox')).toBeDisabled();
  expect(mockOnChange).not.toHaveBeenCalled();

  await act(async () => { jest.advanceTimersByTime(300); });
  await waitFor(() => expect(mockUseDevices).toHaveBeenLastCalledWith({ page: 1, page_size: 100, search: 'serial-b' }));
});

it('excludes already assigned devices and calls out a truncated result set', async () => {
  const user = userEvent.setup();
  setDeviceQuery([devices[0]], 130);
  render(<DeviceSearchSelect value="" onChange={mockOnChange} excludedIds={new Set(['device-1'])} />);

  expect(screen.getByText('Показаны первые 1 из 130. Уточните поиск, чтобы найти остальные.')).toBeInTheDocument();
  expect(screen.getByText('Все показанные устройства уже назначены. Уточните поиск, чтобы найти другие.')).toBeInTheDocument();
  await user.click(screen.getByRole('combobox'));
  expect(screen.queryByRole('option', { name: /Remote Alpha/ })).not.toBeInTheDocument();
  expect(screen.getByRole('combobox')).toBeDisabled();
  expect(mockOnChange).not.toHaveBeenCalled();
});

it('fails closed on lookup errors and exposes an explicit retry', async () => {
  const refetch = jest.fn();
  mockUseDevices.mockReturnValue({
    data: undefined,
    isLoading: false,
    isFetching: false,
    isError: true,
    refetch,
  } as never);
  const user = userEvent.setup();
  render(<DeviceSearchSelect value="" onChange={mockOnChange} />);

  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось загрузить устройства.');
  expect(screen.getByRole('combobox')).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'Повторить' }));
  expect(refetch).toHaveBeenCalledTimes(1);
  expect(mockOnChange).not.toHaveBeenCalled();
});

it('distinguishes an empty active-device catalog from a request failure', () => {
  setDeviceQuery([], 0);
  render(<DeviceSearchSelect value="" onChange={mockOnChange} />);

  expect(screen.getByText('Нет активных устройств.')).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
