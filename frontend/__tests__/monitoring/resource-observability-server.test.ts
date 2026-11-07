/** @jest-environment node */
import { getResourceMetrics, RESOURCE_QUERIES } from '@/lib/server/resourceObservability';

const originalEnvironment = { ...process.env }, originalFetch = global.fetch;
const now = Date.parse('2026-10-05T14:00:00Z'), end = now / 1000;
const mockFetch = jest.fn();
const request = (query = '', token = 'valid-token') => new Request(`http://sphere.test/api/observability/resources${query}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
const reply = (data: unknown, annotations = {}) => Response.json({ status: 'success', data, ...annotations });
const target = { labels: { job: 'sphere-backend' }, health: 'up', lastScrape: new Date(now - 5000).toISOString() };
function source(url: URL) {
    if (url.hostname === 'backend.test') return Response.json({ id: 'operator', role: 'super_admin' });
    if (url.pathname.endsWith('/targets')) return reply({ activeTargets: [target] });
    const query = url.searchParams.get('query');
    return reply({ resultType: 'matrix', result: query === RESOURCE_QUERIES.cpuQuota ? [] : [{ metric: {}, values: [[end - 15, '2'], [end, query === RESOURCE_QUERIES.cpu ? '0' : '2']] }] });
}
beforeEach(() => {
    jest.spyOn(Date, 'now').mockReturnValue(now);
    process.env.OBSERVABILITY_AUTH_API_URL = 'http://backend.test/api/v1/';
    process.env.OBSERVABILITY_PROMETHEUS_URL = 'http://prometheus.test/';
    global.fetch = mockFetch;
    mockFetch.mockReset().mockImplementation(async (url: URL) => source(url));
});
afterEach(() => { jest.restoreAllMocks(); process.env = { ...originalEnvironment }; });
afterAll(() => { global.fetch = originalFetch; });
async function snapshot(query = '') { const response = await getResourceMetrics(request(query)); expect(response.status).toBe(200); expect(response.headers.get('cache-control')).toBe('no-store'); return response.json(); }
it('requires current super-admin authorization before reading global container resources', async () => {
    expect((await getResourceMetrics(request('', ''))).status).toBe(401);
    expect(mockFetch).not.toHaveBeenCalled();
    mockFetch.mockResolvedValueOnce(Response.json({ id: 'tenant', role: 'org_admin' }));
    expect((await getResourceMetrics(request())).status).toBe(403);
    expect(mockFetch).toHaveBeenCalledTimes(1);
});
it('fails closed when authorization is unavailable', async () => {
    mockFetch.mockRejectedValueOnce(new Error('unavailable'));
    expect((await getResourceMetrics(request())).status).toBe(503);
    expect(mockFetch).toHaveBeenCalledTimes(1);
});
it.each(['?window=7d', '?window=__proto__', '?window=1h&window=24h', '?query=up', '?instance=host', '?url=http://evil.test'])('rejects uncontrolled PromQL, scope or target selection: %s', async query => {
    expect((await getResourceMetrics(request(query))).status).toBe(400);
    expect(mockFetch).toHaveBeenCalledTimes(1);
});
it.each([['1h', 3600, 15], ['6h', 21600, 30], ['24h', 86400, 60]])('bounds %s history and distinguishes real zero CPU from an unmeasured quota', async (window, seconds, step) => {
    const data = await snapshot(`?window=${window}`);
    expect(data.scope).toBe('backend-container-cgroup');
    expect(data.cpuAveragingSeconds).toBe(60);
    const urls = mockFetch.mock.calls.map(call => call[0] as URL).filter(url => url.searchParams.has('query'));
    expect(urls).toHaveLength(4);
    urls.forEach(url => {
        expect(Object.values(RESOURCE_QUERIES)).toContain(url.searchParams.get('query'));
        expect(Number(url.searchParams.get('end')) - Number(url.searchParams.get('start'))).toBe(seconds);
        expect(Number(url.searchParams.get('step'))).toBe(step);
    });
    expect(data.metrics.cpu.state).toBe('ready');
    expect(data.metrics.cpu.series[0].points.at(-1).value).toBe(0);
    expect(data.metrics.cpuQuota).toMatchObject({ state: 'empty', series: [] });
    expect(data.metrics.memoryLimit.state).toBe('ready');
});
it.each(['down', 'unknown', 'old', 'future', 'missing', 'multiple', 'malformed'])('hides values from %s discovery instead of merging containers or trusting old query results', async state => {
    const at = new Date(now + (state === 'old' ? -60000 : state === 'future' ? 60000 : -5000)).toISOString();
    const changed = { ...target, health: ['down', 'unknown'].includes(state) ? state : 'up', lastScrape: at };
    mockFetch.mockImplementation(async (url: URL) => url.pathname.endsWith('/targets') ? reply({ activeTargets: state === 'missing' ? [] : state === 'multiple' ? [changed, changed] : state === 'malformed' ? [null] : [changed] }) : source(url));
    const data = await snapshot();
    for (const value of Object.values(data.metrics)) expect(value).toMatchObject({ state: 'stale', series: [] });
    expect(data.lastScrape).toBeNull();
});
it.each(['warnings', 'infos'])('rejects partial %s CPU without losing valid memory measurements', async annotation => {
    mockFetch.mockImplementation(async (url: URL) => url.searchParams.get('query') === RESOURCE_QUERIES.cpu ? reply({ resultType: 'matrix', result: [] }, { [annotation]: ['incomplete result'] }) : source(url));
    const data = await snapshot();
    expect(data.metrics.cpu).toMatchObject({ state: 'partial', series: [] });
    expect(data.metrics.memory.state).toBe('ready');
});
it.each(['negative', 'infinity', 'oversized', 'duplicate', 'unordered', 'old', 'labels', 'NaN', 'blank'])('rejects %s CPU history without fabricating a measurement', async kind => {
    const values = kind === 'negative' ? [[end, '-1']] : kind === 'infinity' ? [[end, '+Inf']] : kind === 'duplicate' ? [[end, '1'], [end, '2']] : kind === 'unordered' ? [[end, '1'], [end - 15, '2']] : kind === 'old' ? [[end - 46, '1']] : kind === 'NaN' ? [[end, 'NaN']] : kind === 'blank' ? [[end, ' ']] : kind === 'oversized' ? Array.from({ length: 1442 }, () => [end, '1']) : [[end, '1']];
    mockFetch.mockImplementation(async (url: URL) => url.searchParams.get('query') === RESOURCE_QUERIES.cpu ? reply({ resultType: 'matrix', result: [{ metric: kind === 'labels' ? { pid: 'private-worker' } : {}, values }] }) : source(url));
    const data = await snapshot();
    expect(data.metrics.cpu).toMatchObject({ state: kind === 'old' ? 'stale' : kind === 'NaN' ? 'empty' : 'error', series: [] });
    expect(data.metrics.memory.state).toBe('ready');
});
it('preserves a missing sample within an otherwise fresh history', async () => {
    mockFetch.mockImplementation(async (url: URL) => url.searchParams.get('query') === RESOURCE_QUERIES.cpu ? reply({ resultType: 'matrix', result: [{ metric: {}, values: [[end - 30, '1'], [end - 15, 'NaN'], [end, '2']] }] }) : source(url));
    expect((await snapshot()).metrics.cpu.series[0].points).toEqual([{ at: now - 30000, value: 1 }, { at: now - 15000, value: null }, { at: now, value: 2 }]);
});
it('bounds upstream JSON and isolates a controller-query failure', async () => {
    mockFetch.mockImplementation(async (url: URL) => url.searchParams.get('query') === RESOURCE_QUERIES.memory ? new Response('x'.repeat(2_000_001)) : source(url));
    const data = await snapshot();
    expect(data.metrics.memory).toMatchObject({ state: 'error', series: [] });
    expect(data.metrics.cpu.state).toBe('ready');
});
