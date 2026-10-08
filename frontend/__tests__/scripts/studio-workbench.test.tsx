import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DeviceWorkbench } from '@/src/features/scripts/studio/DeviceWorkbench';
import { api } from '@/lib/api';
import type { AcknowledgedControl } from '@/src/features/stream/controlObservation';
import type { UiHierarchyNode, UiHierarchySnapshot } from '@/src/features/stream/uiHierarchy';

const deviceId = 'b410464a-5f26-4803-a756-7840cc17b128';
const scriptId = 'fbffbc95-3c16-4f1e-8833-d77271ac1b28';
const versionId = '843654ef-e486-4b63-8e50-578a4226df44';
const taskId = 'b47cb4f2-7a92-46f2-8290-851635fe7890';
let mockTask: Record<string, unknown> | undefined;
let mockProgress: Record<string, unknown> | undefined;
let mockLogs: Record<string, unknown>[];
let mockRetainProgressWhenDisabled = false;
let mockRecordingMode: boolean | undefined;
let mockRecordingReadyObserver: ((ready: boolean) => void) | undefined;
let mockObserve: (event: AcknowledgedControl) => void;
let mockSelectorInsert: ((node: UiHierarchyNode, snapshot: UiHierarchySnapshot) => void) | undefined;
let mockToken = 'fixture-token';
let mockSessionVersion = 1;
let mockHandoffAuto = true;
let mockHandoffId: number | undefined;
let mockHandoffObserver: ((state: 'waiting' | 'ready' | 'blocked', id: number) => void) | undefined;
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: mockToken, sessionVersion: mockSessionVersion }) }));
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
jest.mock('next/link', () => function MockLink({ href, children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) { return <a href={href} {...props}>{children}</a>; });
jest.mock('@/src/features/stream/SingleDeviceStream', () => ({ SingleDeviceStream: ({ deviceId: ownedId, controlDisabled, onControlSent, onControlCommand, onInsertSelector, recordingMode, onRecordingControlReady, taskHandoffId, onTaskHandoffState }: {
  deviceId: string; controlDisabled: boolean; recordingMode?: boolean; onRecordingControlReady?: (ready: boolean) => void; onControlSent: (value: unknown) => void; onControlCommand: typeof mockObserve; onInsertSelector: typeof mockSelectorInsert;
  taskHandoffId?: number; onTaskHandoffState?: typeof mockHandoffObserver;
}) => { const React = jest.requireActual('react');
  React.useEffect(() => { if (mockHandoffAuto && taskHandoffId !== undefined) onTaskHandoffState?.('ready', taskHandoffId); }, [taskHandoffId, onTaskHandoffState]);
  mockHandoffId=taskHandoffId; mockHandoffObserver=onTaskHandoffState;
  mockRecordingReadyObserver=onRecordingControlReady; mockRecordingMode=recordingMode; mockObserve = onControlCommand; mockSelectorInsert = onInsertSelector; return <section aria-label="Поток выбранного Android" data-device={ownedId}>
  <button disabled={controlDisabled} onClick={() => onControlSent({ deviceId: ownedId, at: 1000, dimensions: { width: 960, height: 540 }, command: { type: 'click', x: 480, y: 270 } })}>Записать тестовый клик</button>
</section>; } }));

beforeEach(() => {
  jest.clearAllMocks(); mockTask = undefined; mockProgress = undefined; mockLogs = []; mockRetainProgressWhenDisabled = false; mockToken = 'fixture-token'; mockSessionVersion = 1; mockHandoffAuto = true;
  let sequence = 0;
  Object.defineProperty(globalThis.crypto, 'randomUUID', { configurable: true, value: () => `00000000-0000-4000-8000-${String(++sequence).padStart(12, '0')}` });
});
const version = { id: versionId, version: 1, dag_hash: 'a'.repeat(64) };
function openDevice(registerCloseGuard?: (guard: ((silent?: boolean, confirmDiscard?: boolean) => boolean) | null) => void) {
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
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  expect(api.post).toHaveBeenCalledWith('/tasks', { script_id: scriptId, device_id: deviceId, expected_current_version_id: versionId, priority: 5 }, expect.objectContaining({ timeout: 30000 }));
  expect(screen.getByRole('button', { name: 'Записать тестовый клик' })).toBeDisabled();
  resolve({ data: { id: taskId, script_id: scriptId, device_id: deviceId, script_version_id: versionId } });
  await waitFor(() => expect(screen.getByRole('link', { name: taskId })).toHaveAttribute('href', `/tasks/${taskId}`));
  expect(screen.getByRole('button', { name: 'Записать тестовый клик' })).toBeDisabled();
});

