import { errorResponse, PartialPrometheusError, prometheus, verifyAdmin } from './observability';
import type { HistoryWindow, ObservationSeries } from '@/src/features/monitoring/observabilityTypes';
import type { MeasurementState } from '@/src/features/monitoring/httpMetricsTypes';
import type { ResourceKey, ResourceMetricsSnapshot, ResourceSignal } from '@/src/features/monitoring/resourceMetricsTypes';

const WINDOWS: Record<HistoryWindow, number> = { '1h': 3600, '6h': 21600, '24h': 86400 };
const selector = 'job="sphere-backend"';
const keys: ResourceKey[] = ['cpu', 'cpuQuota', 'memory', 'memoryLimit'];
function guarded(value: string, resource: ResourceKey) {
    const labels = `${selector},resource="${resource}"`;
    const age = `(time() - sphere_container_resource_read_timestamp_seconds{${labels}})`;
    const measured = `${value} and on(job,instance,cgroup) (sphere_container_resource_available{${labels}} == 1) and on(job,instance,cgroup) (${age} >= -5) and on(job,instance,cgroup) (${age} <= 45)`;
    // Do not merge hosts/containers. If discovery finds multiple targets, each
    // historical step is unavailable until a per-target selector is implemented.
    return `max(${measured}) and on() (count(up{${selector}}) == 1)`;
}
// Fixed PromQL only. rate() runs on the cumulative CPU counter before aggregation.
export const RESOURCE_QUERIES = {
    cpu: guarded(`rate(sphere_container_cpu_usage_seconds_total{${selector}}[1m])`, 'cpu'),
    cpuQuota: guarded(`sphere_container_cpu_quota_cores{${selector}}`, 'cpuQuota'),
    memory: guarded(`(sphere_container_memory_usage_bytes{${selector}} / 1073741824)`, 'memory'),
    memoryLimit: guarded(`(sphere_container_memory_limit_bytes{${selector}} / 1073741824)`, 'memoryLimit'),
} as const;
const MESSAGE: Record<Exclude<MeasurementState, 'ready'>, string> = {
    empty: 'Нет измерения. Лимит может отсутствовать или быть неограниченным; это не ноль.',
    partial: 'Источник вернул неполный результат. Значение не подтверждено.',
    error: 'Источник недоступен или результат не прошёл проверку.',
    stale: 'Нет свежего измерения единственного контейнера backend. Прежние значения скрыты.',
};
function object(value: unknown): Record<string, unknown> {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('invalid object');
    return value as Record<string, unknown>;
}
function history(data: Record<string, unknown>, start: number, end: number): ObservationSeries[] {
    if (data.resultType !== 'matrix' || !Array.isArray(data.result) || data.result.length > 1) throw new Error('invalid aggregate');
    return data.result.map(item => {
        const row = object(item);
        if (Object.keys(object(row.metric)).length || !Array.isArray(row.values) || row.values.length > 1441) throw new Error('invalid history');
        const points = row.values.map(value => {
            if (!Array.isArray(value) || value.length !== 2 || typeof value[0] !== 'number' || !Number.isFinite(value[0]) || value[0] < start || value[0] > end + 5 || typeof value[1] !== 'string' || !value[1].trim()) throw new Error('invalid point');
            const number = Number(value[1]);
            if (value[1] !== 'NaN' && (!Number.isFinite(number) || number < 0)) throw new Error('invalid metric');
            return { at: value[0] * 1000, value: value[1] === 'NaN' ? null : number };
        });
        if (points.some((item, index) => index > 0 && item.at <= points[index - 1].at)) throw new Error('unordered history');
        return { name: 'Контейнер backend', points };
    });
}
type Result<T> = { state: MeasurementState; value: T | null };
async function measured<T>(work: () => Promise<T>): Promise<Result<T>> {
    try { return { state: 'ready', value: await work() }; }
    catch (error) { return { state: error instanceof PartialPrometheusError ? 'partial' : 'error', value: null }; }
}
export async function getResourceMetrics(request: Request): Promise<Response> {
    try {
        await verifyAdmin(request);
        const params = new URL(request.url).searchParams;
        const window = (params.get('window') ?? '1h') as HistoryWindow;
        if (!Object.hasOwn(WINDOWS, window) || [...params.keys()].some(key => key !== 'window') || params.getAll('window').length > 1) return Response.json({ detail: 'Допустим только один интервал: 1h, 6h или 24h.' }, { status: 400, headers: { 'Cache-Control': 'no-store' } });
        const end = Math.floor(Date.now() / 1000), start = end - WINDOWS[window];
        const stepSeconds = window === '1h' ? 15 : window === '6h' ? 30 : 60;
        const [targets, signals] = await Promise.all([
            measured(() => prometheus('api/v1/targets', { state: 'active' })),
            Promise.all(keys.map(key => measured(async () => history(await prometheus('api/v1/query_range', { query: RESOURCE_QUERIES[key], start: String(start), end: String(end), step: String(stepSeconds) }), start, end)))),
        ]);
        let fresh = false, lastScrape: string | null = null;
        if (targets.value && Array.isArray(targets.value.activeTargets) && targets.value.activeTargets.length <= 100) {
            try {
                const backend = targets.value.activeTargets.map(object).filter(target => object(target.labels).job === 'sphere-backend');
                const target = backend.length === 1 ? backend[0] : null;
                const at = target && typeof target.lastScrape === 'string' ? Date.parse(target.lastScrape) : NaN;
                fresh = !!target && target.health === 'up' && Number.isFinite(at) && at <= end * 1000 + 5000 && at >= end * 1000 - 45000;
                if (fresh) lastScrape = String(target!.lastScrape);
            } catch { /* Malformed discovery cannot authorize measurements. */ }
        }
        const unavailable: MeasurementState = targets.state === 'partial' ? 'partial' : targets.state === 'error' ? 'error' : 'stale';
        const metrics = Object.fromEntries(keys.map((key, index) => {
            const result = signals[index], series = result.value ?? [];
            const latest = series[0]?.points.at(-1);
            const state = !fresh ? unavailable : result.state !== 'ready' ? result.state : !latest || latest.value === null ? 'empty' : latest.at < (end - 45) * 1000 ? 'stale' : 'ready';
            const reason = state === 'ready' ? '' : state === 'empty' && key === 'cpu' ? 'Нет свежего измерения; это не ноль. Для скорости CPU нужны два успешных сбора.' : state === 'empty' && key === 'memory' ? 'Нет свежего измерения памяти; это не ноль.' : MESSAGE[state];
            return [key, { state, reason, series: state === 'ready' ? series : [] } satisfies ResourceSignal];
        })) as ResourceMetricsSnapshot['metrics'];
        const snapshot: ResourceMetricsSnapshot = { source: 'prometheus', scope: 'backend-container-cgroup', observedAt: new Date(end * 1000).toISOString(), lastScrape, window, stepSeconds, cpuAveragingSeconds: 60, metrics };
        return Response.json(snapshot, { headers: { 'Cache-Control': 'no-store' } });
    } catch (error) { return errorResponse(error); }
}
