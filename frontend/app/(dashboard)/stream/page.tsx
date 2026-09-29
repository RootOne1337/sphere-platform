'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2, Clock3, MonitorPlay, Radio, RefreshCw, Search, Wifi, WifiOff, Zap } from 'lucide-react';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { useDevices, type Device } from '@/lib/hooks/useDevices';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { useGroups } from '@/lib/hooks/useGroups';
import { useLocations } from '@/lib/hooks/useLocations';
import {
  isDeviceReachable,
  type DeviceStatusFilter,
} from '@/src/features/devices/deviceListFilters';
import { getStreamAspectRatio, type StreamFrameDimensions } from '@/src/features/stream/streamAspectRatio';

/** Grid capacities also bound the server response; streams start only on an explicit user action. */
const GRID_SIZES = [1, 2, 4, 6, 9, 12, 16, 25, 32, 64] as const;
const EMPTY_DEVICES: Device[] = [];

type SortField = 'name' | 'status' | 'model' | 'last_seen' | 'battery_level';
type SortDir = 'asc' | 'desc';

const SORT_FIELDS: Array<{ value: SortField; label: string }> = [
  { value: 'name', label: 'Имя' },
  { value: 'status', label: 'Статус' },
  { value: 'model', label: 'Модель' },
  { value: 'battery_level', label: 'Батарея' },
  { value: 'last_seen', label: 'Последняя связь' },
];

const STATUS_LABELS: Record<Device['status'], string> = {
  online: 'В сети',
  busy: 'В работе',
  connecting: 'Подключается',
  offline: 'Не в сети',
  error: 'Ошибка',
  maintenance: 'Обслуживание',
  unknown: 'Статус неизвестен',
};

const STATUS_TONES: Record<Device['status'], string> = {
  online: 'text-emerald-400',
  busy: 'text-primary',
  connecting: 'text-amber-400',
  offline: 'text-muted-foreground',
  error: 'text-destructive',
  maintenance: 'text-amber-400',
  unknown: 'text-muted-foreground',
};

const STATUS_FILTER_LABELS: Array<{ value: DeviceStatusFilter; label: string }> = [
  { value: 'all', label: 'Все' },
  { value: 'online', label: 'Доступны' },
  { value: 'connecting', label: 'Подключаются' },
  { value: 'offline', label: 'Офлайн' },
  { value: 'attention', label: 'Проблемы' },
];

