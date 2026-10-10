import React from 'react';
import { act, fireEvent, render as renderView, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DirectProbeAccess, parseProbeAdmission } from '@/src/features/stream/DirectProbeAccess';

let mockToken: string | null = 'fixture';
let queryClient: QueryClient;
const mockGet = jest.fn();
const mockStop = jest.fn();
const mockStart = jest.fn((...args: unknown[]) => { void args; return mockStop; });
jest.mock('@/lib/store', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({ accessToken: mockToken, sessionVersion: 0 }) }));
jest.mock('@/lib/api', () => ({ api: { get: (...args: unknown[]) => mockGet(...args) } }));
jest.mock('@/src/features/stream/directProbe', () => ({
  startDirectProbe: (...args: unknown[]) => mockStart(...args),
  startDirectVideoProbe: (...args: unknown[]) => mockStart(...args),
}));
const device = '753fd530-2f19-4e5e-98ba-769863678141';
const allowed = { schema_version: 1, device_id: device, enabled: true,
  profiles: ['host', 'public-stun'], scope: 'diagnostic_echo_only', max_duration_ms: 30000, samples: 20 };
function render(view: React.ReactElement) {
  return renderView(view, { wrapper: ({ children }) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider> });
}
beforeEach(() => { queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  jest.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  mockToken = 'fixture'; mockGet.mockReset(); mockStart.mockClear(); mockStop.mockClear();
  mockGet.mockResolvedValue({ data: allowed }); });
afterEach(() => { queryClient.clear(); });

test('ordinary UI reads admission once and creates no peer until the explicit start', async () => {
  render(<DirectProbeAccess deviceId={device} />);
  const start = await screen.findByRole('button', { name: 'Проверить прямой канал' });
  expect(mockGet).toHaveBeenCalledTimes(1);
  expect(mockGet.mock.calls[0][0]).toBe(`/devices/${device}/direct-probe-capabilities`);
  expect(mockStart).not.toHaveBeenCalled();
  fireEvent.click(start);
  expect(mockStart.mock.calls[0][3]).toEqual({ controlledStunUrl: 'stun:stun.cloudflare.com:3478', relayGrant: false });
});

test('profile changes retire the old probe and select only server-admitted profiles', async () => {
  render(<DirectProbeAccess deviceId={device} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Проверить прямой канал' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Профиль проверки' }), { target: { value: 'host' } });
  expect(mockStop).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить прямой канал' }));
  expect(mockStart.mock.calls[1][3]).toEqual({ controlledStunUrl: undefined, relayGrant: false });
  expect(screen.queryByRole('option', { name: /TURN/ })).not.toBeInTheDocument();
});

test.each(['disabled', 'failure', 'foreign', 'invalid'])('denied or unverified admission cannot start a peer: %s', async mode => {
  if (mode === 'failure') mockGet.mockRejectedValue(Error('unavailable'));
  else mockGet.mockResolvedValue({ data: mode === 'disabled' ? { ...allowed, enabled: false, profiles: [] }
    : mode === 'foreign' ? { ...allowed, device_id: 'other' } : { ...allowed, max_duration_ms: 60000 } });
  render(<DirectProbeAccess deviceId={device} />);
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  expect(screen.queryByRole('button', { name: 'Проверить прямой канал' })).not.toBeInTheDocument();
  expect(mockStart).not.toHaveBeenCalled();
});

test('late responses and the previous token admission cannot expose another device', async () => {
  let resolve: (value: unknown) => void = () => undefined;
  mockGet.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  const { rerender } = render(<DirectProbeAccess deviceId={device} />);
  rerender(<DirectProbeAccess deviceId="other" />);
  await act(async () => resolve({ data: allowed }));
  await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  expect(screen.queryByRole('button', { name: 'Проверить прямой канал' })).not.toBeInTheDocument();
  expect(mockGet.mock.calls[0][1].signal.aborted).toBe(true);
});

