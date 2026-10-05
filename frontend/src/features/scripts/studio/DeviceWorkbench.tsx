'use client';
import { useEffect, useRef, useState } from 'react';
import { isAxiosError } from 'axios';
import Link from 'next/link';
import { Circle, Square, Monitor, Play, Plus, Search, Radio, Trash2, CheckCheck, ExternalLink } from 'lucide-react';
import { useDevices, type Device } from '@/lib/hooks/useDevices';
import { useTask, useTaskLogs, useTaskProgress, useStopTask } from '@/lib/hooks/useTasks';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { useCapabilities } from '@/src/features/access/Capabilities';
import { SingleDeviceStream } from '@/src/features/stream/SingleDeviceStream';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/components/ui/input';
import type { DagNode } from '@/lib/dag/export';
import { appendRecording, recordingActions, type RecordedInput, type StreamInput } from './recording';
import { actionLabel } from './presentation';

interface Version { id: string; version: number; dag_hash: string | null }
interface Props { scriptId: string | null; version: Version | null; name: string; canRun: boolean; canEdit: boolean;
  onInsert: (actions: DagNode['action'][]) => boolean; onExecution: (lastCompleted: string | null, logs: { node_id: string; success: boolean }[]) => void;
  registerCloseGuard?: (guard: ((silent?: boolean) => boolean) | null) => void }
const terminal = new Set(['completed', 'failed', 'cancelled', 'timeout', 'timed_out']);

