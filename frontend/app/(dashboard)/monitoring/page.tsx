'use client';

import { useMemo, useState, type ReactNode } from 'react';
import { AlertTriangle, ArrowDownToLine, ArrowUpFromLine, CheckCircle2, Clock3, Cpu, Database, HardDrive, RefreshCw, Search, Server, Wifi } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Badge } from '@/src/shared/ui/badge';
import { Button } from '@/src/shared/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/src/shared/ui/card';
import { Input } from '@/src/shared/ui/input';
import { ClusterHeatmap } from '@/src/features/monitoring/ClusterHeatmap';
import { formatBytes, getMonitoringTelemetryGaps, type ClusterNode, type MonitoringMetrics, summarizeMonitoringHealth } from '@/src/features/monitoring/monitoringTypes';

type StatusFilter = 'all' | 'healthy' | 'attention' | 'unavailable';

function parseMonitoringNodes(payload: unknown): ClusterNode[] {
    if (!Array.isArray(payload)) {
        throw new Error('Ожидается список проверок сервиса.');
    }
    const nodes: unknown[] = payload;
    const isNode = (value: unknown): value is ClusterNode => {
        if (!value || typeof value !== 'object') return false;
        const candidate = value as Partial<ClusterNode>;
        return typeof candidate.id === 'string'
            && typeof candidate.name === 'string'
            && typeof candidate.type === 'string'
            && typeof candidate.status === 'string';
    };
    if (!nodes.every(isNode)) {
        throw new Error('Ответ содержит некорректную запись проверки сервиса.');
    }
    return nodes as ClusterNode[];
}

function formatTime(timestamp: number) {
    if (!timestamp) return 'Ожидаем первые данные';
    return new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(timestamp);
}

function healthTone(tone: ReturnType<typeof summarizeMonitoringHealth>['tone']) {
    if (tone === 'healthy') return 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300';
    if (tone === 'warning') return 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300';
    if (tone === 'critical') return 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300';
    return 'border-border bg-muted text-muted-foreground';
}

function healthLabel(label: string) {
    const labels: Record<string, string> = {
        'CHECKING SYSTEMS': 'Проверяем сервисы',
        'STATUS UNAVAILABLE': 'Статус недоступен',
        'NO HEALTH CHECKS RECEIVED': 'Нет данных о здоровье',
        'CRITICAL COMPONENT FAILURE': 'Критическая ошибка сервиса',
        'DEGRADED COMPONENTS': 'Есть деградация',
        'HEALTH CHECKS PASS · TELEMETRY DEGRADED': 'Проверки прошли · метрики частично недоступны',
        'ALL OBSERVED CHECKS HEALTHY': 'Все полученные проверки в норме',
        'HEALTH STATUS INCOMPLETE': 'Статус частичный',
    };
    return labels[label] ?? label;
}

function Sparkline({ values, tone }: { values: number[]; tone: 'blue' | 'violet' | 'green' }) {
    if (!values.length) {
        return <p className="mt-4 text-xs text-muted-foreground">История измерений этим endpoint не возвращается.</p>;
    }
    const maximum = Math.max(...values.filter(Number.isFinite), 1);
    const color = tone === 'blue' ? 'bg-sky-500' : tone === 'violet' ? 'bg-violet-500' : 'bg-emerald-500';
    return (
        <div className="mt-4 flex h-10 items-end gap-1" role="img" aria-label={`Последние ${values.length} измерений`}>
            {values.map((value, index) => (
                <span key={`${index}-${value}`} className={`min-w-1 flex-1 rounded-t-sm ${color} opacity-80`} style={{ height: `${Math.max(4, Math.min(100, (Math.max(0, value) / maximum) * 100))}%` }} />
            ))}
        </div>
    );
}

function MetricCard({ title, icon: Icon, value, detail, children }: {
    title: string;
    icon: typeof Cpu;
    value: string;
    detail: string;
    children?: ReactNode;
}) {
    return (
        <Card className="rounded-xl border-border/80 shadow-sm">
            <CardHeader className="flex-row items-center justify-between space-y-0 border-0 pb-0">
                <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
                <span className="flex h-9 w-9 items-center justify-center rounded-lg border border-border bg-muted/70 text-muted-foreground" aria-hidden="true"><Icon className="h-4 w-4" /></span>
            </CardHeader>
            <CardContent className="pt-3">
                <p className="text-2xl font-semibold tabular-nums tracking-tight text-foreground">{value}</p>
                <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
                {children}
            </CardContent>
        </Card>
    );
}

