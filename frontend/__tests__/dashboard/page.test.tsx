import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import DashboardPage from '@/app/(dashboard)/dashboard/page';
import { api } from '@/lib/api';
import type { FleetCoverageSnapshot } from '@/src/features/monitoring/fleetCoverageTypes';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/store', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({
  user: { id: 'operator', role: 'org_admin', org_id: 'org-1' }, sessionVersion: 1,
}) }));
let mockVpnAllowed = true;
let mockEventsAllowed = true;
jest.mock('@/src/features/access/Capabilities', () => ({ useCapabilities: () => ({
  verified: true, can: (permission: string) => permission !== 'vpn:read' || mockVpnAllowed,
  canAccessRoute: (path: string) => path === '/vpn' ? mockVpnAllowed : path === '/events' ? mockEventsAllowed : true,
}) }));

function coverage(presenceAvailable = true): FleetCoverageSnapshot {
  const at = new Date().toISOString();
  const observed = { state: 'ready', observed_at: at, reason: '', max_age_seconds: null } as const;
  const absent = { state: 'unavailable', observed_at: null, counts: null, reason: 'redis_unavailable', max_age_seconds: null } as const;
  return {
    schema_version: 1, scope: 'current-tenant-active-inventory', org_id: 'org-1', generated_at: at, max_inventory_devices: 5000,
    inventory: { ...observed, source: 'sql-active-inventory', counts: { total: 7 } },
    presence: presenceAvailable
      ? { ...observed, source: 'redis-presence', max_age_seconds: 120, counts: { online: 2, busy: 1, connecting: 1, offline: 1, error: 0, unknown: 2 } }
      : { ...absent, source: 'redis-presence' },
    android_vpn: { ...absent, source: 'android-managed-vpn-report' },
    vpn_assignment: { ...absent, source: 'sql-tenant-peers' },
    handshakes: { ...absent, source: 'retained-sql-handshakes' },
    transport_tunnels: { ...absent, state: 'unmeasured', source: 'transport-tunnel-probes', reason: 'transport_probes_not_connected' },
  };
}

function renderDashboard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const result = render(
    <QueryClientProvider client={client}>
      <DashboardPage />
    </QueryClientProvider>,
  );
  return { ...result, client };
}

function mockHealthyEndpoints(events: unknown = {
  items: [{
    id: 'event-1',
    org_id: 'org-1',
    device_id: 'device-1',
    device_name: 'PH006',
    event_type: 'device.status_change',
    severity: 'warning',
    message: 'Heartbeat recovered',
    account_id: null,
    account_login: null,
    task_id: null,
    pipeline_run_id: null,
    data: {},
    occurred_at: '2026-09-28T10:12:30Z',
    processed: false,
    created_at: '2026-09-28T10:12:30Z',
    updated_at: '2026-09-28T10:12:30Z',
  }],
  total: 1,
  page: 1,
  per_page: 6,
  pages: 1,
}) {
  jest.mocked(api.get).mockImplementation(async (url) => {
    const dataByPath: Record<string, unknown> = {
      '/monitoring/fleet-coverage': coverage(),
      '/health': { status: 'ok', version: '1.2.41' },
      '/vpn/pool/stats': { total_ips: 100, allocated: 20, free: 80, active_tunnels: 18, stale_handshakes: 2 },
      '/vpn/health': { status: 'ok', checks: {} },
      '/device-events': events,
    };
    return { data: dataByPath[url] } as never;
  });
}

afterEach(() => { mockVpnAllowed = true; mockEventsAllowed = true; jest.clearAllMocks(); });

it('renders current fleet, service and event data from their API queries', async () => {
  mockHealthyEndpoints();
  const { client } = renderDashboard();

  await waitFor(() => expect(screen.getByText('Heartbeat recovered')).toBeInTheDocument());
  expect(screen.getByText('Обзор парка')).toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Свежесть источников данных' })).toBeInTheDocument();
  expect(screen.getByText('Каталог устройств')).toBeInTheDocument();
  expect(screen.getByText('Health · backend')).toBeInTheDocument();
  expect(screen.getByText('Журнал событий')).toBeInTheDocument();
  expect(screen.getByText(/не подтверждает свежесть heartbeat устройства или видеокадра/i)).toBeInTheDocument();
  expect(screen.getByText('Всего устройств')).toBeInTheDocument();
  expect(screen.getByText('Выполняют задачи')).toBeInTheDocument();
  expect(screen.getByText('PH006')).toBeInTheDocument();
  expect(screen.getByText(/Версия 1\.2\.41/)).toBeInTheDocument();
  expect(screen.getByText(/18 активных по данным пула/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /Открыть реестр/ })).toHaveAttribute('href', '/devices');
  expect(screen.getByRole('link', { name: /Все события/ })).toHaveAttribute('href', '/events');
  expect(screen.queryByText(/FPS|Mbps|ping/i)).not.toBeInTheDocument();

  client.clear();
});

