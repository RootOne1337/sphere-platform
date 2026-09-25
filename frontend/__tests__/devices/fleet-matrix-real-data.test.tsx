import { render, screen } from '@testing-library/react';
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
  expect(container.textContent).not.toMatch(/\d+\s?ms/);
  expect(document.querySelectorAll('svg polyline')).toHaveLength(0);
  expect(screen.getByText('ADB linked')).toBeInTheDocument();
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
