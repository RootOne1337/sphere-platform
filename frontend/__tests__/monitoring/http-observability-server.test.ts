/** @jest-environment node */
import { getHttpMetrics, HTTP_QUERIES } from '@/lib/server/httpObservability';

const originalEnvironment = { ...process.env }, originalFetch = global.fetch;
const now = Date.parse('2026-10-05T14:00:00Z'), end = now / 1000;
const mockFetch = jest.fn();
const request = (query = '', token = 'valid-token') => new Request(`http://sphere.test/api/observability/http${query}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
const reply = (data: unknown, annotations = {}) => Response.json({ status: 'success', data, ...annotations });
const routeLabels = { method: 'GET', endpoint: '/api/v1/devices/{id}' };
function source(url: URL) {
    if (url.hostname === 'backend.test') return Response.json({ id: 'operator', role: 'super_admin' });
    if (url.pathname.endsWith('/targets')) return reply({ activeTargets: [{ labels: { job: 'sphere-backend' }, health: 'up', lastScrape: new Date(now - 5000).toISOString() }] });
    if (url.pathname.endsWith('/query_range')) return reply({ resultType: 'matrix', result: [{ metric: {}, values: [[end - 15, '2'], [end, url.searchParams.get('query') === HTTP_QUERIES.p95 ? '0.03' : '0']] }] });
    return reply({ resultType: 'vector', result: [{ metric: url.searchParams.get('query') === HTTP_QUERIES.statuses ? { status_code: '200' } : routeLabels, value: [end, '0'] }] });
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
async function snapshot(query = '') { const response = await getHttpMetrics(request(query)); expect(response.status).toBe(200); expect(response.headers.get('cache-control')).toBe('no-store'); return response.json(); }
it('requires current super-admin authorization before any metrics request', async () => {
    expect((await getHttpMetrics(request('', ''))).status).toBe(401);
    expect(mockFetch).not.toHaveBeenCalled();
    mockFetch.mockResolvedValueOnce(Response.json({ id: 'tenant', role: 'org_admin' }));
    expect((await getHttpMetrics(request())).status).toBe(403);
    expect(mockFetch).toHaveBeenCalledTimes(1);
});
it('fails closed if authorization is unavailable', async () => {
    mockFetch.mockRejectedValueOnce(new Error('unavailable'));
    expect((await getHttpMetrics(request())).status).toBe(503);
    expect(mockFetch).toHaveBeenCalledTimes(1);
});
it.each(['?window=7d', '?window=__proto__', '?window=1h&window=24h', '?endpoint=x', '?query=up', '?url=http://evil.test'])('rejects browser-selected PromQL or targets: %s', async query => {
    expect((await getHttpMetrics(request(query))).status).toBe(400);
    expect(mockFetch).toHaveBeenCalledTimes(1);
});
it.each([['1h', 3600, 15], ['6h', 21600, 30], ['24h', 86400, 60]])('bounds %s history and uses only fixed job/rate/quantile queries', async (window, seconds, step) => {
    const data = await snapshot(`?window=${window}`);
    expect(data.aggregationSeconds).toBe(300);
    const urls = mockFetch.mock.calls.map(call => call[0] as URL).filter(url => url.searchParams.has('query'));
    expect(urls).toHaveLength(9);
    urls.forEach(url => expect(Object.values(HTTP_QUERIES)).toContain(url.searchParams.get('query')));
    urls.filter(url => url.pathname.endsWith('query_range')).forEach(url => {
        expect(Number(url.searchParams.get('end')) - Number(url.searchParams.get('start'))).toBe(seconds);
        expect(Number(url.searchParams.get('step'))).toBe(step);
    });
    expect(data.metrics.rps.state).toBe('ready');
    expect(data.metrics.rps.series[0].points.at(-1).value).toBe(0);
    expect(data.endpoints.rows[0].serverErrorsRps).toBe(0);
});
it('distinguishes an empty rate and an undefined idle quantile from measured zero', async () => {
    mockFetch.mockImplementation(async (url: URL) => url.searchParams.get('query') === HTTP_QUERIES.rps ? reply({ resultType: 'matrix', result: [] }) : url.searchParams.get('query') === HTTP_QUERIES.p95 ? reply({ resultType: 'matrix', result: [{ metric: {}, values: [[end, 'NaN']] }] }) : source(url));
    const data = await snapshot();
    expect(data.metrics.rps).toMatchObject({ state: 'empty', series: [] });
    expect(data.metrics.p95.state).toBe('empty');
    expect(data.metrics.p95.series[0].points[0].value).toBeNull();
    expect(data.metrics.serverErrors.state).toBe('ready');
});
it.each(['warnings', 'infos'])('distinguishes a partial %s result without publishing it as zero or breaking other panels', async annotation => {
    mockFetch.mockImplementation(async (url: URL) => url.searchParams.get('query') === HTTP_QUERIES.rps ? reply({ resultType: 'matrix', result: [] }, { [annotation]: ['incomplete result'] }) : source(url));
    const data = await snapshot();
    expect(data.metrics.rps).toMatchObject({ state: 'partial', series: [] });
    expect(data.metrics.p95.state).toBe('ready');
});
it.each(['down', 'unknown', 'old', 'future', 'missing'])('hides rates from a %s collection source even if rate() returns finite values', async state => {
    mockFetch.mockImplementation(async (url: URL) => url.pathname.endsWith('/targets') ? reply({ activeTargets: state === 'missing' ? [] : [{ labels: { job: 'sphere-backend' }, health: ['down', 'unknown'].includes(state) ? state : 'up', lastScrape: new Date(now + (state === 'old' ? -60000 : state === 'future' ? 60000 : -5000)).toISOString() }] }) : source(url));
    const data = await snapshot();
    expect(data.metrics.rps).toMatchObject({ state: 'stale', series: [] });
    expect(data.endpoints).toMatchObject({ state: 'stale', rows: [] });
    expect(data.statuses.rows).toEqual([]);
});
it.each(['negative', 'infinity', 'oversized', 'duplicate', 'unordered', 'old'])('rejects %s history instead of showing a plausible measurement', async kind => {
    const values = kind === 'negative' ? [[end, '-1']] : kind === 'infinity' ? [[end, '+Inf']] : kind === 'duplicate' ? [[end, '1'], [end, '2']] : kind === 'unordered' ? [[end, '1'], [end - 15, '2']] : kind === 'old' ? [[end - 100, '1']] : Array.from({ length: 1442 }, () => [end, '1']);
    mockFetch.mockImplementation(async (url: URL) => url.searchParams.get('query') === HTTP_QUERIES.rps ? reply({ resultType: 'matrix', result: [{ metric: {}, values }] }) : source(url));
    expect((await snapshot()).metrics.rps.state).toBe(kind === 'old' ? 'stale' : 'error');
});
it('does not leak unnormalized upstream labels or accept unbounded endpoint rows', async () => {
    mockFetch.mockImplementation(async (url: URL) => url.searchParams.get('query') === HTTP_QUERIES.routes ? reply({ resultType: 'vector', result: Array.from({ length: 31 }, () => ({ metric: routeLabels, value: [end, '1'] })) }) : source(url));
    expect((await snapshot()).endpoints).toMatchObject({ state: 'error', rows: [] });
    mockFetch.mockImplementation(async (url: URL) => url.searchParams.get('query') === HTTP_QUERIES.routes ? reply({ resultType: 'vector', result: [{ metric: { ...routeLabels, endpoint: '/path?token=private' }, value: [end, '1'] }] }) : source(url));
    expect((await snapshot()).endpoints.rows).toEqual([]);
});
it('marks a missing per-route counter as partial and never invents zero', async () => {
    mockFetch.mockImplementation(async (url: URL) => url.searchParams.get('query') === HTTP_QUERIES.routeServerErrors ? reply({ resultType: 'vector', result: [] }) : source(url));
    const data = await snapshot();
    expect(data.endpoints.state).toBe('partial');
    expect(data.endpoints.rows[0].serverErrorsRps).toBeNull();
});
it('bounds response JSON and isolates an individual upstream error', async () => {
    mockFetch.mockImplementation(async (url: URL) => url.searchParams.get('query') === HTTP_QUERIES.p95 ? new Response('x'.repeat(2_000_001)) : source(url));
    const data = await snapshot();
    expect(data.metrics.p95).toMatchObject({ state: 'error', series: [] });
    expect(data.metrics.rps.state).toBe('ready');
});