it('reports an unavailable event feed instead of substituting healthy or empty data', async () => {
  mockHealthyEndpoints();
  jest.mocked(api.get).mockImplementation(async (url) => {
    if (url === '/device-events') throw new Error('event API unavailable');
    const dataByPath: Record<string, unknown> = {
      '/monitoring/fleet-coverage': coverage(),
      '/health': { status: 'ok', version: 'test' },
      '/vpn/pool/stats': { total_ips: 1, allocated: 1, free: 0, active_tunnels: 1, stale_handshakes: 0 },
      '/vpn/health': { status: 'ok', checks: {} },
    };
    return { data: dataByPath[url] } as never;
  });
  const { client } = renderDashboard();

  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Данные сейчас недоступны'));
  expect(screen.queryByText('Пока нет событий для отображения.')).not.toBeInTheDocument();
  expect(screen.getByText('Обзор парка')).toBeInTheDocument();

  client.clear();
});

it('shows a real empty journal state when the event API returns no events', async () => {
  mockHealthyEndpoints({ items: [], total: 0, page: 1, per_page: 6, pages: 0 });
  const { client } = renderDashboard();

  await waitFor(() => expect(screen.getByText('Пока нет событий для отображения.')).toBeInTheDocument());
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();

  client.clear();
});

it('keeps inventory visible and hides fabricated offline counts when presence fails', async () => {
  mockHealthyEndpoints();
  const respond = jest.mocked(api.get).getMockImplementation()!;
  jest.mocked(api.get).mockImplementation((url, config) => url === '/monitoring/fleet-coverage'
    ? Promise.resolve({ data: coverage(false) }) : respond(url, config));
  const { client } = renderDashboard();

  expect(await screen.findByText('Источник связи с Android недоступен.')).toBeInTheDocument();
  const cards = screen.getByRole('region', { name: 'Сводные показатели устройств' });
  expect(within(cards).getByText('Всего устройств').nextElementSibling).toHaveTextContent('7');
  expect(within(cards).getAllByText('—')).toHaveLength(4);
  expect(screen.getByRole('link', { name: 'Диагностика источника связи' })).toHaveAttribute('href', '/monitoring#fleet-coverage-title');
  expect(jest.mocked(api.get).mock.calls.some(([url]) => url === '/devices/status/fleet')).toBe(false);
  client.clear();
});

it('keeps explicit offline, unknown and measured zero separate and hides disallowed VPN queries on refresh', async () => {
  mockVpnAllowed = false;
  mockHealthyEndpoints();
  const { client } = renderDashboard();
  await screen.findByText('7 устройств');
  expect(screen.getByRole('meter', { name: 'Не в сети' })).toHaveAttribute('aria-valuenow', '1');
  expect(screen.getByRole('meter', { name: 'Не подтверждено' })).toHaveAttribute('aria-valuenow', '2');
  expect(screen.getByRole('meter', { name: 'Ошибка связи' })).toHaveAttribute('aria-valuenow', '0');
  expect(screen.getByText('Нет разрешения VPN.')).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: /Настройки VPN/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Обновить данные' }));
  await waitFor(() => expect(jest.mocked(api.get).mock.calls.filter(([url]) => url === '/monitoring/fleet-coverage')).toHaveLength(2));
  expect(jest.mocked(api.get).mock.calls.some(([url]) => url.startsWith('/vpn/'))).toBe(false);
  client.clear();
});

it('links to diagnostics for observed problems and never polls the inaccessible event journal', async () => {
  mockEventsAllowed = false;
  mockHealthyEndpoints();
  const { client } = renderDashboard();

  const attention = await screen.findByRole('region', { name: 'Требуют проверки' });
  expect(within(attention).getByRole('link', { name: 'Связь не подтверждена · 2' }))
    .toHaveAttribute('href', '/monitoring#fleet-coverage-title');
  expect(within(attention).getByRole('link', { name: 'Устаревшие handshake VPN · 2' }))
    .toHaveAttribute('href', '/vpn');
  expect(screen.queryByRole('link', { name: /Все события/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Обновить данные' }));
  await waitFor(() => expect(jest.mocked(api.get).mock.calls.filter(([url]) => url === '/health')).toHaveLength(2));
  expect(jest.mocked(api.get).mock.calls.some(([url]) => url === '/device-events')).toBe(false);
  client.clear();
});
