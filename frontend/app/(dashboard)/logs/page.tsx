'use client';

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Clock3, FileText, Pause, Play, RefreshCw, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '@/lib/api';
import { useRouter, useSearchParams } from 'next/navigation';
import { useDeviceSnapshot } from '@/lib/hooks/useDeviceSnapshot';
import { isUtcLogDate, useDeviceLogDates } from '@/lib/hooks/useDeviceLogDates';
import { DeviceLogSourcePicker } from '@/components/sphere/DeviceLogSourcePicker';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { useAuthStore } from '@/lib/store';
import { Badge } from '@/src/shared/ui/badge';
import { Button } from '@/src/shared/ui/button';
import { Card, CardContent } from '@/src/shared/ui/card';
import { Input } from '@/src/shared/ui/input';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { describeDeviceLogError, type DeviceLogError } from '@/src/features/devices/deviceLogError';

type LogLevel = 'V' | 'D' | 'I' | 'W' | 'E' | 'A' | 'ALL';
type EntryLevel = Exclude<LogLevel, 'ALL'>;

interface LogEntry {
  raw: string;
  level: EntryLevel;
  timestamp: string;
  tag: string;
  message: string;
}

interface LogsResponse {
  device_id: string;
  lines: string[];
  total: number;
  read?: LogReadScope;
}

interface LogReadScope {
  date?: string | null;
  truncated: boolean;
  reasons: string[];
  bytes_scanned: number;
  scan_byte_limit: number;
  omitted_oversized_lines: number;
  files_scanned: number;
  files_available: number;
}

const READ_REASONS: Record<string, string> = {
  file_limit: 'выбраны три последних дневных файла',
  line_limit: 'достигнут лимит строк',
  scan_byte_limit: 'достигнут лимит чтения',
  response_byte_limit: 'достигнут лимит ответа',
  oversized_line: 'слишком длинные строки пропущены целиком',
};

const LEVELS: LogLevel[] = ['ALL', 'V', 'D', 'I', 'W', 'E', 'A'];
const LEVEL_LABELS: Record<LogLevel, string> = {
  ALL: 'Все уровни', V: 'Подробно', D: 'Отладка', I: 'Информация', W: 'Предупреждения', E: 'Ошибки', A: 'Критические',
};
const LEVEL_COLORS: Record<EntryLevel, string> = {
  V: 'text-slate-400', D: 'text-sky-300', I: 'text-emerald-300', W: 'text-amber-300', E: 'text-rose-300', A: 'text-fuchsia-300 font-semibold',
};
const LOG_PATTERN = /^(\S+T\S+)\s+([VDIWEAF])\/([^:]+):\s?(.*)$/;

function parseLine(raw: string): LogEntry {
  const match = raw.match(LOG_PATTERN);
  if (match) {
    return {
      raw,
      level: match[2] === 'F' ? 'A' : match[2] as EntryLevel,
      timestamp: match[1],
      tag: match[3].trim(),
      message: match[4],
    };
  }
  const levelMatch = raw.match(/\s([VDIWEAF])\/\S/);
  const matchedLevel = levelMatch?.[1];
  return {
    raw,
    level: matchedLevel ? matchedLevel === 'F' ? 'A' : matchedLevel as EntryLevel : 'I',
    timestamp: '',
    tag: '',
    message: raw,
  };
}

