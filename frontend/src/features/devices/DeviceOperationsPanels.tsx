'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { api } from '@/lib/api';
import { Button } from '@/src/shared/ui/button';
import { Badge } from '@/src/shared/ui/badge';
import { executionStatusLabel } from '@/lib/task-status';

export function utcTime(value: unknown): string {
  if (typeof value !== 'string' || !value || !Number.isFinite(Date.parse(value))) return 'Не сообщено';
  return new Date(value).toLocaleString('ru-RU', { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'medium' }) + ' UTC';
}

export function Metric({ label, value }: { label: string; value: ReactNode }) {
  return <div className="min-w-0 rounded-xl border border-border bg-muted/20 p-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-words text-sm font-medium tabular-nums">{value}</dd></div>;
}

function QueryState({ loading, error, cached, updatedAt }: { loading: boolean; error: boolean; cached: boolean; updatedAt: number }) {
  return <>
    {loading && <p role="status" className="text-sm text-muted-foreground">Загрузка данных…</p>}
    {error && <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">Не удалось получить данные API.{cached ? ' Ниже сохранённый ответ; он может быть устаревшим.' : ' Это не означает отсутствие записей.'}</p>}
    {updatedAt > 0 && <p className="text-xs text-muted-foreground">Последний успешный запрос: {utcTime(new Date(updatedAt).toISOString())}</p>}
  </>;
}

type HistoryItem = { id: string; device_id: string; status?: string; cancel_requested_at?: string | null; timeout_requested_at?: string | null; script_name?: string | null; created_at?: string; occurred_at?: string; event_type?: string; severity?: string; message?: string | null; task_id?: string | null };
type HistoryResponse = { items: HistoryItem[]; total: number };
export function validateDeviceHistory(value: unknown, deviceId: string, kind: 'tasks' | 'events'): HistoryResponse {
  if (!value || typeof value !== 'object') throw new Error('Некорректный ответ истории.');
  const data = value as HistoryResponse;
  if (!Array.isArray(data.items) || !Number.isSafeInteger(data.total) || data.total < 0 || data.total < data.items.length || data.items.some((item) =>
    !item || item.device_id !== deviceId || typeof item.id !== 'string' ||
    (kind === 'tasks' ? typeof item.status !== 'string' || typeof item.created_at !== 'string' : typeof item.event_type !== 'string' || typeof item.occurred_at !== 'string') ||
    (item.script_name != null && typeof item.script_name !== 'string') || (item.message != null && typeof item.message !== 'string') ||
    (item.task_id != null && typeof item.task_id !== 'string') || (item.severity != null && typeof item.severity !== 'string')
  )) throw new Error('API вернул некорректную историю или записи другого устройства.');
  return { items: data.items.slice(0, 6), total: data.total };
}

export function DeviceHistoryPanel({ deviceId, kind }: { deviceId: string; kind: 'tasks' | 'events' }) {
  const query = useQuery({
    queryKey: ['device-inspector', deviceId, kind],
    queryFn: async ({ signal }) => {
      const { data } = await api.get<unknown>(kind === 'tasks' ? '/tasks' : '/device-events', {
        params: { device_id: deviceId, page: 1, per_page: 6, sort_by: kind === 'tasks' ? 'created_at' : 'occurred_at', sort_dir: 'desc' }, signal,
      });
      return validateDeviceHistory(data, deviceId, kind);
    },
    retry: false, refetchInterval: 15_000, refetchOnMount: 'always',
  });
  return <section aria-label={kind === 'tasks' ? 'История задач устройства' : 'События устройства'} className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">{kind === 'tasks' ? 'Последние задачи' : 'Последние события'}</h3><Button variant="outline" size="sm" disabled={query.isFetching} onClick={() => { void query.refetch(); }}><RefreshCw className="mr-2 h-4 w-4" aria-hidden />Обновить историю</Button></div>
    <QueryState loading={query.isLoading} error={query.isError} cached={!!query.data} updatedAt={query.dataUpdatedAt} />
    {query.data && <p className="text-xs text-muted-foreground">Показано {query.data.items.length} из {query.data.total} записей этого устройства. Обновление каждые 15 секунд, пока вкладка открыта.</p>}
    {query.data?.items.length === 0 && !query.isError && <p className="rounded-xl border border-dashed border-border p-5 text-sm text-muted-foreground">API не вернул записей для этого устройства.</p>}
    <ul className="space-y-3">{query.data?.items.map((item) => <li key={item.id} className="space-y-2 rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2"><p className="min-w-0 break-words text-sm font-medium">{kind === 'tasks' ? item.script_name || `Задача ${item.id.slice(0, 8)}` : item.event_type}</p><Badge variant="outline">{kind === 'tasks' ? executionStatusLabel({ ...item, status: item.status || '' }) : item.severity || 'Не сообщено'}</Badge></div>
      <p className="text-xs text-muted-foreground">{utcTime(kind === 'tasks' ? item.created_at : item.occurred_at)}</p>
      {item.message && <p className="break-words text-sm text-muted-foreground">{item.message}</p>}
      <p className="break-all font-mono text-xs text-muted-foreground">{item.id}</p>
      {(kind === 'tasks' || item.task_id) && <Link className="inline-block text-sm text-primary underline underline-offset-4" href={`/tasks/${encodeURIComponent(kind === 'tasks' ? item.id : item.task_id!)}`}>Результат и шаги задачи</Link>}
    </li>)}</ul>
  </section>;
}

type DiagnosticState = 'active_report' | 'not_streaming' | 'stale' | 'unavailable';
type DiagnosticResponse = { device_id: string; state: DiagnosticState; age_seconds?: number | null; diagnostics?: { observed_at: string; telemetry: Record<string, unknown> } | null };
export function validateDeviceDiagnostics(value: unknown, deviceId: string): DiagnosticResponse {
  if (!value || typeof value !== 'object') throw new Error('Некорректная диагностика.');
  const data = value as DiagnosticResponse;
  if (data.device_id !== deviceId || !['active_report', 'not_streaming', 'stale', 'unavailable'].includes(data.state) ||
    (data.diagnostics != null && (typeof data.diagnostics.observed_at !== 'string' || !data.diagnostics.telemetry || typeof data.diagnostics.telemetry !== 'object'))
  ) throw new Error('API вернул некорректную диагностику или другое устройство.');
  return data;
}
const DIAGNOSTIC_LABELS: Record<DiagnosticState, string> = { active_report: 'Свежий отчёт APK', not_streaming: 'Нет активного отчёта о захвате', stale: 'Отчёт устарел', unavailable: 'Отчёт недоступен' };
const COUNTERS = [
  ['capture_fps', 'Захват, FPS'], ['render_fps', 'Рендер в APK, FPS'], ['encoder_fps', 'Кодирование, FPS'],
  ['encoded_frames_total', 'Кадров закодировано'], ['ws_queue_accepted_total', 'Принято очередью APK'], ['ws_queue_rejected_total', 'Отклонено очередью APK'],
  ['capture_read_failures_total', 'Ошибки захвата'], ['render_failures_total', 'Ошибки рендера APK'], ['encoder_errors_total', 'Ошибки кодера'],
] as const;

export function DeviceDiagnosticsPanel({ deviceId }: { deviceId: string }) {
  const query = useQuery({
    queryKey: ['device-inspector', deviceId, 'diagnostics'],
    queryFn: async ({ signal }) => {
      const { data } = await api.get<unknown>(`/devices/${encodeURIComponent(deviceId)}/stream-diagnostics`, { signal });
      return validateDeviceDiagnostics(data, deviceId);
    }, retry: false, refetchInterval: 15_000, refetchOnMount: 'always',
  });
  return <section aria-label="Диагностика видеотракта" className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">Захват → кодер → очередь APK</h3><Button variant="outline" size="sm" disabled={query.isFetching} onClick={() => { void query.refetch(); }}><RefreshCw className="mr-2 h-4 w-4" aria-hidden />Обновить диагностику</Button></div>
    <QueryState loading={query.isLoading} error={query.isError} cached={!!query.data} updatedAt={query.dataUpdatedAt} />
    {query.data && <><Badge variant={query.data.state === 'active_report' && !query.isError ? 'secondary' : 'outline'}>{DIAGNOSTIC_LABELS[query.data.state]}</Badge><p className="text-xs text-muted-foreground">Отчёт APK: {utcTime(query.data.diagnostics?.observed_at)}. Счётчики относятся к сессии захвата и могут сбрасываться при её смене.</p>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">{COUNTERS.map(([key, label]) => {
        const value = query.data.diagnostics?.telemetry[key];
        return <Metric key={key} label={label} value={typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('ru-RU') : 'Не сообщено'} />;
      })}</dl></>}
    <p className="rounded-xl border border-border bg-muted/30 p-3 text-sm text-muted-foreground">Принятие кадра очередью APK не доказывает доставку серверу или декодирование в браузере. Проверьте эти стадии в диагностике открытого видеопотока.</p>
    <Button asChild variant="outline"><Link href={`/stream/${encodeURIComponent(deviceId)}`}>Открыть поток с диагностикой браузера</Link></Button>
  </section>;
}

