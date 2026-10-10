import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HttpMetricsPanel } from '@/src/features/monitoring/HttpMetricsPanel';
import type { HttpMetricsSnapshot } from '@/src/features/monitoring/httpMetricsTypes';
import { api } from '@/lib/api';

let role = 'super_admin';
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/store', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({ user: { id: 'operator', role }, sessionVersion: 1 }) }));
const now = Date.parse('2026-10-05T14:00:00Z');
const signal = { state: 'ready' as const, reason: '', series: [{ name: 'sphere-backend', points: [{ at: now - 15000, value: 2 }, { at: now, value: 0 }] }] };
const fixture: HttpMetricsSnapshot = { source: 'prometheus', observedAt: new Date(now).toISOString(), lastScrape: new Date(now - 5000).toISOString(), window: '1h', stepSeconds: 15, aggregationSeconds: 300,
    metrics: { rps: signal, p95: signal, serverErrors: signal, clientErrors: signal }, endpoints: { state: 'ready', reason: '', limit: 30, possiblyTruncated: false, rows: [{ method: 'GET', endpoint: '/api/v1/devices/{id}', rps: 2, p95Seconds: 0.04, serverErrorsRps: 0, clientErrorsRps: null }] }, statuses: { state: 'ready', reason: '', rows: [{ code: '200', rps: 2 }, { code: '401', rps: 0 }] } };
function mount() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const view = render(<QueryClientProvider client={client}><HttpMetricsPanel window="1h" now={now} /></QueryClientProvider>);
    return { ...view, client };
}
beforeEach(() => { role = 'super_admin'; jest.mocked(api.get).mockReset().mockResolvedValue({ data: fixture }); });
it('does not request global HTTP data for a tenant role', () => { role = 'org_admin'; mount(); expect(api.get).not.toHaveBeenCalled(); });
it('shows units, five-minute scope, a normalized route and its live drilldown', async () => {
    mount();
    const table = await screen.findByRole('table');
    expect(within(table).getByText('/api/v1/devices/{id}')).toBeInTheDocument();
    expect(screen.getByText(/скользящее окно 5 минут/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Разобрать GET /api/v1/devices/{id}' }));
    expect(screen.getByText('GET /api/v1/devices/{id}')).toBeInTheDocument();
    expect(screen.getByText('0,04 с')).toBeInTheDocument();
    expect(screen.getAllByText('0 запр/с').length).toBeGreaterThan(0);
    expect(screen.getByText('Нет измерения')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'missing' } });
    expect(within(table).queryByText('/api/v1/devices/{id}')).not.toBeInTheDocument();
    expect(screen.getByText(/маршруты по фильтру не найдены/)).toBeInTheDocument();
});
it.each(['empty', 'partial', 'error', 'stale'] as const)('renders %s signal separately from measured zero', async state => {
    jest.mocked(api.get).mockResolvedValue({ data: { ...fixture, metrics: { ...fixture.metrics, rps: { state, reason: 'Неподтверждено', series: [] } } } });
    mount();
    const panel = await screen.findByRole('group', { name: 'HTTP · запросы в секунду' });
    expect(within(panel).getAllByText('Нет измерения').length).toBeGreaterThan(0);
    expect(within(panel).queryByText('0 запр/с')).not.toBeInTheDocument();
});
it.each([-46000, 6000])('hides a stale or future-dated snapshot (%s ms)', async offset => {
    jest.mocked(api.get).mockResolvedValue({ data: { ...fixture, observedAt: new Date(now + offset).toISOString() } });
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('Срез HTTP-метрик устарел');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
});
it('hides cached values after an upstream error and recovers on refresh', async () => {
    mount(); await screen.findByRole('table');
    jest.mocked(api.get).mockRejectedValueOnce(new Error('offline'));
    fireEvent.click(screen.getByRole('button', { name: 'Обновить HTTP-метрики' }));
    await screen.findByRole('alert');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Обновить HTTP-метрики' }));
    await screen.findByRole('table');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
it('expires source measurements even when the cached HTTP snapshot itself is recent', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { ...fixture, lastScrape: new Date(now - 46000).toISOString() } });
    mount();
    await screen.findByRole('alert');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
});
it('drops stale endpoint details when the route leaves the top list', async () => {
    const { client } = mount(); await screen.findByRole('table');
    fireEvent.click(screen.getByRole('button', { name: 'Разобрать GET /api/v1/devices/{id}' }));
    client.setQueryData(['platform-http-metrics', 'operator', 1, '1h'], { ...fixture, endpoints: { ...fixture.endpoints, rows: [] } });
    await waitFor(() => expect(screen.getByText(/Выбранный маршрут отсутствует в новом срезе/)).toBeInTheDocument());
    expect(screen.queryByText('0,04 с')).not.toBeInTheDocument();
});
