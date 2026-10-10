import React from 'react';
import { act, fireEvent, render } from '@testing-library/react';
import { LiveDirectVideo } from '@/src/features/stream/LiveDirectVideo';
import type { DirectProbeResult } from '@/src/features/stream/directProbe';

let mockAdmission = { data: { admitted: true, profiles: ['host', 'public-stun'] }, isError: false };
let mockToken: string | null = 'fixture';
let mockReport: (result: DirectProbeResult) => void;
let mockTrack: (track: MediaStreamTrack) => void;
let mockFrame: VideoFrameRequestCallback;
const mockStop = jest.fn();
const mockStart = jest.fn((_url, _token, report, options) => {
  mockReport = report; mockTrack = options.onTrack;
  report({ state: 'gathering', samples: [], path: 'unknown', protocol: null });
  return mockStop;
});
jest.mock('@tanstack/react-query', () => ({ useQuery: () => mockAdmission }));
jest.mock('@/lib/store', () => ({ useAuthStore: (selector: (value: unknown) => unknown) => selector({ accessToken: mockToken, sessionVersion: 1 }) }));
jest.mock('@/src/features/stream/directProbe', () => ({ startDirectVideoSession: (...args: Parameters<typeof mockStart>) => mockStart(...args) }));
const epoch = '12345678-1234-4234-8234-123456789abc';
const expected = () => ({ captureEpoch: epoch, frameWidth: 960, frameHeight: 540 });
const connected: DirectProbeResult = { state: 'connected', samples: [2], path: 'host', protocol: 'udp', reason: null,
  videoBinding: { captureEpoch: epoch, width: 960, height: 540 } };
const pause = jest.fn(), play = jest.fn(async () => {}), cancel = jest.fn();
beforeEach(() => {
  jest.useFakeTimers(); jest.clearAllMocks(); mockToken = 'fixture';
  mockAdmission = { data: { admitted: true, profiles: ['host', 'public-stun'] }, isError: false };
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  Object.defineProperty(HTMLVideoElement.prototype, 'play', { configurable: true, value: play });
  Object.defineProperty(HTMLVideoElement.prototype, 'pause', { configurable: true, value: pause });
  Object.defineProperty(HTMLVideoElement.prototype, 'cancelVideoFrameCallback', { configurable: true, value: cancel });
  Object.defineProperty(HTMLVideoElement.prototype, 'requestVideoFrameCallback', { configurable: true,
    value: (callback: VideoFrameRequestCallback) => { mockFrame = callback; return 7; } });
  Object.defineProperty(globalThis, 'MediaStream', { configurable: true, value: class { constructor(readonly tracks: MediaStreamTrack[]) {} } });
});
afterEach(() => jest.useRealTimers());
function mount(onFrame = jest.fn(() => true), onObservation = jest.fn()) {
  const view = render(<LiveDirectVideo deviceId="device" session="viewer" eligible expectedCapture={expected}
    onFrame={onFrame} onObservation={onObservation} />);
  return { ...view, onFrame, onObservation };
}
const present = () => mockFrame(1, { width: 960, height: 540 } as VideoFrameCallbackMetadata);

test('automatic primary video promotes only a matching displayed frame, never an ICE result', async () => {
  const view = mount();
  expect(mockStart).toHaveBeenCalledTimes(1);
  expect(mockStart.mock.calls[0][3].controlledStunUrl).toBe('stun:stun.cloudflare.com:3478');
  act(() => mockReport(connected));
  expect(view.container.querySelector('video')).toHaveAttribute('data-direct-video-active', 'false');
  act(() => mockTrack({ kind: 'video' } as MediaStreamTrack)); await act(async () => {});
  act(present);
  expect(view.onFrame).toHaveBeenCalledTimes(1);
  expect(view.container.querySelector('video')).toHaveAttribute('data-direct-video-active', 'true');
  expect(view.onObservation).toHaveBeenLastCalledWith(expect.objectContaining({ active: true, frames: 1 }));
  view.unmount(); act(() => jest.runAllTicks());
  expect(mockStop).toHaveBeenCalledTimes(1); expect(jest.getTimerCount()).toBe(0);
});

