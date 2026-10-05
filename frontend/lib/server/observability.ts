// Server-only integration. No credentials or upstream URLs are sent to the client.
import { createCipheriv, createDecipheriv, createHmac, randomBytes } from 'node:crypto';
import type { HistoryWindow, ObservationSeries, ObservabilitySnapshot } from '@/src/features/monitoring/observabilityTypes';

export const GRAFANA_PREFIX = '/observability/grafana';
const COOKIE = 'sphere_observability';
const TTL_SECONDS = 90;
const MAX_JSON_BYTES = 2_000_000;
// Grafana 13 bootstraps its read-only flags through OFREP POST in this namespace.
const GRAFANA_FEATURE_READ = 'apis/features.grafana.app/v0alpha1/namespaces/default/ofrep/v1/evaluate/flags';
const WINDOWS: Record<HistoryWindow, number> = { '1h': 3600, '6h': 21600, '24h': 86400 };
const QUERIES = {
    availability: 'up{job="sphere-backend"}',
    scrapeDuration: 'scrape_duration_seconds{job="sphere-backend"}',
    samples: 'scrape_samples_post_metric_relabeling{job="sphere-backend"}',
    storageSeries: 'prometheus_tsdb_head_series{job="prometheus"}',
};

class ObservationError extends Error {
    constructor(public status: number, message: string) { super(message); }
}

export function errorResponse(error: unknown) {
    return Response.json({ detail: error instanceof ObservationError ? error.message : 'Источник наблюдаемости недоступен.' }, {
        status: error instanceof ObservationError ? error.status : 503,
        headers: { 'Cache-Control': 'no-store' },
    });
}

function configuredUrl(key: string): URL {
    try {
        const url = new URL(process.env[key] ?? '');
        if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error();
        if (!url.pathname.endsWith('/')) url.pathname += '/';
        return url;
    } catch { throw new ObservationError(503, 'Серверное подключение наблюдаемости не настроено.'); }
}

function object(value: unknown): Record<string, unknown> {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('invalid object');
    return value as Record<string, unknown>;
}

async function readText(body: ReadableStream<Uint8Array> | null, maximum: number) {
    const reader = body?.getReader();
    if (!reader) throw new Error('empty response');
    let bytes = 0;
    const chunks: Uint8Array[] = [];
    try {
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            bytes += value.length;
            if (bytes > maximum) throw new ObservationError(413, 'Ответ или запрос слишком большой.');
            chunks.push(value);
        }
        return Buffer.concat(chunks).toString('utf8');
    } finally { await reader.cancel().catch(() => undefined); }
}

async function readJson(response: Response): Promise<unknown> {
    if (!response.ok) throw new ObservationError(503, 'Источник наблюдаемости не ответил успешно.');
    if (Number(response.headers.get('content-length') ?? 0) > MAX_JSON_BYTES) throw new Error('oversized response');
    try { return JSON.parse(await readText(response.body, MAX_JSON_BYTES)); }
    catch { throw new Error('invalid upstream JSON'); }
}

async function verifyAdmin(request: Request): Promise<string> {
    const authorization = request.headers.get('authorization') ?? '';
    if (!/^Bearer [A-Za-z0-9._~-]{1,8192}$/.test(authorization)) throw new ObservationError(401, 'Требуется вход в Sphere.');
    const response = await fetch(new URL('auth/me', configuredUrl('OBSERVABILITY_AUTH_API_URL')), {
        headers: { Authorization: authorization }, cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(3000),
    });
    if (response.status === 401 || response.status === 403) throw new ObservationError(response.status, 'Сессия Sphere недействительна.');
    const profile = object(await readJson(response));
    if (typeof profile.id !== 'string' || !profile.id) throw new Error('invalid profile');
    if (profile.role !== 'super_admin') throw new ObservationError(403, 'Метрики всей платформы доступны только супер-администратору.');
    return profile.id;
}

