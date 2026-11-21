'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { OnChangeFn, SortingState, VisibilityState } from '@tanstack/react-table';

export const FLEET_TABLE_KEY = 'sphere.fleet.table.v1';
const OPTIONAL_COLUMNS = ['agent_version', 'status', 'battery_level', 'network', 'server_name', 'tags', 'last_seen', 'android_id', 'cpu_usage', 'ram_usage_mb'];
export const FLEET_COLUMN_IDS = ['name', ...OPTIONAL_COLUMNS];
export const FLEET_MIN_COLUMN_WIDTH: Record<string, number> = { name: 180, agent_version: 160, status: 160, battery_level: 90, network: 140, server_name: 140, tags: 130, last_seen: 190, android_id: 170, cpu_usage: 120, ram_usage_mb: 130 };
const SORTABLE_COLUMNS = ['name', ...OPTIONAL_COLUMNS];
export interface FleetTablePreferences {
  version: 1;
  columnVisibility: VisibilityState;
  sorting: SortingState;
  columnOrder: string[];
  columnSizing: Record<string, number>;
  columnPinning: Record<string, 'left' | 'right' | null>;
}
export function defaultFleetTablePreferences(): FleetTablePreferences {
  return { version: 1, columnVisibility: { network: false, server_name: false, tags: false, android_id: false, cpu_usage: false, ram_usage_mb: false }, sorting: [],
    columnOrder: [...FLEET_COLUMN_IDS], columnSizing: {}, columnPinning: { name: 'left' } };
}

export function parseFleetTablePreferences(raw: string | null): FleetTablePreferences {
  const defaults = defaultFleetTablePreferences();
  if (!raw || raw.length > 8192) return defaults;
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== 'object' || !('version' in value) || value.version !== 1) return defaults;
    const data = value as Record<string, unknown>;
    if (data.columnVisibility && typeof data.columnVisibility === 'object' && !Array.isArray(data.columnVisibility)) {
      for (const id of OPTIONAL_COLUMNS) {
        const visible = (data.columnVisibility as Record<string, unknown>)[id];
        if (typeof visible === 'boolean') defaults.columnVisibility[id] = visible;
      }
    }
    if (Array.isArray(data.sorting)) {
      const seen = new Set<string>();
      defaults.sorting = data.sorting.filter((item) => {
        if (!item || typeof item !== 'object' || !SORTABLE_COLUMNS.includes(item.id) || typeof item.desc !== 'boolean' || seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
      }).slice(0, 3).map(({ id, desc }) => ({ id, desc }));
    }
    if (Array.isArray(data.columnOrder)) {
      const order = data.columnOrder.filter((id): id is string => typeof id === 'string' && FLEET_COLUMN_IDS.includes(id));
      defaults.columnOrder = [...new Set(order), ...FLEET_COLUMN_IDS.filter(id => !order.includes(id))];
    }
    if (data.columnSizing && typeof data.columnSizing === 'object') {
      for (const id of FLEET_COLUMN_IDS) {
        const width = (data.columnSizing as Record<string, unknown>)[id];
        if (typeof width === 'number' && Number.isFinite(width) && width >= FLEET_MIN_COLUMN_WIDTH[id] && width <= 720) defaults.columnSizing[id] = Math.round(width);
      }
    }
    if (data.columnPinning && typeof data.columnPinning === 'object') {
      for (const id of FLEET_COLUMN_IDS) {
        const pinned = (data.columnPinning as Record<string, unknown>)[id];
        if (pinned === 'left' || pinned === 'right' || pinned === null) defaults.columnPinning[id] = pinned;
      }
    }
    return defaults;
  } catch { return defaults; }
}

/** Browser presentation preferences only: never credentials, rows or selections. */
export function useFleetTablePreferences() {
  const [preferences, setPreferences] = useState(defaultFleetTablePreferences);
  const current = useRef(preferences);
  const [storageUnavailable, setStorageUnavailable] = useState(false);
  useEffect(() => {
    const apply = (raw: string | null) => {
      current.current = parseFleetTablePreferences(raw);
      setPreferences(current.current);
    };
    try { apply(window.localStorage.getItem(FLEET_TABLE_KEY)); }
    catch { setStorageUnavailable(true); }
    const onStorage = (event: StorageEvent) => {
      if (event.storageArea === window.localStorage && (event.key === FLEET_TABLE_KEY || event.key === null)) apply(event.newValue);
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  const update = useCallback((next: FleetTablePreferences) => {
    // Sanitize writes too: only declared, non-sensitive presentation keys survive.
    current.current = parseFleetTablePreferences(JSON.stringify(next));
    setPreferences(current.current);
    try {
      window.localStorage.setItem(FLEET_TABLE_KEY, JSON.stringify(current.current));
      setStorageUnavailable(false);
    } catch { setStorageUnavailable(true); }
  }, []);
  const setColumnVisibility = useCallback<OnChangeFn<VisibilityState>>((value) => {
    update({ ...current.current, columnVisibility: typeof value === 'function' ? value(current.current.columnVisibility) : value });
  }, [update]);
  const setSorting = useCallback<OnChangeFn<SortingState>>((value) => {
    update({ ...current.current, sorting: typeof value === 'function' ? value(current.current.sorting) : value });
  }, [update]);
  const reset = useCallback(() => update(defaultFleetTablePreferences()), [update]);
  const setColumnLayout = useCallback((layout: Pick<FleetTablePreferences, 'columnOrder' | 'columnSizing' | 'columnPinning'>) => {
    update({ ...current.current, ...layout });
  }, [update]);
  return { ...preferences, setColumnVisibility, setSorting, setColumnLayout, reset, storageUnavailable };
}
