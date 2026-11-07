import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { FleetCoveragePanel } from '@/src/features/monitoring/FleetCoveragePanel';
import { parseFleetCoverage, type CoverageSignal, type FleetCoverageSnapshot } from '@/src/features/monitoring/fleetCoverageTypes';
import { api } from '@/lib/api';

const NOW = Date.parse('2026-10-05T18:00:00Z');
let org = 'current-org';
let version = 1;
jest.mock('@/lib/api', () => ({ api: { get: jest.fn() } }));
jest.mock('@/lib/store', () => ({ useAuthStore: (selector: (state: unknown) => unknown) => selector({ user: { id: 'operator', role: 'org_admin', org_id: org }, sessionVersion: version }) }));
function signal(source: string, counts: Record<string, number>, maxAge: number | null = null): CoverageSignal {
    return { state: 'ready', source, counts, observed_at: new Date(NOW).toISOString(), reason: '', max_age_seconds: maxAge };
}
const fixture: FleetCoverageSnapshot = {
    schema_version: 1, scope: 'current-tenant-active-inventory', org_id: 'current-org', generated_at: new Date(NOW).toISOString(), max_inventory_devices: 5000,
    inventory: signal('sql-active-inventory', { total: 19 }),
    presence: signal('redis-presence', { online: 14, busy: 0, connecting: 0, offline: 0, error: 0, unknown: 5 }, 120),
    android_vpn: signal('android-managed-vpn-report', { active: 0, inactive: 14, stale: 0, unknown: 5 }, 120),
    vpn_assignment: signal('sql-tenant-peers', { assigned: 0, provisioning: 0, revoking: 0, error: 0, free: 0, outside_active_inventory: 0 }),
    handshakes: signal('retained-sql-handshakes', { recent: 0, stale: 0, unknown: 0, inactive: 0 }, 180),
    transport_tunnels: { state: 'unmeasured', source: 'transport-tunnel-probes', reason: 'transport_probes_not_connected', counts: null, observed_at: null, max_age_seconds: null },
};
const copy = () => JSON.parse(JSON.stringify(fixture)) as FleetCoverageSnapshot;
function mount() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const tree = () => <QueryClientProvider client={client}><FleetCoveragePanel /></QueryClientProvider>;
    return { ...render(tree()), client, tree };
}
beforeEach(() => {
    org = 'current-org'; version = 1;
    jest.spyOn(Date, 'now').mockReturnValue(NOW);
    jest.mocked(api.get).mockReset().mockResolvedValue({ data: copy() });
});
afterEach(() => { jest.restoreAllMocks(); jest.useRealTimers(); });

