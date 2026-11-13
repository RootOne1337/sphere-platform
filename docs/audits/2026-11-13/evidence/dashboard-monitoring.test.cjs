const React = require('react');
const { cleanup, render, screen, within } = require('@testing-library/react');
const { createWrapper } = require('@/__tests__/helpers');

jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));

const { api } = require('@/lib/api');
const { useAuthStore } = require('@/lib/store');
const DashboardPage = require('@/app/(dashboard)/dashboard/page').default;
const MonitoringPage = require('@/app/(dashboard)/monitoring/page').default;
const { canAccessRoute } = require('@/src/features/access/routeAccess');
const observed = require('./dashboard-monitoring-result.json');

const stamp = () => new Date().toISOString();

beforeEach(() => {
  api.get.mockReset();
  useAuthStore.setState({ user: { id: 'fixture-user', org_id: observed.fleet_coverage.org_id,
    role: 'script_runner', email: 'fixture@example.test' }, sessionVersion: 1 });
});

afterEach(() => { cleanup(); useAuthStore.setState({ user: null, sessionVersion: 0 }); });

it('renders missing Redis presence as two offline devices on Dashboard and unavailable on Monitoring', async () => {
  const coverage = { ...observed.fleet_coverage, generated_at: stamp(),
    inventory: { ...observed.fleet_coverage.inventory, observed_at: stamp() } };
  api.get.mockImplementation(async url => {
    if (url === '/devices/status/fleet') return { data: observed.dashboard_summary };
    if (url === '/health') return { data: { status: 'ok', version: 'fixture' } };
    if (url === '/device-events') return { data: { items: [], total: 0, page: 1, per_page: 6, pages: 0 } };
    if (url === '/vpn/health' || url === '/vpn/pool/stats') throw { response: { status: 403 } };
    if (url === '/monitoring/fleet-coverage') return { data: coverage };
    if (url === '/monitoring/nodes') return { data: [] };
    if (url === '/monitoring/metrics') return { data: { ...observed.monitoring_metrics, observedAt: stamp() } };
    throw Error(`Unexpected GET ${url}`);
  });
  const main = render(React.createElement(DashboardPage), { wrapper: createWrapper() });
  expect(await screen.findByText('2 устройств')).toBeInTheDocument();
  expect(screen.getByRole('meter', { name: 'Не в сети' })).toHaveAttribute('aria-valuenow', '2');
  expect(screen.queryByText(/Не удалось получить сводку устройств/)).not.toBeInTheDocument();
  main.unmount();
  render(React.createElement(MonitoringPage), { wrapper: createWrapper() });
  const presence = await screen.findByRole('article', { name: 'Связь с Android' });
  expect(within(presence).getByText('Источник недоступен')).toBeInTheDocument();
  expect(within(presence).queryByText('Сообщили offline')).not.toBeInTheDocument();
});

it('shows telemetry degradation even when every implemented metric and probe succeeds', async () => {
  const nodes = [ ['backend', 'Backend API responder', 'API'], ['postgres', 'PostgreSQL', 'DB'],
    ['redis', 'Redis', 'CACHE'], ['disk', 'Диск', 'DISK'] ].map(([id, name, type]) => ({
    id, name, type, status: 'HEALTHY', cpu: null, ram: null, disk: null, uptime: '1m', details: {},
  }));
  api.get.mockImplementation(async url => {
    if (url === '/monitoring/nodes') return { data: nodes };
    if (url === '/monitoring/metrics') return { data: { ...observed.monitoring_metrics, observedAt: stamp() } };
    if (url === '/monitoring/fleet-coverage') return { data: { ...observed.fleet_coverage, generated_at: stamp() } };
    throw Error(`Unexpected GET ${url}`);
  });
  render(React.createElement(MonitoringPage), { wrapper: createWrapper() });
  expect(await screen.findByText('Проверки прошли · метрики частично недоступны')).toBeInTheDocument();
  expect(screen.getByText(/Не получены: активные туннели\./)).toBeInTheDocument();
  expect(screen.getByText('Активные туннели').nextElementSibling).toHaveTextContent('Не измеряется');
  expect(screen.queryByText('Все полученные проверки в норме')).not.toBeInTheDocument();
});

it('offers VPN navigation and queries forbidden VPN sources for a script runner', async () => {
  const permissions = observed.script_runner_permissions_checked;
  expect(canAccessRoute('/dashboard', permissions, true)).toBe(true);
  expect(canAccessRoute('/vpn', permissions, true)).toBe(false);
  api.get.mockImplementation(async url => {
    if (url === '/vpn/health' || url === '/vpn/pool/stats') throw { response: { status: 403 } };
    if (url === '/devices/status/fleet') return { data: observed.dashboard_summary };
    if (url === '/health') return { data: { status: 'ok', version: 'fixture' } };
    if (url === '/device-events') return { data: { items: [], total: 0, page: 1, per_page: 6, pages: 0 } };
    throw Error(`Unexpected GET ${url}`);
  });
  render(React.createElement(DashboardPage), { wrapper: createWrapper() });
  expect(await screen.findByText('Сводка пула недоступна')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Настройки VPN' })).toHaveAttribute('href', '/vpn');
  expect(api.get).toHaveBeenCalledWith('/vpn/health');
  expect(api.get).toHaveBeenCalledWith('/vpn/pool/stats');
});
