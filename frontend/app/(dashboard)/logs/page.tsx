'use client';

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Clock3, FileText, Pause, Play, RefreshCw, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '@/lib/api';
import { useRouter, useSearchParams } from 'next/navigation';
import { useDeviceSnapshot } from '@/lib/hooks/useDeviceSnapshot';
import { DeviceLogSourcePicker } from '@/components/sphere/DeviceLogSourcePicker';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { Badge } from '@/src/shared/ui/badge';
import { Button } from '@/src/shared/ui/button';
import { Card, CardContent } from '@/src/shared/ui/card';
import { Input } from '@/src/shared/ui/input';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

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
}

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

function validateLogsResponse(data: unknown, expectedDevice: string): LogsResponse {
  if (!data || typeof data !== 'object') throw new Error('Backend вернул некорректный ответ логов.');
  const payload = data as Partial<LogsResponse>;
  if (typeof payload.device_id !== 'string' || !Array.isArray(payload.lines) || !payload.lines.every((line) => typeof line === 'string')) {
    throw new Error('Backend вернул некорректный список строк логов.');
  }
  if (payload.device_id !== expectedDevice) throw new Error('Backend вернул логи другого устройства.');
  const total = typeof payload.total === 'number' && Number.isFinite(payload.total) && payload.total >= 0
    ? Math.trunc(payload.total)
    : payload.lines.length;
  return { device_id: payload.device_id, lines: payload.lines, total };
}

function errorMessage(error: unknown) {
  if (error && typeof error === 'object' && 'message' in error && typeof error.message === 'string') return error.message;
  return 'Не удалось выполнить запрос к backend.';
}

function formatTime(timestamp: number) {
  if (!timestamp) return 'Ещё не обновлялось';
  return new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(timestamp);
}

function LogsPageContent() {
  const params = useSearchParams();
  const router = useRouter();
  const requestedDevice = params.get('device_id')?.trim() ?? '';
  const [selectedDevice, setSelectedDevice] = useState(requestedDevice);
  const lastRequestedDevice = useRef(requestedDevice);
  useEffect(() => {
    if (lastRequestedDevice.current !== requestedDevice) {
      lastRequestedDevice.current = requestedDevice;
      setSelectedDevice(requestedDevice);
    }
  }, [requestedDevice]);
  const selectDevice = useCallback((id: string) => {
    setSelectedDevice(id);
    const nextParams = new URLSearchParams(params.toString());
    nextParams.set('device_id', id);
    router.replace(`/logs?${nextParams}`, { scroll: false });
  }, [params, router]);

  return <main className="mx-auto w-full max-w-[1600px] space-y-4 p-4 sm:p-6 lg:p-8">
    <DeviceLogSourcePicker value={selectedDevice} onChange={selectDevice} />
    {selectedDevice ? <LogViewer key={selectedDevice} selectedDevice={selectedDevice} />
      : <p role="status" className="text-sm text-muted-foreground">Выберите устройство, чтобы просмотреть логи.</p>}
  </main>;
}

export default function LogsPage() {
  return <Suspense fallback={<p role="status">Загружаем системный журнал…</p>}><LogsPageContent /></Suspense>;
}

