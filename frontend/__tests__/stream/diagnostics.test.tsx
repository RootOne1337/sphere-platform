import { act, fireEvent, render, screen } from '@testing-library/react';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/store', () => ({ useAuthStore: () => ({ accessToken: 'fixture-token' }) }));

let mockStats: Record<string, number | null>;
jest.mock('@/lib/h264-decoder', () => ({ H264Decoder: class {
  constructor() {}
  init() {}
  destroy() {}
  reset() {}
  handleBinary() {}
  get stats() { return mockStats; }
} }));

class Socket {
  static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
  readyState = Socket.CONNECTING;
  binaryType = '';
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;
  send = jest.fn();
  close = jest.fn(() => { this.readyState = Socket.CLOSED; });
  constructor(_url: string) {}
}

beforeEach(() => {
  jest.useFakeTimers();
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
  expect(screen.getByText('Local WS rejected: 1')).toBeInTheDocument();
  expect(screen.getByText(/7 пакетов · 4096 байт/)).toBeInTheDocument();
  expect(screen.getByText('Последний пакет: 0 сек назад')).toBeInTheDocument();
  expect(screen.getByText('Последний canvas frame: 0 сек назад')).toBeInTheDocument();
  expect(screen.getByText('IDR/delta: 1/4')).toBeInTheDocument();
  expect(screen.getByText('Decoded output: 4')).toBeInTheDocument();
  expect(api.get).toHaveBeenCalledWith('/devices/device-1/stream-diagnostics');
});

it('applies the requested fit mode to the actual canvas surface', () => {
  const { container } = render(<DeviceStream deviceId="device-fit" fit="cover" />);
  act(() => jest.advanceTimersByTime(0));

  const canvas = container.querySelector('canvas');
  expect(canvas).toHaveStyle({ width: '100%', height: '100%', objectFit: 'cover' });
  expect(canvas?.parentElement).toHaveClass('h-full', 'w-full', 'min-h-0', 'min-w-0');
});
