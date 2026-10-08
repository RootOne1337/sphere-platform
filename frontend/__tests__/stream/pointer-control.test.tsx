import { act, fireEvent, render } from '@testing-library/react';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { api } from '@/lib/api';

let mockRenderFrame: ((frame: VideoFrame) => void) | null = null;
let mockCapture: { captureEpoch: string; frameWidth: number; frameHeight: number } | null = null;

const TOUCH_EPOCH = '00112233-4455-6677-8899-aabbccddeeff';

jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: 'fixture-token' }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
jest.mock('@/lib/h264-decoder', () => ({
  H264Decoder: class {
    constructor(onFrame: (frame: VideoFrame) => void) {
      mockRenderFrame = onFrame;
    }
    init() {}
    destroy() {}
    reset() {}
    handleBinary() {}
    get stats() { return null; }
    get lastRenderedCapture() { return mockCapture; }
  },
}));

class MockSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: MockSocket[] = [];

  readyState = MockSocket.CONNECTING;
  bufferedAmount = 0;
  binaryType = '';
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;
  send = jest.fn();
  close = jest.fn(() => { this.readyState = MockSocket.CLOSED; });

  constructor() {
    MockSocket.instances.push(this);
  }
}

beforeEach(() => {
  jest.useFakeTimers();
  mockRenderFrame = null;
  mockCapture = null;
  jest.mocked(api.post).mockReset().mockResolvedValue({ data: { output: '' } });
  MockSocket.instances = [];
  Object.defineProperty(global, 'WebSocket', { configurable: true, value: MockSocket });
  class TestPointerEvent extends MouseEvent {
    readonly pointerId: number;
    constructor(type: string, init: MouseEventInit & { pointerId?: number } = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
    }
  }
  Object.defineProperty(window, 'PointerEvent', { configurable: true, value: TestPointerEvent });
  jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: jest.fn() } as never);
  Object.defineProperty(HTMLCanvasElement.prototype, 'setPointerCapture', {
    configurable: true,
    value: jest.fn(),
  });
});

function readyGestureFixture(enableStaticInput = false, readOnly = false) {
  const view = render(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput={enableStaticInput} readOnly={readOnly} />);
  act(() => jest.advanceTimersByTime(0));
  const socket = MockSocket.instances[0];
  socket.readyState = MockSocket.OPEN;
  act(() => socket.onopen?.(new Event('open')));
  const canvas = view.container.querySelector('canvas')!;
  jest.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
    left: 0, top: 0, right: 100, bottom: 100, width: 100, height: 100, x: 0, y: 0,
    toJSON: () => ({}),
  });
  act(() => mockRenderFrame?.({ displayWidth: 1280, displayHeight: 720 } as VideoFrame));
  const commands = () => MockSocket.instances.flatMap(instance => instance.send.mock.calls)
    .map(([message]) => JSON.parse(message as string))
    .filter(({ type }) => type === 'click' || type === 'swipe');
  const down = (pointerId: number, clientX = 50) => fireEvent.pointerDown(canvas, { clientX, clientY: 50, pointerId, button: 0 });
  const up = (pointerId: number, clientX = 50) => fireEvent.pointerUp(canvas, { clientX, clientY: 50, pointerId, button: 0 });
  return { ...view, canvas, socket, commands, down, up };
}

function readyWheel() {
  const view = readyGestureFixture(true);
  view.rerender(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput enableNavigation />);
  const wheel = (deltaY = 80, options: Record<string, unknown> = {}) => fireEvent.wheel(view.canvas, { clientX: 50, clientY: 50, deltaY, ...options });
  return { ...view, wheel };
}

function readyContinuous() {
  mockCapture = { captureEpoch: TOUCH_EPOCH, frameWidth: 1280, frameHeight: 720 };
  const view = readyWheel();
  const receive = (message: object) => act(() => view.socket.onmessage?.({ data: JSON.stringify(message) }));
  const sent = () => view.socket.send.mock.calls.map(([raw]) => JSON.parse(raw as string));
  const status = (sequence: number, status: number, stage = 'input') => receive({ type: 'continuous_input_status',
    session_id: 'viewer_session_fixture', owner: 'owner_session_fixture', capture_epoch: TOUCH_EPOCH,
    sequence, status, stage, origin: 'injector', device_uptime_ms: 100 });
  expect(sent().filter(x => x.type === 'touch_probe')).toHaveLength(1);
  receive({ type: 'touch_capability', capture_epoch: TOUCH_EPOCH, frame_width: 1280, frame_height: 720 });
  receive({ type: 'touch_session', session_id: 'viewer_session_fixture', owner: 'owner_session_fixture',
    capture_epoch: TOUCH_EPOCH, frame_width: 1280, frame_height: 720 });
  status(0, 0, 'startup');
  return { ...view, receive, sent, status };
}

