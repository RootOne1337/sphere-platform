'use client';

import { Suspense, useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { ListTodo, Play, Clock, CalendarClock, ShieldAlert, CheckCircle2, Workflow, ChevronLeft, ChevronRight, RotateCcw, Radio, Loader2 } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';
import { Badge } from '@/src/shared/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';

import { useTasks, useRetryTask, type Task } from '@/lib/hooks/useTasks';
import { executionStatusLabel } from '@/lib/task-status';
import { useActivePipelineRuns } from '@/lib/hooks/usePipelineRuns';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { useBroadcastBatch } from '@/lib/hooks/useBatches';
import { useScripts, type Script } from '@/lib/hooks/useScripts';
import { useDevices } from '@/lib/hooks/useDevices';
import { summarizeTaskStatuses } from '@/lib/task-status-summary';
import { getApiErrorMessage } from '@/lib/apiError';
import { useCapabilities } from '@/src/features/access/Capabilities';
import { BatchRun, BatchRuns, batchHref } from '@/src/features/tasks/BatchRuns';
import { getCurrentScriptVersion } from '@/src/features/scripts/scriptPresentation';
import { toast } from 'sonner';

const STATUS_OPTIONS = ['ALL', 'RUNNING', 'ASSIGNED', 'QUEUED', 'COMPLETED', 'FAILED', 'TIMEOUT', 'CANCELLED'] as const;
const STATUS_LABELS: Record<(typeof STATUS_OPTIONS)[number], string> = {
  ALL: 'Все статусы', RUNNING: 'Выполняются', ASSIGNED: 'Назначены', QUEUED: 'В очереди',
  COMPLETED: 'Завершены', FAILED: 'Ошибка', TIMEOUT: 'Таймаут', CANCELLED: 'Отменены',
};
type SortField = 'script_name' | 'status' | 'priority' | 'created_at';
type SortDir = 'asc' | 'desc';
const taskName = (task: Task) => task.script_name || `Task ${task.id.slice(0, 8)}`;
const formatTime = (value: string | null) => value ? new Date(value).toLocaleString() : '—';
const scriptVersionId = (script: Script) => script.current_version_id ?? getCurrentScriptVersion(script)?.id;
const UUID = /^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i;
const terminalStatuses = new Set(['completed', 'failed', 'cancelled', 'timeout']);

const TASKS_PER_PAGE = 25;
export default function TaskEnginePage() {
  return <Suspense fallback={<p role="status" className="p-6">Загрузка заданий…</p>}><TasksView /></Suspense>;
}

function TasksView() {
  const params = useSearchParams();
  const batchId = params?.get('batch_id');
  if (batchId) return <BatchRun key={batchId} id={batchId} />;
  if (params?.get('view') === 'batches') return <BatchRuns />;
  const deviceId = params?.get('device_id') || undefined;
  const scriptId = params?.get('script_id') || undefined;
  if ((deviceId && !UUID.test(deviceId)) || (scriptId && !UUID.test(scriptId))) {
    return <div className="space-y-3 p-6">
      <p role="alert">Ссылка содержит некорректный ID устройства или сценария.</p>
      <Button asChild variant="outline"><Link href="/tasks">Открыть общую историю задач</Link></Button>
    </div>;
  }
  return <TaskHistory key={`${deviceId ?? ''}:${scriptId ?? ''}`} deviceId={deviceId} scriptId={scriptId} />;
}

function TaskHistory({ deviceId, scriptId }: { deviceId?: string; scriptId?: string }) {
  const router = useRouter();
  const access = useCapabilities();
  const canExecute = access.can('script:execute');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [sortField, setSortField] = useState<SortField>('created_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [page, setPage] = useState(1);

  // Broadcast модалка
  const [broadcastOpen, setBroadcastOpen] = useState(false);
  const [bcScriptId, setBcScriptId] = useState<string>('');
  const [bcVersionId, setBcVersionId] = useState<string>('');
  const [broadcastUnconfirmed, setBroadcastUnconfirmed] = useState(false);
  const [bcWaveSize, setBcWaveSize] = useState('10');
  const [bcWaveDelay, setBcWaveDelay] = useState('5000');
  const [bcPriority, setBcPriority] = useState(5);

  const debouncedSearch = useDebounce(search.trim(), 300);
  const queryPending = search.trim() !== debouncedSearch;
  const history = useTasks({
    page: queryPending ? 1 : page, per_page: TASKS_PER_PAGE,
    status: statusFilter === 'ALL' ? undefined : statusFilter.toLowerCase(),
    search: debouncedSearch || undefined, sort_by: sortField, sort_dir: sortDir,
    ...(deviceId ? { device_id: deviceId } : {}), ...(scriptId ? { script_id: scriptId } : {}),
    include_counts: true,
  });
  const active = useTasks({ active_only: true, per_page: 10,
    ...(deviceId ? { device_id: deviceId } : {}), ...(scriptId ? { script_id: scriptId } : {}),
  });
  const pipelines = useActivePipelineRuns(deviceId, !scriptId);
  const tasksData = history.data;
  const isLoading = history.isLoading || queryPending;
  const tasks = tasksData?.items ?? [];
  const counts = history.isError || isLoading ? null : tasksData?.status_counts;
  const totalPages = Math.max(1, tasksData?.pages ?? 1);
  useEffect(() => {
    if (tasksData && !history.isError && !isLoading && page > totalPages) setPage(totalPages);
  }, [tasksData, history.isError, isLoading, page, totalPages]);
  const retryTask = useRetryTask();
  const broadcastBatch = useBroadcastBatch();
  const [bcSearch, setBcSearch] = useState('');
  const scriptSearch = useDebounce(bcSearch.trim(), 300);
  const { data: scriptsData } = useScripts({ per_page: 100, state: 'active', query: scriptSearch || undefined });
  const scripts = scriptsData?.items ?? [];
  const online = useDevices({ live_status: 'online', page_size: 1 });
  const onlineCounts = online.isError || online.data?.presence_available === false ? undefined : online.data?.status_counts;
  const onlineCount = onlineCounts ? onlineCounts.online - onlineCounts.busy : null;
  const waveSize = Number(bcWaveSize);
  const waveDelay = Number(bcWaveDelay);
  const validWave = bcWaveSize.trim() !== '' && Number.isInteger(waveSize) && waveSize >= 1 && waveSize <= 100;
  const validDelay = bcWaveDelay.trim() !== '' && Number.isInteger(waveDelay) && waveDelay >= 0 && waveDelay <= 60000;
  // Completion ratio has an explicit denominator: completed + failed + timeout.
  // Queued/active/cancelled work is not silently counted as an execution failure.
  const taskSummary = summarizeTaskStatuses(counts);

  const toggleSort = (field: SortField) => {
    setPage(1);
    if (sortField === field) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  const handleRetry = (task: Task, e: React.MouseEvent) => {
    e.stopPropagation();
    retryTask.mutate(
      task.id,
      {
        onSuccess: (created) => toast.success(`Новое задание принято: ${created?.id ?? 'ID не получен'}`, {
          description: 'Исходная версия и входы сохранены. Выполнение ещё не подтверждено.',
          ...(typeof created?.id === 'string' ? { action: { label: 'Открыть', onClick: () => router.push(`/tasks/${created.id}`) } } : {}),
        }),
        onError: (error) => toast.error(getApiErrorMessage(error, 'Не удалось подтвердить повторный запуск. Проверьте историю задач.')),
      },
    );
  };

  const handleBroadcast = () => {
    if (!canExecute || !bcScriptId || !bcVersionId || !validWave || !validDelay || broadcastBatch.isPending || broadcastUnconfirmed) return;
    broadcastBatch.mutate(
      {
        script_id: bcScriptId,
        expected_current_version_id: bcVersionId,
        wave_size: waveSize,
        wave_delay_ms: waveDelay,
        priority: bcPriority,
      },
      {
        onSuccess: (data) => {
          toast.success('Пакет принят', {
            description: `Цели: ${data.online_devices}. Состояния допуска и исполнения доступны в пакете.`,
            action: { label: 'Открыть пакет', onClick: () => router.push(batchHref(data.id)) },
          });
          setBroadcastOpen(false);
          setBcScriptId('');
          setBcVersionId('');
          setBcSearch('');
          setBcWaveSize('10');
          setBcWaveDelay('5000');
          setBcPriority(5);
          router.push(batchHref(data.id));
        },
        onError: (err: unknown) => {
          const status = (err as { response?: { status?: number } } | null)?.response?.status;
          if (status === undefined || status === 408 || status >= 500) {
            setBroadcastUnconfirmed(true);
            toast.error('Приём пакета не подтверждён', {
              description: 'Проверьте историю пакетов перед повторной отправкой.',
              action: { label: 'Все пакеты', onClick: () => router.push('/tasks?view=batches') },
            });
          } else {
            toast.error(getApiErrorMessage(err, 'Ошибка запуска пакетной задачи'));
          }
        },
      },
    );
  };

  return (
    <div className="min-h-full bg-background">
      <header className="border-b border-border bg-background px-6 py-6 lg:px-8">
        <div className="mx-auto flex max-w-screen-2xl flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
          <div className="min-w-0">
            <p className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-primary">
              <ListTodo className="h-4 w-4" aria-hidden="true" /> Автоматизация · Задания
            </p>
            <h1 className="text-2xl font-semibold tracking-tight text-foreground">Задачи и исполнения</h1>
            <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground">
              История запусков, текущая очередь и активные pipeline. Данные обновляются автоматически каждые 10 секунд.
            </p>
          </div>

          <div className="flex w-full flex-wrap items-center gap-2 xl:w-auto">
            <Button asChild variant="outline" size="sm" className="h-10 rounded-lg"><Link href="/tasks?view=batches">Пакетные запуски</Link></Button>
            <Input
              aria-label="Поиск задач"
              placeholder="Сценарий, устройство или ID"
              className="h-10 min-w-[220px] flex-1 rounded-lg bg-background sm:w-64 sm:flex-none"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            />
            <select
              aria-label="Статус задачи"
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
              className="h-10 rounded-lg border border-input bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
            </select>
            <Button variant="default" size="sm" className="h-10 rounded-lg" onClick={() => router.push('/scripts/builder')}>
              <Workflow className="mr-2 h-4 w-4" aria-hidden="true" /> Новый сценарий
            </Button>
            {canExecute && <Button variant="outline" size="sm" className="h-10 rounded-lg" onClick={() => setBroadcastOpen(true)}>
              <Radio className="mr-2 h-4 w-4" aria-hidden="true" /> Запустить на парке
              <span className="ml-2 rounded-md bg-muted px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
                {onlineCount ?? '—'} в сети
              </span>
            </Button>}
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-screen-2xl space-y-6 px-6 py-6 lg:px-8">
        {(deviceId || scriptId) && <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card p-3 text-sm">
          {deviceId && <span className="break-all">Устройство <code>{deviceId}</code></span>}
          {scriptId && <span className="break-all">Сценарий <code>{scriptId}</code></span>}
          <Button asChild variant="outline" size="sm"><Link href="/tasks">Сбросить область истории</Link></Button>
        </div>}
        <section aria-label="Показатели выбранной истории" className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="flex items-start justify-between rounded-xl border border-border bg-card p-5 shadow-sm">
            <div><div className="text-sm font-medium text-muted-foreground">Всего задач</div>
              <div className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-foreground">{isLoading || history.isError ? '—' : tasksData?.total ?? '—'}</div>
              <div className="mt-1 text-xs text-muted-foreground">История с текущими фильтрами</div></div>
            <span className="rounded-lg bg-primary/10 p-2.5 text-primary"><CalendarClock className="h-5 w-5" aria-hidden="true" /></span>
          </div>
          <div className="flex items-start justify-between rounded-xl border border-border bg-card p-5 shadow-sm">
            <div><div className="text-sm font-medium text-muted-foreground">Успешное выполнение</div>
              <div className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-success">{taskSummary.successRate}</div>
              <div className="mt-1 text-xs text-muted-foreground">Среди завершённых задач</div></div>
            <span className="rounded-lg bg-success/10 p-2.5 text-success"><CheckCircle2 className="h-5 w-5" aria-hidden="true" /></span>
          </div>
          <div className="flex items-start justify-between rounded-xl border border-border bg-card p-5 shadow-sm">
            <div><div className="text-sm font-medium text-muted-foreground">Ошибки и таймауты</div>
              <div className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-destructive">{taskSummary.failedAndTimeout ?? '—'}</div>
              <div className="mt-1 text-xs text-muted-foreground">В выбранной истории</div></div>
            <span className="rounded-lg bg-destructive/10 p-2.5 text-destructive"><ShieldAlert className="h-5 w-5" aria-hidden="true" /></span>
          </div>
        </section>

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <section className="space-y-3 rounded-xl border border-border bg-card p-5 shadow-sm" aria-label="Активные задачи">
            <h2 className="flex items-center gap-2 text-base font-semibold tracking-tight"><Clock className="h-4 w-4 text-primary" aria-hidden="true" />Активные задачи</h2>
            {active.isLoading ? <p>Загрузка очереди…</p> : active.isError ? <p role="alert">Не удалось загрузить очередь задач</p> : active.data && <>
              <p className="text-sm text-muted-foreground">Показано {active.data.items.length} из {active.data.total}. В очереди, назначены или выполняются.</p>
              {active.data.total === 0 && <p className="rounded-lg bg-muted/50 px-3 py-4 text-sm text-muted-foreground">Активных задач сейчас нет.</p>}
              {active.data.items.map(task => <button key={task.id} onClick={() => router.push(`/tasks/${task.id}`)} className="block w-full text-left border-t border-border pt-2">
                <span className="text-sm">{taskName(task)}</span><span className="ml-2 text-xs font-mono">{executionStatusLabel(task)}</span>
                <span className="block text-xs text-muted-foreground">{task.device_name || task.device_id} · {task.id}</span>
              </button>)}
            </>}
          </section>
          {!scriptId && <section className="space-y-3 rounded-xl border border-border bg-card p-5 shadow-sm" aria-label="Активные pipeline">
            <h2 className="flex items-center gap-2 text-base font-semibold tracking-tight"><Workflow className="h-4 w-4 text-primary" aria-hidden="true" />Активные pipeline</h2>
            {pipelines.isLoading ? <p className="text-sm text-muted-foreground">Загрузка активных pipeline…</p> : pipelines.isError ? <p role="alert" className="text-sm text-destructive">Не удалось загрузить pipeline</p> : pipelines.data && <>
              <p className="text-sm text-muted-foreground">Показано {pipelines.data.items.length} из {pipelines.data.total}. Включая ожидающие и приостановленные.</p>
              {pipelines.data.total === 0 && <p className="rounded-lg bg-muted/50 px-3 py-4 text-sm text-muted-foreground">Активных pipeline сейчас нет.</p>}
              {pipelines.data.items.map(run => <div key={run.id} className="border-t border-border pt-2 text-xs space-y-1">
                <Link className="block break-all font-mono text-primary hover:underline" href={`/orchestration?run_id=${encodeURIComponent(run.id)}`} prefetch={false}>{run.id}</Link><Badge variant="outline">{executionStatusLabel(run)}</Badge>
                <p className="text-muted-foreground break-all">Pipeline {run.pipeline_id} · устройство {run.device_id}</p>
                {run.current_step_id && <p>Шаг: {run.current_step_id}</p>}
                {run.current_task_id && <Button variant="outline" size="sm" aria-label={`Текущая задача pipeline ${run.id}`} onClick={() => router.push(`/tasks/${run.current_task_id}`)}>Открыть задачу</Button>}
              </div>)}
            </>}
          </section>}
        </div>

        {history.isError && <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <p>Не удалось загрузить историю задач</p>
          <Button variant="outline" size="sm" onClick={() => history.refetch()}>Повторить загрузку</Button>
        </div>}
        {!history.isError && <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-sm">
          <table className="w-full min-w-[950px] text-left text-sm">
            <thead className="border-b border-border bg-muted/60"><tr>
              {([['status','Статус'],['script_name','Сценарий']] as const).map(([field,label]) => <th key={field} className="p-3" aria-sort={sortField===field ? (sortDir==='asc'?'ascending':'descending') : 'none'}>
                <button onClick={() => toggleSort(field)}>{label} {sortField===field ? (sortDir==='asc'?'↑':'↓') : ''}</button>
              </th>)}
              <th className="p-3">Устройство</th>
              {([['priority','Приоритет'],['created_at','Создана']] as const).map(([field,label]) => <th key={field} className="p-3" aria-sort={sortField===field ? (sortDir==='asc'?'ascending':'descending') : 'none'}>
                <button onClick={() => toggleSort(field)}>{label} {sortField===field ? (sortDir==='asc'?'↑':'↓') : ''}</button>
              </th>)}
              <th className="p-3">Начало / завершение</th><th className="p-3">Действия</th>
            </tr></thead>
            <tbody className="divide-y divide-border">
              {isLoading ? <tr><td colSpan={7} className="p-8 text-center text-sm text-muted-foreground"><span className="inline-flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />Загрузка задач…</span></td></tr> : <>
                {tasks.length===0 && <tr><td colSpan={7} className="p-8 text-center text-sm text-muted-foreground">По выбранным фильтрам задач нет.</td></tr>}
                {tasks.map(task => <tr key={task.id} className="hover:bg-muted">
                  <td className="p-3"><Badge variant="outline">{executionStatusLabel(task).toUpperCase()}</Badge></td>
                  <td className="p-3"><button onClick={() => router.push(`/tasks/${task.id}`)} className="text-left hover:text-primary">
                    <span className="font-semibold">{taskName(task)}</span><span className="block text-xs font-mono text-muted-foreground">{task.id}</span>
                  </button>{task.batch_id && <Link className="mt-1 block text-xs text-primary hover:underline" href={batchHref(task.batch_id)} prefetch={false}>Пакет задания</Link>}</td>
                  <td className="p-3">{task.device_name || task.device_id}</td><td className="p-3">{task.priority}</td>
                  <td className="p-3 whitespace-nowrap">{formatTime(task.created_at)}</td>
                  <td className="p-3 whitespace-nowrap">{formatTime(task.started_at)}<br />{formatTime(task.finished_at)}</td>
                  <td className="p-3">{canExecute && terminalStatuses.has(task.status) && task.script_version_id &&
                    <Button variant="ghost" size="icon" title="Перезапустить задачу" aria-label={`Перезапустить ${task.id}`} disabled={retryTask.isPending} onClick={(e) => handleRetry(task,e)}><RotateCcw className="w-4 h-4" /></Button>}</td>
                </tr>)}
              </>}
            </tbody>
          </table>
        </div>}
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>{!history.isError && !isLoading && tasksData ? `${tasksData.total} задач` : '—'}</span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon" aria-label="Предыдущая страница" disabled={page<=1 || isLoading || history.isError} onClick={() => setPage(p => p-1)}><ChevronLeft className="w-4 h-4" /></Button>
            <span>{!history.isError && !isLoading && tasksData ? `${page} / ${totalPages}` : '—'}</span>
            <Button variant="ghost" size="icon" aria-label="Следующая страница" disabled={page>=totalPages || isLoading || history.isError} onClick={() => setPage(p => p+1)}><ChevronRight className="w-4 h-4" /></Button>
          </div>
        </div>
      </div>

      {/* ── Модалка: Broadcast — запуск на всех онлайн-устройствах ────────── */}
      <Dialog open={broadcastOpen && canExecute} onOpenChange={setBroadcastOpen}>
        <DialogContent className="sm:max-w-[480px] bg-card border-border">
          <DialogHeader>
            <DialogTitle className="font-mono text-foreground flex items-center gap-2">
              <Radio className="w-5 h-5 text-primary" />
              Запуск на всех устройствах
            </DialogTitle>
            <DialogDescription className="font-mono text-xs">
              Сервер выберет цели среди устройств, подтверждённых онлайн при приёме запроса.
            </DialogDescription>
          </DialogHeader>

          {/* Статус онлайн */}
          <div className="flex items-center gap-3 p-3 rounded border border-border bg-muted/50">
            <span className="text-sm font-mono font-bold text-foreground">{onlineCount ?? '—'}</span>
            <span className="text-xs text-muted-foreground font-mono">устройств в сети по последнему подсчёту</span>
          </div>

          <div className="grid gap-4 py-2">
            {/* Выбор скрипта */}
            <div className="grid gap-2">
              <Label htmlFor="broadcast-script-search" className="text-xs font-mono font-bold text-muted-foreground uppercase tracking-wider">Поиск сценария</Label>
              <Input id="broadcast-script-search" value={bcSearch} onChange={e => {
                setBcSearch(e.target.value); setBcScriptId(''); setBcVersionId('');
              }} placeholder="Название сценария" />
              <Select value={bcScriptId} onValueChange={id => {
                const script = scripts.find(item => item.id === id);
                setBcScriptId(id);
                setBcVersionId(script ? scriptVersionId(script) ?? '' : '');
              }}>
                <SelectTrigger aria-label="Сценарий" className="bg-background border-border font-mono text-xs">
                  <SelectValue placeholder="Выберите скрипт..." />
                </SelectTrigger>
                <SelectContent>
                  {scripts.filter(s => !s.is_archived && scriptVersionId(s)).map((s) => (
                    <SelectItem key={s.id} value={s.id} className="font-mono text-xs">
                      {s.name}{getCurrentScriptVersion(s) && ` · версия ${getCurrentScriptVersion(s)?.version}`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {bcVersionId && <p className="break-all text-xs text-muted-foreground">ID подтверждаемой версии {bcVersionId}</p>}
            </div>

            {/* Настройки волн */}
            <div className="grid grid-cols-3 gap-3">
              <div className="grid gap-2">
                <Label htmlFor="broadcast-wave-size" className="text-[10px] font-mono font-bold text-muted-foreground uppercase tracking-wider">
                  Размер волны
                </Label>
                <Input
                  id="broadcast-wave-size"
                  type="number"
                  min={1}
                  max={100}
                  value={bcWaveSize}
                  onChange={(e) => setBcWaveSize(e.target.value)}
                  className="bg-background border-border font-mono text-xs h-9"
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="broadcast-wave-delay" className="text-[10px] font-mono font-bold text-muted-foreground uppercase tracking-wider">
                  Задержка (мс)
                </Label>
                <Input
                  id="broadcast-wave-delay"
                  type="number"
                  min={0}
                  max={60000}
                  value={bcWaveDelay}
                  onChange={(e) => setBcWaveDelay(e.target.value)}
                  className="bg-background border-border font-mono text-xs h-9"
                />
              </div>
              <div className="grid gap-2">
                <Label className="text-[10px] font-mono font-bold text-muted-foreground uppercase tracking-wider">
                  Приоритет
                </Label>
                <Select value={String(bcPriority)} onValueChange={(v) => setBcPriority(Number(v))}>
                  <SelectTrigger className="bg-background border-border font-mono text-xs h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((p) => (
                      <SelectItem key={p} value={String(p)} className="font-mono text-xs">
                        {p} {p <= 3 ? '(высокий)' : p <= 7 ? '(средний)' : '(низкий)'}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Информация о волнах */}
            {onlineCount != null && onlineCount > 0 && validWave && validDelay && (
              <div className="text-[10px] font-mono text-muted-foreground bg-muted/30 rounded p-2 border border-border/50">
                До {waveSize} устройств в волне · около {Math.ceil(onlineCount / waveSize)} волн.
                Пауза между волнами {waveDelay} мс, плюс до 1000 мс случайного разброса.
              </div>
            )}
          </div>

          {broadcastUnconfirmed && <p role="alert" className="text-sm text-destructive">Приём пакета не подтверждён. <Link className="underline" href="/tasks?view=batches">Сверьте историю пакетов</Link> перед новым запуском.</p>}
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setBroadcastOpen(false)}
              className="font-mono text-xs"
            >
              Отмена
            </Button>
            <Button
              onClick={handleBroadcast}
              disabled={!bcScriptId || !bcVersionId || !validWave || !validDelay || broadcastBatch.isPending || broadcastUnconfirmed}
              className="font-mono text-xs"
            >
              {broadcastBatch.isPending ? (
                <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Запуск...</>
              ) : (
                <><Play className="w-4 h-4 mr-2" /> Отправить пакет</>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
