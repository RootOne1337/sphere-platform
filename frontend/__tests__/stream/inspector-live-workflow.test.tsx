import { act, fireEvent, render, screen } from '@testing-library/react';
import { SingleDeviceStream } from '@/src/features/stream/SingleDeviceStream';
import { api } from '@/lib/api';

let draw: ((frame: VideoFrame) => void) | null;
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: 'fixture-token' }) }));
jest.mock('@/lib/api', () => ({ api: { post: jest.fn(), get: jest.fn() } }));
jest.mock('@/src/features/access/Capabilities', () => ({
  useCapabilities: () => ({ can: () => true }), PermissionNotice: () => null,
}));
jest.mock('@/lib/h264-decoder', () => ({ H264Decoder: class {
  constructor(callback: (frame: VideoFrame) => void) { draw = callback; }
  init() {} destroy() {} reset() {} handleBinary() {} get stats() { return null; }
} }));
class Socket {
  static OPEN = 1; static instances: Socket[] = [];
  readyState = 1; send = jest.fn(); close = jest.fn();
  onopen?: (event: Event) => void;
  constructor() { Socket.instances.push(this); }
}
const tree = () => ({ device_id: 'remote', snapshot_id: 'a'.repeat(32), source: 'android_uiautomator_root',
  requested_at: '2026-10-04T00:00:00Z', completed_at: '2026-10-04T00:00:02Z', width: 960, height: 540,
  rotation: 0, temporary_file_cleanup_confirmed: true,
  nodes: [{ id: 0, parent_id: null, depth: 0, xpath: '/hierarchy/node[1]',
    bounds: { left: 100, top: 100, right: 200, bottom: 160 },
    attributes: { text: 'Example', 'resource-id': 'pkg:id/target', class: 'android.widget.Button', custom: 'all-values' } }] });
