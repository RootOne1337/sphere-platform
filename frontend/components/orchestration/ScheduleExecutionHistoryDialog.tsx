'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { CatalogPagination } from '@/src/shared/ui/catalog-pagination';

interface Execution {
  id: string; schedule_id: string; status: string;
  fire_time: string; actual_time: string; finished_at?: string | null;
  devices_targeted: number; tasks_created: number; tasks_succeeded: number; tasks_failed: number;
  batch_id?: string | null; pipeline_batch_id?: string | null; skip_reason?: string | null;
}
interface ExecutionPage { items: Execution[]; total: number; page: number; per_page: number }
const PAGE_SIZE = 50;
const statusLabels: Record<string, string> = { triggered: 'Сработало', skipped: 'Пропущено', completed: 'Завершено', partial: 'Частичный результат', failed: 'Задачи завершились с ошибками' };

function validatePage(value: unknown, scheduleId: string, page: number): ExecutionPage {
  if (!value || typeof value !== 'object') throw new Error('Некорректная история срабатываний.');
  const data = value as ExecutionPage;
  if (!Array.isArray(data.items) || !Number.isInteger(data.total) || data.total < 0 || data.page !== page || data.per_page !== PAGE_SIZE) {
    throw new Error('Некорректная страница истории срабатываний.');
  }
  for (const item of data.items) {
    if (!item || typeof item.id !== 'string' || item.schedule_id !== scheduleId || typeof item.status !== 'string') throw new Error('История содержит запись другого расписания или некорректный ID.');
    for (const field of ['fire_time', 'actual_time'] as const) {
      if (typeof item[field] !== 'string' || !Number.isFinite(Date.parse(item[field]))) throw new Error('Некорректное время срабатывания.');
    }
    for (const field of ['devices_targeted', 'tasks_created', 'tasks_succeeded', 'tasks_failed'] as const) {
      if (!Number.isInteger(item[field]) || item[field] < 0) throw new Error('Некорректные счётчики истории.');
    }
    for (const field of ['finished_at', 'batch_id', 'pipeline_batch_id', 'skip_reason'] as const) {
      if (item[field] != null && typeof item[field] !== 'string') throw new Error('Некорректные сведения о срабатывании.');
    }
  }
  return data;
}

function timestamp(value?: string | null) {
  if (!value) return 'Не сообщено';
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? `${date.toISOString().replace('T', ' ').replace('Z', '')} UTC` : value;
}

function ExecutionHistory({ scheduleId }: { scheduleId: string }) {
  const [page, setPage] = useState(1);
  const history = useQuery({
    queryKey: ['schedule-executions', scheduleId, page],
    queryFn: async ({ signal }) => {
      const { data } = await api.get(`/schedules/${encodeURIComponent(scheduleId)}/executions`, { params: { page, per_page: PAGE_SIZE }, signal });
      return validatePage(data, scheduleId, page);
    },
    retry: false, refetchInterval: 30_000, refetchIntervalInBackground: false,
  });
  return <div className="min-w-0 space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
      <p className="break-all font-mono">Schedule ID: {scheduleId}</p>
      <Button variant="outline" size="sm" onClick={() => void history.refetch()} disabled={history.isFetching}>Обновить историю</Button>
    </div>
    <p className="text-xs text-muted-foreground">Время показано в UTC. Счётчики — отчёт backend, а не подтверждение текущего состояния Android. Открытая история обновляется каждые 30 секунд.</p>
    {history.isLoading ? <p role="status">Загружаем историю срабатываний…</p> : history.isError ? <div role="alert" className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
      <p>История не загружена. {history.error.message}</p>
      <Button variant="outline" size="sm" onClick={() => void history.refetch()} disabled={history.isFetching}>Повторить историю</Button>
    </div> : history.data && <>
      {!history.data.items.length ? <p className="rounded-lg border border-border p-6 text-sm text-muted-foreground">{history.data.total ? 'На этой странице нет срабатываний; вернитесь к предыдущей.' : 'Срабатываний пока нет.'}</p> : <div className="max-h-[55dvh] overflow-auto rounded-lg border border-border">
        <table className="w-full min-w-[760px] text-left text-sm">
          <thead className="sticky top-0 bg-muted"><tr>{['Плановое / фактическое время', 'Статус', 'Устройства', 'Создано задач', 'Успешно / ошибки', 'Сведения'].map(title => <th key={title} scope="col" className="px-3 py-3 font-medium">{title}</th>)}</tr></thead>
          <tbody className="divide-y divide-border">{history.data.items.map(execution => <tr key={execution.id}>
            <td className="px-3 py-3 text-xs tabular-nums"><time dateTime={execution.fire_time}>{timestamp(execution.fire_time)}</time><br /><time dateTime={execution.actual_time} className="text-muted-foreground">{timestamp(execution.actual_time)}</time></td>
            <td className="px-3 py-3"><Badge variant={execution.status === 'completed' ? 'success' : execution.status === 'failed' ? 'destructive' : ['skipped', 'partial'].includes(execution.status) ? 'warning' : 'secondary'}>{statusLabels[execution.status] ?? execution.status}</Badge></td>
            <td className="px-3 py-3 tabular-nums">{execution.devices_targeted}</td>
            <td className="px-3 py-3 tabular-nums">{execution.tasks_created}</td>
            <td className="px-3 py-3 tabular-nums">{execution.tasks_succeeded} / {execution.tasks_failed}</td>
            <td className="max-w-72 px-3 py-3"><details>
              <summary className="cursor-pointer text-xs text-primary">Сведения о срабатывании</summary>
              <dl className="mt-2 space-y-2 break-all text-xs">
                {[
                  ['ID', execution.id], ['Завершение', timestamp(execution.finished_at)], ['Task batch', execution.batch_id ?? 'Не сообщено'],
                  ['Pipeline batch', execution.pipeline_batch_id ?? 'Не сообщено'], ['Причина пропуска', execution.skip_reason ?? 'Не сообщено'],
                ].map(([label, value]) => <div key={label}><dt className="text-muted-foreground">{label}</dt><dd>{value}</dd></div>)}
              </dl>
            </details></td>
          </tr>)}</tbody>
        </table>
      </div>}
      <CatalogPagination page={page} perPage={PAGE_SIZE} total={history.data.total} busy={history.isFetching} label="срабатывания расписания" onPageChange={setPage} />
      <p className="text-xs text-muted-foreground">Снимок API: {new Date(history.dataUpdatedAt).toLocaleString('ru-RU')}{history.isFetching ? ' · обновляем…' : ''}</p>
    </>}
  </div>;
}

export function ScheduleExecutionHistoryDialog({ schedule, onClose }: { schedule: { id: string; name: string } | null; onClose: () => void }) {
  return <Dialog open={!!schedule} onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="max-w-5xl">
      <DialogHeader><DialogTitle>История срабатываний · {schedule?.name}</DialogTitle><DialogDescription>Отчёт сервера об отдельных запусках выбранного расписания.</DialogDescription></DialogHeader>
      {schedule && <ExecutionHistory key={schedule.id} scheduleId={schedule.id} />}
    </DialogContent>
  </Dialog>;
}
