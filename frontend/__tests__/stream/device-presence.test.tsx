import { fireEvent, render, screen } from '@testing-library/react';
import FleetStreamPage from '@/app/(dashboard)/stream/page';
import type { Device } from '@/lib/hooks/useDevices';

let mockDevices: Device[];
jest.mock('@/lib/hooks/useDevices', () => ({
  useDevices: (params: { status?: string }) => {
    // The real API filters offline rows out of an online-only query.
    const items = mockDevices.filter(d => !params.status || d.status === params.status);
    return { data: { items, total: items.length } };
  },
}));
jest.mock('@/lib/hooks/useGroups', () => ({ useGroups: () => ({ data: [] }) }));
jest.mock('@/lib/hooks/useLocations', () => ({ useLocations: () => ({ data: [] }) }));
jest.mock('@/components/sphere/DeviceStream', () => ({
  DeviceStream: ({ deviceId }: { deviceId: string }) => <div>Live {deviceId}</div>,
}));

beforeEach(() => {
  mockDevices = [
    { id: 'a', name: 'Agent A', status: 'online', group_ids: [], location_ids: [] },
    { id: 'b', name: 'Agent B', status: 'online', group_ids: [], location_ids: [] },
  ] as unknown as Device[];
});

it('keeps an offline device visible, hides stale video, and resumes the selected stream on recovery', () => {
  const view = render(<FleetStreamPage />);
  fireEvent.click(screen.getAllByRole('button', { name: 'Start' })[0]);
  expect(screen.getByText('Live a')).toBeInTheDocument();
  mockDevices = mockDevices.map(d => d.id === 'a' ? { ...d, status: 'offline' } : d);
  view.rerender(<FleetStreamPage />);
  expect(screen.getByText('Agent A')).toBeInTheDocument();
  expect(screen.getByText('Agent B')).toBeInTheDocument();
  expect(screen.queryByText('Live a')).not.toBeInTheDocument();
  expect(screen.getByText(/Связь потеряна/)).toBeInTheDocument();
  mockDevices = mockDevices.map(d => ({ ...d, status: 'online' }));
  view.rerender(<FleetStreamPage />);
  expect(screen.getByText('Live a')).toBeInTheDocument();
  expect(screen.queryByText(/Связь потеряна/)).not.toBeInTheDocument();
});

it('shows devices already offline at page load without offering an unavailable start', () => {
  mockDevices = [{ ...mockDevices[0], status: 'offline' }];
  render(<FleetStreamPage />);
  expect(screen.getByText('Agent A')).toBeInTheDocument();
  expect(screen.getByText(/0 онлайн/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Start' })).toBeDisabled();
});

it('honors Stop while offline instead of resuming a cancelled viewer', () => {
  const view = render(<FleetStreamPage />);
  fireEvent.click(screen.getAllByRole('button', { name: 'Start' })[0]);
  mockDevices = mockDevices.map(d => d.id === 'a' ? { ...d, status: 'offline' } : d);
  view.rerender(<FleetStreamPage />);
  fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
  mockDevices = mockDevices.map(d => ({ ...d, status: 'online' }));
  view.rerender(<FleetStreamPage />);
  expect(screen.queryByText('Live a')).not.toBeInTheDocument();
});
