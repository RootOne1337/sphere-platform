import { act, fireEvent, render, screen } from '@testing-library/react';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
let mockAccessToken: string | null = 'fixture-token';
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: mockAccessToken }) }));

let mockStats: Record<string, number | null>;
let mockFrameCallback: ((frame: VideoFrame) => void) | null = null;
jest.mock('@/lib/h264-decoder', () => ({ H264Decoder: class {
  constructor(onFrame: (frame: VideoFrame) => void) { mockFrameCallback = onFrame; }
  init() {}
  destroy() {}
  reset() {}
  handleBinary() {}
  get stats() { return mockStats; }
} }));

class Socket {
  static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
  static instances: Socket[] = [];
  readyState = Socket.CONNECTING;
  binaryType = '';
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;
  send = jest.fn();
  close = jest.fn(() => { this.readyState = Socket.CLOSED; });
  constructor() { Socket.instances.push(this); }
}

beforeEach(() => {
  jest.useFakeTimers();
  mockAccessToken = 'fixture-token';
  Socket.instances = [];
  mockFrameCallback = null;
  mockStats = {
    receivedPictureFps: 20, renderedFps: 18,
    binaryMessagesReceived: 7, binaryBytesReceived: 4096, validPackets: 7, invalidPackets: 0,
    spsUnits: 1, ppsUnits: 1, idrUnits: 1, deltaUnits: 4, decodeSubmitted: 5,
    decodedOutputs: 4, renderedFrames: 4, decodeErrors: 0, renderErrors: 0,
    queueRecoveries: 0, staleOutputDrops: 0, framesDroppedBeforeConfiguration: 0,
    decoderQueueSize: 0, pendingOutputCount: 0,
    lastBinaryAtMs: Date.now(), lastRenderedAtMs: Date.now(),
  };
  (api.get as jest.Mock).mockReset().mockResolvedValue({ data: {
    state: 'active_report',
    agent_status: 'online',
    last_heartbeat: '2026-09-25T12:00:00Z',
    age_seconds: 4,
    diagnostics: { observed_at: '2026-09-25T12:00:00Z', telemetry: {
      schema_version: 2,
      capture_fps: 15, render_fps: 14, capture_frames_total: 900,
      rendered_frames_total: 850, capture_read_failures_total: 0,
      render_failures_total: 1, encoder_errors_total: 0,
      frame_throttle_drops_total: 50, encoder_fps: 14,
      capture_throttle_drops_total: 23,
      encoded_frames_total: 850, encoded_bytes_total: 200000,
      ws_queue_attempts_total: 400, ws_queue_accepted_total: 399,
      ws_queue_rejected_total: 1, ws_queue_accepted_bytes_total: 180000,
    } },
  } });
  Object.defineProperty(global, 'WebSocket', { configurable: true, value: Socket });
  jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: jest.fn() } as never);
});

afterEach(() => { jest.restoreAllMocks(); jest.useRealTimers(); });

it('shows agent and browser stages only when operator opens diagnostics', async () => {
  render(<DeviceStream deviceId="device-1" enableDiagnostics />);
  act(() => jest.advanceTimersByTime(0));
  fireEvent.click(screen.getByRole('button', { name: 'Диагностика' }));

  expect(await screen.findByText(/Отчёт APK: захват активен/)).toBeInTheDocument();
  act(() => jest.advanceTimersByTime(1000));
  expect(screen.getByText('Capture FPS: 15')).toBeInTheDocument();
  expect(screen.getByText('Raw capture FPS skips: 23')).toBeInTheDocument();
  expect(screen.getByText('Encoded FPS drops: 50')).toBeInTheDocument();
  expect(screen.getByText('Входной видео FPS (1 с): 20')).toBeInTheDocument();
  expect(screen.getByText('Отрисовка FPS (1 с): 18')).toBeInTheDocument();
  expect(screen.getByText('Local WS rejected: 1')).toBeInTheDocument();
  expect(screen.getByText(/7 пакетов · 4096 байт/)).toBeInTheDocument();
  expect(screen.getByText('Последний пакет: 1 сек назад')).toBeInTheDocument();
  expect(screen.getByText('Последний canvas frame: 1 сек назад')).toBeInTheDocument();
  expect(screen.getByText('IDR/delta: 1/4')).toBeInTheDocument();
  expect(screen.getByText('Decoded output: 4')).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/devices/device-1/stream-diagnostics', { signal: expect.any(AbortSignal) });
});

it('keeps raw capture skips unknown for an older agent instead of displaying zero', async () => {
  (api.get as jest.Mock).mockResolvedValue({ data: {
    state: 'active_report', age_seconds: 4,
    diagnostics: { observed_at: '2026-09-25T12:00:00Z', telemetry: {
      schema_version: 2, frame_throttle_drops_total: 50,
    } },
  } });
  render(<DeviceStream deviceId="device-old" enableDiagnostics />);
  act(() => jest.advanceTimersByTime(0));
  fireEvent.click(screen.getByRole('button', { name: 'Диагностика' }));
  expect(await screen.findByText('Raw capture FPS skips: —')).toBeInTheDocument();
  expect(screen.getByText('Encoded FPS drops: 50')).toBeInTheDocument();
});

