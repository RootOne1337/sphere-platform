import { fireEvent, render, screen } from '@testing-library/react';
import { ClusterHeatmap } from '@/src/features/monitoring/ClusterHeatmap';
import { formatBytes, summarizeMonitoringHealth } from '@/src/features/monitoring/monitoringTypes';
import type { ClusterNode } from '@/src/features/monitoring/monitoringTypes';

const node = (status: string): ClusterNode => ({
  id: 'postgres-db-1',
  name: 'PostgreSQL',
  type: 'DB',
  cpu: null,
  ram: null,
  disk: null,
  status,
  uptime: '15m',
});

describe('monitoring status presentation', () => {
  it('does not call unavailable or empty health data healthy', () => {
    expect(summarizeMonitoringHealth(undefined, { failed: true }).tone).toBe('unknown');
    expect(summarizeMonitoringHealth([]).label).toBe('NO HEALTH CHECKS RECEIVED');
    expect(summarizeMonitoringHealth([node('unknown')]).tone).toBe('unknown');
  });

  it('recognizes backend uppercase critical and warning statuses', () => {
    expect(summarizeMonitoringHealth([node('CRITICAL')]).tone).toBe('critical');
    expect(summarizeMonitoringHealth([node('WARNING')]).tone).toBe('warning');
    expect(summarizeMonitoringHealth([node('HEALTHY')]).label).toBe('ALL OBSERVED CHECKS HEALTHY');
  });

  it('keeps partial metrics failures visible even when dependency health checks pass', () => {
    expect(summarizeMonitoringHealth([node('HEALTHY')], { telemetryFailed: true })).toEqual({
      label: 'HEALTH CHECKS PASS · TELEMETRY DEGRADED',
      tone: 'warning',
    });
  });

  it('formats only measured byte counters', () => {
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(null)).toBe('Unavailable');
    expect(formatBytes(Number.NaN)).toBe('Unavailable');
  });

  it('renders absent resource samples as unavailable instead of zero', () => {
    render(<ClusterHeatmap nodes={[node('HEALTHY')]} />);

    const service = screen.getByRole('button', { name: 'PostgreSQL, DB, HEALTHY' });
    expect(service).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(service);

    expect(screen.getAllByText('Unavailable')).toHaveLength(4);
    expect(screen.queryByText('0%')).not.toBeInTheDocument();
  });

  it('lets keyboard users inspect a service from the registry', () => {
    const second = { ...node('WARNING'), id: 'worker-2', name: 'Worker 2', type: 'WORKER' as const, latencyMs: 18.4 };
    render(<ClusterHeatmap nodes={[node('HEALTHY'), second]} />);

    const worker = screen.getByRole('button', { name: 'Worker 2, WORKER, WARNING' });
    fireEvent.focus(worker);

    expect(worker).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('18.4 ms')).toBeInTheDocument();
  });
});
