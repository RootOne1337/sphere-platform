import { fireEvent, render, screen } from '@testing-library/react';
import { MultiStreamGrid } from '@/src/features/devices/MultiStreamGrid';
import type { Device } from '@/lib/hooks/useDevices';

jest.mock('@/components/sphere/DeviceStream', () => ({
  DeviceStream: ({ deviceId, fit }: { deviceId: string; fit: string }) => (
    <div data-testid={`stream-${deviceId}`} data-fit={fit} />
  ),
}));

jest.mock('@/src/shared/store/useStreamStore', () => ({
  GRID_SIZE_OPTIONS: [1, 4],
  gridColumns: (size: number) => size === 1 ? 1 : 2,
  gridLabel: (size: number) => size === 1 ? '1×1' : '2×2',
  useStreamStore: () => {
    const React = jest.requireActual('react');
    const [objectFit, setObjectFit] = React.useState('contain');
    return {
      gridSize: 4,
      objectFit,
      showHUD: true,
      showStats: true,
      setGridSize: jest.fn(),
      setObjectFit,
      toggleHUD: jest.fn(),
      toggleStats: jest.fn(),
    };
  },
}));

const makeDevice = (id: string, status: Device['status'], last_heartbeat: string | null): Device => ({
  id,
  name: id,
  android_id: id,
  model: 'LDPlayer',
  device_model: 'LDPlayer',
  android_version: 'Android 9',
  tags: [],
  group_id: null,
  group_ids: [],
  group_name: null,
  location_ids: [],
  status,
  agent_version: null,
  agent_version_code: null,
  battery_level: null,
  cpu_usage: null,
  ram_usage_mb: null,
  screen_on: null,
  last_seen: last_heartbeat,
  last_heartbeat,
  adb_connected: false,
  vpn_assigned: false,
  vpn_active: null,
  server_name: null,
});

describe('MultiStreamGrid', () => {
  afterEach(() => jest.restoreAllMocks());

  it('streams selected devices and stops the live viewers from its stop button', () => {
    const onClose = jest.fn();
    render(
      <MultiStreamGrid
        devices={[
          makeDevice('local-first', 'online', null),
          makeDevice('remote-selected', 'online', null),
        ]}
        selectedIds={['remote-selected']}
        onClose={onClose}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Запустить вещание' }));
    expect(screen.getByTestId('stream-remote-selected')).toBeInTheDocument();
    expect(screen.getByTestId('stream-remote-selected')).toHaveAttribute('data-fit', 'contain');
    expect(screen.queryByTestId('stream-local-first')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Остановить потоки' }));
    expect(screen.queryByTestId('stream-remote-selected')).not.toBeInTheDocument();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('applies the selected contain/cover mode to the live canvas viewer', () => {
    render(
      <MultiStreamGrid devices={[makeDevice('device-1', 'online', null)]} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Запустить вещание' }));
    expect(screen.getByTestId('stream-device-1')).toHaveAttribute('data-fit', 'contain');

    fireEvent.click(screen.getByRole('button', { name: 'Изменить масштаб видео' }));
    expect(screen.getByTestId('stream-device-1')).toHaveAttribute('data-fit', 'cover');
  });

  it('shows the measured heartbeat age instead of a fixed freshness claim or fabricated network error', () => {
    jest.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-09-25T12:01:00Z'));
    render(
      <MultiStreamGrid
        devices={[
          makeDevice('offline-device', 'offline', null),
          makeDevice('online-device', 'online', '2026-09-25T12:00:00Z'),
        ]}
      />,
    );

    expect(screen.getByText('1 мин назад')).toBeInTheDocument();
    expect(screen.getByText(/Проверьте heartbeat и доступность устройства/)).toBeInTheDocument();
    expect(screen.queryByText('ERR_CONN_REFUSED')).not.toBeInTheDocument();
    expect(screen.queryByText('< 5s')).not.toBeInTheDocument();
  });

  it('keeps stream subscriptions within the selected grid capacity', () => {
    const devices = Array.from({ length: 5 }, (_, index) =>
      makeDevice(`device-${index}`, 'online', null),
    );
    render(<MultiStreamGrid devices={devices} />);

    fireEvent.click(screen.getByRole('button', { name: 'Запустить вещание' }));

    expect(screen.getByTestId('stream-device-0')).toBeInTheDocument();
    expect(screen.getByTestId('stream-device-3')).toBeInTheDocument();
    expect(screen.queryByTestId('stream-device-4')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Показаны первые 4 из 5 устройств');
  });
});
