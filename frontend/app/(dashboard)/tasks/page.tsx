'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
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
import { useScripts } from '@/lib/hooks/useScripts';
import { useDevices } from '@/lib/hooks/useDevices';
import { summarizeTaskStatuses } from '@/lib/task-status-summary';
import { getApiErrorMessage } from '@/lib/apiError';
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

const TASKS_PER_PAGE = 25;
export default function TaskEnginePage() {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [sortField, setSortField] = useState<SortField>('created_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [page, setPage] = useState(1);

  // Broadcast модалка
  const [broadcastOpen, setBroadcastOpen] = useState(false);
  const [bcScriptId, setBcScriptId] = useState<string>('');
  const [bcWaveSize, setBcWaveSize] = useState(10);
  const [bcWaveDelay, setBcWaveDelay] = useState(5000);
  const [bcPriority, setBcPriority] = useState(5);

  const debouncedSearch = useDebounce(search.trim(), 300);
  const queryPending = search.trim() !== debouncedSearch;
  const history = useTasks({
    page: queryPending ? 1 : page, per_page: TASKS_PER_PAGE,
    status: statusFilter === 'ALL' ? undefined : statusFilter.toLowerCase(),
    search: debouncedSearch || undefined, sort_by: sortField, sort_dir: sortDir,
    include_counts: true,
  });
  const active = useTasks({ active_only: true, per_page: 10 });
  const pipelines = useActivePipelineRuns();
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
  const { data: scriptsData } = useScripts({ per_page: 100 });
  const scripts = scriptsData?.items ?? [];
  const { data: onlineData } = useDevices({ status: 'online', page_size: 1 });
  const onlineCount = onlineData?.total ?? 0;
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
      { script_id: task.script_id, device_id: task.device_id, priority: task.priority },
      {
        onSuccess: () => toast.success(`Задача "${taskName(task)}" перезапущена`),
        onError: () => toast.error('Ошибка перезапуска'),
      },
    );
  };

  const handleBroadcast = () => {
    if (!bcScriptId) {
      toast.error('Выберите скрипт');
      return;
    }
    broadcastBatch.mutate(
      {
        script_id: bcScriptId,
        wave_size: bcWaveSize,
        wave_delay_ms: bcWaveDelay,
        priority: bcPriority,
      },
      {
        onSuccess: (data) => {
          toast.success(`Батч запущен на ${data.online_devices} устройствах`);
          setBroadcastOpen(false);
          setBcScriptId('');
          setBcWaveSize(10);
          setBcWaveDelay(5000);
          setBcPriority(5);
        },
        onError: (err: unknown) => {
          toast.error(getApiErrorMessage(err, 'Ошибка запуска пакетной задачи'));
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
            <Button variant="outline" size="sm" className="h-10 rounded-lg" onClick={() => setBroadcastOpen(true)}>
              <Radio className="mr-2 h-4 w-4" aria-hidden="true" /> Запустить на парке
              <span className="ml-2 rounded-md bg-muted px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
                {onlineCount} в сети
              </span>
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-screen-2xl space-y-6 px-6 py-6 lg:px-8">
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
          <section className="space-y-3 rounded-xl border border-border bg-card p-5 shadow-sm" aria-label="Активные pipeline">
            <h2 className="flex items-center gap-2 text-base font-semibold tracking-tight"><Workflow className="h-4 w-4 text-primary" aria-hidden="true" />Активные pipeline</h2>
            {pipelines.isLoading ? <p className="text-sm text-muted-foreground">Загрузка активных pipeline…</p> : pipelines.isError ? <p role="alert" className="text-sm text-destructive">Не удалось загрузить pipeline</p> : pipelines.data && <>
              <p className="text-sm text-muted-foreground">Показано {pipelines.data.items.length} из {pipelines.data.total}. Включая ожидающие и приостановленные.</p>
              {pipelines.data.total === 0 && <p className="rounded-lg bg-muted/50 px-3 py-4 text-sm text-muted-foreground">Активных pipeline сейчас нет.</p>}
              {pipelines.data.items.map(run => <div key={run.id} className="border-t border-border pt-2 text-xs space-y-1">
                <div className="font-mono break-all">{run.id}</div><Badge variant="outline">{executionStatusLabel(run)}</Badge>
                <p className="text-muted-foreground break-all">Pipeline {run.pipeline_id} · устройство {run.device_id}</p>
                {run.current_step_id && <p>Шаг: {run.current_step_id}</p>}
                {run.current_task_id && <Button variant="outline" size="sm" aria-label={`Текущая задача pipeline ${run.id}`} onClick={() => router.push(`/tasks/${run.current_task_id}`)}>Открыть задачу</Button>}
              </div>)}
            </>}
          </section>
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
                  </button></td>
                  <td className="p-3">{task.device_name || task.device_id}</td><td className="p-3">{task.priority}</td>
                  <td className="p-3 whitespace-nowrap">{formatTime(task.created_at)}</td>
                  <td className="p-3 whitespace-nowrap">{formatTime(task.started_at)}<br />{formatTime(task.finished_at)}</td>
                  <td className="p-3"><Button variant="ghost" size="icon" title="Перезапустить задачу" aria-label={`Перезапустить ${task.id}`} disabled={retryTask.isPending} onClick={(e) => handleRetry(task,e)}><RotateCcw className="w-4 h-4" /></Button></td>
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
      <Dialog open={broadcastOpen} onOpenChange={setBroadcastOpen}>
        <DialogContent className="sm:max-w-[480px] bg-card border-border">
          <DialogHeader>
            <DialogTitle className="font-mono text-foreground flex items-center gap-2">
              <Radio className="w-5 h-5 text-primary" />
              Запуск на всех устройствах
            </DialogTitle>
            <DialogDescription className="font-mono text-xs">
              Скрипт будет запущен на всех онлайн-устройствах организации волнами.
              Список устройств формируется автоматически по актуальному кешу статусов.
            </DialogDescription>
          </DialogHeader>

          {/* Статус онлайн */}
          <div className="flex items-center gap-3 p-3 rounded border border-border bg-muted/50">
            <div className="w-2.5 h-2.5 rounded-full bg-success animate-pulse" />
            <span className="text-sm font-mono font-bold text-foreground">{onlineCount}</span>
            <span className="text-xs text-muted-foreground font-mono">устройств в сети</span>
          </div>

          <div className="grid gap-4 py-2">
            {/* Выбор скрипта */}
            <div className="grid gap-2">
              <Label className="text-xs font-mono font-bold text-muted-foreground uppercase tracking-wider">Скрипт</Label>
              <Select value={bcScriptId} onValueChange={setBcScriptId}>
                <SelectTrigger className="bg-background border-border font-mono text-xs">
                  <SelectValue placeholder="Выберите скрипт..." />
                </SelectTrigger>
                <SelectContent>
                  {scripts.filter((s) => !s.is_archived).map((s) => (
                    <SelectItem key={s.id} value={s.id} className="font-mono text-xs">
                      {s.name} ({s.node_count} узлов)
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Настройки волн */}
            <div className="grid grid-cols-3 gap-3">
              <div className="grid gap-2">
                <Label className="text-[10px] font-mono font-bold text-muted-foreground uppercase tracking-wider">
                  Размер волны
                </Label>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  value={bcWaveSize}
                  onChange={(e) => setBcWaveSize(Number(e.target.value) || 10)}
                  className="bg-background border-border font-mono text-xs h-9"
                />
              </div>
              <div className="grid gap-2">
                <Label className="text-[10px] font-mono font-bold text-muted-foreground uppercase tracking-wider">
                  Задержка (мс)
                </Label>
                <Input
                  type="number"
                  min={0}
                  max={60000}
                  value={bcWaveDelay}
                  onChange={(e) => setBcWaveDelay(Number(e.target.value) || 5000)}
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
                        {p} {p <= 3 ? '(низкий)' : p <= 7 ? '(средний)' : '(высокий)'}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Информация о волнах */}
            {onlineCount > 0 && bcWaveSize > 0 && (
              <div className="text-[10px] font-mono text-muted-foreground bg-muted/30 rounded p-2 border border-border/50">
                {Math.ceil(onlineCount / bcWaveSize)} волн × {bcWaveSize} устройств
                &nbsp;·&nbsp;~{((Math.ceil(onlineCount / bcWaveSize) - 1) * bcWaveDelay / 1000).toFixed(0)}с общая задержка
              </div>
            )}
          </div>

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
              disabled={!bcScriptId || onlineCount === 0 || broadcastBatch.isPending}
              className="font-mono text-xs"
            >
              {broadcastBatch.isPending ? (
                <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Запуск...</>
              ) : (
                <><Play className="w-4 h-4 mr-2" /> Запустить на {onlineCount} устройствах</>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
