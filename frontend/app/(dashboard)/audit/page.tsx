'use client';

import { useMemo, useState } from 'react';
import {
  AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, CircleHelp,
  Download, Filter, Loader2, RefreshCw, ShieldCheck,
  XCircle,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { AuditQueryBuilder } from '@/src/features/audit/AuditQueryBuilder';
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

function safeCsvCell(value: string) {
  const safe = /^[\s]*[=+\-@]/.test(value) ? `'${value}` : value;
  return `"${safe.replace(/"/g, '""')}"`;
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
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filterStatus, setFilterStatus] = useState<AuditStatus | ''>('');
  const [filterAction, setFilterAction] = useState('');
  const [filterUser, setFilterUser] = useState('');
  const [page, setPage] = useState(1);

  const auditQuery = useQuery({
    queryKey: ['audit-logs', page],
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/audit/logs', {
        params: { page, per_page: PAGE_SIZE },
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

  const uniqueActions = useMemo(() => [...new Set(events.map((event) => event.action))].sort(), [events]);
  const uniqueUsers = useMemo(() => [...new Set(events.map((event) => event.user))].sort(), [events]);
  const filteredEvents = useMemo(() => {
    let result = events;
    if (filterStatus) result = result.filter((event) => event.status === filterStatus);
    if (filterAction) result = result.filter((event) => event.action === filterAction);
    if (filterUser) result = result.filter((event) => event.user === filterUser);
    if (!searchQuery.trim()) return result;

    const terms = searchQuery.toLowerCase().split(/\s+/).filter(Boolean);
    return result.filter((event) => terms.every((term) => {
      if (term.includes(':')) {
        const [key, ...parts] = term.split(':');
        const value = parts.join(':');
        if (key === 'status') return event.status.toLowerCase() === value;
        if (key === 'action') return event.action.toLowerCase().includes(value);
        if (key === 'user') return event.user.toLowerCase().includes(value);
      }
      return [event.id, event.timestamp, event.user, event.action, event.resource, event.ip]
        .join(' ').toLowerCase().includes(term);
    }));
  }, [events, searchQuery, filterStatus, filterAction, filterUser]);

  const summary = useMemo(() => ({
    success: events.filter((event) => event.status === 'SUCCESS').length,
    failed: events.filter((event) => event.status === 'FAILED').length,
    warning: events.filter((event) => event.status === 'WARNING').length,
    unknown: events.filter((event) => event.status === 'UNKNOWN').length,
  }), [events]);

  const exportCsv = () => {
    if (!filteredEvents.length) return;
    const rows = [
      ['Время', 'Результат', 'Действие', 'Пользователь', 'Ресурс', 'IP', 'ID события'],
      ...filteredEvents.map((event) => [
        event.timestamp, event.status, event.action, event.user, event.resource, event.ip, event.id,
      ]),
    ];
    const csv = `\uFEFF${rows.map((row) => row.map(safeCsvCell).join(';')).join('\r\n')}`;
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `sphere-audit-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  const clearFilters = () => {
    setFilterStatus('');
    setFilterAction('');
    setFilterUser('');
    setSearchQuery('');
  };
  const hasFilters = Boolean(filterStatus || filterAction || filterUser || searchQuery.trim());

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
            <Button onClick={exportCsv} disabled={filteredEvents.length === 0}>
              <Download className="mr-2 h-4 w-4" />
              Экспорт CSV
              {filteredEvents.length > 0 && <span className="ml-1 tabular-nums">({filteredEvents.length})</span>}
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
          <p className="mt-3 text-xs text-muted-foreground">Общее число в журнале backend</p>
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
          <p className="mt-3 text-xs text-muted-foreground">Согласно meta.status API</p>
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
        <div className="flex flex-col gap-3 border-b border-border p-4 sm:p-5 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0 flex-1"><AuditQueryBuilder value={searchQuery} onChange={setSearchQuery} /></div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant={filtersOpen ? 'secondary' : 'outline'} onClick={() => setFiltersOpen((open) => !open)} aria-expanded={filtersOpen}>
              <Filter className="mr-2 h-4 w-4" />
              Фильтры
              {hasFilters && <span className="ml-2 h-2 w-2 rounded-full bg-primary" aria-label="Есть активные фильтры" />}
            </Button>
            {hasFilters && <Button variant="ghost" onClick={clearFilters}>Сбросить</Button>}
          </div>
        </div>

        {filtersOpen && (
          <div className="grid gap-3 border-b border-border bg-muted/30 p-4 sm:grid-cols-2 sm:p-5 xl:grid-cols-4" aria-label="Фильтры журнала">
            <label className="grid gap-1.5 text-sm font-medium">Результат
              <select value={filterStatus} onChange={(event) => setFilterStatus(event.target.value as AuditStatus | '')} className="h-10 rounded-lg border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <option value="">Все результаты</option><option value="SUCCESS">Успешно</option><option value="FAILED">Ошибка</option><option value="WARNING">Предупреждение</option><option value="UNKNOWN">Не указано</option>
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-medium">Действие
              <select value={filterAction} onChange={(event) => setFilterAction(event.target.value)} className="h-10 rounded-lg border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <option value="">Все действия</option>{filterAction && !uniqueActions.includes(filterAction) && <option value={filterAction}>{filterAction}</option>}{uniqueActions.map((action) => <option key={action} value={action}>{action}</option>)}
              </select>
            </label>
            <label className="grid gap-1.5 text-sm font-medium">Пользователь
              <select value={filterUser} onChange={(event) => setFilterUser(event.target.value)} className="h-10 rounded-lg border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <option value="">Все пользователи</option>{filterUser && !uniqueUsers.includes(filterUser) && <option value={filterUser}>{filterUser}</option>}{uniqueUsers.map((user) => <option key={user} value={user}>{user}</option>)}
              </select>
            </label>
            <div className="flex items-end text-xs leading-5 text-muted-foreground"><CircleHelp className="mr-2 h-4 w-4 shrink-0" />Фильтры и поиск применяются к загруженной странице. Стрелки ниже загружают остальные записи.</div>
          </div>
        )}

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
                  <div className="mx-auto max-w-md"><ShieldCheck className="mx-auto mb-3 h-8 w-8 text-muted-foreground/60" /><p className="font-medium">{events.length ? 'По этим условиям событий нет' : 'В журнале пока нет событий'}</p><p className="mt-1 text-sm text-muted-foreground">{events.length ? 'Измените запрос или сбросьте фильтры.' : 'После действий в системе новые записи появятся здесь.'}</p></div>
                </td></tr>
              )}
            </tbody>
          </table>
        </div>

        <footer className="flex flex-col gap-3 border-t border-border px-4 py-3 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-5">
          <p>{auditQuery.isError ? 'Данные недоступны' : `Показано ${filteredEvents.length} из ${events.length} на странице · всего ${total.toLocaleString('ru-RU')}`}</p>
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
