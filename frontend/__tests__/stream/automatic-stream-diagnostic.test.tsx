import React from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AutomaticStreamDiagnostic } from '@/src/features/stream/AutomaticStreamDiagnostic';
import type { DirectProbeResult } from '@/src/features/stream/directProbe';

const mockGet = jest.fn();
let mockProbe: { profile: string; automaticKey: string; enabled: boolean; onOutcome: (value: DirectProbeResult, frames: number) => void };
const mockMounted = jest.fn();
jest.mock('@/lib/api', () => ({ api: { get: (...args: unknown[]) => mockGet(...args) } }));
jest.mock('@/lib/store', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ accessToken: 'fixture', sessionVersion: 1 }) }));
jest.mock('@/src/features/stream/DirectVideoProbe', () => ({ DirectVideoProbe: (props: typeof mockProbe) => { mockProbe = props; mockMounted(props); return <div />; } }));
const device = '753fd530-2f19-4e5e-98ba-769863678141';
const admission = { schema_version: 1, device_id: device, enabled: true, profiles: ['host', 'public-stun'],
  scope: 'diagnostic_echo_only', max_duration_ms: 30000, samples: 20, readonly_video_enabled: true };
const failed: DirectProbeResult = { state: 'failed', samples: [], path: 'unknown', protocol: null, reason: 'connection_deadline' };
let query: QueryClient;
beforeEach(() => { query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  mockProbe = { profile: '', automaticKey: '', enabled: false, onOutcome: () => {} };
  mockGet.mockReset().mockResolvedValue({ data: admission }); mockMounted.mockClear(); });
afterEach(() => query.clear());
const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={query}>{children}</QueryClientProvider>;

test('starts host video automatically only for an admitted live surface and does not restart on rerenders', async () => {
  const props = { deviceId: device, session: 'viewer', eligible: false, onDiagnostic: jest.fn(), onBusyChange: jest.fn() };
  const view = render(<AutomaticStreamDiagnostic {...props} />, { wrapper });
  await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));
  expect(mockMounted).not.toHaveBeenCalled();
  view.rerender(<AutomaticStreamDiagnostic {...props} eligible />);
  await waitFor(() => expect(mockProbe?.profile).toBe('host'));
  expect(mockProbe.automaticKey).toBe('viewer:host');
  act(() => mockProbe.onOutcome({ ...failed, state: 'finished', samples: Array(20).fill(5), path: 'host' }, 10));
  expect(props.onDiagnostic.mock.calls[0][0]).toMatchObject({ presented_frames: 10, trigger: 'automatic', echo_rtt_p95_ms: 5 });
  view.rerender(<AutomaticStreamDiagnostic {...props} eligible />);
  expect(mockProbe.profile).toBe('host');
});

test('a failed host video attempt permits exactly one NAT fallback without requiring any user button', async () => {
  const onDiagnostic = jest.fn();
  render(<AutomaticStreamDiagnostic deviceId={device} session="viewer" eligible onDiagnostic={onDiagnostic} onBusyChange={() => {}} />, { wrapper });
  await waitFor(() => expect(mockProbe.profile).toBe('host'));
  jest.useFakeTimers();
  act(() => mockProbe.onOutcome(failed, 0));
  act(() => jest.advanceTimersByTime(1000));
  expect(mockProbe.profile).toBe('public-stun');
  act(() => mockProbe.onOutcome(failed, 0));
  act(() => jest.advanceTimersByTime(60000));
  expect(onDiagnostic).toHaveBeenCalledTimes(2);
  expect(mockProbe.profile).toBe('public-stun');
  jest.useRealTimers();
});

test('missing admission and old APK video denial do not allocate a peer', async () => {
  mockGet.mockResolvedValue({ data: { ...admission, readonly_video_enabled: false } });
  render(<AutomaticStreamDiagnostic deviceId={device} session="viewer" eligible onDiagnostic={() => {}} onBusyChange={() => {}} />, { wrapper });
  await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));
  expect(mockMounted).not.toHaveBeenCalled();
});

test('a session replacement rejects late reports from the previous browser peer', async () => {
  const onDiagnostic = jest.fn(), busy = jest.fn();
  const view = render(<AutomaticStreamDiagnostic deviceId={device} session="first" eligible onDiagnostic={onDiagnostic} onBusyChange={busy} />, { wrapper });
  await waitFor(() => expect(mockProbe.automaticKey).toBe('first:host'));
  const old = mockProbe.onOutcome;
  view.rerender(<AutomaticStreamDiagnostic deviceId={device} session="second" eligible onDiagnostic={onDiagnostic} onBusyChange={busy} />);
  await waitFor(() => expect(mockProbe.automaticKey).toBe('second:host'));
  act(() => old(failed, 0));
  expect(onDiagnostic).not.toHaveBeenCalled();
});
