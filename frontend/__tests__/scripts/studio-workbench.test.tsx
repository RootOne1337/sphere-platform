import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DeviceWorkbench } from '@/src/features/scripts/studio/DeviceWorkbench';
import { api } from '@/lib/api';
import type { AcknowledgedControl } from '@/src/features/stream/controlObservation';

const deviceId = 'b410464a-5f26-4803-a756-7840cc17b128';
const scriptId = 'fbffbc95-3c16-4f1e-8833-d77271ac1b28';
const versionId = '843654ef-e486-4b63-8e50-578a4226df44';
const taskId = 'b47cb4f2-7a92-46f2-8290-851635fe7890';
let mockTask: Record<string, unknown> | undefined;
let mockProgress: Record<string, unknown> | undefined;
let mockLogs: Record<string, unknown>[];
let mockRetainProgressWhenDisabled = false;
let mockObserve: (event: AcknowledgedControl) => void;
let mockToken = 'fixture-token';
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: mockToken }) }));
const mockDevice = { id: deviceId, name: 'PH025', model: 'LDPlayer', status: 'online', agent_version: '1.2.45', android_version: '9' };
jest.mock('@/lib/hooks/useDevices', () => ({ useDevices: () => ({ data: { items: [mockDevice], total: 1, pages: 1 }, isLoading: false, isError: false, isFetching: false, refetch: jest.fn() }) }));
jest.mock('@/lib/hooks/useDebounce', () => ({ useDebounce: (value: unknown) => value }));
jest.mock('@/lib/hooks/useTasks', () => ({
  useTask: () => ({ data: mockTask, isError: false }),
  useTaskProgress: (_id: unknown, enabled: boolean) => ({ data: enabled || mockRetainProgressWhenDisabled ? mockProgress : undefined }),
  useTaskLogs: () => ({ data: mockLogs, isError: false }),
  useStopTask: () => ({ isPending: false, mutate: jest.fn() }),
}));
jest.mock('@/src/features/access/Capabilities', () => ({ useCapabilities: () => ({ can: () => true }) }));
jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
jest.mock('next/link', () => function MockLink({ href, children }: { href: string; children: React.ReactNode }) { return <a href={href}>{children}</a>; });
jest.mock('@/src/features/stream/SingleDeviceStream', () => ({ SingleDeviceStream: ({ deviceId: ownedId, controlDisabled, onControlSent, onControlCommand }: {
  deviceId: string; controlDisabled: boolean; onControlSent: (value: unknown) => void; onControlCommand: typeof mockObserve;
}) => { mockObserve = onControlCommand; return <section aria-label="Поток выбранного Android" data-device={ownedId}>
  <button disabled={controlDisabled} onClick={() => onControlSent({ deviceId: ownedId, at: 1000, dimensions: { width: 960, height: 540 }, command: { type: 'click', x: 480, y: 270 } })}>Записать тестовый клик</button>
</section>; } }));