async function prometheus(path: string, params?: Record<string, string>) {
    const url = new URL(path, configuredUrl('OBSERVABILITY_PROMETHEUS_URL'));
    Object.entries(params ?? {}).forEach(([key, value]) => url.searchParams.set(key, value));
    const result = object(await readJson(await fetch(url, { cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(5000) })));
    if (result.status !== 'success' || ['warnings', 'infos'].some(key => result[key] !== undefined && (!Array.isArray(result[key]) || result[key].length > 0))) throw new Error('invalid or partial prometheus result');
    return object(result.data);
}

function parseSeries(data: Record<string, unknown>): ObservationSeries[] {
    if (data.resultType !== 'matrix' || !Array.isArray(data.result) || data.result.length > 8) throw new Error('invalid series');
    return (data.result as unknown[]).map(value => {
        const series = object(value);
        if (!Array.isArray(series.values) || series.values.length > 1441) throw new Error('invalid points');
        return {
            name: String(object(series.metric).instance ?? 'source').slice(0, 100),
            points: (series.values as unknown[]).map(point => {
                if (!Array.isArray(point) || point.length !== 2 || typeof point[0] !== 'number' || !Number.isFinite(point[0]) || typeof point[1] !== 'string') throw new Error('invalid point');
                const value = Number(point[1]);
                return { at: point[0] * 1000, value: point[1].trim() && Number.isFinite(value) ? value : null };
            }),
        };
    });
}

export async function getObservability(request: Request): Promise<Response> {
    try {
        await verifyAdmin(request);
        const search = new URL(request.url).searchParams;
        const window = (search.get('window') ?? '1h') as HistoryWindow;
        if (!Object.hasOwn(WINDOWS, window) || [...search.keys()].some(key => key !== 'window')) throw new ObservationError(400, 'Допустимы только интервалы 1h, 6h и 24h.');
        const end = Math.floor(Date.now() / 1000);
        const stepSeconds = window === '1h' ? 15 : window === '6h' ? 30 : 60;
        const [targets, alerts, ...charts] = await Promise.all([
            prometheus('api/v1/targets', { state: 'active' }), prometheus('api/v1/alerts'),
            ...Object.values(QUERIES).map(query => prometheus('api/v1/query_range', { query, start: String(end - WINDOWS[window]), end: String(end), step: String(stepSeconds) })),
        ]);
        if (!Array.isArray(targets.activeTargets) || targets.activeTargets.length > 100 || !Array.isArray(alerts.alerts) || alerts.alerts.length > 100) throw new Error('invalid inventory');
        const snapshot: ObservabilitySnapshot = {
            source: 'prometheus', observedAt: new Date(end * 1000).toISOString(), window, stepSeconds,
            targets: (targets.activeTargets as unknown[]).map(value => {
                const target = object(value), labels = object(target.labels);
                if (typeof labels.job !== 'string' || typeof target.health !== 'string' || !['up', 'down', 'unknown'].includes(target.health) || typeof target.lastScrape !== 'string' || typeof target.lastScrapeDuration !== 'number' || !Number.isFinite(target.lastScrapeDuration)) throw new Error('invalid target');
                return { job: labels.job, health: target.health, lastScrape: target.lastScrape, durationSeconds: target.lastScrapeDuration, error: String(target.lastError ?? '').slice(0, 500) };
            }),
            alerts: (alerts.alerts as unknown[]).map(value => {
                const alert = object(value), labels = object(alert.labels);
                if (typeof labels.alertname !== 'string' || typeof alert.state !== 'string' || !['pending', 'firing'].includes(alert.state)) throw new Error('invalid alert');
                return { name: labels.alertname, state: alert.state, severity: String(labels.severity ?? 'unknown'), since: String(alert.activeAt ?? ''), summary: String(object(alert.annotations).summary ?? '').slice(0, 500) };
            }),
            charts: Object.fromEntries(Object.keys(QUERIES).map((key, index) => [key, parseSeries(charts[index])])) as ObservabilitySnapshot['charts'],
        };
        return Response.json(snapshot, { headers: { 'Cache-Control': 'no-store' } });
    } catch (error) { return errorResponse(error); }
}