it('installed canvas integration sends MOVE before UP without a second legacy swipe', () => {
  const view = readyContinuous();
  expect(view.queryByRole('button', { name: /непрерывные жесты/i })).not.toBeInTheDocument();
  expect(view.getByText(/Непрерывное управление/)).toBeInTheDocument();
  fireEvent.pointerDown(view.canvas, { clientX: 40, clientY: 50, pointerId: 1, button: 0, buttons: 1 });
  view.status(1, 1);
  fireEvent.pointerMove(view.canvas, { clientX: 60, clientY: 50, pointerId: 1, buttons: 1 });
  act(() => jest.advanceTimersByTime(16));
  view.status(2, 1);
  expect(view.sent().filter(x => x.type === 'touch_event').map(x => x.action)).toEqual([0, 2]);
  fireEvent.pointerUp(view.canvas, { clientX: 55, clientY: 50, pointerId: 1, button: 0 });
  expect(view.sent().filter(x => x.type === 'touch_event').map(x => x.action)).toEqual([0, 2, 1]);
  expect(view.commands()).toEqual([]);
  expect(view.getByRole('button', { name: 'Домой' })).toBeEnabled();
  view.unmount();
});

it('Home waits for native release and resumes continuous input only after the acknowledged key', async () => {
  const view = readyContinuous();
  fireEvent.click(view.getByRole('button', { name: 'Домой' }));
  expect(view.sent().filter(x => x.type === 'touch_close')).toHaveLength(1);
  expect(api.post).not.toHaveBeenCalled();
  await act(async () => view.status(0, 3, 'release'));
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post).toHaveBeenCalledWith('/devices/gesture-remote/shell', { command: 'input keyevent 3' }, expect.anything());
  expect(view.getByRole('button', { name: 'Домой' })).not.toBeDisabled();
  expect(view.sent().filter(x => x.type === 'touch_probe')).toHaveLength(2);
  expect(view.queryByText(/связь, фокус/)).not.toBeInTheDocument();
  view.receive({ type: 'touch_capability', capture_epoch: TOUCH_EPOCH, frame_width: 1280, frame_height: 720 });
  view.receive({ type: 'touch_session', session_id: 'viewer_session_fixture', owner: 'new_owner_session_fixture',
    capture_epoch: TOUCH_EPOCH, frame_width: 1280, frame_height: 720 });
  view.receive({ type: 'continuous_input_status', session_id: 'viewer_session_fixture', owner: 'new_owner_session_fixture',
    capture_epoch: TOUCH_EPOCH, sequence: 0, status: 0, stage: 'startup', origin: 'injector', device_uptime_ms: 150 });
  expect(view.getByText(/Непрерывное управление/)).toBeInTheDocument();
  fireEvent.pointerDown(view.canvas, { clientX: 40, clientY: 50, pointerId: 2, button: 0, buttons: 1 });
  expect(view.sent().filter(x => x.type === 'touch_event').map(x => x.action)).toEqual([0]);
  view.unmount();
});

it('blur cancels ownership and never falls back to replaying a legacy drag', () => {
  const view = readyContinuous();
  fireEvent.pointerDown(view.canvas, { clientX: 40, clientY: 50, pointerId: 1, button: 0, buttons: 1 });
  fireEvent.blur(window);
  fireEvent.pointerUp(view.canvas, { clientX: 65, clientY: 50, pointerId: 1, button: 0 });
  expect(view.sent().filter(x => x.type === 'touch_close')).toHaveLength(1);
  expect(view.commands()).toEqual([]);
  expect(view.getByRole('button', { name: 'Домой' })).toBeDisabled();
  view.unmount();
});

