'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  CircleAlert,
  Clock3,
  Cpu,
  ExternalLink,
  RefreshCw,
  Server,
  ShieldCheck,
  ShieldAlert,
  Smartphone,
  Wifi,
  WifiOff,
  Zap,
  type LucideIcon,
} from 'lucide-react';
import { api } from '@/lib/api';
import { useDeviceEvents, type DeviceEvent, type EventSeverity } from '@/lib/hooks/useDeviceEvents';
import { usePoolStats, useVpnHealth } from '@/lib/hooks/useVpn';
import { API_POLL_INTERVALS } from '@/lib/queryPollIntervals';
import { formatDataAge, formatDataUpdatedAt, getDataFreshness, type DataFreshnessState } from '@/src/features/dashboard/dataFreshness';
import { Badge } from '@/src/shared/ui/badge';
import { Button } from '@/src/shared/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/src/shared/ui/card';

interface FleetStats {
  total: number;
  online: number;
  busy: number;
  connecting: number;
  offline: number;
}

interface SystemHealthResponse {
  status: string;
  version?: string;
}

function useFleetStats() {
  return useQuery<FleetStats>({
    queryKey: ['dashboard', 'fleet'],
    queryFn: async () => {
      const { data } = await api.get('/devices/status/fleet');
      return data as FleetStats;
    },
    refetchInterval: API_POLL_INTERVALS.dashboardFleetMs,
    staleTime: 5_000,
  });
}

function useSystemHealth() {
  return useQuery<SystemHealthResponse>({
    queryKey: ['dashboard', 'health'],
    queryFn: async () => {
      const { data } = await api.get('/health');
      return data as SystemHealthResponse;
    },
    refetchInterval: API_POLL_INTERVALS.dashboardHealthMs,
    staleTime: 10_000,
  });
}

function formatTimestamp(timestamp: string | null | undefined) {
  if (!timestamp) return 'Время не указано';
  const date = new Date(timestamp);
  if (!Number.isFinite(date.getTime())) return 'Время не указано';
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function severityVariant(severity: EventSeverity): 'default' | 'secondary' | 'destructive' | 'outline' | 'success' | 'warning' {
  if (severity === 'critical' || severity === 'error') return 'destructive';
  if (severity === 'warning') return 'warning';
  if (severity === 'info') return 'secondary';
  return 'outline';
}

function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  tone,
}: {
  label: string;
  value: number | string;
  detail: string;
  icon: LucideIcon;
  tone: string;
}) {
  return (
    <Card className="group rounded-xl border-border/80 bg-card transition-colors hover:border-primary/30 motion-reduce:transition-none">
      <CardContent className="flex min-h-[128px] items-start justify-between gap-4 p-4 sm:p-5">
        <div className="min-w-0">
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          <p className={`mt-3 text-3xl font-semibold tabular-nums tracking-tight ${tone}`}>{value}</p>
          <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
        </div>
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-border bg-background text-muted-foreground transition-colors group-hover:border-primary/30 group-hover:text-primary motion-reduce:transition-none">
          <Icon className="h-5 w-5" aria-hidden="true" />
        </span>
      </CardContent>
    </Card>
  );
}

function StatRow({ label, value, total, tone }: { label: string; value: number; total: number; tone: string }) {
  const percentage = total > 0 ? Math.min(100, Math.max(0, (value / total) * 100)) : 0;
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_3rem] items-center gap-x-4 gap-y-2">
      <div className="flex min-w-0 items-center justify-between gap-3">
        <span className="truncate text-sm text-muted-foreground">{label}</span>
        <span className="font-mono text-sm font-semibold tabular-nums text-foreground">{value}</span>
      </div>
      <span className="text-right font-mono text-xs tabular-nums text-muted-foreground">{total > 0 ? `${Math.round(percentage)}%` : '—'}</span>
      <div className="col-span-2 h-2 overflow-hidden rounded-full bg-muted" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={Math.max(1, total)} aria-valuenow={value}>
        <div className={`h-full rounded-full transition-[width] duration-500 motion-reduce:transition-none ${tone}`} style={{ width: `${percentage}%` }} />
      </div>
    </div>
  );
}

