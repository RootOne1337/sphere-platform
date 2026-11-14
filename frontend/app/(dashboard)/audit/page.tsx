'use client';

import { Suspense, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, CircleHelp,
  Download, Loader2, RefreshCw, ShieldCheck,
  XCircle,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { AuditFiltersForm } from '@/src/features/audit/AuditFiltersForm';
import { isAuditRequestId, type AuditFilters } from '@/src/features/audit/investigation';
import { useAuditExport } from '@/src/features/audit/useAuditExport';
import { useAuthStore } from '@/lib/store';
import { AuditDrawer } from '@/src/features/audit/AuditDrawer';
import { normalizeAuditEvent, type AuditEvent, type AuditStatus } from '@/src/features/audit/types';
import { Badge } from '@/src/shared/ui/badge';
import { Button } from '@/src/shared/ui/button';
import { Card } from '@/components/ui/card';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';

const PAGE_SIZE = 100;
const EMPTY_EVENTS: AuditEvent[] = [];

function normalizeCursorPage(value: unknown) {
  if (!value || typeof value !== 'object' || !('items' in value) || !Array.isArray(value.items)
    || !('next_cursor' in value) || (value.next_cursor !== null && (
      typeof value.next_cursor !== 'string' || value.next_cursor.length === 0 || value.next_cursor.length > 512
    ))) {
    throw new Error('Backend вернул некорректный список событий аудита.');
  }
  return { items: value.items.map(normalizeAuditEvent), nextCursor: value.next_cursor };
}

function StatusMark({ status }: { status: AuditStatus }) {
  const config = {
    SUCCESS: { label: 'Успешно', icon: CheckCircle2, variant: 'success' as const },
    FAILED: { label: 'Ошибка', icon: XCircle, variant: 'destructive' as const },
    WARNING: { label: 'Предупреждение', icon: AlertTriangle, variant: 'warning' as const },
    UNKNOWN: { label: 'Не указано', icon: CircleHelp, variant: 'secondary' as const },
  }[status];
  const Icon = config.icon;

  return (
    <Badge variant={config.variant} className="gap-1.5 rounded-full px-2.5 py-1 font-medium">
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {config.label}
    </Badge>
  );
}

function formatTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(date);
}

export default function AuditLogsPage() {
  return <Suspense fallback={<p role="status" className="p-6">Загрузка журнала аудита…</p>}><AuditRoute /></Suspense>;
}

function AuditRoute() {
  const actor = useAuthStore(state => state.user);
  const version = useAuthStore(state => state.sessionVersion);
  const scope = `${actor?.id}:${actor?.org_id}:${actor?.role}:${version}`;
  const requestId = useSearchParams()?.get('request_id');
  const initialQuery = isAuditRequestId(requestId) ? `request:${requestId}` : '';
  return <AuditInvestigation key={`${scope}:${initialQuery}`} scope={scope} initialQuery={initialQuery} />;
}

