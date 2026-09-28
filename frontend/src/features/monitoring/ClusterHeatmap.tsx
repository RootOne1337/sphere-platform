'use client';

import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Check, CircleHelp, Cpu, HardDrive, Server, Timer, Wifi } from 'lucide-react';
import type { ClusterNode } from './monitoringTypes';

interface ClusterHeatmapProps {
    nodes: ClusterNode[];
}

function normalizedStatus(node: ClusterNode) {
    return String(node.status ?? 'UNKNOWN').toUpperCase();
}

function statusTone(status: string) {
    if (status === 'HEALTHY' || status === 'OK') return 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300';
    if (status === 'WARNING' || status === 'DEGRADED') return 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300';
    if (status === 'CRITICAL' || status === 'DOWN') return 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300';
    return 'border-border bg-muted text-muted-foreground';
}

function ResourceValue({ label, value }: { label: string; value: number | null }) {
    const present = value != null && Number.isFinite(value);
    const percentage = present ? Math.min(100, Math.max(0, value)) : 0;
    return (
        <div className="min-w-0">
            <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-muted-foreground">{label}</span>
                <span className="shrink-0 font-medium tabular-nums text-foreground">{present ? `${value}%` : 'Unavailable'}</span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                <span className={`block h-full rounded-full ${!present ? 'bg-transparent' : value! >= 90 ? 'bg-rose-500' : value! >= 75 ? 'bg-amber-500' : 'bg-emerald-500'}`} style={{ width: `${percentage}%` }} />
            </div>
        </div>
    );
}

