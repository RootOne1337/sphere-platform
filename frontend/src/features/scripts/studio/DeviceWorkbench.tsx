'use client';
import { useEffect, useRef, useState } from 'react';
import { isAxiosError } from 'axios';
import Link from 'next/link';
import { Circle, Square, Monitor, Play, Plus, Search, Radio, Trash2, CheckCheck, ExternalLink } from 'lucide-react';
import { useDevices, type Device } from '@/lib/hooks/useDevices';
import { useTask, useTaskLogs, useTaskProgress, useStopTask } from '@/lib/hooks/useTasks';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { getApiErrorMessage } from '@/lib/apiError';
import { useCapabilities } from '@/src/features/access/Capabilities';
import { SingleDeviceStream } from '@/src/features/stream/SingleDeviceStream';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/components/ui/input';
import type { DagNode } from '@/lib/dag/export';
import { appendRecording, appendSelectorRecording, observeAcknowledgedRecording, recordingActions, type RecordedInput, type StreamInput } from './recording';
import type { AcknowledgedControl } from '@/src/features/stream/controlObservation';
import { actionLabel } from './presentation';

interface Version { id: string; version: number; dag_hash: string | null }
interface Props { scriptId: string | null; version: Version | null; name: string; canRun: boolean; canEdit: boolean;
  onInsert: (actions: DagNode['action'][]) => boolean; onExecution: (lastCompleted: string | null, logs: { node_id: string; success: boolean }[]) => void;
  registerCloseGuard?: (guard: ((silent?: boolean) => boolean) | null) => void }
const terminal = new Set(['completed', 'failed', 'cancelled', 'timeout', 'timed_out']);
const keyLabels: Record<number, string> = { 3: 'Домой', 4: 'Назад', 187: 'Недавние', 82: 'Меню', 67: 'Backspace', 112: 'Delete', 66: 'Enter', 61: 'Tab', 278: 'Копировать', 277: 'Вырезать', 279: 'Вставить' };
function recordedLabel(entry: RecordedInput): string {
  const command = entry.command;
  if (command.type === 'key_event') return `Клавиша · ${keyLabels[command.keycode] ?? command.keycode}`;
  if (command.type === 'type_text') return `Ввод текста · ${command.text.length} символов`;
  if (command.type === 'tap_element') return `XPath · ${command.selector}`;
  return `${command.type === 'click' ? 'Нажатие' : 'Свайп'} · ${entry.dimensions.width}×${entry.dimensions.height}`;
}
const outcomeLabels = { 'transport-submitted': 'Отправлено WS', 'android-pending': 'Ожидает APK', 'android-confirmed': 'Подтверждено APK', 'android-unknown': 'Результат неизвестен', 'selector-planned': 'В план · не выполнялся' };