test('logout unmounts an active native probe and does not request admission anonymously', async () => {
  const { rerender } = render(<DirectProbeAccess deviceId={device} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Проверить прямой канал' }));
  mockToken = null;
  rerender(<DirectProbeAccess deviceId={device} />);
  expect(mockStop).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
  expect(mockGet).toHaveBeenCalledTimes(1);
});

test.each([
  { ...allowed, profiles: ['host', 'host'] }, { ...allowed, profiles: ['arbitrary'] },
  { ...allowed, enabled: false }, { ...allowed, scope: 'media_and_input' },
  { ...allowed, samples: 200 }, { ...allowed, device_id: 'foreign' },
  { ...allowed, readonly_video_enabled: 'true' },
  { ...allowed, enabled: false, profiles: [], readonly_video_enabled: true }, null,
])('strict finite admission rejects unknown/broader claims', value => {
  expect(parseProbeAdmission(value, device)).toBeNull();
});

test('the media selector needs independent server admission and never starts a peer on selection', async () => {
  const { unmount } = render(<DirectProbeAccess deviceId={device} />);
  await screen.findByRole('button', { name: 'Проверить прямой канал' });
  expect(screen.queryByRole('combobox', { name: 'Что проверить' })).not.toBeInTheDocument();
  unmount(); mockGet.mockResolvedValue({ data: { ...allowed, readonly_video_enabled: true } });
  render(<DirectProbeAccess deviceId={device} />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'Что проверить' }), { target: { value: 'video' } });
  expect(screen.getByRole('button', { name: 'Проверить видео с APK' })).toBeEnabled();
  expect(mockStart).not.toHaveBeenCalled();
  expect(screen.queryByRole('button', { name: 'Проверить прямой канал' })).not.toBeInTheDocument();
});

test('online/OTA invalidation reveals new video support without reloading or starting a peer', async () => {
  render(<DirectProbeAccess deviceId={device} />);
  await screen.findByRole('button', { name: 'Проверить прямой канал' });
  expect(screen.queryByRole('combobox', { name: 'Что проверить' })).not.toBeInTheDocument();
  mockGet.mockResolvedValue({ data: { ...allowed, readonly_video_enabled: true } });
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ['direct-probe-capabilities'] }); });
  expect(await screen.findByRole('combobox', { name: 'Что проверить' })).toBeInTheDocument();
  expect(mockGet).toHaveBeenCalledTimes(2);
  expect(mockStart).not.toHaveBeenCalled();
});

test('an unrelated fleet query does not reread capabilities and a failed read can be retried without a peer', async () => {
  render(<DirectProbeAccess deviceId={device} />);
  await screen.findByRole('button', { name: 'Проверить прямой канал' });
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ['tasks'] }); });
  expect(mockGet).toHaveBeenCalledTimes(1);
  mockGet.mockRejectedValueOnce(Error('temporary failure'));
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ['direct-probe-capabilities'] }); });
  fireEvent.click(await screen.findByRole('button', { name: 'Обновить доступ к проверке' }));
  expect(await screen.findByRole('button', { name: 'Проверить прямой канал' })).toBeEnabled();
  expect(mockGet).toHaveBeenCalledTimes(3);
  expect(mockStart).not.toHaveBeenCalled();
});

test('a running finite probe keeps its mode/profile through invalidation and reconciles when it finishes', async () => {
  mockGet.mockResolvedValue({ data: { ...allowed, readonly_video_enabled: true } });
  render(<DirectProbeAccess deviceId={device} />);
  const mode = await screen.findByRole('combobox', { name: 'Что проверить' });
  fireEvent.click(screen.getByRole('button', { name: 'Проверить прямой канал' }));
  const update = mockStart.mock.calls[0][2] as (value: unknown) => void;
  act(() => { update({ state: 'connected', samples: [], path: 'host', protocol: 'udp' }); });
  expect(mode).toBeDisabled();
  await act(async () => { await queryClient.invalidateQueries({ queryKey: ['direct-probe-capabilities'] }); });
  expect(mockGet).toHaveBeenCalledTimes(1);
  expect(mockStop).not.toHaveBeenCalled();
  act(() => { update({ state: 'completed', samples: [1], path: 'host', protocol: 'udp' }); });
  await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
  expect(mode).toBeEnabled();
  expect(mockStart).toHaveBeenCalledTimes(1);
});
