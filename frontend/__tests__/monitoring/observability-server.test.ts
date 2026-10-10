/** @jest-environment node */
import { createGrafanaSession, getObservability, proxyGrafana } from '@/lib/server/observability';

const admin = { id: 'operator', role: 'super_admin' };
const request = (path = '', token = 'valid-token') => new Request(`http://sphere.test/api/observability${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
const ok = (data: unknown) => Response.json(data);
const prom = (data: unknown) => ok({ status: 'success', data });
const originalEnvironment = { ...process.env };
const mockFetch = jest.fn();
const originalFetch = global.fetch;

beforeEach(() => {
    process.env.OBSERVABILITY_AUTH_API_URL = 'http://backend.test/api/v1/';
    process.env.OBSERVABILITY_PROMETHEUS_URL = 'http://prometheus.test/';
    process.env.OBSERVABILITY_GRAFANA_URL = 'http://grafana.test/';
    process.env.OBSERVABILITY_SESSION_SECRET = 'test-only-signature-key-with-32-characters';
    global.fetch = mockFetch;
    mockFetch.mockReset().mockImplementation(async (url: URL) => {
        if (url.hostname === 'backend.test') return ok(admin);
        if (url.pathname.endsWith('/targets')) return prom({ activeTargets: [{ labels: { job: 'sphere-backend' }, health: 'up', lastScrape: '2026-09-30T00:00:00Z', lastScrapeDuration: 0.003, lastError: '' }] });
        if (url.pathname.endsWith('/alerts')) return prom({ alerts: [] });
        return prom({ resultType: 'matrix', result: [{ metric: { instance: 'backend:8000' }, values: [[100, '1'], [115, 'NaN'], [130, '0']] }] });
    });
});
afterEach(() => { process.env = { ...originalEnvironment }; });
afterAll(() => { global.fetch = originalFetch; });

describe('Platform observability authorization and bounded queries', () => {
    it('does not contact upstream without a Bearer token', async () => {
        expect((await getObservability(request('', ''))).status).toBe(401);
        expect(mockFetch).not.toHaveBeenCalled();
    });
    it.each(['viewer', 'org_admin', 'device_manager', 'api_user'])('does not expose global telemetry to %s', async role => {
        mockFetch.mockResolvedValueOnce(ok({ id: 'tenant-user', role }));
        expect((await getObservability(request())).status).toBe(403);
        expect(mockFetch).toHaveBeenCalledTimes(1);
    });
    it('rejects an expired token and does not query Prometheus', async () => {
        mockFetch.mockResolvedValueOnce(new Response(null, { status: 401 }));
        expect((await getObservability(request())).status).toBe(401);
        expect(mockFetch).toHaveBeenCalledTimes(1);
    });
    it('fails closed when the auth service is unavailable', async () => {
        mockFetch.mockRejectedValueOnce(new Error('timeout'));
        expect((await getObservability(request())).status).toBe(503);
        expect(mockFetch).toHaveBeenCalledTimes(1);
    });
    it.each(['?window=toString', '?window=__proto__', '?window=7d', '?query=secret', '?url=http://evil.test'])('rejects arbitrary query parameters %s', async path => {
        expect((await getObservability(request(path))).status).toBe(400);
        expect(mockFetch).toHaveBeenCalledTimes(1);
    });
    it('preserves unknown samples and bounds the maximum history range', async () => {
        const response = await getObservability(request('?window=24h'));
        expect(response.status).toBe(200);
        expect(response.headers.get('cache-control')).toBe('no-store');
        const data = await response.json();
        expect(data.charts.availability[0].points).toEqual([{ at: 100000, value: 1 }, { at: 115000, value: null }, { at: 130000, value: 0 }]);
        expect(data.stepSeconds).toBe(60);
        const urls: URL[] = mockFetch.mock.calls.map(call => call[0]);
        expect(urls[0].pathname).toBe('/api/v1/auth/me');
        const ranges = urls.filter(url => url.pathname.endsWith('query_range'));
        expect(ranges).toHaveLength(4);
        ranges.forEach(url => {
            expect(Number(url.searchParams.get('end')) - Number(url.searchParams.get('start'))).toBe(86400);
            expect(url.searchParams.get('step')).toBe('60');
            expect(url.searchParams.get('query')).not.toMatch(/rate|quantile/);
        });
    });
    it('does not turn a malformed or partial Prometheus response into healthy zeros', async () => {
        mockFetch.mockResolvedValueOnce(ok(admin)).mockResolvedValueOnce(ok({ status: 'success', warnings: ['partial'], data: { activeTargets: [] } }));
        const response = await getObservability(request());
        expect(response.status).toBe(503);
        expect(await response.json()).not.toHaveProperty('charts');
    });
    it('rejects a source response larger than the configured JSON bound', async () => {
        mockFetch.mockResolvedValueOnce(ok(admin)).mockResolvedValueOnce(new Response('x'.repeat(2_000_001)));
        expect((await getObservability(request())).status).toBe(503);
    });
    it('rejects credentials in the configured upstream URL', async () => {
        process.env.OBSERVABILITY_PROMETHEUS_URL = 'http://secret:password@prometheus.test';
        expect((await getObservability(request())).status).toBe(503);
        expect(mockFetch).toHaveBeenCalledTimes(1);
    });
});

async function sessionCookie() {
    const result = await createGrafanaSession(request());
    expect(result.status).toBe(200);
    return result.headers.get('set-cookie')!.split(';')[0];
}
function grafanaRequest(cookie: string, method = 'GET', body?: string) {
    return new Request('http://sphere.test/observability/grafana/api/ds/query', { method, headers: { cookie, authorization: 'Bearer must-not-forward', 'X-WEBAUTH-USER': 'evil-admin' }, body });
}
function grafanaResponse(response: Response) {
    mockFetch.mockImplementation(async (url: URL) => url.hostname === 'backend.test' ? ok(admin) : response);
}

describe('Read-only Grafana bridge', () => {
    const featurePath = ['apis', 'features.grafana.app', 'v0alpha1', 'namespaces', 'default', 'ofrep', 'v1', 'evaluate', 'flags'];
    it('reads Grafana boot feature flags with a fixed context, never a browser-selected identity', async () => {
        const cookie = await sessionCookie();
        mockFetch.mockClear();
        grafanaResponse(ok({ flags: [{ key: 'test', value: true }] }));
        const response = await proxyGrafana(grafanaRequest(cookie, 'POST', JSON.stringify({ context: { targetingKey: 'other-org', userId: 'admin', email: 'private@example.test' } })), featurePath);
        expect(response.status).toBe(200);
        const [url, options] = mockFetch.mock.calls.at(-1)!;
        expect(url.pathname).toBe('/observability/grafana/' + featurePath.join('/'));
        expect(options.body).toBe(JSON.stringify({ context: { targetingKey: 'default' } }));
        expect(options.headers).toEqual({ 'X-WEBAUTH-USER': 'sphere-observer', Accept: '*/*', 'Content-Type': 'application/json' });
    });
    it.each(['{}', '[]', '{', '{"context":[]}', '{"context":{"targetingKey":1}}'])('rejects malformed feature evaluation %s', async body => {
        const cookie = await sessionCookie();
        mockFetch.mockClear();
        expect((await proxyGrafana(grafanaRequest(cookie, 'POST', body), featurePath)).status).toBe(400);
        expect(mockFetch).not.toHaveBeenCalled();
    });
    it('bounds feature evaluation and rejects cross-site requests before contacting Grafana', async () => {
        const cookie = await sessionCookie();
        mockFetch.mockClear();
        const crossSite = new Request('http://sphere.test/observability/grafana/' + featurePath.join('/'), { method: 'POST', headers: { cookie, 'sec-fetch-site': 'cross-site' }, body: '{"context":{"targetingKey":"default"}}' });
        expect((await proxyGrafana(crossSite, featurePath)).status).toBe(403);
        expect((await proxyGrafana(grafanaRequest(cookie, 'POST', 'x'.repeat(16_385)), featurePath)).status).toBe(413);
        expect(mockFetch).not.toHaveBeenCalled();
    });
    it.each([
        ['POST', [...featurePath.slice(0, 4), 'other-org', ...featurePath.slice(5)]],
        ['POST', [...featurePath, 'flag-key']],
        ['POST', ['ofrep', 'v1', 'evaluate', 'flags']],
        ['PUT', featurePath],
        ['DELETE', featurePath],
    ])('does not widen the feature read allowlist to %s %j', async (method, path) => {
        const cookie = await sessionCookie();
        mockFetch.mockClear();
        expect((await proxyGrafana(grafanaRequest(cookie, method as string, '{}'), path as string[])).status).toBe(405);
        expect(mockFetch).not.toHaveBeenCalled();
    });
    it('issues an HttpOnly, path-scoped, short-lived cookie only to a verified admin', async () => {
        process.env.OBSERVABILITY_SECURE_COOKIE = 'true';
        const response = await createGrafanaSession(request());
        expect(response.headers.get('set-cookie')).toMatch(/HttpOnly; SameSite=Strict; Path=\/observability\/grafana; Max-Age=90; Secure$/);
        expect(response.headers.get('set-cookie')).not.toContain('valid-token');
        mockFetch.mockResolvedValueOnce(ok({ id: 'tenant', role: 'viewer' }));
        expect((await createGrafanaSession(request())).status).toBe(403);
    });
    it('blocks anonymous, tampered and expired cookies before accessing Grafana', async () => {
        expect((await proxyGrafana(grafanaRequest(''), [])).status).toBe(401);
        const cookie = await sessionCookie();
        mockFetch.mockClear();
        expect((await proxyGrafana(grafanaRequest(`${cookie}x`), [])).status).toBe(401);
        const clock = jest.spyOn(Date, 'now').mockReturnValue(Date.now() + 91000);
        expect((await proxyGrafana(grafanaRequest(cookie), [])).status).toBe(401);
        clock.mockRestore();
        expect(mockFetch).not.toHaveBeenCalled();
    });
    it.each(['PUT', 'PATCH', 'DELETE', 'POST'])('blocks Grafana mutation %s', async method => {
        const cookie = await sessionCookie();
        mockFetch.mockClear();
        expect((await proxyGrafana(grafanaRequest(cookie, method), ['api', 'dashboards', 'db'])).status).toBe(405);
        expect(mockFetch).not.toHaveBeenCalled();
    });
    it('replaces browser identity headers and suppresses upstream cookies', async () => {
        const cookie = await sessionCookie();
        grafanaResponse(new Response('<html>Grafana</html>', { headers: { 'content-type': 'text/html', 'set-cookie': 'upstream-admin=secret' } }));
        const response = await proxyGrafana(grafanaRequest(cookie), ['d', 'sphere-collection']);
        expect(response.status).toBe(200);
        expect(response.headers.get('set-cookie')).toBeNull();
        expect(response.headers.get('content-security-policy')).toBe("frame-ancestors 'self'");
        const [, options] = mockFetch.mock.calls.at(-1)!;
        expect(options.headers).toEqual({ 'X-WEBAUTH-USER': 'sphere-observer', Accept: '*/*' });
    });
    it('allows bounded dashboard reads but rejects long ranges and excessive query counts', async () => {
        const cookie = await sessionCookie();
        grafanaResponse(ok({ results: {} }));
        const valid = { from: '0', to: '3600000', queries: [{ refId: 'A' }] };
        expect((await proxyGrafana(grafanaRequest(cookie, 'POST', JSON.stringify(valid)), ['api', 'ds', 'query'])).status).toBe(200);
        expect((await proxyGrafana(grafanaRequest(cookie, 'POST', JSON.stringify({ ...valid, to: '86400001' })), ['api', 'ds', 'query'])).status).toBe(400);
        expect((await proxyGrafana(grafanaRequest(cookie, 'POST', JSON.stringify({ ...valid, queries: Array(9).fill({}) })), ['api', 'ds', 'query'])).status).toBe(400);
    });
    it('blocks traversal, datasource bypasses and off-site redirects', async () => {
        const cookie = await sessionCookie();
        expect((await proxyGrafana(grafanaRequest(cookie), ['..', 'api'])).status).toBe(400);
        expect((await proxyGrafana(grafanaRequest(cookie), ['api', 'datasources', 'proxy', '1'])).status).toBe(403);
        grafanaResponse(new Response(null, { status: 302, headers: { location: 'http://evil.test/' } }));
        expect((await proxyGrafana(grafanaRequest(cookie), [])).status).toBe(503);
    });
    it.each([401, 403])('rechecks a Sphere token after minting and stops revoked/changed role %s', async status => {
        const cookie = await sessionCookie();
        mockFetch.mockClear().mockResolvedValue(new Response(null, { status }));
        expect((await proxyGrafana(grafanaRequest(cookie), ['api', 'user'])).status).toBe(status);
        expect(mockFetch).toHaveBeenCalledTimes(1);
        const [url, options] = mockFetch.mock.calls[0];
        expect(url.hostname).toBe('backend.test');
        expect(options.headers.Authorization).toBe('Bearer valid-token');
    });
    it.each([{ id: admin.id, role: 'viewer' }, { id: 'changed-user', role: 'super_admin' }])('does not grant access after a role or identity change', async profile => {
        const cookie = await sessionCookie();
        mockFetch.mockClear().mockResolvedValue(ok(profile));
        expect((await proxyGrafana(grafanaRequest(cookie), ['api', 'user'])).status).toBe(profile.role === 'viewer' ? 403 : 401);
        expect(mockFetch).toHaveBeenCalledTimes(1);
    });
    it('fails closed on Sphere outage, without contacting Grafana or using a cached role', async () => {
        const cookie = await sessionCookie();
        mockFetch.mockClear().mockRejectedValue(new Error('auth offline'));
        expect((await proxyGrafana(grafanaRequest(cookie), ['api', 'user'])).status).toBe(503);
        expect(mockFetch).toHaveBeenCalledTimes(1);
    });
    it('encrypts the original token, authenticates the ciphertext and isolates key rotation', async () => {
        const first = await sessionCookie();
        const second = await sessionCookie();
        expect(first).not.toBe(second);
        expect(first).not.toContain('valid-token');
        expect(first).not.toContain(Buffer.from('valid-token').toString('base64url'));
        const fields = first.split('.');
        fields[2] = (fields[2][0] === 'A' ? 'B' : 'A') + fields[2].slice(1);
        mockFetch.mockClear();
        expect((await proxyGrafana(grafanaRequest(fields.join('.')), [])).status).toBe(401);
        process.env.OBSERVABILITY_SESSION_SECRET = 'a-different-test-only-key-at-least-32-characters';
        expect((await proxyGrafana(grafanaRequest(first), [])).status).toBe(401);
        expect(mockFetch).not.toHaveBeenCalled();
    });
    it('bounds browser cookies and rejects oversized tokens before minting', async () => {
        expect((await createGrafanaSession(request('', 'a'.repeat(2042)))).status).toBe(400);
        mockFetch.mockClear();
        expect((await proxyGrafana(grafanaRequest('sphere_observability=' + 'x'.repeat(4097)), [])).status).toBe(401);
        expect(mockFetch).not.toHaveBeenCalled();
    });
    it.each([401, 403, 302])('does not disguise upstream auth failure %s as the Welcome page', async status => {
        const cookie = await sessionCookie();
        grafanaResponse(new Response(null, { status, headers: status === 302 ? { location: '/observability/grafana/login?redirectTo=dashboard' } : {} }));
        const response = await proxyGrafana(grafanaRequest(cookie), ['d', 'sphere-collection']);
        expect(response.status).toBe(503);
        expect(response.headers.get('location')).toBeNull();
        expect((await response.json()).detail).toMatch(/Grafana/);
    });
    it('rewrites safe dashboard redirects while keeping the Grafana subpath', async () => {
        const cookie = await sessionCookie();
        grafanaResponse(new Response(null, { status: 302, headers: { location: '/observability/grafana/d/sphere-collection/canonical-slug?orgId=1' } }));
        const response = await proxyGrafana(grafanaRequest(cookie), ['d', 'sphere-collection']);
        expect(response.status).toBe(302);
        expect(response.headers.get('location')).toBe('/observability/grafana/d/sphere-collection/canonical-slug?orgId=1');
    });
});
