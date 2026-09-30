import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { api } from '@/lib/api';
import { HistoryChart, ObservabilityPanel } from '@/src/features/monitoring/ObservabilityPanel';
import type { ObservabilitySnapshot } from '@/src/features/monitoring/observabilityTypes';

let mockAuth = { user: { id: 'operator', role: 'super_admin' }, sessionVersion: 1 };
jest.mock('@/lib/api', () => ({ api: { get: jest.fn(), post: jest.fn() } }));
jest.mock('@/lib/store', () => ({ useAuthStore: (selector: (state: typeof mockAuth) => unknown) => selector(mockAuth) }));
const fixture: ObservabilitySnapshot = {
    source: 'prometheus', observedAt: '2026-09-30T03:10:00Z', window: '1h', stepSeconds: 15,
    targets: [{ job: 'sphere-backend', health: 'up', lastScrape: '2026-09-30T03:09:59Z', durationSeconds: 0.002, error: '' }],
    alerts: [], charts: {
        availability: [{ name: 'backend', points: [{ at: 100000, value: 1 }, { at: 115000, value: null }, { at: 130000, value: 0 }] }],
        samples: [], scrapeDuration: [], storageSeries: [],
    },
};
function mount() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(<QueryClientProvider client={client}><ObservabilityPanel /></QueryClientProvider>);
    return { ...view, client };
}
beforeEach(() => {
    mockAuth = { user: { id: 'operator', role: 'super_admin' }, sessionVersion: 1 };
    jest.mocked(api.get).mockReset().mockResolvedValue({ data: fixture });
    jest.mocked(api.post).mockReset().mockResolvedValue({ data: { expiresIn: 90 } });
});

it('does not fetch or render platform data for tenant roles', () => {
    mockAuth.user.role = 'org_admin';
    mount();
    expect(screen.getByText(/доступен супер-администратору/)).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
});
it('shows genuine zero/down readings, unknown history and the worker aggregation limitation separately', async () => {
    mount();
    await screen.findByText('Сбор работает');
    expect(screen.getByText('Недоступен')).toBeInTheDocument();
    expect(screen.getAllByText('Нет измерения')).toHaveLength(3);
    expect(screen.getByText(/Общие RPS, p95, CPU/)).toBeInTheDocument();
    expect(screen.getByText(/Активных алертов по подключённым правилам нет/)).toBeInTheDocument();
});
it('preserves visual gaps instead of joining missing samples', () => {
    const { container } = render(<HistoryChart title="test chart" series={fixture.charts.availability} step={15} unit="" />);
    expect(container.querySelector('path')?.getAttribute('d')?.match(/M/g)).toHaveLength(2);
});
it('hides cached graphs after the source fails', async () => {
    mount();
    await screen.findByText('Сбор работает');
    jest.mocked(api.get).mockRejectedValueOnce({ response: { data: { detail: 'Prometheus offline' } } });
    fireEvent.click(screen.getByRole('button', { name: 'Обновить Prometheus' }));
    await screen.findByRole('alert');
    expect(screen.queryByText('Сбор работает')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Prometheus offline');
});
it('requests an explicit history window from the same-origin protected endpoint', async () => {
    mount();
    await screen.findByText('Сбор работает');
    fireEvent.click(screen.getByRole('button', { name: '24 часа' }));
    await waitFor(() => expect(api.get).toHaveBeenLastCalledWith('/api/observability', expect.objectContaining({ baseURL: '', params: { window: '24h' } })));
});
it('only embeds Grafana after successful session authorization and unmounts it on close', async () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Открыть Grafana здесь' }));
    await screen.findByTitle('Grafana — наблюдаемость Sphere');
    expect(api.post).toHaveBeenCalledWith('/api/observability/session', null, expect.objectContaining({ baseURL: '' }));
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть Grafana' }));
    expect(screen.queryByTitle('Grafana — наблюдаемость Sphere')).not.toBeInTheDocument();
});
it('does not mount an iframe after session renewal fails', async () => {
    jest.mocked(api.post).mockRejectedValueOnce({ response: { data: { detail: 'Session denied' } } });
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Открыть Grafana здесь' }));
    await screen.findByText('Session denied');
    expect(screen.queryByTitle('Grafana — наблюдаемость Sphere')).not.toBeInTheDocument();
});
