"use client";

import * as React from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
    ColumnDef,
    flexRender,
    getCoreRowModel,
    getSortedRowModel,
    SortingState,
    useReactTable,
    RowSelectionState,
    VisibilityState,
    OnChangeFn,
} from "@tanstack/react-table";
import { Device } from "@/lib/hooks/useDevices";
import { DeviceStatusBadge } from "@/components/sphere/DeviceStatusBadge";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/src/shared/ui/badge";
import { Button } from "@/src/shared/ui/button";
import { cn } from "@/src/shared/lib/utils";
import { useInspectorStore } from "@/src/features/inspector/inspectorStore";
import { Activity, Cpu, Wifi, Battery, Shield, Columns3, MoreHorizontal, Pencil, FolderOpen, MapPin, Trash2, Server } from "lucide-react";
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export type DeviceAction = 'rename' | 'assign_group' | 'assign_location' | 'assign_server' | 'delete';

interface FleetMatrixProps {
    data: Device[];
    isLoading: boolean;
    rowSelection: RowSelectionState;
    onRowSelectionChange: OnChangeFn<RowSelectionState>;
    onDeviceAction?: (deviceId: string, action: DeviceAction) => void;
}

export function FleetMatrix({ data, isLoading, rowSelection, onRowSelectionChange, onDeviceAction }: FleetMatrixProps) {
    const { openInspector } = useInspectorStore();
    const parentRef = React.useRef<HTMLDivElement>(null);
    const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({});
    const [sorting, setSorting] = React.useState<SortingState>([]);

    const columns = React.useMemo<ColumnDef<Device>[]>(
        () => [
            {
                id: "select",
                size: 40,
                enableHiding: false,
                header: ({ table }) => (
                    <div className="flex items-center justify-center h-full">
                        <Checkbox
                            checked={table.getIsAllPageRowsSelected()}
                            onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
                            aria-label="Выбрать все видимые устройства"
                            className="border-muted-foreground/50 data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                        />
                    </div>
                ),
                cell: ({ row }) => (
                    <div className="flex items-center justify-center h-full" onClick={(e) => e.stopPropagation()}>
                        <Checkbox
                            checked={row.getIsSelected()}
                            onCheckedChange={(value) => row.toggleSelected(!!value)}
                            aria-label={`Выбрать ${row.original.name}`}
                            className="border-muted-foreground/50 data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                        />
                    </div>
                ),
            },
            {
                accessorKey: "name",
                header: "Identifier",
                size: 250,
                cell: ({ row }) => {
                    const device = row.original;
                    return (
                        <div className="flex h-full flex-col justify-center pr-4">
                            <button
                                type="button"
                                onClick={(event) => {
                                    event.stopPropagation();
                                    openInspector("device", device.id, device);
                                }}
                                aria-label={`Открыть устройство ${device.name}`}
                                className="w-fit max-w-full truncate text-left font-mono text-sm font-semibold text-foreground transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary motion-reduce:transition-none"
                            >
                                {device.name}
                            </button>
                            <span className="font-mono text-[10px] text-muted-foreground truncate">
                                {device.model} • Android {device.android_version} • Agent {device.agent_version || "not reported"}
                            </span>
                        </div>
                    );
                },
            },
            {
                accessorKey: "status",
                header: "Status",
                size: 100,
                cell: ({ row }) => (
                    <div className="flex items-center h-full">
                        <DeviceStatusBadge status={row.original.status} />
                    </div>
                ),
            },
            {
                accessorKey: "battery_level",
                header: "Power",
                size: 120,
                cell: ({ row }) => {
                    const lvl = row.original.battery_level;
                    if (lvl === null) return <span className="text-muted-foreground">—</span>;
                    const isLow = lvl < 20;

                    return (
                        <div className="flex items-center justify-between w-full h-full pr-2">
                            <div className="flex items-center gap-1">
                                <Battery className={cn("w-3 h-3", isLow ? "text-destructive" : "text-success")} />
                                <span className={cn("font-mono text-[10px]", isLow && "text-destructive font-bold")}>
                                    {lvl}%
                                </span>
                            </div>
                        </div>
                    );
                },
            },
            {
                accessorKey: "network",
                header: "Access",
                size: 140,
                cell: ({ row }) => {
                    const { adb_connected, vpn_assigned } = row.original;

                    return (
                        <div className="flex items-center gap-2 w-full h-full pr-2">
                            <div className="flex items-center gap-1.5" aria-label="Reported access flags">
                                <span className="inline-flex items-center gap-1" title={`ADB ${adb_connected ? "linked" : "not linked"}`}>
                                    {adb_connected ? <Wifi className="w-3 h-3 text-success" aria-hidden="true" /> : <Wifi className="w-3 h-3 text-muted-foreground/30" aria-hidden="true" />}
                                    <span className="text-[9px] font-mono text-muted-foreground">ADB {adb_connected ? "linked" : "—"}</span>
                                </span>
                                <span className="inline-flex items-center gap-1" title={`VPN ${vpn_assigned ? "assigned" : "not assigned"}`}>
                                    {vpn_assigned ? <Shield className="w-3 h-3 text-primary" aria-hidden="true" /> : <Shield className="w-3 h-3 text-muted-foreground/30" aria-hidden="true" />}
                                    <span className="text-[9px] font-mono text-muted-foreground">VPN {vpn_assigned ? "assigned" : "—"}</span>
                                </span>
                            </div>
                        </div>
                    );
                },
            },
            {
                accessorKey: "server_name",
                header: "Game Server",
                size: 130,
                cell: ({ row }) => {
                    const sn = row.original.server_name;
                    if (!sn) return <span className="text-muted-foreground text-[10px] font-mono">—</span>;
                    return (
                        <div className="flex items-center gap-1.5 h-full">
                            <Server className="w-3 h-3 text-primary shrink-0" />
                            <span className="font-mono text-[11px] text-foreground truncate">{sn}</span>
                        </div>
                    );
                },
            },
            {
                accessorKey: "tags",
                header: "Classification Tags",
                size: 300,
                cell: ({ row }) => {
                    const tags = row.original.tags;
                    if (!tags || tags.length === 0) return <span className="text-muted-foreground text-[10px]">NO TAGS</span>;
                    return (
                        <div className="flex gap-1.5 items-center flex-wrap h-full overflow-hidden content-center py-1">
                            {tags.slice(0, 3).map((tag) => (
                                <Badge key={tag} variant="outline" className="text-[9px] bg-muted px-1.5 py-0 border-border">
                                    {tag}
                                </Badge>
                            ))}
                            {tags.length > 3 && (
                                <Badge variant="outline" className="text-[9px] bg-muted px-1.5 py-0 border-border text-muted-foreground">
                                    +{tags.length - 3}
                                </Badge>
                            )}
                        </div>
                    );
                },
            },
            {
                accessorKey: "last_seen",
                header: "Last Seen",
                size: 150,
                cell: ({ row }) => {
                    const ts = row.original.last_seen;
                    if (!ts) return <span className="text-muted-foreground">—</span>;
                    const date = new Date(ts);
                    return (
                        <div className="flex flex-col justify-center h-full">
                            <span className="font-mono text-[10px] text-foreground">
                                {date.toLocaleTimeString([], { hour12: false })}
                            </span>
                            <span className="font-mono text-[9px] text-muted-foreground">
                                {date.toLocaleDateString()}
                            </span>
                        </div>
                    );
                },
            },
            {
                id: "actions",
                size: 48,
                enableHiding: false,
                header: () => null,
                cell: ({ row }) => {
                    const device = row.original;
                    return (
                        <div className="flex items-center justify-center h-full" onClick={(e) => e.stopPropagation()}>
                            <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon"
                                        aria-label={`Действия устройства ${device.name}`}
                                        title={`Действия устройства ${device.name}`}
                                        className="h-8 w-8 rounded-sm text-muted-foreground opacity-0 transition-opacity hover:text-primary focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary group-hover:opacity-100 motion-reduce:transition-none"
                                    >
                                        <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
                                    </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end" className="w-44 bg-card border-border">
                                    <DropdownMenuItem
                                        className="text-xs font-mono cursor-pointer"
                                        onClick={() => onDeviceAction?.(device.id, 'rename')}
                                    >
                                        <Pencil className="w-3 h-3 mr-2" /> Переименовать
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        className="text-xs font-mono cursor-pointer"
                                        onClick={() => onDeviceAction?.(device.id, 'assign_group')}
                                    >
                                        <FolderOpen className="w-3 h-3 mr-2" /> В группу
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        className="text-xs font-mono cursor-pointer"
                                        onClick={() => onDeviceAction?.(device.id, 'assign_location')}
                                    >
                                        <MapPin className="w-3 h-3 mr-2" /> В локацию
                                    </DropdownMenuItem>
                                    <DropdownMenuItem
                                        className="text-xs font-mono cursor-pointer"
                                        onClick={() => onDeviceAction?.(device.id, 'assign_server')}
                                    >
                                        <Server className="w-3 h-3 mr-2" /> Игровой сервер
                                    </DropdownMenuItem>
                                    <DropdownMenuSeparator className="bg-border" />
                                    <DropdownMenuItem
                                        className="text-xs font-mono cursor-pointer text-destructive focus:text-destructive"
                                        onClick={() => onDeviceAction?.(device.id, 'delete')}
                                    >
                                        <Trash2 className="w-3 h-3 mr-2" /> Удалить
                                    </DropdownMenuItem>
                                </DropdownMenuContent>
                            </DropdownMenu>
                        </div>
                    );
                },
            },
        ],
        [onDeviceAction, openInspector]
    );

    const table = useReactTable({
        data,
        columns,
        state: { rowSelection, columnVisibility, sorting },
        onRowSelectionChange: onRowSelectionChange,
        onColumnVisibilityChange: setColumnVisibility,
        onSortingChange: setSorting,
        getCoreRowModel: getCoreRowModel(),
        getSortedRowModel: getSortedRowModel(),
        getRowId: (row) => row.id,
    });

    const { rows } = table.getRowModel();

    const virtualizer = useVirtualizer({
        count: rows.length,
        getScrollElement: () => parentRef.current,
        estimateSize: () => 48,
        overscan: 20,
    });

    if (isLoading) {
        return (
            <div role="status" aria-live="polite" className="relative flex flex-1 flex-col items-center justify-center overflow-hidden rounded-lg border border-border bg-card text-sm text-muted-foreground">
                <Activity className="mb-3 h-6 w-6 animate-pulse opacity-50 motion-reduce:animate-none" aria-hidden="true" />
                <p>Загружаем список устройств…</p>

                {/* Decorative Grid Lines */}
                <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px] pointer-events-none" />
            </div>
        );
    }

    if (data.length === 0) {
        return (
            <div role="status" className="flex min-h-[280px] flex-1 flex-col items-center justify-center rounded-lg border border-dashed border-border bg-background/50 px-6 text-center">
                <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
                    <Cpu className="h-5 w-5" aria-hidden="true" />
                </span>
                <h2 className="text-base font-semibold text-foreground">Устройства не найдены</h2>
                <p className="mt-2 max-w-md text-sm text-muted-foreground">
                    Измените поиск или фильтры. Новое устройство появится после регистрации Sphere Agent и первого heartbeat.
                </p>
            </div>
        );
    }

    return (
        <div role="table" aria-label="Устройства организации" className="relative flex flex-1 flex-col overflow-x-auto overflow-y-hidden rounded-lg border border-border bg-card shadow-sm custom-scrollbar">
            {/* Dynamic Header (Sticky) */}
            <div role="row" className="sticky top-0 z-10 flex h-10 min-w-max border-b border-border bg-muted pr-8 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {table.getFlatHeaders().map((header) => {
                    const canSort = header.column.getCanSort();
                    const sorted = header.column.getIsSorted();
                    return (
                        <div
                            key={header.id}
                            role="columnheader"
                            aria-sort={sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : undefined}
                            className="flex shrink-0 items-center truncate border-r border-border px-3 last:border-r-0"
                            style={{ width: header.getSize() }}
                        >
                            {header.isPlaceholder ? null : canSort ? (
                                <button
                                    type="button"
                                    onClick={header.column.getToggleSortingHandler()}
                                    aria-label={`Сортировать по ${typeof header.column.columnDef.header === 'string' ? header.column.columnDef.header : header.column.id}`}
                                    className="flex h-full w-full items-center text-left transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary motion-reduce:transition-none"
                                >
                                    {flexRender(header.column.columnDef.header, header.getContext())}
                                    {sorted === 'asc' && <span className="ml-1 text-primary" aria-hidden="true">↑</span>}
                                    {sorted === 'desc' && <span className="ml-1 text-primary" aria-hidden="true">↓</span>}
                                </button>
                            ) : flexRender(header.column.columnDef.header, header.getContext())}
                        </div>
                    );
                })}

                {/* Column Visibility Toggle */}
                <div className="absolute right-0 top-0 h-full w-8 border-l border-border bg-muted flex items-center justify-center">
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon" aria-label="Настроить видимые колонки" className="h-7 w-7 rounded-md text-muted-foreground hover:text-primary">
                                <Columns3 className="w-3.5 h-3.5" />
                            </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="w-40 bg-card border-border">
                            <DropdownMenuLabel className="font-mono text-[10px] uppercase text-muted-foreground">Toggle Columns</DropdownMenuLabel>
                            <DropdownMenuSeparator className="bg-border" />
                            {table
                                .getAllColumns()
                                .filter((column) => typeof column.accessorFn !== "undefined" && column.getCanHide())
                                .map((column) => {
                                    return (
                                        <DropdownMenuCheckboxItem
                                            key={column.id}
                                            className="capitalize text-xs font-mono font-bold"
                                            checked={column.getIsVisible()}
                                            onCheckedChange={(value) => column.toggleVisibility(!!value)}
                                        >
                                            {column.id.replace('_', ' ')}
                                        </DropdownMenuCheckboxItem>
                                    );
                                })}
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>
            </div>

            {/* Virtualized Body */}
            <div
                ref={parentRef}
                role="rowgroup"
                className="relative min-w-max flex-1 overflow-x-hidden overflow-y-auto bg-card custom-scrollbar"
            >
                <div
                    style={{
                        height: `${virtualizer.getTotalSize()}px`,
                        width: "100%",
                        position: "relative",
                    }}
                >
                    {virtualizer.getVirtualItems().map((virtualRow) => {
                        const row = rows[virtualRow.index];
                        const isSelected = row.getIsSelected();
                        return (
                            <div
                                key={row.id}
                                role="row"
                                aria-selected={isSelected}
                                className={cn(
                                    "group absolute left-0 top-0 flex min-w-max border-b border-border/60 transition-colors hover:bg-muted/60 motion-reduce:transition-none",
                                    isSelected && "bg-primary/5 hover:bg-primary/10"
                                )}
                                style={{
                                    height: `${virtualRow.size}px`,
                                    transform: `translateY(${virtualRow.start}px)`,
                                }}
                            >
                                {row.getVisibleCells().map((cell) => (
                                    <div
                                        key={cell.id}
                                        role="cell"
                                        className="shrink-0 truncate border-r border-transparent px-3 transition-colors group-hover:border-border last:border-r-0 motion-reduce:transition-none"
                                        style={{ width: cell.column.getSize() }}
                                    >
                                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                    </div>
                                ))}
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Decorative footer line */}
            <div className="h-1 w-full bg-gradient-to-r from-transparent via-primary/20 to-transparent flex-shrink-0" />
        </div>
    );
}
