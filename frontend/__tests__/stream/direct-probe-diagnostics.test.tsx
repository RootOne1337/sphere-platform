import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { DirectProbeDiagnostics } from '@/src/features/stream/DirectProbeDiagnostics';
import type { DirectProbeResult } from '@/src/features/stream/directProbe';
import { DirectProbeConfigurationError } from '@/src/features/stream/directProbeIce';

let mockReport: (value: DirectProbeResult) => void;
const mockStop = jest.fn();
const mockStart = jest.fn((_url: string, _token: string, report: typeof mockReport,
  options?: { controlledStunUrl?: string; relayGrant?: boolean }) => { void options; mockReport = report; return mockStop; });
jest.mock('@/lib/store', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({ accessToken: 'fixture' }) }));
jest.mock('@/src/features/stream/directProbe', () => ({ startDirectProbe: (...args: Parameters<typeof mockStart>) => mockStart(...args) }));

const initialStun = process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL;
const initialRelay = process.env.NEXT_PUBLIC_DIRECT_PROBE_RELAY;
beforeEach(() => { mockStart.mockReset(); mockStop.mockClear(); delete process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL;
  delete process.env.NEXT_PUBLIC_DIRECT_PROBE_RELAY;
  mockStart.mockImplementation((_url, _token, report) => { mockReport = report; return mockStop; }); });
afterAll(() => { if (initialRelay === undefined) delete process.env.NEXT_PUBLIC_DIRECT_PROBE_RELAY;
  else process.env.NEXT_PUBLIC_DIRECT_PROBE_RELAY = initialRelay;
  if (initialStun === undefined) delete process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL;
  else process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL = initialStun; });

test('failed ICE exposes measured zero replies and unknown RTT/path/DTLS without implying Android execution', () => {
  render(<DirectProbeDiagnostics deviceId="one" />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить прямой канал' }));
  act(() => mockReport({ state: 'failed', samples: [], path: 'unknown', protocol: null, reason: 'connection_deadline', iceProfile: 'host',
    iceState: 'checking', networkAgeAtStopMs: 99, network: { localCandidates: 1, remoteCandidates: 2,
      pairs: 2, checkingPairs: 2, failedPairs: 0, succeededPairs: 0, requestsSent: 4, responsesReceived: 0, dtlsState: null } }));
  expect(screen.getByRole('status')).toHaveTextContent('Соединение не подтверждено');
  expect(screen.getByText('Не измерен')).toBeInTheDocument();
  expect(screen.getByText('Не подтверждён')).toBeInTheDocument();
  expect(screen.getByText('checking / Не измерен')).toBeInTheDocument();
  expect(screen.getByText('4 / 0')).toBeInTheDocument();
  expect(screen.getByText('99 мс')).toBeInTheDocument();
  expect(screen.getByText(/Успешная пара не означает выбранный путь/)).toBeInTheDocument();
});

test('the build profile is forwarded while local addresses stay out of the diagnostic panel', () => {
  process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL = 'stun:10.0.2.2:3478';
  render(<DirectProbeDiagnostics deviceId="one" />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить прямой канал' }));
  expect(mockStart.mock.calls[0][3]).toEqual({ controlledStunUrl: 'stun:10.0.2.2:3478', relayGrant: false });
  act(() => mockReport({ state: 'connecting', samples: [], path: 'unknown', protocol: null, reason: null,
    iceProfile: 'controlled-stun' }));
  expect(screen.getByText('Локальный STUN')).toBeInTheDocument();
  expect(screen.queryByText(/10\.0\.2\.2/)).not.toBeInTheDocument();
});

test('the explicit public service is named as a diagnostic STUN provider, without implying TURN', () => {
  process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL = 'stun:stun.cloudflare.com:3478';
  render(<DirectProbeDiagnostics deviceId="one" />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить прямой канал' }));
  expect(mockStart.mock.calls[0][3]).toEqual({ controlledStunUrl: 'stun:stun.cloudflare.com:3478', relayGrant: false });
  act(() => mockReport({ state: 'connecting', samples: [], path: 'unknown', protocol: null, reason: null,
    iceProfile: 'public-stun' }));
  expect(screen.getByText('Публичный STUN · Cloudflare')).toBeInTheDocument();
  expect(screen.getByText(/TURN не подключён/)).toBeInTheDocument();
});

test('bad configuration is explained as a build problem and never shown as unavailable WebRTC', () => {
  mockStart.mockImplementation(() => { throw new DirectProbeConfigurationError(); });
  render(<DirectProbeDiagnostics deviceId="one" />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить прямой канал' }));
  expect(screen.getByText(/STUN-профиль сборки некорректен/)).toBeInTheDocument();
  expect(screen.queryByText(/браузер не смог подготовить/)).not.toBeInTheDocument();
});

test('relay grant build names the actual selected path separately from configuration', () => {
  process.env.NEXT_PUBLIC_DIRECT_PROBE_RELAY = 'true';
  render(<DirectProbeDiagnostics deviceId="one" />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить прямой канал' }));
  expect(mockStart.mock.calls[0][3]).toEqual({ controlledStunUrl: undefined, relayGrant: true });
  act(() => mockReport({ state: 'connected', samples: [5], path: 'relay', protocol: 'udp', reason: null, iceProfile: 'turn' }));
  expect(screen.getByText('Временный TURN-доступ')).toBeInTheDocument();
  expect(screen.getByText('Ретранслятор · UDP')).toBeInTheDocument();
  expect(screen.queryByText(/TURN не подключён/)).not.toBeInTheDocument();
});

test.each([
  ['gathering_deadline', /браузер не завершил сбор ICE-адресов/],
  ['signaling_deadline', /не получен и не установлен ответ APK/],
  ['connection_deadline', /после ответа APK канал не открылся/],
])('phase failure remains distinct: %s', (reason, text) => {
  render(<DirectProbeDiagnostics deviceId="one" />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить прямой канал' }));
  act(() => mockReport({ state: 'failed', samples: [], path: 'unknown', protocol: null, reason, iceProfile: 'host' }));
  expect(screen.getByText(text)).toBeInTheDocument();
});

test('changing device retires the old probe and clears its diagnostic snapshot', () => {
  const { rerender } = render(<DirectProbeDiagnostics deviceId="one" />);
  fireEvent.click(screen.getByRole('button', { name: 'Проверить прямой канал' }));
  act(() => mockReport({ state: 'connecting', samples: [], path: 'unknown', protocol: null, reason: null }));
  expect(screen.getByRole('status')).toHaveTextContent('APK ответил');
  rerender(<DirectProbeDiagnostics deviceId="two" />);
  expect(mockStop).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  expect(mockStart).toHaveBeenCalledTimes(1);
});
