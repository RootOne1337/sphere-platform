import { fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ResourceMetricsPanel } from '@/src/features/monitoring/ResourceMetricsPanel';
import type { ResourceMetricsSnapshot } from '@/src/features/monitoring/resourceMetricsTypes';
import { api } from '@/lib/api';

let role = 'super_admin';
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/store', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({ user: { id: 'operator', role }, sessionVersion: 1 }) }));
const now = Date.parse('2026-10-05T14:00:00Z');
const signal = { state: 'ready' as const, reason: '', series: [{ name: 'Контейнер backend', points: [{ at: now - 15000, value: 2 }, { at: now, value: 0 }] }] };
const fixture: ResourceMetricsSnapshot = { source: 'prometheus', scope: 'backend-container-cgroup', observedAt: new Date(now).toISOString(), lastScrape: new Date(now - 5000).toISOString(), window: '1h', stepSeconds: 15, cpuAveragingSeconds: 60,
    metrics: { cpu: signal, cpuQuota: { state: 'empty', reason: 'Нет измерения лимита', series: [] }, memory: { ...signal, series: [{ name: 'Контейнер backend', points: [{ at: now, value: 0.5 }] }] }, memoryLimit: { ...signal, series: [{ name: 'Контейнер backend', points: [{ at: now, value: 2 }] }] } } };
function mount() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    return render(<QueryClientProvider client={client}><ResourceMetricsPanel window="1h" now={now} /></QueryClientProvider>);
}
beforeEach(() => { role = 'super_admin'; jest.mocked(api.get).mockReset().mockResolvedValue({ data: fixture }); });
it('does not request container-global data for tenant roles', () => { role = 'org_admin'; mount(); expect(api.get).not.toHaveBeenCalled(); });
it('labels the actual cgroup scope, cores and GiB without turning a missing quota into zero', async () => {
    mount();
    const cpu = await screen.findByRole('group', { name: 'CPU · использованные ядра' });
    expect(within(cpu).getByText('0 ядра')).toBeInTheDocument();
    const quota = screen.getByRole('group', { name: 'CPU · лимит контейнера' });
    expect(within(quota).getAllByText('Нет измерения').length).toBeGreaterThan(0);
    expect(within(quota).queryByText('0 ядра')).not.toBeInTheDocument();
    expect(screen.getByText('0,5 GiB')).toBeInTheDocument();
    expect(screen.getByText('2 GiB')).toBeInTheDocument();
    expect(screen.getByText(/RSS отдельных worker-процессов здесь не измеряется/)).toBeInTheDocument();
    expect(screen.getByText(/доступность источника не доказывает отсутствие утечек/)).toBeInTheDocument();
});
it.each(['empty', 'partial', 'error', 'stale'] as const)('shows %s memory independently from valid CPU', async state => {
    jest.mocked(api.get).mockResolvedValue({ data: { ...fixture, metrics: { ...fixture.metrics, memory: { state, reason: 'Неподтверждено', series: [] } } } });
    mount();
    const memory = await screen.findByRole('group', { name: 'Память · расход контейнера' });
    expect(within(memory).getAllByText('Нет измерения').length).toBeGreaterThan(0);
    expect(within(memory).queryByText('0 GiB')).not.toBeInTheDocument();
    expect(screen.getByText('0 ядра')).toBeInTheDocument();
});
it.each(['observedAt', 'lastScrape'] as const)('expires stale %s even when the other timestamp is fresh', async field => {
    jest.mocked(api.get).mockResolvedValue({ data: { ...fixture, [field]: new Date(now - 46000).toISOString() } });
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('Срез ресурсов устарел');
    expect(screen.queryByRole('group')).not.toBeInTheDocument();
});
it('hides cached measurements after failure, then recovers on refresh', async () => {
    mount(); await screen.findByRole('group', { name: 'Память · расход контейнера' });
    jest.mocked(api.get).mockRejectedValueOnce(new Error('offline'));
    fireEvent.click(screen.getByRole('button', { name: 'Обновить ресурсы backend' }));
    await screen.findByRole('alert');
    expect(screen.queryByText('0,5 GiB')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Обновить ресурсы backend' }));
    await screen.findByText('0,5 GiB');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
