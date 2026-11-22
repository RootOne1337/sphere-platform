import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { VpnBatchTab } from '@/app/(dashboard)/vpn/_tabs/VpnBatchTab';
import { useDevices } from '@/lib/hooks/useDevices';

const mockAssign = jest.fn();
const mockBulkRevoke = jest.fn();

jest.mock('@/lib/hooks/useDevices', () => ({ useDevices: jest.fn() }));
jest.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: jest.fn().mockResolvedValue(undefined) }),
}));
jest.mock('@/lib/hooks/useVpn', () => ({
  useAssignVpn: () => ({ mutateAsync: mockAssign, isPending: false }),
  useBulkRevokeVpn: () => ({ mutateAsync: mockBulkRevoke, isPending: false }),
}));

const devices = [
  { id: 'device-a', name: 'Device A', vpn_assigned: false },
  { id: 'device-b', name: 'Device B', vpn_assigned: true },
];

function renderTab() {
  jest.mocked(useDevices).mockReturnValue({
    data: { items: devices, total: devices.length, page: 1, page_size: 500, pages: 1 },
    isLoading: false,
    isError: false,
    refetch: jest.fn(),
  } as never);
  return render(<VpnBatchTab />);
}

function selectDevice(name: string) {
  fireEvent.click(screen.getByRole('checkbox', { name: new RegExp(name) }));
}

beforeEach(() => {
  jest.clearAllMocks();
  mockAssign.mockResolvedValue({});
  mockBulkRevoke.mockResolvedValue({
    total: 2,
    succeeded: 2,
    failed: 0,
    results: devices.map((device) => ({ device_id: device.id, success: true, error: null })),
  });
});

it('finishes assignment after an individual failure and leaves only the unconfirmed device selected', async () => {
  mockAssign.mockResolvedValueOnce({}).mockRejectedValueOnce(new Error('transport timeout'));
  renderTab();
  selectDevice('Device A');
  selectDevice('Device B');
  fireEvent.click(screen.getByRole('button', { name: 'Назначить VPN (2)' }));

  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Назначено 1 из 2'));
  expect(mockAssign).toHaveBeenCalledTimes(2);
  expect(screen.getByRole('checkbox', { name: /Device A/ })).not.toBeChecked();
  expect(screen.getByRole('checkbox', { name: /Device B/ })).toBeChecked();
  expect(screen.getByRole('button', { name: 'Назначить VPN (1)' })).toBeEnabled();
});

it('uses the receipt-producing bulk revoke API and retains only failed targets', async () => {
  mockBulkRevoke.mockResolvedValueOnce({
    total: 2,
    succeeded: 1,
    failed: 1,
    results: [
      { device_id: 'device-a', success: true, error: null },
      { device_id: 'device-b', success: false, error: 'provider unavailable' },
    ],
  });
  renderTab();
  selectDevice('Device A');
  selectDevice('Device B');
  fireEvent.click(screen.getByRole('button', { name: 'Отозвать VPN (2)' }));

  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Отозвано 1 из 2'));
  expect(mockBulkRevoke).toHaveBeenCalledWith(['device-a', 'device-b']);
  expect(screen.getByRole('checkbox', { name: /Device A/ })).not.toBeChecked();
  expect(screen.getByRole('checkbox', { name: /Device B/ })).toBeChecked();
  expect(screen.getByRole('button', { name: 'Отозвать VPN (1)' })).toBeEnabled();
});

it('keeps the selection after a request-level revoke failure and never retries automatically', async () => {
  mockBulkRevoke.mockRejectedValueOnce(new Error('network timeout'));
  renderTab();
  selectDevice('Device A');
  fireEvent.click(screen.getByRole('button', { name: 'Отозвать VPN (1)' }));

  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Сервер не подтвердил результат'));
  expect(mockBulkRevoke).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('checkbox', { name: /Device A/ })).toBeChecked();
  expect(screen.getByRole('button', { name: 'Отозвать VPN (1)' })).toBeEnabled();
});
