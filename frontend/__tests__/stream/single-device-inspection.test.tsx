import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SingleDeviceStream } from '@/src/features/stream/SingleDeviceStream';
import { api } from '@/lib/api';

let mockPermission = true;
let mockStreamRead = true;
const mockStreamRetired = jest.fn();
let mockToken = 'fixture-token';
let mockStreamProps: Record<string, any>;
let mockInspectionReleased = true;
jest.mock('@/src/features/access/Capabilities', () => ({
  useCapabilities: () => ({ can: (permission: string) => permission === 'stream:read' ? mockStreamRead : mockPermission }), PermissionNotice: () => null,
}));
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: mockToken }) }));
jest.mock('@/lib/api', () => ({ api: { post: jest.fn() } }));
jest.mock('@/components/sphere/DeviceStream', () => ({ DeviceStream: (props: Record<string, any>) => {
  const React = jest.requireActual('react');
  React.useEffect(() => () => mockStreamRetired(), []);
  React.useEffect(() => props.onInspectionControlReady(!!props.inspection && mockInspectionReleased), [!!props.inspection]);
  mockStreamProps = props;
  return <button onClick={() => props.onFrameDimensions({ width: 960, height: 540 })}>Fixture frame</button>;
} }));
const snapshot = (deviceId = 'remote') => ({ device_id: deviceId, snapshot_id: 'a'.repeat(32), source: 'android_uiautomator_root',
  requested_at: '2026-10-03T21:00:00Z', completed_at: '2026-10-03T21:00:02Z', width: 960, height: 540, rotation: 1, temporary_file_cleanup_confirmed: true,
  nodes: [{ id: 0, parent_id: null, depth: 0, xpath: '/hierarchy/node[1]',
    bounds: { left: 100, top: 100, right: 200, bottom: 150 }, attributes: { text: '<script>safe plain text</script>', 'resource-id': 'pkg:id/ok', clickable: 'true', enabled: 'true', custom: 'retained' } }] });
beforeEach(() => { jest.clearAllMocks(); mockPermission = true; mockStreamRead = true; mockToken = 'fixture-token'; mockInspectionReleased = true; });

