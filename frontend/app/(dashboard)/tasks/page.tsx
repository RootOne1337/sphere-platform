'use client';

import { useState, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { ListTodo, Play, Clock, CalendarClock, ShieldAlert, CheckCircle2, Workflow, ArrowUpDown, ChevronLeft, ChevronRight, RotateCcw, Radio, Loader2 } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';
import { Badge } from '@/src/shared/ui/badge';
import { TaskGanttChart } from '@/src/features/tasks/TaskGanttChart';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Label } from '@/components/ui/label';

import { useTasks, useRetryTask } from '@/lib/hooks/useTasks';
import { useBroadcastBatch } from '@/lib/hooks/useBatches';
import { useScripts } from '@/lib/hooks/useScripts';
import { useDevices } from '@/lib/hooks/useDevices';
import { toast } from 'sonner';

interface TaskItem {
  id: string;
  name: string;
  type: string;
  schedule: string;
  status: string;
  lastRun: string;
  nextRun: string;
  startTimeMs: number;
  durationMs: number | null;
  device_name: string | null;
  // Для retry
  script_id: string;
  device_id: string;
  priority: number;
}

/** Статусы для фильтра */
const STATUS_OPTIONS = ['ALL', 'RUNNING', 'ASSIGNED', 'QUEUED', 'COMPLETED', 'SUCCESS', 'FAILED', 'ERROR', 'TIMEOUT', 'CANCELLED'] as const;

/** Поля для сортировки */
type SortField = 'name' | 'status' | 'type' | 'lastRun';
type SortDir = 'asc' | 'desc';