it('old APK probe timeout preserves video and does not invent readiness', () => {
  mockCapture = { captureEpoch: TOUCH_EPOCH, frameWidth: 1280, frameHeight: 720 };
  const view = readyWheel();
  view.down(1); view.up(1, 65);
  expect(view.commands()).toHaveLength(1);
  act(() => jest.advanceTimersByTime(6000));
  expect(view.getByText(/APK не подтвердил непрерывные жесты/)).toBeInTheDocument();
  expect(view.queryByRole('button', { name: 'Непрерывные жесты' })).not.toBeInTheDocument();
  expect(view.canvas.width).toBe(1280);
  view.unmount();
});

it('recording does not silently turn live motion into a successful reusable swipe', () => {
  const view = readyWheel();
  view.rerender(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput enableNavigation onControlSent={jest.fn()} />);
  expect(view.getByText(/Запись использует отдельные завершённые действия/)).toBeInTheDocument();
  view.unmount();
});
it('holds root inspection until this controller receives its native RELEASE3', () => {
  const view = readyContinuous();
  const inspectionReady = jest.fn();
  view.rerender(<DeviceStream deviceId="gesture-remote" enableNavigation enableStaticInput
    inspection={{ onPick: jest.fn(), bounds: null }} onInspectionControlReady={inspectionReady} />);
  expect(inspectionReady).toHaveBeenLastCalledWith(false);
  expect(view.sent().filter(x => x.type === 'touch_close')).toHaveLength(1);
  view.status(0, 3, 'release');
  expect(inspectionReady).toHaveBeenLastCalledWith(true);
  act(() => jest.advanceTimersByTime(3000));
  expect(view.queryByRole('button', { name: 'Восстановить управление' })).not.toBeInTheDocument();
  expect(view.commands()).toEqual([]);
});

it('a native unknown release cannot unlock root inspection', () => {
  const view = readyContinuous();
  const inspectionReady = jest.fn();
  view.rerender(<DeviceStream deviceId="gesture-remote" enableNavigation enableStaticInput
    inspection={{ onPick: jest.fn(), bounds: null }} onInspectionControlReady={inspectionReady} />);
  view.status(0, 4, 'release');
  expect(inspectionReady).toHaveBeenLastCalledWith(false);
  expect(inspectionReady).not.toHaveBeenCalledWith(true);
});
it('a missing inspection release stays fenced and exposes explicit recovery after a bounded wait', () => {
  const view = readyContinuous();
  const inspectionReady = jest.fn();
  view.rerender(<DeviceStream deviceId="gesture-remote" enableNavigation enableStaticInput
    inspection={{ onPick: jest.fn(), bounds: null }} onInspectionControlReady={inspectionReady} />);
  act(() => jest.advanceTimersByTime(2000));
  // A parent age/poll render creates a fresh inspection object; it must not
  // postpone the original deadline indefinitely.
  view.rerender(<DeviceStream deviceId="gesture-remote" enableNavigation enableStaticInput
    inspection={{ onPick: jest.fn(), bounds: null }} onInspectionControlReady={inspectionReady} />);
  act(() => jest.advanceTimersByTime(1000));
  expect(inspectionReady).not.toHaveBeenCalledWith(true);
  expect(view.getByRole('button', { name: 'Восстановить управление' })).toBeEnabled();
  expect(view.container.querySelector('[data-control-state]')).toHaveAttribute('data-control-failure', 'inspection_release_unknown');
  expect(view.sent().filter(x => x.type === 'touch_close')).toHaveLength(1);
  expect(api.post).not.toHaveBeenCalled();
});

it('a late capability cannot replace the path midway through an already held legacy gesture', () => {
  mockCapture = { captureEpoch: TOUCH_EPOCH, frameWidth: 1280, frameHeight: 720 };
  const view = readyWheel();
  view.down(1);
  act(() => view.socket.onmessage?.({ data: JSON.stringify({ type: 'touch_capability', capture_epoch: TOUCH_EPOCH, frame_width: 1280, frame_height: 720 }) }));
  view.up(1, 65);
  expect(view.commands()).toHaveLength(1);
  expect(view.socket.send.mock.calls.map(([raw]) => JSON.parse(raw as string)).filter(x => x.type === 'touch_open')).toHaveLength(0);
  view.unmount();
});

