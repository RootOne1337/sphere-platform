'use client';

import { use, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  Activity, ActivitySquare, ArrowLeft, Ban, Box, Camera, CheckCircle2,
  ChevronRight, Clock, FileCode2, Flag, GitBranch, Hand, Home, Keyboard,
  ListOrdered, Loader2, MonitorSmartphone, MousePointer2, Play, RotateCcw,
  Search, Settings2, Square, Terminal, Timer, XCircle, type LucideIcon,
} from 'lucide-react';
import {
  useTask, useTaskLogs, useCancelTask, useStopTask, useTaskProgress,
  useRetryTask, useTaskLiveLogs, type NodeExecutionLog, type LiveLogEntry,
} from '@/lib/hooks/useTasks';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { TaskScreenshot } from '@/components/tasks/TaskScreenshot';
import { PageFrame } from '@/src/shared/ui/page-layout';
import { isCancellationPending } from '@/lib/task-status';
import { getApiErrorMessage } from '@/lib/apiError';

interface Props {
  params: Promise<{ id: string }>;
}

const STATUS_CONFIG: Record<string, { label: string; className: string }> = {
  queued: { label: 'В очереди', className: 'border-warning/30 bg-warning/10 text-warning' },
  assigned: { label: 'Назначено', className: 'border-primary/30 bg-primary/10 text-primary' },
  running: { label: 'Выполняется', className: 'border-primary/30 bg-primary/10 text-primary' },
  completed: { label: 'Завершено', className: 'border-success/30 bg-success/10 text-success' },
  failed: { label: 'Ошибка', className: 'border-destructive/30 bg-destructive/10 text-destructive' },
  cancelled: { label: 'Отменено', className: 'border-border bg-muted text-muted-foreground' },
  timeout: { label: 'Таймаут', className: 'border-warning/30 bg-warning/10 text-warning' },
};

const ACTION_CONFIG: Record<string, { icon: LucideIcon; label: string }> = {
  start: { icon: Play, label: 'Начало' },
  end: { icon: Flag, label: 'Завершение' },
  sleep: { icon: Timer, label: 'Пауза' },
  condition: { icon: GitBranch, label: 'Условие' },
  tap: { icon: MousePointer2, label: 'Нажатие' },
  find_element: { icon: Search, label: 'Поиск элемента' },
  swipe: { icon: Hand, label: 'Свайп' },
  input_text: { icon: Keyboard, label: 'Ввод текста' },
  screenshot: { icon: Camera, label: 'Снимок экрана' },
  launch_app: { icon: MonitorSmartphone, label: 'Запуск приложения' },
  back: { icon: ArrowLeft, label: 'Назад' },
  home: { icon: Home, label: 'Главный экран' },
  scroll: { icon: ListOrdered, label: 'Прокрутка' },
};

export default function TaskDetailPage({ params }: Props) {
  const { id } = use(params);
  return <OwnedTaskDetail key={id} id={id} />;
}

function httpStatus(error: unknown): number | undefined {
  return (error as { response?: { status?: number } } | null)?.response?.status;
}

function taskReadTitle(error: unknown): string {
  switch (httpStatus(error)) {
    case 404: return 'Задание не найдено';
    case 401: return 'Требуется вход в систему';
    case 403: return 'Нет доступа к заданию';
    default: return 'Не удалось загрузить задание';
  }
}

function reportedLogs(value: unknown): NodeExecutionLog[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.filter((log): log is NodeExecutionLog => log !== null && typeof log === 'object'
    && typeof log.node_id === 'string' && typeof log.action_type === 'string' && typeof log.success === 'boolean');
}

function reportedCount(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined;
}

