import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { DirectProbeAccess, parseProbeAdmission } from '@/src/features/stream/DirectProbeAccess';

let mockToken: string | null = 'fixture';
const mockGet = jest.fn();
const mockStop = jest.fn();
const mockStart = jest.fn((...args: unknown[]) => { void args; return mockStop; });
jest.mock('@/lib/store', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({ accessToken: mockToken }) }));
jest.mock('@/lib/api', () => ({ api: { get: (...args: unknown[]) => mockGet(...args) } }));
jest.mock('@/src/features/stream/directProbe', () => ({ startDirectProbe: (...args: unknown[]) => mockStart(...args) }));
const device = '753fd530-2f19-4e5e-98ba-769863678141';
const allowed = { schema_version: 1, device_id: device, enabled: true,
  profiles: ['host', 'public-stun'], scope: 'diagnostic_echo_only', max_duration_ms: 30000, samples: 20 };
beforeEach(() => { mockToken = 'fixture'; mockGet.mockReset(); mockStart.mockClear(); mockStop.mockClear();
  mockGet.mockResolvedValue({ data: allowed }); });

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
  { ...allowed, samples: 200 }, { ...allowed, device_id: 'foreign' }, null,
])('strict finite admission rejects unknown/broader claims', value => {
  expect(parseProbeAdmission(value, device)).toBeNull();
});
