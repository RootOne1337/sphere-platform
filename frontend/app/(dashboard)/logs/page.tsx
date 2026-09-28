'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Clock3, FileText, Pause, Play, RefreshCw, Search, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '@/lib/api';
import { useDevices, type Device } from '@/lib/hooks/useDevices';
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

const EMPTY_DEVICES: Device[] = [];
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

function validateLogsResponse(data: unknown): LogsResponse {
  if (!data || typeof data !== 'object') throw new Error('Backend вернул некорректный ответ логов.');
  const payload = data as Partial<LogsResponse>;
  if (typeof payload.device_id !== 'string' || !Array.isArray(payload.lines) || !payload.lines.every((line) => typeof line === 'string')) {
    throw new Error('Backend вернул некорректный список строк логов.');
  }
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

export default function LogsPage() {
  const devicesQuery = useDevices({});
  const devices = devicesQuery.data?.items ?? EMPTY_DEVICES;
  const [selectedDevice, setSelectedDevice] = useState('');
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

  const selectedDeviceInfo = devices.find((device) => device.id === selectedDevice);

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
      const payload = validateLogsResponse(response.data);
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
    if (!selectedDevice && devices.length > 0) setSelectedDevice(devices[0].id);
  }, [devices, selectedDevice]);

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
    if (!autoRefresh || !selectedDevice) return undefined;
    const interval = window.setInterval(() => void fetchLogs(selectedDevice, true), 5000);
    return () => window.clearInterval(interval);
  }, [autoRefresh, selectedDevice, fetchLogs]);

  useEffect(() => () => activeRequest.current?.abort(), []);

  const visibleLines = useMemo(
    () => levelFilter === 'ALL' ? lines : lines.filter((line) => line.level === levelFilter),
    [levelFilter, lines],
  );

  const handleClear = async () => {
    if (!selectedDevice || clearPending) return;
    setClearPending(true);
    setClearError(null);
    activeRequest.current?.abort();
    try {
      await api.delete(`/logs/${encodeURIComponent(selectedDevice)}`);
      setLines([]);
      setTotalLines(0);
      setLastUpdatedAt(Date.now());
      setClearOpen(false);
      toast.success('Логи устройства удалены');
    } catch (deleteError) {
      const message = errorMessage(deleteError);
      setClearError(message);
      toast.error(`Не удалось удалить логи: ${message}`);
    } finally {
      setClearPending(false);
    }
  };

  return (
    <main className="mx-auto flex w-full max-w-[1600px] flex-col gap-6 p-4 sm:p-6 lg:p-8">
      <header className="flex flex-col gap-4 border-b border-border/70 pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Sphere / Диагностика</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">Системные логи</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Строки логов агента, уже полученные backend от устройства. Поиск выполняется на сервере с задержкой, чтобы не отправлять запрос на каждый символ.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant={autoRefresh ? 'secondary' : 'outline'} size="sm" onClick={() => setAutoRefresh((current) => !current)} disabled={!selectedDevice} aria-pressed={autoRefresh}>
            {autoRefresh ? <Pause className="mr-2 h-4 w-4" aria-hidden="true" /> : <Play className="mr-2 h-4 w-4" aria-hidden="true" />}
            {autoRefresh ? 'Пауза автообновления' : 'Автообновление · 5 с'}
          </Button>
          <Button variant="outline" size="sm" onClick={() => void fetchLogs(selectedDevice, false)} disabled={!selectedDevice || loading} aria-label="Обновить логи">
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
            Обновить
          </Button>
          <Button variant="destructive" size="sm" onClick={() => { setClearError(null); setClearOpen(true); }} disabled={!selectedDevice || clearPending}>
            <Trash2 className="mr-2 h-4 w-4" aria-hidden="true" />Очистить логи
          </Button>
        </div>
      </header>

      {devicesQuery.isError && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">
          <span className="flex items-center gap-2"><AlertCircle className="h-4 w-4" aria-hidden="true" />Каталог устройств не загрузился. Выбрать источник логов пока нельзя.</span>
          <Button variant="outline" size="sm" onClick={() => void devicesQuery.refetch()}>Повторить</Button>
        </div>
      )}

      <Card className="overflow-hidden rounded-xl border-border/80">
        <div className="flex flex-col gap-3 border-b border-border/70 bg-muted/30 p-3 sm:flex-row sm:items-center sm:px-4">
          <Select value={selectedDevice} onValueChange={setSelectedDevice} disabled={devicesQuery.isLoading || devices.length === 0}>
            <SelectTrigger className="h-9 w-full rounded-lg sm:max-w-[310px]" aria-label="Устройство для просмотра логов">
              <SelectValue placeholder={devicesQuery.isLoading ? 'Загружаем устройства…' : 'Выберите устройство'} />
            </SelectTrigger>
            <SelectContent>
              {devices.map((device) => <SelectItem key={device.id} value={device.id}>{device.name} · {device.id.slice(0, 8)}</SelectItem>)}
            </SelectContent>
          </Select>

          <Select value={levelFilter} onValueChange={(value) => setLevelFilter(value as LogLevel)}>
            <SelectTrigger className="h-9 w-full rounded-lg sm:w-[190px]" aria-label="Фильтр уровня логов"><SelectValue /></SelectTrigger>
            <SelectContent>{LEVELS.map((level) => <SelectItem key={level} value={level}>{LEVEL_LABELS[level]}</SelectItem>)}</SelectContent>
          </Select>

          <label className="relative block min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Поиск в логах" aria-label="Поиск в логах" disabled={!selectedDevice} className="h-9 rounded-lg pl-9" />
          </label>

          <Badge variant="outline" className="w-fit shrink-0 rounded-full px-2.5 normal-case tracking-normal">
            {visibleLines.length} показано · {totalLines} загружено
          </Badge>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/70 px-4 py-2.5 text-xs text-muted-foreground">
          <div className="flex min-w-0 items-center gap-2">
            <FileText className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span className="truncate">{selectedDeviceInfo?.name ?? 'Устройство не выбрано'}</span>
            {selectedDeviceInfo && <span className="hidden truncate font-mono opacity-70 sm:inline">{selectedDevice}</span>}
          </div>
          <span className="inline-flex items-center gap-1.5"><Clock3 className="h-3.5 w-3.5" aria-hidden="true" />Обновлено: {formatTime(lastUpdatedAt)}{autoRefresh ? ' · авто 5 с' : ''}</span>
        </div>

        <CardContent className="p-3 sm:p-4">
          <div ref={containerRef} aria-label="Строки системного журнала" aria-live="polite" className="max-h-[65vh] min-h-[320px] overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-3 font-mono text-[11px] leading-5 sm:p-4 sm:text-xs">
            {devicesQuery.isLoading ? (
              <p role="status" className="py-8 text-center font-sans text-sm text-slate-400">Загружаем каталог устройств…</p>
            ) : devicesQuery.isError ? null : devices.length === 0 ? (
              <div className="flex flex-col items-center py-10 text-center font-sans">
                <FileText className="h-6 w-6 text-slate-500" aria-hidden="true" />
                <p className="mt-3 text-sm font-medium text-slate-200">Устройств пока нет</p>
                <p className="mt-1 text-xs text-slate-400">Здесь появятся логи после регистрации Android-агента.</p>
              </div>
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
    </main>
  );
}