export default function FleetStreamPage() {
  const [gridSize, setGridSize] = useState<(typeof GRID_SIZES)[number]>(4);
  const [activeStreams, setActiveStreams] = useState<Set<string>>(new Set());
  const [frameDimensionsByDevice, setFrameDimensionsByDevice] = useState<Record<string, StreamFrameDimensions>>({});
  const [statusFilter, setStatusFilter] = useState<DeviceStatusFilter>('all');
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search.trim(), 300);
  const [listPage, setListPage] = useState(1);
  const [filterGroupId, setFilterGroupId] = useState('');
  const [filterLocationId, setFilterLocationId] = useState('');
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const liveStatus = statusFilter === 'all' ? undefined : statusFilter;
  const { data, dataUpdatedAt, isLoading, isError, isFetching, refetch } = useDevices({
    page: listPage,
    page_size: gridSize,
    live_status: liveStatus,
    search: debouncedSearch || undefined,
    group_id: filterGroupId || undefined,
    location_id: filterLocationId || undefined,
  });
  const catalogUpdatedAt = dataUpdatedAt > 0 ? new Date(dataUpdatedAt) : null;
  const allDevices = data?.items ?? EMPTY_DEVICES;
  const scopeTotal = data?.scope_total ?? data?.total ?? 0;
  const statusCounts = data?.status_counts ?? null;
  const { data: groups } = useGroups();
  const { data: locations } = useLocations();

  const statusFilterCounts: Record<DeviceStatusFilter, number | null> = {
    all: scopeTotal,
    online: statusCounts?.online ?? null,
    busy: statusCounts?.busy ?? null,
    connecting: statusCounts?.connecting ?? null,
    offline: statusCounts?.offline ?? null,
    attention: statusCounts?.issues ?? null,
  };

  const sortedDevices = useMemo(() => {
    const compare = (a: Device, b: Device) => {
      switch (sortField) {
        case 'name':
          return (a.name || '').localeCompare(b.name || '');
        case 'status':
          return (a.status || '').localeCompare(b.status || '');
        case 'model':
          return (a.model || '').localeCompare(b.model || '');
        case 'last_seen': {
          const left = a.last_seen ? Date.parse(a.last_seen) : Number.NaN;
          const right = b.last_seen ? Date.parse(b.last_seen) : Number.NaN;
          if (!Number.isFinite(left)) return Number.isFinite(right) ? -1 : 0;
          if (!Number.isFinite(right)) return 1;
          return left - right;
        }
        case 'battery_level':
          return (a.battery_level ?? -1) - (b.battery_level ?? -1);
      }
      return 0;
    };
    // The API owns global filtering and paging. This optional sort is deliberately
    // page-local until the backend exposes a validated sort contract.
    return [...allDevices].sort((a, b) => (sortDir === 'asc' ? 1 : -1) * compare(a, b));
  }, [allDevices, sortDir, sortField]);

  // The selected grid capacity is also the server page size, bounding both the
  // response body and DOM when the organization has thousands of devices.
  const totalPages = Math.max(1, data?.pages ?? Math.ceil((data?.total ?? 0) / gridSize));
  const currentPage = Math.min(listPage, totalPages);
  const visibleDevices = sortedDevices;
  const queryPending = search.trim() !== debouncedSearch;

  useEffect(() => {
    if (listPage > totalPages) setListPage(totalPages);
  }, [listPage, totalPages]);

  const startStream = useCallback((deviceId: string) => {
    setActiveStreams((previous) => new Set(previous).add(deviceId));
  }, []);

  const stopStream = useCallback((deviceId: string) => {
    setActiveStreams((previous) => {
      const next = new Set(previous);
      next.delete(deviceId);
      return next;
    });
  }, []);

  const updateFrameDimensions = useCallback((deviceId: string, dimensions: StreamFrameDimensions) => {
    setFrameDimensionsByDevice((previous) => {
      const current = previous[deviceId];
      if (current?.width === dimensions.width && current.height === dimensions.height) return previous;
      return { ...previous, [deviceId]: dimensions };
    });
  }, []);

  const updateGridSize = (size: (typeof GRID_SIZES)[number]) => {
    setGridSize(size);
    setListPage(1);
  };

  const updateFilter = (update: () => void) => {
    update();
    setListPage(1);
  };

  const toggleSort = (field: SortField) => {
    if (sortField === field) setSortDir((previous) => previous === 'asc' ? 'desc' : 'asc');
    else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  return (
    <main className="min-w-0 space-y-5 p-4 md:p-6">
      <header className="flex flex-col justify-between gap-4 border-b border-border pb-5 lg:flex-row lg:items-end">
        <div className="min-w-0">
          <p className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.16em] text-primary">
            <Radio className="h-4 w-4" aria-hidden="true" /> Операционный центр
          </p>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">Потоки устройств</h1>
          <p className="mt-1 text-sm text-muted-foreground">Открывайте просмотр только для выбранных устройств. Потоки запускаются по запросу.</p>
        </div>
        <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center">
          {catalogUpdatedAt ? (
            <span
              aria-label="Время последнего успешного ответа каталога API"
              title={catalogUpdatedAt.toLocaleString()}
              className="inline-flex min-h-9 items-center gap-2 rounded-md border border-border bg-card/60 px-3 text-xs text-muted-foreground"
            >
              <Clock3 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span>Ответ API · <time dateTime={catalogUpdatedAt.toISOString()}>{catalogUpdatedAt.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}</time></span>
            </span>
          ) : (
            <span role="status" className="inline-flex min-h-9 items-center gap-2 rounded-md border border-border bg-card/60 px-3 text-xs text-muted-foreground">
              <Clock3 className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> {isError ? 'Нет успешного ответа API' : 'Ожидаем первый ответ API'}
            </span>
          )}
          <button
            type="button"
            onClick={() => { void refetch(); }}
            disabled={isFetching}
            aria-label="Обновить список устройств"
            className="inline-flex h-10 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md border border-border bg-card px-3 text-sm font-medium text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-wait disabled:opacity-60 motion-reduce:transition-none"
          >
            <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} aria-hidden="true" />
            {isFetching ? 'Обновляем…' : 'Обновить данные'}
          </button>
        </div>
      </header>

      <section aria-label="Состояние устройств" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <MetricCard label="В области" value={isLoading ? '—' : scopeTotal} detail="Устройства после поиска и группировки" icon={MonitorPlay} tone="text-foreground" />
        <MetricCard label="Доступны" value={isLoading ? '—' : statusCounts?.online ?? '—'} detail="В сети или выполняют задачу" icon={Wifi} tone="text-emerald-400" />
        <MetricCard label="В работе" value={isLoading ? '—' : statusCounts?.busy ?? '—'} detail="Статус API: busy" icon={Zap} tone="text-primary" />
        <MetricCard label="Подключаются" value={isLoading ? '—' : statusCounts?.connecting ?? '—'} detail="Ожидают heartbeat" icon={Clock3} tone="text-amber-400" />
        <MetricCard label="Офлайн / проблемы" value={isLoading ? '—' : statusCounts ? statusCounts.offline + statusCounts.issues : '—'} detail="Offline, ошибки, обслуживание или неизвестно" icon={WifiOff} tone={statusCounts?.issues ? 'text-destructive' : 'text-muted-foreground'} />
      </section>

      {isError && (
        <div role="alert" className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div><p className="font-medium">Не удалось обновить список устройств.</p><p className="mt-0.5 text-destructive/80">{data ? 'Показаны последние загруженные данные.' : 'Проверьте соединение с API и повторите загрузку.'}</p></div>
        </div>
      )}

      {data?.presence_available === false && (
        <p role="status" className="rounded-lg border border-amber-400/25 bg-amber-400/5 px-3 py-2 text-xs text-amber-200">
          Live-presence недоступен: API не подтвердил состояние устройств. Не запускайте новые потоки, пока связь со статусным хранилищем не восстановится.
        </p>
      )}

      <section className="space-y-4 rounded-xl border border-border bg-card/60 p-3 shadow-sm md:p-4" aria-label="Управление потоками">
        <div className="flex flex-col gap-3 border-b border-border pb-4 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <div role="group" aria-label="Количество устройств на странице" className="flex flex-wrap items-center gap-1 rounded-lg border border-border bg-background p-1">
              <span className="px-2 text-xs text-muted-foreground">На странице</span>
              {GRID_SIZES.map((size) => (
                <button
                  key={size}
                  type="button"
                  aria-label={`Показывать до ${size} устройств`}
                  aria-pressed={gridSize === size}
                  onClick={() => updateGridSize(size)}
                  className={`min-h-8 min-w-9 rounded px-2 text-xs font-medium tabular-nums transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none ${gridSize === size ? 'bg-primary text-primary-foreground shadow-sm' : 'text-muted-foreground hover:bg-accent hover:text-foreground'}`}
                >{size}</button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground" aria-live="polite">
              {isLoading ? 'Загружаем устройства…' : `${statusCounts?.online ?? '—'} доступны · ${activeStreams.size} выбрано для просмотра`}
            </p>
          </div>
          {activeStreams.size > 0 && (
            <button
              type="button"
              onClick={() => setActiveStreams(new Set())}
              className="inline-flex min-h-9 items-center justify-center gap-2 self-start rounded-md bg-destructive px-3 text-sm font-medium text-destructive-foreground transition-colors hover:bg-destructive/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring xl:self-auto motion-reduce:transition-none"
            >
              <WifiOff className="h-4 w-4" aria-hidden="true" /> Остановить просмотр ({activeStreams.size})
            </button>
          )}
        </div>

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[minmax(16rem,1.6fr)_repeat(2,minmax(10rem,1fr))]">
          <label className="relative block min-w-0">
            <span className="sr-only">Поиск устройств</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <input
              type="search"
              placeholder="Имя, Android ID или модель"
              value={search}
              onChange={(event) => updateFilter(() => setSearch(event.target.value))}
              className="h-10 w-full rounded-md border border-input bg-background pl-9 pr-3 text-sm text-foreground outline-none transition-shadow placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
            />
          </label>

          <label>
            <span className="sr-only">Фильтр по группе</span>
            <select aria-label="Фильтр по группе" value={filterGroupId} onChange={(event) => updateFilter(() => setFilterGroupId(event.target.value))} className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <option value="">Все группы</option>
              {groups?.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
            </select>
          </label>

          <label>
            <span className="sr-only">Фильтр по локации</span>
            <select aria-label="Фильтр по локации" value={filterLocationId} onChange={(event) => updateFilter(() => setFilterLocationId(event.target.value))} className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <option value="">Все локации</option>
              {locations?.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}
            </select>
          </label>
        </div>

        <div role="group" aria-label="Фильтр состояния устройств" className="flex flex-wrap gap-2">
          {STATUS_FILTER_LABELS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              aria-pressed={statusFilter === value}
              onClick={() => updateFilter(() => setStatusFilter(value))}
              className={`inline-flex min-h-9 items-center gap-2 rounded-full border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none ${statusFilter === value ? 'border-primary/50 bg-primary/10 text-primary' : 'border-border bg-background text-muted-foreground hover:bg-accent hover:text-foreground'}`}
            >
              <span>{label}</span>
              <span className="tabular-nums opacity-75">{statusFilterCounts[value] ?? '—'}</span>
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-2 border-b border-border pb-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {queryPending ? 'Применяем поиск…' : isLoading ? 'Загрузка…' : `Показано ${visibleDevices.length} из ${data?.total ?? 0} устройств`}
            {(data?.total ?? 0) > 0 && ` · страница ${currentPage} из ${totalPages}`}
          </p>
          <div role="group" aria-label="Сортировка устройств" className="flex flex-wrap items-center gap-1">
            <span className="mr-1 text-xs text-muted-foreground">Сортировка страницы:</span>
            {SORT_FIELDS.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                aria-pressed={sortField === value}
                onClick={() => toggleSort(value)}
                className={`min-h-8 rounded px-2 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none ${sortField === value ? 'bg-primary/15 font-medium text-primary' : 'text-muted-foreground hover:bg-accent hover:text-foreground'}`}
              >
                {label}{sortField === value && <span aria-hidden="true"> {sortDir === 'asc' ? '↑' : '↓'}</span>}
                {sortField === value && <span className="sr-only">, {sortDir === 'asc' ? 'по возрастанию' : 'по убыванию'}</span>}
              </button>
            ))}
          </div>
        </div>

        <p className="text-xs leading-5 text-muted-foreground">
          Управление доступно только при поступлении свежих кадров. Выбор сохраняется при временной потере связи и после возврата устройства на текущую страницу.
          Если карточку скрыть фильтром или перейти на другую страницу, её WebSocket закрывается до следующего показа.
        </p>

        {isLoading && allDevices.length === 0 ? (
          <p role="status" className="rounded-lg border border-dashed border-border py-16 text-center text-sm text-muted-foreground">Загружаем список устройств…</p>
        ) : isError && allDevices.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-4 py-12 text-center">
            <AlertTriangle className="mx-auto h-6 w-6 text-destructive" aria-hidden="true" />
            <p className="mt-3 text-sm font-medium">Список устройств недоступен</p>
            <button type="button" onClick={() => { void refetch(); }} className="mt-3 rounded-md border border-border px-3 py-2 text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Повторить</button>
          </div>
        ) : visibleDevices.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border px-4 py-14 text-center">
            <MonitorPlay className="mx-auto h-7 w-7 text-muted-foreground" aria-hidden="true" />
            <p className="mt-3 text-sm font-medium">Устройства не найдены</p>
            <p className="mt-1 text-xs text-muted-foreground">Измените фильтры или проверьте регистрацию устройств.</p>
          </div>
        ) : (
          <div
            className="grid gap-3"
            style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 17rem), 1fr))' }}
          >
            {visibleDevices.map((device) => {
              const isActive = activeStreams.has(device.id);
              const reachable = isDeviceReachable(device);
              const heartbeat = describeHeartbeat(device.last_heartbeat);
              return (
                <article key={device.id} className="group min-w-0 overflow-hidden rounded-lg border border-border bg-background shadow-sm transition-[border-color,box-shadow] hover:border-primary/40 hover:shadow-md motion-reduce:transition-none">
                  <div className="flex min-h-12 items-center justify-between gap-2 border-b border-border px-3 py-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-foreground" title={device.name}>{device.name || 'Без имени'}</p>
                      <p className="truncate text-[11px] text-muted-foreground" title={device.android_id}>{device.android_id || device.model || 'Android-устройство'}</p>
                    </div>
                    <span className={`shrink-0 text-[11px] font-medium ${STATUS_TONES[device.status]}`}>
                      {STATUS_LABELS[device.status]}
                    </span>
                  </div>

                  <div
                    className="w-full overflow-hidden bg-black"
                    style={{ aspectRatio: getStreamAspectRatio(frameDimensionsByDevice[device.id]) }}
                    aria-label={`Видеокадр устройства ${device.name}`}
                  >
                    {isActive && reachable ? (
                      <DeviceStream
                        deviceId={device.id}
                        fit="contain"
                        enableDiagnostics
                        onFrameDimensions={(dimensions) => updateFrameDimensions(device.id, dimensions)}
                      />
                    ) : (
                      <div className="flex h-full flex-col items-center justify-center gap-2 px-3 text-center text-xs text-muted-foreground">
                        {isActive ? <WifiOff className="h-5 w-5 text-amber-400" aria-hidden="true" /> : <MonitorPlay className="h-5 w-5" aria-hidden="true" />}
                        <span>{isActive ? 'Просмотр приостановлен до восстановления связи' : reachable ? 'Запустите просмотр по запросу' : 'Устройство сейчас недоступно'}</span>
                      </div>
                    )}
                  </div>

                  <div className="flex items-center justify-between gap-2 px-3 py-2">
                    <div className="min-w-0">
                      <span className="flex min-w-0 items-center gap-1.5 truncate text-[11px] text-muted-foreground">
                        {reachable ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-400" aria-hidden="true" /> : <Activity className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
                        <span className="truncate">{device.model || device.android_version || 'Android'}</span>
                      </span>
                      <span
                        aria-label={`Последний heartbeat: ${heartbeat.label}`}
                        title={heartbeat.title}
                        className={`mt-1 flex items-center gap-1.5 truncate text-[10px] ${heartbeat.fresh ? 'text-emerald-400' : 'text-amber-400'}`}
                      >
                        <Clock3 className="h-3 w-3 shrink-0" aria-hidden="true" />
                        <time dateTime={device.last_heartbeat ?? undefined} className="truncate">{heartbeat.label}</time>
                      </span>
                    </div>
                    {isActive ? (
                      <button type="button" onClick={() => stopStream(device.id)} aria-label={`Остановить просмотр ${device.name}`} className="min-h-8 shrink-0 rounded-md border border-destructive/30 px-2.5 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none">Стоп</button>
                    ) : (
                      <button type="button" onClick={() => startStream(device.id)} disabled={!reachable} aria-label={`Начать просмотр ${device.name}`} className="min-h-8 shrink-0 rounded-md bg-primary px-2.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-40 motion-reduce:transition-none">Смотреть</button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}

        {totalPages > 1 && (
          <nav aria-label="Страницы списка устройств" className="flex items-center justify-center gap-3 border-t border-border pt-3">
            <button type="button" disabled={currentPage <= 1} onClick={() => setListPage((page) => Math.max(1, page - 1))} aria-label="Предыдущая страница" className="min-h-9 rounded-md border border-border px-3 text-sm transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Назад</button>
            <span className="min-w-24 text-center text-xs tabular-nums text-muted-foreground">{currentPage} / {totalPages}</span>
            <button type="button" disabled={currentPage >= totalPages} onClick={() => setListPage((page) => Math.min(totalPages, page + 1))} aria-label="Следующая страница" className="min-h-9 rounded-md border border-border px-3 text-sm transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Вперёд</button>
          </nav>
        )}
      </section>
    </main>
  );
}

function MetricCard({ label, value, detail, icon: Icon, tone }: {
  label: string;
  value: number | string;
  detail: string;
  icon: typeof MonitorPlay;
  tone: string;
}) {
  return (
    <article className="min-w-0 rounded-lg border border-border bg-card p-3 shadow-sm md:p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-xs font-medium text-muted-foreground">{label}</p>
        <Icon className={`h-4 w-4 shrink-0 ${tone}`} aria-hidden="true" />
      </div>
      <p className={`mt-2 text-2xl font-semibold tabular-nums ${tone}`}>{value}</p>
      <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-muted-foreground">{detail}</p>
    </article>
  );
}

function describeHeartbeat(value: string | null | undefined): {
  label: string;
  fresh: boolean;
  title?: string;
} {
  if (!value) return { label: 'Heartbeat нет', fresh: false };
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return { label: 'Время heartbeat неизвестно', fresh: false };

  const ageSeconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  const relative = ageSeconds < 60
    ? `${ageSeconds} с назад`
    : ageSeconds < 3600
      ? `${Math.floor(ageSeconds / 60)} мин назад`
      : `${Math.floor(ageSeconds / 3600)} ч назад`;
  return {
    label: `Heartbeat · ${relative}`,
    fresh: ageSeconds <= 75,
    title: new Date(timestamp).toLocaleString(),
  };
}