function OwnedTaskDetail({ id }: { id: string }) {
  const taskQuery = useTask(id);
  const { data: task, isLoading } = taskQuery;
  const logsQuery = useTaskLogs(id);
  const cancelTask = useCancelTask();
  const stopTask = useStopTask();
  const createTask = useRetryTask();
  const [receipt, setReceipt] = useState<string | null>(null);
  const [newTaskId, setNewTaskId] = useState<string | null>(null);
  const writesPending = cancelTask.isPending || stopTask.isPending || createTask.isPending;
  const canAct = taskQuery.isSuccess && !taskQuery.isFetching && !writesPending;
  const actionError = stopTask.error ?? cancelTask.error ?? createTask.error;
  const beginAction = () => {
    stopTask.reset(); cancelTask.reset(); createTask.reset(); setReceipt(null); setNewTaskId(null);
  };

  const isActive = task ? ['queued', 'assigned', 'running'].includes(task.status) : false;
  const progressQuery = useTaskProgress(id, isActive && taskQuery.isSuccess);
  const liveLogsQuery = useTaskLiveLogs(id, isActive && taskQuery.isSuccess);
  const { data: liveProgress } = progressQuery;
  const { data: liveLogs } = liveLogsQuery;

  const resultNodeLogs = reportedLogs(task?.result?.node_logs);
  const logs = reportedLogs(logsQuery.data) ?? resultNodeLogs;
  const successfulReports = logs?.filter((log) => log.success).length ?? 0;
  const failedReports = logs?.filter((log) => !log.success).length ?? 0;

  if (isLoading) {
    return <PageFrame className="max-w-6xl"><div className="flex min-h-[50vh] items-center justify-center gap-3 text-sm text-muted-foreground" aria-busy="true">
      <Loader2 className="h-5 w-5 animate-spin motion-reduce:animate-none" aria-hidden="true" />Загрузка задания…
    </div></PageFrame>;
  }

  if (!task) {
    return <PageFrame className="max-w-6xl"><div className="mx-auto flex min-h-[50vh] w-full max-w-lg flex-col justify-center gap-4">
      <div className="space-y-4 rounded-xl border bg-card p-5 sm:p-6">
        <XCircle className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
        <h1 className="text-lg font-semibold" role="alert">{taskReadTitle(taskQuery.error)}</h1>
        <p className="text-sm leading-6 text-muted-foreground">{httpStatus(taskQuery.error) === 404 ? 'API подтвердил отсутствие записи.' : 'Данные задания не получены; команды недоступны.'}</p>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => void taskQuery.refetch()} disabled={taskQuery.isFetching}>Повторить загрузку задания</Button>
          <Button asChild variant="outline"><Link href="/tasks"><ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />К заданиям</Link></Button>
        </div>
      </div>
    </div></PageFrame>;
  }

  const statusCfg = STATUS_CONFIG[task.status];
  const result = task.result as Record<string, unknown> | null;
  // Cached live telemetry describes an active run, not its confirmed final outcome.
  const nodesExecuted = (isActive ? reportedCount(liveProgress?.nodes_done) : undefined) ?? reportedCount(result?.nodes_executed);
  const totalNodes = (isActive ? reportedCount(liveProgress?.total_nodes) : undefined) ?? reportedCount(result?.total_nodes);
  const cycles = (isActive ? reportedCount(liveProgress?.cycles) : undefined) ?? reportedCount(result?.cycles);
  const currentNode = isActive ? liveProgress?.current_node ?? '' : '';
  const failedNode = typeof result?.failed_node === 'string' ? result.failed_node : undefined;
  const cancellationPending = isCancellationPending(task);
  const statusLabel = cancellationPending
    ? task.timeout_requested_at ? 'Таймаут: ожидается результат устройства' : 'Отмена: ожидается результат устройства'
    : statusCfg?.label ?? task.status;
  const elapsedMs = isActive && liveProgress?.started_at
    ? Date.now() - liveProgress.started_at * 1000
    : task.started_at
      ? (task.finished_at ? Date.parse(task.finished_at) : isActive ? Date.now() : NaN) - Date.parse(task.started_at)
      : NaN;

  return (
    <PageFrame className="max-w-6xl gap-5">
      <nav aria-label="Навигация задания">
        <Button asChild variant="ghost" size="sm" className="-ml-3 text-muted-foreground"><Link href="/tasks"><ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />Все задания</Link></Button>
      </nav>
      {taskQuery.isError && <div role="alert" className="space-y-3 rounded-xl border border-destructive/30 bg-card p-4">
        <h2 className="font-semibold">{taskReadTitle(taskQuery.error)}</h2>
        <p className="text-sm">Показан предыдущий снимок задания. Команды заблокированы до успешного чтения.</p>
        <p className="text-xs text-muted-foreground">Последнее подтверждение: {new Date(taskQuery.dataUpdatedAt).toLocaleString('ru-RU')}</p>
        <Button variant="outline" onClick={() => void taskQuery.refetch()} disabled={taskQuery.isFetching}>Повторить загрузку задания</Button>
      </div>}
      {actionError && <div role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm">
        {getApiErrorMessage(actionError, 'Команда не выполнена. Проверьте связь и права доступа, затем повторите действие.')}
      </div>}
      {receipt && <div role="status" className="rounded-xl border border-primary/20 bg-primary/5 p-4 text-sm leading-6">
        {receipt}{newTaskId && <Link href={`/tasks/${newTaskId}`} className="ml-2 font-medium text-primary underline underline-offset-4">Открыть новое задание</Link>}
      </div>}

      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-2">
          <p className="text-xs font-medium text-muted-foreground">Автоматизация / выполнение</p>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">Выполнение сценария</h1>
            <Badge variant="outline" className={`max-w-full whitespace-normal ${statusCfg?.className ?? 'bg-muted text-muted-foreground'}`}>
              {statusLabel}
            </Badge>
          </div>
          <p className="break-all font-mono text-xs leading-5 text-muted-foreground"><span className="font-sans">Задание: </span>{task.id}</p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {task.status === 'running' && <Button
            variant="destructive"
            onClick={() => {
              if (!canAct || isCancellationPending(task)) return;
              beginAction();
              stopTask.mutate(task.id, { onSuccess: () => setReceipt('Запрос остановки принят. Окончательный статус ожидается от устройства.') });
            }}
            disabled={!canAct || cancellationPending}
          >
            <Square className="mr-2 h-4 w-4" aria-hidden="true" />
            {cancellationPending ? 'Ожидается результат' : stopTask.isPending ? 'Отправка запроса…' : 'Остановить задание'}
          </Button>}
          {['queued', 'assigned'].includes(task.status) && <Button
            variant="destructive"
            onClick={() => {
              if (!canAct || isCancellationPending(task)) return;
              beginAction();
              cancelTask.mutate(task.id, { onSuccess: () => setReceipt('Запрос отмены принят. Итоговый статус будет подтверждён сервером и устройством.') });
            }}
            disabled={!canAct || cancellationPending}
          >
            <Ban className="mr-2 h-4 w-4" aria-hidden="true" />
            {cancellationPending ? 'Ожидается результат' : cancelTask.isPending ? 'Отправка запроса…' : 'Отменить задание'}
          </Button>}
          {['completed', 'failed', 'cancelled', 'timeout'].includes(task.status) && <Button
            disabled={!canAct || !task.script_version_id}
            onClick={() => {
              if (!canAct || !task.script_version_id) return;
              beginAction();
              createTask.mutate(task.id, { onSuccess: (data) => {
                setReceipt('Сервер принял запрос нового задания. Результат выполнения ещё не подтверждён.');
                setNewTaskId(typeof data?.id === 'string' ? data.id : null);
              } });
            }}
          >
            <RotateCcw className={`mr-2 h-4 w-4 ${createTask.isPending ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
            {createTask.isPending ? 'Создание задания…' : 'Повторить выполнение'}
          </Button>}
        </div>
      </header>

      <section aria-label="Контекст задания" className="rounded-xl border bg-card p-4 sm:p-5">
        <div className="grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2">
          <InfoCard icon={FileCode2} label="Сценарий" value={task.script_name || task.script_id} />
          <InfoCard icon={MonitorSmartphone} label="Устройство" value={task.device_name || task.device_id} />
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 border-t pt-4 sm:grid-cols-2 lg:grid-cols-4">
          <InfoCard icon={GitBranch} label="Версия сценария" value={task.script_version_id ?? 'неизвестна — повтор недоступен'} isMono />
          <InfoCard icon={ActivitySquare} label="Приоритет" value={String(task.priority)} />
          <InfoCard icon={Box} label="Пакет заданий" value={task.batch_id || 'Не входит в пакет'} isMono />
          {task.wave_index != null && <InfoCard icon={ListOrdered} label="Индекс волны" value={String(task.wave_index)} />}
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 border-t pt-4 sm:grid-cols-2 lg:grid-cols-4">
          <InfoCard icon={Clock} label="Создано" value={formatDateTime(task.created_at)} />
          <InfoCard icon={Play} label="Начало" value={formatDateTime(task.started_at)} />
          <InfoCard icon={CheckCircle2} label="Завершение" value={formatDateTime(task.finished_at)} />
          <InfoCard icon={Timer} label="Длительность" value={getDuration(task.started_at, task.finished_at, isActive)} />
        </div>
        {!isActive && <p className="mt-4 border-t pt-4 text-xs leading-5 text-muted-foreground">
          Повтор создаёт отдельное задание с исходной версией сценария, входными параметрами и таймаутом. Привязка к старому пакету и его результаты не переносятся.
        </p>}
      </section>

      {task.input_params && Object.keys(task.input_params).length > 0 && <section aria-labelledby="input-parameters-title" className="rounded-xl border bg-card p-4 sm:p-5">
        <h2 id="input-parameters-title" className="mb-4 flex items-center gap-2 text-sm font-semibold"><Terminal className="h-4 w-4 text-muted-foreground" aria-hidden="true" />Входные параметры</h2>
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(task.input_params).map(([key, val]) => <div key={key} className="min-w-0 rounded-lg border bg-muted/30 p-3">
            <dt className="break-all font-mono text-xs text-muted-foreground">{key}</dt>
            <dd className="mt-1 break-all font-mono text-sm text-foreground">{typeof val === 'object' && val !== null ? JSON.stringify(val) : String(val)}</dd>
          </div>)}
        </dl>
      </section>}
      {typeof result?.final_screenshot_key === 'string' && result.final_screenshot_key &&
        <TaskScreenshot taskId={id} screenshotKey={result.final_screenshot_key} label="Итоговый снимок задания" />}

      {task.error_message && <section aria-label="Ошибка выполнения" className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" aria-hidden="true" />
          <div className="min-w-0 flex-1"><h2 className="font-semibold text-destructive">Ошибка выполнения</h2>
            <pre className="mt-3 whitespace-pre-wrap break-words rounded-lg border border-destructive/20 bg-background p-3 font-mono text-xs leading-5 text-foreground">{task.error_message}</pre>
          </div>
        </div>
      </section>}

      <div className={`grid min-w-0 grid-cols-1 gap-5 ${isActive ? 'lg:grid-cols-3' : ''}`}>
        <div className={`min-w-0 space-y-5 ${isActive ? 'lg:col-span-2' : ''}`}>
          <section aria-labelledby="execution-summary-title" className="rounded-xl border bg-card p-4 sm:p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h2 id="execution-summary-title" className="flex items-center gap-2 text-base font-semibold"><Activity className="h-4 w-4 text-muted-foreground" aria-hidden="true" />{isActive ? 'Текущий прогресс' : 'Итог выполнения'}</h2>
              <span className="font-mono text-sm tabular-nums text-muted-foreground">{formatElapsed(elapsedMs)}</span>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <MetricCard label="Выполнено узлов" value={nodesExecuted == null ? '—' : String(nodesExecuted)} />
              <MetricCard label="Циклы" value={cycles == null ? '—' : String(cycles)} />
              <MetricCard label="Всего узлов" value={totalNodes == null ? '—' : String(totalNodes)} />
              <MetricCard label="Успешные отчёты" value={logs == null ? '—' : logs.length ? `${successfulReports}/${logs.length}` : 'Нет отчётов'} />
            </div>
            <p className="mt-3 text-xs leading-5 text-muted-foreground">Успешность относится к полученным отчётам шагов; полнота выполнения по ним не подтверждается.</p>
            {!isActive && <p className="mt-1 text-xs leading-5 text-muted-foreground">Числа узлов и циклов получены из итогового результата задания. «—» означает, что значение не сообщено.</p>}
            {isActive && progressQuery.isError && <p role="alert" className="mt-3 text-sm text-warning">Не удалось обновить прогресс; показаны последние полученные значения.</p>}
            {isActive && currentNode && <div className="mt-4 rounded-lg border bg-muted/30 p-3">
              <p className="text-xs text-muted-foreground">Текущий узел</p><p className="mt-1 break-all font-mono text-sm">{currentNode}</p>
            </div>}
            {isActive && task.status !== 'running' && <p className="mt-4 rounded-lg border bg-muted/30 p-3 text-sm leading-6 text-muted-foreground">
              {task.status === 'queued' ? 'Задание ожидает назначения устройству.' : 'Задание назначено устройству. Ожидается подтверждение начала выполнения.'}
            </p>}
          </section>

          {!isActive && <section aria-labelledby="execution-timeline-title" className="overflow-hidden rounded-xl border bg-card">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b p-4 sm:px-5">
              <h2 id="execution-timeline-title" className="flex items-center gap-2 text-base font-semibold"><Terminal className="h-4 w-4 text-muted-foreground" aria-hidden="true" />Отчёты шагов</h2>
              {!!logs?.length && <p className="text-xs tabular-nums text-muted-foreground">{successfulReports} успешных · {failedReports} ошибок · {logs.length} получено</p>}
            </div>
            <div className="p-4 sm:p-5">
              {logsQuery.isError && <div role="alert" className="mb-4 space-y-2 text-sm text-destructive">
                <p>Не удалось обновить отчёты шагов.{logs?.length ? ' Показаны ранее полученные данные.' : ' Отсутствие отчётов не подтверждено.'}</p>
                <Button variant="outline" onClick={() => void logsQuery.refetch()} disabled={logsQuery.isFetching}>Повторить загрузку отчётов</Button>
              </div>}
              {logsQuery.data == null && resultNodeLogs && <p className="mb-3 text-xs text-muted-foreground">Источник: последний снимок результата задания.</p>}
              {(!logs || logs.length === 0) ? (!logsQuery.isError && <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed px-4 py-10 text-center text-muted-foreground">
                <ActivitySquare className="h-8 w-8" aria-hidden="true" /><p className="text-sm">{logsQuery.isLoading ? 'Загрузка отчётов шагов…' : 'Отчёты шагов не получены.'}</p>
              </div>) : <ol className="space-y-3">{logs.map((log, i) => <LogEntry key={i} taskId={id} log={log} isFailed={log.node_id === failedNode} />)}</ol>}
            </div>
          </section>}

          {result && !isActive && <section className="min-w-0 overflow-hidden rounded-xl border bg-card">
            <details className="group">
              <summary className="flex cursor-pointer list-none items-center gap-2 p-4 text-sm font-semibold transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:px-5">
                <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90 motion-reduce:transition-none" aria-hidden="true" />
                <FileCode2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />Итоговый результат (JSON)
              </summary>
              <div className="overflow-x-auto border-t bg-muted/30"><pre className="p-4 font-mono text-xs leading-6 text-foreground sm:p-5">{JSON.stringify(result, null, 2)}</pre></div>
            </details>
          </section>}
        </div>

        {isActive && <aside aria-labelledby="live-log-title" className="min-w-0 space-y-3">
          <section className="overflow-hidden rounded-xl border bg-card">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b p-4">
              <h2 id="live-log-title" className="flex items-center gap-2 text-sm font-semibold"><Terminal className="h-4 w-4 text-muted-foreground" aria-hidden="true" />Журнал выполнения</h2>
              {liveLogs && <Badge variant="secondary" className="font-normal tabular-nums">Событий: {liveLogs.length}</Badge>}
            </div>
            <div className="max-h-[32rem] overflow-y-auto p-4">
              {liveLogsQuery.isError && <p role="alert" className="mb-3 text-sm leading-5 text-destructive">{liveLogs ? 'Журнал не обновлён; показан предыдущий снимок.' : 'Не удалось загрузить журнал выполнения.'}</p>}
              {liveLogs ? <LiveLogTimeline entries={liveLogs} /> : !liveLogsQuery.isError && <p className="py-6 text-center text-sm text-muted-foreground">{liveLogsQuery.isLoading ? 'Загрузка журнала…' : 'Ожидание событий устройства…'}</p>}
            </div>
          </section>
          {logsQuery.isError && <p role="alert" className="rounded-xl border border-destructive/30 bg-card p-4 text-sm leading-6">Отчёты шагов не обновлены; успешность выполнения не подтверждена.</p>}
        </aside>}
      </div>
    </PageFrame>
  );
}

function InfoCard({ icon: Icon, label, value, isMono }: { icon: LucideIcon; label: string; value: string; isMono?: boolean }) {
  return <dl className="min-w-0">
    <dt className="flex items-center gap-2 text-xs text-muted-foreground"><Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />{label}</dt>
    <dd className={`mt-1.5 break-words text-sm leading-5 text-foreground ${isMono ? 'break-all font-mono text-xs' : 'font-medium'}`}>{value}</dd>
  </dl>;
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 rounded-lg border bg-muted/30 p-3">
    <p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 break-words text-lg font-semibold tabular-nums text-foreground">{value}</p>
  </div>;
}

function LiveLogTimeline({ entries }: { entries: LiveLogEntry[] }) {
  const recent = useMemo(() => [...entries].reverse().slice(0, 100), [entries]);
  const deduped = useMemo(() => {
    const result: (LiveLogEntry & { count: number })[] = [];
    for (const e of recent) {
      const last = result[result.length - 1];
      if (last && last.node_id === e.node_id) last.count++;
      else result.push({ ...e, count: 1 });
    }
    return result;
  }, [recent]);

  if (deduped.length === 0) return <p className="py-6 text-center text-sm text-muted-foreground">Ожидание событий устройства…</p>;

  return <ol className="space-y-2">
    {deduped.map((entry, i) => <li key={i} className="rounded-lg border bg-muted/20 p-3">
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 break-all font-mono text-xs leading-5 text-foreground">{entry.node_id}</span>
        <span className="shrink-0 font-mono text-xs tabular-nums text-muted-foreground" title="Сообщённый счётчик узлов">#{entry.nodes_done}</span>
      </div>
      {entry.count > 1 && <p className="mt-1 text-xs text-muted-foreground">Повторений: {entry.count}</p>}
    </li>)}
  </ol>;
}

function LogEntry({ taskId, log, isFailed }: { taskId: string; log: NodeExecutionLog; isFailed: boolean }) {
  const action = ACTION_CONFIG[log.action_type];
  const Icon = action?.icon ?? Settings2;
  return <li className={`min-w-0 rounded-lg border p-3 sm:p-4 ${isFailed ? 'border-destructive/30 bg-destructive/5' : 'bg-muted/20'}`}>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex min-w-0 items-start gap-3">
        <span className="rounded-lg border bg-background p-2 text-muted-foreground"><Icon className="h-4 w-4" aria-hidden="true" /></span>
        <div className="min-w-0"><h3 className="break-all font-mono text-sm font-medium text-foreground">{log.node_id}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground" title={log.action_type}>{action?.label ?? log.action_type}</span>
            <Badge variant={log.success ? 'success' : 'outline'} className={`font-normal ${log.success ? '' : 'border-destructive/30 bg-destructive/10 text-destructive'}`}>{log.success ? 'Успешно' : 'Ошибка'}</Badge>
          </div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs tabular-nums text-muted-foreground">
        {log.duration_ms > 0 && <span className="font-mono">{log.duration_ms > 1000 ? `${(log.duration_ms / 1000).toFixed(2)} с` : `${log.duration_ms} мс`}</span>}
        {log.started_at && <span>{formatDateTime(log.started_at)}</span>}
      </div>
    </div>
    {log.error && <p className="mt-3 whitespace-pre-wrap break-words rounded-lg border border-destructive/20 bg-background p-3 font-mono text-xs leading-5 text-destructive">{log.error}</p>}
    {log.output != null && log.output !== '' && <details className="group/output mt-3 min-w-0 text-xs">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded py-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ChevronRight className="h-3.5 w-3.5 shrink-0 transition-transform group-open/output:rotate-90 motion-reduce:transition-none" aria-hidden="true" />Данные шага
      </summary>
      <pre className="mt-2 overflow-x-auto rounded-lg border bg-background p-3 font-mono text-xs leading-5 text-foreground">{typeof log.output === 'object' ? JSON.stringify(log.output, null, 2) : String(log.output)}</pre>
    </details>}
    {log.screenshot_key && <TaskScreenshot taskId={taskId} screenshotKey={log.screenshot_key} />}
    {log.action_type === 'screenshot' && !log.screenshot_key && <p className="mt-3 text-xs leading-5 text-muted-foreground">Файл снимка не получен сервером. Локальный путь Android в отчёте не является ссылкой на изображение.</p>}
  </li>;
}

function formatDateTime(value?: string | null): string {
  return value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('ru-RU') : '—';
}

function formatElapsed(ms: number): string {
  if (!Number.isFinite(ms)) return '—';
  if (ms <= 0) return '00:00:00';
  const totalSec = Math.floor(ms / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function getDuration(started?: string | null, finished?: string | null, isActive = false): string {
  if (!started || (!finished && !isActive)) return '—';
  const end = finished ? Date.parse(finished) : Date.now();
  return formatElapsed(end - Date.parse(started));
}
