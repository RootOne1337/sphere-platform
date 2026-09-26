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
import { toast } from 'sonner';

const STATUS_OPTIONS = ['ALL', 'RUNNING', 'ASSIGNED', 'QUEUED', 'COMPLETED', 'FAILED', 'TIMEOUT', 'CANCELLED'] as const;
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
  const resolved = counts ? counts.completed + counts.failed + counts.timeout : 0;
  const successRate = counts && resolved > 0 ? `${(counts.completed / resolved * 100).toFixed(1)}%` : '—';

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
        onError: (err: any) => {
          const detail = err?.response?.data?.detail || 'Ошибка запуска батча';
          toast.error(detail);
        },
      },
    );
  };

  return (
    <div className="flex flex-col h-full bg-card">
      <div className="px-6 py-5 border-b border-border bg-muted shrink-0">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <ListTodo className="w-5 h-5 text-primary" />
              <h1 className="text-xl font-bold font-mono tracking-tight text-foreground uppercase pt-1">Task Engine</h1>
            </div>
            <p className="text-xs text-muted-foreground font-mono max-w-2xl">
              История выполнения сценариев, очередь задач и активные pipeline. Обновление каждые 10 секунд.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3 w-full md:w-auto">
            <Input
              placeholder="Filter tasks..."
              className="w-full sm:w-64 h-9 bg-black/50 border-border font-mono text-xs focus-visible:ring-primary/50"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            />
            {/* Фильтр по статусу */}
            <select
              aria-label="Статус задачи"
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
              className="h-9 px-3 rounded border border-border bg-background text-xs font-mono"
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <Button variant="default" size="sm" className="h-9" onClick={() => router.push('/scripts/builder')}>
              <Workflow className="w-4 h-4 mr-2" /> Новый сценарий
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="h-9 border-primary/50 text-primary hover:bg-primary/10"
              onClick={() => setBroadcastOpen(true)}
            >
              <Radio className="w-4 h-4 mr-2" /> Запустить на всех
              {onlineCount > 0 && (
                <span className="ml-2 inline-flex items-center rounded-sm px-1.5 py-0 text-[9px] uppercase font-bold tracking-widest font-mono border border-transparent bg-secondary text-secondary-foreground">
                  {onlineCount} online
                </span>
              )}
            </Button>
          </div>
        </div>
      </div>

      <div className="p-6 flex-1 overflow-auto space-y-6">
        <section aria-label="Показатели выбранной истории" className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="border border-border bg-muted rounded-sm p-4 flex items-center justify-between">
            <div><div className="text-xs text-muted-foreground">Total Tasks</div>
              <div className="text-2xl font-mono font-bold">{isLoading || history.isError ? '—' : tasksData?.total ?? '—'}</div>
              <div className="text-xs text-muted-foreground">Вся история с выбранными фильтрами</div></div>
            <CalendarClock className="w-8 h-8 text-primary/30" />
          </div>
          <div className="border border-border bg-muted rounded-sm p-4 flex items-center justify-between">
            <div><div className="text-xs text-muted-foreground">Success Rate</div>
              <div className="text-2xl font-mono font-bold text-success">{successRate}</div>
              <div className="text-xs text-muted-foreground">Completed / (completed + failed + timeout)</div></div>
            <CheckCircle2 className="w-8 h-8 text-success/30" />
          </div>
          <div className="border border-border bg-muted rounded-sm p-4 flex items-center justify-between">
            <div><div className="text-xs text-muted-foreground">Failed + Timeout</div>
              <div className="text-2xl font-mono font-bold text-destructive">{counts ? counts.failed + counts.timeout : '—'}</div>
              <div className="text-xs text-muted-foreground">Во всём выбранном наборе</div></div>
            <ShieldAlert className="w-8 h-8 text-destructive/30" />
          </div>
        </section>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <section className="border border-border rounded-sm p-4 space-y-3" aria-label="Активные задачи">
            <h2 className="font-mono text-sm flex items-center gap-2"><Clock className="w-4 h-4" />Активные задачи</h2>
            {active.isLoading ? <p>Загрузка очереди…</p> : active.isError ? <p role="alert">Не удалось загрузить очередь задач</p> : active.data && <>
              <p className="text-xs text-muted-foreground">Показано {active.data.items.length} из {active.data.total}. Queued / assigned / running.</p>
              {active.data.total === 0 && <p>Нет активных задач</p>}
              {active.data.items.map(task => <button key={task.id} onClick={() => router.push(`/tasks/${task.id}`)} className="block w-full text-left border-t border-border pt-2">
                <span className="text-sm">{taskName(task)}</span><span className="ml-2 text-xs font-mono">{executionStatusLabel(task)}</span>
                <span className="block text-xs text-muted-foreground">{task.device_name || task.device_id} · {task.id}</span>
              </button>)}
            </>}
          </section>
          <section className="border border-border rounded-sm p-4 space-y-3" aria-label="Активные pipeline">
            <h2 className="font-mono text-sm flex items-center gap-2"><Workflow className="w-4 h-4" />Активные pipeline</h2>
            {pipelines.isLoading ? <p>Загрузка pipeline…</p> : pipelines.isError ? <p role="alert">Не удалось загрузить pipeline</p> : pipelines.data && <>
              <p className="text-xs text-muted-foreground">Показано {pipelines.data.items.length} из {pipelines.data.total}. Включая waiting и paused.</p>
              {pipelines.data.total === 0 && <p>Нет активных pipeline</p>}
              {pipelines.data.items.map(run => <div key={run.id} className="border-t border-border pt-2 text-xs space-y-1">
                <div className="font-mono break-all">{run.id}</div><Badge variant="outline">{executionStatusLabel(run)}</Badge>
                <p className="text-muted-foreground break-all">Pipeline {run.pipeline_id} · устройство {run.device_id}</p>
                {run.current_step_id && <p>Шаг: {run.current_step_id}</p>}
                {run.current_task_id && <Button variant="outline" size="sm" aria-label={`Текущая задача pipeline ${run.id}`} onClick={() => router.push(`/tasks/${run.current_task_id}`)}>Открыть задачу</Button>}
              </div>)}
            </>}
          </section>
        </div>

        {history.isError && <div role="alert" className="border border-destructive p-4 rounded-sm">
          <p>Не удалось загрузить историю задач</p>
          <Button variant="outline" size="sm" onClick={() => history.refetch()}>Повторить загрузку</Button>
        </div>}
        {!history.isError && <div className="rounded-sm border border-border overflow-x-auto">
          <table className="w-full min-w-[950px] text-left text-xs">
            <thead className="bg-muted border-b border-border"><tr>
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
              {isLoading ? <tr><td colSpan={7} className="p-6 text-center">Загрузка задач…</td></tr> : <>
                {tasks.length===0 && <tr><td colSpan={7} className="p-6 text-center">Задачи не найдены</td></tr>}
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
        <div className="flex items-center justify-between text-xs font-mono">
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
              Устройства определяются автоматически из Redis status cache.
            </DialogDescription>
          </DialogHeader>

          {/* Статус онлайн */}
          <div className="flex items-center gap-3 p-3 rounded border border-border bg-muted/50">
            <div className="w-2.5 h-2.5 rounded-full bg-success animate-pulse" />
            <span className="text-sm font-mono font-bold text-foreground">{onlineCount}</span>
            <span className="text-xs text-muted-foreground font-mono">устройств онлайн</span>
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
