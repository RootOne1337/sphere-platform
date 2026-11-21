"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AgGridReact } from 'ag-grid-react';
import { AllCommunityModule, themeQuartz, type ColDef, type ColumnState, type GridApi, type GridReadyEvent, type ICellRendererParams } from 'ag-grid-community';
import type { Table } from '@tanstack/react-table';
import type { Device } from '@/lib/hooks/useDevices';
import { ArrowLeft, ArrowRight, Columns3, Expand, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { FLEET_COLUMN_IDS, FLEET_MIN_COLUMN_WIDTH, type useFleetTablePreferences } from './fleetTablePreferences';

const modules = [AllCommunityModule];
const defaultColumn = { resizable: true, sortable: true, sortingOrder: ['asc', 'desc', null] as ('asc' | 'desc' | null)[] };
const selectionOptions = { mode: 'multiRow' as const, checkboxes: false, headerCheckbox: false, enableClickSelection: false as const };
const fleetTheme = themeQuartz.withParams({
    fontFamily: 'Inter, system-ui, sans-serif', fontSize: '0.8125rem', headerFontSize: '0.75rem', headerFontWeight: 600,
    backgroundColor: 'hsl(var(--card))', foregroundColor: 'hsl(var(--foreground))',
    accentColor: 'hsl(var(--primary))', borderColor: 'hsl(var(--border))',
    headerBackgroundColor: 'hsl(var(--muted))', headerTextColor: 'hsl(var(--muted-foreground))',
    rowHoverColor: 'hsl(var(--primary) / .04)', selectedRowBackgroundColor: 'hsl(var(--primary) / .08)',
    rowBorder: { color: 'hsl(var(--border) / .6)', width: 1, style: 'solid' },
    wrapperBorderRadius: 12, wrapperBorder: false, cellHorizontalPadding: 14,
    headerColumnResizeHandleColor: 'hsl(var(--muted-foreground) / .5)',
});

type Preferences = ReturnType<typeof useFleetTablePreferences>;
const columnFlex = (id: string) => id === 'battery_level' ? .4 : id === 'last_seen' ? 1.4 : 1;
const GridHeaderContext = createContext<{ table: Table<Device> } | null>(null);
function renderTemplate(template: unknown, context: unknown): ReactNode {
    return typeof template === 'function' ? template(context) : typeof template === 'string' ? template : null;
}
function SelectionHeader() {
    const context = useContext(GridHeaderContext);
    const header = context?.table.getFlatHeaders().find(value => value.id === 'select');
    return header ? renderTemplate(header.column.columnDef.header, header.getContext()) : null;
}
interface FleetDataGridProps {
    table: Table<Device>;
    preferences: Preferences;
    rowHeight: number;
    clockNow: number;
}

/** Ready-made Community grid owns sizing, drag/drop, keyboard navigation and virtualisation.
 * TanStack retains the existing controlled selection and shared card presentation.
 * Only allowlisted presentation preferences are stored; grid state/rows are never serialized.
 */
export function FleetDataGrid({ table, preferences, rowHeight, clockNow }: FleetDataGridProps) {
    const api = useRef<GridApi<Device> | null>(null);
    const root = useRef<HTMLDivElement>(null);
    const current = useRef({ table, preferences }); current.current = { table, preferences };
    const restoring = useRef(false);
    const lastApplied = useRef('');
    const [columnsOpen, setColumnsOpen] = useState(false);
    const ordered = preferences.columnOrder.map(id => table.getColumn(id)!).filter(Boolean);

    // These existing cell templates are pure functions (no hooks). Calling a
    // template preserves nested component identity when only heartbeat age changes.
    const columnDefs = useMemo<ColDef<Device>[]>(() => {
        const base = current.current.table;
        return base.getAllLeafColumns().map(column => {
            const id = column.id; const special = id === 'select' || id === 'actions';
            return {
                colId: id, headerName: typeof column.columnDef.header === 'string' ? column.columnDef.header : '',
                initialWidth: special ? 52 : column.getSize(), minWidth: special ? 52 : FLEET_MIN_COLUMN_WIDTH[id], maxWidth: special ? 52 : 720,
                initialFlex: special || id === 'name' ? undefined : columnFlex(id),
                pinned: id === 'select' || id === 'name' ? 'left' : id === 'actions' ? 'right' : undefined,
                lockPinned: special, lockPosition: special ? id === 'select' ? 'left' : 'right' : undefined,
                suppressMovable: special, resizable: !special, sortable: column.getCanSort(),
                suppressHeaderMenuButton: true, cellDataType: false,
                valueGetter: params => params.data ? current.current.table.getCoreRowModel().rowsById[params.data.id]?.getValue(id) : undefined,
                cellRenderer: (params: ICellRendererParams<Device>) => {
                    if (!params.data) return null;
                    const row = current.current.table.getCoreRowModel().rowsById[params.data.id];
                    const cell = row?.getAllCells().find(value => value.column.id === id);
                    return cell ? <div className="h-full w-full">{renderTemplate(cell.column.columnDef.cell, cell.getContext())}</div> : null;
                },
                ...(id === 'select' ? { headerComponent: SelectionHeader, cellClass: 'sphere-fleet-select', headerClass: 'sphere-fleet-select' } : {}),
                suppressKeyboardEvent: params => {
                    const target = params.event.target;
                    return target instanceof HTMLElement && Boolean(target.closest('button,a,input,[role="checkbox"]'));
                },
            };
        });
    }, []);

    const restore = useCallback(() => {
        const grid = api.current; if (!grid || grid.isDestroyed()) return;
        const { columnOrder, columnVisibility, columnSizing, columnPinning, sorting } = current.current.preferences;
        const signature = JSON.stringify({ columnOrder, columnVisibility, columnSizing, columnPinning, sorting });
        if (signature === lastApplied.current) return;
        restoring.current = true;
        const state: ColumnState[] = ['select', ...columnOrder, 'actions'].map(id => {
            const special = id === 'select' || id === 'actions';
            const sortIndex = sorting.findIndex(value => value.id === id);
            const fixedWidth = columnSizing[id];
            const pinned = id === 'select' ? 'left' : id === 'actions' ? 'right' : columnPinning[id] ?? null;
            return { colId: id, hide: special || id === 'name' ? false : columnVisibility[id] === false,
                pinned, sort: sortIndex < 0 ? null : sorting[sortIndex].desc ? 'desc' : 'asc', sortIndex: sortIndex < 0 ? null : sortIndex,
                width: special ? 52 : fixedWidth ?? (pinned ? current.current.table.getColumn(id)?.getSize() : undefined),
                flex: special || fixedWidth || pinned ? null : columnFlex(id) };
        });
        grid.applyColumnState({ state, applyOrder: true });
        lastApplied.current = signature;
        restoring.current = false;
    }, []);

    const saveLayout = useCallback((grid: GridApi<Device>) => {
        if (restoring.current || grid.isDestroyed()) return;
        const state = grid.getColumnState().filter(value => FLEET_COLUMN_IDS.includes(value.colId));
        const layout = { columnOrder: state.map(value => value.colId), columnSizing: {} as Record<string, number>, columnPinning: {} as Record<string, 'left' | 'right' | null> };
        for (const value of state) {
            if (!value.flex && typeof value.width === 'number') layout.columnSizing[value.colId] = Math.round(value.width);
            layout.columnPinning[value.colId] = value.pinned === 'left' || value.pinned === 'right' ? value.pinned : null;
        }
        const previous = current.current.preferences;
        if (JSON.stringify(layout) !== JSON.stringify({ columnOrder: previous.columnOrder, columnSizing: previous.columnSizing, columnPinning: previous.columnPinning })) previous.setColumnLayout(layout);
    }, []);

    const onReady = useCallback((event: GridReadyEvent<Device>) => {
        api.current = event.api;
        event.api.setGridAriaProperty('label', 'Устройства организации');
        // Integrate the grid's real scroll areas with the existing browser Back
        // restoration; this stores geometry only in this tab's route history.
        root.current?.querySelector<HTMLElement>('.ag-grid-viewport')?.setAttribute('data-route-scroll', 'fleet-grid');
        lastApplied.current = ''; restore();
    }, [restore]);
    useEffect(restore, [restore, preferences.columnOrder, preferences.columnVisibility, preferences.columnSizing, preferences.columnPinning, preferences.sorting]);
    useEffect(() => {
        const grid = api.current; if (!grid || grid.isDestroyed()) return;
        grid.refreshCells({ force: true });
        const selection = table.getState().rowSelection;
        grid.forEachNode(node => { if (node.id && node.isSelected() !== Boolean(selection[node.id])) node.setSelected(Boolean(selection[node.id]), false, 'api'); });
    }, [table, table.options.columns, table.options.data, table.getState().rowSelection, clockNow, columnsOpen]);
    useEffect(() => { const grid = api.current; if (grid && !grid.isDestroyed()) grid.resetRowHeights(); }, [rowHeight]);

    const updateOrder = (id: string, offset: number) => {
        const order = [...preferences.columnOrder]; const from = order.indexOf(id); const to = from + offset;
        if (from < 0 || to < 0 || to >= order.length) return;
        [order[from], order[to]] = [order[to], order[from]];
        preferences.setColumnLayout({ columnOrder: order, columnSizing: preferences.columnSizing, columnPinning: preferences.columnPinning });
    };

    // A fresh context value updates the checkbox without rebuilding every grid
    // header (which would steal keyboard focus during selection or heartbeat).
    const headerContext = useMemo(() => ({ table }), [table, table.options.data, table.getState().rowSelection]);
    return <GridHeaderContext.Provider value={headerContext}><section className="flex h-[max(32rem,70dvh)] min-w-0 shrink-0 flex-col overflow-hidden rounded-xl border border-border bg-card sm:h-[max(36rem,calc(100dvh-20rem))]" aria-label="Таблица устройств">
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
            <p className="text-xs text-muted-foreground"><span className="font-medium text-foreground">{table.options.data.length}</span> устройств на странице</p>
            <div className="flex flex-wrap gap-1">
                <Button type="button" variant="ghost" size="sm" aria-label="Подогнать столбцы по ширине" onClick={() => { const grid = api.current; if (grid && !grid.isDestroyed()) { grid.sizeColumnsToFit(); saveLayout(grid); } }}><Expand className="h-3.5 w-3.5" aria-hidden />По ширине</Button>
                <Button type="button" variant="outline" size="sm" aria-label="Настроить видимые колонки" onClick={() => setColumnsOpen(true)}><Columns3 className="h-3.5 w-3.5" aria-hidden />Столбцы</Button>
            </div>
        </div>
        <div ref={root} className="sphere-fleet-grid min-h-0 min-w-0 flex-1" style={{ minHeight: 240 }}>
            <AgGridReact<Device> containerStyle={{ height: '100%', minHeight: 240, display: 'flex', flexDirection: 'column' }} modules={modules} theme={fleetTheme} loadThemeGoogleFonts={false} rowData={table.options.data} columnDefs={columnDefs}
                defaultColDef={defaultColumn}
                getRowId={params => params.data.id} rowHeight={rowHeight} headerHeight={44} rowBuffer={12}
                onGridReady={onReady} onGridPreDestroyed={() => { api.current = null; }}
                onColumnMoved={event => { if (event.finished && event.source !== 'api') saveLayout(event.api); }}
                onColumnResized={event => { if (event.finished && event.source !== 'api' && event.source !== 'flex') saveLayout(event.api); }}
                onColumnPinned={event => { if (event.source !== 'api') saveLayout(event.api); }}
                onSortChanged={event => { if (restoring.current || event.source === 'api') return;
                    const sorting = event.api.getColumnState().filter(value => value.sort).sort((a, b) => (a.sortIndex ?? 0) - (b.sortIndex ?? 0)).map(value => ({ id: value.colId, desc: value.sort === 'desc' }));
                    current.current.preferences.setSorting(sorting);
                }}
                rowSelection={selectionOptions}
                onSelectionChanged={event => { if (event.source === 'api') return;
                    const selected = Object.fromEntries(event.api.getSelectedRows().map(device => [device.id, true]));
                    current.current.table.setRowSelection(selected);
                }}
                suppressDragLeaveHidesColumns suppressScrollOnNewData suppressCellFocus={false} animateRows={false}
                enableCellTextSelection ensureDomOrder tooltipShowDelay={400}
                localeText={{ ariaLabelColumnMenu: 'Меню столбца', ariaRowSelect: 'Выбрать устройство', ariaRowDeselect: 'Снять выделение устройства', ariaLabelSelectAll: 'Выбрать все устройства', ariaLabelDeselectAll: 'Снять выделение', ariaLabelColumnFilter: 'Фильтр столбца', noRowsToShow: 'Устройства не найдены', loadingOoo: 'Загрузка устройств…' }}
            />
        </div>
        <Dialog open={columnsOpen} onOpenChange={setColumnsOpen}>
            <DialogContent placement="right" className="z-[110] gap-0 overflow-hidden bg-card">
                <header className="shrink-0 border-b px-5 py-5 pr-12"><DialogTitle className="text-base">Столбцы таблицы</DialogTitle><DialogDescription className="mt-2 text-xs leading-5">Перетаскивайте заголовки, чтобы менять порядок. Потяните границу заголовка, чтобы изменить ширину. Настройки сохраняются в этом браузере.</DialogDescription></header>
                <div className="min-h-0 flex-1 space-y-2 overflow-auto p-4">
                    {ordered.map((column, index) => <div key={column.id} className="rounded-xl border border-border bg-background p-3">
                        <div className="flex items-center justify-between gap-2">
                            <label htmlFor={`fleet-column-${column.id}`} className="flex min-h-10 min-w-0 flex-1 cursor-pointer items-center gap-2 text-sm font-medium">
                                <Checkbox id={`fleet-column-${column.id}`} aria-label={typeof column.columnDef.header === 'string' ? column.columnDef.header : column.id} checked={column.getIsVisible()} disabled={!column.getCanHide()} onCheckedChange={value => column.toggleVisibility(Boolean(value))} />
                                <span className="truncate">{String(column.columnDef.header)}</span>
                            </label>
                            <Button variant="ghost" size="icon" className="h-8 w-8" aria-label={`Переместить ${column.columnDef.header} влево`} disabled={index === 0} onClick={() => updateOrder(column.id, -1)}><ArrowLeft className="h-3.5 w-3.5" aria-hidden /></Button>
                            <Button variant="ghost" size="icon" className="h-8 w-8" aria-label={`Переместить ${column.columnDef.header} вправо`} disabled={index === ordered.length - 1} onClick={() => updateOrder(column.id, 1)}><ArrowRight className="h-3.5 w-3.5" aria-hidden /></Button>
                        </div>
                        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                            <label className="flex items-center gap-2 text-xs text-muted-foreground">Закрепление<select data-ui="select" aria-label={`Закрепление ${column.columnDef.header}`} value={preferences.columnPinning[column.id] ?? ''} onChange={event => preferences.setColumnLayout({ columnOrder: preferences.columnOrder, columnSizing: preferences.columnSizing, columnPinning: { ...preferences.columnPinning, [column.id]: event.target.value === 'left' ? 'left' : event.target.value === 'right' ? 'right' : null } })} className="h-8 rounded-md border bg-card px-2 text-xs text-foreground"><option value="">Нет</option><option value="left">Слева</option><option value="right">Справа</option></select></label>
                            <ColumnWidthInput id={column.id} label={String(column.columnDef.header)} value={preferences.columnSizing[column.id]} onCommit={value => {
                                const sizes = { ...preferences.columnSizing };
                                if (value === undefined) delete sizes[column.id]; else sizes[column.id] = value;
                                preferences.setColumnLayout({ columnOrder: preferences.columnOrder, columnPinning: preferences.columnPinning, columnSizing: sizes });
                            }} />
                        </div>
                    </div>)}
                    {preferences.storageUnavailable && <p role="status" className="text-xs text-warning">Хранилище браузера недоступно. Настройки действуют до перезагрузки.</p>}
                </div>
                <footer className="shrink-0 border-t p-4 [padding-bottom:max(1rem,env(safe-area-inset-bottom))]"><Button variant="outline" size="sm" onClick={() => { api.current?.resetColumnState(); lastApplied.current = ''; preferences.reset(); }}><RotateCcw className="h-3.5 w-3.5" aria-hidden />Сбросить вид и сортировку</Button></footer>
            </DialogContent>
        </Dialog>
    </section></GridHeaderContext.Provider>;
}


function ColumnWidthInput({ id, label, value, onCommit }: { id: string; label: string; value?: number; onCommit: (value?: number) => void }) {
    const [draft, setDraft] = useState(value?.toString() ?? '');
    const [error, setError] = useState(false);
    useEffect(() => { setDraft(value?.toString() ?? ''); setError(false); }, [value]);
    return <div className="max-w-full">
        <label className="flex items-center gap-2 text-xs text-muted-foreground">Ширина<input data-ui="input" aria-label={`Ширина ${label}`} aria-invalid={error || undefined} aria-describedby={error ? `fleet-width-error-${id}` : undefined}
            type="number" min={FLEET_MIN_COLUMN_WIDTH[id]} max={720} placeholder="Авто" value={draft}
            onChange={event => { setDraft(event.target.value); setError(false); }}
            onBlur={event => {
                const raw = event.target.value; const next = Number(raw);
                if (!raw) { onCommit(undefined); return; }
                if (!Number.isFinite(next) || next < FLEET_MIN_COLUMN_WIDTH[id] || next > 720) { setError(true); return; }
                onCommit(Math.round(next));
            }}
            onKeyDown={event => { if (event.key === 'Enter') event.currentTarget.blur(); else if (event.key === 'Escape') { event.currentTarget.value = value?.toString() ?? ''; setDraft(value?.toString() ?? ''); setError(false); event.currentTarget.blur(); } }}
            className="h-8 w-20 rounded-md border bg-card px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" /></label>
        {error && <p id={`fleet-width-error-${id}`} role="status" className="mt-1 text-xs text-destructive">От {FLEET_MIN_COLUMN_WIDTH[id]} до 720 px</p>}
    </div>;
}
