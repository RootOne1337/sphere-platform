import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import LogsPage from '@/app/(dashboard)/logs/page';
import { api } from '@/lib/api';
import { useDevices, type Device } from '@/lib/hooks/useDevices';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), delete: jest.fn() } }));
jest.mock('@/lib/hooks/useDevices', () => ({ useDevices: jest.fn() }));
jest.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams(), useRouter: () => ({ replace: jest.fn() }) }));
jest.mock('@/lib/hooks/useDeviceSnapshot', () => ({ useDeviceSnapshot: () => ({ data: device }) }));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), error: jest.fn() } }));

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() });
});

const device: Device = {
  id: 'device-001',
  name: 'Удалённый Android',
  android_id: 'android-001',
  model: 'LDPlayer',
  device_model: null,
  android_version: '9',
  tags: [],
  group_id: null,
  group_ids: [],
  group_name: null,
  location_ids: [],
  status: 'online',
  battery_level: null,
  cpu_usage: null,
  ram_usage_mb: null,
  screen_on: null,
  last_seen: null,
  last_heartbeat: null,
  adb_connected: false,
  vpn_assigned: false,
  vpn_active: null,
  server_name: null,
};

const logPayload = {
  device_id: device.id,
  lines: [
    '2026-09-29T10:12:13.123Z I/Agent: connected through relay',
    '2026-09-29T10:12:14.123Z W/Stream: frame delivery delayed',
    'unstructured diagnostic line',
  ],
  total: 3,
};

beforeEach(() => {
  jest.mocked(useDevices).mockReturnValue({
    data: { items: [device], total: 1, page: 1, page_size: 20 },
    isSuccess: true,
    isFetching: false,
    isLoading: false,
    isError: false,
    refetch: jest.fn(),
  } as never);
  jest.mocked(api.get).mockResolvedValue({ data: logPayload });
  jest.mocked(api.delete).mockResolvedValue({ data: { deleted: true } });
});

afterEach(() => {
  jest.useRealTimers();
  jest.clearAllMocks();
});

describe('Logs page', () => {
  it('loads and displays actual backend log lines and selected device', async () => {
    render(<LogsPage />);

    expect(await screen.findByText('connected through relay')).toBeInTheDocument();
    expect(screen.getByText('frame delivery delayed')).toBeInTheDocument();
    expect(screen.getByText('unstructured diagnostic line')).toBeInTheDocument();
    expect(screen.getByText('Удалённый Android', { selector: 'span' })).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/logs/device-001?lines=1000', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(screen.getByText('3 показано · 3 загружено')).toBeInTheDocument();
  });

  it('filters warning entries without hiding the source log lines from backend', async () => {
    render(<LogsPage />);
    await screen.findByText('connected through relay');

    fireEvent.click(screen.getByRole('combobox', { name: 'Фильтр уровня логов' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Предупреждения' }));

    expect(screen.getByText('frame delivery delayed')).toBeInTheDocument();
    expect(screen.queryByText('connected through relay')).not.toBeInTheDocument();
    expect(screen.getByText('1 показано · 3 загружено')).toBeInTheDocument();
  });

  it('confirms before deleting log files and clears the view only after backend success', async () => {
    render(<LogsPage />);
    await screen.findByText('connected through relay');

    fireEvent.click(screen.getByRole('button', { name: /Очистить логи/ }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Удалить архив логов?');
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Отмена' }));
    expect(api.delete).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /Очистить логи/ }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Удалить логи' }));

    await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/logs/device-001'));
    await waitFor(() => expect(screen.queryByText('connected through relay')).not.toBeInTheDocument());
    expect(screen.getByText('0 показано · 0 загружено')).toBeInTheDocument();
  });

  it('keeps existing lines visible and reports a failed delete', async () => {
    jest.mocked(api.delete).mockRejectedValue(new Error('permission denied'));
    render(<LogsPage />);
    await screen.findByText('connected through relay');

    fireEvent.click(screen.getByRole('button', { name: /Очистить логи/ }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Удалить логи' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('permission denied');
    expect(screen.getByText('connected through relay')).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toHaveTextContent('Не удалось очистить логи');
  });

  it('shows malformed API data as an error instead of crashing the page', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { lines: 'not-an-array' } });
    render(<LogsPage />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Backend вернул некорректный список строк логов.');
    expect(screen.getByRole('button', { name: 'Повторить запрос' })).toBeInTheDocument();
  });

  it('debounces server-side search so rapid typing produces one filtered request', async () => {
    render(<LogsPage />);

    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
    const input = screen.getByRole('textbox', { name: 'Поиск в логах' });
    fireEvent.change(input, { target: { value: 'stream' } });
    fireEvent.change(input, { target: { value: 'stream frame' } });
    expect(api.get).toHaveBeenCalledTimes(1);

    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    expect(api.get).toHaveBeenLastCalledWith('/logs/device-001?lines=1000&search=stream+frame', expect.any(Object));
  });
});
