'use client';

import React from 'react';
import { Play, Pause, Maximize2, X, RefreshCw, SignalHigh, BatteryMedium, Cpu, HardDrive, Settings2, MonitorPlay, Activity } from 'lucide-react';
import { Device } from '@/lib/hooks/useDevices';
import { Badge } from '@/src/shared/ui/badge';
import { Button } from '@/src/shared/ui/button';
import { useStreamStore } from '@/src/shared/store/useStreamStore';

interface MultiStreamGridProps {
    devices: Device[];
    selectedIds?: string[];
    onClose?: () => void;
}

export function MultiStreamGrid({ devices, selectedIds, onClose }: MultiStreamGridProps) {
    const { gridSize, objectFit, showHUD, showStats, setGridSize, setObjectFit, toggleHUD, toggleStats } = useStreamStore();

    // Map gridSize (total items) to columns
    const columns = Math.ceil(Math.sqrt(gridSize));

    return (
        <div className="flex flex-col h-full bg-card border rounded-sm border-border">
            {/* Toolbar */}
            <div className="flex items-center gap-2 overflow-x-auto custom-scrollbar justify-between p-3 border-b border-border bg-muted">
                <div className="flex items-center gap-4 shrink-0">
                    <div className="flex items-center gap-2">
                        <MonitorPlay className="w-4 h-4 text-primary" />
                        <span className="text-xs font-mono font-bold tracking-widest uppercase">Global Operations Center</span>
                    </div>
                    <Badge variant="outline" className="bg-primary/10 text-primary border-primary/20 text-[10px] animate-pulse">LIVE BROADCAST</Badge>

                    <div className="h-4 w-px bg-[#333] hidden md:block" />

                    {/* View Options */}
                    <div className="flex items-center gap-1 hidden md:flex">
                        <Button variant="ghost" size="sm" onClick={() => setGridSize(1)} className={`h-6 text-[10px] px-2 ${gridSize === 1 ? 'bg-[#333] text-foreground' : 'text-muted-foreground'}`}>1x1</Button>
                        <Button variant="ghost" size="sm" onClick={() => setGridSize(4)} className={`h-6 text-[10px] px-2 ${gridSize === 4 ? 'bg-[#333] text-foreground' : 'text-muted-foreground'}`}>2x2</Button>
                        <Button variant="ghost" size="sm" onClick={() => setGridSize(9)} className={`h-6 text-[10px] px-2 ${gridSize === 9 ? 'bg-[#333] text-foreground' : 'text-muted-foreground'}`}>3x3</Button>
                        <Button variant="ghost" size="sm" onClick={() => setGridSize(16)} className={`h-6 text-[10px] px-2 ${gridSize === 16 ? 'bg-[#333] text-foreground' : 'text-muted-foreground'}`}>4x4</Button>

                        <div className="h-3 w-px bg-[#333] mx-1" />

                        <Button variant="ghost" size="sm" onClick={toggleHUD} className={`h-6 text-[10px] px-2 ${showHUD ? 'bg-primary/20 text-primary border border-primary/30' : 'bg-transparent text-muted-foreground'}`}>HUD</Button>
                        <Button variant="ghost" size="sm" onClick={toggleStats} className={`h-6 text-[10px] px-2 ${showStats ? 'bg-primary/20 text-primary border border-primary/30' : 'bg-transparent text-muted-foreground'}`}>STATS</Button>
                        <Button variant="ghost" size="sm" onClick={() => setObjectFit(objectFit === 'contain' ? 'cover' : 'contain')} className="h-6 text-[10px] px-2 text-muted-foreground hover:bg-border">FIT: {objectFit.toUpperCase()}</Button>
                    </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                    <Button variant="destructive" size="sm" className="h-7 text-[10px] tracking-wider uppercase font-bold" onClick={onClose}>
                        <X className="w-3 h-3 mr-1" /> End Broadcast
                    </Button>
                </div>
            </div>

            {/* Matrix Grid */}
            <div
                className="flex-1 p-2 bg-black overflow-y-auto custom-scrollbar grid gap-2"
                style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
            >
                {devices.slice(0, gridSize).map((device) => (
                    <div key={device.id} className="relative bg-muted border border-border rounded-sm overflow-hidden group flex flex-col min-h-[150px] aspect-video">

                        {/* Video Layer */}
                        <div className="flex-1 relative bg-black/50 flex flex-col items-center justify-center overflow-hidden">
                            {device.status.toLowerCase() === 'online' ? (
                                <div className="absolute inset-0 flex items-center justify-center">
                                    <div className="w-16 h-16 rounded-full border-2 border-primary/20 border-t-primary animate-spin" />
                                    <span className="absolute text-[10px] font-mono text-primary/50 font-bold tracking-widest animate-pulse">TCP/UDP</span>
                                </div>
                            ) : (
                                <div className="flex flex-col items-center justify-center text-muted-foreground gap-2">
                                    <X className="w-6 h-6 opacity-30" />
                                    <span className="text-[10px] font-mono font-bold tracking-widest uppercase">Stream Offline</span>
                                    <span className="text-[8px] text-[#555] font-mono">ERR_CONN_REFUSED</span>
                                </div>
                            )}

                            {/* HUD Overlays */}
                            {device.status.toLowerCase() === 'online' && showHUD && (
                                <>
                                    {/* Top Left HUD */}
                                    <div className="absolute top-2 left-2 flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity bg-black/40 backdrop-blur-md px-1.5 py-0.5 rounded-sm border border-white/5">
                                        <div className="w-1.5 h-1.5 bg-success rounded-full animate-pulse" />
                                        <span className="text-[9px] font-mono font-bold text-white shadow-black drop-shadow-md tracking-wider">{device.id}</span>
                                    </div>

                                </>
                            )}
                        </div>

                        {/* Bottom Telemetry Bar */}
                        <div className="h-6 shrink-0 bg-card border-t border-border px-2 flex items-center justify-between">
                            <span className="text-[9px] font-mono text-muted-foreground font-bold tracking-widest truncate">{device.model || 'GENERIC'}</span>

                            {showStats && device.status.toLowerCase() === 'online' && (
                                <div className="flex items-center gap-3">
                                    <div className="flex items-center gap-1 text-[8px] font-mono text-warning">
                                        <Activity className="w-2.5 h-2.5" /> 42ms
                                    </div>
                                    <div className="flex items-center gap-1 text-[8px] font-mono text-muted-foreground">
                                        <Cpu className="w-2.5 h-2.5" /> 12%
                                    </div>
                                </div>
                            )}
                        </div>

                    </div>
                ))}

                {/* Empty Placeholders if fewer devices than grid slots */}
                {Array.from({ length: Math.max(0, gridSize - Math.min(devices.length, gridSize)) }).map((_, i) => (
                    <div key={`empty-${i}`} className="bg-muted/30 border border-border border-dashed rounded-sm aspect-video flex items-center justify-center min-h-[150px]">
                        <span className="text-[10px] font-mono text-[#555] uppercase tracking-widest">No Signal</span>
                    </div>
                ))}

            </div>
        </div>
    );
}
