import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FleetMatrix } from '@/src/features/devices/FleetMatrix';
import type { Device } from '@/lib/hooks/useDevices';

jest.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 48,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, start: index * 48, size: 48 })),
  }),
}));

jest.mock('@/src/features/inspector/inspectorStore', () => ({
  useInspectorStore: () => ({ openInspector: jest.fn() }),
}));

afterEach(() => jest.useRealTimers());

const device = {
  id: 'device-1',
  name: 'PH006',
  android_id: 'android-1',
  model: 'LDPlayer',
  device_model: 'LDPlayer',
  android_version: 'Android 9',
  tags: [],
  group_id: null,
  group_ids: [],
  group_name: null,
  location_ids: [],
  status: 'online',
  battery_level: 56,
  cpu_usage: 12,
  ram_usage_mb: 1024,
  screen_on: true,
  last_seen: '2026-09-23T10:00:00Z',
  last_heartbeat: '2026-09-23T10:00:00Z',
  connected_since: new Date(Date.now() - 23 * 60_000).toISOString(),
  adb_connected: true,
  vpn_assigned: false,
  vpn_active: null,
  server_name: null,
} as Device;

it('does not present generated ping or history as measurements', () => {
  const { container } = render(
    <FleetMatrix
      data={[device]}
      isLoading={false}
      rowSelection={{}}
      onRowSelectionChange={jest.fn()}
    />,
  );

  expect(screen.getByText('56%')).toBeInTheDocument();
  expect(screen.getByText(/В сети 23 мин/)).toBeInTheDocument();
  expect(screen.getByText(/heartbeat .* назад/)).toBeInTheDocument();
  expect(container.textContent).not.toMatch(/\d+\s?ms/);
  expect(document.querySelectorAll('svg polyline')).toHaveLength(0);
  expect(screen.queryByText('ADB linked')).not.toBeInTheDocument();
});

it('shows explicit fallbacks for metadata the Android agent has not reported', () => {
  const { container } = render(
    <FleetMatrix
      data={[{ ...device, model: null, android_version: null, agent_version: null } as Device]}
      isLoading={false}
      rowSelection={{}}
      onRowSelectionChange={jest.fn()}
    />,
  );

  expect(screen.getByText('Модель не сообщена')).toBeInTheDocument();
  expect(screen.getByText('Android не сообщён')).toBeInTheDocument();
  expect(screen.getByText('Агент не сообщил версию')).toBeInTheDocument();
  expect(container.textContent).not.toMatch(/\b(undefined|null)\b/);
});

it('refreshes heartbeat age on the visible connection clock', () => {
  jest.useFakeTimers();
  jest.setSystemTime(new Date('2026-09-23T10:00:00Z'));

  render(
    <FleetMatrix
      data={[{ ...device, connected_since: '2026-09-23T09:00:00Z', last_heartbeat: '2026-09-23T10:00:00Z' } as Device]}
      isLoading={false}
      rowSelection={{}}
      onRowSelectionChange={jest.fn()}
    />,
  );

  expect(screen.getByText(/heartbeat 0 с назад/)).toBeInTheDocument();
  act(() => jest.advanceTimersByTime(15_000));
  expect(screen.getByText(/heartbeat 15 с назад/)).toBeInTheDocument();
});

it('does not invent an uptime when the server has no confirmed session timestamp', () => {
  const { rerender } = render(
    <FleetMatrix
      data={[{ ...device, connected_since: null, last_heartbeat: null } as Device]}
      isLoading={false}
      rowSelection={{}}
      onRowSelectionChange={jest.fn()}
    />,
  );

  expect(screen.getByText('Начало сессии не сообщено')).toBeInTheDocument();
  expect(screen.getByText(/Контакт .* назад/)).toBeInTheDocument();
  expect(screen.queryByText(/В сети .* мин/)).not.toBeInTheDocument();

  rerender(
    <FleetMatrix
      data={[{ ...device, status: 'connecting', connected_since: null } as Device]}
      isLoading={false}
      rowSelection={{}}
      onRowSelectionChange={jest.fn()}
    />,
  );
  expect(screen.getByText('Ожидание первого heartbeat')).toBeInTheDocument();
});

it('shows a real heartbeat without last_seen and keeps the agent version in its own column', () => {
  jest.useFakeTimers();
  jest.setSystemTime(new Date('2026-09-30T10:00:30Z'));
  render(<FleetMatrix data={[{ ...device, last_seen: null, last_heartbeat: '2026-09-30T10:00:00Z', agent_version: '1.2.34-dev' }]} isLoading={false} rowSelection={{}} onRowSelectionChange={jest.fn()} />);
  expect(screen.getByText('heartbeat 30 с назад')).toBeInTheDocument();
  expect(screen.getByText('30.09.2026, 10:00:00 UTC')).toBeInTheDocument();
  expect(screen.getByText('Agent 1.2.34-dev')).toBeInTheDocument();
  expect(screen.getByRole('columnheader', { name: /Android/ })).toBeInTheDocument();
  expect(screen.queryByText('Android Android 9')).not.toBeInTheDocument();
});

