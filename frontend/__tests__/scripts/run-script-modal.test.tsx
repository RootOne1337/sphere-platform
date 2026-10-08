import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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

function renderModal(total: number, returnedCount = total, versioned = false, missingVersion = false, scriptName = 'Smoke script', initialTargetMode: 'all' | 'group' | 'select' = 'all') {
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
    <RunScriptModal scriptId="script-1" scriptName={scriptName} open onClose={jest.fn()} requireVersion={versioned} initialTargetMode={initialTargetMode}
      expectedVersion={versioned && !missingVersion ? { id: 'version-3', version: 3, dag_hash: 'a'.repeat(64) } : undefined} />,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  mockCreateTask.mockResolvedValue({ id: 'task-1' });
  mockStartBatch.mockResolvedValue({ id: 'batch-1' });
});

const versionedModal = { scriptId: 'script-1', scriptName: 'Smoke script', open: true, requireVersion: true,
  expectedVersion: { id: 'version-3', version: 3, dag_hash: 'a'.repeat(64) }, onClose: jest.fn() };

it('hides portalled controls and suspends fleet reads without resetting selection options', () => {
  const view = renderModal(1, 1, true);
  fireEvent.change(screen.getByLabelText('Приоритет (1–10)'), { target: { value: '8' } });
  view.rerender(<RunScriptModal {...versionedModal} {...({ suspended: true } as any)} />);
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(useDevices).toHaveBeenLastCalledWith(expect.any(Object), false);
  expect(mockCreateTask).not.toHaveBeenCalled();
  view.rerender(<RunScriptModal {...versionedModal} {...({ suspended: false } as any)} />);
  expect(screen.getByLabelText('Приоритет (1–10)')).toHaveValue(8);
  expect(screen.getByRole('button', { name: 'Запустить на 1 уст.' })).toBeEnabled();
});

it.each([1, 2])('retains a confirmed %i-target receipt received while hidden without navigating or resubmitting', async count => {
  let resolve!: (value: unknown) => void;
  const mutation = count === 1 ? mockCreateTask : mockStartBatch;
  mutation.mockReturnValueOnce(new Promise(done => { resolve = done; }));
  const view = renderModal(count, count, true);
  fireEvent.click(screen.getByRole('button', { name: `Запустить на ${count} уст.` }));
  view.rerender(<RunScriptModal {...versionedModal} {...({ suspended: true } as any)} />);
  await act(async () => resolve(count === 1
    ? { id: 'task-1', script_id: 'script-1', device_id: 'device-1', script_version_id: 'version-3' }
    : { id: 'batch-1', script_id: 'script-1', script_version_id: 'version-3', total: 2 }));
  expect(mockPush).not.toHaveBeenCalled();
  view.rerender(<RunScriptModal {...versionedModal} {...({ suspended: false } as any)} />);
  expect(screen.getByRole('button', { name: `Запустить на ${count} уст.` })).toBeDisabled();
  expect(screen.getByRole('link', { name: 'Открыть созданное задание' })).toHaveAttribute('href', count === 1 ? '/tasks/task-1' : '/tasks?batch_id=batch-1');
  expect(mutation).toHaveBeenCalledTimes(1);
});

