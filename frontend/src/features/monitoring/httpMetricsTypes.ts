import type { HistoryWindow, ObservationSeries } from './observabilityTypes';

export type MeasurementState = 'ready' | 'empty' | 'partial' | 'error' | 'stale';
export interface HttpSignal {
    state: MeasurementState;
    reason: string;
    series: ObservationSeries[];
}
export interface HttpEndpoint {
    method: string;
    endpoint: string;
    rps: number | null;
    p95Seconds: number | null;
    serverErrorsRps: number | null;
    clientErrorsRps: number | null;
}
export interface HttpMetricsSnapshot {
    source: 'prometheus';
    observedAt: string;
    lastScrape: string | null;
    window: HistoryWindow;
    stepSeconds: number;
    aggregationSeconds: 300;
    metrics: Record<'rps' | 'p95' | 'serverErrors' | 'clientErrors', HttpSignal>;
    endpoints: { state: MeasurementState; reason: string; limit: 30; rows: HttpEndpoint[]; possiblyTruncated: boolean };
    statuses: { state: MeasurementState; reason: string; rows: Array<{ code: string; rps: number | null }> };
}
