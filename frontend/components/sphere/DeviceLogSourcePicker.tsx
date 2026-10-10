'use client';

import { useEffect, useState } from 'react';
import { useDevices } from '@/lib/hooks/useDevices';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { CatalogPagination } from '@/src/shared/ui/catalog-pagination';

const PAGE_SIZE = 100;

/** Catalog paging and searching never change the confirmed source of the log viewer. */
export function DeviceLogSourcePicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const [search, setSearch] = useState('');
  const query = useDebounce(search.trim(), 300);
  const [page, setPage] = useState(1);
  const catalog = useDevices({ page, page_size: PAGE_SIZE, search: query || undefined });
  const devices = catalog.data?.items ?? [];
  const busy = catalog.isFetching || search.trim() !== query;

  useEffect(() => {
    if (!value && !search.trim() && page === 1 && catalog.isSuccess && !catalog.isFetching && devices.length) onChange(devices[0].id);
  }, [value, search, page, catalog.isSuccess, catalog.isFetching, devices, onChange]);

  return (
    <div className="space-y-3 rounded-xl border border-border bg-card p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1.5 text-sm font-medium">
          <span>Источник системного журнала</span>
          <Input aria-label="Поиск источника логов во всём каталоге" value={search} placeholder="Имя, serial, модель или полный UUID"
            onChange={event => { setSearch(event.target.value); setPage(1); }} />
        </label>
        <div className="space-y-1.5">
          <p className="text-sm font-medium">Выберите устройство</p>
          <Select value={value} onValueChange={onChange} disabled={busy || catalog.isError || !devices.length}>
            <SelectTrigger aria-label="Устройство для просмотра логов"><SelectValue placeholder="Выберите устройство" /></SelectTrigger>
            <SelectContent>
              {value && !devices.some(device => device.id === value) && <SelectItem value={value}>Текущий источник · {value}</SelectItem>}
              {!catalog.isError && devices.map(device => <SelectItem key={device.id} value={device.id}>{device.name} · {device.id.slice(0, 8)}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">Поиск выполняется во всём каталоге. Логи продолжают показываться для выбранного ID, пока вы явно не выберете другой источник.</p>
      {catalog.isError ? <div role="alert" className="flex flex-wrap items-center justify-between gap-3 text-sm text-destructive">
        <span>Каталог устройств не загрузился. Существующий источник логов сохранён.</span>
        <Button variant="outline" size="sm" onClick={() => void catalog.refetch()}>Повторить каталог</Button>
      </div> : catalog.isLoading || busy ? <p role="status" className="text-sm text-muted-foreground">Загружаем источники логов…</p>
        : !devices.length && <p className="text-sm text-muted-foreground">{query ? 'Источники не найдены по запросу.' : 'Устройств пока нет'}</p>}
      {catalog.data && !catalog.isError && <CatalogPagination page={page} perPage={PAGE_SIZE} total={catalog.data.total} busy={busy} label="источники логов" onPageChange={setPage} />}
    </div>
  );
}
