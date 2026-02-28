'use client';
import { useState, useEffect } from 'react';
import { Activity, Server, Database, HardDrive, Cpu, Terminal, ArrowUpRight, ShieldCheck, Wifi, AlertTriangle } from 'lucide-react';
import { Badge } from '@/src/shared/ui/badge';

import { ClusterHeatmap } from '@/src/features/monitoring/ClusterHeatmap';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

const DEFAULT_METRICS = {
    cpu: { current: 0, history: Array(12).fill(0) },
    ram: { current: 0, total: 32, history: Array(8).fill(0) },
    redis: { ops: 0, memory: '0 MB', clients: 0 },
    network: { tx: '0 Mbps', rx: '0 Mbps', activeTunnels: 0 },
};

export default function MonitoringPage() {
    const { data: metrics = DEFAULT_METRICS, isLoading: metricsLoading } = useQuery({
        queryKey: ['monitoring-metrics'],
        queryFn: async () => {
            try {
                const { data } = await api.get('/monitoring/metrics');
                return data;
            } catch (e) {
                console.error('Failed to fetch metrics', e);
                return DEFAULT_METRICS;
            }
        },
        refetchInterval: 10000
    });

    const { data: nodes = [], isLoading: nodesLoading } = useQuery({
        queryKey: ['monitoring-nodes'],
        queryFn: async () => {
            try {
                const { data } = await api.get('/monitoring/nodes');
                return data;
            } catch (e) {
                console.error('Failed to fetch nodes', e);
                return [];
            }
        },
        refetchInterval: 10000
    });

    // Simple sparkline generator for NOC feel
    const renderSparkline = (data: number[], colorClass: string) => {
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
                            <span className="text-xs text-warning font-mono font-bold flex items-center gap-2">
                                <AlertTriangle className="w-3 h-3 text-warning animate-pulse" />
                                1 NODE CRITICAL
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
                                <span className="text-[10px] uppercase font-bold tracking-widest">CPU Compute</span>
                            </div>
                            <Badge variant="outline" className="text-[9px] border-warning text-warning">MODERATE</Badge>
                        </div>
                        <div className="flex items-baseline gap-1 relative z-10">
                            <span className="text-3xl font-mono font-bold text-foreground">{metrics.cpu.current}</span>
                            <span className="text-xs text-muted-foreground font-mono">%</span>
                        </div>
                        {renderSparkline(metrics.cpu.history, 'bg-warning')}
                    </div>

                    {/* RAM Widget */}
                    <div className="bg-muted border border-border p-4 rounded-sm flex flex-col relative overflow-hidden">
                        <div className="flex justify-between items-start mb-2 relative z-10">
                            <div className="flex items-center gap-2 text-muted-foreground">
                                <HardDrive className="w-4 h-4" />
                                <span className="text-[10px] uppercase font-bold tracking-widest">Memory (RAM)</span>
                            </div>
                            <Badge variant="outline" className="text-[9px] border-primary text-primary">STABLE</Badge>
                        </div>
                        <div className="flex items-baseline gap-1 relative z-10">
                            <span className="text-3xl font-mono font-bold text-foreground">{metrics.ram.current}</span>
                            <span className="text-xs text-muted-foreground font-mono">/ {metrics.ram.total} GB</span>
                        </div>
                        {renderSparkline(metrics.ram.history, 'bg-primary')}
                    </div>

                    {/* Redis State */}
                    <div className="bg-muted border border-border p-4 rounded-sm flex flex-col justify-between">
                        <div className="flex justify-between items-start mb-4">
                            <div className="flex items-center gap-2 text-muted-foreground">
                                <Database className="w-4 h-4" />
                                <span className="text-[10px] uppercase font-bold tracking-widest">Redis Cache</span>
                            </div>
                            <div className="w-2 h-2 rounded-full bg-success" />
                        </div>
                        <div className="space-y-3">
                            <div className="flex justify-between text-xs font-mono">
                                <span className="text-muted-foreground">Operations/sec</span>
                                <span className="text-foreground">{metrics.redis.ops}</span>
                            </div>
                            <div className="flex justify-between text-xs font-mono">
                                <span className="text-muted-foreground">Memory Used</span>
                                <span className="text-foreground">{metrics.redis.memory}</span>
                            </div>
                            <div className="flex justify-between text-xs font-mono">
                                <span className="text-muted-foreground">Active Clients</span>
                                <span className="text-success">{metrics.redis.clients}</span>
                            </div>
                        </div>
                    </div>

                    {/* Network / VPN */}
                    <div className="bg-muted border border-border p-4 rounded-sm flex flex-col justify-between">
                        <div className="flex justify-between items-start mb-4">
                            <div className="flex items-center gap-2 text-muted-foreground">
                                <Wifi className="w-4 h-4" />
                                <span className="text-[10px] uppercase font-bold tracking-widest">Global Network</span>
                            </div>
                            <ArrowUpRight className="w-4 h-4 text-primary" />
                        </div>
                        <div className="space-y-3">
                            <div className="flex justify-between text-xs font-mono">
                                <span className="text-muted-foreground">Bandwidth TX</span>
                                <span className="text-foreground">{metrics.network.tx}</span>
                            </div>
                            <div className="flex justify-between text-xs font-mono">
                                <span className="text-muted-foreground">Bandwidth RX</span>
                                <span className="text-foreground">{metrics.network.rx}</span>
                            </div>
                            <div className="flex justify-between text-xs font-mono">
                                <span className="text-muted-foreground">Active Tunnels</span>
                                <span className="text-primary font-bold">{metrics.network.activeTunnels}</span>
                            </div>
                        </div>
                    </div>

                </div>

                {/* Node Topology Matrix */}
                <div className="border border-border bg-muted rounded-sm p-4">
                    <div className="flex items-center justify-between mb-4 border-b border-border pb-4">
                        <div className="flex items-center gap-2 text-muted-foreground">
                            <Server className="w-4 h-4" />
                            <span className="text-xs uppercase font-bold tracking-widest text-foreground">Cluster Topology & Nodes</span>
                        </div>
                        <div className="flex items-center gap-3">
                            <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-success"></div><span className="text-[10px] text-muted-foreground font-mono">HEALTHY</span></div>
                            <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-warning"></div><span className="text-[10px] text-muted-foreground font-mono">WARNING</span></div>
                            <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-destructive animate-pulse"></div><span className="text-[10px] text-muted-foreground font-mono">CRITICAL</span></div>
                            <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-[#333]"></div><span className="text-[10px] text-muted-foreground font-mono">OFFLINE</span></div>
                        </div>
                    </div>

                    {nodesLoading ? (
                        <div className="py-10 text-center text-xs text-muted-foreground animate-pulse">
                            Fetching cluster topology...
                        </div>
                    ) : (
                        <ClusterHeatmap nodes={nodes} />
                    )}
                </div>

            </div>
        </div>
    );
}