beforeEach(() => {
  jest.clearAllMocks(); mockTask = undefined; mockProgress = undefined; mockLogs = []; mockRetainProgressWhenDisabled = false; mockToken = 'fixture-token';
  Object.defineProperty(globalThis.crypto, 'randomUUID', { configurable: true, value: () => '00000000-0000-4000-8000-000000000001' });
});
const version = { id: versionId, version: 1, dag_hash: 'a'.repeat(64) };
function openDevice(registerCloseGuard?: (guard: ((silent?: boolean) => boolean) | null) => void) {
  const onInsert = jest.fn().mockReturnValue(true), onExecution = jest.fn();
  const view = render(<DeviceWorkbench scriptId={scriptId} version={version} name="Canary" canRun canEdit onInsert={onInsert} onExecution={onExecution} registerCloseGuard={registerCloseGuard} />);
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

it('retains a pending launch through rejected close attempts until its owned receipt arrives', async () => {
  const confirm = jest.spyOn(window, 'confirm').mockReturnValue(true);
  let resolve!: (value: unknown) => void;
  let guard: ((silent?: boolean) => boolean) | null = null;
  jest.mocked(api.post).mockReturnValue(new Promise(fulfilled => { resolve = fulfilled; }));
  try {
    openDevice(next => { guard = next; });
    fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
    expect(guard!(true)).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Сменить устройство' }));
    let closed = true;
    act(() => { closed = guard!(); }); // The same guard owns the builder's close button.
    expect(closed).toBe(false);
    expect(screen.getByRole('alert')).toHaveTextContent('Дождитесь ответа');
    expect(screen.queryByRole('button', { name: /PH025.*LDPlayer/ })).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Поток выбранного Android' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Создаём задание…' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Создаём задание…' }));
    expect(confirm).not.toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledTimes(1);
    await act(async () => resolve({ data: { id: taskId, script_id: scriptId, device_id: deviceId, script_version_id: versionId } }));
    expect(screen.getByRole('link', { name: taskId })).toHaveAttribute('href', `/tasks/${taskId}`);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(api.post).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Сменить устройство' }));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: /PH025.*LDPlayer/ })).toBeInTheDocument();
  } finally { confirm.mockRestore(); }
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

it('summarizes a completed canary using received final reports instead of an outdated partial progress cache', async () => {
  mockTask = { id: taskId, script_id: scriptId, device_id: deviceId, script_version_id: versionId, status: 'completed' };
  mockProgress = { current_node: 'wait', nodes_done: 2, total_nodes: 3 };
  // TanStack retains cached data when an active-only progress query disables.
  mockRetainProgressWhenDisabled = true;
  mockLogs = ['start', 'wait', 'end'].map(node_id => ({ node_id, success: true, action_type: node_id === 'wait' ? 'sleep' : node_id, duration_ms: node_id === 'wait' ? 4002 : 0 }));
  jest.mocked(api.post).mockResolvedValue({ data: { id: taskId, script_id: scriptId, device_id: deviceId, script_version_id: versionId } });
  openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await screen.findByRole('link', { name: taskId });
  expect(screen.getByText('completed · отчёты шагов: 3')).toBeInTheDocument();
  expect(screen.queryByText(/2\/3 шагов/)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Записать тестовый клик' })).toBeEnabled();
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('inserts reviewed recorded actions only when the user explicitly transfers the stopped recording to the graph', () => {
  const { onInsert } = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Записать действия' }));
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

it('cannot bypass an unknown creation outcome by switching and reselecting the same emulator', async () => {
  const confirm = jest.spyOn(window, 'confirm').mockReturnValue(true);
  jest.mocked(api.post).mockRejectedValue(new Error('Response lost after server commit'));
  openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await screen.findByRole('link', { name: 'Открыть задания' });
  fireEvent.click(screen.getByRole('button', { name: 'Сменить устройство' }));
  expect(screen.queryByRole('button', { name: /PH025.*LDPlayer/ })).not.toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Поток выбранного Android' })).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('переключение устройства заблокировано');
  expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Записать действия' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Записать тестовый клик' })).toBeDisabled();
  expect(confirm).not.toHaveBeenCalled(); // A confirmation must not erase uncertainty.
  expect(api.post).toHaveBeenCalledTimes(1);
  confirm.mockRestore();
});

it('exposes a silent unload guard without dialogs or state changes for an unknown outcome', async () => {
  const confirm = jest.spyOn(window, 'confirm').mockReturnValue(false);
  let guard: ((silent?: boolean) => boolean) | null = null;
  const registered = jest.fn((next: typeof guard) => { guard = next; });
  jest.mocked(api.post).mockRejectedValue(new Error('Transport timeout'));
  openDevice(registered);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await screen.findByRole('link', { name: 'Открыть задания' });
  const before = screen.getByRole('alert').textContent;
  expect(registered).toHaveBeenCalledWith(expect.any(Function));
  expect(guard!(true)).toBe(false);
  expect(guard!(true)).toBe(false);
  expect(screen.getByRole('alert').textContent).toBe(before);
  expect(confirm).not.toHaveBeenCalled();
  expect(api.post).toHaveBeenCalledTimes(1);
  confirm.mockRestore();
});

it('exposes the same side-effect-free unload guard for a pending request and an uninserted recording', async () => {
  const confirm = jest.spyOn(window, 'confirm').mockReturnValue(false);
  let guard: ((silent?: boolean) => boolean) | null = null;
  openDevice(next => { guard = next; });
  expect(guard!(true)).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Записать действия' }));
  fireEvent.click(screen.getByRole('button', { name: 'Записать тестовый клик' }));
  fireEvent.click(screen.getByRole('button', { name: 'Остановить запись' }));
  expect(guard!(true)).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Очистить запись' }));
  expect(guard!(true)).toBe(true);
  jest.mocked(api.post).mockReturnValue(new Promise(() => {}));
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  expect(guard!(true)).toBe(false);
  expect(confirm).not.toHaveBeenCalled();
  expect(api.post).toHaveBeenCalledTimes(1);
  confirm.mockRestore();
});

it('requires confirmation before changing a device with an untransferred recording and respects cancellation', () => {
  const confirm = jest.spyOn(window, 'confirm').mockReturnValue(false);
  const { onInsert } = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Записать действия' }));
  fireEvent.click(screen.getByRole('button', { name: 'Записать тестовый клик' }));
  fireEvent.click(screen.getByRole('button', { name: 'Сменить устройство' }));
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('region', { name: 'Поток выбранного Android' })).toBeInTheDocument();
  expect(onInsert).not.toHaveBeenCalled();
  expect(api.post).not.toHaveBeenCalled();
  confirm.mockRestore();
});

const observedInput = { deviceId, at: 1000, dimensions: { width: 960, height: 540 }, command: { type: 'type_text' as const, text: 'private fixture' } };
it('retains a pending text action after Stop, blocks launch/close/transfer and updates the original slot on receipt', () => {
  const { onInsert } = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Записать действия' }));
  act(() => mockObserve({ requestId: 'text-one', input: observedInput, phase: 'submitted' }));
  expect(screen.getByText('Ожидает APK')).toBeInTheDocument();
  expect(screen.getByRole('list', { name: 'Записанные действия' })).not.toHaveTextContent('private fixture');
  fireEvent.click(screen.getByRole('button', { name: 'Остановить запись' }));
  expect(screen.getByRole('button', { name: 'Вставить в граф' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Очистить запись' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Сменить устройство' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Дождитесь ответа');
  act(() => mockObserve({ requestId: 'text-one', input: observedInput, phase: 'confirmed', completedAt: 1800 }));
  expect(screen.getByText('Подтверждено APK')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Вставить в граф' }));
  expect(onInsert).toHaveBeenCalledWith([{ type: 'type_text', text: 'private fixture', clear_first: false }]);
  expect(screen.queryByRole('list', { name: 'Записанные действия' })).not.toBeInTheDocument();
});
it('requires explicit removal of an unknown action before transferring the remaining gestures', () => {
  const { onInsert } = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Записать действия' }));
  fireEvent.click(screen.getByRole('button', { name: 'Записать тестовый клик' }));
  // Give entries distinct IDs, as crypto.randomUUID does in a browser.
  Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: () => 'second-entry' });
  act(() => mockObserve({ requestId: 'text-two', input: observedInput, phase: 'submitted' }));
  fireEvent.click(screen.getByRole('button', { name: 'Остановить запись' }));
  act(() => mockObserve({ requestId: 'text-two', input: observedInput, phase: 'unknown', completedAt: 1800 }));
  expect(screen.getByText('Результат неизвестен')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Вставить в граф' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Удалить действие 2' }));
  fireEvent.click(screen.getByRole('button', { name: 'Вставить в граф' }));
  expect(onInsert).toHaveBeenCalledWith([{ type: 'tap', x: 640, y: 360 }]);
});
it('also guards an unrecorded interactive command while its result is pending', () => {
  openDevice();
  act(() => mockObserve({ requestId: 'not-recorded', input: observedInput, phase: 'submitted' }));
  expect(screen.queryByRole('list', { name: 'Записанные действия' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeDisabled();
  act(() => mockObserve({ requestId: 'not-recorded', input: observedInput, phase: 'confirmed', completedAt: 1800 }));
  expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeEnabled();
});
it('discards private recordings on an auth session change and ignores the previous observer', () => {
  const { rerender, onInsert, onExecution } = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Записать действия' }));
  act(() => mockObserve({ requestId: 'old-session', input: observedInput, phase: 'submitted' }));
  const oldObserver = mockObserve;
  mockToken = 'another-session';
  rerender(<DeviceWorkbench scriptId={scriptId} version={version} name="Canary" canRun canEdit onInsert={onInsert} onExecution={onExecution} />);
  act(() => oldObserver({ requestId: 'old-session', input: observedInput, phase: 'confirmed', completedAt: 1800 }));
  expect(screen.queryByRole('list', { name: 'Записанные действия' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Записать действия' })).toBeEnabled();
  expect(onInsert).not.toHaveBeenCalled();
});