beforeEach(() => {
  jest.useFakeTimers(); jest.clearAllMocks(); draw = null; Socket.instances = [];
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  Object.defineProperty(global, 'WebSocket', { configurable: true, value: Socket });
  class Pointer extends MouseEvent {
    readonly pointerId: number;
    constructor(type: string, options: MouseEventInit & { pointerId?: number } = {}) { super(type, options); this.pointerId = options.pointerId ?? 1; }
  }
  Object.defineProperty(window, 'PointerEvent', { configurable: true, value: Pointer });
  Object.defineProperty(HTMLCanvasElement.prototype, 'setPointerCapture', { configurable: true, value: jest.fn() });
  jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: jest.fn() } as never);
  jest.mocked(api.post).mockResolvedValue({ data: tree() });
});
afterEach(() => { jest.useRealTimers(); });
function open(picture = true) {
  const view = render(<SingleDeviceStream deviceId="remote" />);
  act(() => jest.advanceTimersByTime(0));
  act(() => Socket.instances[0].onopen?.(new Event('open')));
  const canvas = view.container.querySelector('canvas')!;
  jest.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 480, height: 270,
    right: 480, bottom: 270, x: 0, y: 0, toJSON: () => ({}) });
  if (picture) act(() => draw?.({ displayWidth: 960, displayHeight: 540 } as VideoFrame));
  fireEvent.click(screen.getByRole('button', { name: 'XPath-инспектор' }));
  return { ...view, canvas };
}
function pick(canvas: HTMLCanvasElement) {
  fireEvent.pointerDown(canvas, { clientX: 75, clientY: 60, pointerId: 1, button: 0 });
  fireEvent.pointerUp(canvas, { clientX: 75, clientY: 60, pointerId: 1, button: 0 });
}
function input() {
  return Socket.instances.flatMap(s => s.send.mock.calls).map(([value]) => JSON.parse(value as string))
    .filter(x => ['click', 'swipe', 'key', 'input_text'].includes(x.type));
}
it('loads on mode entry and selects through the actual canvas pointer chain without another button', async () => {
  const view = open();
  await screen.findByText(/1 элементов/);
  pick(view.canvas);
  expect(screen.getByText('/hierarchy/node[1]')).toBeInTheDocument();
  expect(screen.getByText('all-values')).toBeInTheDocument();
  expect(screen.getByLabelText('Границы выбранного элемента')).toBeInTheDocument();
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(input()).toEqual([]);
});
it('waits for a picture before starting the automatic tree read', async () => {
  open(false);
  expect(api.post).not.toHaveBeenCalled();
  act(() => draw?.({ displayWidth: 960, displayHeight: 540 } as VideoFrame));
  await screen.findByText(/1 элементов/);
  expect(api.post).toHaveBeenCalledTimes(1);
});
it('keeps the latest pick while the initial read is pending instead of silently losing it', async () => {
  let resolve: (value: unknown) => void = () => {};
  jest.mocked(api.post).mockImplementation(() => new Promise(r => { resolve = r; }) as never);
  const view = open(); pick(view.canvas);
  expect(api.post).toHaveBeenCalledTimes(1);
  await act(async () => { resolve({ data: tree() }); });
  expect(screen.getByText('/hierarchy/node[1]')).toBeInTheDocument();
  expect(input()).toEqual([]);
});
it('refreshes while active and keeps the selected element visible during the request', async () => {
  const view = open(); await screen.findByText(/1 элементов/); pick(view.canvas);
  let resolve: (value: unknown) => void = () => {};
  jest.mocked(api.post).mockImplementationOnce(() => new Promise(r => { resolve = r; }) as never);
  await act(async () => { jest.advanceTimersByTime(5_000); });
  expect(api.post).toHaveBeenCalledTimes(2);
  expect(screen.getByText('/hierarchy/node[1]')).toBeInTheDocument();
  await act(async () => { resolve({ data: tree() }); });
  expect(screen.getByLabelText('Границы выбранного элемента')).toBeInTheDocument();
  expect(input()).toEqual([]);
});
it('pauses after a failed refresh rather than repeatedly executing root reads', async () => {
  open(); await screen.findByText(/1 элементов/);
  jest.mocked(api.post).mockRejectedValueOnce(new Error('fixture transport unavailable'));
  await act(async () => { jest.advanceTimersByTime(5_000); });
  expect(await screen.findByRole('alert')).toHaveTextContent('fixture transport unavailable');
  await act(async () => { jest.advanceTimersByTime(20_000); });
  expect(api.post).toHaveBeenCalledTimes(2);
});
it('does not start another read while one is pending and waits five seconds after completion', async () => {
  let resolve: (value: unknown) => void = () => {};
  jest.mocked(api.post).mockImplementationOnce(() => new Promise(r => { resolve = r; }) as never);
  open();
  await act(async () => { jest.advanceTimersByTime(15_000); });
  expect(api.post).toHaveBeenCalledTimes(1);
  await act(async () => { resolve({ data: tree() }); });
  await act(async () => { jest.advanceTimersByTime(4_999); });
  expect(api.post).toHaveBeenCalledTimes(1);
  await act(async () => { jest.advanceTimersByTime(1); });
  expect(api.post).toHaveBeenCalledTimes(2);
});
it('suspends periodic reads in a hidden document and refreshes when returning', async () => {
  open(); await screen.findByText(/1 элементов/);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
  fireEvent(document, new Event('visibilitychange'));
  await act(async () => { jest.advanceTimersByTime(20_000); });
  expect(api.post).toHaveBeenCalledTimes(1);
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
  await act(async () => { fireEvent(document, new Event('visibilitychange')); });
  expect(api.post).toHaveBeenCalledTimes(2);
});
it('reports a miss and also supports explicit selection from the returned tree', async () => {
  const view = open(); await screen.findByText(/1 элементов/);
  fireEvent.pointerDown(view.canvas, { clientX: 400, clientY: 100, pointerId: 2, button: 0 });
  fireEvent.pointerUp(view.canvas, { clientX: 400, clientY: 100, pointerId: 2, button: 0 });
  expect(screen.getByText(/Android не предоставил узел в выбранной точке/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Дерево элементов · 1' }));
  fireEvent.click(screen.getByRole('button', { name: /#0 · Example/ }));
  expect(screen.getByLabelText('Границы выбранного элемента')).toBeInTheDocument();
  expect(screen.getByText('all-values')).toBeInTheDocument();
  expect(input()).toEqual([]);
});
