'use client';
import { Activity, Server, Database, HardDrive, Cpu, ArrowUpRight, Wifi, AlertTriangle } from 'lucide-react';
import { Badge } from '@/src/shared/ui/badge';

import { ClusterHeatmap } from '@/src/features/monitoring/ClusterHeatmap';
import { formatBytes, MonitoringMetrics, summarizeMonitoringHealth } from '@/src/features/monitoring/monitoringTypes';
import type { ClusterNode } from '@/src/features/monitoring/monitoringTypes';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export default function MonitoringPage() {
    const { data: metrics, isError: metricsError } = useQuery<MonitoringMetrics>({
        queryKey: ['monitoring-metrics'],
        queryFn: async () => {
            const { data } = await api.get<MonitoringMetrics>('/monitoring/metrics');
            return data;
        },
        refetchInterval: 10000
    });

    const { data: nodes, isLoading: nodesLoading, isError: nodesError } = useQuery<ClusterNode[]>({
        queryKey: ['monitoring-nodes'],
        queryFn: async () => {
            const { data } = await api.get<ClusterNode[]>('/monitoring/nodes');
            return data;
        },
        refetchInterval: 10000
    });

    const systemHealth = summarizeMonitoringHealth(nodes, {
        loading: nodesLoading,
        failed: nodesError,
        telemetryFailed: metricsError,
    });

    // Simple sparkline generator for NOC feel
    const renderSparkline = (data: number[], colorClass: string) => {
        if (!data.length) return <p className="mt-4 text-[10px] text-muted-foreground">History is not retained by this endpoint.</p>;
        const max = Math.max(...data, 100);
        return (
            <div className="flex items-end h-12 gap-[2px] mt-4">
                {data.map((val, i) => (
                    <div
                        key={i}
                        className={`flex-1 rounded-t-sm ${colorClass} transition-all duration-500`}
                        style={{ height: `${(val / max) * 100}%`, opacity: 0.5 + (i / data.length) * 0.5 }}
                    />
                ))}
            </div>
        );
    };

    return (
        <div className="flex flex-col h-full bg-card overflow-y-auto custom-scrollbar">
            {/* Header */}
            <div className="px-6 py-5 border-b border-border bg-muted shrink-0">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    <div>
                        <div className="flex items-center gap-2 mb-1">
                            <Activity className="w-5 h-5 text-primary" />
                            <h1 className="text-xl font-bold font-mono tracking-tight text-foreground uppercase pt-1">Infrastructure Monitoring</h1>
                        </div>
                        <p className="text-xs text-muted-foreground max-w-xl font-mono">
                            Real-time telemetry, backend resource utilization, and subsystem health status.
                        </p>
                    </div>

                    <div className="flex items-center gap-4 bg-black/40 px-4 py-2 rounded-sm border border-border">
                        <div className="flex flex-col hidden sm:flex">
                            <span className="text-[10px] text-muted-foreground uppercase tracking-widest font-bold">System Status</span>
                            <span className={`text-xs font-mono font-bold flex items-center gap-2 ${systemHealth.tone === 'healthy' ? 'text-success' : systemHealth.tone === 'critical' ? 'text-destructive' : systemHealth.tone === 'warning' ? 'text-warning' : 'text-muted-foreground'}`}>
                                {systemHealth.tone === 'critical' || systemHealth.tone === 'warning' ? <AlertTriangle className="w-3 h-3" /> : <Activity className={`w-3 h-3 ${systemHealth.tone === 'loading' ? 'animate-pulse' : ''}`} />}
                                {systemHealth.label}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            <div className="p-6 space-y-6">

                {/* Top KPIs */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">

                    {/* CPU Widget */}
                    <div className="bg-muted border border-border p-4 rounded-sm flex flex-col relative overflow-hidden group">
                        <div className="flex justify-between items-start mb-2 relative z-10">
                            <div className="flex items-center gap-2 text-muted-foreground">
                                <Cpu className="w-4 h-4" />
                                <span className="text-[10px] uppercase font-bold tracking-widest" title="Linux 1-minute host load divided by reported logical CPUs; not container CPU utilization.">Linux Load · 1m</span>
                            </div>
                            <Badge variant="outline" className="text-[9px] border-border text-muted-foreground">HOST LOAD</Badge>
                        </div>
                        <div className="flex items-baseline gap-1 relative z-10">
                            <span className="text-3xl font-mono font-bold text-foreground">{metrics?.cpu?.linuxLoad1mPerCpu == null ? '—' : metrics.cpu.linuxLoad1mPerCpu.toFixed(2)}</span>
                            <span className="text-xs text-muted-foreground font-mono">per logical CPU</span>
                        </div>
                        {metricsError ? <p className="mt-4 text-[10px] text-warning">Metric request failed. Values are not available.</p> : renderSparkline(metrics?.cpu?.history ?? [], 'bg-warning')}
                    </div>

                    {/* RAM Widget */}
                    <div className="bg-muted border border-border p-4 rounded-sm flex flex-col relative overflow-hidden">
                        <div className="flex justify-between items-start mb-2 relative z-10">
                            <div className="flex items-center gap-2 text-muted-foreground">
                                <HardDrive className="w-4 h-4" />
                                <span className="text-[10px] uppercase font-bold tracking-widest">Memory (RAM)</span>
                            </div>
                            <Badge variant="outline" className="text-[9px] border-border text-muted-foreground">CGROUP MEMORY</Badge>
                        </div>
                        <div className="flex items-baseline gap-1 relative z-10">
                            <span className="text-3xl font-mono font-bold text-foreground">{formatBytes(metrics?.ram?.currentBytes)}</span>
                            <span className="text-xs text-muted-foreground font-mono">/ {formatBytes(metrics?.ram?.totalBytes)}</span>
                        </div>
                        {metricsError ? <p className="mt-4 text-[10px] text-warning">Metric request failed. Values are not available.</p> : renderSparkline(metrics?.ram?.history ?? [], 'bg-primary')}
                    </div>

                    {/* Redis State */}
                    <div className="bg-muted border border-border p-4 rounded-sm flex flex-col justify-between">
                        <div className="flex justify-between items-start mb-4">
                            <div className="flex items-center gap-2 text-muted-foreground">
                                <Database className="w-4 h-4" />
                                <span className="text-[10px] uppercase font-bold tracking-widest">Redis Cache</span>
                            </div>
                            <div className={`w-2 h-2 rounded-full ${String(metrics?.redis?.status ?? 'UNKNOWN').toUpperCase() === 'HEALTHY' ? 'bg-success' : String(metrics?.redis?.status ?? '').toUpperCase() === 'CRITICAL' ? 'bg-destructive' : 'bg-muted-foreground'}`} />
                        </div>
                        <div className="space-y-3">
                            <div className="flex justify-between text-xs font-mono">
                                <span className="text-muted-foreground">Operations/sec</span>
                                <span className="text-foreground">{metrics?.redis?.ops ?? 'Unavailable'}</span>
                            </div>
                            <div className="flex justify-between text-xs font-mono">
                                <span className="text-muted-foreground">Memory Used</span>
                                <span className="text-foreground">{metrics?.redis?.memory ?? 'Unavailable'}</span>
                            </div>
                            <div className="flex justify-between text-xs font-mono">
                                <span className="text-muted-foreground">Active Clients</span>
                                <span className="text-foreground">{metrics?.redis?.clients ?? 'Unavailable'}</span>
                            </div>
                        </div>
                    </div>

                    {/* Network / VPN */}
                    <div className="bg-muted border border-border p-4 rounded-sm flex flex-col justify-between">
                        <div className="flex justify-between items-start mb-4">
                            <div className="flex items-center gap-2 text-muted-foreground">
                                <Wifi className="w-4 h-4" />
                                <span className="text-[10px] uppercase font-bold tracking-widest">Container Network</span>
                            </div>
                            <ArrowUpRight className="w-4 h-4 text-primary" />
                        </div>
                        <div className="space-y-3">
                            <div className="flex justify-between text-xs font-mono">
                                <span className="text-muted-foreground">Bytes sent · cumulative</span>
                                <span className="text-foreground">{formatBytes(metrics?.network?.txTotalBytes)}</span>
                            </div>
                            <div className="flex justify-between text-xs font-mono">
                                <span className="text-muted-foreground">Bytes received · cumulative</span>
                                <span className="text-foreground">{formatBytes(metrics?.network?.rxTotalBytes)}</span>
                            </div>
                            <div className="flex justify-between text-xs font-mono">
                                <span className="text-muted-foreground">Active Tunnels</span>
                                <span className="text-muted-foreground font-bold">{metrics?.network?.activeTunnels ?? 'Not instrumented'}</span>
                            </div>
                        </div>
                    </div>

                </div>

                {/* Node Topology Matrix */}
                <div className="border border-border bg-muted rounded-sm p-4">
                    <div className="flex items-center justify-between mb-4 border-b border-border pb-4">
                        <div className="flex items-center gap-2 text-muted-foreground">
                            <Server className="w-4 h-4" />
                            <span className="text-xs uppercase font-bold tracking-widest text-foreground">Verified Service Checks</span>
                        </div>
                        <div className="flex items-center gap-3">
                            <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-success"></div><span className="text-[10px] text-muted-foreground font-mono">HEALTHY</span></div>
                            <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-warning"></div><span className="text-[10px] text-muted-foreground font-mono">WARNING</span></div>
                            <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-destructive animate-pulse"></div><span className="text-[10px] text-muted-foreground font-mono">CRITICAL</span></div>
                            <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-muted-foreground/50 border border-border"></div><span className="text-[10px] text-muted-foreground font-mono">OFFLINE</span></div>
                        </div>
                    </div>

                    {nodesLoading ? (
                        <div className="py-10 text-center text-xs text-muted-foreground animate-pulse">
                            Fetching cluster topology...
                        </div>
                    ) : nodesError ? (
                        <div className="py-10 text-center text-sm text-warning" role="alert">Service health could not be loaded. No healthy status is inferred from a failed request.</div>
                    ) : (
                        nodes?.length ? <ClusterHeatmap nodes={nodes} /> : <div className="py-10 text-center text-sm text-muted-foreground">No service health checks were returned.</div>
                    )}
                </div>

            </div>
        </div>
    );
}
