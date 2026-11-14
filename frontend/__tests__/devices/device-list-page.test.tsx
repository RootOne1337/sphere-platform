import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DevicesPage from '@/app/(dashboard)/devices/page';
import {
  useBulkAction,
  useBulkDeleteDevices,
  useDeleteDevice,
  useDevices,
  useUpdateDevice,
} from '@/lib/hooks/useDevices';
import { useBulkRevokeVpn } from '@/lib/hooks/useVpn';
import { useGroups, useChangeGroupMembership } from '@/lib/hooks/useGroups';
import { useAssignDevicesToLocation, useLocations } from '@/lib/hooks/useLocations';
import { useGameServers } from '@/lib/hooks/usePipelineSettings';
import type { Device } from '@/lib/hooks/useDevices';
import { useSearchParams } from 'next/navigation';
import rolePermissions from '../fixtures/session-capabilities.json';

// Existing registry workflow cases run under an explicitly granted server fixture.
// Denial and revocation are exercised by action-permissions.test.tsx.
jest.mock('@/src/features/access/Capabilities', () => ({
  ...jest.requireActual('@/src/features/access/Capabilities'),
  useCapabilities: () => ({ verified: true, pending: false, failed: false, role: 'org_admin', can: (permission: string) => rolePermissions.org_admin.includes(permission) }),
}));

jest.mock('next/navigation', () => ({ useSearchParams: jest.fn(() => new URLSearchParams()) }));

jest.mock('@/lib/hooks/useDevices', () => ({
  useDevices: jest.fn(),
  useBulkAction: jest.fn(),
  useDeleteDevice: jest.fn(),
  useUpdateDevice: jest.fn(),
  useBulkDeleteDevices: jest.fn(),
}));
jest.mock('@/lib/hooks/useVpn', () => ({ useBulkRevokeVpn: jest.fn() }));
jest.mock('@/lib/hooks/useGroups', () => ({ useGroups: jest.fn(), useChangeGroupMembership: jest.fn() }));
jest.mock('@/lib/hooks/useLocations', () => ({ useLocations: jest.fn(), useAssignDevicesToLocation: jest.fn() }));
jest.mock('@/lib/hooks/usePipelineSettings', () => ({ useGameServers: jest.fn() }));
jest.mock('@/lib/hooks/useDebounce', () => ({ useDebounce: (value: string) => value }));
jest.mock('@/src/features/accounts/applicationProfiles', () => ({ useApplicationProfiles: () => ({ data: undefined }) }));
jest.mock('@/src/features/devices/FleetMatrix', () => ({
  FleetMatrix: ({
    data,
    rowSelection,
    onRowSelectionChange,
  }: {
    data: Device[];
    rowSelection: Record<string, boolean>;
    onRowSelectionChange: (updater: (current: Record<string, boolean>) => Record<string, boolean>) => void;
  }) => (
    <>
      <ul aria-label="Filtered devices">
        {data.map((device) => <li key={device.id}>{device.name}</li>)}
      </ul>
      {data.map((device) => (
        <button
          key={`selection-${device.id}`}
          type="button"
          aria-label={`Переключить выбор ${device.name}`}
          aria-pressed={Boolean(rowSelection[device.id])}
          onClick={() => onRowSelectionChange((current) => ({
            ...current,
            [device.id]: !current[device.id],
          }))}
        />
      ))}
    </>
  ),
}));
jest.mock('@/src/features/devices/MultiStreamGrid', () => ({ MultiStreamGrid: () => null }));

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

const bulkDeleteMutation = jest.fn<Promise<{ deleted: number }>, [string[]]>();

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, 'hasPointerCapture', { configurable: true, value: () => false });
  Object.defineProperty(HTMLElement.prototype, 'setPointerCapture', { configurable: true, value: () => undefined });
  Object.defineProperty(HTMLElement.prototype, 'releasePointerCapture', { configurable: true, value: () => undefined });
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: jest.fn() });
});