it('wheel uses a bounded 180ms native gesture without legacy input or a second DOWN', () => {
  const view = readyContinuous();
  view.wheel();
  view.status(1, 1);
  act(() => jest.advanceTimersByTime(16)); view.status(2, 1);
  fireEvent.pointerDown(view.canvas, { clientX: 30, clientY: 50, pointerId: 1, buttons: 1, button: 0 });
  view.wheel();
  expect(view.sent().filter(x => x.type === 'touch_event').map(x => x.action)).toEqual([0, 2]);
  act(() => jest.advanceTimersByTime(164)); view.status(3, 1);
  expect(view.sent().filter(x => x.type === 'touch_event').map(x => x.action)).toEqual([0, 2, 1]);
  expect(view.sent().filter(x => x.type === 'touch_event').map(x => [x.x, x.y])).toEqual([[640,440],[640,280],[640,280]]);
  expect(view.commands()).toEqual([]);
  view.unmount();
});

it('losing focus cancels a pending wheel terminal rather than replaying it into a new session', () => {
  const view = readyContinuous();
  view.wheel(); view.status(1, 1);
  fireEvent.blur(window);
  act(() => jest.advanceTimersByTime(200));
  expect(view.sent().filter(x => x.type === 'touch_event').map(x => x.action)).toEqual([0]);
  expect(view.sent().filter(x => x.type === 'touch_close')).toHaveLength(1);
  view.status(0, 3, 'release');
  expect(view.sent().filter(x => x.type === 'touch_probe')).toHaveLength(1);
  fireEvent.focus(window);
  expect(view.sent().filter(x => x.type === 'touch_probe')).toHaveLength(2);
  expect(view.commands()).toEqual([]);
  view.unmount();
});

it('missing native release blocks Home, reports no dispatch and provides explicit recovery', async () => {
  const view = readyContinuous();
  fireEvent.click(view.getByRole('button', { name: 'Домой' }));
  await act(async () => jest.advanceTimersByTime(3000));
  expect(api.post).not.toHaveBeenCalled();
  expect(view.getByRole('alert')).toHaveTextContent('команда не отправлена');
  expect(view.getByRole('button', { name: 'Восстановить управление' })).toBeEnabled();
  view.down(1); view.up(1,65);
  expect(view.commands()).toEqual([]);
  expect(view.sent().filter(x => x.type === 'touch_probe')).toHaveLength(1);
  view.unmount();
});

it('unknown key completion does not reopen input or silently send a legacy gesture', async () => {
  const view = readyContinuous();
  jest.mocked(api.post).mockRejectedValueOnce(new Error('timeout'));
  fireEvent.click(view.getByRole('button', { name: 'Домой' }));
  await act(async () => view.status(0,3,'release'));
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(view.getByRole('alert')).toHaveTextContent('результат не подтверждён');
  expect(view.sent().filter(x => x.type === 'touch_probe')).toHaveLength(1);
  view.down(1); view.up(1,65);
  expect(view.commands()).toEqual([]);
  expect(view.container.querySelector('[data-control-failure]')).toHaveAttribute('data-control-failure', 'discrete_result_unknown');
  view.unmount();
});

it('a native failure keeps its diagnostic cause after known release and never silently retries input', () => {
  const view = readyContinuous();
  view.status(0, 6, 'startup');
  view.status(0, 3, 'release');
  expect(view.container.querySelector('[data-control-failure]')).toHaveAttribute('data-control-failure', 'native_input_rejected_or_unknown');
  expect(view.getByRole('button', { name: 'Восстановить управление' })).toBeEnabled();
  expect(view.sent().filter(x => x.type === 'touch_probe')).toHaveLength(1);
  view.unmount();
});

it('fresh permission at the native release boundary prevents a now forbidden Home dispatch', async () => {
  const view = readyContinuous();
  fireEvent.click(view.getByRole('button', { name: 'Домой' }));
  view.rerender(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput enableNavigation readOnly />);
  await act(async () => view.status(0,3,'release'));
  expect(api.post).not.toHaveBeenCalled();
  expect(view.getByRole('alert')).toHaveTextContent('команда не отправлена');
  expect(view.sent().filter(x => x.type === 'touch_probe')).toHaveLength(1);
  view.unmount();
});

