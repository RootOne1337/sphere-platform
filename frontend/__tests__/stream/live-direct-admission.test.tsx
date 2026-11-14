import React from 'react';
import { act, render } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AxiosError, type AxiosResponse } from 'axios';
import { api } from '@/lib/api';
import { LiveDirectVideo } from '@/src/features/stream/LiveDirectVideo';

const mockStop = jest.fn();
const mockStart = jest.fn((...args: unknown[]) => { void args; return mockStop; });
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/store', () => ({ useAuthStore: (selector: (value: unknown) => unknown) => selector({ accessToken: 'fixture', sessionVersion: 1 }) }));
jest.mock('@/src/features/stream/directProbe', () => ({ startDirectVideoSession: (...args: unknown[]) => mockStart(...args) }));
const get = api.get as jest.Mock;
const admission = { schema_version: 1, device_id: 'device', enabled: true, scope: 'diagnostic_echo_only',
  profiles: ['host', 'public-stun'], max_duration_ms: 30000, samples: 20, live_video_enabled: true };
const httpError = (status: number) => new AxiosError('fixture', 'ERR_BAD_RESPONSE', undefined, undefined, { status } as AxiosResponse);
const flush = async () => { await act(async () => { await jest.advanceTimersByTimeAsync(1); }); };
const advance = async (milliseconds: number) => { await act(async () => { await jest.advanceTimersByTimeAsync(milliseconds); }); };

beforeEach(() => {
  jest.useFakeTimers(); jest.clearAllMocks(); get.mockReset();
  Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  Object.defineProperty(HTMLVideoElement.prototype, 'pause', { configurable: true, value: jest.fn() });
});
afterEach(() => jest.useRealTimers());
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const view = render(<QueryClientProvider client={client}><LiveDirectVideo deviceId="device" session={'1'.repeat(16)} eligible
    expectedCapture={() => ({ captureEpoch: '12345678-1234-4234-8234-123456789abc', frameWidth: 960, frameHeight: 540 })}
    onFrame={jest.fn(() => true)} onObservation={jest.fn()} /></QueryClientProvider>);
  return { ...view, retire: () => { view.unmount(); client.clear(); } };
}

test.each([408, 429, 503])('temporary capability HTTP %s recovers without a button and opens a peer only after admission', async status => {
  get.mockRejectedValueOnce(httpError(status)).mockRejectedValueOnce(httpError(status)).mockResolvedValue({ data: admission });
  const view = mount(); await flush();
  expect(get).toHaveBeenCalledTimes(1); expect(mockStart).not.toHaveBeenCalled();
  await advance(1000); expect(get).toHaveBeenCalledTimes(2); expect(mockStart).not.toHaveBeenCalled();
  await advance(2000); await flush();
  expect(get).toHaveBeenCalledTimes(3); expect(mockStart).toHaveBeenCalledTimes(1);
  view.retire(); await flush(); expect(mockStop).toHaveBeenCalledTimes(1);
});

test('unreachable capability reads stop after four reads with no background peer or unbounded retry', async () => {
  get.mockRejectedValue(new AxiosError('fixture', 'ERR_NETWORK'));
  const view = mount(); await flush(); await advance(7000); await flush(); await advance(60000);
  expect(get).toHaveBeenCalledTimes(4); expect(mockStart).not.toHaveBeenCalled();
  view.retire(); await flush(); expect(jest.getTimerCount()).toBe(0);
});

test.each([401, 403])('denied capability HTTP %s is never automatically retried', async status => {
  get.mockRejectedValue(httpError(status));
  const view = mount(); await flush(); await advance(60000);
  expect(get).toHaveBeenCalledTimes(1); expect(mockStart).not.toHaveBeenCalled();
  view.retire(); await flush(); expect(jest.getTimerCount()).toBe(0);
});

test('a malformed successful admission never creates a peer or retries the invalid grant', async () => {
  get.mockResolvedValue({ data: { ...admission, enabled: false } });
  const view = mount(); await flush(); await advance(60000);
  expect(get).toHaveBeenCalledTimes(1); expect(mockStart).not.toHaveBeenCalled();
  view.retire(); await flush(); expect(jest.getTimerCount()).toBe(0);
});