it('retires transport on unavailable read grants while retaining View and requiring a new frame for inspection', async () => {
  const view = render(<SingleDeviceStream deviceId="remote" captureEnabled />);
  fireEvent.click(screen.getByText('Fixture frame'));
  fireEvent.click(screen.getByRole('button', { name: 'Просмотр' }));
  mockPermission = false; mockStreamRead = false;
  view.rerender(<SingleDeviceStream deviceId="remote" captureEnabled />);
  expect(screen.queryByText('Fixture frame')).not.toBeInTheDocument();
  expect(mockStreamRetired).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('button', { name: 'Получить снимок', hidden: true })).not.toBeInTheDocument();
  mockPermission = true; mockStreamRead = true;
  view.rerender(<SingleDeviceStream deviceId="remote" captureEnabled />);
  expect(screen.getByRole('button', { name: 'Просмотр' })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'XPath-инспектор' }));
  expect(screen.getByRole('button', { name: 'Обновить дерево' })).toBeDisabled();
  expect(api.post).not.toHaveBeenCalled();
});
it('passes an execution lock reason separately from the role restriction and removes it after the lock clears', () => {
  const view = render(<SingleDeviceStream deviceId="remote" controlDisabled />);
  expect(mockStreamProps.readOnly).toBe(true);
  expect(mockStreamProps.readOnlyReason).toBe('Управление временно заблокировано на время проверки задания или при неподтверждённом результате.');
  view.rerender(<SingleDeviceStream deviceId="remote" />);
  expect(mockStreamProps.readOnly).toBe(false);
  expect(mockStreamProps.readOnlyReason).toBeUndefined();
  mockPermission = false;
  view.rerender(<SingleDeviceStream deviceId="remote" />);
  expect(mockStreamProps.readOnly).toBe(true);
  expect(mockStreamProps.readOnlyReason).toBeUndefined();
  expect(api.post).not.toHaveBeenCalled();
});
it('keeps View selected through token rotation and still waits for a newly authorized frame', () => {
  const view = render(<SingleDeviceStream deviceId="remote" />);
  fireEvent.click(screen.getByText('Fixture frame'));
  fireEvent.click(screen.getByRole('button', { name: 'Просмотр' }));
  mockToken = 'rotated-token';
  view.rerender(<SingleDeviceStream deviceId="remote" />);
  expect(screen.getByRole('button', { name: 'Просмотр' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByRole('button', { name: 'Управление' })).toHaveAttribute('aria-pressed', 'false');
  expect(mockStreamProps.readOnly).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'XPath-инспектор' }));
  expect(api.post).not.toHaveBeenCalled(); // Old-token frame cannot authorize a new root read.
  expect(screen.getByRole('button', { name: 'Обновить дерево' })).toBeDisabled();
});
it('exposes original capture below a selected stream without issuing a capture on mount', () => {
  render(<SingleDeviceStream deviceId="remote" captureEnabled />);
  expect(screen.getByText('Исходный PNG для пиксельных эталонов')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Получить снимок', hidden: true })).toBeEnabled();
  // Single-device pixels must come from the verified native endpoint, not
  // from an H.264 frame wrapped in a lossless PNG container.
  expect(mockStreamProps.enableScreenshot).toBeUndefined();
  expect(api.post).not.toHaveBeenCalled();
});
it('keeps native capture disabled without confirmed reachability, independently of a video frame', () => {
  render(<SingleDeviceStream deviceId="remote" />);
  fireEvent.click(screen.getByText('Fixture frame'));
  expect(screen.getByRole('button', { name: 'Получить снимок', hidden: true })).toBeDisabled();
  expect(api.post).not.toHaveBeenCalled();
});
it('removes native capture when device-write permission is revoked', () => {
  const view = render(<SingleDeviceStream deviceId="remote" captureEnabled />);
  mockPermission = false;
  view.rerender(<SingleDeviceStream deviceId="remote" captureEnabled />);
  expect(screen.queryByRole('button', { name: 'Получить снимок', hidden: true })).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});
function open() {
  const view = render(<SingleDeviceStream deviceId="remote" />);
  fireEvent.click(screen.getByText('Fixture frame'));
  fireEvent.click(screen.getByRole('button', { name: 'XPath-инспектор' }));
  return view;
}
async function loaded() {
  jest.mocked(api.post).mockResolvedValue({ data: snapshot() });
  const view = open();
  await screen.findByText(/1 элементов/);
  return view;
}
it('loads on inspection entry, reveals all attributes and scales highlight after a pick', async () => {
  await loaded();
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith('/devices/remote/ui-hierarchy', undefined, expect.objectContaining({ timeout: 50_000 }));
  act(() => mockStreamProps.inspection.onPick(120, 120, { width: 960, height: 540 }));
  expect(screen.getByText('/hierarchy/node[1]')).toBeInTheDocument();
  expect(screen.getByText('<script>safe plain text</script>')).toBeInTheDocument();
  expect(screen.getByText('custom')).toBeInTheDocument();
  expect(mockStreamProps.inspection.bounds).toEqual(snapshot().nodes[0].bounds);
  fireEvent.click(screen.getByRole('button', { name: 'Управление' }));
  expect(mockStreamProps.inspection).toBeUndefined();
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('does not poll root or lose the queued pick while native input release is pending', async () => {
  mockInspectionReleased = false;
  jest.mocked(api.post).mockResolvedValue({ data: snapshot() });
  open();
  expect(api.post).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Обновить дерево' })).toBeDisabled();
  act(() => mockStreamProps.inspection.onPick(120, 120, { width: 960, height: 540 }));
  expect(api.post).not.toHaveBeenCalled();
  act(() => mockStreamProps.onInspectionControlReady(true));
  await screen.findByText('/hierarchy/node[1]');
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(mockStreamProps.inspection.bounds).toEqual(snapshot().nodes[0].bounds);
});
it.each(['completed', 'failed'])('drains a %s tree read before enabling ordinary control, without abort or stale selection', async outcome => {
  let resolve!: (value: unknown) => void;
  let reject!: (reason: unknown) => void;
  jest.mocked(api.post).mockImplementation(() => new Promise((yes, no) => { resolve = yes; reject = no; }) as never);
  open();
  const signal = jest.mocked(api.post).mock.calls[0][2]?.signal;
  fireEvent.click(screen.getByRole('button', { name: 'Управление' }));
  expect(mockStreamProps.inspection).toBeUndefined();
  expect(signal?.aborted).toBe(false);
  expect(mockStreamProps.readOnly).toBe(true);
  expect(mockStreamProps.readOnlyReason).toMatch(/Завершаем чтение дерева Android/);
  await act(async () => { if (outcome === 'completed') resolve({ data: snapshot() }); else reject(new Error('known root failure')); });
  expect(mockStreamProps.readOnly).toBe(false);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.queryByText(/1 элементов/)).not.toBeInTheDocument();
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('re-enters inspection during drain without overlapping reads and then obtains a new snapshot', async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.post).mockImplementationOnce(() => new Promise(yes => { resolve = yes; }) as never)
    .mockResolvedValue({ data: snapshot() });
  open();
  fireEvent.click(screen.getByRole('button', { name: 'Управление' }));
  fireEvent.click(screen.getByRole('button', { name: 'XPath-инспектор' }));
  expect(api.post).toHaveBeenCalledTimes(1);
  await act(async () => resolve({ data: snapshot() }));
  await screen.findByText(/1 элементов/);
  expect(api.post).toHaveBeenCalledTimes(2);
});
it('an obsolete aborted request cannot release a newer read on another device', async () => {
  const resolve: Array<(value: unknown) => void> = [];
  jest.mocked(api.post).mockImplementation(() => new Promise(yes => { resolve.push(yes); }) as never);
  const view = open();
  view.rerender(<SingleDeviceStream deviceId="other" />);
  fireEvent.click(screen.getByText('Fixture frame'));
  act(() => mockStreamProps.onInspectionControlReady(true));
  expect(api.post).toHaveBeenCalledTimes(2);
  await act(async () => resolve[0]({ data: snapshot() }));
  fireEvent.click(screen.getByRole('button', { name: 'Управление' }));
  expect(mockStreamProps.readOnly).toBe(true);
  await act(async () => resolve[1]({ data: snapshot('other') }));
  expect(mockStreamProps.readOnly).toBe(false);
});
it('geometry mismatch prevents picking/highlighting and retains the explicit warning', async () => {
  await loaded();
  await act(async () => mockStreamProps.onFrameDimensions({ width: 540, height: 960 }));
  await act(async () => mockStreamProps.inspection.onPick(120, 120, { width: 540, height: 960 }));
  expect(screen.getByText(/Геометрия дерева не совпадает/)).toBeInTheDocument();
  expect(mockStreamProps.inspection.bounds).toBeNull();
  expect(screen.queryByText('/hierarchy/node[1]')).not.toBeInTheDocument();
});
it.each(['device', 'token', 'permission', 'socket'])('retires an in-flight tree on %s change', async reason => {
  let resolve: (value: unknown) => void = () => {};
  jest.mocked(api.post).mockImplementation(() => new Promise(r => { resolve = r; }) as never);
  const view = open();
  const signal = jest.mocked(api.post).mock.calls[0][2]?.signal;
  if (reason === 'device') view.rerender(<SingleDeviceStream deviceId="other" />);
  else if (reason === 'socket') act(() => mockStreamProps.onInspectionInvalidated());
  else { if (reason === 'token') mockToken = 'new-token'; else mockPermission = false; view.rerender(<SingleDeviceStream deviceId="remote" />); }
  await act(async () => { resolve({ data: snapshot() }); });
  expect(signal?.aborted).toBe(true);
  expect(screen.queryByText(/1 элементов/)).not.toBeInTheDocument();
});
it('failure and wrong-device receipt stay errors, with an explicit operator retry', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: snapshot('other') });
  open();
  expect(await screen.findByRole('alert')).toHaveTextContent(/Дерево не принадлежит/);
  expect(api.post).toHaveBeenCalledTimes(1);
  jest.mocked(api.post).mockResolvedValue({ data: snapshot() });
  fireEvent.click(screen.getByRole('button', { name: 'Обновить дерево' }));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  expect(api.post).toHaveBeenCalledTimes(2);
});
it('shows the sanitized failure stage and snapshot without discarding a valid tree or retrying root', async () => {
  await loaded();
  jest.mocked(api.post).mockRejectedValue({ response: { data: { detail: 'generic root failure' }, headers: {
    'x-sphere-ui-stage': 'dump', 'x-sphere-ui-reason': 'native_exit_nonzero',
    'x-sphere-ui-snapshot': 'b'.repeat(32), 'x-sphere-ui-native-exit-code': '1',
    'x-sphere-ui-cleanup': 'unconfirmed',
  } } });
  fireEvent.click(screen.getByRole('button', { name: 'Обновить дерево' }));
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent('Создание дампа UI Automator');
  expect(alert).toHaveTextContent('кодом 1');
  expect(alert).toHaveTextContent('b'.repeat(32));
  expect(alert).toHaveTextContent('Удаление временного файла не подтверждено');
  expect(screen.getByText(/1 элементов/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Автообновление: пауза' })).toBeInTheDocument();
  expect(api.post).toHaveBeenCalledTimes(2);
});
it('does not display arbitrary diagnostic header text or treat unknown stages as trusted diagnostics', async () => {
  jest.mocked(api.post).mockRejectedValue({ response: { data: { detail: 'compatible API error' }, headers: {
    'x-sphere-ui-stage': '<secret command>', 'x-sphere-ui-reason': 'private XML',
    'x-sphere-ui-snapshot': 'private token', 'x-sphere-ui-native-exit-code': '1 secret',
  } } });
  open();
  expect(await screen.findByRole('alert')).toHaveTextContent('compatible API error');
  expect(screen.queryByText(/secret|private/)).not.toBeInTheDocument();
});
it('received permission withdrawal disables inspection even after restoring the same device', async () => {
  const view = await loaded(); mockPermission = false;
  view.rerender(<SingleDeviceStream deviceId="remote" />);
  expect(screen.getByRole('button', { name: 'XPath-инспектор' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Обновить дерево' })).toBeDisabled();
  expect(screen.queryByText(/1 элементов/)).not.toBeInTheDocument();
});

it('expires the tree after 30 seconds without polling Android or retaining a clickable selection', async () => {
  jest.useFakeTimers();
  try {
    await loaded();
    fireEvent.click(screen.getByRole('button', { name: 'Автообновление: включено' }));
    act(() => mockStreamProps.inspection.onPick(120, 120, { width: 960, height: 540 }));
    expect(mockStreamProps.inspection.bounds).not.toBeNull();
    act(() => jest.advanceTimersByTime(31_000));
    expect(screen.getByText('Снимок устарел. Обновите дерево.')).toBeInTheDocument();
    expect(mockStreamProps.inspection.bounds).toBeNull();
    expect(screen.queryByText('/hierarchy/node[1]')).not.toBeInTheDocument();
    expect(api.post).toHaveBeenCalledTimes(1);
  } finally { jest.useRealTimers(); }
});

it('shows a valid tree with a distinct warning when Android cleanup is unconfirmed', async () => {
  jest.mocked(api.post).mockResolvedValue({ data: { ...snapshot(), temporary_file_cleanup_confirmed: false } });
  open();
  await screen.findByText(/1 элементов/);
  expect(screen.getByText(/Удаление временного файла дерева не подтверждено/)).toBeInTheDocument();
});


it('forwards explicit recording intent and readiness without dropping receipt observers', () => {
  const command=jest.fn(),sent=jest.fn(),ready=jest.fn();
  const view=render(<SingleDeviceStream deviceId="remote" recordingMode onRecordingControlReady={ready} onControlSent={sent} onControlCommand={command} />);
  expect(mockStreamProps.recordingMode).toBe(true);
  expect(mockStreamProps.onRecordingControlReady).toBe(ready);
  view.rerender(<SingleDeviceStream deviceId="remote" recordingMode={false} onRecordingControlReady={ready} onControlSent={sent} onControlCommand={command} />);
  expect(mockStreamProps.recordingMode).toBe(false);
  expect(mockStreamProps.onControlCommand).toBe(command);expect(mockStreamProps.onControlSent).toBe(sent);
});

it('drains the existing hierarchy request before task readiness without abort or new root reads', async () => {
  let resolve!: (value: unknown) => void;
  jest.mocked(api.post).mockReturnValue(new Promise(done => { resolve = done; }));
  const observed = jest.fn();
  const view = render(<SingleDeviceStream deviceId="remote" />);
  fireEvent.click(screen.getByRole('button', { name: 'Fixture frame' }));
  fireEvent.click(screen.getByRole('button', { name: 'XPath-инспектор' }));
  expect(api.post).toHaveBeenCalledTimes(1);
  const signal = jest.mocked(api.post).mock.calls[0][2]?.signal as AbortSignal;
  view.rerender(<SingleDeviceStream deviceId="remote" controlDisabled taskHandoffId={9} onTaskHandoffState={observed} />);
  act(() => mockStreamProps.onTaskHandoffState('ready', 9));
  expect(observed).toHaveBeenLastCalledWith('waiting', 9);
  expect(signal.aborted).toBe(false);
  expect(screen.getByRole('button', { name: 'XPath-инспектор' })).toBeDisabled();
  await act(async () => resolve({ data: snapshot() }));
  expect(observed).toHaveBeenLastCalledWith('ready', 9);
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(mockStreamProps.inspection).toBeUndefined();
});

it('does not convert a failed hierarchy drain into task readiness', async () => {
  let reject!: (reason: Error) => void;
  jest.mocked(api.post).mockReturnValue(new Promise((_done, failed) => { reject = failed; }));
  const observed = jest.fn();
  const view = render(<SingleDeviceStream deviceId="remote" />);
  fireEvent.click(screen.getByRole('button', { name: 'Fixture frame' }));
  fireEvent.click(screen.getByRole('button', { name: 'XPath-инспектор' }));
  view.rerender(<SingleDeviceStream deviceId="remote" controlDisabled taskHandoffId={10} onTaskHandoffState={observed} />);
  act(() => mockStreamProps.onTaskHandoffState('ready', 10));
  await act(async () => reject(new Error('Native read timeout')));
  expect(observed).toHaveBeenLastCalledWith('blocked', 10);
  expect(observed).not.toHaveBeenCalledWith('ready', 10);
});

it('does not reuse readiness from a previous launch attempt', () => {
  const observed = jest.fn();
  const view = render(<SingleDeviceStream deviceId="remote" controlDisabled taskHandoffId={11} onTaskHandoffState={observed} />);
  fireEvent.click(screen.getByRole('button', { name: 'Fixture frame' }));
  act(() => mockStreamProps.onTaskHandoffState('ready', 11));
  expect(observed).toHaveBeenLastCalledWith('ready', 11);
  view.rerender(<SingleDeviceStream deviceId="remote" controlDisabled taskHandoffId={12} onTaskHandoffState={observed} />);
  expect(observed).toHaveBeenLastCalledWith('waiting', 12);
  act(() => mockStreamProps.onTaskHandoffState('ready', 11));
  expect(observed).not.toHaveBeenCalledWith('ready', 12);
});

it('waits for an existing native capture and fails closed on its unverified result', async () => {
  let reject!: (reason: Error) => void;
  jest.mocked(api.post).mockReturnValue(new Promise((_done, failed) => { reject = failed; }));
  const observed = jest.fn();
  const view = render(<SingleDeviceStream deviceId="remote" captureEnabled />);
  fireEvent.click(screen.getByRole('button', { name: 'Fixture frame' }));
  fireEvent.click(screen.getByRole('button', { name: 'Получить снимок', hidden: true }));
  const signal = jest.mocked(api.post).mock.calls[0][2]?.signal as AbortSignal;
  view.rerender(<SingleDeviceStream deviceId="remote" captureEnabled controlDisabled taskHandoffId={13} onTaskHandoffState={observed} />);
  act(() => mockStreamProps.onTaskHandoffState('ready', 13));
  expect(signal.aborted).toBe(false);
  expect(observed).toHaveBeenLastCalledWith('waiting', 13);
  await act(async () => reject(new Error('Native capture result unknown')));
  expect(observed).toHaveBeenLastCalledWith('blocked', 13);
  expect(observed).not.toHaveBeenCalledWith('ready', 13);
});

it('does not treat permission-driven HTTP abort as native read completion for a pending task', () => {
  jest.mocked(api.post).mockReturnValue(new Promise(() => {}));
  const observed = jest.fn();
  const view = open();
  const signal = jest.mocked(api.post).mock.calls[0][2]?.signal as AbortSignal;
  view.rerender(<SingleDeviceStream deviceId="remote" controlDisabled taskHandoffId={14} onTaskHandoffState={observed} />);
  act(() => mockStreamProps.onTaskHandoffState('ready', 14));
  mockPermission = false;
  view.rerender(<SingleDeviceStream deviceId="remote" controlDisabled taskHandoffId={14} onTaskHandoffState={observed} />);
  expect(signal.aborted).toBe(true);
  expect(observed).toHaveBeenLastCalledWith('blocked', 14);
  expect(observed).not.toHaveBeenCalledWith('ready', 14);
});

it.each(['permission', 'token'] as const)('does not treat a remounted capture panel as completion of a %s-aborted native read', reason => {
  jest.mocked(api.post).mockReturnValue(new Promise(() => {}));
  const observed = jest.fn();
  const view = render(<SingleDeviceStream deviceId="remote" captureEnabled />);
  fireEvent.click(screen.getByRole('button', { name: 'Fixture frame' }));
  fireEvent.click(screen.getByRole('button', { name: 'Получить снимок', hidden: true }));
  const signal = jest.mocked(api.post).mock.calls[0][2]?.signal as AbortSignal;
  if (reason === 'permission') { mockPermission = false; mockStreamRead = false; }
  else mockToken = 'new-token';
  view.rerender(<SingleDeviceStream deviceId="remote" captureEnabled />);
  expect(signal.aborted).toBe(true);
  mockPermission = true; mockStreamRead = true;
  view.rerender(<SingleDeviceStream deviceId="remote" captureEnabled controlDisabled taskHandoffId={15} onTaskHandoffState={observed} />);
  fireEvent.click(screen.getByRole('button', { name: 'Fixture frame' }));
  act(() => mockStreamProps.onTaskHandoffState('ready', 15));
  expect(observed).toHaveBeenLastCalledWith('blocked', 15);
  expect(observed).not.toHaveBeenCalledWith('ready', 15);
  expect(api.post).toHaveBeenCalledTimes(1);
});

it('requires an explicit verified capture before clearing the native-read fence after access recovers', async () => {
  const cryptoDescriptor = Object.getOwnPropertyDescriptor(global, 'crypto');
  const decoderDescriptor = Object.getOwnPropertyDescriptor(global, 'TextDecoder');
  const createUrl = URL.createObjectURL, revokeUrl = URL.revokeObjectURL;
  Object.defineProperty(global, 'crypto', { configurable: true, value: { subtle: { digest: jest.fn().mockResolvedValue(new ArrayBuffer(32)) } } });
  Object.defineProperty(global, 'TextDecoder', { configurable: true, value: require('util').TextDecoder });
  URL.createObjectURL = jest.fn().mockReturnValue('blob:verified-recovery');
  URL.revokeObjectURL = jest.fn();
  const bytes = new ArrayBuffer(80), pixels = new Uint8Array(bytes);
  pixels.set([137, 80, 78, 71, 13, 10, 26, 10]);
  new DataView(bytes).setUint32(16, 2); new DataView(bytes).setUint32(20, 1);
  const headers = { 'content-type': 'image/png', 'x-screenshot-device-id': 'remote', 'x-screenshot-id': 'a'.repeat(32),
    'x-screenshot-sha256': '0'.repeat(64), 'x-screenshot-android-sha256': '0'.repeat(64),
    'x-screenshot-width': '2', 'x-screenshot-height': '1', 'x-screenshot-cleanup-confirmed': 'true',
    'x-screenshot-requested-at': '2026-10-04T00:00:00Z', 'x-screenshot-completed-at': '2026-10-04T00:00:01Z' };
  try {
    jest.mocked(api.post).mockReturnValueOnce(new Promise(() => {})).mockResolvedValueOnce({ data: bytes, headers });
    const observed = jest.fn();
    const view = render(<SingleDeviceStream deviceId="remote" captureEnabled />);
    fireEvent.click(screen.getByRole('button', { name: 'Fixture frame' }));
    fireEvent.click(screen.getByRole('button', { name: 'Получить снимок', hidden: true }));
    mockPermission = false; mockStreamRead = false;
    view.rerender(<SingleDeviceStream deviceId="remote" captureEnabled />);
    mockPermission = true; mockStreamRead = true;
    view.rerender(<SingleDeviceStream deviceId="remote" captureEnabled controlDisabled taskHandoffId={16} onTaskHandoffState={observed} />);
    fireEvent.click(screen.getByRole('button', { name: 'Fixture frame' }));
    act(() => mockStreamProps.onTaskHandoffState('ready', 16));
    expect(observed).toHaveBeenLastCalledWith('blocked', 16);
    expect(api.post).toHaveBeenCalledTimes(1);
    view.rerender(<SingleDeviceStream deviceId="remote" captureEnabled />);
    fireEvent.click(screen.getByRole('button', { name: 'Получить снимок', hidden: true }));
    await screen.findByRole('link', { name: 'Скачать исходный PNG', hidden: true });
    view.rerender(<SingleDeviceStream deviceId="remote" captureEnabled controlDisabled taskHandoffId={17} onTaskHandoffState={observed} />);
    act(() => mockStreamProps.onTaskHandoffState('ready', 17));
    expect(observed).toHaveBeenLastCalledWith('ready', 17);
    expect(api.post).toHaveBeenCalledTimes(2);
    view.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:verified-recovery');
  } finally {
    if (cryptoDescriptor) Object.defineProperty(global, 'crypto', cryptoDescriptor);
    if (decoderDescriptor) Object.defineProperty(global, 'TextDecoder', decoderDescriptor);
    else Reflect.deleteProperty(global, 'TextDecoder');
    URL.createObjectURL = createUrl; URL.revokeObjectURL = revokeUrl;
  }
});
