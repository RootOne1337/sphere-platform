'use client';

import { useMemo, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, CircleHelp,
  Download, Loader2, RefreshCw, ShieldCheck,
  XCircle,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { AuditFiltersForm } from '@/src/features/audit/AuditFiltersForm';
import { type AuditFilters } from '@/src/features/audit/investigation';
import { useAuditExport } from '@/src/features/audit/useAuditExport';
import { useAuthStore } from '@/lib/store';
import { AuditDrawer } from '@/src/features/audit/AuditDrawer';
import { normalizeAuditResponse, type AuditEvent, type AuditStatus } from '@/src/features/audit/types';
import { Badge } from '@/src/shared/ui/badge';
import { Button } from '@/src/shared/ui/button';
import { Card } from '@/components/ui/card';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';

const PAGE_SIZE = 100;
const EMPTY_EVENTS: AuditEvent[] = [];

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
  const actor = useAuthStore(state => state.user);
  const version = useAuthStore(state => state.sessionVersion);
  const scope = `${actor?.id}:${actor?.org_id}:${actor?.role}:${version}`;
  return <AuditInvestigation key={scope} scope={scope} />;
}

function AuditInvestigation({ scope }: { scope: string }) {
  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);
  const [filters, setFilters] = useState<AuditFilters>({});
  const [page, setPage] = useState(1);
  const csv = useAuditExport();

  const auditQuery = useQuery({
    queryKey: ['audit-logs', scope, filters, page],
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/audit/logs', {
        params: { ...filters, page, per_page: PAGE_SIZE },
        signal,
      });
      return normalizeAuditResponse(data);
    },
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
  const events = auditQuery.data?.items ?? EMPTY_EVENTS;
  const total = auditQuery.data?.total ?? 0;
  const totalPages = auditQuery.data?.pages ?? 0;

  const filteredEvents = events;

  const summary = useMemo(() => ({
    success: events.filter((event) => event.status === 'SUCCESS').length,
    failed: events.filter((event) => event.status === 'FAILED').length,
    warning: events.filter((event) => event.status === 'WARNING').length,
    unknown: events.filter((event) => event.status === 'UNKNOWN').length,
  }), [events]);

  const applyFilters = (params: AuditFilters) => {
    csv.cancel(); setSelectedEvent(null); setPage(1); setFilters(params);
  };

  return (
    <PageFrame>
      <PageHeading
        eyebrow="Контроль изменений"
        title="Журнал аудита"
        description="Хронология действий пользователей и системных операций в пределах вашей организации. Записи поступают из backend; состояние доступа и ошибки запроса показываются отдельно."
        actions={(
          <>
            <Button variant="outline" onClick={() => auditQuery.refetch()} disabled={auditQuery.isFetching}>
              {auditQuery.isFetching ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
              Обновить
            </Button>
            <Button onClick={() => csv.run(filters)} disabled={csv.pending || auditQuery.isFetching || auditQuery.isError || !auditQuery.data || total === 0}>
              <Download className="mr-2 h-4 w-4" />
              Экспорт CSV

            </Button>
          </>
        )}
      />

      <section aria-label="Сводка журнала аудита" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Card className="p-4 sm:p-5">
          <div className="flex items-start justify-between gap-3">
            <div><p className="text-sm font-medium text-muted-foreground">Всего событий</p><p className="mt-2 text-2xl font-semibold tabular-nums">{auditQuery.isError ? '—' : total.toLocaleString('ru-RU')}</p></div>
            <span className="rounded-xl bg-primary/10 p-2.5 text-primary"><ShieldCheck className="h-5 w-5" /></span>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">Все события по применённым фильтрам</p>
        </Card>
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
        <AuditFiltersForm onApply={applyFilters} />
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
                <th scope="col" className="w-[130px] px-4 py-3">Источник</th>
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
              {!auditQuery.isLoading && !auditQuery.isError && filteredEvents.map((event) => (
                <tr key={event.id} className="group cursor-pointer transition-colors hover:bg-muted/45 focus-within:bg-muted/45" onClick={() => setSelectedEvent(event)} onKeyDown={(keyEvent) => { if (keyEvent.key === 'Enter' || keyEvent.key === ' ') { keyEvent.preventDefault(); setSelectedEvent(event); } }} tabIndex={0} aria-label={`Открыть событие ${event.action}`}>
                  <td className="whitespace-nowrap px-4 py-3.5 text-sm tabular-nums text-muted-foreground sm:px-5">{formatTimestamp(event.timestamp)}</td>
                  <td className="px-4 py-3.5"><StatusMark status={event.status} /></td>
                  <td className="max-w-[250px] px-4 py-3.5"><span className="block truncate font-medium group-hover:text-primary">{event.action}</span><span className="mt-1 block truncate font-mono text-[11px] text-muted-foreground">{event.id}</span></td>
                  <td className="max-w-[180px] px-4 py-3.5"><span className="block truncate text-sm">{event.user}</span></td>
                  <td className="max-w-[220px] px-4 py-3.5 text-sm text-muted-foreground"><span className="block truncate">{event.resource}</span></td>
                  <td className="whitespace-nowrap px-4 py-3.5 text-sm text-muted-foreground">{event.ip || '—'}</td>
                </tr>
              ))}
              {!auditQuery.isLoading && !auditQuery.isError && filteredEvents.length === 0 && (
                <tr><td colSpan={6} className="px-5 py-16 text-center">
                  <div className="mx-auto max-w-md"><ShieldCheck className="mx-auto mb-3 h-8 w-8 text-muted-foreground/60" /><p className="font-medium">{Object.keys(filters).length ? 'По этим условиям событий нет' : 'В журнале пока нет событий'}</p><p className="mt-1 text-sm text-muted-foreground">{Object.keys(filters).length ? 'Измените запрос или сбросьте фильтры.' : 'После действий в системе новые записи появятся здесь.'}</p></div>
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        <footer className="flex flex-col gap-3 border-t border-border px-4 py-3 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <p>{auditQuery.isError ? 'Данные недоступны' : `Показано ${filteredEvents.length} из ${events.length} на странице · по фильтрам ${total.toLocaleString('ru-RU')}`}</p>
          <nav aria-label="Страницы журнала" className="flex items-center gap-2">
            <Button variant="outline" size="sm" aria-label="Предыдущая страница" disabled={page <= 1 || auditQuery.isFetching} onClick={() => setPage((current) => Math.max(1, current - 1))}><ChevronLeft className="h-4 w-4" /><span className="sr-only">Предыдущая</span></Button>
            <span className="min-w-24 text-center text-xs tabular-nums">Страница {totalPages === 0 ? 0 : page} из {totalPages}</span>
            <Button variant="outline" size="sm" aria-label="Следующая страница" disabled={page >= totalPages || auditQuery.isFetching} onClick={() => setPage((current) => Math.min(totalPages, current + 1))}><ChevronRight className="h-4 w-4" /><span className="sr-only">Следующая</span></Button>
            <span className="ml-1 hidden text-xs md:inline">Автообновление: 30 сек · только пока страница открыта</span>
          </nav>
        </footer>
      </Card>

      <AuditDrawer event={selectedEvent} onClose={() => setSelectedEvent(null)} />
    </PageFrame>
  );
}
