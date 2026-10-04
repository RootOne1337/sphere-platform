export type MonitoringStatus = 'HEALTHY' | 'WARNING' | 'CRITICAL' | 'OFFLINE' | 'UNKNOWN';

export interface ClusterNode {
    id: string;
    name: string;
    type: 'API' | 'WORKER' | 'DB' | 'CACHE' | 'EDGE' | 'DISK';
    cpu: number | null;
    ram: number | null;
    disk: number | null;
    status: MonitoringStatus | string;
    uptime: string;
    latencyMs?: number | null;
    details?: Record<string, unknown>;
}

export interface MonitoringMetrics {
    /** UTC time when the API sampled the current values. Missing on older backend builds. */
    observedAt?: string | null;
    cpu?: { linuxLoad1mPerCpu: number | null; history: number[] };
    ram?: { currentBytes: number | null; totalBytes: number | null; history: number[] };
    redis?: { status: MonitoringStatus | string; ops: number | null; memory: string | null; clients: number | null };
    network?: { txTotalBytes: number | null; rxTotalBytes: number | null; activeTunnels: number | null };
}

export interface NetworkCounterSample {
    observedAt: string;
    txTotalBytes: number | null | undefined;
    rxTotalBytes: number | null | undefined;
}

export interface NetworkRate {
    state: 'warming' | 'ready' | 'counter-reset' | 'gap' | 'unavailable';
    txBytesPerSecond: number | null;
    rxBytesPerSecond: number | null;
    intervalSeconds: number | null;
}

const MAX_NETWORK_SAMPLE_GAP_SECONDS = 60;

/** Derive an observed rate from two server-stamped cumulative counter samples. */
export function deriveNetworkRate(
    previous: NetworkCounterSample | undefined,
    current: NetworkCounterSample | undefined,
): NetworkRate {
    const unavailable: NetworkRate = {
        state: 'unavailable', txBytesPerSecond: null, rxBytesPerSecond: null, intervalSeconds: null,
    };
    if (!current) return { ...unavailable, state: 'warming' };

    const currentTime = Date.parse(current.observedAt);
    const currentTx = current.txTotalBytes;
    const currentRx = current.rxTotalBytes;
    if (!Number.isFinite(currentTime)
        || currentTx == null || !Number.isFinite(currentTx) || currentTx < 0
        || currentRx == null || !Number.isFinite(currentRx) || currentRx < 0) {
        return unavailable;
    }
    if (!previous) return { ...unavailable, state: 'warming' };

    const previousTime = Date.parse(previous.observedAt);
    const previousTx = previous.txTotalBytes;
    const previousRx = previous.rxTotalBytes;
    if (!Number.isFinite(previousTime)
        || previousTx == null || !Number.isFinite(previousTx) || previousTx < 0
        || previousRx == null || !Number.isFinite(previousRx) || previousRx < 0) {
        return unavailable;
    }

    const intervalSeconds = (currentTime - previousTime) / 1000;
    if (intervalSeconds <= 0) return unavailable;
    if (intervalSeconds > MAX_NETWORK_SAMPLE_GAP_SECONDS) {
        return { ...unavailable, state: 'gap', intervalSeconds };
    }
    if (currentTx < previousTx || currentRx < previousRx) {
        return { ...unavailable, state: 'counter-reset', intervalSeconds };
    }

    return {
        state: 'ready',
        txBytesPerSecond: (currentTx - previousTx) / intervalSeconds,
        rxBytesPerSecond: (currentRx - previousRx) / intervalSeconds,
        intervalSeconds,
    };
}

export function formatBytesPerSecond(bytesPerSecond: number | null | undefined): string {
    if (bytesPerSecond == null || !Number.isFinite(bytesPerSecond) || bytesPerSecond < 0) return '—';
    if (bytesPerSecond < 1024) return `${bytesPerSecond.toFixed(0)} B/s`;
    const units = ['KB/s', 'MB/s', 'GB/s', 'TB/s'];
    let value = bytesPerSecond;
    let unit = -1;
    do {
        value /= 1024;
        unit += 1;
    } while (value >= 1024 && unit < units.length - 1);
    return `${value.toFixed(1)} ${units[unit]}`;
}

export type HealthSummary = { label: string; tone: 'healthy' | 'warning' | 'critical' | 'unknown' | 'loading' };

/** Missing fields are a coverage gap, not a zero-valued measurement. */
export function getMonitoringTelemetryGaps(metrics: MonitoringMetrics | undefined): string[] {
    if (!metrics) return ['метрики ещё не получены'];

    const gaps: string[] = [];
    if (!metrics.observedAt || !Number.isFinite(Date.parse(metrics.observedAt))) gaps.push('время замера');
    if (metrics.cpu?.linuxLoad1mPerCpu == null) gaps.push('нагрузка CPU');
    if (!metrics.cpu?.history?.length) gaps.push('история CPU');
    if (metrics.ram?.currentBytes == null) gaps.push('память контейнера');
    if (!metrics.ram?.history?.length) gaps.push('история памяти');
    if (metrics.redis?.status == null || metrics.redis.status === 'UNKNOWN') gaps.push('статус Redis');
    if (metrics.redis?.ops == null) gaps.push('операции Redis');
    if (metrics.redis?.memory == null) gaps.push('память Redis');
    if (metrics.redis?.clients == null) gaps.push('клиенты Redis');
    if (metrics.network?.txTotalBytes == null) gaps.push('счётчик передачи');
    if (metrics.network?.rxTotalBytes == null) gaps.push('счётчик приёма');
    if (metrics.network?.activeTunnels == null) gaps.push('активные туннели');
    return gaps;
}

export function summarizeMonitoringHealth(
    nodes: ClusterNode[] | undefined,
    state: { loading?: boolean; failed?: boolean; telemetryFailed?: boolean; telemetryIncomplete?: boolean } = {},
): HealthSummary {
    if (state.loading) return { label: 'CHECKING SYSTEMS', tone: 'loading' };
    if (state.failed) return { label: 'STATUS UNAVAILABLE', tone: 'unknown' };
    if (!nodes?.length) return { label: 'NO HEALTH CHECKS RECEIVED', tone: 'unknown' };

    const statuses = nodes.map((node) => String(node.status).toUpperCase());
    if (statuses.includes('CRITICAL') || statuses.includes('DOWN')) {
        return { label: 'CRITICAL COMPONENT FAILURE', tone: 'critical' };
    }
    if (statuses.includes('WARNING') || statuses.includes('DEGRADED')) {
        return { label: 'DEGRADED COMPONENTS', tone: 'warning' };
    }
    if (statuses.every((status) => status === 'HEALTHY' || status === 'OK')) {
        if (state.telemetryFailed || state.telemetryIncomplete) {
            return { label: 'HEALTH CHECKS PASS · TELEMETRY DEGRADED', tone: 'warning' };
        }
        return { label: 'ALL OBSERVED CHECKS HEALTHY', tone: 'healthy' };
    }
    return { label: 'HEALTH STATUS INCOMPLETE', tone: 'unknown' };
}

export function formatBytes(bytes: number | null | undefined): string {
    if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return 'Unavailable';
    if (bytes < 1024) return `${bytes} B`;
    const units = ['KB', 'MB', 'GB', 'TB'];
    let value = bytes;
    let unit = -1;
    do {
        value /= 1024;
        unit += 1;
    } while (value >= 1024 && unit < units.length - 1);
    return `${value.toFixed(1)} ${units[unit]}`;
}