it('retains unknown POST admission through portal suspension and recovery', async () => {
  let reject!: (value: unknown) => void;
  mockCreateTask.mockReturnValueOnce(new Promise((_done, failed) => { reject = failed; }));
  const view = renderModal(1, 1, true);
  fireEvent.click(screen.getByRole('button', { name: 'Запустить на 1 уст.' }));
  view.rerender(<RunScriptModal {...versionedModal} {...({ suspended: true } as any)} />);
  await act(async () => reject(new Error('Network result unknown')));
  view.rerender(<RunScriptModal {...versionedModal} {...({ suspended: false } as any)} />);
  expect(screen.getByRole('alert')).toHaveTextContent('Результат запуска неизвестен');
  expect(screen.getByRole('button', { name: 'Запустить на 1 уст.' })).toBeDisabled();
  expect(mockCreateTask).toHaveBeenCalledTimes(1);
  expect(mockPush).not.toHaveBeenCalled();
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

it('shows the inspected version/hash and verifies the direct task receipt', async () => {
  mockCreateTask.mockResolvedValue({ id: 'task-1', script_id: 'script-1', device_id: 'device-1', script_version_id: 'version-3' });
  renderModal(1, 1, true);
  expect(screen.getByText('Версия для запуска: v3')).toBeInTheDocument();
  expect(screen.getByText('SHA-256: ' + 'a'.repeat(64))).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Запустить на 1 уст.' }));
  await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/tasks/task-1'));
  expect(mockCreateTask).toHaveBeenCalledWith({ script_id: 'script-1', device_id: 'device-1', priority: 5, expected_current_version_id: 'version-3' });
});

it('carries the inspected version into the full batch admission', async () => {
  mockStartBatch.mockResolvedValue({ id: 'batch-1', script_id: 'script-1', script_version_id: 'version-3', total: 2 });
  renderModal(2, 2, true);
  fireEvent.click(screen.getByRole('button', { name: 'Запустить на 2 уст.' }));
  await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/tasks?batch_id=batch-1'));
  expect(mockStartBatch.mock.calls[0][0].expected_current_version_id).toBe('version-3');
});

it('makes a version conflict visible and does not retry admission', async () => {
  mockCreateTask.mockRejectedValue({ response: { status: 409 } });
  renderModal(1, 1, true);
  fireEvent.click(screen.getByRole('button', { name: 'Запустить на 1 уст.' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Версия сценария изменилась');
  expect(mockCreateTask).toHaveBeenCalledTimes(1);
  expect(mockPush).not.toHaveBeenCalled();
});

it('blocks another admission after an unexpected version receipt', async () => {
  mockCreateTask.mockResolvedValue({ id: 'task-1', script_id: 'script-1', device_id: 'device-1', script_version_id: 'different' });
  renderModal(1, 1, true);
  fireEvent.click(screen.getByRole('button', { name: 'Запустить на 1 уст.' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Результат запуска неизвестен');
  expect(screen.getByRole('button', { name: 'Запустить на 1 уст.' })).toBeDisabled();
  expect(screen.getByRole('link', { name: 'Открыть журнал заданий' })).toHaveAttribute('href', '/tasks');
  expect(mockPush).not.toHaveBeenCalled();
});

it('requires a known immutable version when invoked from the catalog', () => {
  renderModal(1, 1, true, true);
  expect(screen.getByRole('alert')).toHaveTextContent('Версия сценария не подтверждена');
  expect(screen.getByRole('button', { name: 'Запустить на 1 уст.' })).toBeDisabled();
});

it('preserves an API-length unbroken title while admitting the selected published version by identifiers', async () => {
  const longName = 'AndroidScenario'.repeat(17); // 255 characters: the CreateScriptRequest name limit.
  expect(longName).toHaveLength(255);
  mockCreateTask.mockResolvedValue({ id: 'task-long-name', script_id: 'script-1', device_id: 'device-1', script_version_id: 'version-3' });
  renderModal(1, 1, true, false, longName);
  expect(screen.getByRole('heading', { name: `Запустить: ${longName}` })).toBeInTheDocument();
  expect(screen.getByText('Версия для запуска: v3')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Запустить на 1 уст.' }));
  await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/tasks/task-long-name'));
  expect(mockCreateTask).toHaveBeenCalledWith({ script_id: 'script-1', device_id: 'device-1', priority: 5, expected_current_version_id: 'version-3' });
});

it('keeps generated batch names within the backend Unicode codepoint limit without changing targets or version', async () => {
  const unicodeName = '🚀'.repeat(255);
  mockStartBatch.mockResolvedValue({ id: 'batch-long-name', script_id: 'script-1', script_version_id: 'version-3', total: 2 });
  renderModal(2, 2, true, false, unicodeName);
  fireEvent.click(screen.getByRole('button', { name: 'Запустить на 2 уст.' }));
  await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/tasks?batch_id=batch-long-name'));
  const request = mockStartBatch.mock.calls[0][0];
  expect(Array.from(request.name)).toHaveLength(255);
  expect(request.name).toBe('🚀'.repeat(247) + ' — batch');
  expect(request).toMatchObject({ device_ids: ['device-1', 'device-2'], script_id: 'script-1', expected_current_version_id: 'version-3' });
});

it('makes explicit target selection observable and keeps it empty until the operator chooses a device', async () => {
  mockCreateTask.mockResolvedValue({ id: 'task-selected', script_id: 'script-1', device_id: 'device-2', script_version_id: 'version-3' });
  renderModal(2, 2, true, false, 'Explicit selection', 'select');
  expect(screen.getByRole('button', { name: 'Выбрать' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByRole('button', { name: 'Все устройства' })).toHaveAttribute('aria-pressed', 'false');
  expect(screen.getByRole('button', { name: 'Запустить' })).toBeDisabled();
  fireEvent.click(screen.getAllByRole('checkbox')[1]);
  fireEvent.click(screen.getByRole('button', { name: 'Запустить на 1 уст.' }));
  await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/tasks/task-selected'));
  expect(mockCreateTask).toHaveBeenCalledWith({ script_id: 'script-1', device_id: 'device-2', priority: 5, expected_current_version_id: 'version-3' });
  expect(mockStartBatch).not.toHaveBeenCalled();
});