beforeEach(() => {
  jest.mocked(useSearchParams).mockReturnValue(new URLSearchParams() as never);
  jest.mocked(useDevices).mockReturnValue({
    data: { items: devices, total: devices.length, page: 1, page_size: 100, pages: 1, scope_total: devices.length },
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
    refetch: jest.fn(),
  } as never);
  for (const hook of [useBulkAction, useDeleteDevice, useUpdateDevice, useBulkDeleteDevices, useBulkRevokeVpn, useChangeGroupMembership, useAssignDevicesToLocation]) {
    jest.mocked(hook).mockReturnValue({ isPending: false, mutateAsync: jest.fn() } as never);
  }
  bulkDeleteMutation.mockResolvedValue({ deleted: 2 });
  jest.mocked(useBulkDeleteDevices).mockReturnValue({ isPending: false, mutateAsync: bulkDeleteMutation } as never);
  jest.mocked(useGroups).mockReturnValue({ data: [], isLoading: false, isError: false, refetch: jest.fn() } as never);
  jest.mocked(useLocations).mockReturnValue({ data: [], isLoading: false, isError: false, refetch: jest.fn() } as never);
  jest.mocked(useGameServers).mockReturnValue({ data: [] } as never);
});

afterEach(() => jest.clearAllMocks());

it('applies the bookmarked group ID to the first server request', () => {
  const groupId = '00000000-0000-4000-8000-000000000001';
  jest.mocked(useSearchParams).mockReturnValue(new URLSearchParams({ group_id: groupId }) as never);
  render(<DevicesPage />);
  expect(useDevices).toHaveBeenCalledWith(expect.objectContaining({ group_id: groupId, page: 1, page_size: 100 }));
  expect(jest.mocked(useDevices).mock.calls.every(([params]) => params.group_id === groupId)).toBe(true);
});

it('applies the location bookmark to the first server request', () => {
  const locationId = '00000000-0000-4000-8000-000000000003';
  jest.mocked(useSearchParams).mockReturnValue(new URLSearchParams({ location_id: locationId }) as never);
  render(<DevicesPage />);
  expect(useDevices).toHaveBeenCalledWith(expect.objectContaining({ location_id: locationId, page: 1 }));
  expect(jest.mocked(useDevices).mock.calls.every(([params]) => params.location_id === locationId)).toBe(true);
});

