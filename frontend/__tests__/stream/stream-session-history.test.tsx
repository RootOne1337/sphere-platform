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