it('inspection releases native ownership and only returning to control negotiates again', () => {
  const view = readyContinuous();
  const pick = jest.fn();
  view.rerender(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput enableNavigation inspection={{onPick:pick,bounds:null}} />);
  expect(view.sent().filter(x => x.type === 'touch_close')).toHaveLength(1);
  view.status(0,3,'release');
  view.down(1); view.up(1);
  expect(pick).toHaveBeenCalledWith(640, 360, { width: 1280, height: 720 });
  expect(view.sent().filter(x => x.type === 'touch_probe')).toHaveLength(1);
  view.rerender(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput enableNavigation />);
  expect(view.sent().filter(x => x.type === 'touch_probe')).toHaveLength(2);
  expect(view.commands()).toEqual([]);
  view.unmount();
});

it('switching a ready continuous session to recording waits for release then records a discrete action', () => {
  const view = readyContinuous();
  const record = jest.fn();
  view.rerender(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput enableNavigation onControlSent={record} />);
  view.down(1); view.up(1,65);
  expect(view.commands()).toEqual([]);
  view.status(0,3,'release');
  view.down(2); view.up(2,65);
  expect(view.commands()).toHaveLength(1);
  expect(record).toHaveBeenCalledTimes(1);
  expect(view.sent().filter(x => x.type === 'touch_probe')).toHaveLength(1);
  view.wheel();
  expect(view.commands()).toHaveLength(2);
  expect(record).toHaveBeenCalledTimes(2);
  expect(view.sent().filter(x => x.type === 'touch_event')).toHaveLength(0);
  view.unmount();
});

it('switching to recording ignores a pending capability and never opens an invisible owner', () => {
  mockCapture = { captureEpoch: TOUCH_EPOCH, frameWidth: 1280, frameHeight: 720 };
  const view = readyWheel();
  view.rerender(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput enableNavigation onControlSent={jest.fn()} />);
  act(() => view.socket.onmessage?.({ data: JSON.stringify({ type:'touch_capability',capture_epoch:TOUCH_EPOCH,frame_width:1280,frame_height:720 }) }));
  expect(view.socket.send.mock.calls.map(([raw]) => JSON.parse(raw as string)).filter(x=>x.type==='touch_open')).toHaveLength(0);
  view.down(1);view.up(1,65);
  expect(view.commands()).toHaveLength(1);
  view.unmount();
});

it('maps downward and upward wheel movements to bounded swipes at native video coordinates', () => {
  const view = readyWheel();
  // Native non-passive handler cancels page scrolling on an accepted gesture.
  expect(view.wheel(80, { cancelable: true })).toBe(false);
  expect(view.commands()).toEqual([{ type: 'swipe', x1: 640, y1: 440, x2: 640, y2: 280, duration_ms: 180 }]);
  act(() => jest.advanceTimersByTime(250)); view.wheel(-80);
  expect(view.commands()[1]).toEqual({ type: 'swipe', x1: 640, y1: 280, x2: 640, y2: 440, duration_ms: 180 });
});
it('bounds horizontal wheel gestures and throttles a wheel burst without deferred replay', () => {
  const view = readyWheel(); view.wheel(0, { deltaX: 1000 }); view.wheel(80);
  expect(view.commands()).toHaveLength(1);
  expect(view.commands()[0]).toEqual({ type: 'swipe', x1: 760, y1: 360, x2: 520, y2: 360, duration_ms: 180 });
  act(() => jest.advanceTimersByTime(500)); expect(view.commands()).toHaveLength(1);
});
it.each(['inspection', 'readonly', 'closed', 'zoom', 'letterbox', 'pressure'])('does not inject wheel gestures for %s', reason => {
  const view = readyWheel();
  if (reason === 'inspection') view.rerender(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput enableNavigation inspection={{ onPick: jest.fn(), bounds: null }} />);
  if (reason === 'readonly') view.rerender(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput enableNavigation readOnly />);
  if (reason === 'closed') view.socket.readyState = MockSocket.CLOSED;
  if (reason === 'pressure') Object.assign(view.socket, { bufferedAmount: 65_537 });
  view.wheel(80, reason === 'zoom' ? { ctrlKey: true } : reason === 'letterbox' ? { clientY: 0 } : {});
  expect(view.commands()).toHaveLength(0);
});

it('read-only viewers render a picture without dispatching taps or swipes, including static frames', () => {
  const { canvas, commands, down, up } = readyGestureFixture(true, true);
  expect(canvas.width).toBe(1280);
  expect(canvas).toHaveAttribute('aria-disabled', 'true');
  down(1); up(1); down(2); up(2, 65);
  act(() => jest.advanceTimersByTime(10_000));
  down(3); up(3);
  expect(commands()).toEqual([]);
});

