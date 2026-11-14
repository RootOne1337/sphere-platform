'use client';

import { Suspense, useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { getApiErrorMessage } from '@/lib/apiError';
import { PipelineDefinitionDialog } from '@/src/features/orchestration/PipelineDefinitionDialog';
import { toast } from 'sonner';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';
import { Badge } from '@/src/shared/ui/badge';
import { Label } from '@/components/ui/label';
import {
    Dialog,
    DialogContent,
    DialogBody,
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
import { ScheduleExecutionHistoryDialog } from '@/components/orchestration/ScheduleExecutionHistoryDialog';
import { PipelineCatalogPicker } from '@/components/orchestration/PipelineCatalogPicker';
import { PipelineResumeControl } from '@/components/orchestration/PipelineResumeControl';
import { ScriptCatalogPicker } from '@/components/orchestration/ScriptCatalogPicker';
import { isoToUtcDateTimeInput, utcDateTimeInputToIso, isValidUtcDateTimeInput, formatScheduleUtc, formatScheduleLocal, scheduleRevision } from '@/src/features/orchestration/scheduleTime';
import { useCatalogPage, CATALOG_PER_PAGE } from '@/src/features/orchestration/useCatalogPage';
import { CatalogPagination } from '@/src/shared/ui/catalog-pagination';

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
    pipeline_version?: number | null;
    current_step_id: string | null;
    execution_phase?: string;
    execution_lease_until?: string | null;
    cancel_requested_at?: string | null;
    context: Record<string, any>;
    input_params: Record<string, any>;
    step_logs: Array<{
        step_id: string;
        type?: string;
        status?: string;
        event?: string;
        reason?: string;
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
    device_ids: string[] | null;
    group_id: string | null;
    device_tags: string[] | null;
    total_runs: number;
    next_fire_at: string | null;
    last_fired_at: string | null;
    created_at: string;
    updated_at: string;
    active_until?: string | null;
    max_runs?: number | null;
}

const EMPTY_PIPELINES: Pipeline[] = [];
const EMPTY_RUNS: PipelineRun[] = [];
const EMPTY_SCHEDULES: Schedule[] = [];

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
    const cfg = STATUS_CONFIG[(status || '').toLowerCase()] ?? STATUS_CONFIG.queued;
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
    return <Suspense fallback={<p role="status" className="p-6 text-sm text-muted-foreground">Загрузка оркестрации…</p>}><ScopedOrchestrationPage /></Suspense>;
}

function ScopedOrchestrationPage() {
    const params = useSearchParams();
    const runId = params?.get('run_id') || undefined;
    const batchId = params?.get('batch_id') || undefined;
    const receiptKey = `${runId ?? ''}:${batchId ?? ''}`;
    return <OrchestrationContent key={receiptKey} runId={runId} batchId={batchId} />;
}

function OrchestrationContent({ runId, batchId }: { runId?: string; batchId?: string }) {
    const receipt = runId ?? batchId;
    const [tab, setTab] = useState<TabKey>(receipt ? 'runs' : 'pipelines');
    const [search, setSearch] = useState('');
    const [launchTarget, setLaunchTarget] = useState<{ pipeline: Pipeline; scope: string } | null>(null);
    const actor = useAuthStore(s => s.user);
    const session = useAuthStore(s => s.sessionVersion);
    const definitionScope = `${actor?.org_id}:${actor?.id}:${actor?.role}:${session}`;
    const runPipelineTarget = launchTarget?.scope === definitionScope ? launchTarget.pipeline : null;
    const canManageDefinition = Boolean(actor && ['device_manager', 'org_admin', 'org_owner', 'super_admin'].includes(actor.role));
    const [definition, setDefinition] = useState<{ id: string; scope: string; action: 'view' | 'activation' } | null>(null);
    const [showCreateSchedule, setShowCreateSchedule] = useState(false);
    const [editingSchedule, setEditingSchedule] = useState<Schedule | null>(null);
    const [pages, setPages] = useState<Record<TabKey, number>>({ pipelines: 1, runs: 1, schedules: 1 });
    const [filters, setFilters] = useState<Record<TabKey, string>>({ pipelines: 'all', runs: 'all', schedules: 'all' });
    const pipelineFilter = filters.pipelines === 'all' ? {} : { is_active: filters.pipelines === 'active' };
    const scheduleFilter = filters.schedules === 'all' ? {} : { is_active: filters.schedules === 'active' };
    const runFilter = { ...(filters.runs === 'all' ? {} : filters.runs === 'active' ? { active_only: true } : { status: filters.runs }),
        ...(runId ? { run_id: runId } : {}), ...(batchId ? { batch_id: batchId } : {}) };
    const pipelinesQuery = useCatalogPage<Pipeline>('pipelines', pages.pipelines, pipelineFilter, { polling: tab === 'pipelines' });
    const runsQuery = useCatalogPage<PipelineRun>('pipeline-runs', pages.runs, runFilter, { polling: tab === 'runs' });
    const schedulesQuery = useCatalogPage<Schedule>('schedules', pages.schedules, scheduleFilter, { polling: tab === 'schedules' });
    const pipelines = pipelinesQuery.isSuccess ? pipelinesQuery.data.items : EMPTY_PIPELINES;
    const runs = runsQuery.isSuccess ? runsQuery.data.items : EMPTY_RUNS;
    const schedules = schedulesQuery.isSuccess ? schedulesQuery.data.items : EMPTY_SCHEDULES;
    const pLoading = pipelinesQuery.isLoading;
    const rLoading = runsQuery.isLoading;
    const sLoading = schedulesQuery.isLoading;
    const currentQuery = tab === 'pipelines' ? pipelinesQuery : tab === 'runs' ? runsQuery : schedulesQuery;
    const currentLabel = tab === 'pipelines' ? 'конвейеры' : tab === 'runs' ? 'запуски конвейеров' : 'расписания';
    const currentData = currentQuery.isSuccess ? currentQuery.data : undefined;
    const changingPage = !!currentData && pages[tab] > Math.max(1, currentData.pages);

    useEffect(() => {
        if (currentData && changingPage) setPages(previous => ({ ...previous, [tab]: Math.max(1, currentData.pages) }));
    }, [tab, currentData, changingPage]);

    function changeTab(next: TabKey) { setSearch(''); setTab(next); }
    function changeFilter(value: string) {
        setSearch('');
        setPages(previous => ({ ...previous, [tab]: 1 }));
        setFilters(previous => ({ ...previous, [tab]: value }));
    }

    // Статистика (вычисляемая)
    const stats = useMemo(() => {
        const activeRuns = runs.filter(r => ['running', 'waiting', 'queued', 'paused'].includes(r.status.toLowerCase()));
        const completedRuns = runs.filter(r => r.status.toLowerCase() === 'completed');
        const failedRuns = runs.filter(r => ['failed', 'timed_out'].includes(r.status.toLowerCase()));
        const activeSchedules = schedules.filter(s => s.is_active);
        return {
            totalPipelines: pipelinesQuery.isSuccess ? pipelinesQuery.data.total : '—',
            activeRuns: runsQuery.isSuccess ? activeRuns.length : '—',
            completedRuns: runsQuery.isSuccess ? completedRuns.length : '—',
            failedRuns: runsQuery.isSuccess ? failedRuns.length : '—',
            totalSchedules: schedulesQuery.isSuccess ? schedulesQuery.data.total : '—',
            activeSchedules: schedulesQuery.isSuccess ? activeSchedules.length : '—',
            successRate: !runsQuery.isSuccess ? '—' : runs.length > 0
                ? ((completedRuns.length / runs.length) * 100).toFixed(1)
                : '—',
        };
    }, [runs, schedules, pipelinesQuery.data, schedulesQuery.data, pipelinesQuery.isSuccess, runsQuery.isSuccess, schedulesQuery.isSuccess]);

    const TABS: { key: TabKey; label: string; count: number | string }[] = [
        { key: 'pipelines', label: 'Pipelines', count: pipelinesQuery.isSuccess ? pipelinesQuery.data.total : '—' },
        { key: 'runs', label: 'Pipeline Runs', count: runsQuery.isSuccess ? runsQuery.data.total : '—' },
        { key: 'schedules', label: 'Schedules', count: schedulesQuery.isSuccess ? schedulesQuery.data.total : '—' },
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
                                aria-label="Поиск на текущей странице"
                                placeholder="Поиск на этой странице…"
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
                    <StatCard label="Pipelines в каталоге" value={stats.totalPipelines} icon={<Layers className="w-7 h-7 text-primary/30" strokeWidth={1} />} />
                    <StatCard label={`Активная очередь · страница ${pages.runs}`} value={stats.activeRuns} icon={<Activity className="w-7 h-7 text-primary/30" strokeWidth={1} />} accent />
                    <StatCard label={`Завершены · страница ${pages.runs}`} value={stats.completedRuns} icon={<CheckCircle2 className="w-7 h-7 text-success/30" strokeWidth={1} />} />
                    <StatCard label={`Ошибки · страница ${pages.runs}`} value={stats.failedRuns} icon={<ShieldAlert className="w-7 h-7 text-destructive/30" strokeWidth={1} />} destructive />
                    <StatCard label={`Доля завершённых · страница ${pages.runs}`} value={stats.successRate === '—' ? '—' : `${stats.successRate}%`} icon={<Zap className="w-7 h-7 text-success/30" strokeWidth={1} />} />
                    <StatCard label="Расписания в каталоге" value={stats.totalSchedules} icon={<CalendarClock className="w-7 h-7 text-primary/30" strokeWidth={1} />} />
                </div>
                <p className="mb-4 text-xs text-muted-foreground">Счётчики запусков и активных расписаний относятся к загруженным страницам с серверным фильтром: запуски — страница {pages.runs}, расписания — страница {pages.schedules} ({stats.activeSchedules} активных). Общие количества во вкладках — итог API с выбранным серверным фильтром.</p>
            </div>

            {(pipelinesQuery.isError || runsQuery.isError || schedulesQuery.isError) && (
                <div className="space-y-2 px-6 pt-3">
                    <QueryFailureNotice source="Конвейеры" query={pipelinesQuery} onRetry={() => pipelinesQuery.refetch()} />
                    <QueryFailureNotice source="Запуски" query={runsQuery} onRetry={() => runsQuery.refetch()} />
                    <QueryFailureNotice source="Расписания" query={schedulesQuery} onRetry={() => schedulesQuery.refetch()} />
                </div>
            )}

            {/* ── TABS ───────────────────────────────────────────────────────── */}
            <div className="px-6 border-b border-border shrink-0">
                <div className="flex gap-1">
                    {TABS.map(t => (
                        <button
                            key={t.key}
                            onClick={() => changeTab(t.key)}
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
                {tab === 'runs' && receipt && <div className="mb-3 flex flex-wrap items-center gap-3 text-sm"><span>{runId ? 'Запуск' : 'Пакет'} <code className="break-all">{receipt}</code></span><Link className="text-primary underline" href="/orchestration">Сбросить выборку</Link></div>}
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                    <label className="text-xs text-muted-foreground">Серверный фильтр
                        <select aria-label={tab === 'runs' ? 'Серверный фильтр запусков' : tab === 'pipelines' ? 'Серверный фильтр конвейеров' : 'Серверный фильтр расписаний'} value={filters[tab]} onChange={e => changeFilter(e.target.value)} className="ml-2 rounded-md border border-border bg-card p-2 text-sm text-foreground">
                            <option value="all">Все</option>
                            <option value="active">{tab === 'runs' ? 'Активная очередь' : 'Активные'}</option>
                            {tab !== 'runs' ? <option value="inactive">Неактивные</option> : ['queued', 'running', 'waiting', 'paused', 'completed', 'failed', 'cancelled', 'timed_out'].map(status => <option key={status} value={status}>{STATUS_CONFIG[status].label}</option>)}
                        </select>
                    </label>
                    <Button variant="outline" size="sm" aria-label="Обновить текущий каталог" disabled={currentQuery.isFetching} onClick={() => { void currentQuery.refetch(); }}>{currentQuery.isFetching ? 'Обновляем…' : 'Обновить каталог'}</Button>
                </div>
                <p className="mb-3 text-xs text-muted-foreground">Текстовый поиск применяется только к текущей странице. Для других записей используйте страницы и серверный фильтр.</p>
                {!changingPage && tab === 'pipelines' && <PipelinesTab pipelines={pipelines} loading={pLoading} error={pipelinesQuery.isError} hasSnapshot={pipelinesQuery.isSuccess} filteredByServer={filters.pipelines !== 'all'} search={search} onRunPipeline={pipeline => setLaunchTarget({ pipeline, scope: definitionScope })} canManage={canManageDefinition} onDefinition={(p, action) => { if (actor) setDefinition({ id: p.id, scope: definitionScope, action }); }} />}
                {!changingPage && tab === 'runs' && <RunsTab runs={runs} pipelines={pipelines} loading={rLoading} error={runsQuery.isError} hasSnapshot={runsQuery.isSuccess} filteredByServer={filters.runs !== 'all'} search={search} />}
                {!changingPage && tab === 'schedules' && <SchedulesTab key={definitionScope} requestScope={`${actor?.org_id}:${actor?.id}`} schedules={schedules} loading={sLoading} error={schedulesQuery.isError} hasSnapshot={schedulesQuery.isSuccess} filteredByServer={filters.schedules !== 'all'} search={search} onCreateSchedule={() => setShowCreateSchedule(true)} onEditSchedule={setEditingSchedule} />}
                {changingPage && <p role="status">Каталог изменился; загружаем доступную страницу…</p>}
                {currentData && !changingPage && <div className="mt-4"><CatalogPagination page={pages[tab]} perPage={CATALOG_PER_PAGE} total={currentData.total} busy={currentQuery.isFetching} label={currentLabel} onPageChange={page => setPages(previous => ({ ...previous, [tab]: page }))} /></div>}
            </div>

            {/* ── МОДАЛКИ (controlled mode — Dialog всегда в DOM, Portal рендерится по open) ── */}
            {actor && definition?.scope === definitionScope && <PipelineDefinitionDialog key={`${definitionScope}:${definition.id}`} pipelineId={definition.id} orgId={actor.org_id} scope={definitionScope} canManage={canManageDefinition} initialAction={definition.action} onClose={() => setDefinition(null)} />}
            <RunPipelineDialog
                key={`${definitionScope}:${runPipelineTarget?.id ?? ''}`}
                pipeline={runPipelineTarget}
                open={!!runPipelineTarget}
                onOpenChange={(v) => { if (!v) setLaunchTarget(null); }}
            />
            <CreateScheduleDialog
                open={showCreateSchedule}
                onOpenChange={setShowCreateSchedule}
            />
            <EditScheduleDialog
                schedule={editingSchedule}
                open={!!editingSchedule}
                onOpenChange={(v) => { if (!v) setEditingSchedule(null); }}
            />
        </div>
    );
}

function QueryFailureNotice({ source, query, onRetry }: {
    source: string;
    query: { isError: boolean; isFetching: boolean; data: unknown };
    onRetry: () => Promise<unknown>;
}) {
    if (!query.isError) return null;
    const hasCachedData = query.data !== undefined;
    return (
        <div role="alert" className="flex flex-col gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
            <div>
                <p className="font-semibold text-destructive">Не удалось обновить {source}.</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                    {hasCachedData ? 'Предыдущие данные скрыты: состояние каталога и доступность действий не подтверждены.' : 'Данные не получены; пустой список не подтверждён.'}
                </p>
            </div>
            <Button type="button" variant="outline" size="sm" aria-label={`Повторить загрузку: ${source}`} onClick={() => { void onRetry(); }} disabled={query.isFetching}>
                {query.isFetching ? 'Повторяем…' : 'Повторить загрузку'}
            </Button>
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

function PipelinesTab({ pipelines, loading, error, hasSnapshot, filteredByServer, search, onRunPipeline, canManage, onDefinition }: { pipelines: Pipeline[]; loading: boolean; error: boolean; hasSnapshot: boolean; filteredByServer: boolean; search: string; onRunPipeline: (p: Pipeline) => void; canManage: boolean; onDefinition: (p: Pipeline, action: 'view' | 'activation') => void }) {
    const [expandedId, setExpandedId] = useState<string | null>(null);

    const filtered = useMemo(() => {
        if (!search) return pipelines;
        const q = search.toLowerCase();
        return pipelines.filter(p =>
            (p.name || '').toLowerCase().includes(q) ||
            p.description?.toLowerCase().includes(q) ||
            (p.tags || []).some(t => (t || '').toLowerCase().includes(q))
        );
    }, [pipelines, search]);

    return (
        <div className="rounded-lg border border-border bg-card overflow-x-auto">
            <table className="w-full text-left whitespace-nowrap">
                <thead className="bg-muted/90 border-b border-border text-[10px] uppercase font-mono tracking-widest font-bold text-muted-foreground sticky top-0 backdrop-blur-sm z-10">
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
                            {error && !hasSnapshot ? 'Список pipelines не загружен; пустой каталог не подтверждён.' : filteredByServer && pipelines.length === 0 ? 'По этому серверному фильтру конвейеров нет.' : pipelines.length === 0 ? 'Нет pipelines. Создайте первый!' : 'На этой странице совпадений нет.'}
                        </td></tr>
                    )}
                    {filtered.map(p => (
                        <PipelineRow
                            key={p.id}
                            pipeline={p}
                            expanded={expandedId === p.id}
                            onToggle={() => setExpandedId(expandedId === p.id ? null : p.id)}
                            onRunPipeline={() => onRunPipeline(p)}
                            canManage={canManage}
                            onDefinition={action => onDefinition(p, action)}
                        />
                    ))}
                </tbody>
            </table>
        </div>
    );
}

function PipelineRow({ pipeline: p, expanded, onToggle, onRunPipeline, canManage, onDefinition }: { pipeline: Pipeline; expanded: boolean; onToggle: () => void; onRunPipeline: () => void; canManage: boolean; onDefinition: (action: 'view' | 'activation') => void }) {

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
                        <Button
                            variant="ghost"
                            size="tiny"
                            className={p.is_active
                                ? 'text-success hover:text-warning hover:bg-warning/10'
                                : 'text-muted-foreground hover:text-success hover:bg-success/10'
                            }
                            title={p.is_active ? 'Деактивировать' : 'Активировать'}
                            aria-label={p.is_active ? 'Деактивировать' : 'Активировать'}
                            onClick={() => onDefinition('activation')}
                            disabled={!canManage}
                        >
                            {p.is_active
                                ? <ToggleRight className="w-4 h-4" />
                                : <ToggleLeft className="w-4 h-4" />
                            }
                        </Button>
                        <Button variant="ghost" size="tiny" className="text-muted-foreground hover:text-success hover:bg-success/10" title="Запустить" onClick={onRunPipeline}>
                            <Play className="w-3 h-3" />
                        </Button>
                        <Button variant="ghost" size="tiny" className="text-muted-foreground hover:text-primary hover:bg-primary/10" title="Определение и управление" aria-label="Определение и управление" onClick={() => onDefinition('view')}>
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
    runs, pipelines, loading, error, hasSnapshot, filteredByServer, search
}: {
    runs: PipelineRun[]; pipelines: Pipeline[]; loading: boolean; error: boolean; hasSnapshot: boolean; filteredByServer: boolean; search: string
}) {
    const queryClient = useQueryClient();
    const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
    const pipelineMap = useMemo(() => new Map(pipelines.map(p => [p.id, p])), [pipelines]);

    // Мутации управления
    const cancelMut = useMutation({
        mutationFn: (runId: string) => api.post(`/pipelines/runs/${runId}/cancel`),
        onSuccess: ({ data }) => {
            queryClient.invalidateQueries({ queryKey: ['pipeline-runs'] });
            toast.success(data.status === 'cancelled' ? 'Run отменён' : 'Отмена запрошена; ожидаем завершение дочерней работы');
        },
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
            r.pipeline_id.toLowerCase().includes(q) || r.device_id.toLowerCase().includes(q) ||
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
                        <tr><td colSpan={8} className="px-4 py-12 text-center text-muted-foreground">{error && !hasSnapshot ? 'Список запусков не загружен; пустой результат не подтверждён.' : search ? 'На этой странице совпадений нет.' : filteredByServer ? 'По этому серверному фильтру запусков нет.' : 'Нет запусков pipeline'}</td></tr>
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
                                resumePending={resumeMut.isPending}
                            />
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}

function RunRow({
    run, pipelineName, expanded, onToggle, isActive, isPaused, onCancel, onPause, onResume, resumePending
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
    resumePending: boolean;
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
                        {pipelineName || run.pipeline_id}
                    </div>
                    <div className="text-[10px] text-[#555] mt-0.5">{run.id.slice(0, 12)}...</div>
                    {run.pipeline_version != null && <span className="text-[10px] text-muted-foreground">Версия {run.pipeline_version}</span>}
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
                            <>
                                <PipelineResumeControl run={run} onResume={onResume} pending={resumePending} />
                                <Button variant="ghost" size="tiny" disabled={!!run.cancel_requested_at}
                                    onClick={onCancel} title="Отменить pipeline">
                                    <XCircle className="w-3 h-3" />
                                </Button>
                            </>
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
                                        {log.event
                                            ? <Badge variant="outline">{log.event}</Badge>
                                            : <StatusBadge status={log.status === 'success' ? 'completed' : ['failed', 'failure'].includes(log.status || '') ? 'failed' : 'running'} />}
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
                                        {log.reason && <span className="text-warning text-[10px]" title={log.reason}>{log.reason}</span>}
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

const SCHEDULE_REQUEST_MAX_AGE = 24 * 60 * 60 * 1000;
const SCHEDULE_STALE = 'schedule_revision_conflict';
const SCHEDULE_CONFLICT_TEXT = 'Расписание изменилось. Сверьте обновлённые данные перед повтором.';
const SCHEDULE_CRON_POLICY = 'CRON использует местное время выбранной зоны. Весной отсутствующий час пропускается, осенью повторяющееся время выполняется один раз в первое вхождение.';
type PendingScheduleFire = { key: string; created: number; revision?: string };

function scheduleConflict(error: unknown) {
    return getApiErrorMessage(error, '') === SCHEDULE_STALE;
}

function ScheduleNextFire({ schedule }: { schedule: Schedule }) {
    const { is_active, next_fire_at, cron_expression, timezone, max_runs, total_runs, active_until } = schedule;
    if (next_fire_at && is_active) {
        const local = cron_expression ? formatScheduleLocal(next_fire_at, timezone) : null;
        return <div>
            <time className="font-semibold text-foreground" dateTime={next_fire_at}>{formatScheduleUtc(next_fire_at)}</time>
            {local && <p className="mt-1 text-[10px] text-muted-foreground">{local} · {timezone}</p>}
        </div>;
    }
    const reason = max_runs != null && total_runs >= max_runs ? 'Лимит запусков исчерпан'
        : active_until && Date.parse(active_until) < Date.now() ? 'Окно активности завершилось'
            : !is_active ? 'Отключено' : 'Время не назначено';
    return <span className="text-muted-foreground">{reason}</span>;
}

function scheduleRequestId() {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
    return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
}

function SchedulesTab({ requestScope, schedules, loading, error, hasSnapshot, filteredByServer, search, onCreateSchedule, onEditSchedule }: { requestScope: string; schedules: Schedule[]; loading: boolean; error: boolean; hasSnapshot: boolean; filteredByServer: boolean; search: string; onCreateSchedule: () => void; onEditSchedule: (s: Schedule) => void }) {
    const queryClient = useQueryClient();
    const [historySchedule, setHistorySchedule] = useState<Schedule | null>(null);
    const [notice, setNotice] = useState<{ id: string; error?: boolean; text: string } | null>(null);
    const changeLock = useRef(false);
    const fireRequests = useRef(new Map<string, PendingScheduleFire>());
    const storageKey = (id: string) => `sphere:schedule-fire:${requestScope}:${id}`;
    function pendingFire(id: string): PendingScheduleFire | undefined {
        const cached = fireRequests.current.get(id);
        if (cached) return cached;
        try {
            const stored = JSON.parse(sessionStorage.getItem(storageKey(id)) ?? 'null') as PendingScheduleFire | null;
            if (stored && /^[0-9a-f-]{36}$/.test(stored.key) && Number.isFinite(stored.created)
                && (stored.revision === undefined || scheduleRevision(stored.revision))) return stored;
        } catch { /* The in-memory copy remains available when storage is disabled. */ }
        return undefined;
    }
    function rememberFire(id: string, request: PendingScheduleFire) {
        fireRequests.current.set(id, request);
        try {
            sessionStorage.setItem(storageKey(id), JSON.stringify(request));
        } catch { /* The in-memory copy remains available when storage is disabled. */ }
    }
    function clearFire(id: string, expectedKey: string) {
        if (fireRequests.current.get(id)?.key === expectedKey) fireRequests.current.delete(id);
        try {
            const key = storageKey(id);
            const stored = JSON.parse(sessionStorage.getItem(key) ?? 'null') as PendingScheduleFire | null;
            if (stored?.key === expectedKey) sessionStorage.removeItem(key);
        } catch { /* The in-memory copy remains available when storage is disabled. */ }
    }
    const changeSchedule = useMutation({
        mutationFn: async ({ schedule, action, request }: { schedule: Schedule; action: 'toggle' | 'fire' | 'delete'; request?: PendingScheduleFire }) => {
            const { id, is_active } = schedule;
            const revision = scheduleRevision(schedule.updated_at);
            if (action === 'delete') return api.delete(`/schedules/${id}`, { params: { expected_updated_at: revision } });
            if (action === 'fire') {
                if (!request) throw new Error('Отсутствует ключ ручного запроса');
                const response = await api.post(`/schedules/${id}/fire-now`, undefined, {
                    headers: { 'Idempotency-Key': request.key },
                    ...(request.revision ? { params: { expected_updated_at: request.revision } } : {}),
                });
                if (response.data?.id !== id || !Number.isFinite(Date.parse(response.data?.requested_fire_at))
                    || typeof response.data?.request_replayed !== 'boolean') {
                    throw new Error('Квитанция запуска не подтверждена. Повтор использует тот же идентификатор.');
                }
                return response;
            }
            const response = await api.post(`/schedules/${id}/toggle`, undefined, {
                params: { active: !is_active, expected_updated_at: revision },
            });
            if (response.data?.id !== id || response.data?.is_active !== !is_active) {
                throw new Error('Состояние расписания не подтверждено');
            }
            return response;
        },
        onSuccess: async (_response, { schedule, action, request }) => {
            if (action === 'fire' && request) clearFire(schedule.id, request.key);
            const text = action === 'fire' ? 'Запрос принят планировщиком. Откройте историю срабатываний для проверки результата.'
                : action === 'toggle' ? 'Настройка сохранена.' : 'Расписание выключено. История сохранена.';
            setNotice({ id: schedule.id, text });
            await Promise.all([
                queryClient.invalidateQueries({ queryKey: ['schedules'] }),
                queryClient.invalidateQueries({ queryKey: ['schedule-executions', schedule.id] }),
            ]);
        },
        onError: async (failure, { schedule, request }) => {
            const stale = scheduleConflict(failure);
            if (stale && request) clearFire(schedule.id, request.key);
            setNotice({
                id: schedule.id, error: true,
                text: stale ? SCHEDULE_CONFLICT_TEXT
                    : getApiErrorMessage(failure, 'Результат команды не подтверждён. Проверьте расписание и историю срабатываний.'),
            });
            if (stale) await queryClient.invalidateQueries({ queryKey: ['schedules'] });
        },
        onSettled: () => { changeLock.current = false; },
    });

    function change(schedule: Schedule, action: 'toggle' | 'fire' | 'delete') {
        if (changeLock.current || error) return;
        let request = action === 'fire' ? pendingFire(schedule.id) : undefined;
        const revision = scheduleRevision(schedule.updated_at);
        if (!request && !revision) {
            setNotice({ id: schedule.id, error: true, text: 'Версия расписания не подтверждена. Обновите список.' });
            void queryClient.invalidateQueries({ queryKey: ['schedules'] });
            return;
        }
        if (action === 'fire') {
            if (!schedule.is_active && !request) return;
            if (request && Date.now() - request.created >= SCHEDULE_REQUEST_MAX_AGE) {
                clearFire(schedule.id, request.key);
                setNotice({ id: schedule.id, error: true, text: 'Срок повтора истёк. Сверьте историю перед новым запросом.' });
                return;
            }
            request ??= { key: scheduleRequestId(), created: Date.now(), revision };
            rememberFire(schedule.id, request);
        }
        changeLock.current = true;
        setNotice(null);
        changeSchedule.mutate({ schedule, action, request });
    }

    const filtered = useMemo(() => {
        if (!search) return schedules;
        const q = search.toLowerCase();
        return schedules.filter(s =>
            (s.name || '').toLowerCase().includes(q) ||
            s.cron_expression?.toLowerCase().includes(q) ||
            (s.target_type || '').toLowerCase().includes(q)
        );
    }, [schedules, search]);

    return (
        <div className="space-y-4">
            {notice && !schedules.some(schedule => schedule.id === notice.id) &&
                <p role={notice.error ? 'alert' : 'status'} className="text-sm">{notice.text}</p>}
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
                            {error && !hasSnapshot ? 'Список расписаний не загружен; пустой каталог не подтверждён.' : filteredByServer && schedules.length === 0 ? 'По этому серверному фильтру расписаний нет.' : schedules.length === 0 ? 'Нет расписаний. Создайте первое!' : 'На этой странице совпадений нет.'}
                        </td></tr>
                    )}
                    {filtered.map(s => {
                        const triggerInfo = s.cron_expression
                            ? { type: 'CRON', value: s.cron_expression, color: 'border-primary text-primary' }
                            : s.interval_seconds
                                ? { type: 'INTERVAL', value: `каждые ${s.interval_seconds}s`, color: 'border-amber-400 text-amber-400' }
                                : { type: 'ONE-SHOT', value: formatScheduleUtc(s.one_shot_at), color: 'border-cyan-400 text-cyan-400' };

                        return (
                            <tr key={s.id} className="hover:bg-muted transition-colors group">
                                <td className="px-4 py-3">
                                    <button
                                        type="button"
                                        onClick={() => change(s, 'toggle')}
                                        disabled={error || changeSchedule.isPending}
                                        aria-pressed={s.is_active}
                                        aria-label={`Активность расписания ${s.name}`}
                                        className="rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-50"
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
                                    {changeSchedule.isPending && changeSchedule.variables?.schedule.id === s.id &&
                                        <p role="status" className="mt-1 whitespace-normal text-muted-foreground">Обновление расписания…</p>}
                                    {notice?.id === s.id && <p role={notice.error ? 'alert' : 'status'} className={`mt-1 max-w-72 whitespace-normal ${notice.error ? 'text-destructive' : 'text-muted-foreground'}`}>{notice.text}</p>}
                                </td>
                                <td className="px-4 py-3">
                                    <Badge variant="outline" className={`text-[9px] ${s.target_type === 'script' ? 'border-emerald-400 text-emerald-400' : 'border-violet-400 text-violet-400'}`}>
                                        {(s.target_type || '').toUpperCase()}
                                    </Badge>
                                </td>
                                <td className="px-4 py-3">
                                    <div className="flex items-center gap-2">
                                        <Badge variant="outline" className={`text-[8px] ${triggerInfo.color}`}>{triggerInfo.type}</Badge>
                                        <span className="text-muted-foreground text-[10px]">{triggerInfo.value}</span>
                                    </div>
                                    {s.cron_expression && <p className="mt-1 text-[10px] text-muted-foreground">{s.timezone || 'UTC'}</p>}
                                </td>
                                <td className="px-4 py-3 text-muted-foreground">{s.total_runs}</td>
                                <td className="px-4 py-3 text-muted-foreground">{timeAgo(s.last_fired_at)}</td>
                                <td className="px-4 py-3">
                                    <ScheduleNextFire schedule={s} />
                                </td>
                                <td className="px-4 py-3">
                                    <Badge variant="outline" className={`text-[8px] ${s.conflict_policy === 'skip' ? 'border-amber-400 text-amber-400' :
                                            s.conflict_policy === 'queue' ? 'border-blue-400 text-blue-400' :
                                                'border-destructive text-destructive'
                                        }`}>
                                        {(s.conflict_policy || '').toUpperCase()}
                                    </Badge>
                                </td>
                                <td className="px-4 py-3 text-right">
                                    <div className="flex items-center justify-end gap-1">
                                        <Button
                                            variant="ghost" size="tiny"
                                            className="text-muted-foreground hover:text-success hover:bg-success/10"
                                            onClick={() => change(s, 'fire')}
                                            disabled={(!s.is_active && !pendingFire(s.id)) || error || changeSchedule.isPending}
                                            title={pendingFire(s.id) ? 'Повторить запрос с прежним идентификатором' : s.is_active ? 'Поставить в очередь планировщика' : 'Сначала включите расписание'}
                                            aria-label={`Запросить запуск расписания ${s.name}`}
                                        >
                                            <Zap className="w-3 h-3" />
                                        </Button>
                                        <Button variant="ghost" size="tiny" title="История срабатываний"
                                            aria-label={`История срабатываний: ${s.name}`} onClick={() => setHistorySchedule(s)}>
                                            <Clock className="w-3 h-3" />
                                        </Button>
                                        <Button
                                            variant="ghost" size="tiny"
                                            className="text-muted-foreground hover:text-primary hover:bg-primary/10"
                                            title="Редактировать"
                                            disabled={changeSchedule.isPending}
                                            onClick={() => onEditSchedule(s)}
                                        >
                                            <Pencil className="w-3 h-3" />
                                        </Button>
                                        <Button
                                            variant="ghost" size="tiny"
                                            className="text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                                            title="Выключить с сохранением истории"
                                            disabled={!s.is_active || error || changeSchedule.isPending}
                                            onClick={() => {
                                                if (confirm(`Выключить расписание «${s.name}»? История срабатываний сохранится.`)) {
                                                    change(s, 'delete');
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
        <ScheduleExecutionHistoryDialog schedule={historySchedule} onClose={() => setHistorySchedule(null)} />
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
        mutationFn: async (devices: string[]) => {
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
            return { pipeline: data as Pipeline, devices };
        },
        onSuccess: async ({ pipeline, devices }) => {
            queryClient.invalidateQueries({ queryKey: ['pipelines'] });
            if (devices.length > 0) {
                try {
                    if (!pipeline?.id || !Number.isInteger(pipeline.version) || pipeline.version < 1 || !Number.isFinite(Date.parse(pipeline.updated_at))) {
                        throw new Error('Нет подтверждённой версии созданного конвейера.');
                    }
                    const single = devices.length === 1;
                    const { data } = await api.post(`/pipelines/${pipeline.id}/${single ? 'run' : 'run-batch'}`, {
                        ...(single ? { device_id: devices[0] } : { device_ids: devices }),
                        input_params: {},
                        expected_version: pipeline.version,
                        expected_updated_at: pipeline.updated_at,
                    });
                    if (typeof data?.id !== 'string' || !data.id || data.pipeline_id !== pipeline.id
                        || data.pipeline_version !== pipeline.version
                        || (single ? data.device_id !== devices[0] : data.total !== devices.length)) {
                        throw new Error('Некорректная квитанция запуска.');
                    }
                    const href = `/orchestration?${single ? 'run_id' : 'batch_id'}=${encodeURIComponent(data.id)}`;
                    queryClient.invalidateQueries({ queryKey: ['pipeline-runs'] });
                    toast.success('Конвейер создан, запуск принят', {
                        description: <Link className="text-primary underline" href={href}>Открыть результаты</Link>,
                    });
                } catch (error) {
                    toast.success('Pipeline создан');
                    toast.error(getApiErrorMessage(error, 'Запуск не подтверждён. Проверьте историю запусков.'));
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
                <DialogContent layout="workspace" className="max-w-4xl">
                <DialogHeader>
                    <DialogTitle className="font-mono tracking-tight flex items-center gap-2">
                        <GitBranch className="w-5 h-5 text-primary" />
                        Создать Pipeline
                    </DialogTitle>
                    <DialogDescription className="text-xs text-muted-foreground font-mono">
                        Построй цепочку шагов автоматизации. Каждый шаг выполняется последовательно или по DAG-логике (on_success/on_failure).
                    </DialogDescription>
                </DialogHeader>

                <DialogBody>
                    {/* Основные поля */}
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Название *</Label>
                            <Input
                                placeholder="Например: Reboot + Screenshot + Report"
                                value={name}
                                onChange={e => setName(e.target.value)}
                                className="h-9 bg-background border-border font-mono text-xs"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Теги (через запятую)</Label>
                            <Input
                                placeholder="automation, reboot, critical"
                                value={tags}
                                onChange={e => setTags(e.target.value)}
                                className="h-9 bg-background border-border font-mono text-xs"
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
                            className="w-full rounded-sm border border-border bg-background px-3 py-2 text-xs font-mono text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 resize-none"
                        />
                    </div>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Глобальный таймаут (мс)</Label>
                            <Input
                                type="number"
                                value={globalTimeout}
                                onChange={e => setGlobalTimeout(Number(e.target.value))}
                                className="h-9 bg-background border-border font-mono text-xs"
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
                                className="h-9 bg-background border-border font-mono text-xs"
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
                                                className="h-7 bg-background border-border font-mono text-[11px]"
                                                placeholder="step_1"
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">Название *</Label>
                                            <Input
                                                value={step.name}
                                                onChange={e => updateStep(idx, { name: e.target.value })}
                                                className="h-7 bg-background border-border font-mono text-[11px]"
                                                placeholder="Выполнить скрипт"
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">Тип</Label>
                                            <select
                                                value={step.type}
                                                onChange={e => updateStep(idx, { type: e.target.value })}
                                                className="w-full h-7 rounded-sm border border-border bg-background px-2 text-[11px] font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
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
                                                className="h-7 bg-background border-border font-mono text-[11px]"
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
                                                className="h-7 bg-background border-border font-mono text-[11px]"
                                                min={0}
                                                max={10}
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">On Success → ID</Label>
                                            <Input
                                                value={step.on_success}
                                                onChange={e => updateStep(idx, { on_success: e.target.value })}
                                                className="h-7 bg-background border-border font-mono text-[11px]"
                                                placeholder="step_2"
                                            />
                                        </div>
                                        <div className="space-y-1">
                                            <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">On Failure → ID</Label>
                                            <Input
                                                value={step.on_failure}
                                                onChange={e => updateStep(idx, { on_failure: e.target.value })}
                                                className="h-7 bg-background border-border font-mono text-[11px]"
                                                placeholder=""
                                            />
                                        </div>
                                    </div>
                                    {/* Выбор скрипта для execute_script */}
                                    {step.type === 'execute_script' && (
                                        <div className="space-y-1 mb-2">
                                            <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">Скрипт *</Label>
                                            <ScriptCatalogPicker
                                                label={`Сценарий шага ${idx + 1}`}
                                                value={step.script_id}
                                                onChange={(id, item) => updateStep(idx, { script_id: id, name: step.name || item?.name || '' })}
                                            />
                                        </div>
                                    )}
                                    <div className="space-y-1">
                                        <Label className="text-[9px] uppercase font-bold tracking-widest text-muted-foreground">Параметры (JSON)</Label>
                                        <textarea
                                            value={step.params}
                                            onChange={e => updateStep(idx, { params: e.target.value })}
                                            rows={2}
                                            className={`w-full rounded-sm border px-2 py-1.5 text-[11px] font-mono text-foreground bg-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 resize-none ${
                                                validateParamsJson(step.params) ? 'border-border' : 'border-destructive'
                                            }`}
                                            placeholder='{"script_id": "...", "args": ["--flag"]}'
                                        />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                                {showDeviceSelector && (
                    <div className="mt-3 pt-3 border-t border-border">
                        <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground mb-2 block">Целевые устройства</Label>
                        <DeviceSelector value={targetDeviceIds} onChange={setTargetDeviceIds} />
                    </div>
                )}
                </DialogBody>

                <DialogFooter className="mt-4 pt-4 border-t border-border">
                    <Button variant="outline" onClick={() => setOpen(false)} className="font-mono text-xs">
                        Отмена
                    </Button>
                    <Button
                        onClick={() => {
                            setShowDeviceSelector(false);
                            createMut.mutate([]);
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
                                createMut.mutate(targetDeviceIds);
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
    const [launchBlocked, setLaunchBlocked] = useState(false);
    const [error, setError] = useState('');
    const busy = useRef(false);

    const runMut = useMutation({
        mutationFn: async ({ preview, devices, inputs }: { preview: Pipeline; devices: string[]; inputs: object }) => {
            const single = devices.length === 1;
            const { data } = await api.post(`/pipelines/${preview.id}/${single ? 'run' : 'run-batch'}`, {
                ...(single ? { device_id: devices[0] } : { device_ids: devices }),
                input_params: inputs,
                expected_version: preview.version,
                expected_updated_at: preview.updated_at,
            });
            if (typeof data?.id !== 'string' || !data.id || data.pipeline_id !== preview.id
                || data.pipeline_version !== preview.version
                || (single ? data.device_id !== devices[0] : data.total !== devices.length)) {
                throw new Error('Неподтверждённая квитанция запуска');
            }
            return { id: data.id as string, single, version: preview.version };
        },
        onSuccess: ({ id, single, version }) => {
            queryClient.invalidateQueries({ queryKey: ['pipeline-runs'] });
            const href = `/orchestration?${single ? 'run_id' : 'batch_id'}=${encodeURIComponent(id)}`;
            toast.success(`${single ? 'Запуск' : 'Пакет'} принят`, {
                description: <div className="space-y-1"><p className="break-all">Версия {version} · {id}</p><Link className="text-primary underline" href={href}>Открыть результаты</Link></div>,
            });
            onOpenChange(false);
        },
        onError: error => {
            const status = (error as { response?: { status?: number } })?.response?.status;
            if (status === 409) {
                setLaunchBlocked(true);
                setError('Конвейер изменился или редактируется. Закройте окно, обновите каталог и подтвердите новый запуск.');
                void queryClient.invalidateQueries({ queryKey: ['pipelines'] });
            } else if (!status || status >= 500) {
                setLaunchBlocked(true);
                setError('Принятие запуска не подтверждено. Проверьте историю запусков перед повтором.');
            } else {
                setError(getApiErrorMessage(error, 'Запуск отклонён. Проверьте параметры и доступ.'));
            }
        },
        onSettled: () => { busy.current = false; },
    });

    const validPreview = !!pipeline && Number.isInteger(pipeline.version) && pipeline.version > 0 && Number.isFinite(Date.parse(pipeline.updated_at));
    const canSubmit = selectedDeviceIds.length > 0 && validPreview && !launchBlocked;
    const submit = () => {
        if (!pipeline || !canSubmit || busy.current) return;
        let inputs: unknown;
        try {
            inputs = JSON.parse(inputParams || '{}');
        } catch {
            setError('Входные параметры должны быть корректным объектом JSON.');
            return;
        }
        if (!inputs || typeof inputs !== 'object' || Array.isArray(inputs)) {
            setError('Входные параметры должны быть корректным объектом JSON.');
            return;
        }
        setError('');
        busy.current = true;
        runMut.mutate({ preview: pipeline, devices: selectedDeviceIds, inputs });
    };

    return (
        <Dialog open={open} onOpenChange={value => { if (!busy.current) onOpenChange(value); }}>
            <DialogContent layout="workspace" className="max-w-2xl">
                <DialogHeader>
                    <DialogTitle className="font-mono tracking-tight flex items-center gap-2">
                        <Play className="w-5 h-5 text-success" />
                        Запустить Pipeline
                    </DialogTitle>
                    <DialogDescription className="text-xs text-muted-foreground font-mono">
                        <span className="text-primary font-bold">{pipeline?.name}</span> — {pipeline?.steps.length ?? 0} шагов, v{pipeline?.version}
                    </DialogDescription>
                </DialogHeader>

                <DialogBody>
                    {/* Выбор устройств */}
                    <DeviceSelector value={selectedDeviceIds} onChange={setSelectedDeviceIds} />

                    <div className="space-y-1.5">
                        <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Входные параметры (JSON)</Label>
                        <textarea
                            value={inputParams}
                            onChange={e => setInputParams(e.target.value)}
                            rows={3}
                            className="w-full rounded-sm border border-border bg-background px-3 py-2 text-xs font-mono text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary/50 resize-none"
                            placeholder='{"key": "value"}'
                        />
                    </div>
                    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
                    {pipeline && !validPreview && <p role="status" className="text-sm text-muted-foreground">Версия конвейера недоступна. Обновите каталог.</p>}

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
                </DialogBody>

                <DialogFooter className="mt-4">
                    <Button variant="outline" disabled={runMut.isPending} onClick={() => onOpenChange(false)} className="font-mono text-xs">
                        Отмена
                    </Button>
                    <Button
                        onClick={submit}
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

function EditScheduleDialog({ schedule, open, onOpenChange }: {
    schedule: Schedule | null;
    open: boolean;
    onOpenChange: (v: boolean) => void;
}) {
    const queryClient = useQueryClient();
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [triggerType, setTriggerType] = useState<'cron' | 'interval' | 'one_shot'>('cron');
    const [cronExpression, setCronExpression] = useState('');
    const [intervalSeconds, setIntervalSeconds] = useState(3600);
    const [oneShotAt, setOneShotAt] = useState('');
    const [oneShotLoadError, setOneShotLoadError] = useState<string | null>(null);
    const originalOneShot = useRef<{ raw: string; input: string } | null>(null);
    const [targetType, setTargetType] = useState<'script' | 'pipeline'>('pipeline');
    const [pipelineId, setPipelineId] = useState('');
    const [scriptId, setScriptId] = useState('');
    const [conflictPolicy, setConflictPolicy] = useState<'skip' | 'queue' | 'cancel'>('skip');
    const [timezone, setTimezone] = useState('UTC');
    const [targetDeviceIds, setTargetDeviceIds] = useState<string[]>([]);
    const [revisionConflict, setRevisionConflict] = useState(false);

    // Заполняем форму данными расписания при открытии
    const scheduleId = schedule?.id;

    // Синхронизация состояния формы при смене расписания
    useEffect(() => {
        if (!schedule) return;
        setRevisionConflict(false);
        originalOneShot.current = null;
        setName(schedule.name);
        setDescription(schedule.description || '');
        setTimezone(schedule.timezone || 'UTC');
        setTargetType(schedule.target_type as 'script' | 'pipeline');
        setPipelineId(schedule.pipeline_id || '');
        setScriptId(schedule.script_id || '');
        setConflictPolicy(schedule.conflict_policy as 'skip' | 'queue' | 'cancel');
        setTargetDeviceIds(schedule.device_ids || []);
        if (schedule.cron_expression) {
            setTriggerType('cron');
            setCronExpression(schedule.cron_expression);
        } else if (schedule.interval_seconds) {
            setTriggerType('interval');
            setIntervalSeconds(schedule.interval_seconds);
        } else {
            setTriggerType('one_shot');
            try {
                const input = schedule.one_shot_at ? isoToUtcDateTimeInput(schedule.one_shot_at) : '';
                setOneShotAt(input);
                if (schedule.one_shot_at) originalOneShot.current = { raw: schedule.one_shot_at, input };
                setOneShotLoadError(null);
            } catch {
                setOneShotAt('');
                setOneShotLoadError('Дата запуска API некорректна. Укажите подтверждённый момент в UTC перед сохранением.');
            }
        }
    }, [scheduleId]);

    const updateMut = useMutation({
        mutationFn: async () => {
            if (!schedule || !scheduleRevision(schedule.updated_at)) throw new Error('Версия расписания не подтверждена');
            const originalDeviceIds = schedule.device_ids ?? [];
            const deviceIdsChanged = targetDeviceIds.length !== originalDeviceIds.length
                || targetDeviceIds.some(id => !originalDeviceIds.includes(id));
            const payload: Record<string, any> = {
                expected_updated_at: schedule.updated_at,
                name: name.trim(),
                description: description.trim() || null,
                target_type: targetType,
                conflict_policy: conflictPolicy,
                ...(timezone !== (schedule.timezone || 'UTC') ? { timezone } : {}),
                ...(deviceIdsChanged ? { device_ids: targetDeviceIds } : {}),
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
                // An unchanged source retains backend sub-millisecond precision and its original aware representation.
                payload.one_shot_at = originalOneShot.current && oneShotAt === originalOneShot.current.input
                    ? originalOneShot.current.raw : utcDateTimeInputToIso(oneShotAt);
                payload.cron_expression = null;
                payload.interval_seconds = null;
            }

            const { data } = await api.patch(`/schedules/${schedule.id}`, payload);
            if (data?.id !== schedule.id || !scheduleRevision(data?.updated_at)) {
                throw new Error('Обновление расписания не подтверждено');
            }
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['schedules'] });
            toast.success('Расписание обновлено');
            onOpenChange(false);
        },
        onError: (failure) => {
            if (scheduleConflict(failure)) {
                setRevisionConflict(true);
                void queryClient.invalidateQueries({ queryKey: ['schedules'] });
                return;
            }
            toast.error(getApiErrorMessage(failure, 'Обновление расписания не подтверждено. Проверьте список.'));
        },
    });

    const canSubmit = name.trim().length > 0 && (
        (triggerType === 'cron' && cronExpression.trim()) ||
        (triggerType === 'interval' && Number.isInteger(intervalSeconds) && intervalSeconds >= 60 && intervalSeconds <= 86400) ||
        (triggerType === 'one_shot' && isValidUtcDateTimeInput(oneShotAt))
    ) && (
        (targetType === 'pipeline' && pipelineId) ||
        (targetType === 'script' && scriptId)
    );

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent layout="workspace" className="max-w-2xl">
                <DialogHeader>
                    <DialogTitle className="font-mono tracking-tight flex items-center gap-2">
                        <Pencil className="w-5 h-5 text-primary" />
                        Редактировать расписание
                    </DialogTitle>
                    <DialogDescription className="text-xs text-muted-foreground font-mono">
                        Измени параметры существующего расписания. Бэкенд пересчитает <code>next_fire_at</code> автоматически.
                    </DialogDescription>
                </DialogHeader>

                <DialogBody>
                    {revisionConflict && <p role="alert" className="text-sm text-destructive">
                        {SCHEDULE_CONFLICT_TEXT} Закройте форму и откройте расписание снова.
                    </p>}
                    {schedule && !scheduleRevision(schedule.updated_at) && <p role="alert" className="text-sm text-destructive">
                        Версия расписания не подтверждена. Обновите список перед изменением.
                    </p>}
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Название *</Label>
                            <Input
                                placeholder="Ежечасный health-check"
                                value={name}
                                onChange={e => setName(e.target.value)}
                                className="h-9 bg-background border-border font-mono text-xs"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Часовой пояс CRON (IANA)</Label>
                            <Input
                                aria-label="Часовой пояс CRON"
                                value={timezone}
                                onChange={e => setTimezone(e.target.value)}
                                className="h-9 bg-background border-border font-mono text-xs"
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
                            className="h-9 bg-background border-border font-mono text-xs"
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

                    {triggerType === 'cron' && <>
                        <CronBuilder value={cronExpression} onChange={setCronExpression} />
                        <p className="text-xs text-muted-foreground">{SCHEDULE_CRON_POLICY}</p>
                    </>}
                    {triggerType === 'interval' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Интервал (секунды) *</Label>
                            <Input
                                type="number"
                                aria-label="Интервал запуска в секундах"
                                value={intervalSeconds}
                                onChange={e => setIntervalSeconds(Number(e.target.value))}
                                className="h-9 bg-background border-border font-mono text-xs"
                                min={60}
                                max={86400}
                                step={1}
                            />
                        </div>
                    )}
                    {triggerType === 'one_shot' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Дата/время запуска (UTC) *</Label>
                            <Input
                                type="datetime-local"
                                aria-label="Дата и время запуска (UTC)"
                                step="0.001"
                                value={oneShotAt}
                                onChange={e => { setOneShotAt(e.target.value); setOneShotLoadError(null); }}
                                className="h-9 bg-background border-border font-mono text-xs"
                            />
                            <p className="text-xs text-muted-foreground">Часовой пояс расписания применяется к CRON. Разовый запуск задаётся в UTC; часовой пояс браузера не меняет это время.</p>
                            {oneShotLoadError && <p role="alert" className="text-xs text-destructive">{oneShotLoadError}</p>}
                        </div>
                    )}

                    {/* Цель */}
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
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
                                className="w-full h-9 rounded-sm border border-border bg-background px-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
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
                            <PipelineCatalogPicker value={pipelineId} onChange={setPipelineId} enabled={open && targetType === 'pipeline'} />
                        </div>
                    )}
                    {targetType === 'script' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Скрипт *</Label>
                            <ScriptCatalogPicker label="Сценарий расписания" value={scriptId} onChange={setScriptId} />
                        </div>
                    )}

                    {/* Целевые устройства */}
                    <div className="space-y-1.5">
                        <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Целевые устройства</Label>
                        <DeviceSelector value={targetDeviceIds} onChange={setTargetDeviceIds} />
                        {targetDeviceIds.length === 0 && (schedule?.group_id || schedule?.device_tags?.length
                            ? <p className="text-xs text-muted-foreground">Цели из сохранённой группы или тегов продолжат действовать.</p>
                            : <p role="status" className="text-xs text-muted-foreground">
                                {schedule?.is_active ? 'Без устройств, группы и тегов планировщик пропустит срабатывание.' : 'У расписания нет выбранных целей.'}
                              </p>)}
                    </div>
                </DialogBody>

                <DialogFooter className="mt-4 pt-4 border-t border-border">
                    <Button variant="outline" onClick={() => onOpenChange(false)} className="font-mono text-xs">
                        Отмена
                    </Button>
                    <Button
                        onClick={() => updateMut.mutate()}
                        disabled={!canSubmit || updateMut.isPending || revisionConflict || !scheduleRevision(schedule?.updated_at)}
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

function CreateScheduleDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
    const queryClient = useQueryClient();
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
            else {
                payload.one_shot_at = utcDateTimeInputToIso(oneShotAt);
            }

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
        (triggerType === 'interval' && Number.isInteger(intervalSeconds) && intervalSeconds >= 60 && intervalSeconds <= 86400) ||
        (triggerType === 'one_shot' && isValidUtcDateTimeInput(oneShotAt))
    ) && (
        (targetType === 'pipeline' && pipelineId) ||
        (targetType === 'script' && scriptId)
    ) && targetDeviceIds.length > 0;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent layout="workspace" className="max-w-2xl">
                <DialogHeader>
                    <DialogTitle className="font-mono tracking-tight flex items-center gap-2">
                        <CalendarClock className="w-5 h-5 text-primary" />
                        Создать расписание
                    </DialogTitle>
                    <DialogDescription className="text-xs text-muted-foreground font-mono">
                        Настрой автоматический запуск скрипта или pipeline по CRON, интервалу или одноразово.
                    </DialogDescription>
                </DialogHeader>

                <DialogBody>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Название *</Label>
                            <Input
                                placeholder="Ежечасный health-check"
                                value={name}
                                onChange={e => setName(e.target.value)}
                                className="h-9 bg-background border-border font-mono text-xs"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Часовой пояс CRON (IANA)</Label>
                            <Input
                                aria-label="Часовой пояс CRON"
                                value={timezone}
                                onChange={e => setTimezone(e.target.value)}
                                className="h-9 bg-background border-border font-mono text-xs"
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
                            className="h-9 bg-background border-border font-mono text-xs"
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

                    {triggerType === 'cron' && <>
                        <CronBuilder value={cronExpression} onChange={setCronExpression} />
                        <p className="text-xs text-muted-foreground">{SCHEDULE_CRON_POLICY}</p>
                    </>}
                    {triggerType === 'interval' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Интервал (секунды) *</Label>
                            <Input
                                type="number"
                                aria-label="Интервал запуска в секундах"
                                value={intervalSeconds}
                                onChange={e => setIntervalSeconds(Number(e.target.value))}
                                className="h-9 bg-background border-border font-mono text-xs"
                                min={60}
                                max={86400}
                                step={1}
                            />
                        </div>
                    )}
                    {triggerType === 'one_shot' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Дата/время запуска (UTC) *</Label>
                            <Input
                                type="datetime-local"
                                aria-label="Дата и время запуска (UTC)"
                                step="0.001"
                                value={oneShotAt}
                                onChange={e => setOneShotAt(e.target.value)}
                                className="h-9 bg-background border-border font-mono text-xs"
                            />
                            <p className="text-xs text-muted-foreground">Часовой пояс расписания применяется к CRON. Разовый запуск задаётся в UTC; часовой пояс браузера не меняет это время.</p>
                        </div>
                    )}

                    {/* Цель */}
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
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
                                className="w-full h-9 rounded-sm border border-border bg-background px-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary/50"
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
                            <PipelineCatalogPicker value={pipelineId} onChange={setPipelineId} enabled={open && targetType === 'pipeline'} />
                        </div>
                    )}
                    {targetType === 'script' && (
                        <div className="space-y-1.5">
                            <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Скрипт *</Label>
                            <ScriptCatalogPicker label="Сценарий расписания" value={scriptId} onChange={setScriptId} />
                        </div>
                    )}

                    {/* Целевые устройства */}
                    <div className="space-y-1.5">
                        <Label className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground">Целевые устройства</Label>
                        <DeviceSelector value={targetDeviceIds} onChange={setTargetDeviceIds} />
                        {!targetDeviceIds.length && <p role="status" className="text-xs text-muted-foreground">Выберите минимум одно устройство для запуска. Пустой выбор не означает весь парк.</p>}
                    </div>
                </DialogBody>

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
