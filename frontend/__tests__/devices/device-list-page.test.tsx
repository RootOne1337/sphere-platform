import { fireEvent, render, screen, within } from '@testing-library/react';
import DevicesPage from '@/app/(dashboard)/devices/page';
import {
  useBulkAction,
  useBulkDeleteDevices,
  useDeleteDevice,
  useDevices,
  useUpdateDevice,
} from '@/lib/hooks/useDevices';
import { useBulkRevokeVpn } from '@/lib/hooks/useVpn';
import { useGroups, useMoveDevices } from '@/lib/hooks/useGroups';
import { useAssignDevicesToLocation, useLocations } from '@/lib/hooks/useLocations';
import { useGameServers } from '@/lib/hooks/usePipelineSettings';
import type { Device } from '@/lib/hooks/useDevices';

jest.mock('@/lib/hooks/useDevices', () => ({
  useDevices: jest.fn(),
  useBulkAction: jest.fn(),
  useDeleteDevice: jest.fn(),
  useUpdateDevice: jest.fn(),
  useBulkDeleteDevices: jest.fn(),
}));
jest.mock('@/lib/hooks/useVpn', () => ({ useBulkRevokeVpn: jest.fn() }));
jest.mock('@/lib/hooks/useGroups', () => ({ useGroups: jest.fn(), useMoveDevices: jest.fn() }));
jest.mock('@/lib/hooks/useLocations', () => ({ useLocations: jest.fn(), useAssignDevicesToLocation: jest.fn() }));
jest.mock('@/lib/hooks/usePipelineSettings', () => ({ useGameServers: jest.fn() }));
jest.mock('@/lib/hooks/useDebounce', () => ({ useDebounce: (value: string) => value }));
jest.mock('@/src/features/devices/FleetMatrix', () => ({
  FleetMatrix: ({ data }: { data: Device[] }) => (
    <ul aria-label="Filtered devices">{data.map((device) => <li key={device.id}>{device.name}</li>)}</ul>
  ),
}));
jest.mock('@/src/features/devices/MultiStreamGrid', () => ({ MultiStreamGrid: () => null }));
jest.mock('@/src/features/devices/DeviceBulkDeleteButton', () => ({ DeviceBulkDeleteButton: () => null }));
jest.mock('@/src/features/devices/DeviceDeleteConfirmationDialog', () => ({ DeviceDeleteConfirmationDialog: () => null }));

function makeDevice(id: string, status: Device['status'], groupId: string | null = null): Device {
  return {
    id,
    name: id,
    android_id: `android-${id}`,
    model: 'LDPlayer',
    device_model: null,
    android_version: '9',
    tags: [],
    group_id: groupId,
    group_ids: [],
    group_name: null,
    location_ids: [],
    status,
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
}

const devices = [
  makeDevice('phone-online', 'online', 'group-a'),
  makeDevice('phone-busy', 'busy', 'group-a'),
  makeDevice('phone-connecting', 'connecting', 'group-b'),
  makeDevice('phone-maintenance', 'maintenance', 'group-b'),
];

beforeEach(() => {
  jest.mocked(useDevices).mockReturnValue({
    data: { items: devices, total: devices.length, page: 1, page_size: 5000, pages: 1 },
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
    refetch: jest.fn(),
  } as never);
  for (const hook of [useBulkAction, useDeleteDevice, useUpdateDevice, useBulkDeleteDevices, useBulkRevokeVpn, useMoveDevices, useAssignDevicesToLocation]) {
    jest.mocked(hook).mockReturnValue({ isPending: false, mutateAsync: jest.fn() } as never);
  }
  jest.mocked(useGroups).mockReturnValue({ data: [], isLoading: false, isError: false, refetch: jest.fn() } as never);
  jest.mocked(useLocations).mockReturnValue({ data: [], isLoading: false, isError: false, refetch: jest.fn() } as never);
  jest.mocked(useGameServers).mockReturnValue({ data: [] } as never);
});

afterEach(() => jest.clearAllMocks());

it('wires fleet status cards to the visible device list and clears attention through the same filter', () => {
  render(<DevicesPage />);
  const list = screen.getByRole('list', { name: 'Filtered devices' });
  const statusCards = screen.getByRole('region', { name: 'Состояние устройств' });
  const cardButton = (label: string) => within(statusCards).getByText(label, { selector: 'p' }).closest('button')!;

  expect(within(list).getAllByRole('listitem')).toHaveLength(4);
  fireEvent.click(cardButton('В сети'));
  expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['phone-online', 'phone-busy']);

  fireEvent.click(cardButton('Подключаются'));
  expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['phone-connecting']);

  fireEvent.click(cardButton('Требуют внимания'));
  expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['phone-maintenance']);
  expect(cardButton('Требуют внимания')).toHaveAttribute('aria-pressed', 'true');
});