export function DeviceWorkbench(props: Props) {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const query = useDebounce(search.trim(), 300);
  const { data, isLoading, isError, isFetching, refetch } = useDevices({ page, page_size: 25, search: query || undefined });
  const [device, setDevice] = useState<Device | null>(null);
  const closeGuard = useRef<((silent?: boolean) => boolean) | null>(null);
  return <section aria-label="Рабочее устройство" className="flex h-full min-h-0 min-w-0 flex-col bg-card">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3"><div><h2 className="flex items-center gap-2 text-sm font-semibold"><Monitor className="size-4 text-primary" />Лаборатория устройства</h2><p className="mt-1 text-xs text-muted-foreground">Живое видео · запись жестов · XPath · проверка версии</p></div>
      {device && <Button size="sm" variant="outline" onClick={() => { if (!closeGuard.current || closeGuard.current()) setDevice(null); }}>Сменить устройство</Button>}</header>
    <div className="min-h-0 flex-1 overflow-auto p-4">
      {!device ? <div className="space-y-4"><div className="rounded-xl border border-dashed bg-muted/30 p-5"><h3 className="font-semibold">Выберите тестовый Android</h3><p className="mt-2 text-xs leading-5 text-muted-foreground">Откроется один поток. Действия управления изменяют выбранный Android; добавление шагов и серверная проверка сценария его не запускают.</p></div>
        <div className="relative"><Search className="absolute left-3 top-3 size-4 text-muted-foreground" /><Input aria-label="Найти тестовое устройство" placeholder="Имя, Android ID или модель" className="pl-9" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} /></div>
        {isError ? <div role="alert">Не удалось загрузить устройства. <Button size="sm" variant="outline" onClick={() => void refetch()}>Повторить</Button></div> : isLoading ? <p role="status">Загружаем устройства…</p> : <>
          <div className="space-y-2">{data?.items.map(item => <button key={item.id} type="button" disabled={!['online', 'busy'].includes(item.status) || isFetching || search.trim() !== query} onClick={() => setDevice(item)} className="flex w-full items-center gap-3 rounded-xl border p-3 text-left transition-colors hover:border-primary/50 hover:bg-primary/5 disabled:opacity-50">
            <span className={`size-2 rounded-full ${item.status === 'online' ? 'bg-emerald-500' : item.status === 'busy' ? 'bg-amber-500' : 'bg-muted-foreground'}`} /><div className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold">{item.name}</span><span className="block truncate text-xs text-muted-foreground">{item.model || item.device_model || 'Модель не сообщается'} · Agent {item.agent_version ?? '—'}</span></div><span className="text-[10px] text-muted-foreground">{item.status}</span><Plus className="size-4 text-primary" /></button>)}</div>
          {!data?.items.length && <p className="text-sm text-muted-foreground">Устройства не найдены.</p>}
          <div className="flex items-center justify-between gap-2 text-xs"><Button size="sm" variant="outline" disabled={page <= 1 || isFetching} onClick={() => setPage(page - 1)}>Назад</Button><span>{page} / {data?.pages || 1} · всего {data?.total ?? '—'}</span><Button size="sm" variant="outline" disabled={page >= (data?.pages ?? 1) || isFetching} onClick={() => setPage(page + 1)}>Далее</Button></div>
        </>}
      </div> : <OwnedWorkbench key={device.id} {...props} registerCloseGuard={guard => { closeGuard.current = guard; props.registerCloseGuard?.(guard); }} device={device} />}
    </div>
  </section>;
}
function OwnedWorkbench({ device, scriptId, version, name, canRun, canEdit, onInsert, onExecution, registerCloseGuard }: Props & { device: Device }) {
  const access = useCapabilities();
  const [recording, setRecording] = useState(false);
  const [preservePauses, setPreservePauses] = useState(true);
  const [entries, setEntries] = useState<RecordedInput[]>([]);
  const entriesRef = useRef(entries); entriesRef.current = entries;
  const [error, setError] = useState('');
  const [taskId, setTaskId] = useState('');
  const [runPending, setRunPending] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [ownedVersion, setOwnedVersion] = useState<string | null>(null);
  const live = useRef(true), runningRequest = useRef(false);
  const accessRef = useRef(access); accessRef.current = access;
  const task = useTask(taskId);
  const ownsTask = task.data?.device_id === device.id && task.data?.script_id === scriptId && task.data?.script_version_id === ownedVersion;
  const active = Boolean(taskId && (!task.data || !ownsTask || !terminal.has(task.data.status)));
  const progress = useTaskProgress(taskId, active && ownsTask);
  const logs = useTaskLogs(taskId);
  const stop = useStopTask();
  useEffect(() => { registerCloseGuard?.((silent = false) => {
    const guarded = Boolean(entries.length || active || runPending || uncertain);
    if (silent) return !guarded;
    if (uncertain) {
      setError('Результат запуска неизвестен. Проверьте журнал заданий: переключение устройства заблокировано, чтобы не создать повторное выполнение.');
      return false;
    }
    return guarded ? window.confirm('Закрыть устройство? Невставленная запись будет потеряна. Созданное задание продолжит работу; его можно открыть в разделе заданий.') : true;
  }); return () => registerCloseGuard?.(null); }, [entries.length, active, runPending, uncertain, registerCloseGuard]);
  useEffect(() => { live.current = true; return () => { live.current = false; onExecution(null, []); }; }, [onExecution]);
  useEffect(() => { if (!canEdit || !access.can('stream:control')) setRecording(false); }, [canEdit, access]);
  useEffect(() => {
    if (!ownsTask || version?.id !== ownedVersion || !canRun) { onExecution(null, []); return; }
    onExecution(progress.data?.current_node ?? null, logs.data ?? []);
  }, [ownsTask, ownedVersion, version?.id, canRun, progress.data, logs.data, onExecution]);
  const sent = (input: StreamInput) => {
    if (!recording || !canEdit || !accessRef.current.can('stream:control')) return;
    try { const next = appendRecording(entriesRef.current, input, device.id); entriesRef.current = next; setEntries(next); }
    catch (reason) { setRecording(false); setError(reason instanceof Error ? reason.message : 'Не удалось записать ввод.'); }
  };
  async function run() {
    if (runningRequest.current || uncertain || active || !canRun || !scriptId || !version?.dag_hash || !accessRef.current.can('script:execute')) return;
    const pinned = version.id;
    runningRequest.current = true; setRunPending(true); setRecording(false); setError('');
    try {
      const { data } = await api.post('/tasks', { script_id: scriptId, device_id: device.id, expected_current_version_id: pinned, priority: 5 }, { timeout: 30000 });
      if (!live.current) return;
      if (!data?.id || data.device_id !== device.id || data.script_id !== scriptId || data.script_version_id !== pinned) throw new Error('Ответ создания задания не подтверждает выбранную цель и версию.');
      setOwnedVersion(pinned); setTaskId(data.id);
    } catch (reason) { if (live.current) { setUncertain(!(isAxiosError(reason) && reason.response && reason.response.status >= 400 && reason.response.status < 500)); setError(getApiErrorMessage(reason, 'Запуск не подтверждён. Проверьте задания перед повтором: автоматического повтора нет.')); } }
    finally { runningRequest.current = false; if (live.current) setRunPending(false); }
  }
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border bg-muted/30 p-3"><div className="min-w-0 flex-1 basis-48"><p className="break-words text-sm font-semibold [overflow-wrap:anywhere]">{device.name}</p><p className="mt-1 break-words text-xs text-muted-foreground [overflow-wrap:anywhere]">Android {device.android_version ?? '—'} · Agent {device.agent_version ?? '—'}</p></div><Link href={`/devices/${device.id}`} className="flex shrink-0 items-center gap-1 text-xs text-primary">Карточка <ExternalLink className="size-3" /></Link></div>
    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap"><Button size="sm" className="h-auto min-h-8 min-w-0 whitespace-normal" variant={recording ? 'destructive' : 'outline'} disabled={!canEdit || active || runPending || uncertain || !access.can('stream:control')} onClick={() => setRecording(!recording)}>{recording ? <Square className="mr-2 size-3 shrink-0" /> : <Circle className="mr-2 size-3 shrink-0 text-rose-500" />}{recording ? 'Остановить запись' : 'Записать жесты'}</Button>
      <Button size="sm" className="h-auto min-h-8 min-w-0 whitespace-normal" disabled={!canRun || active || runPending || recording || uncertain} onClick={() => void run()}><Play className="mr-2 size-3 shrink-0" /><span className="min-w-0 break-words [overflow-wrap:anywhere]">{runPending ? 'Создаём задание…' : `Проверить на ${device.name}`}</span></Button>
      {active && <Button size="sm" variant="outline" disabled={stop.isPending || !access.can('script:execute')} onClick={() => stop.mutate(taskId, { onError: reason => setError(getApiErrorMessage(reason, 'Остановка не подтверждена.')) })}>Остановить задание</Button>}</div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 p-3 text-xs text-destructive">{error} {uncertain && <Link href="/tasks" className="underline">Открыть задания</Link>}</p>}
    {!canRun && <p className="text-xs text-muted-foreground">Для проверки сохраните сценарий и откройте его неизменённую версию. Запуск всегда создаёт одно реальное задание на выбранном Android.</p>}
    <SingleDeviceStream deviceId={device.id} captureEnabled compact controlDisabled={active || runPending || uncertain} onControlSent={sent} onInsertSelector={canEdit && !active && !runPending && !uncertain ? (node, snapshot) => {
      if (snapshot.device_id !== device.id) return;
      onInsert([{ type: 'tap_element', selector: node.xpath, strategy: 'xpath', timeout_ms: 5000 }]);
    } : undefined} />
    <div className="rounded-xl border"><header className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2"><h3 className="flex items-center gap-2 text-xs font-semibold"><Radio className={`size-3 ${recording ? 'text-rose-500' : 'text-muted-foreground'}`} />Запись · {entries.length}/200</h3><div className="flex gap-1"><Button size="sm" variant="ghost" disabled={!entries.length || recording} onClick={() => setEntries([])} aria-label="Очистить запись"><Trash2 className="size-3" /></Button><Button size="sm" variant="outline" disabled={!entries.length || recording || !canEdit} onClick={() => { try { if (onInsert(recordingActions(entries, preservePauses))) setEntries([]); } catch (reason) { setError(reason instanceof Error ? reason.message : 'Запись не перенесена.'); } }}>Вставить в граф</Button></div></header>
      <label className="flex items-center gap-2 px-3 pt-3 text-xs"><input type="checkbox" checked={preservePauses} disabled={recording} onChange={event => setPreservePauses(event.target.checked)} />Сохранять паузы между жестами (до 60 с)</label>
      <p className="px-3 py-2 text-[11px] leading-5 text-muted-foreground">Записываются клики, свайпы и колесо, отправленные по WebSocket. Это подтверждение отправки, не выполнения Android. Координаты привязаны к ориентации записи; для устойчивого сценария выбирайте XPath. Текст и системные кнопки этой записью не захватываются.</p>
      {!!entries.length && <ol className="max-h-40 overflow-auto px-3 pb-3">{entries.map((entry, index) => <li key={entry.id} className="flex items-center justify-between border-t py-2 text-xs"><span>{index + 1}. {entry.command.type === 'click' ? 'Нажатие' : 'Свайп'} · {entry.dimensions.width}×{entry.dimensions.height}</span><span className="text-[10px] text-muted-foreground">Отправлено</span></li>)}</ol>}
    </div>
    {taskId && <div className="rounded-xl border p-3"><h3 className="flex items-center gap-2 text-sm font-semibold"><CheckCheck className="size-4 text-primary" />Проверка {name}</h3><Link href={`/tasks/${taskId}`} className="mt-2 block break-all font-mono text-xs text-primary">{taskId}</Link>
      {task.isError || !ownsTask ? <p role="status" className="mt-2 text-xs">Ожидаем подтверждённое состояние выбранного задания…</p> : <><p className="mt-2 text-xs">{task.data!.status} · {terminal.has(task.data!.status)
        ? logs.isError ? 'Итоговые отчёты недоступны' : logs.data ? `отчёты шагов: ${logs.data.length}` : 'Ожидаем итоговые отчёты шагов'
        : progress.data ? `${progress.data.nodes_done}/${progress.data.total_nodes} шагов` : 'Прогресс пока не сообщается'}</p>
        <p className="mt-2 text-[11px] text-muted-foreground">Подсвечивается последний обработанный шаг, сообщённый APK. Прогресс проверяется каждые 2 с; видео и события не имеют покадровой синхронизации.</p>
        {logs.isError ? <p role="alert" className="mt-2 text-xs">Логи задания недоступны.</p> : <ol className="mt-3 max-h-48 overflow-auto text-xs">{logs.data?.map((log, index) => <li key={`${log.node_id}:${index}`} className="flex flex-wrap justify-between gap-2 border-t py-2"><span className={log.success ? 'text-emerald-600 dark:text-emerald-400' : 'text-destructive'}>{log.success ? '✓' : '×'} {log.node_id} · {actionLabel(log.action_type)}</span><span>{log.duration_ms} мс</span></li>)}</ol>}</>}
    </div>}
  </div>;
}
