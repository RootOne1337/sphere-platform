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
  Object.defineProperty(window, 'PointerEvent', { configurable: true, value: MouseEvent });
  jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: jest.fn() } as never);
  Object.defineProperty(HTMLCanvasElement.prototype, 'setPointerCapture', {
    configurable: true,
    value: jest.fn(),
  });
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