it('inspection picks a node without dispatching Android tap, swipe or onTap', () => {
  const view = readyGestureFixture(true);
  const onPick = jest.fn();
  const onTap = jest.fn();
  view.rerender(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput onTap={onTap}
    inspection={{ onPick, bounds: null }} />);
  view.down(1); view.up(1); view.down(2); view.up(2, 65);
  expect(onPick).toHaveBeenCalledWith(640, 360, { width: 1280, height: 720 });
  expect(onPick).toHaveBeenCalledTimes(1);
  expect(onTap).not.toHaveBeenCalled();
  expect(view.commands()).toEqual([]);
});

it('a gesture started in inspection is never replayed as Android input after a mode change', () => {
  const view = readyGestureFixture(true);
  const onPick = jest.fn();
  view.rerender(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput inspection={{ onPick, bounds: null }} />);
  view.down(1);
  view.rerender(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput />);
  view.up(1);
  expect(onPick).not.toHaveBeenCalled();
  expect(view.commands()).toEqual([]);
});

it('revoking control cancels a gesture already held over the picture', () => {
  const view = readyGestureFixture(true);
  view.down(1);
  view.rerender(<DeviceStream deviceId="gesture-remote" fit="contain" enableStaticInput readOnly />);
  view.up(1);
  expect(view.commands()).toEqual([]);
});

it.each(['invalid_parameter', 'unsupported_message'])('a rejected %s cancels the pending gesture but does not disable video or later explicit input', reason => {
  const view = readyGestureFixture(true);
  view.down(1);
  act(() => view.socket.onmessage?.({ data: JSON.stringify({ type: 'error', error: 'stream_input_invalid', reason, private: 'must-not-be-shown' }) }));
  view.up(1);
  expect(view.commands()).toEqual([]);
  expect(view.canvas).toHaveAttribute('aria-disabled', 'false');
  expect(view.getByRole('status')).toHaveTextContent('Видеопоток продолжается');
  expect(view.queryByText('must-not-be-shown')).not.toBeInTheDocument();
  view.down(2); view.up(2);
  expect(view.commands()).toEqual([{ type: 'click', x: 640, y: 360 }]);
  expect(MockSocket.instances).toHaveLength(1);
  fireEvent.click(view.getByRole('button', { name: 'Скрыть сообщение об отклонённой команде' }));
  expect(view.queryByRole('status')).not.toBeInTheDocument();
});

it('changing the selected device clears a previous rejected-command notice', () => {
  const view = readyGestureFixture(true);
  act(() => view.socket.onmessage?.({ data: JSON.stringify({ type: 'error', error: 'stream_input_invalid' }) }));
  expect(view.getByRole('status')).toHaveTextContent('Сервер отклонил некорректную команду');
  view.rerender(<DeviceStream deviceId="other-device" fit="contain" enableStaticInput />);
  expect(view.queryByText(/Сервер отклонил некорректную команду/)).not.toBeInTheDocument();
});

it('single-device static input accepts a new tap and swipe without inventing a fresh picture', () => {
  const { canvas, commands, down, up } = readyGestureFixture(true);
  act(() => jest.advanceTimersByTime(10_000));
  expect(canvas).toHaveAttribute('aria-disabled', 'false');
  expect(canvas).toHaveAttribute('aria-label', 'Экран устройства: управление по последнему кадру');
  down(1); up(1);
  down(2); up(2, 65);
  expect(commands()).toEqual([
    { type: 'click', x: 640, y: 360 },
    { type: 'swipe', x1: 640, y1: 360, x2: 832, y2: 360, duration_ms: 154 },
  ]);
});

it('static input cancels the held gesture at expiry and allows a distinct new gesture', () => {
  const { commands, down, up } = readyGestureFixture(true);
  down(1);
  act(() => jest.advanceTimersByTime(10_000));
  up(1);
  expect(commands()).toHaveLength(0);
  down(2); up(2);
  expect(commands()).toEqual([{ type: 'click', x: 640, y: 360 }]);
});