test('periodic connected statistics cannot extend the first-picture deadline', () => {
  const view = mount(); act(() => mockReport(connected));
  act(() => jest.advanceTimersByTime(5000)); act(() => mockReport(connected));
  act(() => jest.advanceTimersByTime(3000));
  expect(mockStop).toHaveBeenCalledTimes(1);
  expect(view.onObservation).toHaveBeenLastCalledWith(expect.objectContaining({ active: false,
    result: expect.objectContaining({ reason: 'video_first_frame_timeout' }) }));
  view.unmount(); expect(jest.getTimerCount()).toBe(0);
});

test.each(['capture', 'geometry', 'renderer'])('invalid primary picture keeps server fallback: %s', async reason => {
  const view = mount(jest.fn(() => reason !== 'renderer'));
  act(() => {
    mockReport(reason === 'capture' ? { ...connected, videoBinding: { ...connected.videoBinding!, captureEpoch: 'other' } } : connected);
    mockTrack({ kind: 'video' } as MediaStreamTrack);
  }); await act(async () => {});
  act(() => mockFrame(1, { width: reason === 'geometry' ? 540 : 960, height: 540 } as VideoFrameCallbackMetadata));
  expect(view.container.querySelector('video')).toHaveAttribute('data-direct-video-active', 'false');
  expect(mockStop).toHaveBeenCalledTimes(1);
  if (reason !== 'renderer') expect(view.onFrame).not.toHaveBeenCalled();
  view.unmount();
});

test('transient failures retry with a bounded cadence while authorization rejection is terminal', () => {
  const view = mount();
  for (const delay of [1000, 2000, 4000, 60000]) {
    const count = mockStart.mock.calls.length;
    act(() => mockReport({ ...connected, state: 'failed', reason: 'connection_deadline' }));
    act(() => jest.advanceTimersByTime(delay - 1)); expect(mockStart).toHaveBeenCalledTimes(count);
    act(() => jest.advanceTimersByTime(1)); expect(mockStart).toHaveBeenCalledTimes(count + 1);
  }
  const count = mockStart.mock.calls.length;
  act(() => mockReport({ ...connected, state: 'failed', reason: 'video_access_rejected' }));
  act(() => jest.advanceTimersByTime(180000)); expect(mockStart).toHaveBeenCalledTimes(count);
  view.unmount(); expect(jest.getTimerCount()).toBe(0);
});

test('hidden, changed or retired viewer generations cannot revive old pictures', async () => {
  const view = mount(); const lateTrack = mockTrack, lateReport = mockReport;
  Object.defineProperty(document, 'hidden', { configurable: true, value: true });
  fireEvent(document, new Event('visibilitychange'));
  expect(mockStop).toHaveBeenCalledTimes(1);
  const orphan = { kind: 'video', stop: jest.fn() };
  act(() => { lateReport(connected); lateTrack(orphan as unknown as MediaStreamTrack); });
  expect(orphan.stop).toHaveBeenCalledTimes(1); expect(view.onFrame).not.toHaveBeenCalled();
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  fireEvent(document, new Event('visibilitychange')); expect(mockStart).toHaveBeenCalledTimes(2);
  view.rerender(<LiveDirectVideo deviceId="other" session="new" eligible expectedCapture={expected}
    onFrame={view.onFrame} onObservation={view.onObservation} />);
  expect(mockStop).toHaveBeenCalledTimes(2); expect(mockStart).toHaveBeenCalledTimes(3);
  view.unmount(); expect(mockStop).toHaveBeenCalledTimes(3); expect(jest.getTimerCount()).toBe(0);
});

test('missing native admission never creates a direct media peer', () => {
  mockAdmission.data.admitted = false;
  const view = mount(); expect(mockStart).not.toHaveBeenCalled(); view.unmount();
});