it('does not create a task until the exact handoff reports ready, ignoring an obsolete receipt', async () => {
  mockHandoffAuto = false;
  jest.mocked(api.post).mockResolvedValue({ data: { id: taskId, script_id: scriptId, device_id: deviceId, script_version_id: versionId } });
  openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  const id = mockHandoffId!;
  expect(api.post).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Записать тестовый клик' })).toBeDisabled();
  await act(async () => mockHandoffObserver?.('ready', id - 1));
  expect(api.post).not.toHaveBeenCalled();
  await act(async () => mockHandoffObserver?.('ready', id));
  expect(api.post).toHaveBeenCalledTimes(1);
  await screen.findByRole('link', { name: taskId });
});

it('distinguishes failed native preparation from an uncertain task submission and permits explicit retry', async () => {
  mockHandoffAuto = false;
  openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await act(async () => mockHandoffObserver?.('blocked', mockHandoffId!));
  expect(api.post).not.toHaveBeenCalled();
  expect(screen.getByRole('alert')).toHaveTextContent('Задание не создано');
  expect(screen.queryByRole('link', { name: 'Открыть задания в новой вкладке' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeEnabled();
});

it('rechecks the saved version and run authority after waiting for native control', async () => {
  mockHandoffAuto = false;
  const view = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  const id = mockHandoffId!;
  view.rerender(<DeviceWorkbench scriptId={scriptId} version={{ ...version, id: 'changed-version' }} name="Canary" canRun={false} canEdit onInsert={view.onInsert} onExecution={view.onExecution} />);
  await act(async () => mockHandoffObserver?.('ready', id));
  expect(api.post).not.toHaveBeenCalled();
  expect(screen.getByRole('alert')).toHaveTextContent('Задание не создано');
});

it('retains a pending launch through rejected close attempts until its owned receipt arrives', async () => {
  const confirm = jest.spyOn(window, 'confirm').mockReturnValue(true);
  let resolve!: (value: unknown) => void;
  let guard: ((silent?: boolean) => boolean) | null = null;
  jest.mocked(api.post).mockReturnValue(new Promise(fulfilled => { resolve = fulfilled; }));
  try {
    openDevice(next => { guard = next; });
    fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
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
  const recovery = await screen.findByRole('link', { name: 'Открыть задания в новой вкладке' });
  expect(recovery).toHaveAttribute('target', '_blank'); expect(recovery).toHaveAttribute('rel', 'noopener noreferrer');
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
const selectorNode: UiHierarchyNode = { id: 0, parent_id: null, depth: 0, xpath: '/hierarchy/node[1]', bounds: null, attributes: {} };
const selectorSnapshot: UiHierarchySnapshot = { device_id: deviceId, snapshot_id: 'a'.repeat(32), source: 'android_uiautomator_root', width: 960, height: 540, rotation: 0,
  requested_at: '2026-10-06T00:00:00Z', completed_at: '2026-10-06T00:00:01Z', temporary_file_cleanup_confirmed: true, nodes: [selectorNode] };
it('reviews XPath in order after recorded input, without injecting Android or mutating the graph before transfer', () => {
  const { onInsert } = openDevice();
  const now = jest.spyOn(Date, 'now').mockReturnValue(2000);
  try {
    fireEvent.click(screen.getByRole('button', { name: 'Записать действия' }));
    fireEvent.click(screen.getByRole('button', { name: 'Записать тестовый клик' }));
    act(() => mockSelectorInsert!(selectorNode, selectorSnapshot));
    expect(onInsert).not.toHaveBeenCalled();
    expect(screen.getByText('В план · не выполнялся')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Записанные действия' }).children).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Вставить в граф' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Остановить запись' }));
    fireEvent.click(screen.getByLabelText('Сохранять паузы между действиями (до 60 с)'));
    fireEvent.click(screen.getByRole('button', { name: 'Вставить в граф' }));
    expect(onInsert).toHaveBeenCalledWith([{ type: 'tap', x: 640, y: 360 }, { type: 'tap_element', selector: selectorNode.xpath, strategy: 'xpath', timeout_ms: 5000 }]);
    expect(api.post).not.toHaveBeenCalled();
  } finally { now.mockRestore(); }
});
it('keeps a selector-only plan for explicit review even when recording is stopped', () => {
  const { onInsert } = openDevice();
  act(() => mockSelectorInsert!(selectorNode, selectorSnapshot));
  expect(onInsert).not.toHaveBeenCalled();
  expect(screen.getByText('В план · не выполнялся')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Вставить в граф' }));
  expect(onInsert).toHaveBeenCalledWith([{ type: 'tap_element', selector: selectorNode.xpath, strategy: 'xpath', timeout_ms: 5000 }]);
});

it('permits an explicit corrected retry after a definitive API rejection, without automatically resubmitting', async () => {
  jest.mocked(api.post).mockRejectedValue({ isAxiosError: true, response: { status: 409, data: { detail: 'Target is busy' } } });
  openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await screen.findByRole('alert');
  await waitFor(() => expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeEnabled());
  expect(screen.queryByRole('link', { name: 'Открыть задания в новой вкладке' })).not.toBeInTheDocument();
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('keeps a transport timeout uncertain rather than permitting a potentially duplicate task', async () => {
  jest.mocked(api.post).mockRejectedValue(new Error('Request timed out'));
  openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await screen.findByRole('link', { name: 'Открыть задания в новой вкладке' });
  expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeDisabled();
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('cannot bypass an unknown creation outcome by switching and reselecting the same emulator', async () => {
  const confirm = jest.spyOn(window, 'confirm').mockReturnValue(true);
  jest.mocked(api.post).mockRejectedValue(new Error('Response lost after server commit'));
  openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await screen.findByRole('link', { name: 'Открыть задания в новой вкладке' });
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
  await screen.findByRole('link', { name: 'Открыть задания в новой вкладке' });
  const before = screen.getByRole('alert').textContent;
  expect(registered).toHaveBeenCalledWith(expect.any(Function));
  expect(guard!(true)).toBe(false);
  expect(guard!(true)).toBe(false);
  expect(screen.getByRole('alert').textContent).toBe(before);
  expect(confirm).not.toHaveBeenCalled();
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  confirm.mockRestore();
});

it('bounds preparation without treating expiry as release or as an unknown server commit', async () => {
  jest.useFakeTimers();
  try {
    mockHandoffAuto = false;
    openDevice();
    fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
    expect(screen.getByRole('button', { name: 'Освобождаем Android…' })).toBeDisabled();
    await act(async () => jest.advanceTimersByTime(55_000));
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Задание не создано');
    expect(screen.queryByRole('link', { name: 'Открыть задания в новой вкладке' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeEnabled();
  } finally { jest.useRealTimers(); }
});

it('cannot submit from an obsolete auth session after its preparation callback arrives', async () => {
  mockHandoffAuto = false;
  const view = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  const oldObserver = mockHandoffObserver, id = mockHandoffId!;
  mockToken = 'changed-session';
  mockSessionVersion++;
  view.rerender(<DeviceWorkbench scriptId={scriptId} version={version} name="Canary" canRun canEdit onInsert={view.onInsert} onExecution={view.onExecution} />);
  await act(async () => oldObserver?.('ready', id));
  expect(api.post).not.toHaveBeenCalled();
});

it('rejects a token rotation during preparation without losing the explanation or creating a task', async () => {
  mockHandoffAuto = false;
  const view = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  const observer = mockHandoffObserver, id = mockHandoffId!;
  mockToken = 'rotated-token'; // refreshSession preserves the same sessionVersion.
  view.rerender(<DeviceWorkbench scriptId={scriptId} version={version} name="Canary" canRun canEdit onInsert={view.onInsert} onExecution={view.onExecution} />);
  await act(async () => observer?.('ready', id));
  expect(api.post).not.toHaveBeenCalled();
  expect(screen.getByRole('alert')).toHaveTextContent('Задание не создано');
  expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeEnabled();
});

it('retains a submitted task through same-session refresh and accepts its owned response exactly once', async () => {
  let resolve!: (value: unknown) => void;
  let guard: ((silent?: boolean) => boolean) | null = null;
  jest.mocked(api.post).mockReturnValue(new Promise(fulfilled => { resolve = fulfilled; }));
  const view = openDevice(next => { guard = next; });
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  mockToken = 'rotated-token';
  view.rerender(<DeviceWorkbench scriptId={scriptId} version={version} name="Canary" canRun canEdit onInsert={view.onInsert} onExecution={view.onExecution} registerCloseGuard={next => { guard = next; }} />);
  expect(screen.getByRole('button', { name: 'Создаём задание…' })).toBeDisabled();
  expect(guard!(true)).toBe(false);
  await act(async () => resolve({ data: { id: taskId, script_id: scriptId, device_id: deviceId, script_version_id: versionId } }));
  expect(screen.getByRole('link', { name: taskId })).toHaveAttribute('href', `/tasks/${taskId}`);
  expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeDisabled();
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('keeps an unknown launch blocked across refresh instead of enabling a potentially duplicate task', async () => {
  let guard: ((silent?: boolean) => boolean) | null = null;
  jest.mocked(api.post).mockRejectedValue(new Error('Transport timeout'));
  const view = openDevice(next => { guard = next; });
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await screen.findByRole('link', { name: 'Открыть задания в новой вкладке' });
  mockToken = 'rotated-token';
  view.rerender(<DeviceWorkbench scriptId={scriptId} version={version} name="Canary" canRun canEdit onInsert={view.onInsert} onExecution={view.onExecution} registerCloseGuard={next => { guard = next; }} />);
  expect(screen.getByRole('link', { name: 'Открыть задания в новой вкладке' })).toBeInTheDocument();
  expect(guard!(true)).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeDisabled();
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('preserves completed task reports and graph execution through an access-token refresh', async () => {
  mockTask = { id: taskId, script_id: scriptId, device_id: deviceId, script_version_id: versionId, status: 'completed' };
  mockLogs = ['start', 'wait', 'end'].map(node_id => ({ node_id, success: true, action_type: node_id === 'wait' ? 'sleep' : node_id, duration_ms: 0 }));
  jest.mocked(api.post).mockResolvedValue({ data: { id: taskId, script_id: scriptId, device_id: deviceId, script_version_id: versionId } });
  const view = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await screen.findByRole('link', { name: taskId });
  view.onExecution.mockClear();
  mockToken = 'rotated-token';
  view.rerender(<DeviceWorkbench scriptId={scriptId} version={version} name="Canary" canRun canEdit onInsert={view.onInsert} onExecution={view.onExecution} />);
  expect(screen.getByRole('link', { name: taskId })).toBeInTheDocument();
  expect(screen.getByText('completed · отчёты шагов: 3')).toBeInTheDocument();
  expect(view.onExecution).not.toHaveBeenCalledWith(null, []);
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('ignores a pending task response from a genuinely retired session', async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.post).mockReturnValue(new Promise(fulfilled => { resolve = fulfilled; }));
  const view = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  mockToken = 'another-session'; mockSessionVersion++;
  view.rerender(<DeviceWorkbench scriptId={scriptId} version={version} name="Canary" canRun canEdit onInsert={view.onInsert} onExecution={view.onExecution} />);
  await act(async () => resolve({ data: { id: taskId, script_id: scriptId, device_id: deviceId, script_version_id: versionId } }));
  expect(screen.queryByRole('link', { name: taskId })).not.toBeInTheDocument();
  expect(view.onExecution.mock.calls.every(([last, logs]) => last === null && logs.length === 0)).toBe(true);
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
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  confirm.mockRestore();
});

it('does not submit after the page becomes hidden while native preparation is pending', async () => {
  mockHandoffAuto = false;
  openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  const previous = Object.getOwnPropertyDescriptor(document, 'visibilityState');
  try {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    await act(async () => mockHandoffObserver?.('ready', mockHandoffId!));
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent('Задание не создано');
  } finally {
    if (previous) Object.defineProperty(document, 'visibilityState', previous);
    else Reflect.deleteProperty(document, 'visibilityState');
  }
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
it('lets the Studio dialog own recording confirmation without bypassing pending or unknown launches', async () => {
  const confirm = jest.spyOn(window, 'confirm').mockReturnValue(false);
  let guard: ((silent?: boolean, confirmDiscard?: boolean) => boolean) | null = null;
  openDevice(next => { guard = next; });
  fireEvent.click(screen.getByRole('button', { name: 'Записать действия' }));
  fireEvent.click(screen.getByRole('button', { name: 'Записать тестовый клик' }));
  fireEvent.click(screen.getByRole('button', { name: 'Остановить запись' }));
  expect(guard!(true)).toBe(false);
  expect(guard!(false, false)).toBe(true); expect(confirm).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Очистить запись' }));
  let reject!: (reason: Error) => void;
  jest.mocked(api.post).mockReturnValue(new Promise((_resolve, fail) => { reject = fail; }));
  fireEvent.click(screen.getByRole('button', { name: 'Проверить на PH025' }));
  act(() => { expect(guard!(false, false)).toBe(false); });
  await act(async () => reject(new Error('Unknown launch')));
  await screen.findByRole('link', { name: 'Открыть задания в новой вкладке' });
  act(() => { expect(guard!(false, false)).toBe(false); });
  expect(confirm).not.toHaveBeenCalled(); expect(api.post).toHaveBeenCalledTimes(1);
  confirm.mockRestore();
});
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
  mockSessionVersion++;
  rerender(<DeviceWorkbench scriptId={scriptId} version={version} name="Canary" canRun canEdit onInsert={onInsert} onExecution={onExecution} />);
  act(() => oldObserver({ requestId: 'old-session', input: observedInput, phase: 'confirmed', completedAt: 1800 }));
  expect(screen.queryByRole('list', { name: 'Записанные действия' })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Записать действия' })).toBeEnabled();
  expect(onInsert).not.toHaveBeenCalled();
});

it('preserves ordered recording receipts across refresh and updates the existing slot without replay', () => {
  const view = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Записать действия' }));
  act(() => mockObserve({ requestId: 'same-session', input: observedInput, phase: 'submitted' }));
  fireEvent.click(screen.getByRole('button', { name: 'Остановить запись' }));
  const observer = mockObserve;
  mockToken = 'rotated-token';
  view.rerender(<DeviceWorkbench scriptId={scriptId} version={version} name="Canary" canRun canEdit onInsert={view.onInsert} onExecution={view.onExecution} />);
  expect(screen.getByText('Ожидает APK')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Проверить на PH025' })).toBeDisabled();
  act(() => observer({ requestId: 'same-session', input: observedInput, phase: 'unknown', completedAt: 1800 }));
  expect(screen.getByText('Результат неизвестен')).toBeInTheDocument();
  expect(screen.getByRole('list', { name: 'Записанные действия' }).children).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'Вставить в граф' })).toBeDisabled();
  expect(view.onInsert).not.toHaveBeenCalled();
  expect(api.post).not.toHaveBeenCalled();
});

it('clears private recordings at a session boundary even if the token string did not change', () => {
  const view = openDevice();
  fireEvent.click(screen.getByRole('button', { name: 'Записать действия' }));
  act(() => mockObserve({ requestId: 'retired-session', input: observedInput, phase: 'submitted' }));
  const observer = mockObserve;
  mockSessionVersion++;
  view.rerender(<DeviceWorkbench scriptId={scriptId} version={version} name="Canary" canRun canEdit onInsert={view.onInsert} onExecution={view.onExecution} />);
  act(() => observer({ requestId: 'retired-session', input: observedInput, phase: 'confirmed', completedAt: 1800 }));
  expect(screen.queryByRole('list', { name: 'Записанные действия' })).not.toBeInTheDocument();
  expect(view.onInsert).not.toHaveBeenCalled();
});


it('toggles recording explicitly while keeping late Android receipt observation alive', () => {
  openDevice(); expect(mockRecordingMode).toBe(false);
  fireEvent.click(screen.getByRole('button',{name:'Записать действия'}));expect(mockRecordingMode).toBe(true);
  act(() => mockObserve({requestId:'late-mode',input:observedInput,phase:'submitted'}));
  fireEvent.click(screen.getByRole('button',{name:'Остановить запись'}));expect(mockRecordingMode).toBe(false);
  expect(screen.getByText('Ожидает APK')).toBeInTheDocument();
  act(() => mockObserve({requestId:'late-mode',input:observedInput,phase:'confirmed',completedAt:1800}));
  expect(screen.getByText('Подтверждено APK')).toBeInTheDocument();
  expect(mockRecordingMode).toBe(false);
});


it('shows preparation until the stream reports known recording readiness', () => {
  openDevice();fireEvent.click(screen.getByRole('button',{name:'Записать действия'}));
  expect(screen.getByText(/Подготавливаем запись/)).toBeInTheDocument();
  act(() => mockRecordingReadyObserver!(true));
  expect(screen.queryByText(/Подготавливаем запись/)).not.toBeInTheDocument();
  act(() => mockRecordingReadyObserver!(false));
  expect(screen.getByText(/Подготавливаем запись/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Остановить запись'}));
  expect(screen.queryByText(/Подготавливаем запись/)).not.toBeInTheDocument();
});