it.each(['close', 'error', 'denied', 'timeout'])('static %s still blocks pointer input', reason => {
  const { canvas, socket, commands, down, up } = readyGestureFixture(true);
  act(() => jest.advanceTimersByTime(10_000));
  act(() => {
    if (reason === 'close') socket.onclose?.({ code: 1006 });
    else if (reason === 'error') socket.onerror?.();
    else if (reason === 'timeout') jest.advanceTimersByTime(20_000);
    else socket.onmessage?.({ data: JSON.stringify({ type: 'error', error: 'stream_control_denied' }) });
  });
  down(1); up(1);
  expect(commands()).toHaveLength(0);
  expect(canvas).toHaveAttribute('aria-disabled', 'true');
});

it('static mode cannot use the old socket picture after reconnect until a new picture is drawn', () => {
  const { socket, canvas, commands, down, up } = readyGestureFixture(true);
  act(() => socket.onclose?.({ code: 1006 }));
  act(() => jest.advanceTimersByTime(1500));
  const recovered = MockSocket.instances[1];
  recovered.readyState = MockSocket.OPEN;
  act(() => recovered.onopen?.(new Event('open')));
  act(() => jest.advanceTimersByTime(10_000));
  down(1); up(1);
  expect(commands()).toHaveLength(0);
  expect(canvas).toHaveAttribute('aria-disabled', 'true');
  act(() => mockRenderFrame?.({ displayWidth: 1280, displayHeight: 720 } as VideoFrame));
  down(2); up(2);
  expect(commands()).toEqual([{ type: 'click', x: 640, y: 360 }]);
});

it('an OPEN socket is checked again at release even before a close callback rerenders', () => {
  const { socket, commands, down, up } = readyGestureFixture(true);
  act(() => jest.advanceTimersByTime(10_000));
  down(1);
  socket.readyState = MockSocket.CLOSED;
  up(1);
  expect(commands()).toHaveLength(0);
});

it('cancels a captured gesture when the decoded frame changes dimensions', () => {
  const { commands, down, up } = readyGestureFixture();
  down(1);
  act(() => mockRenderFrame?.({ displayWidth: 720, displayHeight: 1280 } as VideoFrame));
  up(1);
  expect(commands()).toHaveLength(0);
  down(2);
  up(2);
  expect(commands()).toEqual([{ type: 'click', x: 360, y: 640 }]);
});

it('ignores a different pointer release without consuming the owning gesture', () => {
  const { commands, down, up } = readyGestureFixture();
  down(1);
  up(2, 65);
  expect(commands()).toHaveLength(0);
  up(1);
  expect(commands()).toEqual([{ type: 'click', x: 640, y: 360 }]);
});

it('a second pointer cannot replace the gesture start or its owner', () => {
  const { commands, down, up } = readyGestureFixture();
  down(1);
  down(2, 65);
  up(2, 65);
  expect(commands()).toHaveLength(0);
  up(1);
  expect(commands()).toEqual([{ type: 'click', x: 640, y: 360 }]);
});

it('cancellation of another pointer cannot cancel the owning gesture', () => {
  const { canvas, commands, down, up } = readyGestureFixture();
  down(1);
  fireEvent.pointerCancel(canvas, { pointerId: 2 });
  up(1);
  expect(commands()).toEqual([{ type: 'click', x: 640, y: 360 }]);
});

it('normal changing frames with the same dimensions retain a legitimate gesture', () => {
  const { commands, down, up } = readyGestureFixture();
  down(1);
  act(() => mockRenderFrame?.({ displayWidth: 1280, displayHeight: 720 } as VideoFrame));
  up(1);
  expect(commands()).toEqual([{ type: 'click', x: 640, y: 360 }]);
});

it('loss of the owning pointer capture cancels input and permits a new gesture', () => {
  const { canvas, commands, down, up } = readyGestureFixture();
  down(1);
  fireEvent.lostPointerCapture(canvas, { pointerId: 1 });
  up(1);
  expect(commands()).toHaveLength(0);
  down(2);
  up(2);
  expect(commands()).toEqual([{ type: 'click', x: 640, y: 360 }]);
});

it('a stale frame followed by fresh video cannot revive the old held gesture', () => {
  const { commands, down, up } = readyGestureFixture();
  down(1);
  act(() => jest.advanceTimersByTime(10_000));
  act(() => mockRenderFrame?.({ displayWidth: 1280, displayHeight: 720 } as VideoFrame));
  up(1);
  expect(commands()).toHaveLength(0);
  down(2);
  up(2);
  expect(commands()).toEqual([{ type: 'click', x: 640, y: 360 }]);
});

