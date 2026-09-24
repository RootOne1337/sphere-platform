import { act, render, screen } from '@testing-library/react';
import { DeviceStream } from '@/components/sphere/DeviceStream';

jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: 'fixture-token' }) }));
let mockRecovery: (() => void) | undefined;
let mockFrame: ((frame: unknown) => void) | undefined;
const mockReset = jest.fn();
jest.mock('@/lib/h264-decoder', () => ({ H264Decoder: class {
  constructor(frame: (value: unknown) => void, recover: () => void) { mockFrame = frame; mockRecovery = recover; }
  init() {} destroy() {} reset() { mockReset(); } handleBinary() {}
} }));

class Socket {
  static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
  static instances: Socket[] = [];
  readyState = Socket.CONNECTING;
  binaryType = '';
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  send = jest.fn();
  close = jest.fn(() => { this.readyState = Socket.CLOSED; this.onclose?.({ code: 1000 }); });
  constructor(_url: string) { Socket.instances.push(this); }
  open() { this.readyState = Socket.OPEN; this.onopen?.(); }
  message(data: string) { this.onmessage?.({ data }); }
  fail(code = 1006) { this.readyState = Socket.CLOSED; this.onclose?.({ code }); }
}

function advance(ms: number) { act(() => { jest.advanceTimersByTime(ms); }); }
beforeEach(() => {
  jest.useFakeTimers(); Socket.instances = []; mockReset.mockClear();
  Object.defineProperty(global, 'WebSocket', { configurable: true, value: Socket });
  jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: jest.fn() } as never);
  jest.spyOn(Math, 'random').mockReturnValue(0.5);
});
afterEach(() => { jest.restoreAllMocks(); jest.useRealTimers(); });

it('increases the delay across failed sockets instead of retrying every 500ms', () => {
  const view = render(<DeviceStream deviceId="fixture" />); advance(0);
  act(() => Socket.instances[0].fail()); advance(500);
  expect(Socket.instances).toHaveLength(2);
  act(() => Socket.instances[1].fail()); advance(500);
  expect(Socket.instances).toHaveLength(2);
  advance(500); expect(Socket.instances).toHaveLength(3); view.unmount();
});

it('reconnects after a server normal-close without requiring F5', () => {
  const view = render(<DeviceStream deviceId="fixture" />); advance(0);
  act(() => { Socket.instances[0].open(); Socket.instances[0].fail(1000); });
  advance(500); expect(Socket.instances).toHaveLength(2); view.unmount();
});

it('retries the initial keyframe request when the viewer connects but no image arrives', () => {
  const view = render(<DeviceStream deviceId="fixture" />); advance(0);
  act(() => Socket.instances[0].open());
  expect(screen.getByRole('status')).toHaveTextContent('Ожидание видеокадра…');
  advance(1100);
  expect(Socket.instances[0].send).toHaveBeenLastCalledWith('{"type":"request_keyframe"}');
  advance(2000);
  expect(Socket.instances[0].send).toHaveBeenCalledTimes(3); // auth + two keyframe requests
  advance(4999);
  expect(Socket.instances[0].send).toHaveBeenCalledTimes(3);
  advance(1);
  expect(Socket.instances[0].send).toHaveBeenCalledTimes(4); // next request backs off to 5 s
  act(() => mockFrame?.({ displayWidth: 100, displayHeight: 200 }));
  advance(40_000);
  expect(Socket.instances[0].send).toHaveBeenCalledTimes(4);
  view.unmount();
});

it('shows the server control error instead of hiding it behind an endless frame wait', () => {
  const view = render(<DeviceStream deviceId="fixture" />); advance(0);
  act(() => Socket.instances[0].open());
  act(() => Socket.instances[0].message(JSON.stringify({
    type: 'error', error: 'stream_control_unavailable',
  })));
  expect(screen.getByRole('status')).toHaveTextContent(
    'Сервер не смог передать запрос видеопотока Android-агенту.',
  );
  view.unmount();
});

it('requests a fresh key frame after codec cooldown, stops after output, and clears timers on unmount', () => {
  const view = render(<DeviceStream deviceId="fixture" />); advance(0);
  act(() => Socket.instances[0].open());
  act(() => mockRecovery?.()); advance(1000);
  expect(Socket.instances[0].send).toHaveBeenCalledTimes(1); // auth only
  advance(100); expect(Socket.instances[0].send).toHaveBeenLastCalledWith('{"type":"request_keyframe"}');
  advance(2000); expect(Socket.instances[0].send).toHaveBeenCalledTimes(3);
  act(() => mockFrame?.({ displayWidth: 100, displayHeight: 200 }));
  advance(4000); expect(Socket.instances[0].send).toHaveBeenCalledTimes(3);
  act(() => mockRecovery?.()); advance(1100);
  expect(Socket.instances[0].send).toHaveBeenCalledTimes(4);
  act(() => mockFrame?.({ displayWidth: 100, displayHeight: 200 })); view.unmount();
  expect(jest.getTimerCount()).toBe(0);
});

it('resets codec references and cancels keyframe requests when a socket ends', () => {
  const view = render(<DeviceStream deviceId="fixture" />); advance(0);
  act(() => { Socket.instances[0].open(); mockRecovery?.(); Socket.instances[0].fail(); });
  expect(mockReset).toHaveBeenCalledTimes(1);
  advance(1500); expect(Socket.instances[0].send).toHaveBeenCalledTimes(1);
  view.unmount(); expect(jest.getTimerCount()).toBe(0);
});

it('recovers an open socket that stopped receiving server pings', () => {
  const view = render(<DeviceStream deviceId="fixture" />); advance(0);
  act(() => Socket.instances[0].open()); advance(36_000);
  expect(Socket.instances.length).toBeGreaterThan(1); view.unmount();
});

it('clears retry timers when the viewer is closed', () => {
  const view = render(<DeviceStream deviceId="fixture" />); advance(0);
  act(() => Socket.instances[0].fail()); view.unmount();
  expect(jest.getTimerCount()).toBe(0);
  advance(60_000); expect(Socket.instances).toHaveLength(1);
});

it.each([4001, 4003, 4004])('does not loop on a terminal access/device rejection %i', code => {
  const view = render(<DeviceStream deviceId="fixture" />); advance(0);
  act(() => Socket.instances[0].fail(code)); advance(60_000);
  expect(Socket.instances).toHaveLength(1); view.unmount();
});

it('explains a terminal device lookup rejection on the Open page', () => {
  const view = render(<DeviceStream deviceId="fixture" />); advance(0);
  act(() => Socket.instances[0].fail(4004));
  expect(screen.getByRole('status')).toHaveTextContent(
    'Устройство не найдено или недоступно в этой организации.',
  );
  view.unmount();
});
