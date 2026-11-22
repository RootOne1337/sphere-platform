// Run against the real /devices page under Jest/jsdom with a synthetic API receipt.
const React = require('react');
const { act, fireEvent, render, screen, waitFor, within } = require('@testing-library/react');

jest.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams() }));
jest.mock('@/src/features/access/Capabilities', () => ({
  ...jest.requireActual('@/src/features/access/Capabilities'),
  useCapabilities: () => ({ can: () => true }),
}));
jest.mock('@/lib/hooks/useDevices', () => ({
  useDevices: jest.fn(), useBulkAction: () => ({}), useDeleteDevice: () => ({}),
  useUpdateDevice: () => ({}), useBulkDeleteDevices: () => ({}),
}));
jest.mock('@/lib/hooks/useGroups', () => ({ useGroups: () => ({}), useMoveDevices: () => ({}) }));
jest.mock('@/lib/hooks/useLocations', () => ({ useLocations: () => ({}), useAssignDevicesToLocation: () => ({}) }));
jest.mock('@/lib/hooks/usePipelineSettings', () => ({ useGameServers: () => ({}) }));
jest.mock('@/lib/hooks/useVpn', () => ({ useBulkRevokeVpn: jest.fn() }));
jest.mock('@/src/features/devices/MultiStreamGrid', () => ({ MultiStreamGrid: () => null }));
jest.mock('@/src/features/devices/FleetMatrix', () => ({
  FleetMatrix: ({ data, onRowSelectionChange }) => data.map(device =>
    require('react').createElement('button', {
      key: device.id,
      onClick: () => onRowSelectionChange(previous => ({ ...previous, [device.id]: true })),
    }, `Выбрать ${device.name}`)
  ),
}));
jest.mock('sonner', () => ({ toast: { success: jest.fn(), warning: jest.fn(), error: jest.fn() } }));

const DevicesPage = require('@/app/(dashboard)/devices/page').default;
const { useDevices } = require('@/lib/hooks/useDevices');
const { useBulkRevokeVpn } = require('@/lib/hooks/useVpn');
const { toast } = require('sonner');
const devices = ['Без назначения', 'Подтверждённый отзыв'].map((name, index) => ({
  id: `00000000-0000-4000-8000-00000000000${index + 1}`, name, status: 'online',
  group_ids: [], location_ids: [], tags: [],
}));

beforeEach(() => {
  jest.clearAllMocks();
  useDevices.mockReturnValue({
    data: { items: devices, total: 2, page: 1, page_size: 100, pages: 1, scope_total: 2 },
  });
});

async function requestRevoke(selected, receipt) {
  const mutateAsync = jest.fn().mockResolvedValue(receipt);
  useBulkRevokeVpn.mockReturnValue({ mutateAsync, isPending: false });
  render(React.createElement(DevicesPage));
  for (const device of selected) {
    fireEvent.click(screen.getByRole('button', { name: `Выбрать ${device.name}` }));
  }
  fireEvent.click(screen.getByRole('button', { name: 'Отозвать VPN' }));
  const dialog = await screen.findByRole('dialog');
  await act(async () => {
    fireEvent.click(within(dialog).getByRole('button', { name: `Отозвать VPN (${selected.length})` }));
  });
  expect(mutateAsync).toHaveBeenCalledWith(selected.map(device => device.id));
}

it('counts an already-unassigned item as a completed revocation', async () => {
  await requestRevoke(devices, {
    total: 2, succeeded: 2, failed: 0,
    results: devices.map(device => ({ device_id: device.id, success: true, error: null })),
  });
  await waitFor(() => expect(toast.success).toHaveBeenCalledWith('VPN отозван у 2 устройств'));
});

it('labels an unknown provider result as a definite non-revocation', async () => {
  const [device] = devices;
  await requestRevoke([device], {
    total: 1, succeeded: 0, failed: 1,
    results: [{ device_id: device.id, success: false, error: 'VPN revocation unavailable; inspect operation state' }],
  });
  await waitFor(() => expect(toast.warning).toHaveBeenCalledWith(
    'Не отозван VPN у 1 из 1 устройств', expect.anything(),
  ));
  expect(screen.getByRole('button', { name: 'Отозвать VPN' })).toBeEnabled();
});
