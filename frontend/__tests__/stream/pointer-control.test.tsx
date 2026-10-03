import { act, fireEvent, render } from '@testing-library/react';
import { DeviceStream } from '@/components/sphere/DeviceStream';

let mockRenderFrame: ((frame: VideoFrame) => void) | null = null;

jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: 'fixture-token' }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
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
  },
}));

class MockSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: MockSocket[] = [];

  readyState = MockSocket.CONNECTING;
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
