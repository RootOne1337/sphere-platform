'use client';

import { useState, useMemo, useCallback, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { toast } from 'sonner';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';
import { Badge } from '@/src/shared/ui/badge';
import { Label } from '@/components/ui/label';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from '@/components/ui/dialog';
import {
    GitBranch,
    Play,
    Pause,
    RotateCcw,
    XCircle,
    Plus,
    CalendarClock,
    CheckCircle2,
    ShieldAlert,
    Zap,
    Timer,
    Clock,
    Search,
    Activity,
    ChevronDown,
    ChevronRight,
    Layers,
    ToggleLeft,
    ToggleRight,
    Eye,
    Workflow,
    Repeat,
    Trash2,
    Pencil,
    GripVertical,
    Copy,
    ArrowUp,
    ArrowDown,
    Loader2,
} from 'lucide-react';
import { DeviceSelector } from '@/components/sphere/DeviceSelector';
import { useScripts, Script } from '@/lib/hooks/useScripts';

// ============================================================================
//  ТИПЫ
// ============================================================================

interface PipelineStep {
    id: string;
    name: string;
    type: string;
    params: Record<string, any>;
    on_success: string | null;
    on_failure: string | null;
    timeout_ms: number;
    retries: number;
}

interface Pipeline {
    id: string;
    name: string;
    description: string | null;
    steps: PipelineStep[];
    input_schema: Record<string, any>;
    global_timeout_ms: number;
    max_retries: number;
    version: number;
    is_active: boolean;
    tags: string[];
    created_at: string;
    updated_at: string;
}

interface PipelineRun {
    id: string;
    pipeline_id: string;
    device_id: string;
    status: string;
    current_step_id: string | null;
    context: Record<string, any>;
    input_params: Record<string, any>;
    step_logs: Array<{
        step_id: string;
        type?: string;
        status: string;
        started_at?: string;
        finished_at?: string;
        duration_ms?: number;
        output?: any;
        error?: string;
    }>;
    started_at: string | null;
    finished_at: string | null;
    retry_count: number;
    created_at: string;
}

interface Schedule {
    id: string;
    name: string;
    description: string | null;
    cron_expression: string | null;
    interval_seconds: number | null;
    one_shot_at: string | null;
    timezone: string;
    target_type: string;
    script_id: string | null;
    pipeline_id: string | null;
    conflict_policy: string;
    is_active: boolean;
    total_runs: number;
    next_fire_at: string | null;
    last_fired_at: string | null;
    created_at: string;
}

interface ScheduleExecution {
    id: string;
    schedule_id: string;
    status: string;
    fire_time: string;
    actual_time: string;
    devices_targeted: number;
    tasks_created: number;
    tasks_succeeded: number;
    tasks_failed: number;
    skip_reason: string | null;
    created_at: string;
}

// ============================================================================
//  ХУКИ ДАННЫХ
// ============================================================================

function usePipelines() {
    return useQuery<Pipeline[]>({
        queryKey: ['pipelines'],
        queryFn: async () => {
            try {
                const { data } = await api.get('/pipelines?per_page=100');
                return data.items || [];
            } catch { return []; }
        },
        refetchInterval: 8000,
    });
}

function usePipelineRuns() {
    return useQuery<PipelineRun[]>({
        queryKey: ['pipeline-runs'],
        queryFn: async () => {
            try {
                const { data } = await api.get('/pipelines/runs?per_page=100');
                return data.items || [];
            } catch { return []; }
        },
        refetchInterval: 5000,
    });
}

function useSchedules() {
    return useQuery<Schedule[]>({
        queryKey: ['schedules'],
        queryFn: async () => {
            try {
                const { data } = await api.get('/schedules?per_page=100');
                return data.items || [];
            } catch { return []; }
        },
        refetchInterval: 8000,
    });
}

// ============================================================================
//  УТИЛИТЫ
// ============================================================================

const STATUS_CONFIG: Record<string, { color: string; dot: string; label: string }> = {
    queued: { color: 'text-muted-foreground', dot: 'bg-muted-foreground', label: 'QUEUED' },
    running: { color: 'text-primary', dot: 'bg-primary animate-pulse', label: 'RUNNING' },
    paused: { color: 'text-warning', dot: 'bg-warning', label: 'PAUSED' },
    waiting: { color: 'text-blue-400', dot: 'bg-blue-400 animate-pulse', label: 'WAITING' },
    completed: { color: 'text-success', dot: 'bg-success', label: 'COMPLETED' },
    failed: { color: 'text-destructive', dot: 'bg-destructive', label: 'FAILED' },
    cancelled: { color: 'text-muted-foreground', dot: 'bg-muted-foreground', label: 'CANCELLED' },
    timed_out: { color: 'text-destructive', dot: 'bg-destructive', label: 'TIMEOUT' },
};

function StatusBadge({ status }: { status: string }) {
    const cfg = STATUS_CONFIG[status.toLowerCase()] ?? STATUS_CONFIG.queued;
    return (
        <div className="flex items-center gap-2">
            <div className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
            <span className={`text-[10px] font-bold tracking-widest font-mono ${cfg.color}`}>
                {cfg.label}
            </span>
        </div>
    );
}

function formatDuration(ms: number) {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
    const m = Math.floor(ms / 60_000);
    const s = Math.floor((ms % 60_000) / 1000);
    return `${m}m ${s}s`;
}

function timeAgo(dateStr: string | null) {
    if (!dateStr) return '—';
    const diff = Date.now() - new Date(dateStr).getTime();
    if (diff < 60_000) return 'только что';
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} мин назад`;
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} ч назад`;
    return new Date(dateStr).toLocaleDateString('ru-RU');
}

const STEP_TYPE_COLORS: Record<string, string> = {
    execute_script: 'border-primary text-primary',
    condition: 'border-amber-400 text-amber-400',
    action: 'border-emerald-400 text-emerald-400',
    wait_for_event: 'border-blue-400 text-blue-400',
    parallel: 'border-violet-400 text-violet-400',
    delay: 'border-muted-foreground text-muted-foreground',
    n8n_workflow: 'border-rose-400 text-rose-400',
    loop: 'border-orange-400 text-orange-400',
    sub_pipeline: 'border-cyan-400 text-cyan-400',
};

// ============================================================================
//  ГЛАВНАЯ СТРАНИЦА ОРКЕСТРАЦИИ
// ============================================================================

type TabKey = 'pipelines' | 'schedules' | 'runs';

export default function OrchestrationPage() {
    const [tab, setTab] = useState<TabKey>('pipelines');
    const [search, setSearch] = useState('');
    const [runPipelineTarget, setRunPipelineTarget] = useState<Pipeline | null>(null);
    const [showCreateSchedule, setShowCreateSchedule] = useState(false);
    const [editingSchedule, setEditingSchedule] = useState<Schedule | null>(null);

    const { data: pipelines = [], isLoading: pLoading } = usePipelines();
    const { data: runs = [], isLoading: rLoading } = usePipelineRuns();
    const { data: schedules = [], isLoading: sLoading } = useSchedules();

    // Статистика (вычисляемая)
    const stats = useMemo(() => {
        const activeRuns = runs.filter(r => ['running', 'waiting', 'queued'].includes(r.status.toLowerCase()));
        const completedRuns = runs.filter(r => r.status.toLowerCase() === 'completed');
        const failedRuns = runs.filter(r => ['failed', 'timed_out'].includes(r.status.toLowerCase()));
        const activeSchedules = schedules.filter(s => s.is_active);
        return {
            totalPipelines: pipelines.length,
            activeRuns: activeRuns.length,
            completedRuns: completedRuns.length,
            failedRuns: failedRuns.length,
            totalSchedules: schedules.length,
            activeSchedules: activeSchedules.length,
            successRate: runs.length > 0
                ? ((completedRuns.length / runs.length) * 100).toFixed(1)
                : '—',
        };
    }, [pipelines, runs, schedules]);

    const TABS: { key: TabKey; label: string; count: number }[] = [
        { key: 'pipelines', label: 'Pipelines', count: pipelines.length },
        { key: 'runs', label: 'Pipeline Runs', count: runs.length },
        { key: 'schedules', label: 'Schedules', count: schedules.length },
    ];

    return (
        <div className="flex flex-col h-full bg-card">

            {/* ── HEADER ─────────────────────────────────────────────────────── */}
            <div className="px-6 py-5 border-b border-border bg-muted shrink-0">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                    <div>
                        <div className="flex items-center gap-2 mb-1">
                            <GitBranch className="w-5 h-5 text-primary" />
                            <h1 className="text-xl font-bold font-mono tracking-tight text-foreground uppercase pt-1">
                                Orchestration
                            </h1>
                            <Badge variant="outline" className="ml-2 text-[9px]">LIVE</Badge>
                        </div>
                        <p className="text-xs text-muted-foreground font-mono max-w-2xl">
                            Pipeline Engine, Scheduler, DAG запуски и расписания. Полное управление автоматизацией в реальном времени.
                        </p>
                    </div>

                    <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
                        <div className="relative w-full sm:w-64">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
                            <Input
                                placeholder="Поиск..."
                                className="pl-9 h-9 bg-black/50 border-border font-mono text-xs focus-visible:ring-primary/50"
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                            />
                        </div>
                        <CreatePipelineButton />
                    </div>
                </div>
            </div>

            {/* ── STATS CARDS ────────────────────────────────────────────────── */}
            <div className="px-6 pt-5">
                <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3 mb-5">
                    <StatCard label="Pipelines" value={stats.totalPipelines} icon={<Layers className="w-7 h-7 text-primary/30" strokeWidth={1} />} />
                    <StatCard label="Active Runs" value={stats.activeRuns} icon={<Activity className="w-7 h-7 text-primary/30" strokeWidth={1} />} accent />
                    <StatCard label="Completed" value={stats.completedRuns} icon={<CheckCircle2 className="w-7 h-7 text-success/30" strokeWidth={1} />} />
                    <StatCard label="Failed" value={stats.failedRuns} icon={<ShieldAlert className="w-7 h-7 text-destructive/30" strokeWidth={1} />} destructive />
                    <StatCard label="Success Rate" value={`${stats.successRate}%`} icon={<Zap className="w-7 h-7 text-success/30" strokeWidth={1} />} />
                    <StatCard label="Schedules Active" value={`${stats.activeSchedules}/${stats.totalSchedules}`} icon={<CalendarClock className="w-7 h-7 text-primary/30" strokeWidth={1} />} />
                </div>
            </div>

            {/* ── TABS ───────────────────────────────────────────────────────── */}
            <div className="px-6 border-b border-border shrink-0">
                <div className="flex gap-1">
                    {TABS.map(t => (
                        <button
                            key={t.key}
                            onClick={() => setTab(t.key)}
                            className={`px-4 py-2 text-xs font-mono font-bold tracking-widest uppercase transition-colors relative
                ${tab === t.key
                                    ? 'text-primary'
                                    : 'text-muted-foreground hover:text-foreground'
                                }`}
                        >
                            {t.label}
                            <span className="ml-1.5 text-[9px] opacity-50">{t.count}</span>
                            {tab === t.key && (
                                <div className="absolute bottom-0 left-0 right-0 h-[2px] bg-primary rounded-t-full" />
                            )}
                        </button>
                    ))}
                </div>
            </div>

            {/* ── CONTENT ────────────────────────────────────────────────────── */}
            <div className="flex-1 overflow-auto p-6">
                {tab === 'pipelines' && <PipelinesTab pipelines={pipelines} loading={pLoading} search={search} onRunPipeline={setRunPipelineTarget} />}
                {tab === 'runs' && <RunsTab runs={runs} pipelines={pipelines} loading={rLoading} search={search} />}
                {tab === 'schedules' && <SchedulesTab schedules={schedules} pipelines={pipelines} loading={sLoading} search={search} onCreateSchedule={() => setShowCreateSchedule(true)} onEditSchedule={setEditingSchedule} />}
            </div>

            {/* ── МОДАЛКИ (controlled mode — Dialog всегда в DOM, Portal рендерится по open) ── */}
            <RunPipelineDialog
                pipeline={runPipelineTarget}
                open={!!runPipelineTarget}
                onOpenChange={(v) => { if (!v) setRunPipelineTarget(null); }}
            />
            <CreateScheduleDialog
                open={showCreateSchedule}
                onOpenChange={setShowCreateSchedule}
                pipelines={pipelines}
            />
            <EditScheduleDialog
                schedule={editingSchedule}
                open={!!editingSchedule}
                onOpenChange={(v) => { if (!v) setEditingSchedule(null); }}
                pipelines={pipelines}
            />
        </div>
    );
}