export function DeviceWorkbench(props: Props) {
  const { accessToken } = useAuthStore();
  const session = useRef({ token: accessToken, epoch: 0 });
  if (session.current.token !== accessToken) session.current = { token: accessToken, epoch: session.current.epoch + 1 };
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const query = useDebounce(search.trim(), 300);
  const { data, isLoading, isError, isFetching, refetch } = useDevices({ page, page_size: 25, search: query || undefined });
  const [device, setDevice] = useState<Device | null>(null);
  const closeGuard = useRef<((silent?: boolean) => boolean) | null>(null);
  return <section aria-label="Рабочее устройство" className="flex h-full min-h-0 min-w-0 flex-col bg-card">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3"><div><h2 className="flex items-center gap-2 text-sm font-semibold"><Monitor className="size-4 text-primary" />Лаборатория устройства</h2><p className="mt-1 text-xs text-muted-foreground">Живое видео · запись действий · XPath · проверка версии</p></div>
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
      </div> : <OwnedWorkbench key={`${device.id}:${session.current.epoch}`} {...props} registerCloseGuard={guard => { closeGuard.current = guard; props.registerCloseGuard?.(guard); }} device={device} />}
    </div>
  </section>;
}
function OwnedWorkbench({ device, scriptId, version, name, canRun, canEdit, onInsert, onExecution, registerCloseGuard }: Props & { device: Device }) {
  const access = useCapabilities();
  const [recording, setRecording] = useState(false);
  const [preservePauses, setPreservePauses] = useState(true);
  const [entries, setEntries] = useState<RecordedInput[]>([]);
  const entriesRef = useRef(entries); entriesRef.current = entries;
  const controlRequests = useRef(new Set<string>());
  const [controlPending, setControlPending] = useState(false);
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
    const pending = runPending || runningRequest.current || controlRequests.current.size > 0;
    const guarded = Boolean(entriesRef.current.length || active || pending || uncertain);
    if (silent) return !guarded;
    if (pending) {
      setError('Задание или команда Android ещё не подтверждены. Дождитесь ответа перед сменой или закрытием устройства; повторный запуск недоступен.');
      return false;
    }
    if (uncertain) {
      setError('Результат запуска неизвестен. Проверьте журнал заданий: переключение устройства заблокировано, чтобы не создать повторное выполнение.');
      return false;
    }
    return guarded ? window.confirm('Закрыть устройство? Невставленная запись будет потеряна. Созданное задание продолжит работу; его можно открыть в разделе заданий.') : true;
  }); return () => registerCloseGuard?.(null); }, [entries, active, runPending, uncertain, registerCloseGuard]);
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
  const commandObserved = (event: AcknowledgedControl) => {
    if (!live.current || event.input.deviceId !== device.id) return;
    if (event.phase === 'submitted') controlRequests.current.add(event.requestId);
    else controlRequests.current.delete(event.requestId);
    setControlPending(controlRequests.current.size > 0);
    if (event.phase !== 'submitted' && !controlRequests.current.size) setError(value => value.startsWith('Задание или команда Android ещё') ? '' : value);
    try {
      const next = observeAcknowledgedRecording(entriesRef.current, event, device.id,
        recording && canEdit && accessRef.current.can('stream:control'));
      if (next !== entriesRef.current) { entriesRef.current = next; setEntries(next); }
    } catch (reason) { setRecording(false); setError(reason instanceof Error ? reason.message : 'Не удалось записать команду.'); }
  };
  const unresolved = entries.some(entry => entry.outcome === 'android-pending' || entry.outcome === 'android-unknown');
  async function run() {
    if (runningRequest.current || controlRequests.current.size || uncertain || active || !canRun || !scriptId || !version?.dag_hash || !accessRef.current.can('script:execute')) return;
    const pinned = version.id;
    runningRequest.current = true; setRunPending(true); setRecording(false); setError('');
    try {
      const { data } = await api.post('/tasks', { script_id: scriptId, device_id: device.id, expected_current_version_id: pinned, priority: 5 }, { timeout: 30000 });
      if (!live.current) return;
      if (!data?.id || data.device_id !== device.id || data.script_id !== scriptId || data.script_version_id !== pinned) throw new Error('Ответ создания задания не подтверждает выбранную цель и версию.');
      setError(''); setOwnedVersion(pinned); setTaskId(data.id);
    } catch (reason) { if (live.current) { setUncertain(!(isAxiosError(reason) && reason.response && reason.response.status >= 400 && reason.response.status < 500)); setError(getApiErrorMessage(reason, 'Запуск не подтверждён. Проверьте задания перед повтором: автоматического повтора нет.')); } }
    finally { runningRequest.current = false; if (live.current) setRunPending(false); }
  }
  return <div className="space-y-4">
    <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border bg-muted/30 p-3"><div className="min-w-0 flex-1 basis-48"><p className="break-words text-sm font-semibold [overflow-wrap:anywhere]">{device.name}</p><p className="mt-1 break-words text-xs text-muted-foreground [overflow-wrap:anywhere]">Android {device.android_version ?? '—'} · Agent {device.agent_version ?? '—'}</p></div><Link href={`/devices/${device.id}`} className="flex shrink-0 items-center gap-1 text-xs text-primary">Карточка <ExternalLink className="size-3" /></Link></div>
    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap"><Button size="sm" className="h-auto min-h-8 min-w-0 whitespace-normal" variant={recording ? 'destructive' : 'outline'} disabled={!canEdit || active || runPending || uncertain || (!recording && controlPending) || !access.can('stream:control')} onClick={() => setRecording(!recording)}>{recording ? <Square className="mr-2 size-3 shrink-0" /> : <Circle className="mr-2 size-3 shrink-0 text-rose-500" />}{recording ? 'Остановить запись' : 'Записать действия'}</Button>
      <Button size="sm" className="h-auto min-h-8 min-w-0 whitespace-normal" disabled={!canRun || active || runPending || recording || controlPending || uncertain} onClick={() => void run()}><Play className="mr-2 size-3 shrink-0" /><span className="min-w-0 break-words [overflow-wrap:anywhere]">{runPending ? 'Создаём задание…' : `Проверить на ${device.name}`}</span></Button>
      {active && <Button size="sm" variant="outline" disabled={stop.isPending || !access.can('script:execute')} onClick={() => stop.mutate(taskId, { onError: reason => setError(getApiErrorMessage(reason, 'Остановка не подтверждена.')) })}>Остановить задание</Button>}</div>
    {error && <p role="alert" className="rounded-lg border border-destructive/30 p-3 text-xs text-destructive">{error} {uncertain && <Link href="/tasks" target="_blank" rel="noopener noreferrer" className="underline">Открыть задания в новой вкладке</Link>}</p>}
    {!canRun && <p className="text-xs text-muted-foreground">Для проверки сохраните сценарий и откройте его неизменённую версию. Запуск всегда создаёт одно реальное задание на выбранном Android.</p>}
    <SingleDeviceStream deviceId={device.id} captureEnabled compact controlDisabled={active || runPending || uncertain || controlPending} onControlSent={sent} onControlCommand={commandObserved} onInsertSelector={canEdit && !active && !runPending && !uncertain && !controlPending ? (node, snapshot) => {
      if (snapshot.device_id !== device.id) return;
      try {
        const next = appendSelectorRecording(entriesRef.current, node, snapshot, device.id, Date.now());
        entriesRef.current = next; setEntries(next); setError('');
      } catch (reason) { setRecording(false); setError(reason instanceof Error ? reason.message : 'XPath не добавлен в запись.'); }
    } : undefined} />
    <div className="rounded-xl border"><header className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2"><h3 className="flex items-center gap-2 text-xs font-semibold"><Radio className={`size-3 ${recording ? 'text-rose-500' : 'text-muted-foreground'}`} />Запись · {entries.length}/200</h3><div className="flex flex-wrap gap-1"><Button size="sm" variant="ghost" disabled={!entries.length || recording || controlPending || !canEdit} onClick={() => { entriesRef.current = []; setEntries([]); }} aria-label="Очистить запись"><Trash2 className="size-3" /></Button><Button size="sm" variant="outline" disabled={!entries.length || recording || controlPending || unresolved || !canEdit} onClick={() => { try { if (onInsert(recordingActions(entriesRef.current, preservePauses))) { entriesRef.current = []; setEntries([]); setError(''); } } catch (reason) { setError(reason instanceof Error ? reason.message : 'Запись не перенесена.'); } }}>Вставить в граф</Button></div></header>
      <label className="flex items-center gap-2 px-3 pt-3 text-xs"><input type="checkbox" checked={preservePauses} disabled={recording || controlPending} onChange={event => setPreservePauses(event.target.checked)} />Сохранять паузы между действиями (до 60 с)</label>
      <p className="px-3 py-2 text-[11px] leading-5 text-muted-foreground">Клики, свайпы и колесо: отправка по WebSocket, без ACK выполнения. Текст и кнопки Android: отдельное подтверждение APK. XPath добавляется явно из инспектора. Буфер Android и выбранное поле зависят от приложения; запись не сохраняет содержимое буфера.</p>
      <p className="px-3 pb-2 text-[11px] leading-5 text-muted-foreground">Текст скрыт в списке, но войдёт в исходник при вставке в граф. До вставки запись хранится только в памяти этой страницы; не записывайте пароли. Выбранный XPath добавляется в ту же очередь как будущий шаг и сейчас не нажимает Android. Остановите запись и вставьте очередь в граф.</p>
      {unresolved && <p role="status" className="px-3 pb-3 text-xs text-amber-700 dark:text-amber-400">Перенос заблокирован: дождитесь ответа APK. Если результат неизвестен, проверьте экран и явно удалите сомнительное действие; автоматического повтора нет.</p>}
      {!!entries.length && <ol aria-label="Записанные действия" className="max-h-56 overflow-auto px-3 pb-3">{entries.map((entry, index) => <li key={entry.id} className="flex flex-wrap items-center gap-2 border-t py-2 text-xs"><span className="min-w-0 flex-1 basis-40 break-words">{index + 1}. {recordedLabel(entry)}</span><span className={`rounded-full border px-2 py-1 text-[10px] ${entry.outcome === 'android-unknown' ? 'text-destructive' : entry.outcome === 'android-confirmed' ? 'text-emerald-700 dark:text-emerald-400' : 'text-muted-foreground'}`}>{outcomeLabels[entry.outcome]}</span><Button size="sm" variant="ghost" disabled={recording || controlPending || !canEdit} aria-label={`Удалить действие ${index + 1}`} onClick={() => { const next = entriesRef.current.filter(value => value.id !== entry.id); entriesRef.current = next; setEntries(next); }}><Trash2 className="size-3" /></Button></li>)}</ol>}
    </div>
    {taskId && <div className="rounded-xl border p-3"><h3 className="flex items-center gap-2 text-sm font-semibold"><CheckCheck className="size-4 text-primary" />Проверка {name}</h3><Link href={`/tasks/${taskId}`} target="_blank" rel="noopener noreferrer" title="Открыть задание в новой вкладке, сохранив редактор" className="mt-2 block break-all font-mono text-xs text-primary">{taskId}</Link>
      {task.isError || !ownsTask ? <p role="status" className="mt-2 text-xs">Ожидаем подтверждённое состояние выбранного задания…</p> : <><p className="mt-2 text-xs">{task.data!.status} · {terminal.has(task.data!.status)
        ? logs.isError ? 'Итоговые отчёты недоступны' : logs.data ? `отчёты шагов: ${logs.data.length}` : 'Ожидаем итоговые отчёты шагов'
        : progress.data ? `${progress.data.nodes_done}/${progress.data.total_nodes} шагов` : 'Прогресс пока не сообщается'}</p>
        <p className="mt-2 text-[11px] text-muted-foreground">Подсвечивается последний обработанный шаг, сообщённый APK. Прогресс проверяется каждые 2 с; видео и события не имеют покадровой синхронизации.</p>
        {logs.isError ? <p role="alert" className="mt-2 text-xs">Логи задания недоступны.</p> : <ol className="mt-3 max-h-48 overflow-auto text-xs">{logs.data?.map((log, index) => <li key={`${log.node_id}:${index}`} className="flex flex-wrap justify-between gap-2 border-t py-2"><span className={log.success ? 'text-emerald-600 dark:text-emerald-400' : 'text-destructive'}>{log.success ? '✓' : '×'} {log.node_id} · {actionLabel(log.action_type)}</span><span>{log.duration_ms} мс</span></li>)}</ol>}</>}
    </div>}
  </div>;
}