it('resets page and selection when navigation changes the bookmarked group', () => {
  jest.mocked(useSearchParams).mockReturnValue(new URLSearchParams({ group_id: 'group-a' }) as never);
  const { rerender } = render(<DevicesPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Переключить выбор phone-online' }));
  jest.mocked(useSearchParams).mockReturnValue(new URLSearchParams({ group_id: 'group-b' }) as never);
  rerender(<DevicesPage />);
  expect(useDevices).toHaveBeenLastCalledWith(expect.objectContaining({ group_id: 'group-b', page: 1 }));
  expect(screen.getByRole('button', { name: 'Переключить выбор phone-online' })).toHaveAttribute('aria-pressed', 'false');
});

it('does not treat absent legacy metadata as a failed live-presence source', () => {
  render(<DevicesPage />);
  expect(screen.getByRole('navigation', { name: 'Страницы реестра устройств' }).querySelector('[title]')).toHaveAttribute('title', expect.stringContaining('Наличие: состояние не сообщено API'));
  expect(screen.getByText(/Статусы рассчитаны по загруженной странице/)).toBeInTheDocument();
  expect(screen.queryByText('источник live presence недоступен')).not.toBeInTheDocument();
});

it.each([true, false])('renders explicit presence metadata %s separately from unsupported metadata', (available) => {
  jest.mocked(useDevices).mockReturnValue({
    data: {
      items: devices, total: 4, page: 1, page_size: 100, pages: 1, scope_total: 4,
      presence_available: available, as_of: '2026-09-30T10:15:00Z',
      status_counts: { online: 2, busy: 1, connecting: 1, offline: 0, issues: 1 },
    },
    isLoading: false, isFetching: false, isError: false, refetch: jest.fn(),
  } as never);
  render(<DevicesPage />);
  const footer = screen.getByRole('navigation', { name: 'Страницы реестра устройств' });
  expect(footer.querySelector('[title]')).toHaveAttribute('title', expect.stringContaining(`Наличие: ${available ? 'доступен' : 'недоступен'}`));
  expect(footer.querySelector('[title]')).toHaveAttribute('title', expect.stringContaining('30.09.2026, 10:15:00 UTC'));
  expect(screen.queryByText(/Статусы рассчитаны по загруженной странице/)).not.toBeInTheDocument();
});

it('uses unknown KPI values when the first catalog request fails without a snapshot', () => {
  jest.mocked(useDevices).mockReturnValue({ data: undefined, isLoading: false, isFetching: false, isError: true, error: new Error('offline'), refetch: jest.fn() } as never);
  render(<DevicesPage />);
  const cards = screen.getByRole('region', { name: 'Состояние устройств' });
  expect(within(cards).getAllByText('—')).toHaveLength(6);
  expect(within(cards).queryByText('0')).not.toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось загрузить актуальный список устройств');
});

it('wires fleet status cards to the visible device list and clears attention through the same filter', () => {
  render(<DevicesPage />);
  const list = screen.getByRole('list', { name: 'Filtered devices' });
  const statusCards = screen.getByRole('region', { name: 'Состояние устройств' });
  const cardButton = (label: string) => within(statusCards).getByRole('button', { name: new RegExp(`^${label} `) });

  expect(within(list).getAllByRole('listitem')).toHaveLength(4);
  fireEvent.click(cardButton('В сети'));
  expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['phone-online', 'phone-busy']);

  fireEvent.click(cardButton('Подключаются'));
  expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['phone-connecting']);

  fireEvent.click(cardButton('Требуют внимания'));
  expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual(['phone-maintenance']);
  expect(cardButton('Требуют внимания')).toHaveAttribute('aria-pressed', 'true');
  expect(useDevices).toHaveBeenLastCalledWith(expect.objectContaining({ live_status: 'attention', page: 1, page_size: 100 }));
});

it('requests bounded server pages and clears stale row selection when moving pages', () => {
  jest.mocked(useDevices).mockReturnValue({
    data: { items: devices.slice(0, 1), total: 4, page: 1, page_size: 100, pages: 2, scope_total: 4 },
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
    refetch: jest.fn(),
  } as never);
  render(<DevicesPage />);

  expect(useDevices).toHaveBeenCalledWith(expect.objectContaining({ page: 1, page_size: 100 }));
  fireEvent.click(screen.getByRole('button', { name: 'Переключить выбор phone-online' }));
  fireEvent.click(screen.getByRole('button', { name: 'Следующая страница' }));
  expect(useDevices).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, page_size: 100 }));
});

it('connects visible row selection to confirmed bulk deletion and clears selection only after server success', async () => {
  render(<DevicesPage />);

  fireEvent.click(screen.getByRole('button', { name: 'Переключить выбор phone-online' }));
  fireEvent.click(screen.getByRole('button', { name: 'Переключить выбор phone-busy' }));

  const deleteButton = screen.getByRole('button', { name: 'Удалить выбранные устройства (2)' });
  expect(deleteButton).toBeEnabled();
  fireEvent.click(deleteButton);

  expect(screen.getByRole('dialog')).toHaveTextContent('Обновления и приложения на Android не затрагиваются');
  expect(bulkDeleteMutation).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: 'Убрать из каталога (2)' }));

  await waitFor(() => expect(bulkDeleteMutation).toHaveBeenCalledTimes(1));
  expect(bulkDeleteMutation).toHaveBeenCalledTimes(1);
  expect(bulkDeleteMutation).toHaveBeenCalledWith(['phone-online', 'phone-busy']);
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Удалить выбранные устройства (2)' })).not.toBeInTheDocument());
});