// ============================================================================
//  STAT CARD
// ============================================================================

function StatCard({
    label, value, icon, accent, destructive
}: {
    label: string; value: string | number; icon: React.ReactNode; accent?: boolean; destructive?: boolean
}) {
    return (
        <div className="border border-border bg-muted rounded-sm p-4 flex items-center justify-between hover:border-border/60 transition-colors">
            <div>
                <div className="text-[10px] uppercase text-muted-foreground font-bold tracking-widest mb-1">{label}</div>
                <div className={`text-2xl font-mono font-bold ${destructive ? 'text-destructive' : accent ? 'text-primary' : 'text-foreground'
                    }`}>
                    {value}
                </div>
            </div>
            {icon}
        </div>
    );
}

// ============================================================================
//  TAB: PIPELINES
// ============================================================================

function PipelinesTab({ pipelines, loading, search, onRunPipeline }: { pipelines: Pipeline[]; loading: boolean; search: string; onRunPipeline: (p: Pipeline) => void }) {
    const [expandedId, setExpandedId] = useState<string | null>(null);

    const filtered = useMemo(() => {
        if (!search) return pipelines;
        const q = search.toLowerCase();
        return pipelines.filter(p =>
            p.name.toLowerCase().includes(q) ||
            p.description?.toLowerCase().includes(q) ||
            p.tags.some(t => t.toLowerCase().includes(q))
        );
    }, [pipelines, search]);

    return (
        <div className="rounded-sm border border-border bg-card shadow-2xl overflow-hidden">
            <table className="w-full text-left whitespace-nowrap">
                <thead className="bg-[#151515]/90 border-b border-border text-[10px] uppercase font-mono tracking-widest font-bold text-muted-foreground sticky top-0 backdrop-blur-sm z-10">
                    <tr>
                        <th className="px-4 py-3 w-10"></th>
                        <th className="px-4 py-3">Название</th>
                        <th className="px-4 py-3 w-[100px]">Шаги</th>
                        <th className="px-4 py-3 w-[100px]">Версия</th>
                        <th className="px-4 py-3 w-[100px]">Статус</th>
                        <th className="px-4 py-3 w-[120px]">Теги</th>
                        <th className="px-4 py-3 w-[140px]">Обновлён</th>
                        <th className="px-4 py-3 w-[120px] text-right">Действия</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-[#222]/50 font-mono text-xs text-foreground/80">
                    {loading && (
                        <tr><td colSpan={8} className="px-4 py-12 text-center text-muted-foreground animate-pulse">Загрузка pipelines...</td></tr>
                    )}
                    {!loading && filtered.length === 0 && (
                        <tr><td colSpan={8} className="px-4 py-12 text-center text-muted-foreground">
                            {pipelines.length === 0 ? 'Нет pipelines. Создайте первый!' : 'Ничего не найдено'}
                        </td></tr>
                    )}
                    {filtered.map(p => (
                        <PipelineRow
                            key={p.id}
                            pipeline={p}
                            expanded={expandedId === p.id}
                            onToggle={() => setExpandedId(expandedId === p.id ? null : p.id)}
                            onRunPipeline={() => onRunPipeline(p)}
                        />
                    ))}
                </tbody>
            </table>
        </div>
    );
}

function PipelineRow({ pipeline: p, expanded, onToggle, onRunPipeline }: { pipeline: Pipeline; expanded: boolean; onToggle: () => void; onRunPipeline: () => void }) {
    const queryClient = useQueryClient();

    return (
        <>
            <tr className="hover:bg-muted transition-colors group cursor-pointer" onClick={onToggle}>
                <td className="px-4 py-3">
                    {expanded
                        ? <ChevronDown className="w-3.5 h-3.5 text-primary" />
                        : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground group-hover:text-foreground" />
                    }
                </td>
                <td className="px-4 py-3">
                    <div className="font-bold text-foreground group-hover:text-primary transition-colors">{p.name}</div>
                    {p.description && <div className="text-[10px] text-muted-foreground mt-0.5 max-w-[300px] truncate">{p.description}</div>}
                </td>
                <td className="px-4 py-3">
                    <Badge variant="outline" className="text-[9px]">{p.steps.length} шагов</Badge>
                </td>
                <td className="px-4 py-3 text-muted-foreground">v{p.version}</td>
                <td className="px-4 py-3">
                    {p.is_active
                        ? <Badge variant="success" className="text-[9px]">ACTIVE</Badge>
                        : <Badge variant="secondary" className="text-[9px]">INACTIVE</Badge>
                    }
                </td>
                <td className="px-4 py-3">
                    <div className="flex gap-1 flex-wrap">
                        {p.tags.slice(0, 3).map(t => (
                            <Badge key={t} variant="outline" className="text-[8px] px-1 py-0 border-border">{t}</Badge>
                        ))}
                    </div>
                </td>
                <td className="px-4 py-3 text-muted-foreground">{timeAgo(p.updated_at)}</td>
                <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="tiny" className="text-muted-foreground hover:text-success hover:bg-success/10" title="Запустить" onClick={onRunPipeline}>
                            <Play className="w-3 h-3" />
                        </Button>
                        <Button variant="ghost" size="tiny" className="text-muted-foreground hover:text-primary hover:bg-primary/10" title="Просмотр" onClick={onToggle}>
                            <Eye className="w-3 h-3" />
                        </Button>
                    </div>
                </td>
            </tr>

            {/* Развернутые шаги pipeline */}
            {expanded && (
                <tr>
                    <td colSpan={8} className="bg-background/50 px-0 py-0">
                        <div className="px-10 py-4 border-l-2 border-primary/30 ml-4">
                            <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground mb-3 flex items-center gap-2">
                                <Workflow className="w-3.5 h-3.5" /> ШАГИ PIPELINE — ГРАФ ИСПОЛНЕНИЯ
                            </div>
                            <div className="flex items-start gap-2 overflow-x-auto pb-2 custom-scrollbar">
                                {p.steps.map((step, idx) => (
                                    <div key={step.id} className="flex items-start gap-2 shrink-0">
                                        <div className={`border rounded-sm p-3 min-w-[160px] bg-card hover:border-primary/40 transition-colors ${STEP_TYPE_COLORS[step.type] ? 'border-l-2 ' + STEP_TYPE_COLORS[step.type].split(' ')[0].replace('border-', 'border-l-') : 'border-border'
                                            }`}>
                                            <div className="text-[9px] uppercase font-bold tracking-widest mb-1">
                                                <Badge variant="outline" className={`text-[8px] ${STEP_TYPE_COLORS[step.type] || 'border-border text-muted-foreground'}`}>
                                                    {step.type}
                                                </Badge>
                                            </div>
                                            <div className="text-xs font-bold text-foreground">{step.name}</div>
                                            <div className="text-[10px] text-muted-foreground mt-1 font-mono">
                                                ID: {step.id}
                                            </div>
                                            {step.retries > 0 && (
                                                <div className="text-[10px] text-muted-foreground mt-0.5 flex items-center gap-1">
                                                    <Repeat className="w-2.5 h-2.5" /> {step.retries}x retry
                                                </div>
                                            )}
                                            {step.timeout_ms && (
                                                <div className="text-[10px] text-muted-foreground mt-0.5 flex items-center gap-1">
                                                    <Timer className="w-2.5 h-2.5" /> {formatDuration(step.timeout_ms)}
                                                </div>
                                            )}
                                        </div>
                                        {idx < p.steps.length - 1 && (
                                            <div className="flex items-center self-center text-muted-foreground/40 pt-2">
                                                <div className="w-4 h-px bg-border" />
                                                <ChevronRight className="w-3 h-3" />
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                            <div className="mt-3 flex items-center gap-4 text-[10px] text-muted-foreground">
                                <span>Глобальный таймаут: <span className="text-foreground font-bold">{formatDuration(p.global_timeout_ms)}</span></span>
                                <span>Макс. ретраев: <span className="text-foreground font-bold">{p.max_retries}</span></span>
                            </div>
                        </div>
                    </td>
                </tr>
            )}
        </>
    );
}

// ============================================================================
//  TAB: PIPELINE RUNS
// ============================================================================

function RunsTab({
    runs, pipelines, loading, search
}: {
    runs: PipelineRun[]; pipelines: Pipeline[]; loading: boolean; search: string
}) {
    const queryClient = useQueryClient();
    const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
    const pipelineMap = useMemo(() => new Map(pipelines.map(p => [p.id, p])), [pipelines]);

    // Мутации управления
    const cancelMut = useMutation({
        mutationFn: (runId: string) => api.post(`/pipelines/runs/${runId}/cancel`),
        onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['pipeline-runs'] }); toast.success('Run отменён'); },
        onError: () => toast.error('Ошибка отмены'),
    });

    const pauseMut = useMutation({
        mutationFn: (runId: string) => api.post(`/pipelines/runs/${runId}/pause`),
        onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['pipeline-runs'] }); toast.success('Run приостановлен'); },
        onError: () => toast.error('Ошибка паузы'),
    });

    const resumeMut = useMutation({
        mutationFn: (runId: string) => api.post(`/pipelines/runs/${runId}/resume`),
        onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['pipeline-runs'] }); toast.success('Run возобновлён'); },
        onError: () => toast.error('Ошибка возобновления'),
    });

    const filtered = useMemo(() => {
        const sorted = [...runs].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
        if (!search) return sorted;
        const q = search.toLowerCase();
        return sorted.filter(r =>
            r.id.toLowerCase().includes(q) ||
            r.status.toLowerCase().includes(q) ||
            pipelineMap.get(r.pipeline_id)?.name.toLowerCase().includes(q)
        );
    }, [runs, search, pipelineMap]);

    return (
        <div className="rounded-sm border border-border bg-card shadow-2xl overflow-hidden">
            <table className="w-full text-left whitespace-nowrap">
                <thead className="bg-[#151515]/90 border-b border-border text-[10px] uppercase font-mono tracking-widest font-bold text-muted-foreground sticky top-0 backdrop-blur-sm z-10">
                    <tr>
                        <th className="px-4 py-3 w-10"></th>
                        <th className="px-4 py-3 w-[130px]">Статус</th>
                        <th className="px-4 py-3">Pipeline</th>
                        <th className="px-4 py-3 w-[140px]">Устройство</th>
                        <th className="px-4 py-3 w-[120px]">Текущий шаг</th>
                        <th className="px-4 py-3 w-[100px]">Шагов</th>
                        <th className="px-4 py-3 w-[140px]">Создан</th>
                        <th className="px-4 py-3 w-[140px] text-right">Управление</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-[#222]/50 font-mono text-xs text-foreground/80">
                    {loading && (
                        <tr><td colSpan={8} className="px-4 py-12 text-center text-muted-foreground animate-pulse">Загрузка runs...</td></tr>
                    )}
                    {!loading && filtered.length === 0 && (
                        <tr><td colSpan={8} className="px-4 py-12 text-center text-muted-foreground">Нет запусков pipeline</td></tr>
                    )}
                    {filtered.map(run => {
                        const pl = pipelineMap.get(run.pipeline_id);
                        const isActive = ['running', 'waiting', 'queued'].includes(run.status.toLowerCase());
                        const isPaused = run.status.toLowerCase() === 'paused';
                        const expanded = expandedRunId === run.id;

                        return (
                            <RunRow
                                key={run.id}
                                run={run}
                                pipelineName={pl?.name}
                                expanded={expanded}
                                onToggle={() => setExpandedRunId(expanded ? null : run.id)}
                                isActive={isActive}
                                isPaused={isPaused}
                                onCancel={() => cancelMut.mutate(run.id)}
                                onPause={() => pauseMut.mutate(run.id)}
                                onResume={() => resumeMut.mutate(run.id)}
                            />
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}

function RunRow({
    run, pipelineName, expanded, onToggle, isActive, isPaused, onCancel, onPause, onResume
}: {
    run: PipelineRun;
    pipelineName?: string;
    expanded: boolean;
    onToggle: () => void;
    isActive: boolean;
    isPaused: boolean;
    onCancel: () => void;
    onPause: () => void;
    onResume: () => void;
}) {
    return (
        <>
            <tr className="hover:bg-muted transition-colors group cursor-pointer" onClick={onToggle}>
                <td className="px-4 py-3">
                    {expanded
                        ? <ChevronDown className="w-3.5 h-3.5 text-primary" />
                        : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground group-hover:text-foreground" />
                    }
                </td>
                <td className="px-4 py-3"><StatusBadge status={run.status} /></td>
                <td className="px-4 py-3">
                    <div className="font-bold text-foreground group-hover:text-primary transition-colors">
                        {pipelineName || 'Unknown Pipeline'}
                    </div>
                    <div className="text-[10px] text-[#555] mt-0.5">{run.id.slice(0, 12)}...</div>
                </td>
                <td className="px-4 py-3 text-muted-foreground">{run.device_id.slice(0, 12)}...</td>
                <td className="px-4 py-3">
                    {run.current_step_id
                        ? <Badge variant="outline" className="text-[9px] border-primary/40 text-primary">{run.current_step_id}</Badge>
                        : <span className="text-muted-foreground">—</span>
                    }
                </td>
                <td className="px-4 py-3 text-muted-foreground">{run.step_logs.length}</td>
                <td className="px-4 py-3 text-muted-foreground">{timeAgo(run.created_at)}</td>
                <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-1">
                        {isActive && (
                            <>
                                <Button variant="ghost" size="tiny" className="text-muted-foreground hover:text-warning hover:bg-warning/10" onClick={onPause} title="Пауза">
                                    <Pause className="w-3 h-3" />
                                </Button>
                                <Button variant="ghost" size="tiny" className="text-muted-foreground hover:text-destructive hover:bg-destructive/10" onClick={onCancel} title="Отмена">
                                    <XCircle className="w-3 h-3" />
                                </Button>
                            </>
                        )}
                        {isPaused && (
                            <Button variant="ghost" size="tiny" className="text-muted-foreground hover:text-success hover:bg-success/10" onClick={onResume} title="Возобновить">
                                <Play className="w-3 h-3" />
                            </Button>
                        )}
                    </div>
                </td>
            </tr>

            {/* Развёрнутый лог шагов */}
            {expanded && run.step_logs.length > 0 && (
                <tr>
                    <td colSpan={8} className="bg-background/50 px-0 py-0">
                        <div className="px-10 py-4 border-l-2 border-primary/30 ml-4">
                            <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground mb-3">
                                ЛОГ ШАГОВ ИСПОЛНЕНИЯ
                            </div>
                            <div className="space-y-1.5">
                                {run.step_logs.map((log, idx) => (
                                    <div key={idx} className="flex items-center gap-3 text-[11px] font-mono">
                                        <span className="w-5 text-muted-foreground/50 text-right">{idx + 1}</span>
                                        <StatusBadge status={log.status === 'success' ? 'completed' : log.status === 'failed' ? 'failed' : 'running'} />
                                        <span className="text-foreground font-bold">{log.step_id}</span>
                                        {log.type && (
                                            <Badge variant="outline" className={`text-[8px] ${STEP_TYPE_COLORS[log.type] || ''}`}>{log.type}</Badge>
                                        )}
                                        {log.duration_ms != null && (
                                            <span className="text-muted-foreground">{formatDuration(log.duration_ms)}</span>
                                        )}
                                        {log.error && (
                                            <span className="text-destructive text-[10px] truncate max-w-[200px]" title={log.error}>⚠ {log.error}</span>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    </td>
                </tr>
            )}
        </>
    );
}

// ============================================================================
//  TAB: SCHEDULES
// ============================================================================

function SchedulesTab({ schedules, pipelines, loading, search, onCreateSchedule, onEditSchedule }: { schedules: Schedule[]; pipelines: Pipeline[]; loading: boolean; search: string; onCreateSchedule: () => void; onEditSchedule: (s: Schedule) => void }) {
    const queryClient = useQueryClient();

    const toggleMut = useMutation({
        mutationFn: ({ id, active }: { id: string; active: boolean }) =>
            api.post(`/schedules/${id}/toggle?active=${active}`),
        onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['schedules'] }); toast.success('Расписание обновлено'); },
        onError: () => toast.error('Ошибка'),
    });

    const fireNowMut = useMutation({
        mutationFn: (id: string) => api.post(`/schedules/${id}/fire-now`),
        onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['schedules'] }); toast.success('Расписание запущено!'); },
        onError: () => toast.error('Ошибка запуска'),
    });

    const deleteMut = useMutation({
        mutationFn: (id: string) => api.delete(`/schedules/${id}`),
        onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['schedules'] }); toast.success('Расписание удалено'); },
        onError: () => toast.error('Ошибка удаления'),
    });

    const filtered = useMemo(() => {
        if (!search) return schedules;
        const q = search.toLowerCase();
        return schedules.filter(s =>
            s.name.toLowerCase().includes(q) ||
            s.cron_expression?.toLowerCase().includes(q) ||
            s.target_type.toLowerCase().includes(q)
        );
    }, [schedules, search]);

    return (
        <div className="space-y-4">
            <div className="flex justify-end">
                <Button variant="outline" size="sm" className="h-8 text-xs font-mono" onClick={onCreateSchedule}>
                    <Plus className="w-3.5 h-3.5 mr-1.5" /> Новое расписание
                </Button>
            </div>
            <div className="rounded-sm border border-border bg-card shadow-2xl overflow-hidden">
            <table className="w-full text-left whitespace-nowrap">
                <thead className="bg-[#151515]/90 border-b border-border text-[10px] uppercase font-mono tracking-widest font-bold text-muted-foreground sticky top-0 backdrop-blur-sm z-10">
                    <tr>
                        <th className="px-4 py-3">Состояние</th>
                        <th className="px-4 py-3">Название</th>
                        <th className="px-4 py-3 w-[120px]">Тип</th>
                        <th className="px-4 py-3 w-[170px]">Триггер</th>
                        <th className="px-4 py-3 w-[100px]">Запусков</th>
                        <th className="px-4 py-3 w-[140px]">Последний</th>
                        <th className="px-4 py-3 w-[140px]">Следующий</th>
                        <th className="px-4 py-3 w-[100px]">Политика</th>
                        <th className="px-4 py-3 w-[140px] text-right">Действия</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-[#222]/50 font-mono text-xs text-foreground/80">
                    {loading && (
                        <tr><td colSpan={9} className="px-4 py-12 text-center text-muted-foreground animate-pulse">Загрузка расписаний...</td></tr>
                    )}
                    {!loading && filtered.length === 0 && (
                        <tr><td colSpan={9} className="px-4 py-12 text-center text-muted-foreground">
                            {schedules.length === 0 ? 'Нет расписаний. Создайте первое!' : 'Ничего не найдено'}
                        </td></tr>
                    )}
                    {filtered.map(s => {
                        const triggerInfo = s.cron_expression
                            ? { type: 'CRON', value: s.cron_expression, color: 'border-primary text-primary' }
                            : s.interval_seconds
                                ? { type: 'INTERVAL', value: `каждые ${s.interval_seconds}s`, color: 'border-amber-400 text-amber-400' }
                                : { type: 'ONE-SHOT', value: s.one_shot_at ? new Date(s.one_shot_at).toLocaleString('ru-RU') : '—', color: 'border-cyan-400 text-cyan-400' };

                        return (
                            <tr key={s.id} className="hover:bg-muted transition-colors group">
                                <td className="px-4 py-3">
                                    <button
                                        onClick={() => toggleMut.mutate({ id: s.id, active: !s.is_active })}
                                        className="focus:outline-none"
                                        title={s.is_active ? 'Деактивировать' : 'Активировать'}
                                    >
                                        {s.is_active
                                            ? <ToggleRight className="w-5 h-5 text-success" />
                                            : <ToggleLeft className="w-5 h-5 text-muted-foreground" />
                                        }
                                    </button>
                                </td>
                                <td className="px-4 py-3">
                                    <div className="font-bold text-foreground group-hover:text-primary transition-colors">{s.name}</div>
                                    <div className="text-[10px] text-[#555] mt-0.5">{s.id.slice(0, 12)}...</div>
                                </td>
                                <td className="px-4 py-3">
                                    <Badge variant="outline" className={`text-[9px] ${s.target_type === 'script' ? 'border-emerald-400 text-emerald-400' : 'border-violet-400 text-violet-400'}`}>
                                        {s.target_type.toUpperCase()}
                                    </Badge>
                                </td>
                                <td className="px-4 py-3">
                                    <div className="flex items-center gap-2">
                                        <Badge variant="outline" className={`text-[8px] ${triggerInfo.color}`}>{triggerInfo.type}</Badge>
                                        <span className="text-muted-foreground text-[10px]">{triggerInfo.value}</span>
                                    </div>
                                </td>
                                <td className="px-4 py-3 text-muted-foreground">{s.total_runs}</td>
                                <td className="px-4 py-3 text-muted-foreground">{timeAgo(s.last_fired_at)}</td>
                                <td className="px-4 py-3">
                                    {s.next_fire_at
                                        ? <span className="text-foreground font-bold">{new Date(s.next_fire_at).toLocaleString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                                        : <span className="text-muted-foreground">—</span>
                                    }
                                </td>
                                <td className="px-4 py-3">
                                    <Badge variant="outline" className={`text-[8px] ${s.conflict_policy === 'skip' ? 'border-amber-400 text-amber-400' :
                                            s.conflict_policy === 'queue' ? 'border-blue-400 text-blue-400' :
                                                'border-destructive text-destructive'
                                        }`}>
                                        {s.conflict_policy.toUpperCase()}
                                    </Badge>
                                </td>
                                <td className="px-4 py-3 text-right">
                                    <div className="flex items-center justify-end gap-1">
                                        <Button
                                            variant="ghost" size="tiny"
                                            className="text-muted-foreground hover:text-success hover:bg-success/10"
                                            onClick={() => fireNowMut.mutate(s.id)}
                                            title="Запустить сейчас"
                                        >
                                            <Zap className="w-3 h-3" />
                                        </Button>
                                        <Button
                                            variant="ghost" size="tiny"
                                            className="text-muted-foreground hover:text-primary hover:bg-primary/10"
                                            title="Редактировать"
                                            onClick={() => onEditSchedule(s)}
                                        >
                                            <Pencil className="w-3 h-3" />
                                        </Button>
                                        <Button
                                            variant="ghost" size="tiny"
                                            className="text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                                            title="Удалить"
                                            onClick={() => {
                                                if (confirm(`Удалить расписание «${s.name}»?`)) {
                                                    deleteMut.mutate(s.id);
                                                }
                                            }}
                                        >
                                            <Trash2 className="w-3 h-3" />
                                        </Button>
                                    </div>
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
        </div>
    );
}


// ============================================================================
//  ДИАЛОГ: СОЗДАНИЕ PIPELINE (Enterprise Step Builder)
// ============================================================================

const STEP_TYPES = [
    { value: 'execute_script', label: 'Execute Script' },
    { value: 'condition', label: 'Condition (if/else)' },
    { value: 'action', label: 'Action' },
    { value: 'delay', label: 'Delay' },
    { value: 'parallel', label: 'Parallel' },
    { value: 'wait_for_event', label: 'Wait for Event' },
    { value: 'n8n_workflow', label: 'n8n Workflow' },
    { value: 'loop', label: 'Loop' },
    { value: 'sub_pipeline', label: 'Sub-Pipeline' },
] as const;

interface StepDraft {
    id: string;
    name: string;
    type: string;
    params: string;
    timeout_ms: number;
    retries: number;
    on_success: string;
    on_failure: string;
    script_id: string;
}

function emptyStep(index: number): StepDraft {
    return {
        id: `step_${index + 1}`,
        name: '',
        type: 'execute_script',
        params: '{}',
        timeout_ms: 60000,
        retries: 0,
        on_success: '',
        on_failure: '',
        script_id: '',
    };
}

function CreatePipelineButton() {
    const queryClient = useQueryClient();
    const { data: scriptsData } = useScripts();
    const scripts = scriptsData?.items ?? [];
    const [open, setOpen] = useState(false);
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [tags, setTags] = useState('');
    const [globalTimeout, setGlobalTimeout] = useState(86400000);
    const [maxRetries, setMaxRetries] = useState(0);
    const [steps, setSteps] = useState<StepDraft[]>([emptyStep(0)]);
    const [targetDeviceIds, setTargetDeviceIds] = useState<string[]>([]);
    const [showDeviceSelector, setShowDeviceSelector] = useState(false);

    const resetForm = useCallback(() => {
        setName('');
        setDescription('');
        setTags('');
        setGlobalTimeout(86400000);
        setMaxRetries(0);
        setSteps([emptyStep(0)]);
        setTargetDeviceIds([]);
        setShowDeviceSelector(false);
    }, []);

    const createMut = useMutation({
        mutationFn: async () => {
            const payload = {
                name: name.trim(),
                description: description.trim() || null,
                steps: steps.map(s => {
                    let parsedParams = JSON.parse(s.params || '{}');
                    // Для execute_script автоматически подставляем script_id
                    if (s.type === 'execute_script' && s.script_id) {
                        parsedParams = { ...parsedParams, script_id: s.script_id };
                    }
                    return {
                        id: s.id.trim(),
                        name: s.name.trim(),
                        type: s.type,
                        params: parsedParams,
                        on_success: s.on_success.trim() || null,
                        on_failure: s.on_failure.trim() || null,
                        timeout_ms: s.timeout_ms,
                        retries: s.retries,
                    };
                }),
                input_schema: {},
                global_timeout_ms: globalTimeout,
                max_retries: maxRetries,
                tags: tags.split(',').map(t => t.trim()).filter(Boolean),
            };
            const { data } = await api.post('/pipelines', payload);
            return data;
        },
        onSuccess: async (pipeline: any) => {
            queryClient.invalidateQueries({ queryKey: ['pipelines'] });
            // Если выбраны устройства — сразу batch-запуск
            if (targetDeviceIds.length > 0 && pipeline?.id) {
                try {
                    if (targetDeviceIds.length === 1) {
                        await api.post(`/pipelines/${pipeline.id}/run`, {
                            device_id: targetDeviceIds[0],
                            input_params: {},
                        });
                    } else {
                        await api.post(`/pipelines/${pipeline.id}/run-batch`, {
                            device_ids: targetDeviceIds,
                            input_params: {},
                        });
                    }
                    queryClient.invalidateQueries({ queryKey: ['pipeline-runs'] });
                    toast.success(`Pipeline создан и запущен на ${targetDeviceIds.length} устройствах`);
                } catch (err: any) {
                    toast.success('Pipeline создан');
                    toast.error('Не удалось запустить: ' + (err?.response?.data?.detail || 'ошибка'));
                }
            } else {
                toast.success('Pipeline создан');
            }
            resetForm();
            setOpen(false);
        },
        onError: (err: any) => {
            const detail = err?.response?.data?.detail;
            toast.error(typeof detail === 'string' ? detail : 'Ошибка создания pipeline');
        },
    });

    const addStep = () => setSteps(prev => [...prev, emptyStep(prev.length)]);
    const removeStep = (idx: number) => setSteps(prev => prev.filter((_, i) => i !== idx));
    const moveStep = (idx: number, dir: -1 | 1) => {
        setSteps(prev => {
            const arr = [...prev];
            const target = idx + dir;
            if (target < 0 || target >= arr.length) return arr;
            [arr[idx], arr[target]] = [arr[target], arr[idx]];
            return arr;
        });
    };
    const updateStep = (idx: number, patch: Partial<StepDraft>) => {
        setSteps(prev => prev.map((s, i) => i === idx ? { ...s, ...patch } : s));
    };
    const duplicateStep = (idx: number) => {
        setSteps(prev => {
            const copy = { ...prev[idx], id: `${prev[idx].id}_copy`, name: `${prev[idx].name} (копия)` };
            const arr = [...prev];
            arr.splice(idx + 1, 0, copy);
            return arr;
        });
    };

    const canSubmit = name.trim().length > 0 && steps.length > 0 && steps.every(s => s.id.trim() && s.name.trim());

    const validateParamsJson = (val: string): boolean => {
        try { JSON.parse(val || '{}'); return true; } catch { return false; }
    };

    return (
        <>
            <Button variant="default" size="sm" className="h-9" onClick={() => setOpen(true)}>
                <Plus className="w-4 h-4 mr-2" /> Новый Pipeline
            </Button>
            <Dialog open={open} onOpenChange={setOpen}>
                <DialogContent className="max-w-4xl max-h-[90vh] overflow-hidden flex flex-col bg-card border-border">
                <DialogHeader>
                    <DialogTitle className="font-mono tracking-tight flex items-center gap-2">
                        <GitBranch className="w-5 h-5 text-primary" />
                        Создать Pipeline
                    </DialogTitle>
                    <DialogDescription className="text-xs text-muted-foreground font-mono">
                        Построй цепочку шагов автоматизации. Каждый шаг выполняется последовательно или по DAG-логике (on_success/on_failure).
                    </DialogDescription>
                </DialogHeader>

                <div className="flex-1 overflow-y-auto space-y-5 pr-2 custom-scrollbar">
                    {/* Основные поля */}
                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Название *</Label>
                            <Input
                                placeholder="Например: Reboot + Screenshot + Report"
                                value={name}
                                onChange={e => setName(e.target.value)}
                                className="h-9 bg-black/30 border-border font-mono text-xs"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Теги (через запятую)</Label>
                            <Input
                                placeholder="automation, reboot, critical"
                                value={tags}
                                onChange={e => setTags(e.target.value)}
                                className="h-9 bg-black/30 border-border font-mono text-xs"
                            />
                        </div>
                    </div>
                    <div className="space-y-1.5">
                        <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Описание</Label>
                        <textarea
                            placeholder="Описание pipeline..."
                            value={description}
                            onChange={e => setDescription(e.target.value)}
                            rows={2}
                            className="w-full rounded-sm border border-border bg-black/30 px-3 py-2 text-xs font-mono text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 resize-none"
                        />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Глобальный таймаут (мс)</Label>
                            <Input
                                type="number"
                                value={globalTimeout}
                                onChange={e => setGlobalTimeout(Number(e.target.value))}
                                className="h-9 bg-black/30 border-border font-mono text-xs"
                                min={10000}
                                max={259200000}
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Макс. ретраев pipeline</Label>
                            <Input
                                type="number"
                                value={maxRetries}
                                onChange={e => setMaxRetries(Number(e.target.value))}
                                className="h-9 bg-black/30 border-border font-mono text-xs"
                                min={0}
                                max={5}
                            />
                        </div>
                    </div>

                    {/* Шаги pipeline */}
                    <div>
                        <div className="flex items-center justify-between mb-3">
                            <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground flex items-center gap-2">
                                <Workflow className="w-3.5 h-3.5" />
                                ШАГИ PIPELINE ({steps.length})
                            </div>
                            <Button variant="outline" size="sm" className="h-7 text-[10px] font-mono" onClick={addStep}>
                                <Plus className="w-3 h-3 mr-1" /> Добавить шаг
                            </Button>
                        </div>

                        <div className="space-y-3">
                            {steps.map((step, idx) => (
                                <div key={idx} className="border border-border rounded-sm bg-muted/50 p-3 relative group">
                                    {/* Шапка шага */}
                                    <div className="flex items-center justify-between mb-3">
                                        <div className="flex items-center gap-2">
                                            <span className="text-[10px] font-mono font-bold text-primary">#{idx + 1}</span>
                                            <Badge variant="outline" className={`text-[8px] ${STEP_TYPE_COLORS[step.type] || 'border-border'}`}>
                                                {step.type}
                                            </Badge>
                                        </div>
                                        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                                            <Button variant="ghost" size="tiny" onClick={() => moveStep(idx, -1)} disabled={idx === 0} title="Вверх">
                                                <ArrowUp className="w-3 h-3" />
                                            </Button>
                                            <Button variant="ghost" size="tiny" onClick={() => moveStep(idx, 1)} disabled={idx === steps.length - 1} title="Вниз">
                                                <ArrowDown className="w-3 h-3" />
                                            </Button>
                                            <Button variant="ghost" size="tiny" onClick={() => duplicateStep(idx)} title="Дубликат">
                                                <Copy className="w-3 h-3" />
                                            </Button>
                                            <Button variant="ghost" size="tiny" className="hover:text-destructive" onClick={() => removeStep(idx)} disabled={steps.length <= 1} title="Удалить">
                                                <Trash2 className="w-3 h-3" />
                                            </Button>
                                        </div>
                                    </div>

                                    {/* Поля шага */}
                                    <div className="grid grid-cols-3 gap-3 mb-2">
                                        <div className="space-y-1">
                                            <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">ID шага *</Label>
                                            <Input
                                                value={step.id}
                                                onChange={e => updateStep(idx, { id: e.target.value })}
                                                className="h-7 bg-black/30 border-border font-mono text-[11px]"
                                                placeholder="step_1"
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">Название *</Label>
                                            <Input
                                                value={step.name}
                                                onChange={e => updateStep(idx, { name: e.target.value })}
                                                className="h-7 bg-black/30 border-border font-mono text-[11px]"
                                                placeholder="Выполнить скрипт"
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">Тип</Label>
                                            <select
                                                value={step.type}
                                                onChange={e => updateStep(idx, { type: e.target.value })}
                                                className="w-full h-7 rounded-sm border border-border bg-black/30 px-2 text-[11px] font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
                                            >
                                                {STEP_TYPES.map(st => (
                                                    <option key={st.value} value={st.value}>{st.label}</option>
                                                ))}
                                            </select>
                                        </div>
                                    </div>
                                    <div className="grid grid-cols-4 gap-3 mb-2">
                                        <div className="space-y-1">
                                            <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">Таймаут (мс)</Label>
                                            <Input
                                                type="number"
                                                value={step.timeout_ms}
                                                onChange={e => updateStep(idx, { timeout_ms: Number(e.target.value) })}
                                                className="h-7 bg-black/30 border-border font-mono text-[11px]"
                                                min={1000}
                                                max={3600000}
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">Ретраев</Label>
                                            <Input
                                                type="number"
                                                value={step.retries}
                                                onChange={e => updateStep(idx, { retries: Number(e.target.value) })}
                                                className="h-7 bg-black/30 border-border font-mono text-[11px]"
                                                min={0}
                                                max={10}
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">On Success → ID</Label>
                                            <Input
                                                value={step.on_success}
                                                onChange={e => updateStep(idx, { on_success: e.target.value })}
                                                className="h-7 bg-black/30 border-border font-mono text-[11px]"
                                                placeholder="step_2"
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">On Failure → ID</Label>
                                            <Input
                                                value={step.on_failure}
                                                onChange={e => updateStep(idx, { on_failure: e.target.value })}
                                                className="h-7 bg-black/30 border-border font-mono text-[11px]"
                                                placeholder=""
                                            />
                                        </div>
                                    </div>
                                    {/* Выбор скрипта для execute_script */}
                                    {step.type === 'execute_script' && (
                                        <div className="space-y-1 mb-2">
                                            <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">Скрипт *</Label>
                                            <select
                                                value={step.script_id}
                                                onChange={e => {
                                                    const sid = e.target.value;
                                                    const scr = scripts.find(s => s.id === sid);
                                                    updateStep(idx, {
                                                        script_id: sid,
                                                        name: step.name || scr?.name || '',
                                                    });
                                                }}
                                                className="w-full h-7 rounded-sm border border-border bg-black/30 px-2 text-[11px] font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
                                            >
                                                <option value="">Выбери скрипт...</option>
                                                {scripts.filter(s => !s.is_archived).map(s => (
                                                    <option key={s.id} value={s.id}>
                                                        {s.name} ({s.node_count} нод)
                                                    </option>
                                                ))}
                                            </select>
                                        </div>
                                    )}
                                    <div className="space-y-1">
                                        <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">Параметры (JSON)</Label>
                                        <textarea
                                            value={step.params}
                                            onChange={e => updateStep(idx, { params: e.target.value })}
                                            rows={2}
                                            className={`w-full rounded-sm border px-2 py-1.5 text-[11px] font-mono text-foreground bg-black/30 placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 resize-none ${
                                                validateParamsJson(step.params) ? 'border-border' : 'border-destructive'
                                            }`}
                                            placeholder='{"script_id": "...", "args": ["--flag"]}'
                                        />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

                <DialogFooter className="mt-4 pt-4 border-t border-border">
                    <Button variant="outline" onClick={() => setOpen(false)} className="font-mono text-xs">
                        Отмена
                    </Button>
                    <Button
                        onClick={() => {
                            setShowDeviceSelector(false);
                            createMut.mutate();
                        }}
                        disabled={!canSubmit || createMut.isPending}
                        className="font-mono text-xs"
                    >
                        {createMut.isPending && <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" />}
                        Создать Pipeline
                    </Button>
                    <Button
                        variant={showDeviceSelector ? 'default' : 'outline'}
                        onClick={() => {
                            if (showDeviceSelector && targetDeviceIds.length > 0) {
                                createMut.mutate();
                            } else {
                                setShowDeviceSelector(!showDeviceSelector);
                            }
                        }}
                        disabled={(!canSubmit || createMut.isPending) || (showDeviceSelector && targetDeviceIds.length === 0)}
                        className="font-mono text-xs bg-success hover:bg-success/90 text-success-foreground"
                    >
                        {createMut.isPending && <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" />}
                        <Play className="w-3.5 h-3.5 mr-1.5" />
                        {showDeviceSelector
                            ? `Создать и запустить (${targetDeviceIds.length})`
                            : 'Создать и запустить'
                        }
                    </Button>
                </DialogFooter>

                {showDeviceSelector && (
                    <div className="mt-3 pt-3 border-t border-border">
                        <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground mb-2 block">Целевые устройства</Label>
                        <DeviceSelector value={targetDeviceIds} onChange={setTargetDeviceIds} />
                    </div>
                )}
            </DialogContent>
        </Dialog>
        </>
    );
}


// ============================================================================
//  ДИАЛОГ: ЗАПУСК PIPELINE НА УСТРОЙСТВЕ
// ============================================================================

function RunPipelineDialog({ pipeline, open, onOpenChange }: { pipeline: Pipeline | null; open: boolean; onOpenChange: (v: boolean) => void }) {
    const queryClient = useQueryClient();
    const [selectedDeviceIds, setSelectedDeviceIds] = useState<string[]>([]);
    const [inputParams, setInputParams] = useState('{}');

    const runMut = useMutation({
        mutationFn: async () => {
            if (!pipeline) return;
            if (selectedDeviceIds.length === 1) {
                // Одно устройство → прямой запуск
                const { data } = await api.post(`/pipelines/${pipeline.id}/run`, {
                    device_id: selectedDeviceIds[0],
                    input_params: JSON.parse(inputParams || '{}'),
                });
                return data;
            } else {
                // Массовый запуск через batch
                const { data } = await api.post(`/pipelines/${pipeline.id}/run-batch`, {
                    device_ids: selectedDeviceIds,
                    input_params: JSON.parse(inputParams || '{}'),
                });
                return data;
            }
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['pipeline-runs'] });
            toast.success(`Pipeline "${pipeline?.name}" запущен на ${selectedDeviceIds.length} устройствах`);
            setSelectedDeviceIds([]);
            setInputParams('{}');
            onOpenChange(false);
        },
        onError: (err: any) => {
            const detail = err?.response?.data?.detail;
            toast.error(typeof detail === 'string' ? detail : 'Ошибка запуска pipeline');
        },
    });

    const canSubmit = selectedDeviceIds.length > 0;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl max-h-[85vh] overflow-hidden flex flex-col bg-card border-border">
                <DialogHeader>
                    <DialogTitle className="font-mono tracking-tight flex items-center gap-2">
                        <Play className="w-5 h-5 text-success" />
                        Запустить Pipeline
                    </DialogTitle>
                    <DialogDescription className="text-xs text-muted-foreground font-mono">
                        <span className="text-primary font-bold">{pipeline?.name}</span> — {pipeline?.steps.length ?? 0} шагов, v{pipeline?.version}
                    </DialogDescription>
                </DialogHeader>

                <div className="flex-1 overflow-y-auto space-y-4 pr-2">
                    {/* Выбор устройств */}
                    <DeviceSelector value={selectedDeviceIds} onChange={setSelectedDeviceIds} />

                    <div className="space-y-1.5">
                        <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Входные параметры (JSON)</Label>
                        <textarea
                            value={inputParams}
                            onChange={e => setInputParams(e.target.value)}
                            rows={3}
                            className="w-full rounded-sm border border-border bg-black/30 px-3 py-2 text-xs font-mono text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 resize-none"
                            placeholder='{"key": "value"}'
                        />
                    </div>

                    {/* Превью шагов */}
                    <div className="border border-border rounded-sm p-3 bg-muted/30">
                        <div className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground mb-2">Шаги исполнения</div>
                        <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
                            {pipeline?.steps.map((s, i) => (
                                <div key={s.id} className="flex items-center gap-1.5 shrink-0">
                                    <Badge variant="outline" className={`text-[8px] whitespace-nowrap ${STEP_TYPE_COLORS[s.type] || ''}`}>
                                        {s.name}
                                    </Badge>
                                    {i < (pipeline?.steps.length ?? 0) - 1 && <ChevronRight className="w-2.5 h-2.5 text-muted-foreground/40" />}
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

                <DialogFooter className="mt-4">
                    <Button variant="outline" onClick={() => onOpenChange(false)} className="font-mono text-xs">
                        Отмена
                    </Button>
                    <Button
                        onClick={() => runMut.mutate()}
                        disabled={!canSubmit || runMut.isPending}
                        className="font-mono text-xs bg-success hover:bg-success/90 text-success-foreground"
                    >
                        {runMut.isPending && <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" />}
                        <Play className="w-3.5 h-3.5 mr-1.5" /> Запустить ({selectedDeviceIds.length})
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}


// ============================================================================
//  CRON ВИЗУАЛЬНЫЙ БИЛДЕР
// ============================================================================

const CRON_PRESETS = [
    { label: 'Каждые 5 мин', cron: '*/5 * * * *' },
    { label: 'Каждые 15 мин', cron: '*/15 * * * *' },
    { label: 'Каждые 30 мин', cron: '*/30 * * * *' },
    { label: 'Каждый час', cron: '0 * * * *' },
    { label: 'Каждые 2 часа', cron: '0 */2 * * *' },
    { label: 'Каждые 6 часов', cron: '0 */6 * * *' },
    { label: 'Ежедневно 00:00', cron: '0 0 * * *' },
    { label: 'Ежедневно 09:00', cron: '0 9 * * *' },
    { label: 'Пн-Пт 09:00', cron: '0 9 * * 1-5' },
] as const;

function CronBuilder({ value, onChange }: { value: string; onChange: (v: string) => void }) {
    const [mode, setMode] = useState<'preset' | 'custom' | 'manual'>('preset');
    const [selectedMinutes, setSelectedMinutes] = useState<number[]>([]);
    const [selectedHours, setSelectedHours] = useState<number[]>([]);
    const [dayOfWeek, setDayOfWeek] = useState('*');
    const [dayOfMonth, setDayOfMonth] = useState('*');

    const updateCustomCron = useCallback((mins: number[], hrs: number[], dow: string, dom: string) => {
        const minutePart = mins.length === 0 ? '*' : mins.sort((a, b) => a - b).join(',');
        const hourPart = hrs.length === 0 ? '*' : hrs.sort((a, b) => a - b).join(',');
        onChange(`${minutePart} ${hourPart} ${dom} * ${dow}`);
    }, [onChange]);

    const toggleMinute = (m: number) => {
        const next = selectedMinutes.includes(m)
            ? selectedMinutes.filter(x => x !== m)
            : [...selectedMinutes, m];
        setSelectedMinutes(next);
        updateCustomCron(next, selectedHours, dayOfWeek, dayOfMonth);
    };

    const toggleHour = (h: number) => {
        const next = selectedHours.includes(h)
            ? selectedHours.filter(x => x !== h)
            : [...selectedHours, h];
        setSelectedHours(next);
        updateCustomCron(selectedMinutes, next, dayOfWeek, dayOfMonth);
    };

    const MINUTE_OPTIONS = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55];
    const HOUR_OPTIONS = Array.from({ length: 24 }, (_, i) => i);
    const DOW_OPTIONS = [
        { value: '*', label: 'Все' },
        { value: '1-5', label: 'Пн-Пт' },
        { value: '6,0', label: 'Сб-Вс' },
        { value: '1', label: 'Пн' }, { value: '2', label: 'Вт' }, { value: '3', label: 'Ср' },
        { value: '4', label: 'Чт' }, { value: '5', label: 'Пт' }, { value: '6', label: 'Сб' }, { value: '0', label: 'Вс' },
    ];

    return (
        <div className="space-y-3">
            <div className="flex items-center gap-2">
                <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">CRON</Label>
                <div className="flex gap-1 ml-auto">
                    {(['preset', 'custom', 'manual'] as const).map(m => (
                        <Button
                            key={m}
                            variant={mode === m ? 'default' : 'outline'}
                            size="sm"
                            className="h-6 text-[9px] font-mono px-2"
                            onClick={() => setMode(m)}
                        >
                            {m === 'preset' ? 'Пресеты' : m === 'custom' ? 'Конструктор' : 'Ручной'}
                        </Button>
                    ))}
                </div>
            </div>

            {mode === 'preset' && (
                <div className="grid grid-cols-3 gap-1.5">
                    {CRON_PRESETS.map(p => (
                        <Button
                            key={p.cron}
                            variant={value === p.cron ? 'default' : 'outline'}
                            size="sm"
                            className="h-7 text-[10px] font-mono justify-start"
                            onClick={() => onChange(p.cron)}
                        >
                            {p.label}
                        </Button>
                    ))}
                </div>
            )}

            {mode === 'custom' && (
                <div className="space-y-3">
                    <div className="space-y-1">
                        <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">
                            Минуты {selectedMinutes.length > 0 && `(${selectedMinutes.sort((a, b) => a - b).join(', ')})`}
                        </Label>
                        <div className="flex flex-wrap gap-1">
                            {MINUTE_OPTIONS.map(m => (
                                <Button
                                    key={m}
                                    variant={selectedMinutes.includes(m) ? 'default' : 'outline'}
                                    size="sm"
                                    className="h-6 w-10 text-[10px] font-mono p-0"
                                    onClick={() => toggleMinute(m)}
                                >
                                    :{String(m).padStart(2, '0')}
                                </Button>
                            ))}
                        </div>
                    </div>
                    <div className="space-y-1">
                        <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">
                            Часы {selectedHours.length > 0 && `(${selectedHours.sort((a, b) => a - b).join(', ')})`}
                        </Label>
                        <div className="flex flex-wrap gap-1">
                            {HOUR_OPTIONS.map(h => (
                                <Button
                                    key={h}
                                    variant={selectedHours.includes(h) ? 'default' : 'outline'}
                                    size="sm"
                                    className="h-6 w-9 text-[10px] font-mono p-0"
                                    onClick={() => toggleHour(h)}
                                >
                                    {String(h).padStart(2, '0')}
                                </Button>
                            ))}
                        </div>
                    </div>
                    <div className="space-y-1">
                        <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">День недели</Label>
                        <div className="flex flex-wrap gap-1">
                            {DOW_OPTIONS.map(d => (
                                <Button
                                    key={d.value}
                                    variant={dayOfWeek === d.value ? 'default' : 'outline'}
                                    size="sm"
                                    className="h-6 text-[10px] font-mono px-2"
                                    onClick={() => {
                                        setDayOfWeek(d.value);
                                        updateCustomCron(selectedMinutes, selectedHours, d.value, dayOfMonth);
                                    }}
                                >
                                    {d.label}
                                </Button>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {mode === 'manual' && (
                <div className="space-y-1.5">
                    <Input
                        placeholder="5,25,45 * * * * (5, 25 и 45 мин каждого часа)"
                        value={value}
                        onChange={e => onChange(e.target.value)}
                        className="h-9 bg-black/30 border-border font-mono text-xs"
                    />
                    <div className="text-[9px] text-muted-foreground font-mono">
                        Формат: мин час день_мес месяц день_нед · Примеры: <span className="text-primary">5,25,45 * * * *</span> · <span className="text-primary">0 9,18 * * 1-5</span>
                    </div>
                </div>
            )}

            {value && (
                <div className="flex items-center gap-2 p-2 rounded-sm border border-border bg-muted/30">
                    <Clock className="w-3.5 h-3.5 text-primary shrink-0" />
                    <code className="text-[11px] font-mono text-primary font-bold">{value}</code>
                    <span className="text-[9px] text-muted-foreground ml-auto">{describeCron(value)}</span>
                </div>
            )}
        </div>
    );
}

function describeCron(cron: string): string {
    const parts = cron.trim().split(/\s+/);
    if (parts.length !== 5) return 'невалидный cron';
    const [min, hour, , , dow] = parts;

    let desc = '';
    if (min === '*') desc += 'каждую минуту';
    else if (min.startsWith('*/')) desc += `каждые ${min.slice(2)} мин`;
    else if (min.includes(',')) desc += `в ${min} мин`;
    else desc += `в :${min.padStart(2, '0')}`;

    if (hour === '*') desc += ', каждый час';
    else if (hour.startsWith('*/')) desc += `, каждые ${hour.slice(2)} ч`;
    else if (hour.includes(',')) desc += `, в ${hour} ч`;
    else if (hour !== '*') desc += `, в ${hour}:00`;

    if (dow === '1-5') desc += ', Пн-Пт';
    else if (dow === '6,0' || dow === '0,6') desc += ', Сб-Вс';
    else if (dow !== '*') desc += `, дн.нед: ${dow}`;

    return desc;
}


// ============================================================================
//  ДИАЛОГ: РЕДАКТИРОВАНИЕ РАСПИСАНИЯ
// ============================================================================

function EditScheduleDialog({ schedule, open, onOpenChange, pipelines }: {
    schedule: Schedule | null;
    open: boolean;
    onOpenChange: (v: boolean) => void;
    pipelines: Pipeline[];
}) {
    const queryClient = useQueryClient();
    const { data: scriptsData } = useScripts();
    const scripts = scriptsData?.items ?? [];
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [triggerType, setTriggerType] = useState<'cron' | 'interval' | 'one_shot'>('cron');
    const [cronExpression, setCronExpression] = useState('');
    const [intervalSeconds, setIntervalSeconds] = useState(3600);
    const [oneShotAt, setOneShotAt] = useState('');
    const [targetType, setTargetType] = useState<'script' | 'pipeline'>('pipeline');
    const [pipelineId, setPipelineId] = useState('');
    const [scriptId, setScriptId] = useState('');
    const [conflictPolicy, setConflictPolicy] = useState<'skip' | 'queue' | 'cancel'>('skip');
    const [timezone, setTimezone] = useState('UTC');

    // Заполняем форму данными расписания при открытии
    const scheduleId = schedule?.id;

    // Синхронизация состояния формы при смене расписания
    useEffect(() => {
        if (!schedule) return;
        setName(schedule.name);
        setDescription(schedule.description || '');
        setTimezone(schedule.timezone || 'UTC');
        setTargetType(schedule.target_type as 'script' | 'pipeline');
        setPipelineId(schedule.pipeline_id || '');
        setScriptId(schedule.script_id || '');
        setConflictPolicy(schedule.conflict_policy as 'skip' | 'queue' | 'cancel');
        if (schedule.cron_expression) {
            setTriggerType('cron');
            setCronExpression(schedule.cron_expression);
        } else if (schedule.interval_seconds) {
            setTriggerType('interval');
            setIntervalSeconds(schedule.interval_seconds);
        } else {
            setTriggerType('one_shot');
            setOneShotAt(schedule.one_shot_at || '');
        }
    }, [scheduleId]);

    const updateMut = useMutation({
        mutationFn: async () => {
            if (!schedule) return;
            const payload: Record<string, any> = {
                name: name.trim(),
                description: description.trim() || null,
                target_type: targetType,
                conflict_policy: conflictPolicy,
                timezone,
            };
            if (targetType === 'pipeline') { payload.pipeline_id = pipelineId; payload.script_id = null; }
            else { payload.script_id = scriptId; payload.pipeline_id = null; }

            if (triggerType === 'cron') {
                payload.cron_expression = cronExpression.trim();
                payload.interval_seconds = null;
                payload.one_shot_at = null;
            } else if (triggerType === 'interval') {
                payload.interval_seconds = intervalSeconds;
                payload.cron_expression = null;
                payload.one_shot_at = null;
            } else {
                payload.one_shot_at = oneShotAt;
                payload.cron_expression = null;
                payload.interval_seconds = null;
            }

            const { data } = await api.patch(`/schedules/${schedule.id}`, payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['schedules'] });
            toast.success('Расписание обновлено');
            onOpenChange(false);
        },
        onError: (err: any) => {
            const detail = err?.response?.data?.detail;
            toast.error(typeof detail === 'string' ? detail : 'Ошибка обновления расписания');
        },
    });

    const canSubmit = name.trim().length > 0 && (
        (triggerType === 'cron' && cronExpression.trim()) ||
        (triggerType === 'interval' && intervalSeconds > 0) ||
        (triggerType === 'one_shot' && oneShotAt)
    ) && (
        (targetType === 'pipeline' && pipelineId) ||
        (targetType === 'script' && scriptId)
    );

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl bg-card border-border">
                <DialogHeader>
                    <DialogTitle className="font-mono tracking-tight flex items-center gap-2">
                        <Pencil className="w-5 h-5 text-primary" />
                        Редактировать расписание
                    </DialogTitle>
                    <DialogDescription className="text-xs text-muted-foreground font-mono">
                        Измени параметры существующего расписания. Бэкенд пересчитает <code>next_fire_at</code> автоматически.
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-2">
                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Название *</Label>
                            <Input
                                placeholder="Ежечасный health-check"
                                value={name}
                                onChange={e => setName(e.target.value)}
                                className="h-9 bg-black/30 border-border font-mono text-xs"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Timezone</Label>
                            <Input
                                value={timezone}
                                onChange={e => setTimezone(e.target.value)}
                                className="h-9 bg-black/30 border-border font-mono text-xs"
                                placeholder="UTC"
                            />
                        </div>
                    </div>

                    <div className="space-y-1.5">
                        <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Описание</Label>
                        <Input
                            placeholder="Описание расписания..."
                            value={description}
                            onChange={e => setDescription(e.target.value)}
                            className="h-9 bg-black/30 border-border font-mono text-xs"
                        />
                    </div>

                    {/* Тип триггера */}
                    <div className="space-y-1.5">
                        <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Тип триггера</Label>
                        <div className="flex gap-2">
                            {(['cron', 'interval', 'one_shot'] as const).map(t => (
                                <Button
                                    key={t}
                                    variant={triggerType === t ? 'default' : 'outline'}
                                    size="sm"
                                    className="h-7 text-[10px] font-mono"
                                    onClick={() => setTriggerType(t)}
                                >
                                    {t === 'cron' ? 'CRON' : t === 'interval' ? 'INTERVAL' : 'ONE-SHOT'}
                                </Button>
                            ))}
                        </div>
                    </div>

                    {triggerType === 'cron' && (
                        <CronBuilder value={cronExpression} onChange={setCronExpression} />
                    )}
                    {triggerType === 'interval' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Интервал (секунды) *</Label>
                            <Input
                                type="number"
                                value={intervalSeconds}
                                onChange={e => setIntervalSeconds(Number(e.target.value))}
                                className="h-9 bg-black/30 border-border font-mono text-xs"
                                min={10}
                            />
                        </div>
                    )}
                    {triggerType === 'one_shot' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Дата/время запуска (ISO) *</Label>
                            <Input
                                type="datetime-local"
                                value={oneShotAt}
                                onChange={e => setOneShotAt(e.target.value)}
                                className="h-9 bg-black/30 border-border font-mono text-xs"
                            />
                        </div>
                    )}

                    {/* Цель */}
                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Тип цели</Label>
                            <div className="flex gap-2">
                                <Button
                                    variant={targetType === 'pipeline' ? 'default' : 'outline'}
                                    size="sm"
                                    className="h-7 text-[10px] font-mono"
                                    onClick={() => setTargetType('pipeline')}
                                >
                                    Pipeline
                                </Button>
                                <Button
                                    variant={targetType === 'script' ? 'default' : 'outline'}
                                    size="sm"
                                    className="h-7 text-[10px] font-mono"
                                    onClick={() => setTargetType('script')}
                                >
                                    Script
                                </Button>
                            </div>
                        </div>
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Конфликт-политика</Label>
                            <select
                                value={conflictPolicy}
                                onChange={e => setConflictPolicy(e.target.value as any)}
                                className="w-full h-9 rounded-sm border border-border bg-black/30 px-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
                            >
                                <option value="skip">SKIP</option>
                                <option value="queue">QUEUE</option>
                                <option value="cancel">CANCEL PREVIOUS</option>
                            </select>
                        </div>
                    </div>

                    {targetType === 'pipeline' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Pipeline *</Label>
                            <select
                                value={pipelineId}
                                onChange={e => setPipelineId(e.target.value)}
                                className="w-full h-9 rounded-sm border border-border bg-black/30 px-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
                            >
                                <option value="">Выбери pipeline...</option>
                                {pipelines.map(p => (
                                    <option key={p.id} value={p.id}>{p.name} (v{p.version})</option>
                                ))}
                            </select>
                        </div>
                    )}
                    {targetType === 'script' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Скрипт *</Label>
                            <select
                                value={scriptId}
                                onChange={e => setScriptId(e.target.value)}
                                className="w-full h-9 rounded-sm border border-border bg-black/30 px-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
                            >
                                <option value="">Выбери скрипт...</option>
                                {scripts.filter(s => !s.is_archived).map(s => (
                                    <option key={s.id} value={s.id}>
                                        {s.name} ({s.node_count} нод)
                                    </option>
                                ))}
                            </select>
                        </div>
                    )}
                </div>

                <DialogFooter className="mt-4 pt-4 border-t border-border">
                    <Button variant="outline" onClick={() => onOpenChange(false)} className="font-mono text-xs">
                        Отмена
                    </Button>
                    <Button
                        onClick={() => updateMut.mutate()}
                        disabled={!canSubmit || updateMut.isPending}
                        className="font-mono text-xs"
                    >
                        {updateMut.isPending && <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" />}
                        Сохранить изменения
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}


// ============================================================================
//  ДИАЛОГ: СОЗДАНИЕ РАСПИСАНИЯ
// ============================================================================

function CreateScheduleDialog({ open, onOpenChange, pipelines }: { open: boolean; onOpenChange: (v: boolean) => void; pipelines: Pipeline[] }) {
    const queryClient = useQueryClient();
    const { data: scriptsData } = useScripts();
    const scripts = scriptsData?.items ?? [];
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [triggerType, setTriggerType] = useState<'cron' | 'interval' | 'one_shot'>('cron');
    const [cronExpression, setCronExpression] = useState('');
    const [intervalSeconds, setIntervalSeconds] = useState(3600);
    const [oneShotAt, setOneShotAt] = useState('');
    const [targetType, setTargetType] = useState<'script' | 'pipeline'>('pipeline');
    const [pipelineId, setPipelineId] = useState('');
    const [scriptId, setScriptId] = useState('');
    const [conflictPolicy, setConflictPolicy] = useState<'skip' | 'queue' | 'cancel'>('skip');
    const [timezone, setTimezone] = useState('UTC');
    const [targetDeviceIds, setTargetDeviceIds] = useState<string[]>([]);

    const createMut = useMutation({
        mutationFn: async () => {
            const payload: Record<string, any> = {
                name: name.trim(),
                description: description.trim() || null,
                target_type: targetType,
                conflict_policy: conflictPolicy,
                timezone,
                is_active: true,
                device_ids: targetDeviceIds.length > 0 ? targetDeviceIds : undefined,
            };
            if (targetType === 'pipeline') payload.pipeline_id = pipelineId;
            else payload.script_id = scriptId;

            if (triggerType === 'cron') payload.cron_expression = cronExpression.trim();
            else if (triggerType === 'interval') payload.interval_seconds = intervalSeconds;
            else payload.one_shot_at = oneShotAt;

            const { data } = await api.post('/schedules', payload);
            return data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['schedules'] });
            toast.success('Расписание создано');
            onOpenChange(false);
        },
        onError: (err: any) => {
            const detail = err?.response?.data?.detail;
            toast.error(typeof detail === 'string' ? detail : 'Ошибка создания расписания');
        },
    });

    const canSubmit = name.trim().length > 0 && (
        (triggerType === 'cron' && cronExpression.trim()) ||
        (triggerType === 'interval' && intervalSeconds > 0) ||
        (triggerType === 'one_shot' && oneShotAt)
    ) && (
        (targetType === 'pipeline' && pipelineId) ||
        (targetType === 'script' && scriptId)
    );

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl bg-card border-border">
                <DialogHeader>
                    <DialogTitle className="font-mono tracking-tight flex items-center gap-2">
                        <CalendarClock className="w-5 h-5 text-primary" />
                        Создать расписание
                    </DialogTitle>
                    <DialogDescription className="text-xs text-muted-foreground font-mono">
                        Настрой автоматический запуск скрипта или pipeline по CRON, интервалу или одноразово.
                    </DialogDescription>
                </DialogHeader>

                <div className="space-y-4 max-h-[60vh] overflow-y-auto pr-2">
                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Название *</Label>
                            <Input
                                placeholder="Ежечасный health-check"
                                value={name}
                                onChange={e => setName(e.target.value)}
                                className="h-9 bg-black/30 border-border font-mono text-xs"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Timezone</Label>
                            <Input
                                value={timezone}
                                onChange={e => setTimezone(e.target.value)}
                                className="h-9 bg-black/30 border-border font-mono text-xs"
                                placeholder="UTC"
                            />
                        </div>
                    </div>

                    <div className="space-y-1.5">
                        <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Описание</Label>
                        <Input
                            placeholder="Описание расписания..."
                            value={description}
                            onChange={e => setDescription(e.target.value)}
                            className="h-9 bg-black/30 border-border font-mono text-xs"
                        />
                    </div>

                    {/* Тип триггера */}
                    <div className="space-y-1.5">
                        <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Тип триггера</Label>
                        <div className="flex gap-2">
                            {(['cron', 'interval', 'one_shot'] as const).map(t => (
                                <Button
                                    key={t}
                                    variant={triggerType === t ? 'default' : 'outline'}
                                    size="sm"
                                    className="h-7 text-[10px] font-mono"
                                    onClick={() => setTriggerType(t)}
                                >
                                    {t === 'cron' ? 'CRON' : t === 'interval' ? 'INTERVAL' : 'ONE-SHOT'}
                                </Button>
                            ))}
                        </div>
                    </div>

                    {triggerType === 'cron' && (
                        <CronBuilder value={cronExpression} onChange={setCronExpression} />
                    )}
                    {triggerType === 'interval' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Интервал (секунды) *</Label>
                            <Input
                                type="number"
                                value={intervalSeconds}
                                onChange={e => setIntervalSeconds(Number(e.target.value))}
                                className="h-9 bg-black/30 border-border font-mono text-xs"
                                min={10}
                            />
                        </div>
                    )}
                    {triggerType === 'one_shot' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Дата/время запуска (ISO) *</Label>
                            <Input
                                type="datetime-local"
                                value={oneShotAt}
                                onChange={e => setOneShotAt(e.target.value)}
                                className="h-9 bg-black/30 border-border font-mono text-xs"
                            />
                        </div>
                    )}

                    {/* Цель */}
                    <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Тип цели</Label>
                            <div className="flex gap-2">
                                <Button
                                    variant={targetType === 'pipeline' ? 'default' : 'outline'}
                                    size="sm"
                                    className="h-7 text-[10px] font-mono"
                                    onClick={() => setTargetType('pipeline')}
                                >
                                    Pipeline
                                </Button>
                                <Button
                                    variant={targetType === 'script' ? 'default' : 'outline'}
                                    size="sm"
                                    className="h-7 text-[10px] font-mono"
                                    onClick={() => setTargetType('script')}
                                >
                                    Script
                                </Button>
                            </div>
                        </div>
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Конфликт-политика</Label>
                            <select
                                value={conflictPolicy}
                                onChange={e => setConflictPolicy(e.target.value as any)}
                                className="w-full h-9 rounded-sm border border-border bg-black/30 px-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
                            >
                                <option value="skip">SKIP</option>
                                <option value="queue">QUEUE</option>
                                <option value="cancel">CANCEL PREVIOUS</option>
                            </select>
                        </div>
                    </div>

                    {targetType === 'pipeline' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Pipeline *</Label>
                            <select
                                value={pipelineId}
                                onChange={e => setPipelineId(e.target.value)}
                                className="w-full h-9 rounded-sm border border-border bg-black/30 px-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
                            >
                                <option value="">Выбери pipeline...</option>
                                {pipelines.map(p => (
                                    <option key={p.id} value={p.id}>{p.name} (v{p.version})</option>
                                ))}
                            </select>
                        </div>
                    )}
                    {targetType === 'script' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Скрипт *</Label>
                            <select
                                value={scriptId}
                                onChange={e => setScriptId(e.target.value)}
                                className="w-full h-9 rounded-sm border border-border bg-black/30 px-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
                            >
                                <option value="">Выбери скрипт...</option>
                                {scripts.filter(s => !s.is_archived).map(s => (
                                    <option key={s.id} value={s.id}>
                                        {s.name} ({s.node_count} нод)
                                    </option>
                                ))}
                            </select>
                        </div>
                    )}

                    {/* Целевые устройства */}
                    <div className="space-y-1.5">
                        <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Целевые устройства</Label>
                        <DeviceSelector value={targetDeviceIds} onChange={setTargetDeviceIds} />
                    </div>
                </div>

                <DialogFooter className="mt-4 pt-4 border-t border-border">
                    <Button variant="outline" onClick={() => onOpenChange(false)} className="font-mono text-xs">
                        Отмена
                    </Button>
                    <Button
                        onClick={() => createMut.mutate()}
                        disabled={!canSubmit || createMut.isPending}
                        className="font-mono text-xs"
                    >
                        {createMut.isPending && <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" />}
                        Создать расписание
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
