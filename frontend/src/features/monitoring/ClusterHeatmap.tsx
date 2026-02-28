'use client';

import { useMemo, useState } from 'react';
import { Server, Cpu, HardDrive, AlertTriangle } from 'lucide-react';
import { Badge } from '@/src/shared/ui/badge';

interface ClusterNode {
    id: string;
    name: string;
    type: 'API' | 'WORKER' | 'DB' | 'CACHE' | 'EDGE';
    cpu: number;
    ram: number;
    disk: number;
    status: 'HEALTHY' | 'WARNING' | 'CRITICAL' | 'OFFLINE';
    uptime: string;
}

interface ClusterHeatmapProps {
    nodes: ClusterNode[];
}

export function ClusterHeatmap({ nodes }: ClusterHeatmapProps) {
    const [hoveredNode, setHoveredNode] = useState<ClusterNode | null>(null);

    // Group nodes by type
    const groupedNodes = useMemo(() => {
        return nodes.reduce((acc, node) => {
            if (!acc[node.type]) acc[node.type] = [];
            acc[node.type].push(node);
            return acc;
        }, {} as Record<string, ClusterNode[]>);
    }, [nodes]);

    const getColorClass = (status: string, usage: number) => {
        if (status === 'OFFLINE') return 'bg-[#333] border-[#444] text-muted-foreground';
        if (status === 'CRITICAL' || usage > 90) return 'bg-destructive/20 border-destructive/50 text-destructive animate-pulse shadow-[0_0_15px_rgba(239,68,68,0.2)]';
        if (status === 'WARNING' || usage > 75) return 'bg-warning/20 border-warning/50 text-warning';

        // Healthy - gradient based on load (green to yellow)
        if (usage > 50) return 'bg-[#eab308]/10 border-[#eab308]/30 text-[#eab308]';
        if (usage > 25) return 'bg-success/20 border-success/40 text-success';
        return 'bg-success/5 border-success/20 text-success/70';
    };

    return (
        <div className="flex flex-col h-full space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
                {Object.entries(groupedNodes).map(([type, typeNodes]) => (
                    <div key={type} className="flex flex-col bg-card border border-border rounded-sm p-4">
                        <div className="flex items-center justify-between mb-4 pb-2 border-b border-border">
                            <h3 className="text-xs font-bold font-mono tracking-widest text-muted-foreground uppercase">{type} Layer</h3>
                            <Badge variant="outline" className="text-[9px] bg-muted border-border">{typeNodes.length} Nodes</Badge>
                        </div>

                        <div className="grid grid-cols-4 gap-2">
                            {typeNodes.map(node => {
                                const avgLoad = (node.cpu + node.ram) / 2;
                                return (
                                    <div
                                        key={node.id}
                                        onMouseEnter={() => setHoveredNode(node)}
                                        onMouseLeave={() => setHoveredNode(null)}
                                        className={`aspect-square rounded-sm border flex items-center justify-center cursor-pointer transition-all duration-300 hover:scale-110 relative group ${getColorClass(node.status, avgLoad)}`}
                                    >
                                        <span className="text-[8px] font-mono font-bold opacity-0 group-hover:opacity-100 transition-opacity absolute">{avgLoad.toFixed(0)}%</span>
                                        {node.status === 'CRITICAL' && <AlertTriangle className="w-3 h-3 absolute -top-1 -right-1" />}
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                ))}
            </div>

            {/* Details Panel (Mock Hover State) */}
            <div className="bg-muted border border-border rounded-sm p-5 min-h-[140px] flex items-center shadow-inner relative overflow-hidden">
                {hoveredNode ? (
                    <div className="w-full flex justify-between items-center z-10 relative">
                        <div className="flex items-center gap-4">
                            <div className={`p-4 rounded-sm ${hoveredNode.status === 'CRITICAL' ? 'bg-destructive/20 text-destructive' : hoveredNode.status === 'WARNING' ? 'bg-warning/20 text-warning' : 'bg-success/20 text-success'}`}>
                                <Server className="w-8 h-8" />
                            </div>
                            <div>
                                <h2 className="text-lg font-bold font-mono text-foreground tracking-tight">{hoveredNode.name}</h2>
                                <p className="text-xs text-muted-foreground font-mono mt-1 flex items-center gap-2">
                                    <span className="text-muted-foreground border border-border px-1.5 py-0.5 rounded-sm bg-black">{hoveredNode.id}</span>
                                    <span>•</span>
                                    <span className="uppercase tracking-widest">{hoveredNode.type} Node</span>
                                </p>
                            </div>
                        </div>

                        <div className="flex gap-8">
                            <div className="flex flex-col">
                                <span className="text-[10px] uppercase font-bold tracking-widest text-[#555] mb-2 flex items-center gap-1"><Cpu className="w-3 h-3" /> CPU Load</span>
                                <div className="w-32 h-2 bg-border rounded-full overflow-hidden">
                                    <div className={`h-full ${hoveredNode.cpu > 80 ? 'bg-destructive' : hoveredNode.cpu > 50 ? 'bg-warning' : 'bg-success'}`} style={{ width: `${hoveredNode.cpu}%` }}></div>
                                </div>
                                <span className="text-xs mt-1 font-mono text-right">{hoveredNode.cpu}%</span>
                            </div>
                            <div className="flex flex-col">
                                <span className="text-[10px] uppercase font-bold tracking-widest text-[#555] mb-2 flex items-center gap-1"><HardDrive className="w-3 h-3" /> Memory</span>
                                <div className="w-32 h-2 bg-border rounded-full overflow-hidden">
                                    <div className={`h-full ${hoveredNode.ram > 80 ? 'bg-destructive' : hoveredNode.ram > 50 ? 'bg-warning' : 'bg-success'}`} style={{ width: `${hoveredNode.ram}%` }}></div>
                                </div>
                                <span className="text-xs mt-1 font-mono text-right">{hoveredNode.ram}%</span>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="w-full h-full flex flex-col items-center justify-center opacity-50 z-10 relative">
                        <Server className="w-6 h-6 text-muted-foreground mb-2" />
                        <p className="text-xs font-mono uppercase tracking-widest text-muted-foreground">Hover over any node in the matrix to inspect telemetry.</p>
                    </div>
                )}

                {/* Decorative background logo */}
                <Server className="w-64 h-64 text-[#ffffff02] absolute -right-10 -bottom-20 pointer-events-none" />
            </div>

        </div>
    );
}
