jest.mock('@/src/features/monitoring/HttpMetricsPanel', () => ({ HttpMetricsPanel: () => null }));
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
    jest.spyOn(Date, 'now').mockReturnValue(Date.parse(fixture.observedAt));
    mockAuth = { user: { id: 'operator', role: 'super_admin' }, sessionVersion: 1 };
    jest.mocked(api.get).mockReset().mockResolvedValue({ data: fixture });
    jest.mocked(api.post).mockReset().mockResolvedValue({ data: { expiresIn: 90 } });
});
afterEach(() => {
    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
    jest.restoreAllMocks();
    jest.useRealTimers();
});

it('does not fetch or render platform data for tenant roles', () => {
    mockAuth.user.role = 'org_admin';
    mount();
    expect(screen.getByText(/доступен супер-администратору/)).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
});
it('shows genuine zero/down readings, unknown history and panel coverage separately', async () => {
    mount();
    await screen.findByText('Сбор работает');
    expect(screen.getByText('Недоступен')).toBeInTheDocument();
    expect(screen.getAllByText('Нет измерения')).toHaveLength(3);
    expect(screen.getByText(/История CPU и памяти/)).toBeInTheDocument();
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

it('automatically recovers a failed source on the next 15-second poll without a manual refresh', async () => {
    jest.useFakeTimers({ now: Date.parse(fixture.observedAt) });
    mount();
    await act(async () => { await jest.advanceTimersByTimeAsync(1); });
    expect(screen.getByText('Сбор работает')).toBeInTheDocument();
    jest.mocked(api.get).mockRejectedValueOnce(new Error('source down'));
    await act(async () => { await jest.advanceTimersByTimeAsync(15_000); });
    expect(screen.queryByText('Сбор работает')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toBeInTheDocument();
    await act(async () => { await jest.advanceTimersByTimeAsync(15_000); });
    expect(screen.getByText('Сбор работает')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('does not show a successful but stale or future-dated snapshot as current', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { ...fixture, observedAt: '2026-09-30T03:08:00Z' } });
    mount();
    await screen.findByRole('alert');
    expect(screen.queryByText('Сбор работает')).not.toBeInTheDocument();
    jest.mocked(api.get).mockResolvedValue({ data: { ...fixture, observedAt: '2026-09-30T03:12:00Z' } });
    fireEvent.click(screen.getByRole('button', { name: 'Обновить Prometheus' }));
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
    expect(screen.queryByText('Сбор работает')).not.toBeInTheDocument();
});

it('does not call a target healthy when its last scrape is old or unknown', async () => {
    jest.mocked(api.get).mockResolvedValue({ data: { ...fixture, targets: [
        { ...fixture.targets[0], lastScrape: '2026-09-30T03:08:00Z' },
        { ...fixture.targets[0], job: 'new-source', health: 'unknown', lastScrape: '0001-01-01T00:00:00Z' },
    ] } });
    mount();
    await screen.findByText('Сбор задерживается');
    expect(screen.getByText('Состояние неизвестно')).toBeInTheDocument();
    expect(screen.queryByText('Сбор работает')).not.toBeInTheDocument();
    expect(screen.getByText(/нет подтверждённого времени/)).toBeInTheDocument();
});

it('unmounts background Grafana and authorizes it again when returning after cookie expiry', async () => {
    jest.useFakeTimers({ now: Date.parse(fixture.observedAt) });
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Открыть Grafana здесь' }));
    await act(async () => { await jest.advanceTimersByTimeAsync(1); });
    expect(screen.getByTitle('Grafana — наблюдаемость Sphere')).toBeInTheDocument();
    act(() => {
        Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
        document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(screen.queryByTitle('Grafana — наблюдаемость Sphere')).not.toBeInTheDocument();
    await act(async () => { await jest.advanceTimersByTimeAsync(120_000); });
    expect(api.post).toHaveBeenCalledTimes(1);
    act(() => {
        Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
        document.dispatchEvent(new Event('visibilitychange'));
    });
    await act(async () => { await jest.advanceTimersByTimeAsync(1); });
    expect(api.post).toHaveBeenCalledTimes(2);
    expect(screen.getByTitle('Grafana — наблюдаемость Sphere')).toBeInTheDocument();
});

it('aborts pending authorization when closing and ignores its late completion', async () => {
    let resolve!: (value: unknown) => void;
    jest.mocked(api.post).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'Открыть Grafana здесь' }));
    const signal = jest.mocked(api.post).mock.calls[0][2]?.signal as AbortSignal;
    fireEvent.click(screen.getByRole('button', { name: 'Закрыть Grafana' }));
    expect(signal.aborted).toBe(true);
    await act(async () => resolve({ data: { expiresIn: 90 } }));
    expect(screen.queryByTitle('Grafana — наблюдаемость Sphere')).not.toBeInTheDocument();
});
