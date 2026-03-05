'use client';
import { useState, useCallback, useMemo } from 'react';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { useDevices, type Device } from '@/lib/hooks/useDevices';

/** Размеры сетки стрима — от 1 до 16 ячеек */
const GRID_SIZES = [1, 2, 4, 6, 9, 12, 16] as const;

/** Количество устройств на одной странице списка */
const DEVICES_PER_PAGE = 50;

export default function FleetStreamPage() {
  const [gridSize, setGridSize] = useState<(typeof GRID_SIZES)[number]>(4);
  const [activeStreams, setActiveStreams] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState('');
  const [listPage, setListPage] = useState(1);

  // Загружаем все онлайн-устройства (до 500)
  const { data } = useDevices({ status: 'online', page_size: 5000 });
  const allDevices = data?.items ?? [];
  const totalOnline = data?.total ?? 0;

  // Фильтрация по поисковому запросу
  const filteredDevices = useMemo(() => {
    if (!search.trim()) return allDevices;
    const q = search.toLowerCase();
    return allDevices.filter(
      (d) =>
        d.name.toLowerCase().includes(q) ||
        d.android_id.toLowerCase().includes(q) ||
        d.model.toLowerCase().includes(q),
    );
  }, [allDevices, search]);

  // Пагинация списка устройств
  const totalPages = Math.max(1, Math.ceil(filteredDevices.length / DEVICES_PER_PAGE));
  const pagedDevices = filteredDevices.slice(
    (listPage - 1) * DEVICES_PER_PAGE,
    listPage * DEVICES_PER_PAGE,
  );

  // Колонки грида в зависимости от размера
  const cols = gridSize <= 2 ? gridSize : gridSize <= 4 ? 2 : gridSize <= 9 ? 3 : 4;

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

  return (
    <div className="p-4 space-y-4">
      {/* Панель управления */}
      <div className="flex gap-2 items-center flex-wrap">
        <span className="text-sm text-muted-foreground">Grid:</span>
        {GRID_SIZES.map((s) => (
          <button
            key={s}
            onClick={() => setGridSize(s)}
            className={`px-2 py-1 rounded text-sm ${
              gridSize === s ? 'bg-primary text-primary-foreground' : 'bg-secondary'
            }`}
          >
            {s}x
          </button>
        ))}
        <span className="text-xs text-muted-foreground ml-2">
          {totalOnline} онлайн
          {filteredDevices.length !== allDevices.length && ` / ${filteredDevices.length} найдено`}
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

      {/* Поиск по устройствам */}
      <input
        type="text"
        placeholder="Поиск по имени, android_id, модели..."
        value={search}
        onChange={(e) => {
          setSearch(e.target.value);
          setListPage(1);
        }}
        className="w-full max-w-md px-3 py-1.5 rounded border border-gray-700 bg-background text-sm"
      />

      {filteredDevices.length === 0 && (
        <p className="text-sm text-muted-foreground">Устройства не найдены.</p>
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
                <p className="text-xs text-muted-foreground truncate flex-1" title={device.name}>
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
                <div className="rounded border border-gray-700 bg-black flex items-center justify-center text-xs text-gray-500"
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
          <span className="text-xs text-muted-foreground">
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
