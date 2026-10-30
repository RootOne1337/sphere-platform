import type { HistoryWindow, ObservationSeries } from './observabilityTypes';
import type { MeasurementState } from './httpMetricsTypes';

export type ResourceKey = 'cpu' | 'cpuQuota' | 'memory' | 'memoryLimit';
export interface ResourceSignal {
    state: MeasurementState;
    reason: string;
    series: ObservationSeries[];
}
export interface ResourceMetricsSnapshot {
    source: 'prometheus';
    scope: 'backend-container-cgroup';
    observedAt: string;
    lastScrape: string | null;
    window: HistoryWindow;
    stepSeconds: number;
    cpuAveragingSeconds: 60;
    metrics: Record<ResourceKey, ResourceSignal>;
}
