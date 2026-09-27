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
    cpu?: { linuxLoad1mPerCpu: number | null; history: number[] };
    ram?: { currentBytes: number | null; totalBytes: number | null; history: number[] };
    redis?: { status: MonitoringStatus | string; ops: number | null; memory: string | null; clients: number | null };
    network?: { txTotalBytes: number | null; rxTotalBytes: number | null; activeTunnels: number | null };
}

export type HealthSummary = { label: string; tone: 'healthy' | 'warning' | 'critical' | 'unknown' | 'loading' };

export function summarizeMonitoringHealth(
    nodes: ClusterNode[] | undefined,
    state: { loading?: boolean; failed?: boolean; telemetryFailed?: boolean } = {},
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
        if (state.telemetryFailed) {
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