function validateLogsResponse(data: unknown, expectedDevice: string, expectedDate: string | null): LogsResponse {
  if (!data || typeof data !== 'object') throw new Error('Backend вернул некорректный ответ логов.');
  const payload = data as Partial<LogsResponse>;
  if (typeof payload.device_id !== 'string' || !Array.isArray(payload.lines) || !payload.lines.every((line) => typeof line === 'string')) {
    throw new Error('Backend вернул некорректный список строк логов.');
  }
  if (payload.device_id !== expectedDevice) throw new Error('Backend вернул логи другого устройства.');
  if (payload.lines.length > 1000 || new Blob([JSON.stringify(payload.lines)]).size > 512 * 1024) {
    throw new Error('Backend превысил допустимый размер журнала.');
  }
  let read: LogReadScope | undefined;
  if (payload.read !== undefined) {
    const scope = payload.read as LogReadScope & Record<string, unknown>;
    const integer = (value: unknown, max: number) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= max;
    if (!scope || typeof scope !== 'object' || scope.schema_version !== 1 || scope.scope !== 'recent-file-tail'
      || (scope.date ?? null) !== expectedDate || (expectedDate !== null && scope.files_available > 1)
      || typeof scope.truncated !== 'boolean' || !Array.isArray(scope.reasons)
      || scope.reasons.length > 5 || !scope.reasons.every((reason) => typeof reason === 'string' && Object.hasOwn(READ_REASONS, reason))
      || scope.truncated !== (scope.reasons.length > 0)
      || scope.scan_byte_limit !== 2 * 1024 * 1024 || !integer(scope.bytes_scanned, scope.scan_byte_limit)
      || scope.response_byte_limit !== 512 * 1024 || !integer(scope.response_lines_bytes, scope.response_byte_limit)
      || !integer(scope.files_scanned, 3) || !integer(scope.files_available, 128) || scope.files_scanned > scope.files_available
      || !integer(scope.omitted_oversized_lines, scope.bytes_scanned)) {
      throw new Error('Backend вернул некорректные границы чтения журнала.');
    }
    if (payload.total !== payload.lines.length) throw new Error('Backend вернул противоречивое число строк журнала.');
    read = scope;
  }
  if (expectedDate !== null && !read) throw new Error('Backend вернул журнал без подтверждения выбранной даты.');
  const total = typeof payload.total === 'number' && Number.isFinite(payload.total) && payload.total >= 0
    ? Math.trunc(payload.total)
    : payload.lines.length;
  return { device_id: payload.device_id, lines: payload.lines, total, read };
}

function formatTime(timestamp: number) {
  if (!timestamp) return 'Ещё не обновлялось';
  return new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(timestamp);
}

function LogsPageContent() {
  const params = useSearchParams();
  const router = useRouter();
  const sessionVersion = useAuthStore(state => state.sessionVersion);
  const requestedDevice = params.get('device_id')?.trim() ?? '';
  const requestedDate = params.get('date');
  const [selectedDevice, setSelectedDevice] = useState(requestedDevice);
  const [selectedDate, setSelectedDate] = useState(requestedDate);
  const lastRequestedDevice = useRef(requestedDevice);
  const lastRequestedDate = useRef(requestedDate);
  useEffect(() => {
    if (lastRequestedDevice.current !== requestedDevice) {
      lastRequestedDevice.current = requestedDevice;
      setSelectedDevice(requestedDevice);
    }
  }, [requestedDevice]);
  useEffect(() => {
    if (lastRequestedDate.current !== requestedDate) {
      lastRequestedDate.current = requestedDate;
      setSelectedDate(requestedDate);
    }
  }, [requestedDate]);
  const selectDevice = useCallback((id: string) => {
    setSelectedDevice(id);
    const nextParams = new URLSearchParams(params.toString());
    nextParams.set('device_id', id);
    if (selectedDate !== null) nextParams.set('date', selectedDate);
    else nextParams.delete('date');
    router.replace(`/logs?${nextParams}`, { scroll: false });
  }, [params, router, selectedDate]);
  const selectDate = useCallback((date: string | null) => {
    setSelectedDate(date);
    const nextParams = new URLSearchParams(params.toString());
    nextParams.set('device_id', selectedDevice);
    if (date) nextParams.set('date', date);
    else nextParams.delete('date');
    router.replace(`/logs?${nextParams}`, { scroll: false });
  }, [params, router, selectedDevice]);

  return <main className="mx-auto w-full max-w-[1600px] space-y-4 p-4 sm:p-6 lg:p-8">
    <DeviceLogSourcePicker value={selectedDevice} onChange={selectDevice} />
    {selectedDevice ? <LogViewer key={`${sessionVersion}:${selectedDevice}`} sessionVersion={sessionVersion} selectedDevice={selectedDevice}
      selectedDate={selectedDate} onSelectDate={selectDate} />
      : <p role="status" className="text-sm text-muted-foreground">Выберите устройство, чтобы просмотреть логи.</p>}
  </main>;
}

