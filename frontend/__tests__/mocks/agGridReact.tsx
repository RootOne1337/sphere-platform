/** Metadata/authority adapter harness only. Native grid geometry, resizing,
 * reordering and persistence are accepted separately in real Chromium. */
import React, { useEffect, useRef, useState } from 'react';
import type { AgGridReactProps } from 'ag-grid-react';
import type { ColDef, ColumnState, GridApi, GridReadyEvent, ICellRendererParams, SortChangedEvent } from 'ag-grid-community';
import type { Device } from '@/lib/hooks/useDevices';

export function AgGridReact(props: AgGridReactProps<Device>) {
  const columns = props.columnDefs as ColDef<Device>[];
  const current = useRef(props); current.current = props;
  const [, refresh] = useState(0);
  const state = useRef<ColumnState[]>(columns.map(column => ({ colId: column.colId!, width: column.initialWidth, flex: column.initialFlex, pinned: column.pinned })));
  const selected = useRef(new Set<string>());
  const api = useRef<Partial<GridApi<Device>>>({
    isDestroyed: () => false, setGridAriaProperty: () => {},
    getColumnState: () => state.current,
    applyColumnState: params => { state.current = params.state?.map(value => ({ ...state.current.find(old => old.colId === value.colId), ...value })) ?? state.current; refresh(value => value + 1); return true; },
    refreshCells: () => refresh(value => value + 1), refreshHeader: () => refresh(value => value + 1), resetRowHeights: () => {},
    forEachNode: callback => { current.current.rowData?.forEach((data, index) => callback({ id: data.id, data, isSelected: () => selected.current.has(data.id), setSelected: (value: boolean) => { if (value) selected.current.add(data.id); else selected.current.delete(data.id); } } as never, index)); },
    getSelectedRows: () => current.current.rowData?.filter(value => selected.current.has(value.id)) ?? [],
    resetColumnState: () => {}, sizeColumnsToFit: () => {},
  });
  useEffect(() => { props.onGridReady?.({ api: api.current } as GridReadyEvent<Device>); }, []);
  const visible = state.current.filter(column => !column.hide).map(column => columns.find(value => value.colId === column.colId)!);
  const sorted = [...(props.rowData ?? [])];
  const sort = state.current.find(column => column.sort);
  if (sort) {
    const column = columns.find(column => column.colId === sort.colId)!;
    const get = (data: Device) => typeof column.valueGetter === 'function' ? column.valueGetter({ data } as never) : undefined;
    sorted.sort((a, b) => String(get(a) ?? '').localeCompare(String(get(b) ?? '')) * (sort.sort === 'desc' ? -1 : 1));
  }
  return <div role="grid" aria-label="Устройства организации">
    <div role="row">{visible.map(column => {
      const columnState = state.current.find(value => value.colId === column.colId);
      const Header = column.headerComponent as React.ComponentType;
      return <div role="columnheader" key={column.colId} aria-sort={columnState?.sort === 'asc' ? 'ascending' : columnState?.sort === 'desc' ? 'descending' : undefined}>
        {Header ? <Header /> : column.sortable ? <button aria-label={`Сортировать по ${column.headerName}`} onClick={() => { state.current = state.current.map(value => value.colId === column.colId ? { ...value, sort: value.sort === 'asc' ? 'desc' : 'asc' } : { ...value, sort: null }); current.current.onSortChanged?.({ api: api.current, source: 'uiColumnSorted' } as SortChangedEvent<Device>); refresh(value => value + 1); }}>{column.headerName}</button> : column.headerName}
      </div>;
    })}</div>
    <div role="rowgroup">{sorted.map(data => <div key={data.id} role="row">{visible.map(column => { const Cell = column.cellRenderer as React.ComponentType<ICellRendererParams<Device>>; return <div role="gridcell" key={column.colId}><Cell {...({ data, node: { id: data.id } } as ICellRendererParams<Device>)} /></div>; })}</div>)}</div>
  </div>;
}
