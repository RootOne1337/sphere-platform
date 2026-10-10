import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import DevicesPage from '@/app/(dashboard)/devices/page';
import { useCapabilities } from '@/src/features/access/Capabilities';
import { useBulkAction, useBulkDeleteDevices, useDeleteDevice, useDevices, useUpdateDevice, type Device } from '@/lib/hooks/useDevices';
import { useBulkRevokeVpn } from '@/lib/hooks/useVpn';
import { useGroups, useMoveDevices } from '@/lib/hooks/useGroups';
import { useLocations, useAssignDevicesToLocation } from '@/lib/hooks/useLocations';
import { useGameServers } from '@/lib/hooks/usePipelineSettings';
import rolePermissions from '../fixtures/session-capabilities.json';

jest.mock('next/navigation', () => ({ useSearchParams: () => new URLSearchParams() }));
jest.mock('@/src/features/access/Capabilities', () => ({ ...jest.requireActual('@/src/features/access/Capabilities'), useCapabilities: jest.fn() }));
jest.mock('@/lib/hooks/useDevices', () => ({ useDevices: jest.fn(), useBulkAction: jest.fn(), useBulkDeleteDevices: jest.fn(), useDeleteDevice: jest.fn(), useUpdateDevice: jest.fn() }));
jest.mock('@/lib/hooks/useVpn', () => ({ useBulkRevokeVpn: jest.fn() }));
jest.mock('@/lib/hooks/useGroups', () => ({ useGroups: jest.fn(), useMoveDevices: jest.fn() }));
jest.mock('@/lib/hooks/useLocations', () => ({ useLocations: jest.fn(), useAssignDevicesToLocation: jest.fn() }));
jest.mock('@/lib/hooks/usePipelineSettings', () => ({ useGameServers: jest.fn() }));
jest.mock('@/lib/hooks/useDebounce', () => ({ useDebounce: (value: string) => value }));
jest.mock('@/src/features/devices/MultiStreamGrid', () => ({ MultiStreamGrid: () => null }));
jest.mock('@/src/features/devices/FleetMatrix', () => ({ FleetMatrix: ({ rowSelection, onRowSelectionChange, onDeviceAction }: {
  rowSelection: Record<string, boolean>; onRowSelectionChange: (value: Record<string, boolean>) => void;
  onDeviceAction: (id: string, action: string) => void;
}) => <>
  <button onClick={() => onRowSelectionChange({ 'device-1': !rowSelection['device-1'] })}>Выбрать Fixture</button>
  {['rename', 'assign_group', 'assign_location', 'assign_server', 'delete'].map(action => <button key={action} onClick={() => onDeviceAction('device-1', action)}>Invoke {action}</button>)}
</> }));

const device = { id: 'device-1', name: 'Fixture', status: 'online', group_ids: [], location_ids: [], tags: [] } as unknown as Device;
const mutations = {
  reboot: jest.fn(), remove: jest.fn(), bulkRemove: jest.fn(), update: jest.fn(), vpn: jest.fn(), group: jest.fn(), location: jest.fn(),
};
function permissions(grants: readonly string[], fields = {}) {
  jest.mocked(useCapabilities).mockReturnValue({
    verified: true, pending: false, failed: false, role: 'fixture',
    can: permission => grants.includes(permission), canAccessRoute: () => true, retry: jest.fn(), ...fields,
  });
}
beforeEach(() => {
  jest.clearAllMocks();
  permissions(rolePermissions.org_admin);
  jest.mocked(useDevices).mockReturnValue({ data: { items: [device], total: 1, page: 1, page_size: 100, pages: 1 }, isLoading: false, isFetching: false, isError: false, refetch: jest.fn() } as never);
  for (const [hook, mutateAsync] of [
    [useBulkAction, mutations.reboot], [useDeleteDevice, mutations.remove], [useBulkDeleteDevices, mutations.bulkRemove],
    [useUpdateDevice, mutations.update], [useBulkRevokeVpn, mutations.vpn], [useMoveDevices, mutations.group], [useAssignDevicesToLocation, mutations.location],
  ] as const) jest.mocked(hook).mockReturnValue({ isPending: false, mutateAsync } as never);
  jest.mocked(useGroups).mockReturnValue({ data: [{ id: 'group-1', name: 'Group' }], isLoading: false, isError: false, refetch: jest.fn() } as never);
  jest.mocked(useLocations).mockReturnValue({ data: [{ id: 'loc-1', name: 'Location' }], isLoading: false, isError: false, refetch: jest.fn() } as never);
  jest.mocked(useGameServers).mockReturnValue({ data: [{ id: 1, name: 'Server' }] } as never);
});

