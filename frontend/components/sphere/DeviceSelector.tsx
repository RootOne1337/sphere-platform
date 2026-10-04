'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useDevices, type Device } from '@/lib/hooks/useDevices';
import { useGroups } from '@/lib/hooks/useGroups';
import { useLocations } from '@/lib/hooks/useLocations';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { DeviceStatusBadge } from '@/components/sphere/DeviceStatusBadge';
import { Search, Monitor, FolderOpen, MapPin } from 'lucide-react';

type SelectionMode = 'all' | 'group' | 'location' | 'manual';
const MAX_DEVICE_SELECTOR_SCOPE = 5000;
const EMPTY_DEVICES: Device[] = [];

interface DeviceSelectorProps {
  /** Массив выбранных device_ids */
  value: string[];
  /** Колбэк при изменении выбора */
  onChange: (deviceIds: string[]) => void;
  /** Режим выбора (опционально — по умолчанию manual) */
  mode?: SelectionMode;
  /** Колбэк при смене режима */
  onModeChange?: (mode: SelectionMode) => void;
}

export function DeviceSelector({ value, onChange, mode: externalMode, onModeChange }: DeviceSelectorProps) {
  const [internalMode, setInternalMode] = useState<SelectionMode>('manual');
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search.trim(), 300);
  const [groupFilter, setGroupFilter] = useState<string>('');
  const [locationFilter, setLocationFilter] = useState<string>('');
  const [scopeWarning, setScopeWarning] = useState<string | null>(null);
  const pendingAutoSelection = useRef<string | null>(null);

  const mode = externalMode ?? internalMode;
  const setMode = (m: SelectionMode) => {
    if (onModeChange) onModeChange(m);
    else setInternalMode(m);
  };

  const {
    data: devicesData,
    isLoading: devicesLoading,
    isFetching: devicesFetching,
    isError: devicesError,
    refetch: refetchDevices,
  } = useDevices({
    page: 1,
    page_size: MAX_DEVICE_SELECTOR_SCOPE,
    group_id: mode === 'group' && groupFilter ? groupFilter : undefined,
    location_id: mode === 'location' && locationFilter ? locationFilter : undefined,
    search: mode === 'manual' ? debouncedSearch || undefined : undefined,
  });
  const { data: groups } = useGroups();
  const { data: locations } = useLocations();

  const devices = devicesData?.items ?? EMPTY_DEVICES;
  const totalDevices = devicesData?.total ?? 0;
  const scopeIsPartial = Boolean(devicesData && devices.length < totalDevices);
  const searchIsPending = mode === 'manual' && search.trim() !== debouncedSearch;
  const selectionIsBusy = devicesLoading || devicesFetching || devicesError || searchIsPending;

  const selectionScopeKey = mode === 'all'
    ? 'all'
    : mode === 'group' && groupFilter
      ? `group:${groupFilter}`
      : mode === 'location' && locationFilter
        ? `location:${locationFilter}`
        : null;

  useEffect(() => {
    const hasPendingSelection = Boolean(selectionScopeKey && pendingAutoSelection.current === selectionScopeKey);
    if (hasPendingSelection) {
      if (devicesError) {
        pendingAutoSelection.current = null;
        setScopeWarning('Не удалось подтвердить полный список устройств; область не выбрана. Повторите загрузку.');
        onChange([]);
        return;
      }
      if (devicesLoading || devicesFetching || !devicesData) return;

      pendingAutoSelection.current = null;
      if (scopeIsPartial) {
        setScopeWarning(`Область не выбрана целиком: загружено ${devices.length} из ${totalDevices}. Переключитесь на ручной выбор для точечного поиска.`);
        onChange([]);
        return;
      }

      setScopeWarning(null);
      onChange(devices.map((device) => device.id));
      return;
    }

    if (mode !== 'all' || devicesLoading || devicesFetching || devicesError || !devicesData || value.length === 0) return;
    const currentIds = new Set(devices.map((device) => device.id));
    const selectionMatchesCatalog = !scopeIsPartial && value.length === devices.length && value.every((id) => currentIds.has(id));
    if (!selectionMatchesCatalog) {
      setScopeWarning('Состав каталога изменился после выбора. Повторно выберите все устройства, чтобы подтвердить актуальную область.');
      onChange([]);
    }
  }, [
    selectionScopeKey,
    mode,
    devicesError,
    devicesLoading,
    devicesFetching,
    devicesData,
    scopeIsPartial,
    devices,
    totalDevices,
    value,
    onChange,
  ]);

  // Фильтрация по текущему mode
  const filteredDevices = useMemo(() => {
    let list = devices;

    if (mode === 'group' && groupFilter) {
      list = list.filter(d => d.group_ids?.includes(groupFilter));
    }
    if (mode === 'location' && locationFilter) {
      list = list.filter(d => d.location_ids?.includes(locationFilter));
    }
    if (search && (mode !== 'manual' || searchIsPending)) {
      const q = search.toLowerCase();
      list = list.filter(d =>
        d.name.toLowerCase().includes(q) ||
        d.model?.toLowerCase().includes(q) ||
        d.android_id?.toLowerCase().includes(q) ||
        d.id.toLowerCase().includes(q)
      );
    }

    return list;
  }, [devices, mode, groupFilter, locationFilter, search, searchIsPending]);

  // При переключении mode "all" → выбираем все active
  const handleModeChange = (newMode: string) => {
    const m = newMode as SelectionMode;
    pendingAutoSelection.current = null;
    setMode(m);
    setScopeWarning(null);
    setSearch('');
    if (m === 'all') {
      pendingAutoSelection.current = 'all';
      return;
    }

    if (m === 'group' && groupFilter) pendingAutoSelection.current = `group:${groupFilter}`;
    if (m === 'location' && locationFilter) pendingAutoSelection.current = `location:${locationFilter}`;
    onChange([]);
  };

  const toggleDevice = (id: string) => {
    if (value.includes(id)) {
      onChange(value.filter(v => v !== id));
    } else {
      onChange([...value, id]);
    }
    setScopeWarning(null);
  };

  const selectAllFiltered = () => {
    if (selectionIsBusy) return;
    if (scopeIsPartial) {
      setScopeWarning(`Массовый выбор заблокирован: загружено ${devices.length} из ${totalDevices}. Переключитесь на ручной выбор для точечного поиска.`);
      return;
    }
    const ids = filteredDevices.map(d => d.id);
    const merged = [...new Set([...value, ...ids])];
    onChange(merged);
  };

  const deselectAllFiltered = () => {
    const ids = new Set(filteredDevices.map(d => d.id));
    onChange(value.filter(v => !ids.has(v)));
  };

  return (
    <div className="space-y-3">
      {/* Режим выбора */}
      <div className="space-y-1">
        <Label className="text-xs font-mono uppercase text-muted-foreground">Режим выбора</Label>
        <Select value={mode} onValueChange={handleModeChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Все устройства</SelectItem>
            <SelectItem value="group">По группе</SelectItem>
            <SelectItem value="location">По локации</SelectItem>
            <SelectItem value="manual">Ручной выбор</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Фильтр по группе */}
      {mode === 'group' && (
        <div className="space-y-1">
          <Label className="text-xs font-mono uppercase text-muted-foreground">Группа</Label>
          <Select value={groupFilter} onValueChange={(v) => {
            setGroupFilter(v);
            setSearch('');
            pendingAutoSelection.current = `group:${v}`;
            setScopeWarning(null);
            onChange([]);
          }}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Выбери группу" />
            </SelectTrigger>
            <SelectContent>
              {groups?.map(g => (
                <SelectItem key={g.id} value={g.id}>
                  <span className="flex items-center gap-2">
                    {g.color && <span className="w-2 h-2 rounded-full" style={{ backgroundColor: g.color }} />}
                    <FolderOpen className="w-3 h-3" />
                    {g.name} ({g.total_devices})
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Фильтр по локации */}
      {mode === 'location' && (
        <div className="space-y-1">
          <Label className="text-xs font-mono uppercase text-muted-foreground">Локация</Label>
          <Select value={locationFilter} onValueChange={(v) => {
            setLocationFilter(v);
            setSearch('');
            pendingAutoSelection.current = `location:${v}`;
            setScopeWarning(null);
            onChange([]);
          }}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Выбери локацию" />
            </SelectTrigger>
            <SelectContent>
              {locations?.map(l => (
                <SelectItem key={l.id} value={l.id}>
                  <span className="flex items-center gap-2">
                    {l.color && <span className="w-2 h-2 rounded-full" style={{ backgroundColor: l.color }} />}
                    <MapPin className="w-3 h-3" />
                    {l.name} ({l.total_devices})
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Ручной / отфильтрованный список */}
      {mode !== 'all' && (
        <>
          <div className="relative">
            <Search className="absolute left-2 top-2 w-3.5 h-3.5 text-muted-foreground" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={mode === 'manual' ? 'Имя, serial, модель или UUID…' : 'Фильтр видимых устройств…'}
              className="h-8 pl-7 text-xs"
              disabled={devicesError}
            />
          </div>

          <div className="flex justify-between items-center text-[10px] text-muted-foreground font-mono">
            <span>{value.length} выбрано · показано {devices.length} из {totalDevices}</span>
            <div className="flex gap-2">
              <button type="button" onClick={selectAllFiltered} disabled={selectionIsBusy || scopeIsPartial} className="hover:text-primary transition-colors disabled:cursor-not-allowed disabled:opacity-50">
                Выбрать все
              </button>
              <button type="button" onClick={deselectAllFiltered} disabled={selectionIsBusy} className="hover:text-primary transition-colors disabled:cursor-not-allowed disabled:opacity-50">
                Снять все
              </button>
            </div>
          </div>

          <div className="max-h-[200px] overflow-y-auto border border-border rounded-sm divide-y divide-border">
            {filteredDevices.map(d => (
              <label
                key={d.id}
                className="flex items-center gap-2 px-2 py-1.5 hover:bg-accent/50 cursor-pointer text-xs"
              >
                <Checkbox
                  checked={value.includes(d.id)}
                  onCheckedChange={() => toggleDevice(d.id)}
                  disabled={selectionIsBusy}
                  className="h-3.5 w-3.5"
                />
                <Monitor className="w-3 h-3 text-muted-foreground shrink-0" />
                <span className="font-mono truncate flex-1">{d.name}</span>
                <DeviceStatusBadge status={d.status} />
              </label>
            ))}
            {filteredDevices.length === 0 && (
              <div className="p-4 text-center text-muted-foreground text-xs">
                Устройства не найдены
              </div>
            )}
          </div>
        </>
      )}

      {mode === 'all' && (
        <div className="text-xs text-muted-foreground font-mono p-2 bg-accent/30 rounded-sm">
          <Monitor className="w-3 h-3 inline mr-1" />
          {scopeIsPartial
            ? `Нельзя выбрать весь каталог: загружено ${devices.length} из ${totalDevices}. Переключитесь на ручной выбор.`
            : devicesLoading || devicesFetching
              ? 'Проверяем полный состав каталога…'
              : devicesError
                ? 'Не удалось проверить полный состав каталога'
              : totalDevices === 0
                ? 'В каталоге нет активных устройств'
              : value.length === totalDevices && totalDevices > 0
                ? `Выбраны все устройства (${totalDevices})`
                : 'Подтвердите выбор всех устройств'}
        </div>
      )}

      {devicesError && (
        <div className="flex items-center justify-between gap-3 rounded-sm border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive" role="alert">
          <span>Не удалось загрузить полный каталог устройств.</span>
          <button type="button" className="underline underline-offset-2" onClick={() => void refetchDevices()}>Повторить</button>
        </div>
      )}

      {scopeWarning && <p role="status" aria-live="polite" className="rounded-sm border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-800 dark:text-amber-200">{scopeWarning}</p>}

      {scopeIsPartial && mode !== 'all' && (
        <p role="status" aria-live="polite" className="text-xs text-amber-800 dark:text-amber-200">
          Показана только первая часть области ({devices.length} из {totalDevices}). Можно выбирать отдельные видимые устройства; «Выбрать все» отключено.
        </p>
      )}
    </div>
  );
}
