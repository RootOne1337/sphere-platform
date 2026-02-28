'use client';
import { useState, useEffect } from 'react';
import { Activity, Server, Database, HardDrive, Cpu, Terminal, ArrowUpRight, ShieldCheck, Wifi, AlertTriangle } from 'lucide-react';
import { Badge } from '@/src/shared/ui/badge';

import { ClusterHeatmap } from '@/src/features/monitoring/ClusterHeatmap';

// Mock Data for NOC Dashboard
const MOCK_METRICS = {
    cpu: { current: 42, history: [22, 25, 30, 45, 60, 42, 38, 41, 42, 39, 45, 42] },
    ram: { current: 16.4, total: 32, history: [14, 14.5, 15, 16.2, 16.4, 16.4, 16.3, 16.4] },
    redis: { ops: 1240, memory: '1.2 GB', clients: 450 },
    network: { tx: '450 Mbps', rx: '120 Mbps', activeTunnels: 1205 },
};

const MOCK_NODES: any[] = [
    ...Array.from({ length: 4 }).map((_, i) => ({ id: `API-${i + 1}`, name: `Gateway Node ${i + 1}`, type: 'API', cpu: 20 + Math.random() * 40, ram: 40 + Math.random() * 20, status: 'HEALTHY' })),
    ...Array.from({ length: 12 }).map((_, i) => ({ id: `WK-${i + 1}`, name: `Task Worker ${i + 1}`, type: 'WORKER', cpu: 40 + Math.random() * 55, ram: 60 + Math.random() * 30, status: Math.random() > 0.9 ? 'WARNING' : 'HEALTHY' })),
    ...Array.from({ length: 3 }).map((_, i) => ({ id: `DB-${i + 1}`, name: `Postgres Node ${i + 1}`, type: 'DB', cpu: 60 + Math.random() * 35, ram: 80 + Math.random() * 15, status: i === 2 ? 'CRITICAL' : 'HEALTHY' })),
    ...Array.from({ length: 2 }).map((_, i) => ({ id: `RD-${i + 1}`, name: `Redis Cache ${i + 1}`, type: 'CACHE', cpu: 10 + Math.random() * 10, ram: 70 + Math.random() * 10, status: 'HEALTHY' })),
    ...Array.from({ length: 6 }).map((_, i) => ({ id: `EDGE-${i + 1}`, name: `CDN Edge ${i + 1}`, type: 'EDGE', cpu: Math.random() * 30, ram: Math.random() * 20, status: i === 4 ? 'OFFLINE' : 'HEALTHY' })),
];

export default function MonitoringPage() {
    const [metrics, setMetrics] = useState(MOCK_METRICS);

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
        <div className="flex flex-col h-full bg-[#0A0A0A] overflow-y-auto custom-scrollbar">
            {/* Header */}
            <div className="px-6 py-5 border-b border-[#222] bg-[#111] shrink-0">
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

                    <div className="flex items-center gap-4 bg-black/40 px-4 py-2 rounded-sm border border-[#333]">
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
                    <div className="bg-[#111] border border-[#222] p-4 rounded-sm flex flex-col relative overflow-hidden group">
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
                    <div className="bg-[#111] border border-[#222] p-4 rounded-sm flex flex-col relative overflow-hidden">
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
                    <div className="bg-[#111] border border-[#222] p-4 rounded-sm flex flex-col justify-between">
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
                    <div className="bg-[#111] border border-[#222] p-4 rounded-sm flex flex-col justify-between">
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
                <div className="border border-[#222] bg-[#111] rounded-sm p-4">
                    <div className="flex items-center justify-between mb-4 border-b border-[#222] pb-4">
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

                    <ClusterHeatmap nodes={MOCK_NODES} />
                </div>

            </div>
        </div>
    );
}
