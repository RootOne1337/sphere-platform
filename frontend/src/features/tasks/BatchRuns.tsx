'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { getApiErrorMessage } from '@/lib/apiError';
import { batchTargetStates, useBatch, useBatchList, useCancelBatch, type BatchSummary, type BatchTarget, type BatchTargetState } from '@/lib/hooks/useBatches';
import { useTasks } from '@/lib/hooks/useTasks';
import { useCapabilities } from '@/src/features/access/Capabilities';
import { Badge } from '@/src/shared/ui/badge';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';

const batchStatuses: Record<string, string> = {
  pending: 'Принят', running: 'Обрабатывается', completed: 'Завершён',
  partial: 'Частичный успех', failed: 'Завершён с ошибками', cancelled: 'Приём целей остановлен',
};

const targetLabels: Record<BatchTargetState, string> = {
  pending_admission: 'Ожидает допуска', queued: 'В очереди', assigned: 'Назначено',
  running: 'Выполняется', completed: 'Завершено', failed: 'Ошибка', timeout: 'Таймаут',
  cancelled: 'Отменено', rejected: 'Отказ до создания задачи',
  not_admitted_cancelled: 'Не принято после отмены', unknown: 'Исход не подтверждён',
};

const tableClass = 'w-full text-left text-sm';
const panelClass = 'overflow-x-auto rounded-xl border border-border bg-card';
const selectClass = 'h-9 rounded-md border border-input bg-background px-3 text-sm';
const time = (value?: string | null) => value ? new Date(value).toLocaleString() : '—';
const batchTitle = (batch: BatchSummary) => batch.name || batch.script_name || 'Пакет сценария';

export const batchHref = (id: string) => `/tasks?batch_id=${encodeURIComponent(id)}`;

function Pager({ page, pages, onPage }: { page: number; pages: number; onPage: (page: number) => void }) {
  return <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
    <Button variant="ghost" size="icon" aria-label="Предыдущая страница" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft className="size-4" /></Button>
    <span>{page} / {Math.max(1, pages)}</span>
    <Button variant="ghost" size="icon" aria-label="Следующая страница" disabled={page >= pages} onClick={() => onPage(page + 1)}><ChevronRight className="size-4" /></Button>
  </div>;
}

export function BatchRuns() {
  const [page, setPage] = useState(1);
  const list = useBatchList(page);
  return <main className="mx-auto max-w-screen-2xl space-y-5 px-4 py-6 sm:px-8">
    <Button variant="outline" asChild><Link href="/tasks">История заданий</Link></Button>
    <h1 className="text-2xl font-semibold tracking-tight">Пакетные запуски</h1>
    <p className="text-sm text-muted-foreground">Откройте пакет, чтобы увидеть волны, результаты по целям и связанные задания.</p>
    {list.isError ? <div role="alert" className="space-y-2">
      <p>Не удалось загрузить пакеты.</p>
      <Button variant="outline" onClick={() => void list.refetch()}>Повторить загрузку</Button>
    </div> : list.isPending ? <p role="status">Загрузка пакетов…</p> : <>
      {list.data.items.length === 0 && <p className="text-sm text-muted-foreground">{page === 1 ? 'Пакетных запусков пока нет.' : 'На этой странице нет пакетов.'}</p>}
      {list.data.items.length > 0 && <div className={panelClass}>
        <table className={`${tableClass} min-w-[620px]`}>
          <thead className="bg-muted/60"><tr>
            <th className="p-3">Пакет</th><th className="p-3">Статус</th>
            <th className="p-3">Цели / волны</th><th className="p-3">Создан</th>
          </tr></thead>
          <tbody className="divide-y divide-border">{list.data.items.map(batch => <tr key={batch.id}>
            <td className="p-3"><Link className="font-semibold text-primary hover:underline" href={batchHref(batch.id)} prefetch={false}>{batchTitle(batch)}</Link>
              <span className="block font-mono text-xs text-muted-foreground">{batch.id}</span></td>
            <td className="p-3"><Badge variant="outline">{batchStatuses[batch.status] ?? batch.status}</Badge></td>
            <td className="p-3 tabular-nums">{batch.total} / {batch.wave_count ?? '—'}</td>
            <td className="p-3">{time(batch.created_at)}</td>
          </tr>)}</tbody>
        </table>
      </div>}
      <Pager page={page} pages={list.data.pages} onPage={setPage} />
    </>}
  </main>;
}