export function validateDeviceLogs(value: unknown, deviceId: string): { lines: string[] } {
  if (!value || typeof value !== 'object') throw new Error('Некорректный ответ логов.');
  const data = value as { device_id: string; lines: unknown[] };
  if (data.device_id !== deviceId || !Array.isArray(data.lines) || data.lines.length > 100 || !data.lines.every((line) => typeof line === 'string')) throw new Error('Некорректные логи или другое устройство.');
  return { lines: data.lines as string[] };
}
export function DeviceSavedLogsPanel({ deviceId }: { deviceId: string }) {
  const query = useQuery({
    queryKey: ['device-inspector', deviceId, 'saved-logs'],
    queryFn: async ({ signal }) => {
      const { data } = await api.get<unknown>(`/logs/${encodeURIComponent(deviceId)}`, { params: { lines: 100 }, signal });
      return validateDeviceLogs(data, deviceId);
    }, retry: false, refetchOnMount: 'always',
  });
  return <section aria-label="Сохранённые логи APK" className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-semibold">Сохранённые логи APK</h3><Button variant="outline" size="sm" disabled={query.isFetching} onClick={() => { void query.refetch(); }}><RefreshCw className="mr-2 h-4 w-4" aria-hidden />Обновить логи</Button></div>
    <p className="text-sm text-muted-foreground">Последние 100 строк, ранее доставленные на сервер. Доступны и для офлайн-устройства; это не живой Logcat. Автоматический опрос выключен.</p>
    <QueryState loading={query.isLoading} error={query.isError} cached={!!query.data} updatedAt={query.dataUpdatedAt} />
    {query.data && (query.data.lines.length ? <pre className="max-h-[480px] overflow-auto whitespace-pre-wrap break-all rounded-xl border border-border bg-muted/40 p-4 font-mono text-xs leading-relaxed" tabIndex={0} aria-label="Строки логов APK">{query.data.lines.join('\n')}</pre> : !query.isError && <p className="rounded-xl border border-dashed border-border p-5 text-sm text-muted-foreground">Сервер не вернул сохранённых строк. Это не подтверждает отсутствие ошибок на Android.</p>)}
  </section>;
}
