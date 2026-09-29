import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { RunScriptModal } from '@/components/sphere/RunScriptModal';
import { useDevices } from '@/lib/hooks/useDevices';

const mockCreateTask = jest.fn();
const mockStartBatch = jest.fn();
const mockPush = jest.fn();

jest.mock('@/lib/hooks/useDevices', () => ({ useDevices: jest.fn() }));
jest.mock('@/lib/hooks/useGroups', () => ({ useGroups: () => ({ data: [] }) }));
jest.mock('@/lib/hooks/useTasks', () => ({ useCreateTask: () => ({ mutateAsync: mockCreateTask, isPending: false }) }));
jest.mock('@/lib/hooks/useBatches', () => ({ useStartBatch: () => ({ mutateAsync: mockStartBatch, isPending: false }) }));
jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }));
jest.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({ invalidateQueries: jest.fn() }) }));

function makeDevices(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    id: `device-${index + 1}`,
    name: `Device ${index + 1}`,
    android_id: `android-${index + 1}`,
    model: 'Emulator',
    device_model: 'Emulator',
    android_version: '14',
    tags: [],
    group_id: null,
    group_ids: [],
    group_name: null,
    location_ids: [],
    status: 'online',
    battery_level: 100,
    cpu_usage: 1,
    ram_usage_mb: 100,
    screen_on: true,
    last_seen: null,
    last_heartbeat: null,
    adb_connected: false,
    vpn_assigned: false,
    vpn_active: null,
    server_name: null,
  }));
}

function renderModal(total: number, returnedCount = total) {
  jest.mocked(useDevices).mockReturnValue({
    data: {
      items: makeDevices(returnedCount),
      total,
      page: 1,
      page_size: 1000,
      pages: Math.ceil(total / 1000),
    },
    isLoading: false,
    isError: false,
  } as never);

  return render(
    <RunScriptModal scriptId="script-1" scriptName="Smoke script" open onClose={jest.fn()} />,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  mockCreateTask.mockResolvedValue({ id: 'task-1' });
  mockStartBatch.mockResolvedValue({ id: 'batch-1' });
});

it('blocks an incomplete all-device scope instead of silently starting a partial batch', () => {
  renderModal(1001, 1000);

  expect(screen.getByRole('alert')).toHaveTextContent('1001 устройств');
  expect(screen.getByRole('button', { name: 'Запустить на 1001 уст.' })).toBeDisabled();
  expect(mockStartBatch).not.toHaveBeenCalled();
});

it('allows a complete scope at the backend batch limit', async () => {
  renderModal(1000);

  const runButton = screen.getByRole('button', { name: 'Запустить на 1000 уст.' });
  expect(runButton).toBeEnabled();
  fireEvent.click(runButton);

  await waitFor(() => expect(mockStartBatch).toHaveBeenCalledTimes(1));
  expect(mockStartBatch.mock.calls[0][0].device_ids).toHaveLength(1000);
});
