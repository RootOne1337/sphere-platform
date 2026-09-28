import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import DashboardPage from '@/app/(dashboard)/dashboard/page';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));

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
      '/devices/status/fleet': { total: 7, online: 2, busy: 1, connecting: 1, offline: 3 },
      '/health': { status: 'ok', version: '1.2.41' },
      '/vpn/pool/stats': { total_ips: 100, allocated: 20, free: 80, active_tunnels: 18, stale_handshakes: 2 },
      '/vpn/health': { status: 'ok', checks: {} },
      '/device-events': events,
    };
    return { data: dataByPath[url] } as never;
  });
}

afterEach(() => jest.clearAllMocks());

it('renders current fleet, service and event data from their API queries', async () => {
  mockHealthyEndpoints();
  const { client } = renderDashboard();

  await waitFor(() => expect(screen.getByText('Heartbeat recovered')).toBeInTheDocument());
  expect(screen.getByText('Обзор парка')).toBeInTheDocument();
  expect(screen.getByText('Всего устройств')).toBeInTheDocument();
  expect(screen.getByText('Выполняют задачи')).toBeInTheDocument();
  expect(screen.getByText('PH006')).toBeInTheDocument();
  expect(screen.getByText(/Версия 1\.2\.41/)).toBeInTheDocument();
  expect(screen.getByText(/18 активных туннелей/)).toBeInTheDocument();
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
      '/devices/status/fleet': { total: 1, online: 1, busy: 0, connecting: 0, offline: 0 },
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
