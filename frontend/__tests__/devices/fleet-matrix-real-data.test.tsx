import { render, screen } from '@testing-library/react';
import { FleetMatrix } from '@/src/features/devices/FleetMatrix';
import type { Device } from '@/lib/hooks/useDevices';

jest.mock('@tanstack/react-virtual', () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 40,
    getVirtualItems: () => Array.from({ length: count }, (_, index) => ({ index, start: index * 40 })),
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
