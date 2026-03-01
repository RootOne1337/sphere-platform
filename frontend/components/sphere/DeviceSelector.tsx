'use client';

import { useState, useMemo } from 'react';
import { useDevices, Device } from '@/lib/hooks/useDevices';
import { useGroups } from '@/lib/hooks/useGroups';
import { useLocations } from '@/lib/hooks/useLocations';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
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
  const [groupFilter, setGroupFilter] = useState<string>('');
  const [locationFilter, setLocationFilter] = useState<string>('');

  const mode = externalMode ?? internalMode;
  const setMode = (m: SelectionMode) => {
    if (onModeChange) onModeChange(m);
    else setInternalMode(m);
  };

  const { data: devicesData } = useDevices({ page: 1, page_size: 200 });
  const { data: groups } = useGroups();
  const { data: locations } = useLocations();

  const devices = devicesData?.items ?? [];

  // Фильтрация по текущему mode
  const filteredDevices = useMemo(() => {
    let list = devices;

    if (mode === 'group' && groupFilter) {
      list = list.filter(d => d.group_ids?.includes(groupFilter));
    }
    if (mode === 'location' && locationFilter) {
      list = list.filter(d => d.location_ids?.includes(locationFilter));
    }
    if (search) {
      const q = search.toLowerCase();
      list = list.filter(d =>
        d.name.toLowerCase().includes(q) ||
        d.model?.toLowerCase().includes(q) ||
        d.android_version?.toLowerCase().includes(q)
      );
    }

    return list;
  }, [devices, mode, groupFilter, locationFilter, search]);

  // При переключении mode "all" → выбираем все active
  const handleModeChange = (newMode: string) => {
    const m = newMode as SelectionMode;
    setMode(m);
    if (m === 'all') {
      onChange(devices.map(d => d.id));
    } else {
      onChange([]);
    }
  };

  const toggleDevice = (id: string) => {
    if (value.includes(id)) {
      onChange(value.filter(v => v !== id));
    } else {
      onChange([...value, id]);
    }
  };

  const selectAllFiltered = () => {
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
            // Автовыбор устройств группы
            const groupDevices = devices.filter(d => d.group_ids?.includes(v));
            onChange(groupDevices.map(d => d.id));
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
            const locDevices = devices.filter(d => d.location_ids?.includes(v));
            onChange(locDevices.map(d => d.id));
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
              placeholder="Поиск устройств…"
              className="h-8 pl-7 text-xs"
            />
          </div>

          <div className="flex justify-between items-center text-[10px] text-muted-foreground font-mono">
            <span>{value.length} / {filteredDevices.length} выбрано</span>
            <div className="flex gap-2">
              <button onClick={selectAllFiltered} className="hover:text-primary transition-colors">
                Выбрать все
              </button>
              <button onClick={deselectAllFiltered} className="hover:text-primary transition-colors">
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
          Все {devices.length} устройств будут включены
        </div>
      )}
    </div>
  );
}
