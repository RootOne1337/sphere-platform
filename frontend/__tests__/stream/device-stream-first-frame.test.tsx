import { act, render, screen } from '@testing-library/react';
import { DeviceStream } from '@/src/components/streaming/DeviceStream';

let mockDecoder: {
  init: jest.Mock;
  destroy: jest.Mock;
  onDisconnect?: () => void;
  onReconnectStart?: () => void;
  onReconnect?: () => void;
  onFrame?: () => void;
} | null = null;

jest.mock('@/src/lib/streaming/H264Decoder', () => ({
  H264Decoder: class {
    init = jest.fn().mockResolvedValue(undefined);
    destroy = jest.fn();
    onDisconnect?: () => void;
    onReconnectStart?: () => void;
    onReconnect?: () => void;
    onFrame?: () => void;

    constructor() {
      mockDecoder = this;
    }
  },
}));

afterEach(() => {
  jest.useRealTimers();
});

it('shows unavailable instead of connecting when the viewer has no auth token', () => {
  render(<DeviceStream deviceId="device-remote" authToken="" />);
  expect(screen.getByText('Нет сигнала')).toBeInTheDocument();
});

it('keeps Open in waiting state until a decoded frame reaches the canvas', async () => {
  jest.useFakeTimers();
  render(<DeviceStream deviceId="device-remote" authToken="test-token" />);

  await act(async () => {
    await mockDecoder?.init();
  });

  expect(screen.getByText('Ожидание видеокадра...')).toBeInTheDocument();
  expect(screen.queryByText('Нет сигнала')).not.toBeInTheDocument();

  act(() => mockDecoder?.onFrame?.());
  expect(screen.queryByText('Ожидание видеокадра...')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /home/i })).toBeInTheDocument();

  act(() => jest.advanceTimersByTime(9_999));
  expect(screen.getByRole('button', { name: /home/i })).toBeInTheDocument();
  act(() => jest.advanceTimersByTime(1));
  expect(screen.getByText('Нет новых видеокадров более 10 секунд')).toBeInTheDocument();

  act(() => mockDecoder?.onFrame?.());
  expect(screen.getByRole('button', { name: /home/i })).toBeInTheDocument();

  act(() => mockDecoder?.onReconnectStart?.());
  expect(screen.getByText('Переподключение...')).toBeInTheDocument();
  act(() => mockDecoder?.onReconnect?.());
  expect(screen.getByText('Ожидание видеокадра...')).toBeInTheDocument();
});

it('keeps a disconnected stream offline instead of relabeling it stale', async () => {
  jest.useFakeTimers();
  render(<DeviceStream deviceId="device-remote" authToken="test-token" />);

  await act(async () => {
    await mockDecoder?.init();
  });
  act(() => mockDecoder?.onFrame?.());
  act(() => mockDecoder?.onDisconnect?.());
  act(() => jest.advanceTimersByTime(10_000));

  expect(screen.getByText('Нет сигнала')).toBeInTheDocument();
  expect(screen.queryByText('Нет новых видеокадров более 10 секунд')).not.toBeInTheDocument();
});