export function BatchRun({ id }: { id: string }) {
  const query = useBatch(id);
  const cancellation = useCancelBatch();
  const access = useCapabilities();
  const [confirm, setConfirm] = useState(false);
  const [notice, setNotice] = useState('');
  const batch = query.data;
  const canCancel = access.can('script:execute') && query.isSuccess && batch
    && ['pending', 'running'].includes(batch.status) && !cancellation.isPending;
  const status = (query.error as { response?: { status?: number } } | null)?.response?.status;

  return <main className="mx-auto max-w-screen-2xl space-y-5 px-4 py-6 sm:px-8">
    <Button variant="outline" asChild><Link href="/tasks?view=batches">Все пакеты</Link></Button>
    {query.isError ? <div role="alert" className="space-y-2">
      <h1 className="text-xl font-semibold">{status === 404 ? 'Пакет не найден' : 'Не удалось загрузить пакет'}</h1>
      <Button variant="outline" onClick={() => void query.refetch()}>Повторить загрузку</Button>
    </div> : !batch ? <p role="status">Загрузка пакета…</p> : <>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <h1 className="break-words text-2xl font-semibold tracking-tight">{batchTitle(batch)}</h1>
          <p className="break-all font-mono text-xs text-muted-foreground">{batch.id}</p>
        </div>
        {canCancel && <Button variant="outline" onClick={() => { setNotice(''); setConfirm(true); }}>Остановить пакет</Button>}
      </header>
      <dl className="grid gap-4 rounded-xl border border-border bg-card p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div><dt className="text-muted-foreground">Пакет</dt><dd>{batchStatuses[batch.status] ?? batch.status}</dd></div>
        <div><dt className="text-muted-foreground">Цели</dt><dd className="tabular-nums">{batch.total}</dd></div>
        <div><dt className="text-muted-foreground">Волны</dt><dd className="tabular-nums">{batch.wave_count == null ? 'План недоступен' : `${batch.next_wave_index ?? 0} из ${batch.wave_count} обработано`}</dd></div>
        <div><dt className="text-muted-foreground">Версия сценария</dt><dd className="break-all font-mono text-xs">{batch.script_version_id ?? 'Не сохранена в пакете'}</dd></div>
        {batch.next_wave_at && <div><dt className="text-muted-foreground">Следующая волна не раньше</dt><dd>{time(batch.next_wave_at)}</dd></div>}
      </dl>
      {notice && <p role="status" className="text-sm">{notice}</p>}
      {batch.admission_state === 'review_required' && <p role="alert" className="text-sm text-destructive">Допуск остановлен. План требует проверки по ID пакета.</p>}
      {batch.targets == null
        ? <LegacyBatchTasks batchId={id} />
        : <BatchTargets targets={batch.targets} counts={batch.target_counts} />}
    </>}
    <Dialog open={confirm} onOpenChange={open => { if (!cancellation.isPending) setConfirm(open); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Остановить пакет?</DialogTitle>
          <DialogDescription>Новые волны остановятся, задачи в очереди будут отменены. Назначенные задачи получат запрос остановки. Уже выполняющиеся могут завершиться.</DialogDescription>
        </DialogHeader>
        {cancellation.isError && <p role="alert" className="text-sm text-destructive">{getApiErrorMessage(cancellation.error, 'Остановка не подтверждена. Обновите состояние пакета перед повтором.')}</p>}
        <DialogFooter>
          <Button variant="outline" disabled={cancellation.isPending} onClick={() => setConfirm(false)}>Вернуться</Button>
          <Button variant="destructive" disabled={!canCancel} onClick={() => cancellation.mutate(id, {
            onSuccess: () => { setConfirm(false); setNotice('Остановка пакета принята. Проверяйте итог отдельно по каждой задаче.'); },
            onError: () => { void query.refetch(); },
          })}>{cancellation.isPending ? 'Отправляем…' : 'Подтвердить остановку'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </main>;
}

function BatchTargets({ targets, counts }: { targets: BatchTarget[]; counts: Partial<Record<BatchTargetState, number>> | null }) {
  const [search, setSearch] = useState('');
  const [state, setState] = useState('');
  const [wave, setWave] = useState('');
  const [page, setPage] = useState(1);
  const needle = search.trim().toLocaleLowerCase();
  const waves = [...new Set(targets.map(target => target.wave_index))].sort((a, b) => a - b);
  const filtered = targets.filter(target => (!state || target.state === state)
    && (!wave || String(target.wave_index) === wave)
    && (!needle || [target.device_name, target.device_id, target.task_id].some(value => value?.toLocaleLowerCase().includes(needle))));
  const pages = Math.max(1, Math.ceil(filtered.length / 25));
  const currentPage = Math.min(page, pages);

  return <section className="space-y-4" aria-label="Результаты по целям">
    <h2 className="text-lg font-semibold">Результаты по целям</h2>
    {counts && <dl className="flex flex-wrap gap-2" aria-label="Сводка состояний">
      {batchTargetStates.filter(value => counts[value] || value === 'completed').map(value => <div key={value} className="rounded-lg border border-border bg-card px-3 py-2">
        <dt className="text-xs text-muted-foreground">{targetLabels[value]}</dt>
        <dd className="text-lg font-semibold tabular-nums">{counts[value] ?? 0}</dd>
      </div>)}
    </dl>}
    <div className="flex flex-wrap gap-2">
      <Input className="h-9 w-full sm:w-72" aria-label="Поиск цели" placeholder="Устройство или ID" value={search} onChange={e => { setSearch(e.target.value); setPage(1); }} />
      <select className={selectClass} aria-label="Статус цели" value={state} onChange={e => { setState(e.target.value); setPage(1); }}>
        <option value="">Все статусы</option>{batchTargetStates.map(value => <option key={value} value={value}>{targetLabels[value]}</option>)}
      </select>
      <select className={selectClass} aria-label="Волна" value={wave} onChange={e => { setWave(e.target.value); setPage(1); }}>
        <option value="">Все волны</option>{waves.map(value => <option key={value} value={value}>Волна {value + 1}</option>)}
      </select>
    </div>
    <p className="text-sm text-muted-foreground">Найдено {filtered.length} из {targets.length} целей.</p>
    {filtered.length > 0 && <div className={panelClass}><table className={`${tableClass} min-w-[560px]`}>
      <thead className="bg-muted/60"><tr><th className="p-3">Устройство</th><th className="p-3">Волна</th><th className="p-3">Результат</th><th className="p-3">Задание</th></tr></thead>
      <tbody className="divide-y divide-border">
        {filtered.slice((currentPage - 1) * 25, currentPage * 25).map(target => <tr key={target.device_id}>
          <td className="p-3"><span className="font-medium">{target.device_name ?? 'Устройство'}</span>
            <span className="block break-all font-mono text-xs text-muted-foreground">{target.device_id}</span></td>
          <td className="p-3 tabular-nums">{target.wave_index + 1}</td>
          <td className="p-3">
            {targetLabels[target.state] ?? target.state}{target.admission_http_status && ` (HTTP ${target.admission_http_status})`}
            {target.cancel_requested_at && ['queued', 'assigned', 'running'].includes(target.state) &&
              <span className="block text-xs text-muted-foreground">{target.timeout_requested_at ? 'Срок истёк. Ожидается результат.' : 'Запрошена остановка. Ожидается результат.'}</span>}
          </td>
          <td className="p-3">{target.task_id ? <Link className="text-primary hover:underline" prefetch={false} href={`/tasks/${target.task_id}`} aria-label={`Открыть задание ${target.task_id}`}>Открыть</Link> : '—'}</td>
        </tr>)}
      </tbody>
    </table></div>}
    <Pager page={currentPage} pages={pages} onPage={setPage} />
  </section>;
}

function LegacyBatchTasks({ batchId }: { batchId: string }) {
  const [page, setPage] = useState(1);
  const tasks = useTasks({ batch_id: batchId, page, per_page: 25 });
  return <section className="space-y-3">
    <h2 className="text-lg font-semibold">Задания пакета</h2>
    <p className="text-sm text-muted-foreground">План волн и итог по всем целям для этого пакета недоступны. Ниже показаны сохранённые задания.</p>
    {tasks.isError ? <div role="alert" className="space-y-2">
      <p>Не удалось загрузить задания пакета.</p>
      <Button variant="outline" onClick={() => void tasks.refetch()}>Повторить загрузку</Button>
    </div> : tasks.isPending ? <p role="status">Загрузка заданий…</p> : <>
      <p className="text-sm text-muted-foreground">Найдено {tasks.data.total} заданий.</p>
      <ul className="divide-y divide-border rounded-xl border border-border bg-card">
        {tasks.data.items.map(task => <li key={task.id} className="flex flex-wrap justify-between gap-2 p-3 text-sm">
          <Link className="text-primary hover:underline" href={`/tasks/${task.id}`} prefetch={false}>{task.device_name ?? task.device_id}</Link>
          <span>{targetLabels[task.status as BatchTargetState] ?? task.status}</span>
        </li>)}
      </ul>
      <Pager page={page} pages={tasks.data.pages} onPage={setPage} />
    </>}
  </section>;
}
