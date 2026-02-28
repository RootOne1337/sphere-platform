'use client';

import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { toast } from 'sonner';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';
import { Badge } from '@/src/shared/ui/badge';
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
} from 'lucide-react';

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
                        <Button variant="default" size="sm" className="h-9">
                            <Plus className="w-4 h-4 mr-2" /> Новый Pipeline
                        </Button>
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
                {tab === 'pipelines' && <PipelinesTab pipelines={pipelines} loading={pLoading} search={search} />}
                {tab === 'runs' && <RunsTab runs={runs} pipelines={pipelines} loading={rLoading} search={search} />}
                {tab === 'schedules' && <SchedulesTab schedules={schedules} loading={sLoading} search={search} />}
            </div>
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

function PipelinesTab({ pipelines, loading, search }: { pipelines: Pipeline[]; loading: boolean; search: string }) {
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
                        />
                    ))}
                </tbody>
            </table>
        </div>
    );
}

function PipelineRow({ pipeline: p, expanded, onToggle }: { pipeline: Pipeline; expanded: boolean; onToggle: () => void }) {
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
                        <Button variant="ghost" size="tiny" className="text-muted-foreground hover:text-success hover:bg-success/10" title="Запустить">
                            <Play className="w-3 h-3" />
                        </Button>
                        <Button variant="ghost" size="tiny" className="text-muted-foreground hover:text-primary hover:bg-primary/10" title="Просмотр">
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

function SchedulesTab({ schedules, loading, search }: { schedules: Schedule[]; loading: boolean; search: string }) {
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
                                        <Button variant="ghost" size="tiny" className="text-muted-foreground hover:text-primary hover:bg-primary/10" title="Подробности">
                                            <Eye className="w-3 h-3" />
                                        </Button>
                                    </div>
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}
