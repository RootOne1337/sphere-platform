import { errorResponse, PartialPrometheusError, prometheus, verifyAdmin } from './observability';
import type { HistoryWindow, ObservationSeries } from '@/src/features/monitoring/observabilityTypes';
import type { HttpMetricsSnapshot, HttpSignal, MeasurementState } from '@/src/features/monitoring/httpMetricsTypes';

const WINDOWS: Record<HistoryWindow, number> = { '1h': 3600, '6h': 21600, '24h': 86400 };
const selector = 'job="sphere-backend"';
const counter = `sphere_http_requests_total{${selector}}`;
const byRoute = `sum by (method, endpoint) (rate(${counter}[5m]))`;
const topRoutes = `topk(30, ${byRoute})`;
const total = `sum(rate(${counter}[5m]))`;
const errors = (code: '4' | '5', byEndpoint = false) => {
    const group = byEndpoint ? ' by (method, endpoint)' : '';
    return `(sum${group}(rate(sphere_http_requests_total{${selector},status_code=~"${code}.."}[5m])) or ${byEndpoint ? 'on(method, endpoint) ' : ''}(0 * ${byEndpoint ? byRoute : total}))`;
};
// Browser input never becomes PromQL, a label matcher, an upstream URL or a target.
export const HTTP_QUERIES = {
    rps: total,
    p95: `histogram_quantile(0.95, sum by (le) (rate(sphere_http_request_duration_seconds_bucket{${selector}}[5m])))`,
    serverErrors: errors('5'), clientErrors: errors('4'),
    routes: topRoutes,
    routeP95: `histogram_quantile(0.95, sum by (method, endpoint, le) (rate(sphere_http_request_duration_seconds_bucket{${selector}}[5m]))) and on(method, endpoint) ${topRoutes}`,
    routeServerErrors: `${errors('5', true)} and on(method, endpoint) ${topRoutes}`,
    routeClientErrors: `${errors('4', true)} and on(method, endpoint) ${topRoutes}`,
    statuses: `sum by (status_code) (rate(${counter}[5m]))`,
} as const;
const MESSAGE: Record<Exclude<MeasurementState, 'ready'>, string> = {
    empty: 'Нет измерений за текущее окно; это не ноль.',
    partial: 'Источник вернул неполный результат. Значение не подтверждено.',
    error: 'Запрос метрик не прошёл проверку или источник недоступен.',
    stale: 'Нет свежего успешного сбора backend. Текущие значения скрыты.',
};
function object(value: unknown): Record<string, unknown> {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('invalid object');
    return value as Record<string, unknown>;
}
function point(value: unknown, start: number, end: number): { at: number; value: number | null } {
    if (!Array.isArray(value) || value.length !== 2 || typeof value[0] !== 'number' || !Number.isFinite(value[0]) || value[0] < start || value[0] > end + 5 || typeof value[1] !== 'string') throw new Error('invalid point');
    const number = Number(value[1]);
    // NaN is the documented undefined quantile for an idle histogram, not a zero.
    if (value[1] !== 'NaN' && (!value[1].trim() || !Number.isFinite(number) || number < 0)) throw new Error('invalid metric');
    return { at: value[0] * 1000, value: value[1] === 'NaN' ? null : number };
}
function history(data: Record<string, unknown>, start: number, end: number): ObservationSeries[] {
    if (data.resultType !== 'matrix' || !Array.isArray(data.result) || data.result.length > 1) throw new Error('invalid aggregate');
    return data.result.map(item => {
        const row = object(item);
        if (Object.keys(object(row.metric)).length || !Array.isArray(row.values) || row.values.length > 1441) throw new Error('invalid history');
        const points = row.values.map(item => point(item, start, end));
        if (points.some((item, index) => index > 0 && item.at <= points[index - 1].at)) throw new Error('unordered history');
        return { name: 'sphere-backend', points };
    });
}
function vector(data: Record<string, unknown>, end: number, maximum: number) {
    if (data.resultType !== 'vector' || !Array.isArray(data.result) || data.result.length > maximum) throw new Error('invalid vector');
    return data.result.map(item => { const row = object(item); return { metric: object(row.metric), value: point(row.value, end - 45, end).value }; });
}
function routeKey(labels: Record<string, unknown>) {
    if (Object.keys(labels).sort().join(',') !== 'endpoint,method' || typeof labels.endpoint !== 'string' || !/^(?:\/[A-Za-z0-9_/.{}:-]{0,255}|__unmatched__)$/.test(labels.endpoint) || typeof labels.method !== 'string' || !/^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|TRACE|CONNECT|OTHER)$/.test(labels.method)) throw new Error('invalid route labels');
    return `${labels.method} ${labels.endpoint}`;
}
type Result<T> = { state: MeasurementState; reason: string; value: T | null };
async function measured<T>(work: () => Promise<T>): Promise<Result<T>> {
    try { return { state: 'ready', reason: '', value: await work() }; }
    catch (error) {
        const state = error instanceof PartialPrometheusError ? 'partial' : 'error';
        return { state, reason: MESSAGE[state], value: null };
    }
}
export async function getHttpMetrics(request: Request): Promise<Response> {
    try {
        await verifyAdmin(request);
        const params = new URL(request.url).searchParams;
        const window = (params.get('window') ?? '1h') as HistoryWindow;
        if (!Object.hasOwn(WINDOWS, window) || [...params.keys()].some(key => key !== 'window') || params.getAll('window').length > 1) return Response.json({ detail: 'Допустим только один интервал: 1h, 6h или 24h.' }, { status: 400, headers: { 'Cache-Control': 'no-store' } });
        const end = Math.floor(Date.now() / 1000), start = end - WINDOWS[window];
        const stepSeconds = window === '1h' ? 15 : window === '6h' ? 30 : 60;
        const keys = ['rps', 'p95', 'serverErrors', 'clientErrors'] as const;
        const routeKeys = ['routes', 'routeP95', 'routeServerErrors', 'routeClientErrors'] as const;
        const [targets, signals, routes, statuses] = await Promise.all([
            measured(() => prometheus('api/v1/targets', { state: 'active' })),
            Promise.all(keys.map(key => measured(async () => history(await prometheus('api/v1/query_range', { query: HTTP_QUERIES[key], start: String(start), end: String(end), step: String(stepSeconds) }), start, end)))),
            Promise.all(routeKeys.map(key => measured(async () => {
                const rows = vector(await prometheus('api/v1/query', { query: HTTP_QUERIES[key], time: String(end) }), end, 30);
                const entries = rows.map(row => [routeKey(row.metric), row.value] as const);
                if (new Set(entries.map(([key]) => key)).size !== entries.length) throw new Error('duplicate route');
                return new Map(entries);
            }))),
            measured(async () => {
                const rows = vector(await prometheus('api/v1/query', { query: HTTP_QUERIES.statuses, time: String(end) }), end, 100);
                const result = rows.map(row => {
                    const code = row.metric.status_code;
                    if (Object.keys(row.metric).join(',') !== 'status_code' || typeof code !== 'string' || !/^[1-5][0-9]{2}$/.test(code)) throw new Error('invalid status');
                    return { code, rps: row.value };
                });
                if (new Set(result.map(row => row.code)).size !== result.length) throw new Error('duplicate status');
                return result.sort((a, b) => a.code.localeCompare(b.code));
            }),
        ]);
        let fresh = false, lastScrape: string | null = null;
        if (targets.value && Array.isArray(targets.value.activeTargets) && targets.value.activeTargets.length <= 100) {
            const backend = targets.value.activeTargets.map(object).filter(target => object(target.labels).job === 'sphere-backend');
            fresh = backend.length > 0 && backend.every(target => {
                const at = typeof target.lastScrape === 'string' ? Date.parse(target.lastScrape) : NaN;
                if (target.health === 'up' && Number.isFinite(at) && at <= end * 1000 + 5000 && at >= end * 1000 - 45000) { lastScrape = String(target.lastScrape); return true; }
                return false;
            });
        }
        const unavailable: MeasurementState = targets.state === 'partial' ? 'partial' : targets.state === 'error' ? 'error' : 'stale';
        const metrics = Object.fromEntries(keys.map((key, index) => {
            const result = signals[index], series = result.value ?? [];
            const latest = series[0]?.points.at(-1);
            const state = !fresh ? unavailable : result.state !== 'ready' ? result.state : !latest || latest.value === null ? 'empty' : latest.at < (end - stepSeconds * 1.5) * 1000 ? 'stale' : 'ready';
            return [key, { state, reason: state === 'ready' ? '' : MESSAGE[state], series: fresh && (state === 'ready' || state === 'empty') ? series : [] } satisfies HttpSignal];
        })) as HttpMetricsSnapshot['metrics'];
        const routeResult = routes[0];
        const rows = fresh ? [...(routeResult.value ?? [])].map(([key, rps]) => {
            const [method, endpoint] = key.split(' ');
            return { method, endpoint, rps, p95Seconds: routes[1].value?.get(key) ?? null, serverErrorsRps: routes[2].value?.get(key) ?? null, clientErrorsRps: routes[3].value?.get(key) ?? null };
        }).sort((a, b) => (b.rps ?? -1) - (a.rps ?? -1) || `${a.method} ${a.endpoint}`.localeCompare(`${b.method} ${b.endpoint}`)) : [];
        // Only a successfully measured error counter can produce an explicit 0.
        const incomplete = routes.some(result => result.state !== 'ready') || [...(routeResult.value?.keys() ?? [])].some(key => routes.slice(1).some(result => !result.value?.has(key))) || rows.some(row => row.rps === null || row.serverErrorsRps === null || row.clientErrorsRps === null);
        const state: MeasurementState = !fresh ? unavailable : routeResult.state !== 'ready' ? routeResult.state : incomplete ? 'partial' : !rows.length ? 'empty' : 'ready';
        const statusState: MeasurementState = !fresh ? unavailable : statuses.state !== 'ready' ? statuses.state : !statuses.value?.length ? 'empty' : statuses.value.some(row => row.rps === null) ? 'partial' : 'ready';
        const snapshot: HttpMetricsSnapshot = { source: 'prometheus', observedAt: new Date(end * 1000).toISOString(), lastScrape: fresh ? lastScrape : null, window, stepSeconds, aggregationSeconds: 300, metrics,
            endpoints: { state, reason: state === 'ready' ? '' : MESSAGE[state], rows, limit: 30, possiblyTruncated: rows.length === 30 },
            statuses: { state: statusState, reason: statusState === 'ready' ? '' : MESSAGE[statusState], rows: fresh ? statuses.value ?? [] : [] },
        };
        return Response.json(snapshot, { headers: { 'Cache-Control': 'no-store' } });
    } catch (error) { return errorResponse(error); }
}
