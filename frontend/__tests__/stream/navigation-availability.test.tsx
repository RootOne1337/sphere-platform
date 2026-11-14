import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { api } from '@/lib/api';
import { DeviceStream } from '@/components/sphere/DeviceStream';

let mockRenderFrame: ((frame: VideoFrame) => void) | null = null;
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: 'fixture-token' }) }));
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
jest.mock('@/lib/h264-decoder', () => ({ H264Decoder: class {
  constructor(onFrame: (frame: VideoFrame) => void) { mockRenderFrame = onFrame; }
  init() {} destroy() {} reset() {} handleBinary() {}
  get stats() { return null; }
} }));

class MockSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSED = 3;
  static instances: MockSocket[] = [];
  readyState = MockSocket.CONNECTING;
  binaryType = '';
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  send = jest.fn();
  close = jest.fn(() => { this.readyState = MockSocket.CLOSED; });
  constructor() { MockSocket.instances.push(this); }
}
beforeEach(() => {
  jest.useFakeTimers();
  MockSocket.instances = [];
  mockRenderFrame = null;
  jest.mocked(api.post).mockReset().mockResolvedValue({ data: { output: '' } });
  Object.defineProperty(global, 'WebSocket', { configurable: true, value: MockSocket });
  jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: jest.fn() } as never);
});
afterEach(() => { jest.restoreAllMocks(); jest.useRealTimers(); });

function openStream(enableNavigation = true, onControlCommand?: React.ComponentProps<typeof DeviceStream>['onControlCommand']) {
  const view = render(<DeviceStream deviceId="remote" enableNavigation={enableNavigation} onControlCommand={onControlCommand} fit="contain" />);
  act(() => jest.advanceTimersByTime(0));
  const socket = MockSocket.instances[0];
  socket.readyState = MockSocket.OPEN;
  act(() => socket.onopen?.());
  return { ...view, socket };
}
function frame() { act(() => mockRenderFrame?.({ displayWidth: 960, displayHeight: 540 } as VideoFrame)); }

it('retains the role restriction explanation when no execution lock reason is provided', () => {
  const { container } = render(<DeviceStream deviceId="role-limited" enableNavigation readOnly />);
  expect(screen.getByText('Только просмотр · роль не разрешает клики, жесты и навигацию Android.')).toBeInTheDocument();
  expect(container.querySelector('canvas')).toHaveAttribute('aria-label', 'Экран устройства: только просмотр, управление запрещено для вашей роли');
  expect(screen.getByRole('button', { name: 'Назад' })).toBeDisabled();
});

