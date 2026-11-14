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
import { useCapabilities } from '@/src/features/access/Capabilities';
import { useFleetCoverage } from '@/src/features/monitoring/useFleetCoverage';
import { Badge } from '@/src/shared/ui/badge';
import { Button } from '@/src/shared/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/src/shared/ui/card';

interface SystemHealthResponse {
  status: string;
  version?: string;
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
      <CardContent className="flex min-h-24 items-start justify-between gap-2 p-3 sm:min-h-28 sm:p-[var(--panel-padding)]">
        <div className="min-w-0">
          <p className="text-xs font-medium text-muted-foreground sm:text-sm">{label}</p>
          <p className={`mt-2 text-2xl font-semibold tabular-nums tracking-tight ${tone}`}>{value}</p>
          <p className="mt-1 hidden text-xs text-muted-foreground sm:block">{detail}</p>
        </div>
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-border bg-background text-muted-foreground transition-colors group-hover:border-primary/30 group-hover:text-primary motion-reduce:transition-none sm:h-9 sm:w-9">
          <Icon className="h-4 w-4" aria-hidden="true" />
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

function EventRow({ event, canOpenDevice }: { event: DeviceEvent; canOpenDevice: boolean }) {
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
          {event.device_id && canOpenDevice && (
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
  const { query: fleet, snapshot, stale } = useFleetCoverage();
  const access = useCapabilities();
  const canReadVpn = access.can('vpn:read');
  const canReadEvents = access.canAccessRoute('/events');
  const canOpenDevices = access.canAccessRoute('/devices');
  const health = useSystemHealth();
  const pool = usePoolStats(canReadVpn);
  const vpnHealth = useVpnHealth(canReadVpn);
  const events = useDeviceEvents({ page: 1, per_page: 6, sort_by: 'occurred_at', sort_dir: 'desc' }, canReadEvents);
  const refreshing = fleet.isFetching || health.isFetching || events.isFetching
    || (canReadVpn && (pool.isFetching || vpnHealth.isFetching));
  const stats = snapshot?.presence.counts;
  const total = snapshot?.inventory.counts?.total;
  const serviceOk = health.data?.status === 'ok';
  const vpnOk = vpnHealth.data?.status === 'ok';
  const lastUpdated = snapshot?.inventory.observed_at
    ? `Каталог · ${formatDataUpdatedAt(Date.parse(snapshot.inventory.observed_at))}`
    : 'Ожидаем первую сводку от API';
  const presenceMessage = snapshot?.presence.state === 'limited' ? 'Инвентарь превышает бюджет сбора статусов.'
    : snapshot ? 'Источник связи с Android недоступен.' : fleet.isLoading ? 'Получаем сводку устройств…' : 'Свежая сводка связи не получена.';
  const recentSevereEvents = canReadEvents && !events.isError
    ? events.data?.items.filter(({ severity }) => severity === 'error' || severity === 'critical').length ?? 0 : 0;
  const attention = [
    { visible: !!stats?.error, label: `Ошибки связи · ${stats?.error}`, href: '/monitoring#fleet-coverage-title' },
    { visible: !!stats?.unknown, label: `Связь не подтверждена · ${stats?.unknown}`, href: '/monitoring#fleet-coverage-title' },
    { visible: canReadVpn && !pool.isError && (pool.data?.stale_handshakes ?? 0) > 0,
      label: `Устаревшие handshake VPN · ${pool.data?.stale_handshakes}`, href: '/vpn' },
    { visible: recentSevereEvents > 0, label: `Ошибки среди последних событий · ${recentSevereEvents}`, href: '/events' },
  ].filter(({ visible, href }) => visible && access.canAccessRoute(href));
  const freshnessSources: DataSourceSnapshot[] = [
    { id: 'fleet', label: 'Каталог устройств', pollIntervalMs: API_POLL_INTERVALS.fleetCoverageMs, hasData: total !== undefined, dataUpdatedAt: Date.parse(snapshot?.inventory.observed_at ?? '') || 0, isError: fleet.isError || stale || snapshot?.inventory.state === 'unavailable', isFetching: fleet.isFetching },
    { id: 'presence', label: 'Связь с Android', pollIntervalMs: API_POLL_INTERVALS.fleetCoverageMs, hasData: !!stats, dataUpdatedAt: Date.parse(snapshot?.presence.observed_at ?? '') || 0, isError: fleet.isError || stale || (!!snapshot && !stats), isFetching: fleet.isFetching },
    { id: 'backend-health', label: 'Health · backend', pollIntervalMs: API_POLL_INTERVALS.dashboardHealthMs, hasData: health.data !== undefined, dataUpdatedAt: health.dataUpdatedAt, isError: health.isError, isFetching: health.isFetching },
  ];
  if (canReadEvents) {
    freshnessSources.push({ id: 'events', label: 'Журнал событий', pollIntervalMs: API_POLL_INTERVALS.deviceEventsMs, hasData: events.data !== undefined, dataUpdatedAt: events.dataUpdatedAt, isError: events.isError, isFetching: events.isFetching });
  }
  if (canReadVpn) {
    freshnessSources.push(
      { id: 'vpn-health', label: 'Health · VPN', pollIntervalMs: API_POLL_INTERVALS.vpnHealthMs, hasData: vpnHealth.data !== undefined, dataUpdatedAt: vpnHealth.dataUpdatedAt, isError: vpnHealth.isError, isFetching: vpnHealth.isFetching },
      { id: 'vpn-pool', label: 'Пул VPN', pollIntervalMs: API_POLL_INTERVALS.vpnPoolStatsMs, hasData: pool.data !== undefined, dataUpdatedAt: pool.dataUpdatedAt, isError: pool.isError, isFetching: pool.isFetching },
    );
  }

  const refreshAll = async () => {
    await Promise.all([
      fleet.refetch(),
      health.refetch(),
      ...(canReadEvents ? [events.refetch()] : []),
      ...(canReadVpn ? [pool.refetch(), vpnHealth.refetch()] : []),
    ]);
  };

  return (
    <div className="mx-auto flex min-h-full w-full max-w-[1720px] flex-col gap-6 p-4 sm:p-6 xl:p-8">
      <header className="sphere-material sphere-panel flex flex-col gap-5 rounded-2xl border border-border bg-card p-5 shadow-sm sm:flex-row sm:items-end sm:justify-between sm:p-6">
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
          {canOpenDevices && <Button asChild className="h-10 rounded-lg">
            <Link href="/devices">Открыть реестр <ArrowRight className="ml-2 h-4 w-4" aria-hidden="true" /></Link>
          </Button>}
        </div>
      </header>

      {(fleet.isError || stale) && (
        <div role="alert" className="flex flex-col gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm sm:flex-row sm:items-center sm:justify-between">
          <span className="text-destructive">{stale && !fleet.isError ? 'Сводка устройств устарела.' : 'Не удалось получить сводку устройств.'} Предыдущие числа скрыты.</span>
          <Button type="button" variant="outline" size="sm" onClick={() => { void fleet.refetch(); }} disabled={fleet.isFetching}>Повторить</Button>
        </div>
      )}

      {attention.length > 0 && (
        <section aria-labelledby="dashboard-attention" className="rounded-xl border border-border bg-card px-5 py-4">
          <h2 id="dashboard-attention" className="text-sm font-semibold">Требуют проверки</h2>
          <div className="mt-2 flex flex-wrap gap-2">
            {attention.map(({ label, href }) => (
              <Button key={label} asChild variant="outline" size="sm">
                <Link href={href}>{label}<ArrowRight className="ml-2 h-3.5 w-3.5" aria-hidden="true" /></Link>
              </Button>
            ))}
          </div>
        </section>
      )}

      <section aria-label="Сводные показатели устройств" className="grid grid-cols-2 gap-2 xl:grid-cols-5">
        <MetricCard label="Всего устройств" value={total ?? '—'} detail="Активных записей в организации" icon={Smartphone} tone="text-foreground" />
        <MetricCard label="Онлайн" value={stats?.online ?? '—'} detail="Свежий heartbeat Android" icon={Wifi} tone="text-emerald-700 dark:text-emerald-400" />
        <MetricCard label="Выполняют задачи" value={stats?.busy ?? '—'} detail="Заняты по свежему отчёту Android" icon={Zap} tone="text-primary" />
        <MetricCard label="Не в сети" value={stats?.offline ?? '—'} detail="Получен статус offline" icon={WifiOff} tone="text-muted-foreground" />
        <MetricCard label="Не подтверждено" value={stats?.unknown ?? '—'} detail="Нет свежего подтверждения связи" icon={CircleAlert} tone="text-amber-700 dark:text-amber-400" />
      </section>

      <DataFreshnessPanel sources={freshnessSources} />

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-12" aria-label="Состояние и инфраструктура">
        <Card className="rounded-xl xl:col-span-7">
          <CardHeader className="flex flex-row items-start justify-between gap-4 border-0 p-5 pb-2">
            <div>
              <CardTitle className="font-sans text-base font-semibold normal-case tracking-tight text-foreground">Доступность парка</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">Распределение статусов из live-сводки backend</p>
            </div>
            <Badge variant="outline" className="rounded-full px-2.5 py-1 text-xs">{total == null ? fleet.isLoading ? 'Загрузка' : 'Инвентарь недоступен' : `${total} устройств`}</Badge>
          </CardHeader>
          <CardContent className="space-y-5 p-5 pt-3">
            {stats && total !== undefined ? <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <StatRow label="Онлайн" value={stats.online} total={total} tone="bg-emerald-500" />
              <StatRow label="В работе" value={stats.busy} total={total} tone="bg-primary" />
              <StatRow label="Подключаются" value={stats.connecting} total={total} tone="bg-amber-500" />
              <StatRow label="Не в сети" value={stats.offline} total={total} tone="bg-muted-foreground/50" />
              <StatRow label="Ошибка связи" value={stats.error} total={total} tone="bg-destructive" />
              <StatRow label="Не подтверждено" value={stats.unknown} total={total} tone="bg-amber-500" />
            </div> : <p role="status" className="text-sm text-muted-foreground">{presenceMessage}</p>}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
              <p className="text-xs text-muted-foreground">Значения обновляются автоматически каждые 15 секунд.</p>
              <Button asChild variant="outline" size="sm" className="rounded-lg">
                <Link href="/monitoring#fleet-coverage-title">Диагностика источника связи <ArrowRight className="ml-2 h-3.5 w-3.5" aria-hidden="true" /></Link>
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
            {canReadVpn ? <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-background/70 p-3">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted"><ShieldCheck className="h-4 w-4 text-muted-foreground" aria-hidden="true" /></span>
                <div className="min-w-0">
                  <p className="text-sm font-medium">VPN</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {pool.isError ? 'Сводка пула недоступна' : `${pool.data?.active_tunnels ?? '—'} активных по данным пула · ${pool.data?.stale_handshakes ?? '—'} устаревших handshake`}
                  </p>
                </div>
              </div>
              <Badge variant={vpnHealth.isError ? 'destructive' : vpnOk ? 'success' : 'warning'} className="rounded-full px-2.5 py-1 text-xs">
                {vpnHealth.isLoading ? 'Проверка' : vpnHealth.isError ? 'Недоступен' : vpnHealth.data?.status ?? 'Нет данных'}
              </Badge>
            </div> : <p className="text-xs text-muted-foreground">{access.verified ? 'Нет разрешения VPN.' : 'Доступ к сводке VPN не подтверждён.'}</p>}
            {(health.isError || (canReadVpn && (vpnHealth.isError || pool.isError))) && (
              <p className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-800 dark:text-amber-200">
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                Один или несколько health-запросов завершились ошибкой. Проверьте страницу инфраструктуры перед изменением конфигурации.
              </p>
            )}
            <div className="flex flex-wrap gap-2 pt-1">
              <Button asChild variant="outline" size="sm" className="rounded-lg"><Link href="/monitoring">Инфраструктура <ExternalLink className="ml-2 h-3.5 w-3.5" aria-hidden="true" /></Link></Button>
              {canReadVpn && access.canAccessRoute('/vpn') && <Button asChild variant="outline" size="sm" className="rounded-lg"><Link href="/vpn">Настройки VPN <ExternalLink className="ml-2 h-3.5 w-3.5" aria-hidden="true" /></Link></Button>}
            </div>
          </CardContent>
        </Card>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-12" aria-label="События и быстрые переходы">
        {canReadEvents && <Card className="rounded-xl xl:col-span-8">
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
                <div>{events.data?.items.map((event) => <EventRow key={event.id} event={event} canOpenDevice={canOpenDevices} />)}</div>
              </>
            </QueryState>
            {events.isFetching && !events.isLoading && <p className="pt-2 text-right text-xs text-muted-foreground" aria-live="polite">Проверяем обновления…</p>}
          </CardContent>
        </Card>}

        <Card className={canReadEvents ? 'rounded-xl xl:col-span-4' : 'rounded-xl xl:col-span-12'}>
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
            ].filter(({ href }) => access.canAccessRoute(href)).map(({ href, label, description, icon: Icon }) => (
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
