'use client';

import { useMemo, useState } from 'react';
import { Monitor, RefreshCw, Search } from 'lucide-react';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { DeviceStatusBadge } from '@/components/sphere/DeviceStatusBadge';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { useDevices, type Device } from '@/lib/hooks/useDevices';

const DEVICE_LOOKUP_PAGE_SIZE = 100;
const EMPTY_DEVICES: Device[] = [];

interface DeviceSearchSelectProps {
  value: string;
  onChange: (deviceId: string) => void;
  disabled?: boolean;
  excludedIds?: ReadonlySet<string>;
  placeholder?: string;
}

/** Server-searched single-device picker. Partial lookup results are explicit. */
export function DeviceSearchSelect({
  value,
  onChange,
  disabled = false,
  excludedIds,
  placeholder = 'Выберите устройство…',
}: DeviceSearchSelectProps) {
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search.trim(), 300);
  const {
    data,
    isLoading,
    isFetching,
    isError,
    refetch,
  } = useDevices({
    page: 1,
    page_size: DEVICE_LOOKUP_PAGE_SIZE,
    search: debouncedSearch || undefined,
  });

  const devices = data?.items ?? EMPTY_DEVICES;
  const totalDevices = data?.total ?? 0;
  const availableDevices = useMemo(
    () => devices.filter((device) => !excludedIds?.has(device.id)),
    [devices, excludedIds],
  );
  const isSearchPending = search.trim() !== debouncedSearch;
  const isBusy = disabled || isLoading || isFetching || isError || isSearchPending;
  const selectedValue = value && !excludedIds?.has(value) ? value : '';

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="absolute left-2 top-2 w-3.5 h-3.5 text-muted-foreground" aria-hidden="true" />
        <Input
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            if (value) onChange('');
          }}
          placeholder="Поиск по имени, serial, модели или UUID…"
          className="h-8 pl-7 text-xs"
          disabled={disabled || isError}
          aria-label="Поиск устройства"
        />
      </div>

      <Select
        value={selectedValue}
        onValueChange={onChange}
        disabled={isBusy || availableDevices.length === 0}
      >
        <SelectTrigger className="text-xs font-mono" aria-label="Устройство">
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {availableDevices.map((device) => (
            <SelectItem key={device.id} value={device.id}>
              <span className="flex items-center gap-2">
                <Monitor className="w-3 h-3 shrink-0" aria-hidden="true" />
                <span className="truncate">{device.name}</span>
                <DeviceStatusBadge status={device.status} />
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <p className="text-[10px] text-muted-foreground" aria-live="polite">
        {isLoading || isFetching || isSearchPending
          ? 'Ищем устройства…'
          : `${devices.length} показано из ${totalDevices} совпадений`}
      </p>

      {devices.length > 0 && availableDevices.length === 0 && (
        <p className="text-xs text-muted-foreground" role="status">
          {devices.length < totalDevices
            ? 'Все показанные устройства уже назначены. Уточните поиск, чтобы найти другие.'
            : 'Все совпавшие устройства уже назначены.'}
        </p>
      )}

      {devices.length < totalDevices && !isError && (
        <p className="text-xs text-amber-700 dark:text-amber-300" role="status">
          Показаны первые {devices.length} из {totalDevices}. Уточните поиск, чтобы найти остальные.
        </p>
      )}

      {devices.length === 0 && !isLoading && !isFetching && !isError && !isSearchPending && (
        <p className="text-xs text-muted-foreground" role="status">
          {debouncedSearch ? 'Устройства не найдены.' : 'Нет активных устройств.'}
        </p>
      )}

      {isError && (
        <div className="flex items-center justify-between gap-3 rounded-sm border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive" role="alert">
          <span>Не удалось загрузить устройства.</span>
          <button type="button" className="inline-flex items-center gap-1 underline underline-offset-2" onClick={() => void refetch()}>
            <RefreshCw className="h-3 w-3" aria-hidden="true" /> Повторить
          </button>
        </div>
      )}
    </div>
  );
}