function isHealthy(node: ClusterNode) {
    const status = String(node.status).toUpperCase();
    return status === 'HEALTHY' || status === 'OK';
}

function isAttention(node: ClusterNode) {
    const status = String(node.status).toUpperCase();
    return ['WARNING', 'DEGRADED', 'CRITICAL', 'DOWN'].includes(status);
}

export default function MonitoringPage() {
    const metricsQuery = useQuery<MonitoringMetrics>({
        queryKey: ['monitoring-metrics'],
        queryFn: async () => {
            const { data } = await api.get<MonitoringMetrics>('/monitoring/metrics');
            return data;
        },
        refetchInterval: 10000,
    });
    const nodesQuery = useQuery<ClusterNode[]>({
        queryKey: ['monitoring-nodes'],
        queryFn: async () => {
            const { data } = await api.get<unknown>('/monitoring/nodes');
            return parseMonitoringNodes(data);
        },
        refetchInterval: 10000,
    });

    const metrics = metricsQuery.data;
    const nodes = nodesQuery.data;
    const telemetryGaps = getMonitoringTelemetryGaps(metrics);
    const systemHealth = summarizeMonitoringHealth(nodes, {
        loading: nodesQuery.isLoading || metricsQuery.isLoading,
        failed: nodesQuery.isError,
        telemetryFailed: metricsQuery.isError,
        telemetryIncomplete: metricsQuery.isSuccess && telemetryGaps.length > 0,
    });
    const [search, setSearch] = useState('');
    const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
    const observedNodes = useMemo(() => nodes ?? [], [nodes]);
    const filteredNodes = useMemo(() => {
        const needle = search.trim().toLocaleLowerCase();
        return observedNodes.filter((node) => {
            const matchesSearch = !needle || [node.name, node.id, node.type].some((part) => part.toLocaleLowerCase().includes(needle));
            const matchesStatus = statusFilter === 'all'
                || (statusFilter === 'healthy' && isHealthy(node))
                || (statusFilter === 'attention' && isAttention(node))
                || (statusFilter === 'unavailable' && !isHealthy(node) && !isAttention(node));
            return matchesSearch && matchesStatus;
        });
    }, [observedNodes, search, statusFilter]);

    const healthyCount = observedNodes.filter(isHealthy).length;
    const attentionCount = observedNodes.filter(isAttention).length;
    const unavailableCount = observedNodes.length - healthyCount - attentionCount;
    const isRefreshing = metricsQuery.isFetching || nodesQuery.isFetching;
    const lastUpdated = Math.min(metricsQuery.dataUpdatedAt || 0, nodesQuery.dataUpdatedAt || 0);
    const refreshNow = () => { void Promise.all([metricsQuery.refetch(), nodesQuery.refetch()]); };

    const filters: Array<{ id: StatusFilter; label: string; count: number }> = [
        { id: 'all', label: 'Все сервисы', count: observedNodes.length },
        { id: 'healthy', label: 'Работают', count: healthyCount },
        { id: 'attention', label: 'Внимание', count: attentionCount },
        { id: 'unavailable', label: 'Неизвестно', count: unavailableCount },
    ];

    return (
        <main className="mx-auto flex w-full max-w-[1600px] flex-col gap-6 p-4 sm:p-6 lg:p-8">
            <header className="flex flex-col gap-4 border-b border-border/70 pb-5 sm:flex-row sm:items-end sm:justify-between">
                <div className="min-w-0">
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Sphere / Наблюдаемость</p>
                    <h1 className="mt-2 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">Инфраструктура</h1>
                    <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Состояние сервисов и реальные метрики backend. Показатели не подменяются нулями, если API их не вернул.</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <div className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-sm font-medium ${healthTone(systemHealth.tone)}`} role="status" aria-live="polite">
                        <span className={`h-2 w-2 rounded-full ${systemHealth.tone === 'healthy' ? 'bg-emerald-500' : systemHealth.tone === 'critical' ? 'bg-rose-500' : systemHealth.tone === 'warning' ? 'bg-amber-500' : 'bg-muted-foreground'}`} />
                        <span className="max-w-[240px] truncate">{healthLabel(systemHealth.label)}</span>
                    </div>
                    <Button variant="outline" size="sm" onClick={refreshNow} disabled={isRefreshing} aria-label="Обновить метрики и проверки сервисов">
                        <RefreshCw className={`mr-2 h-4 w-4 ${isRefreshing ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
                        Обновить
                    </Button>
                </div>
            </header>

            {(nodesQuery.isError || metricsQuery.isError) && (
                <div role="alert" className="flex items-start gap-3 rounded-xl border border-amber-300/70 bg-amber-50/70 p-4 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    <div><p className="font-medium">Часть наблюдаемости сейчас недоступна</p><p className="mt-1 opacity-80">Проверьте API и права доступа. Недоступные значения показаны отдельно и не считаются здоровыми.</p></div>
                </div>
            )}

            {metricsQuery.isSuccess && telemetryGaps.length > 0 && (
                <div role="status" className="rounded-xl border border-amber-300/60 bg-amber-50/50 px-4 py-3 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/20 dark:text-amber-200">
                    <span className="font-medium">Проверки сервисов и покрытие метрик — разные сигналы.</span>{' '}
                    Не получены: {telemetryGaps.join(', ')}. Отсутствующие измерения не означают ноль или подтверждённо здоровый сервис.
                </div>
            )}

            <section aria-label="Метрики backend" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <MetricCard title="Linux load · 1 мин" icon={Cpu} value={metricsQuery.isError ? 'Недоступно' : metrics?.cpu?.linuxLoad1mPerCpu == null ? '—' : metrics.cpu.linuxLoad1mPerCpu.toFixed(2)} detail="Нагрузка хоста на логический CPU; это не процент CPU контейнера.">
                    {metricsQuery.isError ? <p className="mt-4 text-xs text-amber-700 dark:text-amber-300">Запрос метрик завершился ошибкой.</p> : <Sparkline values={metrics?.cpu?.history ?? []} tone="blue" />}
                </MetricCard>
                <MetricCard title="Память контейнера" icon={HardDrive} value={metricsQuery.isError ? 'Недоступно' : formatBytes(metrics?.ram?.currentBytes)} detail={metrics?.ram?.totalBytes == null ? 'Лимит cgroup не сообщён.' : `Из ${formatBytes(metrics.ram.totalBytes)} по данным cgroup.`}>
                    {metricsQuery.isError ? <p className="mt-4 text-xs text-amber-700 dark:text-amber-300">Запрос метрик завершился ошибкой.</p> : <Sparkline values={metrics?.ram?.history ?? []} tone="violet" />}
                </MetricCard>
                <MetricCard title="Redis" icon={Database} value={metricsQuery.isError ? 'Недоступно' : String(metrics?.redis?.status ?? 'Нет данных')} detail={metrics?.redis?.ops == null ? 'Операции/с не сообщаются.' : `${metrics.redis.ops} операций в секунду.`}>
                    <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-border/70 pt-3 text-xs">
                        <div><dt className="text-muted-foreground">Память</dt><dd className="mt-1 font-medium text-foreground">{metrics?.redis?.memory ?? '—'}</dd></div>
                        <div><dt className="text-muted-foreground">Клиенты</dt><dd className="mt-1 font-medium text-foreground">{metrics?.redis?.clients ?? '—'}</dd></div>
                    </dl>
                </MetricCard>
                <MetricCard title="Сетевые счётчики" icon={Wifi} value={metricsQuery.isError ? 'Недоступно' : `${metrics?.network?.activeTunnels ?? '—'} тунн.`} detail="Активные туннели только если метрика инструментирована.">
                    <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-border/70 pt-3 text-xs">
                        <div className="min-w-0"><dt className="flex items-center gap-1 text-muted-foreground"><ArrowUpFromLine className="h-3 w-3" aria-hidden="true" />Передано</dt><dd className="mt-1 truncate font-medium text-foreground">{formatBytes(metrics?.network?.txTotalBytes)}</dd></div>
                        <div className="min-w-0"><dt className="flex items-center gap-1 text-muted-foreground"><ArrowDownToLine className="h-3 w-3" aria-hidden="true" />Получено</dt><dd className="mt-1 truncate font-medium text-foreground">{formatBytes(metrics?.network?.rxTotalBytes)}</dd></div>
                    </dl>
                </MetricCard>
            </section>

            <section aria-labelledby="service-checks-title" className="space-y-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                        <div className="flex flex-wrap items-center gap-2">
                            <h2 id="service-checks-title" className="text-lg font-semibold tracking-tight text-foreground">Проверки сервисов</h2>
                            <Badge variant="outline" className="rounded-full px-2 normal-case tracking-normal">{observedNodes.length} получено</Badge>
                        </div>
                        <p className="mt-1 text-sm text-muted-foreground">Статусы из `/monitoring/nodes`; выберите сервис, чтобы открыть его телеметрию.</p>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground" title="Автоматическое обновление с интервалом 10 секунд">
                        <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
                        <span>Обновлено: {formatTime(lastUpdated)}</span>
                        <span className="hidden text-border sm:inline" aria-hidden="true">·</span>
                        <span className="hidden sm:inline">Автообновление каждые 10 с</span>
                    </div>
                </div>

                <Card className="overflow-hidden rounded-xl border-border/80">
                    <div className="flex flex-col gap-3 border-b border-border/70 bg-muted/30 p-3 sm:flex-row sm:items-center sm:justify-between sm:px-4">
                        <div className="flex flex-wrap gap-1" role="group" aria-label="Фильтр состояния сервисов">
                            {filters.map((filter) => (
                                <Button key={filter.id} type="button" size="sm" variant={statusFilter === filter.id ? 'secondary' : 'ghost'} aria-pressed={statusFilter === filter.id} onClick={() => setStatusFilter(filter.id)} className="h-8 rounded-lg px-2.5 text-xs">
                                    {filter.label}<span className="ml-1.5 tabular-nums text-muted-foreground">{filter.count}</span>
                                </Button>
                            ))}
                        </div>
                        <label className="relative block w-full sm:max-w-xs">
                            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                            <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Поиск по имени, ID или типу" className="h-9 rounded-lg pl-9" aria-label="Поиск сервисов" />
                        </label>
                    </div>
                    <CardContent className="p-4 sm:p-5">
                        {nodesQuery.isLoading ? (
                            <p role="status" className="py-10 text-center text-sm text-muted-foreground">Получаем проверки сервисов…</p>
                        ) : nodesQuery.isError ? (
                            <p role="alert" className="rounded-lg border border-amber-300/70 bg-amber-50/60 p-4 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">Проверки сервисов не загружены или пришёл некорректный ответ. Статус здоровья не выводится из ошибки запроса.</p>
                        ) : observedNodes.length === 0 ? (
                            <div className="flex flex-col items-center py-10 text-center">
                                <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-border bg-muted text-muted-foreground"><Server className="h-5 w-5" /></span>
                                <p className="mt-3 text-sm font-medium text-foreground">Проверки не получены</p>
                                <p className="mt-1 max-w-md text-sm text-muted-foreground">Backend пока не вернул список сервисов. Пустой ответ не считается признаком исправности.</p>
                            </div>
                        ) : filteredNodes.length === 0 ? (
                            <p className="py-10 text-center text-sm text-muted-foreground">Ничего не найдено. Измените фильтр или поисковый запрос.</p>
                        ) : (
                            <ClusterHeatmap nodes={filteredNodes} />
                        )}
                    </CardContent>
                </Card>
            </section>

            <footer className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-border/70 pt-4 text-xs text-muted-foreground">
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                <span>Проверки инфраструктуры</span><span aria-hidden="true">·</span><span>10-секундный интервал</span><span aria-hidden="true">·</span><span>Источник: backend API</span>
            </footer>
        </main>
    );
}