function sessionSecret() {
    const secret = process.env.OBSERVABILITY_SESSION_SECRET ?? '';
    if (secret.length < 32) throw new ObservationError(503, 'Защищённая сессия Grafana не настроена.');
    return secret;
}
function sessionKey() { return createHmac('sha256', sessionSecret()).update('sphere:grafana:session:v2').digest(); }
function sealSession(session: { id: string; authorization: string; exp: number }) {
    const nonce = randomBytes(12);
    const cipher = createCipheriv('aes-256-gcm', sessionKey(), nonce);
    cipher.setAAD(Buffer.from(COOKIE));
    const payload = Buffer.concat([cipher.update(JSON.stringify(session), 'utf8'), cipher.final()]);
    return ['v2', nonce.toString('base64url'), payload.toString('base64url'), cipher.getAuthTag().toString('base64url')].join('.');
}

export async function createGrafanaSession(request: Request): Promise<Response> {
    try {
        const id = await verifyAdmin(request);
        configuredUrl('OBSERVABILITY_GRAFANA_URL');
        const authorization = request.headers.get('authorization') ?? '';
        // Leave room for AEAD overhead under the browser's 4 KiB cookie limit.
        if (authorization.length > 2048) throw new ObservationError(400, 'Сессия Sphere слишком большая для встраивания Grafana.');
        const payload = sealSession({ id, authorization, exp: Math.floor(Date.now() / 1000) + TTL_SECONDS });
        const secure = process.env.OBSERVABILITY_SECURE_COOKIE === 'true' ? '; Secure' : '';
        return Response.json({ expiresIn: TTL_SECONDS }, { headers: {
            'Cache-Control': 'no-store',
            'Set-Cookie': `${COOKIE}=${payload}; HttpOnly; SameSite=Strict; Path=${GRAFANA_PREFIX}; Max-Age=${TTL_SECONDS}${secure}`,
        } });
    } catch (error) { return errorResponse(error); }
}

function verifyGrafanaCookie(request: Request) {
    const value = request.headers.get('cookie')?.split(';').map(part => part.trim()).find(part => part.startsWith(`${COOKIE}=`))?.slice(COOKIE.length + 1) ?? '';
    if (value.length > 4096) throw new ObservationError(401, 'Сессия Grafana истекла. Откройте её из Sphere.');
    const [version, nonce, payload, tag, extra] = value.split('.');
    if (version !== 'v2' || !nonce || !payload || !tag || extra !== undefined) throw new ObservationError(401, 'Сессия Grafana истекла. Откройте её из Sphere.');
    let session;
    try {
        const parts = [nonce, payload, tag].map(part => {
            const bytes = Buffer.from(part, 'base64url');
            if (bytes.toString('base64url') !== part) throw new Error('noncanonical encoding');
            return bytes;
        });
        if (parts[0].length !== 12 || parts[2].length !== 16) throw new Error('invalid AEAD fields');
        const decipher = createDecipheriv('aes-256-gcm', sessionKey(), parts[0]);
        decipher.setAAD(Buffer.from(COOKIE));
        decipher.setAuthTag(parts[2]);
        session = object(JSON.parse(Buffer.concat([decipher.update(parts[1]), decipher.final()]).toString('utf8')));
    } catch { throw new ObservationError(401, 'Недействительная сессия Grafana.'); }
    if (typeof session.id !== 'string' || !session.id || typeof session.authorization !== 'string' || !/^Bearer [A-Za-z0-9._~-]{1,2041}$/.test(session.authorization) || !Number.isInteger(session.exp) || Number(session.exp) <= Date.now() / 1000 || Number(session.exp) > Date.now() / 1000 + TTL_SECONDS + 1) throw new ObservationError(401, 'Сессия Grafana истекла.');
    return { id: session.id, authorization: session.authorization };
}