export function ClusterHeatmap({ nodes }: ClusterHeatmapProps) {
    const groupedNodes = useMemo(() => nodes.reduce<Record<string, ClusterNode[]>>((groups, node) => {
        const type = node.type || 'OTHER';
        (groups[type] ??= []).push(node);
        return groups;
    }, {}), [nodes]);
    const [selectedNodeId, setSelectedNodeId] = useState<string | null>(nodes[0]?.id ?? null);

    useEffect(() => {
        if (!nodes.some((node) => node.id === selectedNodeId)) setSelectedNodeId(nodes[0]?.id ?? null);
    }, [nodes, selectedNodeId]);

    const selectedNode = nodes.find((node) => node.id === selectedNodeId) ?? nodes[0] ?? null;

    return (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(280px,0.8fr)]">
            <div className="space-y-4">
                {Object.entries(groupedNodes).map(([type, typeNodes]) => (
                    <section key={type} aria-labelledby={`service-group-${type}`} className="rounded-xl border border-border/80 bg-card">
                        <div className="flex items-center justify-between gap-3 border-b border-border/70 px-4 py-3">
                            <div className="flex min-w-0 items-center gap-2.5">
                                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-border bg-muted/70 text-muted-foreground" aria-hidden="true"><Server className="h-4 w-4" /></span>
                                <div className="min-w-0"><h3 id={`service-group-${type}`} className="truncate text-sm font-semibold text-foreground">{type} layer</h3><p className="text-xs text-muted-foreground">Группа проверок backend</p></div>
                            </div>
                            <span className="shrink-0 rounded-full border border-border bg-background px-2.5 py-1 text-xs font-medium tabular-nums text-muted-foreground">{typeNodes.length}</span>
                        </div>
                        <div className="grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-3">
                            {typeNodes.map((node) => {
                                const status = normalizedStatus(node);
                                const isSelected = node.id === selectedNode?.id;
                                const icon = status === 'HEALTHY' || status === 'OK' ? <Check className="h-3.5 w-3.5" aria-hidden="true" />
                                    : status === 'CRITICAL' || status === 'DOWN' ? <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                                    : <CircleHelp className="h-3.5 w-3.5" aria-hidden="true" />;
                                return (
                                    <button
                                        key={node.id}
                                        type="button"
                                        onClick={() => setSelectedNodeId(node.id)}
                                        onFocus={() => setSelectedNodeId(node.id)}
                                        aria-pressed={isSelected}
                                        aria-label={`${node.name}, ${node.type}, ${status}`}
                                        title={`${node.name} · ${node.id} · ${status}`}
                                        className={`min-w-0 rounded-lg border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background motion-reduce:transition-none ${statusTone(status)} ${isSelected ? 'ring-2 ring-primary/70 ring-offset-1 ring-offset-background' : 'hover:border-primary/40'}`}
                                    >
                                        <span className="flex min-w-0 items-start justify-between gap-2">
                                            <span className="min-w-0"><span className="block truncate text-sm font-medium">{node.name}</span><span className="mt-0.5 block truncate font-mono text-[11px] opacity-70">{node.id}</span></span>
                                            <span className="flex shrink-0 items-center gap-1 rounded-full border border-current/20 bg-background/60 px-2 py-1 text-[10px] font-semibold">{icon}{status}</span>
                                        </span>
                                        <span className="mt-3 grid grid-cols-2 gap-3 border-t border-current/10 pt-2.5">
                                            <span className="flex min-w-0 items-center gap-1.5 text-xs"><Cpu className="h-3 w-3 shrink-0 opacity-70" aria-hidden="true" /><span className="truncate">CPU {node.cpu == null ? '—' : `${node.cpu}%`}</span></span>
                                            <span className="flex min-w-0 items-center gap-1.5 text-xs"><HardDrive className="h-3 w-3 shrink-0 opacity-70" aria-hidden="true" /><span className="truncate">RAM {node.ram == null ? '—' : `${node.ram}%`}</span></span>
                                        </span>
                                    </button>
                                );
                            })}
                        </div>
                    </section>
                ))}
            </div>

            <aside aria-label="Выбранная проверка сервиса" className="h-fit rounded-xl border border-border/80 bg-card xl:sticky xl:top-4">
                {selectedNode ? (
                    <>
                        <div className="flex items-start justify-between gap-3 border-b border-border/70 p-4">
                            <div className="flex min-w-0 items-center gap-3">
                                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border bg-muted/70 text-muted-foreground"><Server className="h-5 w-5" aria-hidden="true" /></span>
                                <div className="min-w-0"><p className="text-xs text-muted-foreground">Выбранный сервис</p><h3 className="truncate text-base font-semibold text-foreground" title={selectedNode.name}>{selectedNode.name}</h3></div>
                            </div>
                            <span className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${statusTone(normalizedStatus(selectedNode))}`}>{normalizedStatus(selectedNode)}</span>
                        </div>
                        <div className="space-y-5 p-4">
                            <dl className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-xs">
                                <dt className="text-muted-foreground">ID</dt><dd className="truncate font-mono text-foreground" title={selectedNode.id}>{selectedNode.id}</dd>
                                <dt className="text-muted-foreground">Тип</dt><dd className="text-foreground">{selectedNode.type}</dd>
                                <dt className="flex items-center gap-1 text-muted-foreground"><Timer className="h-3 w-3" aria-hidden="true" />Uptime</dt><dd className="text-foreground">{selectedNode.uptime || 'Unavailable'}</dd>
                                <dt className="flex items-center gap-1 text-muted-foreground"><Wifi className="h-3 w-3" aria-hidden="true" />Задержка</dt><dd className="text-foreground">{selectedNode.latencyMs == null || !Number.isFinite(selectedNode.latencyMs) ? 'Unavailable' : `${selectedNode.latencyMs.toFixed(1)} ms`}</dd>
                            </dl>
                            <div className="space-y-4 border-t border-border/70 pt-4">
                                <ResourceValue label="CPU" value={selectedNode.cpu} />
                                <ResourceValue label="RAM" value={selectedNode.ram} />
                                <ResourceValue label="Диск" value={selectedNode.disk} />
                            </div>
                        </div>
                    </>
                ) : (
                    <div className="p-6 text-center">
                        <Server className="mx-auto h-6 w-6 text-muted-foreground" aria-hidden="true" />
                        <p className="mt-3 text-sm font-medium text-foreground">Нет выбранных проверок</p>
                        <p className="mt-1 text-xs text-muted-foreground">Сервисы появятся после ответа backend.</p>
                    </div>
                )}
            </aside>
        </div>
    );
}