it.each(['viewer', 'script_runner'] as const)('keeps registry readable but disables device mutations for %s', role => {
  permissions(rolePermissions[role]);
  render(<DevicesPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Выбрать Fixture' }));
  for (const name of ['Перезапустить', 'Группа', 'Локация', 'Переименовать', 'Отозвать VPN', 'Удалить выбранные устройства (1)']) {
    expect(screen.getByRole('button', { name })).toBeDisabled();
  }
  for (const action of ['rename', 'assign_group', 'assign_location', 'assign_server', 'delete']) fireEvent.click(screen.getByRole('button', { name: `Invoke ${action}` }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Обновить список' })).toBeEnabled();
  for (const mutation of Object.values(mutations)) expect(mutation).not.toHaveBeenCalled();
});

it('does not confuse device:write with device:delete or vpn:mass_operation', () => {
  permissions(rolePermissions.device_manager);
  render(<DevicesPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Выбрать Fixture' }));
  expect(screen.getByRole('button', { name: 'Перезапустить' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Переименовать' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Группа' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Локация' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Удалить выбранные устройства (1)' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Отозвать VPN' })).toBeDisabled();
});

it.each(['pending', 'failed'] as const)('does not offer mutation authority while capabilities are %s', state => {
  permissions([], { verified: false, pending: state === 'pending', failed: state === 'failed' });
  render(<DevicesPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Выбрать Fixture' }));
  expect(screen.getByRole('button', { name: 'Переименовать' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Удалить выбранные устройства (1)' })).toBeDisabled();
});

it.each(['single', 'bulk'] as const)('withdraws %s deletion from an already open confirmation', kind => {
  const view = render(<DevicesPage />);
  if (kind === 'single') fireEvent.click(screen.getByRole('button', { name: 'Invoke delete' }));
  else {
    fireEvent.click(screen.getByRole('button', { name: 'Выбрать Fixture' }));
    fireEvent.click(screen.getByRole('button', { name: 'Удалить выбранные устройства (1)' }));
  }
  const confirm = kind === 'single' ? 'Убрать запись' : 'Убрать из каталога (1)';
  expect(screen.getByRole('button', { name: confirm })).toBeEnabled();
  permissions(rolePermissions.viewer);
  view.rerender(<DevicesPage />);
  expect(screen.getByRole('button', { name: confirm })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: confirm }));
  expect(mutations.remove).not.toHaveBeenCalled();
  expect(mutations.bulkRemove).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Отмена' })).toBeEnabled();
});

it('blocks the rename Enter shortcut after permission withdrawal without losing the draft', () => {
  const view = render(<DevicesPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Invoke rename' }));
  const input = within(screen.getByRole('dialog')).getByRole('textbox');
  fireEvent.change(input, { target: { value: 'My saved draft' } });
  permissions(rolePermissions.viewer);
  view.rerender(<DevicesPage />);
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(mutations.update).not.toHaveBeenCalled();
  expect(input).toHaveValue('My saved draft');
  expect(within(screen.getByRole('dialog')).getByRole('button', { name: 'Сохранить' })).toBeDisabled();
});

it('withdraws VPN confirmation independently of a still permitted device update', () => {
  const view = render(<DevicesPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Выбрать Fixture' }));
  fireEvent.click(screen.getByRole('button', { name: 'Отозвать VPN' }));
  permissions(rolePermissions.device_manager);
  view.rerender(<DevicesPage />);
  const button = within(screen.getByRole('dialog')).getByRole('button', { name: 'Отозвать VPN (1)' });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(mutations.vpn).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Переименовать' })).toBeEnabled();
});

it('keeps authorized confirmations and sends only their selected target', async () => {
  mutations.bulkRemove.mockResolvedValue({ deleted: 1 });
  render(<DevicesPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Выбрать Fixture' }));
  fireEvent.click(screen.getByRole('button', { name: 'Удалить выбранные устройства (1)' }));
  fireEvent.click(screen.getByRole('button', { name: 'Убрать из каталога (1)' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(mutations.bulkRemove).toHaveBeenCalledTimes(1);
  expect(mutations.bulkRemove).toHaveBeenCalledWith(['device-1']);
  for (const name of ['remove', 'reboot', 'vpn', 'update', 'group', 'location'] as const) expect(mutations[name]).not.toHaveBeenCalled();
});