const TASKS_PER_PAGE = 25;
export default function TaskEnginePage() {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [sortField, setSortField] = useState<SortField>('lastRun');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [page, setPage] = useState(1);

  // Broadcast модалка
  const [broadcastOpen, setBroadcastOpen] = useState(false);
  const [bcScriptId, setBcScriptId] = useState<string>('');
  const [bcWaveSize, setBcWaveSize] = useState(10);
  const [bcWaveDelay, setBcWaveDelay] = useState(5000);
  const [bcPriority, setBcPriority] = useState(5);

  const { data: tasksData, isLoading } = useTasks({ per_page: 100 });
  const rawTasks = tasksData?.items ?? [];
  const retryTask = useRetryTask();
  const broadcastBatch = useBroadcastBatch();

  // Данные для модалки
  const { data: scriptsData } = useScripts({ per_page: 100 });
  const scripts = scriptsData?.items ?? [];
  const { data: onlineData } = useDevices({ status: 'online', page_size: 1 });
  const onlineCount = onlineData?.total ?? 0;

  const tasks: TaskItem[] = useMemo(() => {
    return rawTasks.map((t: any) => {
      const st = (t.status || '').toUpperCase();
      const isRunning = st === 'RUNNING' || st === 'ASSIGNED';
      const created = new Date(t.created_at);

      return {
        id: t.id,
        name: t.name || `Task ${t.id.slice(0, 8)}`,
        type: t.priority > 0 ? 'CRON' : 'SCRIPT',
        schedule: 'Manual',
        status: (t.status || '').toUpperCase(),
        lastRun: created.toLocaleString(),
        nextRun: isRunning ? 'In Progress...' : '-',
        startTimeMs: created.getTime(),
        durationMs: isRunning ? null : (t.finished_at && t.started_at ? new Date(t.finished_at).getTime() - new Date(t.started_at).getTime() : null),
        device_name: t.device_name ?? null,
        script_id: t.script_id,
        device_id: t.device_id,
        priority: t.priority,
      };
    });
  }, [rawTasks]);

  // Фильтрация по статусу + поиск
  const filteredTasks = useMemo(() => {
    let result = tasks;
    if (statusFilter !== 'ALL') {
      result = result.filter((t) => t.status === statusFilter);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (t) => t.name.toLowerCase().includes(q) || t.id.includes(q),
      );
    }
    return result;
  }, [tasks, statusFilter, search]);

  // Сортировка
  const sortedTasks = useMemo(() => {
    const sorted = [...filteredTasks];
    sorted.sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case 'name': cmp = a.name.localeCompare(b.name); break;
        case 'status': cmp = a.status.localeCompare(b.status); break;
        case 'type': cmp = a.type.localeCompare(b.type); break;
        case 'lastRun': cmp = a.startTimeMs - b.startTimeMs; break;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return sorted;
  }, [filteredTasks, sortField, sortDir]);

  // Пагинация
  const totalPages = Math.max(1, Math.ceil(sortedTasks.length / TASKS_PER_PAGE));
  const pagedTasks = sortedTasks.slice((page - 1) * TASKS_PER_PAGE, page * TASKS_PER_PAGE);

  const runningTasks = useMemo(() => {
    return tasks
      .filter(t => t.status === 'RUNNING' || t.status === 'ASSIGNED' || t.status === 'QUEUED')
      .map(t => ({
        ...t,
        status: (t.status === 'FAILED' || t.status === 'ERROR') ? 'FAILED' :
          (t.status === 'COMPLETED' || t.status === 'SUCCESS') ? 'SUCCESS' :
            (t.status === 'RUNNING') ? 'RUNNING' : 'PENDING' as any
      }));
  }, [tasks]);

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  const handleRetry = (task: TaskItem, e: React.MouseEvent) => {
    e.stopPropagation();
    retryTask.mutate(
      { script_id: task.script_id, device_id: task.device_id, priority: task.priority },
      {
        onSuccess: () => toast.success(`Задача "${task.name}" перезапущена`),
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
              Unified orchestration layer for cron jobs, script execution, and N8N workflow schedules.
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
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
              className="h-9 px-3 rounded border border-border bg-background text-xs font-mono"
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <Button variant="default" size="sm" className="h-9">
              <Workflow className="w-4 h-4 mr-2" /> New Workflow
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

      <div className="p-6 flex-1 overflow-auto">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-8">
          {/* Quick Stats — computed from real data */}
          <div className="border border-border bg-muted rounded-sm p-4 flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase text-muted-foreground font-bold tracking-widest mb-1">Total Tasks</div>
              <div className="text-2xl font-mono font-bold text-foreground">{tasks.length}</div>
            </div>
            <CalendarClock className="w-8 h-8 text-primary/30" strokeWidth={1} />
          </div>
          <div className="border border-border bg-muted rounded-sm p-4 flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase text-muted-foreground font-bold tracking-widest mb-1">Success Rate</div>
              <div className="text-2xl font-mono font-bold text-success">
                {tasks.length > 0
                  ? `${((tasks.filter(t => t.status === 'COMPLETED' || t.status === 'SUCCESS').length / tasks.length) * 100).toFixed(1)}%`
                  : '—'}
              </div>
            </div>
            <CheckCircle2 className="w-8 h-8 text-success/30" strokeWidth={1} />
          </div>
          <div className="border border-border bg-muted rounded-sm p-4 flex items-center justify-between">
            <div>
              <div className="text-[10px] uppercase text-muted-foreground font-bold tracking-widest mb-1">Failed Tasks</div>
              <div className="text-2xl font-mono font-bold text-destructive">{tasks.filter(t => t.status === 'FAILED' || t.status === 'ERROR').length}</div>
            </div>
            <ShieldAlert className="w-8 h-8 text-destructive/30" strokeWidth={1} />
          </div>
        </div>

        {/* Top Dashboards: Gantt & Pipelines */}
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
          <div className="flex flex-col">
            <h2 className="text-xs font-mono font-bold tracking-widest text-muted-foreground mb-3 uppercase flex items-center gap-2">
              <Clock className="w-4 h-4" /> Live Execution Queue (Next 60s)
            </h2>
            <div className="flex-1 bg-card rounded-sm relative max-h-[250px] overflow-y-auto custom-scrollbar border-t border-border">
              {isLoading && <div className="p-4 text-center text-xs text-muted-foreground animate-pulse">Loading execution queue...</div>}
              {!isLoading && <TaskGanttChart tasks={runningTasks} />}
            </div>
          </div>

          <div className="flex flex-col">
            <h2 className="text-xs font-mono font-bold tracking-widest text-muted-foreground mb-3 uppercase flex items-center gap-2">
              <Workflow className="w-4 h-4" /> Active Pipeline
            </h2>
            <div className="flex-1 rounded-sm relative border-t border-border min-h-[150px] flex items-center justify-center">
              <div className="text-xs text-muted-foreground font-mono">No active pipeline running</div>
            </div>
          </div>
        </div>

        <div className="rounded-sm border border-border bg-card shadow-2xl overflow-x-auto custom-scrollbar mt-6">
          <table className="w-full min-w-[950px] text-left whitespace-nowrap table-fixed">
            <thead className="bg-[#151515]/90 border-b border-border text-[10px] uppercase font-mono tracking-widest font-bold text-muted-foreground sticky top-0 backdrop-blur-sm z-10">
              <tr>
                <th className="px-4 py-3 w-[120px] cursor-pointer select-none hover:text-foreground transition-colors" onClick={() => toggleSort('status')}>
                  Status {sortField === 'status' && (sortDir === 'asc' ? '↑' : '↓')}
                </th>
                <th className="px-4 py-3 w-[250px] cursor-pointer select-none hover:text-foreground transition-colors" onClick={() => toggleSort('name')}>
                  Task Name {sortField === 'name' && (sortDir === 'asc' ? '↑' : '↓')}
                </th>
                <th className="px-4 py-3 w-[150px]">Устройство</th>
                <th className="px-4 py-3 w-[120px] cursor-pointer select-none hover:text-foreground transition-colors" onClick={() => toggleSort('type')}>
                  Engine {sortField === 'type' && (sortDir === 'asc' ? '↑' : '↓')}
                </th>
                <th className="px-4 py-3 w-[150px]">Crontab / Trigger</th>
                <th className="px-4 py-3 w-[150px] cursor-pointer select-none hover:text-foreground transition-colors" onClick={() => toggleSort('lastRun')}>
                  Last Execution {sortField === 'lastRun' && (sortDir === 'asc' ? '↑' : '↓')}
                </th>
                <th className="px-4 py-3 w-[150px]">Next Projected</th>
                <th className="px-4 py-3 w-[100px] text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#222]/50 font-mono text-xs text-foreground/80">
              {isLoading && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-muted-foreground">Loading tasks...</td>
                </tr>
              )}
              {!isLoading && pagedTasks.map((task) => (
                <tr key={task.id} onClick={() => router.push(`/tasks/${task.id}`)} className="hover:bg-muted transition-colors border-l-2 border-l-transparent group cursor-pointer">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {(task.status === 'ACTIVE' || task.status === 'RUNNING') && <div className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />}
                      {(task.status === 'PAUSED' || task.status === 'QUEUED' || task.status === 'ASSIGNED') && <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground" />}
                      {(task.status === 'ERROR' || task.status === 'FAILED') && <div className="w-1.5 h-1.5 rounded-full bg-destructive animate-pulse" />}
                      {(task.status === 'COMPLETED' || task.status === 'SUCCESS') && <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />}
                      {task.status === 'TIMEOUT' && <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />}
                      {task.status === 'CANCELLED' && <div className="w-1.5 h-1.5 rounded-full bg-zinc-500" />}
                      <span className={`text-[10px] font-bold tracking-widest ${
                        (task.status === 'ACTIVE' || task.status === 'RUNNING') ? 'text-success' :
                        (task.status === 'ERROR' || task.status === 'FAILED') ? 'text-destructive' :
                        (task.status === 'COMPLETED' || task.status === 'SUCCESS') ? 'text-emerald-500' :
                        task.status === 'TIMEOUT' ? 'text-amber-500' :
                        task.status === 'CANCELLED' ? 'text-zinc-500' :
                        'text-muted-foreground'
                        }`}>{task.status}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="font-bold text-foreground group-hover:text-primary transition-colors text-xs">{task.name}</div>
                    <div className="text-[10px] text-[#555] font-mono mt-0.5">{task.id}</div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="text-xs text-foreground/80 font-mono truncate">{task.device_name || task.id.slice(0, 8)}</div>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="outline" className={`text-[9px] bg-black ${task.type === 'CRON' ? 'border-primary text-primary' :
                      task.type === 'WORKFLOW' ? 'border-[#ff00ff] text-[#ff00ff]' :
                        'border-warning text-warning'
                      }`}>
                      {task.type}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-[#777] font-mono">{task.schedule}</td>
                  <td className="px-4 py-3 text-[#777] font-mono">{task.lastRun}</td>
                  <td className="px-4 py-3 font-bold text-[#aaa]">{task.nextRun}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      {/* Retry / Re-run */}
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 text-muted-foreground hover:text-success hover:bg-success/10 rounded-sm"
                        title="Перезапустить задачу"
                        onClick={(e) => handleRetry(task, e)}
                        disabled={retryTask.isPending}
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Пагинация + итого */}
        <div className="flex items-center justify-between px-1 pt-3 text-xs font-mono text-muted-foreground">
          <span>
            {filteredTasks.length} задач{statusFilter !== 'ALL' ? ` (${statusFilter})` : ''}
          </span>
          {totalPages > 1 && (
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="icon" className="h-7 w-7" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                <ChevronLeft className="w-4 h-4" />
              </Button>
              <span>{page} / {totalPages}</span>
              <Button variant="ghost" size="icon" className="h-7 w-7" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                <ChevronRight className="w-4 h-4" />
              </Button>
            </div>
          )}
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
