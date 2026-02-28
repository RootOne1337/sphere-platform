'use client';

import { useMemo } from 'react';
import { Play, Check, X, Circle, ArrowRight, Clock } from 'lucide-react';
import { Badge } from '@/src/shared/ui/badge';

interface WorkflowStep {
    id: string;
    name: string;
    type: 'TRIGGER' | 'ACTION' | 'CONDITION' | 'END';
    status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'SKIPPED';
    duration?: string;
}

interface WorkflowVisualizerProps {
    steps: WorkflowStep[];
}

export function WorkflowVisualizer({ steps }: WorkflowVisualizerProps) {

    const getStepIcon = (status: WorkflowStep['status']) => {
        switch (status) {
            case 'SUCCESS': return <Check className="w-4 h-4 text-success" />;
            case 'FAILED': return <X className="w-4 h-4 text-destructive" />;
            case 'RUNNING': return <Play className="w-4 h-4 text-primary animate-pulse" />;
            case 'SKIPPED': return <Circle className="w-4 h-4 text-[#555]" />;
            default: return <Clock className="w-4 h-4 text-muted-foreground" />;
        }
    };

    const getStepColor = (status: WorkflowStep['status']) => {
        switch (status) {
            case 'SUCCESS': return 'border-success bg-success/10 text-success';
            case 'FAILED': return 'border-destructive bg-destructive/10 text-destructive';
            case 'RUNNING': return 'border-primary bg-primary/10 text-primary';
            case 'SKIPPED': return 'border-border bg-muted text-muted-foreground';
            default: return 'border-[#555] bg-black text-muted-foreground';
        }
    };

    return (
        <div className="w-full bg-card border border-border rounded-sm p-6 overflow-x-auto relative">
            {/* N8N Watermark */}
            <div className="absolute top-4 right-4 opacity-10 pointer-events-none flex items-center gap-2">
                <div className="w-6 h-6 rounded-sm bg-destructive rotate-45" />
                <div className="w-6 h-6 rounded-full bg-primary" />
                <span className="text-2xl font-bold font-mono tracking-tighter ml-1">n8n.cloud</span>
            </div>

            <div className="flex items-center min-w-max gap-2 py-4">
                {steps.map((step, index) => (
                    <div key={step.id} className="flex items-center">

                        {/* Node Card */}
                        <div className={`flex flex-col w-[160px] p-3 rounded-sm border ${getStepColor(step.status)} transition-all hover:scale-105 cursor-default relative overflow-hidden group`}>

                            {/* Status Bar Indicator */}
                            <div className={`absolute top-0 left-0 w-full h-1 ${step.status === 'SUCCESS' ? 'bg-success' : step.status === 'FAILED' ? 'bg-destructive' : step.status === 'RUNNING' ? 'bg-primary animate-pulse' : 'bg-transparent'}`} />

                            <div className="flex justify-between items-start mb-3 pt-1">
                                <Badge variant="outline" className={`text-[8px] bg-black border-[#444] px-1.5 py-0 ${step.status === 'RUNNING' ? 'text-primary border-primary/50' : 'text-muted-foreground'}`}>{step.type}</Badge>
                                {getStepIcon(step.status)}
                            </div>

                            <h4 className="text-xs font-bold font-mono truncate text-foreground group-hover:whitespace-normal group-hover:break-words">{step.name}</h4>

                            <div className="mt-2 flex justify-between items-end">
                                <span className="text-[9px] uppercase font-bold tracking-widest opacity-60">{step.status}</span>
                                {step.duration && <span className="text-[10px] font-mono opacity-80">{step.duration}</span>}
                            </div>
                        </div>

                        {/* Connection Line */}
                        {index < steps.length - 1 && (
                            <div className="flex flex-col items-center justify-center w-12 shrink-0">
                                <div className={`h-[2px] w-full ${step.status === 'SUCCESS' ? 'bg-success' : step.status === 'FAILED' ? 'bg-destructive' : step.status === 'RUNNING' ? 'bg-primary/50 bg-[linear-gradient(90deg,transparent,theme(colors.primary.DEFAULT),transparent)] bg-[length:200%_100%] animate-gradient-x' : 'bg-[#333]'}`} />
                                <ArrowRight className={`w-3 h-3 mt-1 ${step.status === 'SUCCESS' ? 'text-success' : step.status === 'FAILED' ? 'text-destructive' : step.status === 'RUNNING' ? 'text-primary animate-pulse' : 'text-muted-foreground'}`} />
                            </div>
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
}
