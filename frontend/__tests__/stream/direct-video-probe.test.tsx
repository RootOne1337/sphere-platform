import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { DirectVideoProbe } from '@/src/features/stream/DirectVideoProbe';
import type { DirectProbeResult } from '@/src/features/stream/directProbe';

let mockToken: string | null = 'fixture';
const mockStop = jest.fn();
let mockReport: (value: DirectProbeResult) => void;
let mockTrack: (track: MediaStreamTrack) => void;
let mockFrame: VideoFrameRequestCallback;
const mockStart = jest.fn((_url, _token, report, options) => {
  mockReport = report; mockTrack = options.onTrack;
  report({ state: 'gathering', samples: [], path: 'unknown', protocol: null, reason: null });
  return mockStop;
});
jest.mock('@/lib/store', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({ accessToken: mockToken }) }));
jest.mock('@/src/features/stream/directProbe', () => ({
  startDirectVideoProbe: (...args: Parameters<typeof mockStart>) => mockStart(...args),
}));
const connected: DirectProbeResult = { state: 'connected', samples: [25.8], path: 'nat', protocol: 'udp', reason: null,
  videoBinding: { captureEpoch: '12345678-1234-4234-8234-123456789abc', width: 960, height: 540 } };
const pause = jest.fn(), play = jest.fn(async () => {}), cancel = jest.fn();
beforeEach(() => {
  mockToken = 'fixture'; jest.clearAllMocks();
  Object.defineProperty(HTMLVideoElement.prototype, 'play', { configurable: true, value: play });
  Object.defineProperty(HTMLVideoElement.prototype, 'pause', { configurable: true, value: pause });
  Object.defineProperty(HTMLVideoElement.prototype, 'cancelVideoFrameCallback', { configurable: true, value: cancel });
  Object.defineProperty(HTMLVideoElement.prototype, 'requestVideoFrameCallback', { configurable: true,
    value: (callback: VideoFrameRequestCallback) => { mockFrame = callback; return 7; } });
  Object.defineProperty(globalThis, 'MediaStream', { configurable: true, value: class { constructor(readonly tracks: MediaStreamTrack[]) {} } });
});
function begin() { fireEvent.click(screen.getByRole('button', { name: 'Проверить видео с APK' })); }

test('no peer is opened on mount and decoded pictures, not an open channel, confirm video', async () => {
  render(<DirectVideoProbe deviceId="device" profile="public-stun" />);
  expect(mockStart).not.toHaveBeenCalled(); begin();
  expect(mockStart.mock.calls[0][3].controlledStunUrl).toBe('stun:stun.cloudflare.com:3478');
  act(() => mockReport(connected));
  expect(screen.getByRole('status')).toHaveTextContent('Соединяем видеоканал');
  act(() => mockTrack({ kind: 'video' } as MediaStreamTrack));
  await act(async () => {});
  act(() => mockFrame(1, { width: 960, height: 540 } as VideoFrameCallbackMetadata));
  expect(screen.getByRole('status')).toHaveTextContent('Кадры отображаются по WebRTC');
  expect(play).toHaveBeenCalledTimes(1);
});
test('twenty echo packets without a rendered picture never claim successful video', () => {
  render(<DirectVideoProbe deviceId="device" profile="host" />); begin();
  act(() => mockReport({ ...connected, state: 'finished', samples: Array(20).fill(10) }));
  expect(screen.getByRole('status')).toHaveTextContent('Видеокадры не подтверждены');
  expect(screen.queryByText(/Кадры отображаются/)).not.toBeInTheDocument();
});

test('a picture arriving before capture metadata is counted only after its dimensions are bound', async () => {
  render(<DirectVideoProbe deviceId="device" profile="host" />); begin();
  act(() => { mockReport({ ...connected, videoBinding: undefined }); mockTrack({ kind: 'video' } as MediaStreamTrack); });
  await act(async () => {});
  act(() => mockFrame(1, { width: 960, height: 540 } as VideoFrameCallbackMetadata));
  expect(screen.getByRole('status')).toHaveTextContent('Соединяем видеоканал');
  act(() => mockReport(connected));
  expect(screen.getByRole('status')).toHaveTextContent('Кадры отображаются по WebRTC');
});

test('capture metadata cannot validate an earlier picture with different dimensions', async () => {
  render(<DirectVideoProbe deviceId="device" profile="host" />); begin();
  act(() => { mockReport({ ...connected, videoBinding: undefined }); mockTrack({ kind: 'video' } as MediaStreamTrack); });
  await act(async () => {});
  act(() => mockFrame(1, { width: 540, height: 960 } as VideoFrameCallbackMetadata));
  act(() => mockReport(connected));
  expect(mockStop).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('alert')).toHaveTextContent('Размер полученного кадра не совпал');
  expect(screen.getByRole('button', { name: 'Проверить видео с APK' })).toBeEnabled();
});

