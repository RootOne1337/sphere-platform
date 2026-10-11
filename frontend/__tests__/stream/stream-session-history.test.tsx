import React from 'react';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StreamSessionHistoryPanel } from '@/src/features/stream/StreamSessionHistoryPanel';

const mockGet = jest.fn();
jest.mock('@/lib/api', () => ({ api: { get: (...args: unknown[]) => mockGet(...args) } }));
jest.mock('@/lib/store', () => ({ useAuthStore: (select: (state: unknown) => unknown) => select({ sessionVersion: 1 }) }));
let query: QueryClient;
const device = 'fixture-device';
beforeEach(() => { query = new QueryClient({ defaultOptions: { queries: { retry: false } } }); mockGet.mockReset(); });
afterEach(() => query.clear());
const view = () => render(<QueryClientProvider client={query}><StreamSessionHistoryPanel deviceId={device} /></QueryClientProvider>);

test('shows missing browser/RTT data as unmeasured and stale observation as stale', async () => {
  mockGet.mockResolvedValue({ data: { schema_version: 1, device_id: device, session_limit: 10, sessions: [{
    session_id: 'viewer', opened_at: '2026-10-10T10:00:00Z', state: 'stale',
    browser_summary: { max_decode_errors: 0, max_render_errors: 0 },
    direct_diagnostics: [{ profile: 'host', path: 'unknown', presented_frames: 0, reason: 'connection_deadline' }],
  }] } });
  view();
  expect(await screen.findByText('Связь с наблюдателем потеряна')).toBeInTheDocument();
  expect(screen.getByText(/Метрики браузера ещё не получены/)).toHaveTextContent('RTT управления не измерен');
  expect(screen.getByText(/Прямой тест:/)).toHaveTextContent('0 кадров');
});

test.each(['outage', 'foreign'])('does not turn an unavailable or foreign response into a healthy empty history: %s', async mode => {
  if (mode === 'outage') mockGet.mockRejectedValue(Error('503'));
  else mockGet.mockResolvedValue({ data: { schema_version: 1, device_id: 'another-device', session_limit: 10, sessions: [] } });
  view();
  expect(await screen.findByText(/История сейчас недоступна/)).toBeInTheDocument();
  expect(screen.queryByText(/Сеансов ещё нет/)).not.toBeInTheDocument();
});

test.each([
  ['direct_webrtc', 'Касания напрямую · WebRTC'],
  ['server_websocket', 'Касания через сервер · WebSocket'],
  [undefined, 'Маршрут касаний не сообщён'],
])('primary picture never invents the independent touch route: %s', async (control, label) => {
  mockGet.mockResolvedValue({ data: { schema_version: 1, device_id: device, session_limit: 10, sessions: [{
    session_id: 'viewer', opened_at: '2026-10-10T10:00:00Z', state: 'closed', browser_samples: [{
      transport: 'direct_webrtc', control_transport: control, rendered_frames: 1, incoming_fps: 0,
      direct_frames: 120, direct_fps: 15, direct_path: 'nat', direct_network_rtt_ms: 2,
      direct_state: 'failed', direct_failure: 'connection_deadline',
      direct_network: { local_candidates: 5, remote_candidates: 1, pairs: 1, checking_pairs: 1,
        failed_pairs: 0, succeeded_pairs: 0, requests_sent: 237, responses_received: null },
    }],
  }] } });
  view();
  expect(await screen.findByText(label!)).toBeInTheDocument();
  expect(screen.getByText(/ICE-запросы \/ ответы:/)).toHaveTextContent('237 / —');
  expect(screen.queryByText(/Управление через сервер/)).not.toBeInTheDocument();
});

test('native observation preserves known zero, unknown counters and the original snapshot age', async () => {
  mockGet.mockResolvedValue({ data: { schema_version: 1, device_id: device, session_limit: 10, sessions: [{
    session_id: 'viewer', opened_at: '2026-10-10T10:00:00Z', state: 'closed', native_direct_samples: [{
      received_at: '2026-10-10T10:00:05Z', stage: 'closed', kind: 'final', elapsed_ms: 5000,
      answer_sent: true, network_sample_age_ms: 3100, network: { local_candidates: 3, remote_candidates: 1,
        pairs: 1, checking_pairs: 1, failed_pairs: 0, succeeded_pairs: 0, requests_sent: 237,
        requests_received: null, responses_sent: null, responses_received: 0, dtls_state: 'new' },
    }],
  }] } });
  view();
  expect(await screen.findByText(/исходящие \/ входящие: 237 \/ —/)).toHaveTextContent('ответы исходящие / входящие: — / 0');
  expect(screen.getByText(/возраст сетевого среза/)).toHaveTextContent('3100 мс');
  expect(screen.getByText(/Этап: Соединение закрыто/)).toHaveTextContent('итог при закрытии');
});
