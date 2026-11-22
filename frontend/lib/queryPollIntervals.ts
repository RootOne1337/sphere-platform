/** Shared UI polling cadence so displayed freshness thresholds cannot drift from queries. */
export const API_POLL_INTERVALS = {
  deviceInventoryMs: 15_000,
  deviceDetailMs: 10_000,
  prometheusMs: 15_000,
  fleetCoverageMs: 15_000,
  dashboardHealthMs: 30_000,
  dashboardAttentionMs: 60_000,
  vpnPeersMs: 30_000,
  vpnPoolStatsMs: 60_000,
  vpnHealthMs: 30_000,
  deviceEventsMs: 15_000,
  deviceEventStatsMs: 60_000,
} as const;
