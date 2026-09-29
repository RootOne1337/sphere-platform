import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import VPNManagerPage from '@/app/(dashboard)/vpn/page';
import { useAssignVpn, usePoolStats, useVpnKillSwitch, useVpnPeers, useVpnRotate } from '@/lib/hooks/useVpn';
import { useBulkAction, useDevices, type Device } from '@/lib/hooks/useDevices';

const mockMutateAsync = jest.fn();
const mockUseAssignVpn = jest.mocked(useAssignVpn);
const mockUsePoolStats = jest.mocked(usePoolStats);
const mockUseVpnKillSwitch = jest.mocked(useVpnKillSwitch);
const mockUseVpnPeers = jest.mocked(useVpnPeers);
const mockUseVpnRotate = jest.mocked(useVpnRotate);
const mockUseBulkAction = jest.mocked(useBulkAction);
const mockUseDevices = jest.mocked(useDevices);

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn() }) }));
jest.mock('@/src/features/vpn/VPNMap', () => ({ VPNMap: () => null }));
jest.mock('@/src/features/vpn/ThroughputChart', () => ({ ThroughputChart: () => null }));
jest.mock('@/lib/hooks/useVpn', () => ({
  useAssignVpn: jest.fn(),
  usePoolStats: jest.fn(),
  useVpnKillSwitch: jest.fn(),
  useVpnPeers: jest.fn(),
  useVpnRotate: jest.fn(),
}));
jest.mock('@/lib/hooks/useDevices', () => ({ useBulkAction: jest.fn(), useDevices: jest.fn() }));

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

const device: Device = {
  id: 'device-2', name: 'Remote Beta', android_id: 'serial-b', model: 'LDPlayer',
  device_model: 'LDPlayer', android_version: '9', tags: [], group_id: null, group_ids: [],
  group_name: null, location_ids: [], status: 'online', battery_level: 90, cpu_usage: 10,
  ram_usage_mb: 512, screen_on: true, last_seen: null, last_heartbeat: null,
  adb_connected: false, vpn_assigned: false, vpn_active: null, server_name: null,
};

beforeEach(() => {
  jest.clearAllMocks();
  mockUseAssignVpn.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false } as never);
  mockUsePoolStats.mockReturnValue({ data: undefined, isLoading: false } as never);
  mockUseVpnKillSwitch.mockReturnValue({ mutate: jest.fn(), isPending: false } as never);
  mockUseVpnPeers.mockReturnValue({ data: [], isLoading: false } as never);
  mockUseVpnRotate.mockReturnValue({ mutate: jest.fn(), isPending: false } as never);
  mockUseBulkAction.mockReturnValue({ mutate: jest.fn(), isPending: false } as never);
  mockUseDevices.mockReturnValue({
    data: { items: [device], total: 1, page: 1, page_size: 100, pages: 1 },
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: jest.fn(),
  } as never);
});

it('keeps VPN provisioning open after a rejected request and does not retry implicitly', async () => {
  mockMutateAsync.mockRejectedValue({ response: { data: { detail: 'VPN provider unavailable' } } });
  const user = userEvent.setup();
  render(<VPNManagerPage />);

  await user.click(screen.getByRole('button', { name: 'Provision Node' }));
  await user.click(screen.getByRole('combobox', { name: 'Устройство' }));
  await user.click(await screen.findByRole('option', { name: /Remote Beta/ }));
  await user.click(screen.getByRole('button', { name: 'Assign VPN' }));

  expect(mockMutateAsync).toHaveBeenCalledTimes(1);
  expect(mockMutateAsync).toHaveBeenCalledWith({ device_id: 'device-2' });
  expect(await screen.findByRole('alert')).toHaveTextContent('VPN provider unavailable');
  expect(screen.getByRole('heading', { name: 'Provision VPN Node' })).toBeVisible();
  expect(mockMutateAsync).toHaveBeenCalledTimes(1);
});