function EventRow({ event }: { event: DeviceEvent }) {
  const eventLabel = event.event_type.replace(/[._]/g, ' ');
  const deviceHref = event.device_id ? `/devices/${encodeURIComponent(event.device_id)}` : '/events';

  return (
    <article className="grid grid-cols-[auto_minmax(0,1fr)] gap-3 border-b border-border/70 py-3 last:border-0">
      <span className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-lg bg-muted text-muted-foreground" aria-hidden="true">
        {event.severity === 'critical' || event.severity === 'error' ? <CircleAlert className="h-4 w-4 text-destructive" /> : <Activity className="h-4 w-4" />}
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={severityVariant(event.severity)} className="rounded-full px-2 py-0.5 text-[10px] tracking-wide">
            {event.severity}
          </Badge>
          <time dateTime={event.occurred_at} className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <Clock3 className="h-3 w-3" aria-hidden="true" />
            {formatTimestamp(event.occurred_at)}
          </time>
        </div>
        <p className="mt-1 truncate text-sm font-medium capitalize text-foreground" title={event.message || event.event_type}>
          {event.message || eventLabel}
        </p>
        <div className="mt-1 flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
          <span className="truncate">{event.device_name || eventLabel}</span>
          {event.device_id && (
            <Link href={deviceHref} className="shrink-0 rounded text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              Открыть
            </Link>
          )}
        </div>
      </div>
    </article>
  );
}

function QueryState({ loading, error, empty, children }: {
  loading: boolean;
  error: boolean;
  empty: boolean;
  children: React.ReactNode;
}) {
  if (loading) return <p role="status" className="py-8 text-center text-sm text-muted-foreground">Загружаем данные…</p>;
  if (error) return <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">Данные сейчас недоступны. Проверьте доступ к API.</p>;
  if (empty) return <p className="py-8 text-center text-sm text-muted-foreground">Пока нет событий для отображения.</p>;
  return children;
}

type DataSourceSnapshot = {
  id: string;
  label: string;
  pollIntervalMs: number;
  hasData: boolean;
  dataUpdatedAt: number;
  isError: boolean;
  isFetching: boolean;
};

const FRESHNESS_STYLES: Record<DataFreshnessState, string> = {
  waiting: 'border-border bg-muted text-muted-foreground',
  refreshing: 'border-sky-500/30 bg-sky-500/5 text-sky-700 dark:text-sky-300',
  fresh: 'border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-300',
  stale: 'border-amber-500/30 bg-amber-500/5 text-amber-800 dark:text-amber-200',
  error: 'border-destructive/30 bg-destructive/5 text-destructive',
};

function freshnessLabel(state: DataFreshnessState, hasData: boolean) {
  if (state === 'waiting') return 'Ожидаем ответ';
  if (state === 'refreshing') return 'Обновляется';
  if (state === 'fresh') return 'Актуален';
  if (state === 'stale') return 'Ответ устарел';
  return hasData ? 'Ошибка обновления' : 'Нет ответа';
}

