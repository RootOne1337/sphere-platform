'use client';
import { useState, useCallback, useMemo } from 'react';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { useDevices, type Device } from '@/lib/hooks/useDevices';
import { useGroups } from '@/lib/hooks/useGroups';
import { useLocations } from '@/lib/hooks/useLocations';

/**
 * Размеры сетки стрима — от 1 до 64 ячеек.
 * 32 и 64 — enterprise-уровень для массового мониторинга.
 */
const GRID_SIZES = [1, 2, 4, 6, 9, 12, 16, 25, 32, 64] as const;

/** Количество устройств на одной странице списка */
const DEVICES_PER_PAGE = 50;

/** Варианты сортировки */
type SortField = 'name' | 'status' | 'model' | 'last_seen' | 'battery_level';
type SortDir = 'asc' | 'desc';

export default function FleetStreamPage() {
  const [gridSize, setGridSize] = useState<(typeof GRID_SIZES)[number]>(4);
  const [activeStreams, setActiveStreams] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [listPage, setListPage] = useState(1);

  // Фильтры по группе и локации
  const [filterGroupId, setFilterGroupId] = useState<string>('');
  const [filterLocationId, setFilterLocationId] = useState<string>('');

  // Сортировка
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  // Загружаем все онлайн-устройства (до 5000)
  const { data } = useDevices({ status: 'online', page_size: 5000 });
  const allDevices = data?.items ?? [];
  const totalOnline = data?.total ?? 0;

  // Группы и локации для фильтров
  const { data: groups } = useGroups();
  const { data: locations } = useLocations();

  // Фильтрация: поиск + группа + локация
  const filteredDevices = useMemo(() => {
    let result = allDevices;

    // Фильтр по группе
    if (filterGroupId) {
      result = result.filter(
        (d) => d.group_id === filterGroupId || d.group_ids?.includes(filterGroupId),
      );
    }

    // Фильтр по локации
    if (filterLocationId) {
      result = result.filter((d) => d.location_ids?.includes(filterLocationId));
    }

    // Поиск по тексту
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (d) =>
          (d.name || '').toLowerCase().includes(q) ||
          (d.android_id || '').toLowerCase().includes(q) ||
          (d.model || '').toLowerCase().includes(q),
      );
    }

    return result;
  }, [allDevices, search, filterGroupId, filterLocationId]);

  // Сортировка
  const sortedDevices = useMemo(() => {
    const sorted = [...filteredDevices];
    sorted.sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case 'name':
          cmp = (a.name || '').localeCompare(b.name || '');
          break;
        case 'status':
          cmp = (a.status || '').localeCompare(b.status || '');
          break;
        case 'model':
          cmp = (a.model || '').localeCompare(b.model || '');
          break;
        case 'last_seen':
          cmp = (a.last_seen || '').localeCompare(b.last_seen || '');
          break;
        case 'battery_level':
          cmp = (a.battery_level ?? -1) - (b.battery_level ?? -1);
          break;
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });
    return sorted;
  }, [filteredDevices, sortField, sortDir]);

  // Пагинация списка устройств
  const totalPages = Math.max(1, Math.ceil(sortedDevices.length / DEVICES_PER_PAGE));
  const pagedDevices = sortedDevices.slice(
    (listPage - 1) * DEVICES_PER_PAGE,
    listPage * DEVICES_PER_PAGE,
  );

  // Колонки грида с поддержкой до 8×8
  const cols = gridSize <= 2 ? gridSize : gridSize <= 4 ? 2 : gridSize <= 9 ? 3 : gridSize <= 16 ? 4 : gridSize <= 25 ? 5 : gridSize <= 32 ? 6 : 8;

  const startStream = useCallback((deviceId: string) => {
    setActiveStreams((prev) => new Set([...prev, deviceId]));
  }, []);

  const stopStream = useCallback((deviceId: string) => {
    setActiveStreams((prev) => {
      const next = new Set(prev);
      next.delete(deviceId);
      return next;
    });
  }, []);

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  return (
    <div className="p-4 space-y-4">
      {/* Панель управления — Grid Size */}
      <div className="flex gap-2 items-center flex-wrap">
        <span className="text-sm text-muted-foreground font-mono">Grid:</span>
        {GRID_SIZES.map((s) => (
          <button
            key={s}
            onClick={() => setGridSize(s)}
            className={`px-2 py-1 rounded text-sm font-mono ${
              gridSize === s ? 'bg-primary text-primary-foreground' : 'bg-secondary'
            }`}
          >
            {s}x
          </button>
        ))}
        <span className="text-xs text-muted-foreground ml-2 font-mono">
          {totalOnline} онлайн
          {sortedDevices.length !== allDevices.length && ` / ${sortedDevices.length} найдено`}
        </span>
        {activeStreams.size > 0 && (
          <button
            onClick={() => setActiveStreams(new Set())}
            className="ml-auto px-3 py-1 rounded text-sm bg-destructive text-destructive-foreground"
          >
            Стоп все ({activeStreams.size})
          </button>
        )}
      </div>

      {/* Строка фильтров: Поиск + Группа + Локация + Сортировка */}
      <div className="flex gap-3 items-center flex-wrap">
        <input
          type="text"
          placeholder="Поиск по имени, android_id, модели..."
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setListPage(1);
          }}
          className="w-full max-w-xs px-3 py-1.5 rounded border border-border bg-background text-sm font-mono"
        />

        {/* Фильтр по группе */}
        <select
          value={filterGroupId}
          onChange={(e) => { setFilterGroupId(e.target.value); setListPage(1); }}
          className="px-3 py-1.5 rounded border border-border bg-background text-sm font-mono"
        >
          <option value="">Все группы</option>
          {groups?.map((g) => (
            <option key={g.id} value={g.id}>{g.name}</option>
          ))}
        </select>

        {/* Фильтр по локации */}
        <select
          value={filterLocationId}
          onChange={(e) => { setFilterLocationId(e.target.value); setListPage(1); }}
          className="px-3 py-1.5 rounded border border-border bg-background text-sm font-mono"
        >
          <option value="">Все локации</option>
          {locations?.map((l) => (
            <option key={l.id} value={l.id}>{l.name}</option>
          ))}
        </select>

        {/* Сортировка */}
        <div className="flex items-center gap-1">
          <span className="text-xs text-muted-foreground font-mono">Sort:</span>
          {(['name', 'model', 'battery_level', 'last_seen'] as SortField[]).map((field) => (
            <button
              key={field}
              onClick={() => toggleSort(field)}
              className={`px-2 py-1 rounded text-xs font-mono ${
                sortField === field ? 'bg-primary text-primary-foreground' : 'bg-secondary text-muted-foreground'
              }`}
            >
              {field === 'battery_level' ? 'BAT' : field === 'last_seen' ? 'SEEN' : field.toUpperCase()}
              {sortField === field && (sortDir === 'asc' ? ' ↑' : ' ↓')}
            </button>
          ))}
        </div>
      </div>

      {sortedDevices.length === 0 && (
        <p className="text-sm text-muted-foreground font-mono">Устройства не найдены.</p>
      )}

      {/* Грид стримов */}
      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}
      >
        {pagedDevices.slice(0, gridSize).map((device) => {
          const isActive = activeStreams.has(device.id);
          return (
            <div key={device.id} className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground truncate flex-1 font-mono" title={device.name}>
                  {device.name}
                </p>
                {isActive ? (
                  <button
                    onClick={() => stopStream(device.id)}
                    className="shrink-0 px-2 py-0.5 rounded text-xs bg-destructive text-destructive-foreground"
                  >
                    Stop
                  </button>
                ) : (
                  <button
                    onClick={() => startStream(device.id)}
                    className="shrink-0 px-2 py-0.5 rounded text-xs bg-primary text-primary-foreground"
                  >
                    Start
                  </button>
                )}
              </div>
              {isActive ? (
                <DeviceStream deviceId={device.id} />
              ) : (
                <div className="rounded border border-border bg-black flex items-center justify-center text-xs text-muted-foreground font-mono"
                  style={{ aspectRatio: '9/16' }}>
                  Нажми Start для начала стрима
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Пагинация */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 pt-2">
          <button
            disabled={listPage <= 1}
            onClick={() => setListPage((p) => p - 1)}
            className="px-2 py-1 rounded text-sm bg-secondary disabled:opacity-40"
          >
            ←
          </button>
          <span className="text-xs text-muted-foreground font-mono">
            {listPage} / {totalPages}
          </span>
          <button
            disabled={listPage >= totalPages}
            onClick={() => setListPage((p) => p + 1)}
            className="px-2 py-1 rounded text-sm bg-secondary disabled:opacity-40"
          >
            →
          </button>
        </div>
      )}
    </div>
  );
}
