'use client';

import { CheckCircle2, Clock, XCircle, AlertCircle, Play } from 'lucide-react';

interface Task {
    id: string;
    name: string;
    status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED';
    startTimeMs: number;
    durationMs: number | null; // null if still running
}

interface TaskGanttChartProps {
    tasks: Task[];
    windowTimeMs?: number; // Total timeline window to display (default 60s)
}

export function TaskGanttChart({ tasks, windowTimeMs = 60000 }: TaskGanttChartProps) {

    // Find the earliest start time to baseline the chart
    const baselineTime = tasks.length > 0
        ? Math.min(...tasks.map(t => t.startTimeMs))
        : Date.now();

    const getStatusIcon = (status: Task['status']) => {
        switch (status) {
            case 'SUCCESS': return <CheckCircle2 className="w-3 h-3 text-success" />;
            case 'FAILED': return <XCircle className="w-3 h-3 text-destructive" />;
            case 'RUNNING': return <Play className="w-3 h-3 text-primary animate-pulse" />;
            default: return <Clock className="w-3 h-3 text-[#555]" />;
        }
    };

    const getStatusColor = (status: Task['status']) => {
        switch (status) {
            case 'SUCCESS': return 'bg-success/20 border-success/50';
            case 'FAILED': return 'bg-destructive/20 border-destructive/50';
            case 'RUNNING': return 'bg-primary/20 border-primary/50 overflow-hidden relative';
            default: return 'bg-border border-border opacity-50';
        }
    };

    return (
        <div className="w-full bg-card border border-border rounded-sm p-4 overflow-x-auto relative min-w-[600px]">

            {/* Timeline Grid Background */}
            <div className="absolute top-0 bottom-0 left-[200px] right-4 flex justify-between pointer-events-none opacity-20 z-0">
                {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="h-full border-l border-[#555] relative">
                        <span className="absolute -left-3 top-[-16px] text-[8px] font-mono text-muted-foreground">+{i * 10}s</span>
                    </div>
                ))}
            </div>

            <div className="mt-6 space-y-2 relative z-10">
                {tasks.map(task => {
                    // Calculate percentage position
                    const startOffsetMs = Math.max(0, task.startTimeMs - baselineTime);
                    const leftPercent = Math.min((startOffsetMs / windowTimeMs) * 100, 100);

                    // Calculate width (assume running tasks take rest of the window)
                    const effectiveDuration = task.durationMs || (windowTimeMs - startOffsetMs);
                    let widthPercent = (effectiveDuration / windowTimeMs) * 100;
                    if (leftPercent + widthPercent > 100) widthPercent = 100 - leftPercent; // clamp

                    return (
                        <div key={task.id} className="flex items-center h-8 hover:bg-muted transition-colors group rounded-sm p-1">

                            {/* Task Meta (Left Sidebar) */}
                            <div className="w-[180px] shrink-0 flex items-center gap-2 border-r border-border mr-4 pr-2">
                                {getStatusIcon(task.status)}
                                <span className="text-xs font-mono font-bold text-foreground truncate">{task.name}</span>
                            </div>

                            {/* Timeline Bar Area */}
                            <div className="flex-1 relative h-full">
                                <div
                                    className={`absolute top-1/2 -translate-y-1/2 h-5 rounded-[2px] border ${getStatusColor(task.status)} group-hover:brightness-125 transition-all`}
                                    style={{ left: `${leftPercent}%`, width: `${Math.max(widthPercent, 1)}%` }}
                                >
                                    {/* Animated Strip for running tasks */}
                                    {task.status === 'RUNNING' && (
                                        <div className="absolute inset-0 w-full h-full pointer-events-none" style={{ backgroundImage: 'repeating-linear-gradient(45deg, transparent, transparent 5px, rgba(34, 197, 94, 0.1) 5px, rgba(34, 197, 94, 0.1) 10px)' }}></div>
                                    )}
                                </div>
                            </div>

                        </div>
                    );
                })}
            </div>

        </div>
    );
}
