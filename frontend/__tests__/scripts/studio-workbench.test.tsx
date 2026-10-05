import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DeviceWorkbench } from '@/src/features/scripts/studio/DeviceWorkbench';
import { api } from '@/lib/api';

const deviceId = 'b410464a-5f26-4803-a756-7840cc17b128';
const scriptId = 'fbffbc95-3c16-4f1e-8833-d77271ac1b28';
const versionId = '843654ef-e486-4b63-8e50-578a4226df44';
const taskId = 'b47cb4f2-7a92-46f2-8290-851635fe7890';
let mockTask: Record<string, unknown> | undefined;
let mockProgress: Record<string, unknown> | undefined;
let mockLogs: Record<string, unknown>[];
const mockDevice = { id: deviceId, name: 'PH025', model: 'LDPlayer', status: 'online', agent_version: '1.2.45', android_version: '9' };
jest.mock('@/lib/hooks/useDevices', () => ({ useDevices: () => ({ data: { items: [mockDevice], total: 1, pages: 1 }, isLoading: false, isError: false, isFetching: false, refetch: jest.fn() }) }));
jest.mock('@/lib/hooks/useDebounce', () => ({ useDebounce: (value: unknown) => value }));
jest.mock('@/lib/hooks/useTasks', () => ({
  useTask: () => ({ data: mockTask, isError: false }),
  useTaskProgress: (_id: unknown, enabled: boolean) => ({ data: enabled ? mockProgress : undefined }),
  useTaskLogs: () => ({ data: mockLogs, isError: false }),
  useStopTask: () => ({ isPending: false, mutate: jest.fn() }),
}));
jest.mock('@/src/features/access/Capabilities', () => ({ useCapabilities: () => ({ can: () => true }) }));
jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
jest.mock('next/link', () => function MockLink({ href, children }: { href: string; children: React.ReactNode }) { return <a href={href}>{children}</a>; });
jest.mock('@/src/features/stream/SingleDeviceStream', () => ({ SingleDeviceStream: ({ deviceId: ownedId, controlDisabled, onControlSent }: {
  deviceId: string; controlDisabled: boolean; onControlSent: (value: unknown) => void;
}) => <section aria-label="Поток выбранного Android" data-device={ownedId}>
  <button disabled={controlDisabled} onClick={() => onControlSent({ deviceId: ownedId, at: 1000, dimensions: { width: 960, height: 540 }, command: { type: 'click', x: 480, y: 270 } })}>Записать тестовый клик</button>
</section> }));

beforeEach(() => {
  jest.clearAllMocks(); mockTask = undefined; mockProgress = undefined; mockLogs = [];
  Object.defineProperty(globalThis.crypto, 'randomUUID', { configurable: true, value: () => '00000000-0000-4000-8000-000000000001' });
});
const version = { id: versionId, version: 1, dag_hash: 'a'.repeat(64) };
function openDevice() {
  const onInsert = jest.fn().mockReturnValue(true), onExecution = jest.fn();
  const view = render(<DeviceWorkbench scriptId={scriptId} version={version} name="Canary" canRun canEdit onInsert={onInsert} onExecution={onExecution} />);
  fireEvent.click(screen.getByRole('button', { name: /PH025.*LDPlayer/ }));
  return { ...view, onInsert, onExecution };
}

it('creates one real task for the explicitly selected emulator and the exact saved version', async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.post).mockReturnValue(new Promise(fulfilled => { resolve = fulfilled; }));
  openDevice();
  const run = screen.getByRole('button', { name: 'Проверить на PH025' });
  fireEvent.click(run); fireEvent.click(run);
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith('/tasks', { script_id: scriptId, device_id: deviceId, expected_current_version_id: versionId, priority: 5 }, expect.objectContaining({ timeout: 30000 }));
  expect(screen.getByRole('button', { name: 'Записать тестовый клик' })).toBeDisabled();
  resolve({ data: { id: taskId, script_id: scriptId, device_id: deviceId, script_version_id: versionId } });
  await waitFor(() => expect(screen.getByRole('link', { name: taskId })).toHaveAttribute('href', `/tasks/${taskId}`));
  expect(screen.getByRole('button', { name: 'Записать тестовый клик' })).toBeDisabled();
});

it('keeps an unconfirmed foreign receipt uncertain and never silently retries the task', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: { id: taskId, script_id: scriptId, device_id: 'another-device', script_version_id: versionId } });
  const { onExecution } = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await screen.findByRole('link', { name: 'Открыть задания' });
  expect(screen.queryByRole('link', { name: taskId })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeDisabled();
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(onExecution.mock.calls.every(([last, logs]) => last === null && logs.length === 0)).toBe(true);
});

it('does not highlight progress or logs for a task whose device ownership differs from the selected target', async () => {
  mockTask = { id: taskId, script_id: scriptId, device_id: 'foreign-device', script_version_id: versionId, status: 'running' };
  mockProgress = { current_node: 'foreign-node', nodes_done: 5, total_nodes: 8 };
  mockLogs = [{ node_id: 'foreign-node', success: true, action_type: 'tap', duration_ms: 200 }];
  jest.mocked(api.post).mockResolvedValue({ data: { id: taskId, script_id: scriptId, device_id: deviceId, script_version_id: versionId } });
  const { onExecution } = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await screen.findByRole('link', { name: taskId });
  expect(screen.queryByText(/foreign-node/)).not.toBeInTheDocument();
  expect(onExecution.mock.calls.every(([last, logs]) => last === null && logs.length === 0)).toBe(true);
  expect(screen.getByRole('button', { name: 'Записать тестовый клик' })).toBeDisabled();
});

it('inserts reviewed recorded actions only when the user explicitly transfers the stopped recording to the graph', () => {
  const { onInsert } = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Записать жесты' }));
  fireEvent.click(screen.getByRole('button', { name: 'Записать тестовый клик' }));
  expect(onInsert).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Вставить в граф' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Остановить запись' }));
  fireEvent.click(screen.getByRole('button', { name: 'Вставить в граф' }));
  expect(onInsert).toHaveBeenCalledWith([{ type: 'tap', x: 640, y: 360 }]);
  expect(api.post).not.toHaveBeenCalled();
});

it('permits an explicit corrected retry after a definitive API rejection, without automatically resubmitting', async () => {
  jest.mocked(api.post).mockRejectedValue({ isAxiosError: true, response: { status: 409, data: { detail: 'Target is busy' } } });
  openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await screen.findByRole('alert');
  await waitFor(() => expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeEnabled());
  expect(screen.queryByRole('link', { name: 'Открыть задания' })).not.toBeInTheDocument();
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('keeps a transport timeout uncertain rather than permitting a potentially duplicate task', async () => {
  jest.mocked(api.post).mockRejectedValue(new Error('Request timed out'));
  openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await screen.findByRole('link', { name: 'Открыть задания' });
  expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeDisabled();
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('requires confirmation before changing a device with an untransferred recording and respects cancellation', () => {
  const confirm = jest.spyOn(window, 'confirm').mockReturnValue(false);
  const { onInsert } = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Записать жесты' }));
  fireEvent.click(screen.getByRole('button', { name: 'Записать тестовый клик' }));
  fireEvent.click(screen.getByRole('button', { name: 'Сменить устройство' }));
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('region', { name: 'Поток выбранного Android' })).toBeInTheDocument();
  expect(onInsert).not.toHaveBeenCalled();
  expect(api.post).not.toHaveBeenCalled();
  confirm.mockRestore();
});
