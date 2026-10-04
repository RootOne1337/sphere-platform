import { fireEvent, render, screen, within } from '@testing-library/react';
import { ClusterHeatmap } from '@/src/features/monitoring/ClusterHeatmap';
import { deriveNetworkRate, formatBytes, formatBytesPerSecond, getMonitoringTelemetryGaps, summarizeMonitoringHealth } from '@/src/features/monitoring/monitoringTypes';
import type { ClusterNode, MonitoringMetrics } from '@/src/features/monitoring/monitoringTypes';

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

  it('marks a successful but incomplete metrics payload as partial coverage', () => {
    const metrics: MonitoringMetrics = {
      cpu: { linuxLoad1mPerCpu: 0.25, history: [] },
      ram: { currentBytes: 1024, totalBytes: null, history: [] },
      redis: { status: 'HEALTHY', ops: null, memory: null, clients: null },
      network: { txTotalBytes: 100, rxTotalBytes: 200, activeTunnels: null },
    };

    expect(getMonitoringTelemetryGaps(metrics)).toEqual([
      'время замера', 'история CPU', 'история памяти', 'операции Redis', 'память Redis', 'клиенты Redis', 'активные туннели',
    ]);
    expect(summarizeMonitoringHealth([node('HEALTHY')], { telemetryIncomplete: true })).toEqual({
      label: 'HEALTH CHECKS PASS · TELEMETRY DEGRADED',
      tone: 'warning',
    });
  });

  it('formats only measured byte counters', () => {
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(null)).toBe('Unavailable');
    expect(formatBytes(Number.NaN)).toBe('Unavailable');
  });

  it('derives network rates only from valid UTC counter samples', () => {
    const previous = {
      observedAt: '2026-09-29T10:00:00.000Z', txTotalBytes: 1_000, rxTotalBytes: 2_000,
    };
    const current = {
      observedAt: '2026-09-29T10:00:10.000Z', txTotalBytes: 2_000, rxTotalBytes: 2_500,
    };

    expect(deriveNetworkRate(undefined, current).state).toBe('warming');
    expect(deriveNetworkRate(previous, current)).toEqual({
      state: 'ready', txBytesPerSecond: 100, rxBytesPerSecond: 50, intervalSeconds: 10,
    });
    expect(formatBytesPerSecond(1_024)).toBe('1.0 KB/s');
    expect(formatBytesPerSecond(Number.NaN)).toBe('—');
  });

  it('hides a rate after a counter reset, invalid timestamp, or long sample gap', () => {
    const previous = {
      observedAt: '2026-09-29T10:00:00.000Z', txTotalBytes: 1_000, rxTotalBytes: 2_000,
    };

    expect(deriveNetworkRate(previous, {
      observedAt: '2026-09-29T10:00:10.000Z', txTotalBytes: 10, rxTotalBytes: 2_500,
    }).state).toBe('counter-reset');
    expect(deriveNetworkRate(previous, {
      observedAt: 'not-a-date', txTotalBytes: 2_000, rxTotalBytes: 2_500,
    }).state).toBe('unavailable');
    expect(deriveNetworkRate(previous, {
      observedAt: '2026-09-29T10:02:00.000Z', txTotalBytes: 2_000, rxTotalBytes: 2_500,
    }).state).toBe('gap');
  });

  it('renders absent resource samples as unavailable instead of zero', () => {
    render(<ClusterHeatmap nodes={[node('HEALTHY')]} />);

    const service = screen.getByRole('button', { name: 'PostgreSQL, DB, HEALTHY' });
    expect(service).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(service);

    expect(screen.getByText('Не измеряется')).toBeInTheDocument();
    expect(screen.getByText(/Ресурсные проценты CPU\/RAM\/диска/)).toBeInTheDocument();
    expect(screen.queryByText('0%')).not.toBeInTheDocument();
  });

  it('lets keyboard users inspect a service from the registry', () => {
    const second = { ...node('WARNING'), id: 'worker-2', name: 'Worker 2', type: 'WORKER' as const, latencyMs: 18.4 };
    render(<ClusterHeatmap nodes={[node('HEALTHY'), second]} />);

    const worker = screen.getByRole('button', { name: 'Worker 2, WORKER, WARNING' });
    fireEvent.focus(worker);

    expect(worker).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getAllByText('18.4 ms')).toHaveLength(2);
  });

  it('exposes measured pool details and refreshes the selected service without resetting selection', () => {
    const database = { ...node('HEALTHY'), latencyMs: 2.4, details: { pool_size: 40, checked_out: 3 } };
    const cache = { ...node('HEALTHY'), id: 'redis-cache-1', name: 'Redis', type: 'CACHE' as const,
      details: { pong: true, used_memory_mb: 1.5 } };
    const { rerender } = render(<ClusterHeatmap nodes={[database, cache]} />);
    const inspector = screen.getByRole('complementary', { name: 'Выбранная проверка сервиса' });

    expect(within(inspector).getByText('Размер пула API-процесса').nextElementSibling).toHaveTextContent('40');
    expect(within(inspector).getByText('Занято соединений').nextElementSibling).toHaveTextContent('3');
    expect(within(inspector).getByText('Возраст API-процесса')).toBeInTheDocument();
    expect(within(inspector).getByText(/SELECT 1/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Redis, CACHE, HEALTHY' }));
    rerender(<ClusterHeatmap nodes={[database, { ...cache, details: { pong: true, used_memory_mb: 2.75 } }]} />);
    expect(within(inspector).getByText('Память Redis').nextElementSibling).toHaveTextContent('2.75 MiB');
    expect(within(inspector).queryByText('Занято соединений')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Redis, CACHE, HEALTHY' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows valid zero disk usage and avoids projecting arbitrary details or invalid measurements into UI', () => {
    const disk = { ...node('HEALTHY'), id: 'backend-disk-1', name: 'Backend filesystem', type: 'DISK' as const,
      details: { free_gb: 12, total_gb: 20, usage_percent: 0, token: 'private-token',
        nested: { password: 'private-password' }, pool_size: Number.NaN } };
    render(<ClusterHeatmap nodes={[disk]} />);
    const inspector = screen.getByRole('complementary', { name: 'Выбранная проверка сервиса' });
    expect(within(inspector).getByText('Свободно').nextElementSibling).toHaveTextContent('12 GiB');
    expect(within(inspector).getByText('Занято').nextElementSibling).toHaveTextContent('0%');
    expect(inspector).not.toHaveTextContent('private-token');
    expect(inspector).not.toHaveTextContent('private-password');
    expect(inspector).not.toHaveTextContent('NaN');
    expect(within(inspector).queryByText('Размер пула API-процесса')).not.toBeInTheDocument();
  });

  it('marks a failed probe and does not present its unavailable zero latency as a successful measurement', () => {
    render(<ClusterHeatmap nodes={[{ ...node('CRITICAL'), latencyMs: 0, details: {
      error: 'postgresql://operator:private-password@database', pool_size: -1,
    } }]} />);
    const inspector = screen.getByRole('complementary', { name: 'Выбранная проверка сервиса' });
    expect(within(inspector).getByRole('alert')).toHaveTextContent('Ошибка проверки');
    expect(inspector).not.toHaveTextContent('private-password');
    expect(inspector).not.toHaveTextContent('0.0 ms');
    expect(within(inspector).queryByText('Размер пула API-процесса')).not.toBeInTheDocument();
    expect(within(inspector).getByText('Детали проверки не получены.')).toBeInTheDocument();
  });
});