it('does not show a previous device snapshot while the new device request is pending', async () => {
  const view = render(<DeviceStream deviceId="device-first" enableDiagnostics />);
  act(() => jest.advanceTimersByTime(0));
  fireEvent.click(screen.getByRole('button', { name: 'Диагностика' }));
  expect(await screen.findByText('Capture FPS: 15')).toBeInTheDocument();
  (api.get as jest.Mock).mockImplementation(() => new Promise(() => {}));
  view.rerender(<DeviceStream deviceId="device-next" enableDiagnostics />);
  expect(screen.queryByText('Capture FPS: 15')).not.toBeInTheDocument();
  expect(screen.queryByText(/Local WS rejected: 1/)).not.toBeInTheDocument();
  expect(screen.getByText(/Отчёт APK: загрузка/)).toBeInTheDocument();
});

it('does not start overlapping polls when the previous diagnostics request has not settled', () => {
  (api.get as jest.Mock).mockImplementation(() => new Promise(() => {}));
  render(<DeviceStream deviceId="device-slow" enableDiagnostics />);
  act(() => jest.advanceTimersByTime(0));
  fireEvent.click(screen.getByRole('button', { name: 'Диагностика' }));
  act(() => jest.advanceTimersByTime(45_000));
  expect(api.get).toHaveBeenCalledTimes(1);
});

it('ages the received APK snapshot between HTTP polls instead of freezing its freshness', async () => {
  render(<DeviceStream deviceId="device-aging" enableDiagnostics />);
  act(() => jest.advanceTimersByTime(0));
  fireEvent.click(screen.getByRole('button', { name: 'Диагностика' }));
  await act(async () => {});
  expect(screen.getByText(/snapshot 4 сек назад/)).toBeInTheDocument();
  act(() => jest.advanceTimersByTime(11_000));
  expect(screen.getByText(/snapshot 15 сек назад/)).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledTimes(1);
});

it('invalidates the APK report and aborts its poll when the authentication session changes', async () => {
  const view = render(<DeviceStream deviceId="device-session" enableDiagnostics />);
  act(() => jest.advanceTimersByTime(0));
  fireEvent.click(screen.getByRole('button', { name: 'Диагностика' }));
  await act(async () => {});
  expect(screen.getByText('Capture FPS: 15')).toBeInTheDocument();
  const previousSignal = (api.get as jest.Mock).mock.calls[0][1].signal as AbortSignal;
  (api.get as jest.Mock).mockImplementation(() => new Promise(() => {}));
  mockAccessToken = 'replacement-fixture-token';
  view.rerender(<DeviceStream deviceId="device-session" enableDiagnostics />);
  expect(previousSignal.aborted).toBe(true);
  expect(screen.queryByText('Capture FPS: 15')).not.toBeInTheDocument();
  expect(api.get).toHaveBeenCalledTimes(2);
});

it('ignores a late old-device response even when the transport does not honor abort', async () => {
  let resolveOld!: (value: unknown) => void;
  (api.get as jest.Mock).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
  const view = render(<DeviceStream deviceId="device-old-pending" enableDiagnostics />);
  act(() => jest.advanceTimersByTime(0));
  fireEvent.click(screen.getByRole('button', { name: 'Диагностика' }));
  view.rerender(<DeviceStream deviceId="device-current" enableDiagnostics />);
  await act(async () => {});
  expect(screen.getByText('Capture FPS: 15')).toBeInTheDocument();
  await act(async () => resolveOld({ data: { state: 'active_report', age_seconds: 0,
    diagnostics: { telemetry: { capture_fps: 999 } } } }));
  expect(screen.queryByText('Capture FPS: 999')).not.toBeInTheDocument();
  expect(screen.getByText('Capture FPS: 15')).toBeInTheDocument();
});

it('retries a failed poll and replaces the failure message with the next successful report', async () => {
  render(<DeviceStream deviceId="device-retry" enableDiagnostics />);
  act(() => jest.advanceTimersByTime(0));
  fireEvent.click(screen.getByRole('button', { name: 'Диагностика' }));
  await act(async () => {});
  (api.get as jest.Mock).mockRejectedValueOnce(new Error('fixture transport failure'));
  await act(async () => jest.advanceTimersByTime(15_000));
  expect(screen.getByText('Не удалось получить телеметрию устройства')).toBeInTheDocument();
  await act(async () => jest.advanceTimersByTime(15_000));
  expect(screen.queryByText('Не удалось получить телеметрию устройства')).not.toBeInTheDocument();
  expect(screen.getByText('Capture FPS: 15')).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledTimes(3);
});

