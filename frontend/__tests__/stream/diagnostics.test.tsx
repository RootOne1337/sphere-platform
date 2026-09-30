import { act, fireEvent, render, screen } from '@testing-library/react';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: 'fixture-token' }) }));

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
  Socket.instances = [];
  mockFrameCallback = null;
  mockStats = {
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
  expect(screen.getByText('Local WS rejected: 1')).toBeInTheDocument();
  expect(screen.getByText(/7 пакетов · 4096 байт/)).toBeInTheDocument();
  expect(screen.getByText('Последний пакет: 0 сек назад')).toBeInTheDocument();
  expect(screen.getByText('Последний canvas frame: 0 сек назад')).toBeInTheDocument();
  expect(screen.getByText('IDR/delta: 1/4')).toBeInTheDocument();
  expect(screen.getByText('Decoded output: 4')).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/devices/device-1/stream-diagnostics');
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

it('reports a missing first frame even when WebSocket pings keep the connection open', () => {
  render(<DeviceStream deviceId="device-no-frame" />);
  act(() => jest.advanceTimersByTime(0));

  const socket = Socket.instances[0];
  socket.readyState = Socket.OPEN;
  act(() => socket.onopen?.());
  act(() => socket.onmessage?.({ data: JSON.stringify({ type: 'ping' }) }));

  act(() => jest.advanceTimersByTime(9_999));
  expect(screen.queryByText('Первый видеокадр не получен за 10 секунд')).not.toBeInTheDocument();
  act(() => jest.advanceTimersByTime(1));

  expect(screen.getByText('Первый видеокадр не получен за 10 секунд')).toBeInTheDocument();
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
  const button = screen.getByRole('button', { name: 'Сохранить свежий кадр PNG' });
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
  expect(screen.getByRole('button', { name: 'Сохранить свежий кадр PNG' })).toBeDisabled();
  expect(screen.getByText('Ожидание видеокадра…')).toBeInTheDocument();
});