test('a negotiated channel without decoded video has a finite first-picture deadline', () => {
  jest.useFakeTimers();
  const { unmount } = render(<DirectVideoProbe deviceId="device" profile="host" />); begin();
  act(() => mockReport(connected));
  act(() => jest.advanceTimersByTime(8_000));
  expect(mockStop).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('alert')).toHaveTextContent('первый видеокадр не отображён за 8 секунд');
  expect(screen.getByRole('button', { name: 'Проверить видео с APK' })).toBeEnabled();
  unmount(); jest.useRealTimers();
});
test('unexpected rendered geometry stops the experiment and does not unlock any input', async () => {
  render(<DirectVideoProbe deviceId="device" profile="host" />); begin();
  act(() => { mockReport(connected); mockTrack({ kind: 'video' } as MediaStreamTrack); });
  await act(async () => {});
  act(() => mockFrame(1, { width: 540, height: 960 } as VideoFrameCallbackMetadata));
  expect(mockStop).toHaveBeenCalled();
  expect(screen.getByRole('alert')).toHaveTextContent('Размер полученного кадра не совпал');
  expect(screen.queryByRole('button', { name: /управление|касание/i })).not.toBeInTheDocument();
});
test('device change and unmount fence late media callbacks and clear native renderer references', () => {
  const { rerender, unmount } = render(<DirectVideoProbe deviceId="first" profile="host" />); begin();
  const lateReport = mockReport, lateTrack = mockTrack;
  rerender(<DirectVideoProbe deviceId="second" profile="host" />);
  expect(mockStop).toHaveBeenCalledTimes(1);
  const track = { kind: 'video', stop: jest.fn() };
  act(() => { lateReport(connected); lateTrack(track as unknown as MediaStreamTrack); });
  expect(track.stop).toHaveBeenCalledTimes(1); expect(screen.queryByRole('status')).not.toBeInTheDocument();
  begin(); unmount(); expect(mockStop).toHaveBeenCalledTimes(2); expect(pause).toHaveBeenCalled();
});
test('hidden page retires the finite peer and relay uses only authenticated temporary grants', () => {
  render(<DirectVideoProbe deviceId="device" profile="turn" />); begin();
  expect(mockStart.mock.calls[0][3].relayGrant).toBe(true);
  expect(mockStart.mock.calls[0][3].controlledStunUrl).toBeUndefined();
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  fireEvent(document, new Event('visibilitychange'));
  expect(mockStop).toHaveBeenCalledTimes(1);
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
});

test('automatic admission starts once, can be cancelled, and never repeats on focus or rerender', () => {
  const view = render(<DirectVideoProbe deviceId="device" profile="host" automaticKey="viewer:host" />);
  expect(mockStart).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('button', { name: 'Проверить видео с APK' })).not.toBeInTheDocument();
  view.rerender(<DirectVideoProbe deviceId="device" profile="host" automaticKey="viewer:host" enabled={false} />);
  expect(mockStop).toHaveBeenCalledTimes(1);
  view.rerender(<DirectVideoProbe deviceId="device" profile="host" automaticKey="viewer:host" />);
  expect(mockStart).toHaveBeenCalledTimes(1);
});

test('automatic outcome reports real rendered pictures once; echoes alone still report zero frames', async () => {
  const onOutcome = jest.fn();
  render(<DirectVideoProbe deviceId="device" profile="host" automaticKey="viewer:host" onOutcome={onOutcome} />);
  act(() => { mockReport(connected); mockTrack({ kind: 'video' } as MediaStreamTrack); });
  await act(async () => {});
  act(() => mockFrame(1, { width: 960, height: 540 } as VideoFrameCallbackMetadata));
  expect(onOutcome).not.toHaveBeenCalled();
  const finished: DirectProbeResult = { ...connected, state: 'finished', samples: Array(20).fill(10) };
  act(() => { mockReport(finished); mockReport(finished); });
  expect(onOutcome).toHaveBeenCalledTimes(1);
  expect(onOutcome.mock.calls[0][1]).toBe(1);
});

test('cancelling a pending play promise preserves the transport failure and its single outcome', async () => {
  let rejectPlayback: (error: Error) => void = () => {};
  play.mockImplementationOnce(() => new Promise<void>((_resolve, reject) => { rejectPlayback = reject; }));
  const onOutcome = jest.fn();
  render(<DirectVideoProbe deviceId="device" profile="host" automaticKey="viewer:host" onOutcome={onOutcome} />);
  act(() => mockTrack({ kind: 'video' } as MediaStreamTrack));
  act(() => mockReport({ state: 'failed', reason: 'connection_deadline', samples: [], path: 'unknown', protocol: null }));
  await act(async () => { rejectPlayback(new DOMException('Playback cancelled', 'AbortError')); });
  expect(screen.getByRole('region', { name: 'Проверка видео WebRTC' })).toHaveTextContent('Проверка остановлена: connection_deadline');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(onOutcome).toHaveBeenCalledTimes(1);
  expect(onOutcome.mock.calls[0][0].reason).toBe('connection_deadline');
});

test('a playback failure while the transport is active remains a renderer failure', async () => {
  play.mockRejectedValueOnce(new DOMException('Decoder unavailable', 'NotSupportedError'));
  const onOutcome = jest.fn();
  render(<DirectVideoProbe deviceId="device" profile="host" automaticKey="viewer:host" onOutcome={onOutcome} />);
  act(() => mockTrack({ kind: 'video' } as MediaStreamTrack));
  await act(async () => {});
  expect(screen.getByRole('alert')).toHaveTextContent('Браузер не смог воспроизвести');
  expect(onOutcome).toHaveBeenCalledTimes(1);
  expect(onOutcome.mock.calls[0][0].reason).toBe('video_renderer_failed');
});