it('shows explicit false, unknown and measured zero without inventing tunnel health', async () => {
    mount();
    const inventory = await screen.findByRole('article', { name: 'Инвентарь организации' });
    expect(within(inventory).getByText('19')).toBeInTheDocument();
    const android = screen.getByRole('article', { name: 'VPN · отчёты Android' });
    expect(within(android).getByText('14')).toBeInTheDocument();
    expect(within(android).getByText('5')).toBeInTheDocument();
    expect(within(android).getByText(/Это не проверка трафика/)).toBeInTheDocument();
    const transport = screen.getByRole('article', { name: 'Публичный транспорт' });
    expect(within(transport).getByText('Проверки не подключены')).toBeInTheDocument();
    expect(within(transport).queryByText('0')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Открыть парк' })).toHaveAttribute('href', '/devices');
});
it.each(['unavailable', 'forbidden', 'limited'] as const)('keeps inventory visible when an independent source is %s', async state => {
    const data = copy(); data.android_vpn = { ...data.android_vpn, state, counts: null, observed_at: null, reason: 'unconfirmed' };
    jest.mocked(api.get).mockResolvedValue({ data }); mount();
    const inventory = await screen.findByRole('article', { name: 'Инвентарь организации' });
    expect(within(inventory).getByText('19')).toBeInTheDocument();
    const android = screen.getByRole('article', { name: 'VPN · отчёты Android' });
    expect(within(android).getByText('Нет подтверждённых измерений')).toBeInTheDocument();
    expect(within(android).queryByText('14')).not.toBeInTheDocument();
});
it('hides cached counts after request failure and recovers on manual refresh', async () => {
    mount(); await screen.findByRole('article', { name: 'Инвентарь организации' });
    jest.mocked(api.get).mockRejectedValueOnce(new Error('offline'));
    fireEvent.click(screen.getByRole('button', { name: 'Обновить покрытие парка' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Предыдущие числа скрыты');
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Обновить покрытие парка' }));
    await screen.findByRole('article', { name: 'Инвентарь организации' });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
it('changes the cache scope with the session and rejects the previous tenant response', async () => {
    const view = mount(); await screen.findByRole('article', { name: 'Инвентарь организации' });
    expect(view.client.getQueryCache().findAll({ queryKey: ['fleet-coverage'] })[0].queryKey).toEqual(['fleet-coverage', 'current-org', 'operator', 'org_admin', 1]);
    org = 'different-org'; version++;
    view.rerender(view.tree());
    await screen.findByRole('alert');
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
    expect(view.client.getQueryCache().findAll({ queryKey: ['fleet-coverage'] }).map(q => q.queryKey)).toEqual([
        ['fleet-coverage', 'different-org', 'operator', 'org_admin', 2],
    ]);
});
it('cancels an in-flight read when the panel unmounts', async () => {
    jest.mocked(api.get).mockImplementation(() => new Promise(() => {}));
    const view = mount();
    expect(api.get).toHaveBeenCalledWith('/monitoring/fleet-coverage', expect.objectContaining({ timeout: 10000, signal: expect.any(AbortSignal) }));
    const signal = jest.mocked(api.get).mock.calls[0][1]!.signal as AbortSignal;
    expect(signal.aborted).toBe(false);
    view.unmount(); expect(signal.aborted).toBe(true);
});
it.each([-46000, 6000])('does not display an expired or future-dated snapshot (%s ms)', async offset => {
    const data = copy(); data.generated_at = new Date(NOW + offset).toISOString();
    for (const key of ['inventory', 'presence', 'android_vpn', 'vpn_assignment', 'handshakes'] as const) data[key].observed_at = data.generated_at;
    jest.mocked(api.get).mockResolvedValue({ data }); mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('Срез покрытия устарел');
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
});
it('expires a successful snapshot on the clock without requiring a new network response', async () => {
    jest.useFakeTimers({ now: NOW });
    mount(); await act(async () => { await jest.advanceTimersByTimeAsync(10); });
    expect(screen.getByRole('article', { name: 'Инвентарь организации' })).toBeInTheDocument();
    jest.setSystemTime(NOW + 46000);
    await act(async () => { await jest.advanceTimersByTimeAsync(5000); });
    expect(screen.getByRole('alert')).toHaveTextContent('Срез покрытия устарел');
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
});
it.each(['org_id', 'schema_version', 'scope', 'generated_at'])('rejects an incompatible envelope: %s', field => {
    const data = { ...copy(), [field]: 'invalid' };
    expect(() => parseFleetCoverage(data, org)).toThrow();
});
it.each([-1, 0.5, NaN, '1', null])('rejects an invalid measured count: %s', total => {
    const data = copy(); (data.inventory.counts as Record<string, unknown>).total = total;
    expect(() => parseFleetCoverage(data, org)).toThrow();
});
it('rejects plausible counts that contradict the measured active inventory', () => {
    const data = copy(); data.presence.counts!.online = 13;
    expect(() => parseFleetCoverage(data, org)).toThrow('Покрытие presence');
});
it('rejects fabricated measured tunnel health until a versioned producer exists', () => {
    const data = copy(); data.transport_tunnels = signal('transport-tunnel-probes', {});
    expect(() => parseFleetCoverage(data, org)).toThrow('публичного транспорта');
});
it('rejects numbers and timestamps attached to an unavailable source', () => {
    const data = copy(); data.presence.state = 'unavailable';
    expect(() => parseFleetCoverage(data, org)).toThrow('Неизмеренные значения');
});
it('rejects the wrong clock budget rather than silently relaxing freshness', () => {
    const data = copy(); data.presence.max_age_seconds = 3600;
    expect(() => parseFleetCoverage(data, org)).toThrow('срок presence');
});