export async function proxyGrafana(request: Request, path: string[]): Promise<Response> {
    try {
        const session = verifyGrafanaCookie(request);
        if (path.some(part => !part || part === '.' || part === '..' || /[\\/%\x00-\x20]/.test(part))) throw new ObservationError(400, 'Недопустимый путь.');
        const route = path.join('/');
        if (route.startsWith('api/datasources/proxy/') || /api\/datasources\/uid\/[^/]+\/resources/.test(route)) throw new ObservationError(403, 'Используйте запросы dashboard через защищённый endpoint.');
        const isQuery = request.method === 'POST' && route === 'api/ds/query';
        const isFeatureRead = request.method === 'POST' && route === GRAFANA_FEATURE_READ;
        if (!['GET', 'HEAD'].includes(request.method) && !isQuery && !isFeatureRead) throw new ObservationError(405, 'Grafana в Sphere доступна только для чтения.');
        // Never forward browser Authorization, Cookie, Origin or proxy identity headers.
        const headers: Record<string, string> = { 'X-WEBAUTH-USER': 'sphere-observer', Accept: request.headers.get('accept') ?? '*/*' };
        let body: string | undefined;
        if (isQuery || isFeatureRead) {
            if (request.headers.get('sec-fetch-site') === 'cross-site') throw new ObservationError(403, 'Запрос отклонён.');
            headers['Content-Type'] = 'application/json';
        }
        if (isQuery) {
            if (Number(request.headers.get('content-length') ?? 0) > 100_000) throw new ObservationError(413, 'Запрос слишком большой.');
            body = await readText(request.body, 100_000);
            let query;
            try { query = object(JSON.parse(body)); } catch { throw new ObservationError(400, 'Некорректный запрос.'); }
            if (!Number.isFinite(Number(query.from)) || !Number.isFinite(Number(query.to)) || Number(query.to) < Number(query.from) || Number(query.to) - Number(query.from) > 86400_000 || !Array.isArray(query.queries) || query.queries.length > 8) throw new ObservationError(400, 'Максимальный интервал Grafana — 24 часа, не более 8 запросов.');
        }
        if (isFeatureRead) {
            if (Number(request.headers.get('content-length') ?? 0) > 16_384) throw new ObservationError(413, 'Запрос слишком большой.');
            const supplied = await readText(request.body, 16_384);
            try {
                const context = object(object(JSON.parse(supplied)).context);
                if (typeof context.targetingKey !== 'string' || !context.targetingKey.trim()) throw new Error('invalid feature context');
            } catch { throw new ObservationError(400, 'Некорректный запрос feature flags.'); }
            // The bridge uses one server-owned Viewer namespace. Do not forward
            // browser user/org attributes or use them to select feature targeting.
            body = JSON.stringify({ context: { targetingKey: 'default' } });
        }
        // A valid cookie is only a transport ticket, never an independent role.
        // Recheck the original Sphere token's revocation and current user role.
        const id = await verifyAdmin(new Request(request.url, { headers: { Authorization: session.authorization } }));
        if (id !== session.id) throw new ObservationError(401, 'Сессия Sphere изменилась.');
        const upstream = configuredUrl('OBSERVABILITY_GRAFANA_URL');
        upstream.pathname = `${GRAFANA_PREFIX}/${route}`;
        upstream.search = new URL(request.url).search;
        const result = await fetch(upstream, { method: request.method, headers, body, cache: 'no-store', redirect: 'manual', signal: AbortSignal.timeout(10000) });
        if (result.status === 401 || result.status === 403) {
            await result.body?.cancel();
            throw new ObservationError(503, 'Grafana отклонила доступ серверного прокси. Проверьте auth proxy и роль Viewer.');
        }
        const responseHeaders = new Headers({ 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "frame-ancestors 'self'" });
        const type = result.headers.get('content-type');
        if (type) responseHeaders.set('Content-Type', type);
        const location = result.headers.get('location');
        if (location) {
            const redirect = new URL(location, upstream);
            if (redirect.origin !== upstream.origin || !redirect.pathname.startsWith(`${GRAFANA_PREFIX}/`)) throw new Error('unsafe redirect');
            if (redirect.pathname === `${GRAFANA_PREFIX}/login` || redirect.pathname.startsWith(`${GRAFANA_PREFIX}/login/`)) {
                await result.body?.cancel();
                throw new ObservationError(503, 'Grafana требует вход вместо доверенного прокси. Проверьте адрес auth proxy.');
            }
            responseHeaders.set('Location', `${redirect.pathname}${redirect.search}`);
        }
        return new Response(request.method === 'HEAD' || [204, 304].includes(result.status) ? null : result.body, { status: result.status, headers: responseHeaders });
    } catch (error) { return errorResponse(error); }
}