function LogViewer({ selectedDevice }: { selectedDevice: string }) {
  const snapshot = useDeviceSnapshot(selectedDevice);
  const selectedDeviceInfo = snapshot.data;
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search.trim(), 350);
  const [levelFilter, setLevelFilter] = useState<LogLevel>('ALL');
  const [lines, setLines] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [totalLines, setTotalLines] = useState(0);
  const [lastUpdatedAt, setLastUpdatedAt] = useState(0);
  const [clearOpen, setClearOpen] = useState(false);
  const [clearPending, setClearPending] = useState(false);
  const [clearError, setClearError] = useState<string | null>(null);
  const requestSequence = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);


  const fetchLogs = useCallback(async (deviceId: string, scrollToBottom = false) => {
    if (!deviceId) return;
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ lines: '1000' });
      if (debouncedSearch) params.set('search', debouncedSearch);
      const response = await api.get<unknown>(`/logs/${encodeURIComponent(deviceId)}?${params}`, { signal: controller.signal });
      if (controller.signal.aborted || sequence !== requestSequence.current) return;
      const payload = validateLogsResponse(response.data, deviceId);
      setLines(payload.lines.map(parseLine));
      setTotalLines(payload.total);
      setLastUpdatedAt(Date.now());
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
        setError(errorMessage(requestError));
      }
    } finally {
      if (sequence === requestSequence.current) {
        setLoading(false);
        activeRequest.current = null;
      }
    }
  }, [debouncedSearch]);

  useEffect(() => {
    if (selectedDevice) void fetchLogs(selectedDevice, true);
    else {
      activeRequest.current?.abort();
      setLines([]);
      setTotalLines(0);
      setError(null);
    }
  }, [selectedDevice, fetchLogs]);

  useEffect(() => {
    if (!autoRefresh || !selectedDevice || clearPending) return undefined;
    const interval = window.setInterval(() => void fetchLogs(selectedDevice, true), 5000);
    return () => window.clearInterval(interval);
  }, [autoRefresh, selectedDevice, fetchLogs, clearPending]);

  useEffect(() => () => { activeRequest.current?.abort(); ++requestSequence.current; }, []);

  const visibleLines = useMemo(
    () => levelFilter === 'ALL' ? lines : lines.filter((line) => line.level === levelFilter),
    [levelFilter, lines],
  );

  const handleClear = async () => {
    if (!selectedDevice || clearPending) return;
    setClearPending(true);
    setClearError(null);
    activeRequest.current?.abort();
    ++requestSequence.current;
    setLoading(false);
    try {
      await api.delete(`/logs/${encodeURIComponent(selectedDevice)}`);
      setLines([]);
      setTotalLines(0);
      setLastUpdatedAt(Date.now());
      setClearOpen(false);
      toast.success(`Логи устройства ${selectedDeviceInfo?.name ?? selectedDevice} удалены`);
    } catch (deleteError) {
      const message = errorMessage(deleteError);
      setClearError(message);
      toast.error(`Не удалось удалить логи: ${message}`);
    } finally {
      setClearPending(false);
    }
  };

  return (
    <section className="flex w-full flex-col gap-4" aria-label="Журнал выбранного устройства">
      <header className="flex flex-col gap-4 border-b border-border/70 pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Sphere / Диагностика</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">Системные логи</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Строки логов агента, уже полученные backend от устройства. Поиск выполняется на сервере с задержкой, чтобы не отправлять запрос на каждый символ.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant={autoRefresh ? 'secondary' : 'outline'} size="sm" onClick={() => setAutoRefresh((current) => !current)} disabled={!selectedDevice || clearPending} aria-pressed={autoRefresh}>
            {autoRefresh ? <Pause className="mr-2 h-4 w-4" aria-hidden="true" /> : <Play className="mr-2 h-4 w-4" aria-hidden="true" />}
            {autoRefresh ? 'Пауза автообновления' : 'Автообновление · 5 с'}
          </Button>
          <Button variant="outline" size="sm" onClick={() => void fetchLogs(selectedDevice, false)} disabled={!selectedDevice || loading || clearPending} aria-label="Обновить логи">
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
            Обновить
          </Button>
          <Button variant="destructive" size="sm" onClick={() => { setClearError(null); setClearOpen(true); }} disabled={!selectedDevice || clearPending || loading || !!error || !lastUpdatedAt}>
            <Trash2 className="mr-2 h-4 w-4" aria-hidden="true" />Очистить логи
          </Button>
        </div>
      </header>

      <Card className="overflow-hidden rounded-xl border-border/80">
        <div className="flex flex-col gap-3 border-b border-border/70 bg-muted/30 p-3 sm:flex-row sm:items-center sm:px-4">
          <Select value={levelFilter} onValueChange={(value) => setLevelFilter(value as LogLevel)}>
            <SelectTrigger className="h-9 w-full rounded-lg sm:w-[190px]" aria-label="Фильтр уровня логов"><SelectValue /></SelectTrigger>
            <SelectContent>{LEVELS.map((level) => <SelectItem key={level} value={level}>{LEVEL_LABELS[level]}</SelectItem>)}</SelectContent>
          </Select>

          <label className="relative block min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Поиск в логах" aria-label="Поиск в логах" disabled={!selectedDevice || clearPending} className="h-9 rounded-lg pl-9" />
          </label>

          <Badge variant="outline" className="w-fit shrink-0 rounded-full px-2.5 normal-case tracking-normal">
            {error ? 'Данные не подтверждены' : loading || search.trim() !== debouncedSearch ? 'Обновляем журнал…' : `${visibleLines.length} показано · ${totalLines} загружено`}
          </Badge>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/70 px-4 py-2.5 text-xs text-muted-foreground">
          <div className="flex min-w-0 items-center gap-2">
            <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate">{selectedDeviceInfo?.name ?? selectedDevice}</span>
            {<span className="hidden truncate font-mono opacity-70 sm:inline">{selectedDevice}</span>}
          </div>
          <span className="inline-flex items-center gap-1.5"><Clock3 className="h-3.5 w-3.5" aria-hidden="true" />Обновлено: {formatTime(lastUpdatedAt)}{autoRefresh ? ' · авто 5 с' : ''}</span>
        </div>

        <CardContent className="p-3 sm:p-4">
          <div ref={containerRef} aria-label="Строки системного журнала" aria-live="polite" className="max-h-[65vh] min-h-[320px] overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-3 font-mono text-[11px] leading-5 sm:p-4 sm:text-xs">
            {search.trim() !== debouncedSearch ? (
              <p role="status" className="py-8 text-center font-sans text-sm text-slate-400">Применяем поиск в журнале…</p>
            ) : error ? (
              <div role="alert" className="flex flex-col items-start gap-2 py-5 font-sans text-sm text-rose-300">
                <span className="flex items-center gap-2"><AlertCircle className="h-4 w-4" aria-hidden="true" />Логи не загружены: {error}</span>
                <Button variant="outline" size="sm" onClick={() => void fetchLogs(selectedDevice, false)}>Повторить запрос</Button>
              </div>
            ) : loading && lines.length === 0 ? (
              <p role="status" className="py-8 text-center font-sans text-sm text-slate-400">Загружаем логи устройства…</p>
            ) : !selectedDevice ? (
              <p className="py-8 text-center font-sans text-sm text-slate-400">Выберите устройство, чтобы просмотреть логи.</p>
            ) : visibleLines.length === 0 ? (
              <div className="py-8 text-center font-sans text-sm text-slate-400">{lines.length === 0 ? 'Для этого устройства пока нет полученных логов.' : 'Нет строк, подходящих под выбранный фильтр.'}</div>
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
          {clearError && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">Не удалось очистить логи: {clearError}</p>}
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