export default function LogsPage() {
  return <Suspense fallback={<p role="status">Загружаем системный журнал…</p>}><LogsPageContent /></Suspense>;
}

function LogViewer({ selectedDevice, selectedDate, onSelectDate, sessionVersion }: {
  selectedDevice: string; selectedDate: string | null; onSelectDate: (date: string | null) => void; sessionVersion: number;
}) {
  const snapshot = useDeviceSnapshot(selectedDevice);
  const selectedDeviceInfo = snapshot.data;
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search.trim(), 350);
  const [levelFilter, setLevelFilter] = useState<LogLevel>('ALL');
  const [result, setResult] = useState<{ key: string; lines: LogEntry[]; total: number; read?: LogReadScope; at: number }>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<{ key: string; failure: DeviceLogError } | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [showArchive, setShowArchive] = useState(selectedDate !== null);
  const [clearOpen, setClearOpen] = useState(false);
  const [clearPending, setClearPending] = useState(false);
  const [clearError, setClearError] = useState<DeviceLogError | null>(null);
  const requestSequence = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const scopeKey = JSON.stringify([selectedDate, debouncedSearch]);
  const currentResult = result?.key === scopeKey ? result : undefined;
  const currentError = error?.key === scopeKey ? error.failure : null;
  const readScope = currentResult?.read;
  const lastUpdatedAt = currentResult?.at ?? 0;
  const totalLines = currentResult?.total ?? 0;
  const invalidDate = selectedDate !== null && !isUtcLogDate(selectedDate);
  const archiveOpen = showArchive || selectedDate !== null;
  const polling = autoRefresh && !archiveOpen;
  const archiveDates = useDeviceLogDates(selectedDevice, sessionVersion, archiveOpen);
  const archiveFailure = archiveDates.isError ? describeDeviceLogError(archiveDates.error) : null;
  const retryBlocked = useRetryDelay(currentError?.retryAfterSeconds, currentError);
  const archiveRetryBlocked = useRetryDelay(archiveFailure?.retryAfterSeconds, archiveDates.error);
  const searchPending = search.trim() !== debouncedSearch;
  const archiveOptions = archiveFailure?.discardSnapshot ? [] : (archiveDates.data ?? []);

  const cancelRead = useCallback(() => {
    activeRequest.current?.abort();
    activeRequest.current = null;
    ++requestSequence.current;
  }, []);

  const fetchLogs = useCallback(async (scrollToBottom = false) => {
    if (invalidDate) {
      setLoading(false);
      return;
    }
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ lines: '1000' });
      if (debouncedSearch) params.set('search', debouncedSearch);
      if (selectedDate !== null) params.set('date', selectedDate);
      const response = await api.get<unknown>(`/logs/${encodeURIComponent(selectedDevice)}?${params}`, { signal: controller.signal });
      if (controller.signal.aborted || sequence !== requestSequence.current) return;
      let payload;
      try {
        payload = validateLogsResponse(response.data, selectedDevice, selectedDate);
      } catch (error) {
        setAutoRefresh(false);
        setError({ key: scopeKey, failure: describeDeviceLogError(error, 'read', response.headers) });
        return;
      }
      setResult({ key: scopeKey, lines: payload.lines.map(parseLine), total: payload.total, read: payload.read, at: Date.now() });
      if (scrollToBottom) {
        window.requestAnimationFrame(() => {
          const container = containerRef.current;
          if (!container) return;
          if (typeof container.scrollTo === 'function') container.scrollTo({ top: container.scrollHeight });
          else container.scrollTop = container.scrollHeight;
        });
      }
    } catch (requestError) {
      if (!controller.signal.aborted && sequence === requestSequence.current) {
        const failure = describeDeviceLogError(requestError);
        if (failure.discardSnapshot) setResult(undefined);
        setError({ key: scopeKey, failure });
        setAutoRefresh(false);
      }
    } finally {
      if (sequence === requestSequence.current) {
        setLoading(false);
        activeRequest.current = null;
      }
    }
  }, [debouncedSearch, invalidDate, scopeKey, selectedDate, selectedDevice]);

  useEffect(() => {
    void fetchLogs(true);
    return cancelRead;
  }, [fetchLogs, cancelRead]);

  useEffect(() => {
    if (!polling || clearPending || searchPending) return;
    const interval = window.setInterval(() => {
      if (!activeRequest.current && document.visibilityState !== 'hidden') void fetchLogs(true);
    }, 5000);
    return () => window.clearInterval(interval);
  }, [polling, fetchLogs, clearPending, searchPending]);

  const visibleLines = useMemo(() => {
    const lines = currentResult?.lines ?? [];
    return levelFilter === 'ALL' ? lines : lines.filter((line) => line.level === levelFilter);
  }, [levelFilter, currentResult]);

  const handleClear = async () => {
    if (!selectedDevice || clearPending) return;
    setClearPending(true);
    setClearError(null);
    cancelRead();
    setLoading(false);
    try {
      const response = await api.delete(`/logs/${encodeURIComponent(selectedDevice)}`);
      if (response.status !== 204) {
        setClearError(describeDeviceLogError(new Error('Backend вернул неподтверждённый результат удаления.'), 'delete', response.headers));
        return;
      }
      setResult({ key: scopeKey, lines: [], total: 0, at: 0 });
      if (archiveOpen) void archiveDates.refetch({ cancelRefetch: false });
      setClearOpen(false);
      toast.success(`Логи устройства ${selectedDeviceInfo?.name ?? selectedDevice} удалены`);
    } catch (deleteError) {
      const failure = describeDeviceLogError(deleteError, 'delete');
      setClearError(failure);
      toast.error(`Не удалось удалить логи: ${failure.message}`);
    } finally {
      setClearPending(false);
    }
  };

  const closeArchive = () => {
    setAutoRefresh(false);
    setShowArchive(false);
    onSelectDate(null);
  };

  return (
    <section className="flex w-full flex-col gap-4" aria-label="Журнал выбранного устройства">
      <header className="flex flex-col gap-4 border-b border-border/70 pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Sphere / Диагностика</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">Системные логи</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Полученные сервером логи агента. Даты указаны в UTC, поиск работает в пределах выбранной области чтения.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant={autoRefresh ? 'secondary' : 'outline'} size="sm" onClick={() => setAutoRefresh((current) => !current)} disabled={archiveOpen || clearPending || !!currentError} aria-pressed={polling}>
            {autoRefresh ? <Pause className="mr-2 h-4 w-4" aria-hidden="true" /> : <Play className="mr-2 h-4 w-4" aria-hidden="true" />}
            {autoRefresh ? 'Пауза автообновления' : 'Автообновление · 5 с'}
          </Button>
          <Button variant="outline" size="sm" onClick={() => void fetchLogs()} disabled={loading || clearPending || invalidDate || searchPending || retryBlocked} aria-label="Обновить логи">
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
            Обновить
          </Button>
          <Button variant="destructive" size="sm" onClick={() => { setClearError(null); setClearOpen(true); }} disabled={clearPending || loading || searchPending || !!currentError || !lastUpdatedAt}>
            <Trash2 className="mr-2 h-4 w-4" aria-hidden="true" />Очистить логи
          </Button>
        </div>
      </header>

      <Card className="overflow-hidden rounded-xl border-border/80">
        <div className="flex flex-wrap items-end gap-3 border-b border-border/70 px-4 py-3">
          {archiveOpen ? <>
            <label className="flex flex-col gap-1 text-xs font-medium">
              Дата архива (UTC)
              <select value={isUtcLogDate(selectedDate) ? selectedDate : ''} disabled={clearPending}
                onChange={event => onSelectDate(event.target.value || null)}
                className="h-9 max-w-full rounded-md border border-input bg-background px-2 text-sm">
                <option value="">Выберите дату</option>
                {isUtcLogDate(selectedDate) && !archiveOptions.includes(selectedDate) &&
                  <option value={selectedDate}>{selectedDate}</option>}
                {archiveOptions.map(date => <option value={date} key={date}>{date}</option>)}
              </select>
            </label>
            <Button variant="outline" size="sm" disabled={archiveDates.isFetching || clearPending || archiveRetryBlocked}
              onClick={() => void archiveDates.refetch()}>Обновить даты</Button>
            <Button variant="outline" size="sm" onClick={closeArchive} disabled={clearPending}>Последние журналы</Button>
            {archiveDates.isFetching && <span className="text-xs text-muted-foreground" role="status">Загружаем даты…</span>}
            {archiveDates.isSuccess && archiveDates.data.length === 0 && <span className="text-xs text-muted-foreground">Сохранённых дневных файлов нет.</span>}
            {archiveFailure && <p className="basis-full text-sm text-destructive" role="alert">
              Даты архива не загружены. {archiveFailure.message}
              {archiveFailure.requestId && <> ID запроса <code>{archiveFailure.requestId}</code>.</>}
              {archiveRetryBlocked && <> Повтор доступен через {archiveFailure.retryAfterSeconds} с.</>}
            </p>}
          </> : <Button variant="outline" size="sm" onClick={() => { setAutoRefresh(false); setShowArchive(true); }}
            disabled={clearPending}>Архив по дате</Button>}
        </div>
        <div className="flex flex-col gap-3 border-b border-border/70 bg-muted/30 p-3 sm:flex-row sm:items-center sm:px-4">
          <Select value={levelFilter} onValueChange={(value) => setLevelFilter(value as LogLevel)}>
            <SelectTrigger className="h-9 w-full rounded-lg sm:w-[190px]" aria-label="Фильтр уровня логов"><SelectValue /></SelectTrigger>
            <SelectContent>{LEVELS.map((level) => <SelectItem key={level} value={level}>{LEVEL_LABELS[level]}</SelectItem>)}</SelectContent>
          </Select>

          <label className="relative block min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input value={search} onChange={(event) => setSearch(event.target.value)} maxLength={512} placeholder="Поиск в журнале" aria-label="Поиск в логах" disabled={invalidDate || clearPending} className="h-9 rounded-lg pl-9" />
          </label>

          <Badge variant="outline" className="w-fit shrink-0 rounded-full px-2.5 normal-case tracking-normal">
            {invalidDate ? 'Некорректная дата' : currentError ? 'Новое чтение не подтверждено'
              : loading || searchPending ? 'Обновляем журнал…' : `${visibleLines.length} показано · ${totalLines} загружено`}
          </Badge>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/70 px-4 py-2.5 text-xs text-muted-foreground">
          <div className="flex min-w-0 items-center gap-2">
            <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate">{selectedDeviceInfo?.name ?? selectedDevice}</span>
            {<span className="hidden truncate font-mono opacity-70 sm:inline">{selectedDevice}</span>}
          </div>
          <span className="inline-flex items-center gap-1.5"><Clock3 className="h-3.5 w-3.5" aria-hidden="true" />Последнее успешное чтение: {formatTime(lastUpdatedAt)}{polling ? ' · авто 5 с' : ''}</span>
        </div>

        <CardContent className="p-3 sm:p-4">
          {!searchPending && lastUpdatedAt > 0 && <div role="status" className={`mb-3 rounded-lg border p-3 text-xs leading-relaxed ${readScope?.truncated ? 'border-amber-300/60 bg-amber-500/5 text-foreground' : 'border-border bg-muted/30 text-muted-foreground'}`}>
            {currentError && <p className="font-medium">Показан последний успешный результат.</p>}
            {readScope ? <>
              <p className="font-medium">{readScope.truncated ? 'Показана часть журнала' : readScope.files_available === 0
                ? selectedDate ? 'Файл за выбранную дату не найден.' : 'Полученных файлов пока нет'
                : 'Выбранные файлы проверены полностью'}</p>
              <p>Проверено {(readScope.bytes_scanned / 1024).toLocaleString('ru-RU', { maximumFractionDigits: 0 })} КиБ из лимита {readScope.scan_byte_limit / 1024 / 1024} МиБ · файлов {readScope.files_scanned} из {readScope.files_available}.</p>
              {readScope.reasons.length > 0 && <p>{readScope.reasons.map((reason) => READ_REASONS[reason]).join('; ')}.</p>}
              {readScope.omitted_oversized_lines > 0 && <p>Пропущено длинных строк: {readScope.omitted_oversized_lines}.</p>}
              <p>{selectedDate ? `Область чтения: ${selectedDate} UTC.` : 'Отсутствие совпадений здесь не означает их отсутствие в более старых логах.'}</p>
            </> : <p>Сервер не сообщил границы чтения. Полнота поиска по архиву не подтверждена.</p>}
          </div>}
          <div ref={containerRef} aria-label="Строки системного журнала" aria-live="polite" className="max-h-[65vh] min-h-[320px] overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-3 font-mono text-[11px] leading-5 sm:p-4 sm:text-xs">
            {invalidDate && <p role="alert" className="py-5 font-sans text-sm text-rose-300">
              Дата в ссылке должна быть календарной датой в формате ГГГГ-ММ-ДД. Выберите дату архива или откройте последние журналы.
            </p>}
            {!invalidDate && !searchPending && currentError && (
              <div role="alert" className="flex flex-col items-start gap-2 py-5 font-sans text-sm text-rose-300">
                <span className="flex items-center gap-2"><AlertCircle className="h-4 w-4" aria-hidden="true" />Логи не загружены: {currentError.message}</span>
                {currentError.requestId && <span>ID запроса <code>{currentError.requestId}</code></span>}
                {retryBlocked && <span>Повтор доступен через {currentError.retryAfterSeconds} с.</span>}
                <Button variant="outline" size="sm" disabled={retryBlocked} onClick={() => void fetchLogs()}>Повторить запрос</Button>
              </div>
            )}
            {invalidDate ? null : searchPending ? (
              <p role="status" className="py-8 text-center font-sans text-sm text-slate-400">Применяем поиск в журнале…</p>
            ) : currentError && !currentResult ? null : loading && !currentResult ? (
              <p role="status" className="py-8 text-center font-sans text-sm text-slate-400">Загружаем логи устройства…</p>
            ) : visibleLines.length === 0 ? (
              <div className="py-8 text-center font-sans text-sm text-slate-400">{!currentResult?.lines.length ? readScope ? 'В проверенной части журнала нет строк.' : 'Для этого устройства пока нет полученных логов.' : 'Нет строк, подходящих под выбранный фильтр.'}</div>
            ) : (
              <div className="space-y-0.5">
                {visibleLines.map((entry, index) => (
                  <div key={`${index}-${entry.raw.slice(0, 36)}`} className={`whitespace-pre-wrap break-all ${LEVEL_COLORS[entry.level]}`}>
                    {entry.timestamp ? <><span className="text-slate-500">{entry.timestamp}</span>{' '}<span className="font-semibold">{entry.level}/{entry.tag}:</span>{' '}{entry.message}</> : entry.raw}
                  </div>
                ))}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <Dialog open={clearOpen} onOpenChange={(open) => { if (!clearPending) { setClearOpen(open); if (open) setClearError(null); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Удалить архив логов?</DialogTitle>
            <DialogDescription>Будут удалены сохранённые log files устройства <span className="font-medium text-foreground">{selectedDeviceInfo?.name ?? selectedDevice}</span>. Действие необратимо.</DialogDescription>
          </DialogHeader>
          {clearError && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            Не удалось очистить логи: {clearError.message}
            {clearError.requestId && <> ID запроса <code>{clearError.requestId}</code>.</>}
          </p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setClearOpen(false)} disabled={clearPending}>Отмена</Button>
            <Button variant="destructive" onClick={() => void handleClear()} disabled={clearPending}>
              {clearPending ? 'Удаляем…' : 'Удалить логи'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

function useRetryDelay(seconds: number | null | undefined, error: unknown) {
  const [blocked, setBlocked] = useState(false);
  useEffect(() => {
    setBlocked(Boolean(seconds));
    if (!seconds) return;
    const timeout = window.setTimeout(() => setBlocked(false), seconds * 1000);
    return () => window.clearTimeout(timeout);
  }, [error, seconds]);
  return blocked;
}