it('does not format invalid or far-future timestamps as real heartbeat evidence', () => {
  jest.useFakeTimers();
  jest.setSystemTime(new Date('2026-09-30T10:00:00Z'));
  const { container } = render(<FleetMatrix data={[{ ...device, connected_since: 'bad-date', last_heartbeat: '2026-10-01T10:00:00Z', last_seen: 'bad-date' }]} isLoading={false} rowSelection={{}} onRowSelectionChange={jest.fn()} />);
  expect(screen.getByText('Нет данных о сигнале')).toBeInTheDocument();
  expect(screen.getByText('Начало сессии не сообщено')).toBeInTheDocument();
  expect(container.textContent).not.toContain('Invalid Date');
});

it('keeps optional access columns available through the column menu', async () => {
  const user = userEvent.setup();
  render(<FleetMatrix data={[device]} isLoading={false} rowSelection={{}} onRowSelectionChange={jest.fn()} />);
  expect(screen.queryByText('ADB linked')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Настроить видимые колонки' }));
  await user.click(await screen.findByRole('menuitemcheckbox', { name: 'Доступ' }));
  expect(screen.getByText('ADB linked')).toBeInTheDocument();
});

it('keeps device changes and deletion under separate menu permissions', async () => {
  const user = userEvent.setup();
  const onDeviceAction = jest.fn();
  render(<FleetMatrix data={[device]} isLoading={false} rowSelection={{}} onRowSelectionChange={jest.fn()} onDeviceAction={onDeviceAction} canDeviceAction={action => action !== 'delete'} />);
  await user.click(screen.getByRole('button', { name: 'Действия устройства PH006' }));
  expect(screen.getByRole('menuitem', { name: 'Переименовать' })).not.toHaveAttribute('aria-disabled', 'true');
  expect(screen.getByRole('menuitem', { name: 'Удалить' })).toHaveAttribute('aria-disabled', 'true');
  await user.click(screen.getByRole('menuitem', { name: 'Удалить' }));
  expect(onDeviceAction).not.toHaveBeenCalled();
  await user.click(screen.getByRole('menuitem', { name: 'Переименовать' }));
  expect(onDeviceAction).toHaveBeenCalledWith('device-1', 'rename');
});

it('withdraws menu commands when authority changes while the menu is open', async () => {
  const user = userEvent.setup();
  const onDeviceAction = jest.fn();
  const base = { data: [device], isLoading: false, rowSelection: {}, onRowSelectionChange: jest.fn(), onDeviceAction };
  const view = render(<FleetMatrix {...base} canDeviceAction={() => true} />);
  await user.click(screen.getByRole('button', { name: 'Действия устройства PH006' }));
  view.rerender(<FleetMatrix {...base} canDeviceAction={() => false} />);
  // Replacing the memoized table cell retires its former popup. Reopening must
  // consult the new permission decision instead of recovering old menu authority.
  expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Действия устройства PH006' }));
  for (const name of ['Переименовать', 'В группу', 'В локацию', 'Игровой сервер', 'Удалить']) {
    expect(screen.getByRole('menuitem', { name })).toHaveAttribute('aria-disabled', 'true');
  }
  await user.click(screen.getByRole('menuitem', { name: 'Переименовать' }));
  expect(onDeviceAction).not.toHaveBeenCalled();
});

it('offers no mutation in a menu without an explicit permission decision', async () => {
  const user = userEvent.setup();
  const onDeviceAction = jest.fn();
  render(<FleetMatrix data={[device]} isLoading={false} rowSelection={{}} onRowSelectionChange={jest.fn()} onDeviceAction={onDeviceAction} />);
  await user.click(screen.getByRole('button', { name: 'Действия устройства PH006' }));
  for (const item of screen.getAllByRole('menuitem')) expect(item).toHaveAttribute('aria-disabled', 'true');
  expect(onDeviceAction).not.toHaveBeenCalled();
});

it('shows an honest empty state when the registry has no devices', () => {
  render(
    <FleetMatrix
      data={[]}
      isLoading={false}
      rowSelection={{}}
      onRowSelectionChange={jest.fn()}
    />,
  );

  expect(screen.getByRole('status')).toHaveTextContent('Устройства не найдены');
  expect(screen.getByRole('status')).toHaveTextContent('первого heartbeat');
});

it('preserves device column widths so narrow screens can scroll the fleet table horizontally', () => {
  const { container } = render(
    <FleetMatrix
      data={[device]}
      isLoading={false}
      rowSelection={{}}
      onRowSelectionChange={jest.fn()}
    />,
  );

  const row = container.querySelector('[role="rowgroup"] [role="row"]');
  const cells = row?.querySelectorAll('[role="cell"]');

  expect(row).toHaveClass('min-w-max');
  expect(cells?.length).toBeGreaterThan(0);
  expect(Array.from(cells ?? []).every((cell) => cell.classList.contains('shrink-0'))).toBe(true);
  expect(screen.getByRole('button', { name: 'Открыть устройство PH006' })).toBeInTheDocument();
});