function AuditInvestigation({ scope, initialQuery }: { scope: string; initialQuery: string }) {
  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);
  const [filters, setFilters] = useState<AuditFilters>(initialQuery ? { q: initialQuery } : {});
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const cursor = cursors[cursors.length - 1];
  const latest = cursor === null;
  const csv = useAuditExport();

  const auditQuery = useQuery({
    queryKey: ['audit-logs', scope, filters, cursor],
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/audit/logs/cursor', {
        params: { ...filters, per_page: PAGE_SIZE, ...(cursor ? { cursor } : {}) },
        signal,
      });
      return normalizeCursorPage(data);
    },
    staleTime: 15_000,
    refetchInterval: latest ? 30_000 : false,
    refetchOnWindowFocus: latest,
    refetchOnReconnect: latest,
    refetchIntervalInBackground: false,
  });
  const events = auditQuery.data?.items ?? EMPTY_EVENTS;
  const nextCursor = auditQuery.isError ? null : auditQuery.data?.nextCursor;

  const summary = useMemo(() => ({
    success: events.filter((event) => event.status === 'SUCCESS').length,
    failed: events.filter((event) => event.status === 'FAILED').length,
    warning: events.filter((event) => event.status === 'WARNING').length,
    unknown: events.filter((event) => event.status === 'UNKNOWN').length,
  }), [events]);

  const applyFilters = (params: AuditFilters) => {
    csv.cancel(); setSelectedEvent(null); setCursors([null]); setFilters(params);
  };

  const move = (direction: 'back' | 'forward') => {
    setSelectedEvent(null);
    setCursors(current => {
      if (current.at(-1) !== cursor) return current;
      if (direction === 'back') return current.slice(0, -1);
      return nextCursor ? [...current, nextCursor] : current;
    });
  };

  return (
    <PageFrame>
      <PageHeading
        eyebrow="Контроль изменений"
        title="Журнал аудита"
        description="Хронология действий пользователей и системных операций в пределах вашей организации. Записи поступают из backend; состояние доступа и ошибки запроса показываются отдельно."
        actions={(
          <>
            <Button variant="outline" onClick={() => {
              setSelectedEvent(null);
              if (latest) void auditQuery.refetch();
              else setCursors([null]);
            }} disabled={auditQuery.isFetching}>
              {auditQuery.isFetching ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              {latest ? 'Обновить' : 'К новым записям'}
            </Button>
            <Button onClick={() => csv.run(filters)} disabled={csv.pending || auditQuery.isFetching || auditQuery.isError || !auditQuery.data || (latest && events.length === 0)}>
              <Download className="mr-2 h-4 w-4" />
              Экспорт CSV

            </Button>
          </>
        )}
      />

      <section aria-label="Сводка журнала аудита" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div><p className="text-sm font-medium text-muted-foreground">Успешно</p><p className="mt-2 text-2xl font-semibold tabular-nums text-success">{auditQuery.isError ? '—' : summary.success}</p></div>
            <span className="rounded-xl bg-success/10 p-2.5 text-success"><CheckCircle2 className="h-5 w-5" /></span>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">На загруженной странице</p>
        </Card>
        <Card className="p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div><p className="text-sm font-medium text-muted-foreground">Ошибки</p><p className="mt-2 text-2xl font-semibold tabular-nums text-destructive">{auditQuery.isError ? '—' : summary.failed}</p></div>
            <span className="rounded-xl bg-destructive/10 p-2.5 text-destructive"><XCircle className="h-5 w-5" /></span>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">На загруженной странице · meta.status API</p>
        </Card>
        <Card className="p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div><p className="text-sm font-medium text-muted-foreground">Предупреждения</p><p className="mt-2 text-2xl font-semibold tabular-nums text-warning">{auditQuery.isError ? '—' : summary.warning}</p></div>
            <span className="rounded-xl bg-warning/10 p-2.5 text-warning"><AlertTriangle className="h-5 w-5" /></span>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">На загруженной странице</p>
        </Card>
        <Card className="p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div><p className="text-sm font-medium text-muted-foreground">Без результата</p><p className="mt-2 text-2xl font-semibold tabular-nums text-muted-foreground">{auditQuery.isError ? '—' : summary.unknown}</p></div>
            <span className="rounded-xl bg-muted p-2.5 text-muted-foreground"><CircleHelp className="h-5 w-5" /></span>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">В записи нет итогового статуса</p>
        </Card>
      </section>

      <Card className="overflow-visible">
        <AuditFiltersForm onApply={applyFilters} initialQuery={initialQuery} />
        {Object.keys(filters).length > 0 && <div className="border-b border-border px-5 py-3 text-xs text-muted-foreground">Применены: {Object.entries(filters).map(([key, value]) => `${key}=${value}`).join(' · ')}</div>}
        {csv.pending && <div role="status" className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3 text-sm"><Loader2 className="h-4 w-4 animate-spin" />Готовим CSV по применённым фильтрам…<Button variant="outline" size="sm" onClick={csv.cancel}>Отменить экспорт</Button></div>}
        {csv.error && <p role="alert" className="border-b border-border px-5 py-3 text-sm text-destructive">{csv.error}</p>}
        {csv.receipt && <div role="status" className="border-b border-border px-5 py-3 text-sm">
          Передан браузеру CSV: {csv.receipt.rows.toLocaleString('ru-RU')} событий · {formatTimestamp(csv.receipt.observedAt)}.
          {csv.receipt.truncated && <p className="mt-1 text-warning">Остальные события не включены: достигнут лимит 5 000. Сузьте диапазон времени или фильтры и повторите экспорт. Автоматического продолжения нет.</p>}
        </div>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[930px] table-fixed text-left">
            <thead className="sticky top-0 z-10 border-b border-border bg-muted/80 text-xs font-semibold text-muted-foreground backdrop-blur">
              <tr>
                <th scope="col" className="w-[168px] px-4 py-3 sm:px-5">Время</th>
                <th scope="col" className="w-[140px] px-4 py-3">Результат</th>
                <th scope="col" className="w-[180px] px-4 py-3">Действие</th>
                <th scope="col" className="w-[140px] px-4 py-3">Пользователь / ID</th>
                <th scope="col" className="w-[170px] px-4 py-3">Ресурс</th>
                <th scope="col" className="w-[130px] px-4 py-3">Источник / IP</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {auditQuery.isLoading && (
                <tr><td colSpan={6} className="px-5 py-16 text-center text-sm text-muted-foreground"><Loader2 className="mx-auto mb-3 h-5 w-5 animate-spin text-primary" />Загружаем журнал…</td></tr>
              )}
              {auditQuery.isError && (
                <tr><td colSpan={6} className="px-5 py-16 text-center" role="alert">
                  <div className="mx-auto max-w-md"><XCircle className="mx-auto mb-3 h-8 w-8 text-destructive" /><p className="font-medium">Не удалось загрузить журнал аудита</p><p className="mt-1 text-sm text-muted-foreground">Проверьте доступ audit:read и соединение с backend. Пустой список не подменяет ошибку запроса.</p><Button className="mt-4" variant="outline" onClick={() => auditQuery.refetch()}>Повторить запрос</Button></div>
                </td></tr>
              )}
              {!auditQuery.isLoading && !auditQuery.isError && events.map((event) => (
                <tr key={event.id} className="group cursor-pointer transition-colors hover:bg-muted/45 focus-within:bg-muted/45" onClick={() => setSelectedEvent(event)} onKeyDown={(keyEvent) => { if (keyEvent.key === 'Enter' || keyEvent.key === ' ') { keyEvent.preventDefault(); setSelectedEvent(event); } }} tabIndex={0} aria-label={`Открыть событие ${event.action}`}>
                  <td className="whitespace-nowrap px-4 py-3.5 text-sm tabular-nums text-muted-foreground sm:px-5">{formatTimestamp(event.timestamp)}</td>
                  <td className="px-4 py-3.5"><StatusMark status={event.status} /></td>
                  <td className="max-w-[250px] px-4 py-3.5"><span className="block truncate font-medium group-hover:text-primary">{event.action}</span><span className="mt-1 block truncate font-mono text-[11px] text-muted-foreground">{event.id}</span></td>
                  <td className="max-w-[180px] px-4 py-3.5"><span className="block truncate text-sm">{event.taskReceipt ? '—' : event.user}</span></td>
                  <td className="max-w-[220px] px-4 py-3.5 text-sm text-muted-foreground"><span className="block truncate">{event.resource}</span></td>
                  <td className="whitespace-nowrap px-4 py-3.5 text-sm text-muted-foreground">{event.taskReceipt ? 'Android-агент' : event.ip || '—'}</td>
                </tr>
              ))}
              {!auditQuery.isLoading && !auditQuery.isError && events.length === 0 && (
                <tr><td colSpan={6} className="px-5 py-16 text-center">
                  <div className="mx-auto max-w-md"><ShieldCheck className="mx-auto mb-3 h-8 w-8 text-muted-foreground/60" /><p className="font-medium">{Object.keys(filters).length ? 'По этим условиям событий нет' : 'В журнале пока нет событий'}</p><p className="mt-1 text-sm text-muted-foreground">{Object.keys(filters).length ? 'Измените запрос или сбросьте фильтры.' : 'После действий в системе новые записи появятся здесь.'}</p></div>
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        <footer className="flex flex-col gap-3 border-t border-border px-4 py-3 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <p>{auditQuery.isError ? 'Данные недоступны' : `На странице ${events.length} событий`}</p>
          <nav aria-label="Страницы журнала" className="flex items-center gap-2">
            <Button variant="outline" size="sm" aria-label="Предыдущая страница" disabled={latest || auditQuery.isFetching} onClick={() => move('back')}><ChevronLeft className="h-4 w-4" /><span className="sr-only">Предыдущая</span></Button>
            <span className="min-w-24 text-center text-xs tabular-nums" aria-live="polite">Страница {cursors.length}</span>
            <Button variant="outline" size="sm" aria-label="Следующая страница" disabled={!nextCursor || auditQuery.isFetching} onClick={() => move('forward')}><ChevronRight className="h-4 w-4" /><span className="sr-only">Следующая</span></Button>
            {latest && <span className="ml-1 hidden text-xs md:inline">Автообновление каждые 30 сек</span>}
          </nav>
        </footer>
      </Card>

      <AuditDrawer event={selectedEvent} onClose={() => setSelectedEvent(null)} />
    </PageFrame>
  );
}