it('a reconnected socket with fresh video cannot receive a gesture begun in the old session', () => {
  const { socket, commands, down, up } = readyGestureFixture();
  down(1);
  act(() => socket.onclose?.({ code: 1006 }));
  act(() => jest.advanceTimersByTime(1500));
  expect(MockSocket.instances).toHaveLength(2);
  const recovered = MockSocket.instances[1];
  recovered.readyState = MockSocket.OPEN;
  act(() => recovered.onopen?.(new Event('open')));
  act(() => mockRenderFrame?.({ displayWidth: 1280, displayHeight: 720 } as VideoFrame));
  up(1);
  expect(commands()).toHaveLength(0);
  down(2);
  up(2);
  expect(commands()).toEqual([{ type: 'click', x: 640, y: 360 }]);
});

afterEach(() => {
  jest.restoreAllMocks();
  jest.useRealTimers();
});

it('blocks remote input until a fresh frame, clamps captured drags, and blocks input after frames go stale', () => {
  const view = render(<DeviceStream deviceId="remote-1" fit="contain" />);
  act(() => jest.advanceTimersByTime(0));

  const socket = MockSocket.instances[0];
  socket.readyState = MockSocket.OPEN;
  act(() => socket.onopen?.(new Event('open')));

  const canvas = view.container.querySelector('canvas');
  expect(canvas).not.toBeNull();
  if (!canvas) throw new Error('Device stream canvas was not rendered');
  jest.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
    left: 10, top: 20, right: 110, bottom: 220, width: 100, height: 200, x: 10, y: 20,
    toJSON: () => ({}),
  });

  const sendPointerGesture = (endX: number, endY: number) => {
    fireEvent.pointerDown(canvas, { clientX: 60, clientY: 120, pointerId: 1, button: 0 });
    fireEvent.pointerUp(canvas, { clientX: endX, clientY: endY, pointerId: 1, button: 0 });
  };
  const remoteCommands = () => socket.send.mock.calls
    .map(([message]) => JSON.parse(message as string) as { type: string; [key: string]: unknown })
    .filter(({ type }) => type === 'click' || type === 'swipe');

  sendPointerGesture(200, 300);
  expect(remoteCommands()).toHaveLength(0);

  act(() => mockRenderFrame?.({ displayWidth: 900, displayHeight: 2000 } as VideoFrame));
  expect(canvas).toHaveAttribute('aria-disabled', 'false');
  fireEvent.pointerDown(canvas, { clientX: 11, clientY: 120, pointerId: 4, button: 0 });
  fireEvent.pointerUp(canvas, { clientX: 11, clientY: 120, pointerId: 4, button: 0 });
  expect(remoteCommands()).toHaveLength(0);

  sendPointerGesture(200, 300);
  expect(remoteCommands()).toEqual([{
    type: 'swipe', x1: 450, y1: 1000, x2: 899, y2: 1999, duration_ms: 600,
  }]);

  fireEvent.pointerDown(canvas, { clientX: 60, clientY: 120, pointerId: 2, button: 2 });
  fireEvent.pointerUp(canvas, { clientX: 60, clientY: 120, pointerId: 2, button: 2 });
  expect(remoteCommands()).toHaveLength(1);
  fireEvent.pointerDown(canvas, { clientX: 60, clientY: 120, pointerId: 3, button: 0 });
  fireEvent.pointerUp(canvas, { clientX: 60, clientY: 120, pointerId: 3, button: 0 });
  expect(remoteCommands()).toHaveLength(2);
  expect(remoteCommands()[1]).toEqual({ type: 'click', x: 450, y: 1000 });
  fireEvent.pointerDown(canvas, { clientX: 60, clientY: 120, pointerId: 5, button: 0 });
  fireEvent.pointerCancel(canvas, { pointerId: 5, button: 0 });
  fireEvent.pointerUp(canvas, { clientX: 200, clientY: 300, pointerId: 5, button: 0 });
  expect(remoteCommands()).toHaveLength(2);

  act(() => jest.advanceTimersByTime(10_000));
  sendPointerGesture(60, 120);
  expect(remoteCommands()).toHaveLength(2);
  expect(canvas).toHaveAttribute('aria-disabled', 'true');
});