it('static-input mode still requires a first frame even when WebSocket pings keep the connection open', () => {
  const { container } = render(<DeviceStream deviceId="device-no-frame" enableStaticInput />);
  act(() => jest.advanceTimersByTime(0));

  const socket = Socket.instances[0];
  socket.readyState = Socket.OPEN;
  act(() => socket.onopen?.());
  act(() => socket.onmessage?.({ data: JSON.stringify({ type: 'ping' }) }));

  act(() => jest.advanceTimersByTime(9_999));
  expect(screen.queryByText('Первый видеокадр не получен за 10 секунд')).not.toBeInTheDocument();
  act(() => jest.advanceTimersByTime(1));

  expect(screen.getByText('Первый видеокадр не получен за 10 секунд')).toBeInTheDocument();
  expect(container.querySelector('canvas')).toHaveAttribute('aria-disabled', 'true');
});

it('allowing control on a static picture does not relabel a stale PNG export as fresh', () => {
  const { container } = render(<DeviceStream deviceId="device-static-png" enableScreenshot enableStaticInput />);
  act(() => jest.advanceTimersByTime(0));
  const socket = Socket.instances[0];
  socket.readyState = Socket.OPEN;
  act(() => socket.onopen?.());
  act(() => mockFrameCallback?.({ displayWidth: 960, displayHeight: 540 } as VideoFrame));
  const button = screen.getByRole('button', { name: 'Кадр видео (PNG) · не оригинал' });
  expect(button).toBeEnabled();
  act(() => jest.advanceTimersByTime(10_000));
  expect(container.querySelector('canvas')).toHaveAttribute('aria-disabled', 'false');
  expect(button).toBeDisabled();
});

it('applies the requested fit mode to the actual canvas surface', () => {
  const { container } = render(<DeviceStream deviceId="device-fit" fit="cover" />);
  act(() => jest.advanceTimersByTime(0));

  const canvas = container.querySelector('canvas');
  expect(canvas).toHaveStyle({ width: '100%', height: '100%', objectFit: 'cover' });
  expect(canvas?.parentElement).toHaveClass('h-full', 'w-full', 'min-h-0', 'min-w-0');
});

it('reports decoded frame dimensions only when the stream orientation changes', () => {
  const onFrameDimensions = jest.fn();
  render(<DeviceStream deviceId="device-dimensions" onFrameDimensions={onFrameDimensions} />);
  act(() => jest.advanceTimersByTime(0));

  const socket = Socket.instances[0];
  socket.readyState = Socket.OPEN;
  act(() => socket.onopen?.());
  const emitFrame = (displayWidth: number, displayHeight: number) => {
    act(() => mockFrameCallback?.({ displayWidth, displayHeight } as VideoFrame));
  };

  emitFrame(1920, 1080);
  emitFrame(1920, 1080);
  emitFrame(1080, 1920);

  expect(onFrameDimensions).toHaveBeenNthCalledWith(1, { width: 1920, height: 1080 });
  expect(onFrameDimensions).toHaveBeenNthCalledWith(2, { width: 1080, height: 1920 });
  expect(onFrameDimensions).toHaveBeenCalledTimes(2);
});

it('exports only a freshly rendered canvas frame and sends no screenshot API command', () => {
  const toBlob = jest.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((callback) => callback(new Blob(['fixture'], { type: 'image/png' })));
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: jest.fn(() => 'blob:fixture') });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: jest.fn() });
  const download = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  render(<DeviceStream deviceId="device-png" enableScreenshot />);
  act(() => jest.advanceTimersByTime(0));
  const button = screen.getByRole('button', { name: 'Кадр видео (PNG) · не оригинал' });
  expect(button).toBeDisabled();
  const socket = Socket.instances[0]; socket.readyState = Socket.OPEN;
  act(() => socket.onopen?.());
  expect(button).toBeDisabled();
  act(() => mockFrameCallback?.({ displayWidth: 1920, displayHeight: 1080 } as VideoFrame));
  expect(button).toBeEnabled();
  fireEvent.click(button);
  expect(toBlob).toHaveBeenCalledWith(expect.any(Function), 'image/png');
  expect(download).toHaveBeenCalledTimes(1);
  expect(api.get).not.toHaveBeenCalled();
  act(() => jest.advanceTimersByTime(10_000));
  expect(button).toBeDisabled();
});

it('does not claim a rendered picture when drawing the decoder output fails', () => {
  jest.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: () => { throw new Error('canvas failure'); } } as never);
  render(<DeviceStream deviceId="device-draw-failure" enableScreenshot />);
  act(() => jest.advanceTimersByTime(0));
  const socket = Socket.instances[0]; socket.readyState = Socket.OPEN;
  act(() => socket.onopen?.());
  expect(() => act(() => mockFrameCallback?.({ displayWidth: 1920, displayHeight: 1080 } as VideoFrame))).toThrow('canvas failure');
  expect(screen.getByRole('button', { name: 'Кадр видео (PNG) · не оригинал' })).toBeDisabled();
  expect(screen.getByText('Ожидание видеокадра…')).toBeInTheDocument();
});