function DataFreshnessPanel({ sources }: { sources: DataSourceSnapshot[] }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 10_000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <Card role="region" aria-label="Свежесть источников данных" className="rounded-xl border-border/80 shadow-sm">
      <CardHeader className="flex flex-col gap-2 border-0 p-5 pb-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <CardTitle className="font-sans text-base font-semibold normal-case tracking-tight text-foreground">Свежесть источников</CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">Время последнего успешного ответа API по каждому блоку обзора.</p>
        </div>
        <Badge variant="outline" className="w-fit rounded-full px-2.5 py-1 text-xs">Ответ браузера</Badge>
      </CardHeader>
      <CardContent className="space-y-3 p-5 pt-1">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-5">
          {sources.map((source) => {
            const freshness = getDataFreshness({ ...source, now });
            const hasData = source.hasData && source.dataUpdatedAt > 0;
            const updatedAt = hasData ? formatDataUpdatedAt(source.dataUpdatedAt) : 'Ещё не получено';
            return (
              <article key={source.id} className="min-w-0 rounded-lg border border-border bg-background/70 p-3">
                <div className="flex min-w-0 items-start justify-between gap-2">
                  <h3 className="min-w-0 text-xs font-semibold text-foreground">{source.label}</h3>
                  <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium ${FRESHNESS_STYLES[freshness.state]}`}>
                    {freshnessLabel(freshness.state, hasData)}
                  </span>
                </div>
                <p className="mt-2 break-words text-xs tabular-nums text-muted-foreground" title={hasData ? new Date(source.dataUpdatedAt).toISOString() : undefined}>
                  {updatedAt}
                </p>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {hasData ? `Последний успех · ${formatDataAge(freshness.ageMs)}` : source.isFetching ? 'Первый запрос выполняется' : 'Успешного ответа ещё нет'}
                  {' · опрос '}{source.pollIntervalMs / 1000} с
                </p>
              </article>
            );
          })}
        </div>
        <p className="text-xs leading-5 text-muted-foreground">
          Это время получения HTTP-ответа в браузере. Оно не подтверждает свежесть heartbeat устройства или видеокадра — для них проверяйте данные устройства и состояние потока.
        </p>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const fleet = useFleetStats();
  const health = useSystemHealth();
  const pool = usePoolStats();
  const vpnHealth = useVpnHealth();
  const events = useDeviceEvents({ page: 1, per_page: 6, sort_by: 'occurred_at', sort_dir: 'desc' });
  const refreshing = fleet.isFetching || health.isFetching || pool.isFetching || vpnHealth.isFetching || events.isFetching;
  const stats = fleet.data;
  const total = stats?.total ?? 0;
  const serviceOk = health.data?.status === 'ok';
  const vpnOk = vpnHealth.data?.status === 'ok';
  const lastUpdated = fleet.dataUpdatedAt
    ? `Каталог · ${formatDataUpdatedAt(fleet.dataUpdatedAt)}`
    : 'Ожидаем первую сводку от API';
  const freshnessSources: DataSourceSnapshot[] = [
    { id: 'fleet', label: 'Каталог устройств', pollIntervalMs: API_POLL_INTERVALS.dashboardFleetMs, hasData: fleet.data !== undefined, dataUpdatedAt: fleet.dataUpdatedAt, isError: fleet.isError, isFetching: fleet.isFetching },
    { id: 'backend-health', label: 'Health · backend', pollIntervalMs: API_POLL_INTERVALS.dashboardHealthMs, hasData: health.data !== undefined, dataUpdatedAt: health.dataUpdatedAt, isError: health.isError, isFetching: health.isFetching },
    { id: 'vpn-health', label: 'Health · VPN', pollIntervalMs: API_POLL_INTERVALS.vpnHealthMs, hasData: vpnHealth.data !== undefined, dataUpdatedAt: vpnHealth.dataUpdatedAt, isError: vpnHealth.isError, isFetching: vpnHealth.isFetching },
    { id: 'vpn-pool', label: 'Пул VPN', pollIntervalMs: API_POLL_INTERVALS.vpnPoolStatsMs, hasData: pool.data !== undefined, dataUpdatedAt: pool.dataUpdatedAt, isError: pool.isError, isFetching: pool.isFetching },
    { id: 'events', label: 'Журнал событий', pollIntervalMs: API_POLL_INTERVALS.deviceEventsMs, hasData: events.data !== undefined, dataUpdatedAt: events.dataUpdatedAt, isError: events.isError, isFetching: events.isFetching },
  ];

  const refreshAll = async () => {
    await Promise.all([
      fleet.refetch(),
      health.refetch(),
      pool.refetch(),
      vpnHealth.refetch(),
      events.refetch(),
    ]);
  };

  return (
    <div className="mx-auto flex min-h-full w-full max-w-[1720px] flex-col gap-6 p-4 sm:p-6 xl:p-8">
      <header className="flex flex-col gap-5 rounded-2xl border border-border bg-card p-5 shadow-sm sm:flex-row sm:items-end sm:justify-between sm:p-6">
        <div className="min-w-0">
          <p className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.13em] text-primary"><span className="h-2 w-2 rounded-full bg-primary" aria-hidden="true" />Операционный центр</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">Обзор парка</h1>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">Состояние устройств и инфраструктуры по последним данным API.</p>
          <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground"><Clock3 className="h-3.5 w-3.5" aria-hidden="true" />{lastUpdated} · интервалы опроса по источникам ниже</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" onClick={() => { void refreshAll(); }} disabled={refreshing} aria-live="polite" className="h-10 rounded-lg">
            <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
            {refreshing ? 'Обновляем…' : 'Обновить данные'}
          </Button>
          <Button asChild className="h-10 rounded-lg">
            <Link href="/devices">Открыть реестр <ArrowRight className="ml-2 h-4 w-4" aria-hidden="true" /></Link>
          </Button>
        </div>
      </header>

      {fleet.isError && (
        <div role="alert" className="flex flex-col gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm sm:flex-row sm:items-center sm:justify-between">
          <span className="text-destructive">Не удалось получить сводку устройств. Отображаются последние подтверждённые данные, если они есть.</span>
          <Button type="button" variant="outline" size="sm" onClick={() => { void fleet.refetch(); }} disabled={fleet.isFetching}>Повторить</Button>
        </div>
      )}

      <section aria-label="Сводные показатели устройств" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="Всего устройств" value={fleet.isLoading ? '—' : stats?.total ?? '—'} detail="Записей в организации" icon={Smartphone} tone="text-foreground" />
        <MetricCard label="Онлайн" value={fleet.isLoading ? '—' : stats?.online ?? '—'} detail="Статус online по API" icon={Wifi} tone="text-emerald-700 dark:text-emerald-400" />
        <MetricCard label="Выполняют задачи" value={fleet.isLoading ? '—' : stats?.busy ?? '—'} detail="Busy по статусу API" icon={Zap} tone="text-primary" />
        <MetricCard label="Подключаются" value={fleet.isLoading ? '—' : stats?.connecting ?? '—'} detail="Ждут первый heartbeat" icon={ArrowUpRight} tone="text-amber-700 dark:text-amber-400" />
        <MetricCard label="Не в сети" value={fleet.isLoading ? '—' : stats?.offline ?? '—'} detail="Нет живого статуса" icon={WifiOff} tone="text-muted-foreground" />
      </section>

      <DataFreshnessPanel sources={freshnessSources} />

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-12" aria-label="Состояние и инфраструктура">
        <Card className="rounded-xl xl:col-span-7">
          <CardHeader className="flex flex-row items-start justify-between gap-4 border-0 p-5 pb-2">
            <div>
              <CardTitle className="font-sans text-base font-semibold normal-case tracking-tight text-foreground">Доступность парка</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">Распределение статусов из live-сводки backend</p>
            </div>
            <Badge variant="outline" className="rounded-full px-2.5 py-1 text-xs">{fleet.isLoading ? 'Загрузка' : `${total} устройств`}</Badge>
          </CardHeader>
          <CardContent className="space-y-5 p-5 pt-3">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <StatRow label="Онлайн" value={stats?.online ?? 0} total={total} tone="bg-emerald-500" />
              <StatRow label="В работе" value={stats?.busy ?? 0} total={total} tone="bg-primary" />
              <StatRow label="Подключаются" value={stats?.connecting ?? 0} total={total} tone="bg-amber-500" />
              <StatRow label="Не в сети" value={stats?.offline ?? 0} total={total} tone="bg-muted-foreground/50" />
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
              <p className="text-xs text-muted-foreground">Значения обновляются автоматически каждые 15 секунд.</p>
              <Button asChild variant="outline" size="sm" className="rounded-lg">
                <Link href="/devices">Диагностика устройств <ArrowRight className="ml-2 h-3.5 w-3.5" aria-hidden="true" /></Link>
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-xl xl:col-span-5">
          <CardHeader className="border-0 p-5 pb-2">
            <CardTitle className="font-sans text-base font-semibold normal-case tracking-tight text-foreground">Инфраструктура</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">Результаты health endpoints backend и VPN</p>
          </CardHeader>
          <CardContent className="space-y-3 p-5 pt-3">
            <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-background/70 p-3">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted"><Server className="h-4 w-4 text-muted-foreground" aria-hidden="true" /></span>
                <div className="min-w-0">
                  <p className="text-sm font-medium">Backend API</p>
                  <p className="truncate text-xs text-muted-foreground">{health.data?.version ? `Версия ${health.data.version}` : 'Версия не сообщена'}</p>
                </div>
              </div>
              <Badge variant={health.isError ? 'destructive' : serviceOk ? 'success' : 'warning'} className="rounded-full px-2.5 py-1 text-xs">
                {health.isLoading ? 'Проверка' : health.isError ? 'Недоступен' : health.data?.status ?? 'Нет данных'}
              </Badge>
            </div>
            <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-background/70 p-3">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted"><ShieldCheck className="h-4 w-4 text-muted-foreground" aria-hidden="true" /></span>
                <div className="min-w-0">
                  <p className="text-sm font-medium">VPN</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {pool.isError ? 'Сводка пула недоступна' : `${pool.data?.active_tunnels ?? '—'} активных туннелей · ${pool.data?.stale_handshakes ?? '—'} устаревших handshake`}
                  </p>
                </div>
              </div>
              <Badge variant={vpnHealth.isError ? 'destructive' : vpnOk ? 'success' : 'warning'} className="rounded-full px-2.5 py-1 text-xs">
                {vpnHealth.isLoading ? 'Проверка' : vpnHealth.isError ? 'Недоступен' : vpnHealth.data?.status ?? 'Нет данных'}
              </Badge>
            </div>
            {(health.isError || vpnHealth.isError || pool.isError) && (
              <p className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-800 dark:text-amber-200">
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                Один или несколько health-запросов завершились ошибкой. Проверьте страницу инфраструктуры перед изменением конфигурации.
              </p>
            )}
            <div className="flex flex-wrap gap-2 pt-1">
              <Button asChild variant="outline" size="sm" className="rounded-lg"><Link href="/monitoring">Инфраструктура <ExternalLink className="ml-2 h-3.5 w-3.5" aria-hidden="true" /></Link></Button>
              <Button asChild variant="outline" size="sm" className="rounded-lg"><Link href="/vpn">Настройки VPN <ExternalLink className="ml-2 h-3.5 w-3.5" aria-hidden="true" /></Link></Button>
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-12" aria-label="События и быстрые переходы">
        <Card className="rounded-xl xl:col-span-8">
          <CardHeader className="flex flex-row items-center justify-between gap-4 border-0 p-5 pb-2">
            <div>
              <CardTitle className="font-sans text-base font-semibold normal-case tracking-tight text-foreground">Последние события</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">Журнал устройств, отсортированный backend по времени события</p>
            </div>
            <Button asChild variant="ghost" size="sm" className="shrink-0 rounded-lg text-primary"><Link href="/events">Все события <ArrowRight className="ml-2 h-3.5 w-3.5" aria-hidden="true" /></Link></Button>
          </CardHeader>
          <CardContent className="px-5 pb-5 pt-1">
            <QueryState loading={events.isLoading} error={events.isError && !events.data} empty={!events.data?.items.length}>
              <>
                {events.isError && events.data && <p role="status" className="mb-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-2 text-xs text-amber-800 dark:text-amber-200">Не удалось обновить журнал; показаны последние полученные события.</p>}
                <div>{events.data?.items.map((event) => <EventRow key={event.id} event={event} />)}</div>
              </>
            </QueryState>
            {events.isFetching && !events.isLoading && <p className="pt-2 text-right text-xs text-muted-foreground" aria-live="polite">Проверяем обновления…</p>}
          </CardContent>
        </Card>

        <Card className="rounded-xl xl:col-span-4">
          <CardHeader className="border-0 p-5 pb-2">
            <CardTitle className="font-sans text-base font-semibold normal-case tracking-tight text-foreground">Рабочие разделы</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">Переходы ведут к существующим страницам Sphere</p>
          </CardHeader>
          <CardContent className="space-y-2 p-5 pt-3">
            {[
              { href: '/devices', label: 'Реестр устройств', description: 'Статусы, фильтры и операции', icon: Smartphone },
              { href: '/stream', label: 'Просмотр потоков', description: 'Открыть Device Stream', icon: Activity },
              { href: '/tasks', label: 'Задания', description: 'История и исполнение задач', icon: Cpu },
              { href: '/updates', label: 'Обновления', description: 'Каталог версий и OTA', icon: ArrowDownRight },
            ].map(({ href, label, description, icon: Icon }) => (
              <Link key={href} href={href} className="group flex items-center gap-3 rounded-lg border border-transparent p-3 transition-colors hover:border-border hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground transition-colors group-hover:text-primary motion-reduce:transition-none"><Icon className="h-4 w-4" aria-hidden="true" /></span>
                <span className="min-w-0 flex-1"><span className="block text-sm font-medium text-foreground">{label}</span><span className="mt-0.5 block truncate text-xs text-muted-foreground">{description}</span></span>
                <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary motion-reduce:transition-none" aria-hidden="true" />
              </Link>
            ))}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
