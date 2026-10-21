import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { AppVpnRuntimePanel } from '@/src/features/vpn/AppVpnRuntimePanel';
import { parseVpnRuntimePage, runtimeFreshness } from '@/src/features/vpn/runtimeTypes';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
const get = jest.mocked(api.get);
const id = 'a27c2ce8-90fe-453e-b465-65f5efe5cd34';
const now = Date.now();
const iso = new Date(now).toISOString();
const row = { device_id: id, name: 'auto-ph-030', model: 'AQUOS', android_version: '9', status: 'online', agent_version: '1.2.84-dev', last_heartbeat: iso,
  freshness: 'fresh' as const, observation: { received_at: iso, ws_session_id: 'control-session', snapshot: {
    requestId: null, sessionId: id, profileRevisionId: null, phase: 'AWAITING_HANDSHAKE' as const, reason: null, nativeVersion: '3.1',
    handshakeEpochSeconds: null, rxBytes: null, txBytes: null, sampledAtEpochMs: now, providerPid: 23901,
  } } };
const page = { items: [row], total: 26, page: 1, page_size: 25, as_of: iso };
beforeEach(() => {
  jest.resetAllMocks();
  useAuthStore.setState({ user: { id: 'actor', org_id: 'org', role: 'org_admin', email: 'test@example.org' }, sessionVersion: 1 });
  get.mockImplementation(async url => ({ data: url === '/groups' ? [{ id, name: 'Лаборатория' }] : page }));
});
function show() { const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } }); return render(<QueryClientProvider client={qc}><AppVpnRuntimePanel /></QueryClientProvider>); }
it('never turns a ready transport or missing handshake into a connected tunnel', async () => {
  show();
  expect(await screen.findByText('auto-ph-030')).toBeInTheDocument();
  expect(screen.getByText('Ожидает handshake')).toBeInTheDocument();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Диагностика VPN auto-ph-030' }));
  expect(await screen.findByRole('dialog')).toHaveTextContent('Handshake сам по себе не подтверждает');
  expect(screen.queryByText('0 Б')).not.toBeInTheDocument();
});
it('expires retained evidence even if an API response is repeatedly returned', () => {
  expect(runtimeFreshness(row, iso, now)).toBe('fresh');
  expect(runtimeFreshness(row, new Date(now + 20000).toISOString(), now + 20000)).toBe('stale');
});
it.each([
  { ...page, page: 2 }, { ...page, items: [row, row] },
  { ...page, items: [{ ...row, observation: null }] },
  { ...page, items: [{ ...row, observation: { ...row.observation, snapshot: { ...row.observation.snapshot, config_text: 'private-sentinel' } } }] },
])('rejects malformed or secret-bearing runtime responses', value => { expect(() => parseVpnRuntimePage(value, 1)).toThrow(); });
it('keeps API failure separate from an empty fleet', async () => {
  get.mockRejectedValue(new Error('unavailable')); show();
  expect(await screen.findByRole('alert')).toHaveTextContent('Состояние VPN недоступно');
  expect(screen.queryByText('Устройств по этому фильтру нет.')).not.toBeInTheDocument();
});
it('shows newly received evidence immediately between UI clock ticks', async () => {
  const clock = jest.spyOn(Date, 'now').mockReturnValue(now);
  let deliver!: (value: unknown) => void;
  get.mockImplementation(async url => url === '/groups' ? { data: [] } : new Promise(resolve => { deliver = resolve; }));
  try {
    show();
    const received = now + 500;
    clock.mockReturnValue(received);
    await act(async () => deliver({ data: { ...page, as_of: new Date(received).toISOString(), items: [{ ...row, observation: {
      ...row.observation, received_at: new Date(received).toISOString(), snapshot: { ...row.observation.snapshot, sampledAtEpochMs: received },
    } }] } }));
    expect(await screen.findByText('Свежий отчёт')).toBeInTheDocument();
    expect(screen.queryByText('Отчёт устарел')).not.toBeInTheDocument();
  } finally { clock.mockRestore(); }
});