it('explains a runtime execution lock truthfully while still blocking input even after a live frame', () => {
  const { container, rerender, socket } = openStream();
  frame();
  const reason = 'Управление временно заблокировано на время проверки задания или при неподтверждённом результате.';
  rerender(<DeviceStream deviceId="remote" enableNavigation fit="contain" readOnly readOnlyReason={reason} />);
  expect(screen.getByText(`Только просмотр · ${reason}`)).toBeInTheDocument();
  expect(screen.queryByText(/роль не разрешает/)).not.toBeInTheDocument();
  expect(container.querySelector('canvas')).toHaveAttribute('aria-label', `Экран устройства: только просмотр. ${reason}`);
  expect(container.querySelector('canvas')).toHaveAttribute('aria-disabled', 'true');
  expect(screen.getByRole('button', { name: 'Назад' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
  expect(api.post).not.toHaveBeenCalled();
  expect(socket.send.mock.calls.map(([message]) => JSON.parse(message as string)).filter(({ type }) => type === 'keyevent')).toHaveLength(0);
});

it('the fleet default does not show navigation or send commands', () => {
  render(<DeviceStream deviceId="fleet-tile" />);
  expect(screen.queryByRole('region', { name: 'Навигация Android' })).not.toBeInTheDocument();
  expect(api.post).not.toHaveBeenCalled();
});

it('transport open is insufficient: navigation needs a successfully drawn frame', () => {
  openStream();
  expect(screen.getByRole('button', { name: 'Назад' })).toBeDisabled();
  frame();
  expect(screen.getByRole('button', { name: 'Назад' })).toBeEnabled();
});

it('a failed canvas draw cannot enable navigation', () => {
  jest.mocked(HTMLCanvasElement.prototype.getContext).mockReturnValue({ drawImage: () => { throw new Error('draw'); } } as never);
  openStream();
  expect(frame).toThrow('draw');
  expect(screen.getByRole('button', { name: 'Домой' })).toBeDisabled();
});

it('static video retains geometry-free navigation while pointer input remains blocked', async () => {
  const { container } = openStream();
  frame();
  act(() => jest.advanceTimersByTime(10_000));
  expect(container.querySelector('canvas')).toHaveAttribute('aria-disabled', 'true');
  expect(screen.getByRole('button', { name: 'Назад' })).toBeEnabled();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Назад' })));
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(within(screen.getByRole('region', { name: 'Навигация Android' })).getByRole('status')).toHaveTextContent('выполнение подтверждено');
});

it.each(['close', 'error', 'denied'])('%s blocks navigation after a frame and sends no key on WebSocket', reason => {
  const { socket } = openStream();
  frame();
  act(() => {
    if (reason === 'close') socket.onclose?.({ code: 1006 });
    else if (reason === 'error') socket.onerror?.();
    else socket.onmessage?.({ data: JSON.stringify({ type: 'error', error: 'stream_control_denied' }) });
  });
  expect(screen.getByRole('button', { name: 'Назад' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
  expect(api.post).not.toHaveBeenCalled();
  expect(socket.send.mock.calls.map(([message]) => JSON.parse(message as string))
    .filter(({ type }) => type === 'keyevent')).toHaveLength(0);
});

it('navigation occupies its own footer and does not change native canvas dimensions', () => {
  const { container } = openStream();
  frame();
  const navigation = screen.getByRole('region', { name: 'Навигация Android' });
  const canvas = container.querySelector('canvas')!;
  expect(canvas.width).toBe(960);
  expect(canvas.height).toBe(540);
  expect(canvas.style.objectFit).toBe('contain');
  expect(canvas.parentElement).not.toContainElement(navigation);
  expect(canvas.parentElement?.parentElement).toContainElement(navigation);
});

it('reconnection cannot unlock navigation using an old session picture', () => {
  const { socket } = openStream();
  frame();
  act(() => socket.onclose?.({ code: 1006 }));
  act(() => jest.advanceTimersByTime(1500));
  const recovered = MockSocket.instances[1];
  recovered.readyState = MockSocket.OPEN;
  act(() => recovered.onopen?.());
  act(() => jest.advanceTimersByTime(10_000));
  expect(screen.getByRole('button', { name: 'Назад' })).toBeDisabled();
  frame();
  expect(screen.getByRole('button', { name: 'Назад' })).toBeEnabled();
});

it('carries native frame geometry through the real navigation footer and freezes it before an HTTP reply', async () => {
  Object.defineProperty(crypto, 'randomUUID', { configurable: true, value: () => 'footer-request' });
  let finish!: (value: unknown) => void;
  jest.mocked(api.post).mockReturnValue(new Promise(resolve => { finish = resolve; }) as never);
  const observer = jest.fn(); openStream(true, observer); frame();
  fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
  expect(observer.mock.calls[0][0]).toMatchObject({ phase: 'submitted', input: { dimensions: { width: 960, height: 540 }, command: { type: 'key_event', keycode: 4 } } });
  act(() => mockRenderFrame?.({ displayWidth: 540, displayHeight: 960 } as VideoFrame));
  await act(async () => finish({ data: { output: '' } }));
  expect(observer.mock.calls[1][0]).toMatchObject({ phase: 'confirmed', input: { dimensions: { width: 960, height: 540 } } });
});
it('does not emit a recording event before an owned frame exists', () => {
  const observer = jest.fn(); openStream(true, observer);
  fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
  expect(observer).not.toHaveBeenCalled(); expect(api.post).not.toHaveBeenCalled();
});
