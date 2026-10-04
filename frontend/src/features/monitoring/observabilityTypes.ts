export type HistoryWindow = '1h' | '6h' | '24h';
export interface ObservationSeries {
    name: string;
    points: Array<{ at: number; value: number | null }>;
}
export interface ObservabilitySnapshot {
    observedAt: string;
    window: HistoryWindow;
    stepSeconds: number;
    source: 'prometheus';
    targets: Array<{ job: string; health: string; lastScrape: string; durationSeconds: number; error: string }>;
    alerts: Array<{ name: string; state: string; severity: string; since: string; summary: string }>;
    charts: {
        availability: ObservationSeries[];
        scrapeDuration: ObservationSeries[];
        samples: ObservationSeries[];
        storageSeries: ObservationSeries[];
    };
}