it('keeps the selection and reports the server error when bulk deletion is rejected', async () => {
  bulkDeleteMutation.mockRejectedValueOnce({ response: { data: { detail: 'Forbidden' } } });
  render(<DevicesPage />);

  fireEvent.click(screen.getByRole('button', { name: 'Переключить выбор phone-online' }));
  fireEvent.click(screen.getByRole('button', { name: 'Переключить выбор phone-busy' }));
  fireEvent.click(screen.getByRole('button', { name: 'Удалить выбранные устройства (2)' }));
  fireEvent.click(screen.getByRole('button', { name: 'Убрать из каталога (2)' }));

  expect(await screen.findByRole('alert')).toHaveTextContent('Forbidden');
  expect(screen.getByRole('alert')).toHaveTextContent('Выделение сохранено');
  expect(screen.getByRole('button', { name: 'Удалить выбранные устройства (2)' })).toBeEnabled();
  expect(bulkDeleteMutation).toHaveBeenCalledWith(['phone-online', 'phone-busy']);
});

it('adds by default and retains only unavailable devices after a partial group result', async () => {
  const user = userEvent.setup();
  const mutateAsync = jest.fn().mockResolvedValue([
    { device_id: 'phone-online', outcome: 'changed' },
    { device_id: 'phone-busy', outcome: 'device_not_found' },
  ]);
  jest.mocked(useChangeGroupMembership).mockReturnValue({ isPending: false, mutateAsync } as never);
  jest.mocked(useGroups).mockReturnValue({ data: [{ id: 'target', name: 'Целевая группа' }] } as never);
  render(<DevicesPage />);
  await user.click(screen.getByRole('button', { name: 'Переключить выбор phone-online' }));
  await user.click(screen.getByRole('button', { name: 'Переключить выбор phone-busy' }));
  await user.click(screen.getByRole('button', { name: 'Группа' }));
  const dialog = screen.getByRole('dialog');
  expect(dialog).toHaveTextContent('Остальные членства сохранятся');
  await user.click(within(dialog).getByRole('combobox', { name: 'Группа' }));
  await user.click(screen.getByRole('option', { name: 'Целевая группа' }));
  await user.click(within(dialog).getByRole('button', { name: 'Применить' }));
  expect(mutateAsync).toHaveBeenCalledWith({ groupId: 'target', deviceIds: ['phone-online', 'phone-busy'], operation: 'add' });
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('Изменено: 1. Без изменений: 0. Недоступны: 1.');
  expect(dialog).toHaveTextContent('Выбрано устройств: 1.');
});

it('requires confirmation for replacement and allows removal while preserving other groups', async () => {
  const user = userEvent.setup();
  const mutateAsync = jest.fn().mockResolvedValue([{ device_id: 'phone-online', outcome: 'changed' }]);
  jest.mocked(useChangeGroupMembership).mockReturnValue({ isPending: false, mutateAsync } as never);
  jest.mocked(useGroups).mockReturnValue({ data: [{ id: 'target', name: 'Целевая группа' }] } as never);
  render(<DevicesPage />);
  await user.click(screen.getByRole('button', { name: 'Переключить выбор phone-online' }));
  await user.click(screen.getByRole('button', { name: 'Группа' }));
  const dialog = screen.getByRole('dialog');
  await user.click(within(dialog).getByRole('combobox', { name: 'Группа' }));
  await user.click(screen.getByRole('option', { name: 'Целевая группа' }));
  await user.click(within(dialog).getByRole('combobox', { name: 'Действие' }));
  await user.click(screen.getByRole('option', { name: 'Заменить все группы' }));
  const apply = within(dialog).getByRole('button', { name: 'Применить' });
  expect(apply).toBeDisabled();
  await user.click(within(dialog).getByRole('checkbox', { name: /Подтверждаю удаление/ }));
  expect(apply).toBeEnabled();
  await user.click(within(dialog).getByRole('combobox', { name: 'Действие' }));
  await user.click(screen.getByRole('option', { name: 'Убрать из группы' }));
  expect(dialog).toHaveTextContent('Остальные членства сохранятся');
  await user.click(apply);
  expect(mutateAsync).toHaveBeenCalledWith({ groupId: 'target', deviceIds: ['phone-online'], operation: 'remove' });
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});
