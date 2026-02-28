"use client";

import * as React from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
    ColumnDef,
    flexRender,
    getCoreRowModel,
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
import { Activity, Wifi, Battery, Tag, Hash, Shield, Columns3 } from "lucide-react";
import { GridSparkline } from "./GridSparkline";
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface FleetMatrixProps {
    data: Device[];
    isLoading: boolean;
    rowSelection: RowSelectionState;
    onRowSelectionChange: OnChangeFn<RowSelectionState>;
}

export function FleetMatrix({ data, isLoading, rowSelection, onRowSelectionChange }: FleetMatrixProps) {
    const { openInspector } = useInspectorStore();
    const parentRef = React.useRef<HTMLDivElement>(null);
    const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({});

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
                            aria-label="Select all"
                            className="border-muted-foreground/50 data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                        />
                    </div>
                ),
                cell: ({ row }) => (
                    <div className="flex items-center justify-center h-full" onClick={(e) => e.stopPropagation()}>
                        <Checkbox
                            checked={row.getIsSelected()}
                            onCheckedChange={(value) => row.toggleSelected(!!value)}
                            aria-label="Select row"
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
                        <div className="flex flex-col justify-center h-full pr-4">
                            <span className="font-mono text-[13px] font-bold text-foreground">
                                {device.name}
                            </span>
                            <span className="font-mono text-[10px] text-muted-foreground truncate">
                                {device.model} • {device.android_version}
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

                    // Mock battery history (Slowly draining)
                    const batteryHistory = React.useMemo(() => Array.from({ length: 8 }, (_, i) => lvl + (7 - i)), [lvl]);

                    return (
                        <div className="flex items-center justify-between w-full h-full pr-2">
                            <div className="flex flex-col gap-1 w-10 shrink-0">
                                <div className="flex items-center gap-1">
                                    <Battery className={cn("w-3 h-3", isLow ? "text-destructive" : "text-success")} />
                                    <span className={cn("font-mono text-[10px]", isLow && "text-destructive font-bold")}>
                                        {lvl}%
                                    </span>
                                </div>
                            </div>
                            <div className="flex-1 max-w-[50px] opacity-70">
                                <GridSparkline data={batteryHistory} color={isLow ? '#ef4444' : '#22c55e'} height={16} />
                            </div>
                        </div>
                    );
                },
            },
            {
                accessorKey: "network",
                header: "Net Quality",
                size: 140,
                cell: ({ row }) => {
                    const { adb_connected, vpn_assigned } = row.original;
                    // Deterministic ping pattern based on row index
                    const idx = row.index;
                    const pingHistory = React.useMemo(() => [18, 22, 19, 25, 21, 17, 23, 20].map((v, i) => v + ((idx * 7 + i * 3) % 10)), [idx]);
                    const pingSum = pingHistory.reduce((a, b) => a + b, 0);
                    const avgPing = Math.round(pingSum / pingHistory.length);

                    return (
                        <div className="flex items-center justify-between w-full h-full pr-2">
                            <div className="flex flex-col gap-1 w-12 shrink-0">
                                <div className="flex items-center gap-1.5">
                                    {adb_connected ? <Wifi className="w-3 h-3 text-success" /> : <Wifi className="w-3 h-3 text-muted-foreground/30" />}
                                    {vpn_assigned ? <Shield className="w-3 h-3 text-primary" /> : <Shield className="w-3 h-3 text-muted-foreground/30" />}
                                </div>
                                <span className="text-[9px] font-mono text-muted-foreground">{adb_connected ? `${avgPing}ms` : 'OFF'}</span>
                            </div>
                            {adb_connected && (
                                <div className="flex-1 max-w-[60px] opacity-70">
                                    <GridSparkline data={pingHistory} color="#22c55e" height={16} />
                                </div>
                            )}
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
        ],
        []
    );

    const table = useReactTable({
        data,
        columns,
        state: { rowSelection, columnVisibility },
        onRowSelectionChange: onRowSelectionChange,
        onColumnVisibilityChange: setColumnVisibility,
        getCoreRowModel: getCoreRowModel(),
        getRowId: (row) => row.id,
    });

    const { rows } = table.getRowModel();

    const virtualizer = useVirtualizer({
        count: rows.length,
        getScrollElement: () => parentRef.current,
        estimateSize: () => 40, // 40px High-Density Row height
        overscan: 20, // Render 20 items outside viewport for smooth scrolling
    });

    if (isLoading) {
        return (
            <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground font-mono text-xs border border-border bg-card rounded-sm relative overflow-hidden">
                <Activity className="w-6 h-6 animate-pulse mb-3 opacity-50" />
                <p className="tracking-widest uppercase">Initializing Fleet Matrix...</p>

                {/* Decorative Grid Lines */}
                <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808012_1px,transparent_1px),linear-gradient(to_bottom,#80808012_1px,transparent_1px)] bg-[size:24px_24px] pointer-events-none" />
            </div>
        );
    }

    // Header Width Calc
    const totalWidth = table.getTotalSize();

    return (
        <div className="flex-1 flex flex-col border border-border bg-card rounded-sm overflow-x-auto overflow-y-hidden custom-scrollbar relative shadow-2xl">
            {/* Dynamic Header (Sticky) */}
            <div className="flex min-w-max bg-muted border-b border-border z-10 sticky top-0 uppercase tracking-widest text-[9px] font-bold text-muted-foreground h-8 pr-8">
                {table.getFlatHeaders().map((header) => (
                    <div
                        key={header.id}
                        className="flex items-center px-3 truncate border-r border-border last:border-r-0"
                        style={{ width: header.getSize() }}
                    >
                        {header.isPlaceholder
                            ? null
                            : flexRender(header.column.columnDef.header, header.getContext())}
                    </div>
                ))}

                {/* Column Visibility Toggle */}
                <div className="absolute right-0 top-0 h-full w-8 border-l border-border bg-muted flex items-center justify-center">
                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-6 w-6 rounded-sm text-muted-foreground hover:text-primary">
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
                className="flex-1 overflow-y-auto overflow-x-hidden min-w-max custom-scrollbar relative bg-card"
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
                                onClick={() => openInspector("device", row.original.id, row.original)}
                                className={cn(
                                    "absolute top-0 left-0 w-full flex border-b border-[#1A1A1A] hover:bg-[#151515] transition-colors cursor-pointer group",
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
                                        className="px-3 truncate border-r border-transparent group-hover:border-border transition-colors last:border-r-0"
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
