"use client";

import * as React from "react";
import Link from 'next/link';
import { useThemeStore } from '@/src/shared/store/themeStore';
import { useUIStore } from '@/src/shared/store/useUIStore';
import dynamic from 'next/dynamic';
const FleetDataGrid = dynamic(() => import('./FleetDataGrid').then(module => module.FleetDataGrid), { ssr: false, loading: () => <div role="status" className="flex min-h-64 flex-1 items-center justify-center text-sm text-muted-foreground">Подготавливаем таблицу…</div> });
import {
    ColumnDef,
    getCoreRowModel,
    getSortedRowModel,
    useReactTable,
    RowSelectionState,
    OnChangeFn,
} from "@tanstack/react-table";
import { Device } from "@/lib/hooks/useDevices";
import { DeviceViewerBadge } from './DeviceViewerBadge';
import { useFleetTablePreferences } from './fleetTablePreferences';
import { getReportedDeviceModel } from './devicePresentation';
import { DeviceStatusBadge } from "@/components/sphere/DeviceStatusBadge";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/src/shared/ui/badge";
import { Button } from "@/src/shared/ui/button";
import { cn } from "@/src/shared/lib/utils";
import { useInspectorStore } from "@/src/features/inspector/inspectorStore";
import { Activity, Cpu, Wifi, Battery, Shield, MoreHorizontal, Pencil, FolderOpen, MapPin, Trash2, Server } from "lucide-react";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export type DeviceAction = 'rename' | 'assign_group' | 'assign_location' | 'assign_server' | 'delete';

function formatElapsedSince(timestamp: string | null | undefined, now: number): string | null {
    if (!timestamp) return null;
    const parsed = Date.parse(timestamp);
    if (!Number.isFinite(parsed) || parsed > now + 60_000) return null;

    const seconds = Math.max(0, Math.floor((now - parsed) / 1000));
    if (seconds < 60) return `${seconds} с`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} мин`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} ч ${minutes % 60} мин`;
    const days = Math.floor(hours / 24);
    return `${days} д ${hours % 24} ч`;
}

interface FleetMatrixProps {
    data: Device[];
    isLoading: boolean;
    rowSelection: RowSelectionState;
    onRowSelectionChange: OnChangeFn<RowSelectionState>;
    onDeviceAction?: (deviceId: string, action: DeviceAction) => void;
    canDeviceAction?: (action: DeviceAction) => boolean;
    presentation?: 'table' | 'cards';
}

export function FleetMatrix({ data, isLoading, rowSelection, onRowSelectionChange, onDeviceAction, canDeviceAction, presentation = 'table' }: FleetMatrixProps) {
    const { openInspector } = useInspectorStore();
    const actionAuthority = React.useRef({ onDeviceAction, canDeviceAction });
    actionAuthority.current = { onDeviceAction, canDeviceAction };
    const selectionId = React.useId();
    const density = useThemeStore(state => state.density);
    const fontSize = useUIStore(state => state.fontSize);
    const [isNarrow, setIsNarrow] = React.useState<boolean | null>(null);
    React.useEffect(() => {
        if (typeof window.matchMedia !== 'function') { setIsNarrow(false); return; }
        const media = window.matchMedia('(max-width: 639px)');
        const reconcile = () => setIsNarrow(media.matches);
        reconcile(); media.addEventListener('change', reconcile);
        return () => media.removeEventListener('change', reconcile);
    }, []);
    const cardLayout = presentation === 'cards' || isNarrow;
    const rowHeight = Math.ceil(({ compact: 60, cozy: 72, spacious: 88 }[density]) * ({ sm: .875, base: 1, lg: 1.125 }[fontSize]));
    const preferences = useFleetTablePreferences();
    const { columnVisibility, setColumnVisibility, sorting, setSorting } = preferences;
    const [clockNow, setClockNow] = React.useState(() => Date.now());

    React.useEffect(() => {
        const timer = window.setInterval(() => setClockNow(Date.now()), 15_000);
        return () => window.clearInterval(timer);
    }, []);

    const columns = React.useMemo<ColumnDef<Device>[]>(
        () => [
            {
                id: "select",
                size: 52,
                enableHiding: false,
                header: ({ table }) => (
                    <div className="flex h-full items-center justify-center">
                        <label htmlFor={`${selectionId}-all`} className="flex h-11 w-11 cursor-pointer items-center justify-center">
                        <Checkbox
                            id={`${selectionId}-all`}
                            checked={table.getIsAllPageRowsSelected() ? true : table.getIsSomePageRowsSelected() ? 'indeterminate' : false}
                            onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
                            aria-label="Выбрать все видимые устройства"
                            className="border-muted-foreground/50 data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                        />
                        </label>
                    </div>
                ),
                cell: ({ row }) => (
                    <div className="flex h-full items-center justify-center" onClick={(e) => e.stopPropagation()}>
                        <label htmlFor={`${selectionId}-${row.id}`} className="flex h-11 w-11 cursor-pointer items-center justify-center">
                        <Checkbox
                            id={`${selectionId}-${row.id}`}
                            checked={row.getIsSelected()}
                            onCheckedChange={(value) => row.toggleSelected(!!value)}
                            aria-label={`Выбрать ${row.original.name}`}
                            className="border-muted-foreground/50 data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                        />
                        </label>
                    </div>
                ),
            },
            {
                accessorKey: "name",
                header: "Устройство",
                enableHiding: false,
                size: 240,
                cell: ({ row }) => {
                    const device = row.original;
                    const metadata = getReportedDeviceModel(device) ?? "Модель не сообщена";
                    return (
                        <div className="flex h-full flex-col justify-center pr-1">
                            <div className="flex min-w-0 items-center gap-1.5"><button
                                type="button"
                                data-inspector-device={device.id}
                                onClick={(event) => {
                                    event.stopPropagation();
                                    openInspector("device", device.id, device);
                                }}
                                aria-label={`Открыть устройство ${device.name}`}
                                className="w-fit max-w-full truncate rounded-sm text-left text-sm font-semibold text-foreground transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary motion-reduce:transition-none"
                            >
                                {device.name}
                            </button>
                            <DeviceViewerBadge card={device.card_viewers} stream={device.stream_viewers} />
                            </div>
                            <span className="truncate text-xs leading-4 text-muted-foreground" title={metadata}>
                                {metadata}
                            </span>
                        </div>
                    );
                },
            },
            {
                id: "agent_version",
                header: "Android / агент",
                accessorFn: (device) => device.agent_version ?? '',
                size: 180,
                cell: ({ row }) => {
                    const device = row.original;
                    const android = device.android_version?.trim();
                    const agent = device.agent_version?.trim();
                    return <div className="flex h-full flex-col justify-center gap-1 whitespace-normal text-xs leading-4">
                        <span>{android ? `Android ${android.replace(/^Android\s+/i, '')}` : 'Android не сообщён'}</span>
                        <span className="truncate font-mono text-[11px] text-muted-foreground">{agent ? `Agent ${agent}` : 'Агент не сообщил версию'}</span>
                    </div>;
                },
            },
            {
                accessorKey: "status",
                header: "Состояние",
                size: 185,
                cell: ({ row }) => {
                    const device = row.original;
                    const uptime = formatElapsedSince(device.connected_since, clockNow);
                    const detail = device.status === "online" || device.status === "busy"
                        ? uptime ? `В сети ${uptime}` : "Начало сессии не сообщено"
                        : device.status === "connecting"
                            ? "Ожидание первого heartbeat"
                            : "По статусу API";

                    return (
                        <div className="flex h-full min-w-0 flex-col justify-center gap-0.5" title={detail}>
                            <DeviceStatusBadge status={device.status} />
                            <span className="whitespace-normal text-xs leading-4 text-muted-foreground" aria-label={detail}>
                                {detail}
                            </span>
                        </div>
                    );
                },
            },
            {
                accessorKey: "battery_level",
                header: "Заряд",
                size: 90,
                cell: ({ row }) => {
                    const lvl = row.original.battery_level;
                    if (typeof lvl !== 'number' || !Number.isFinite(lvl) || lvl < 0 || lvl > 100) return <span className="text-muted-foreground">—</span>;
                    const isLow = lvl < 20;

                    return (
                        <div className="flex items-center justify-between w-full h-full pr-2">
                            <div className="flex items-center gap-1">
                                <Battery className={cn("w-3 h-3", isLow ? "text-destructive" : "text-success")} />
                                <span className={cn("font-mono text-xs", isLow && "text-destructive font-bold")}>
                                    {lvl}%
                                </span>
                            </div>
                        </div>
                    );
                },
            },
            {
                accessorKey: "network",
                header: "Доступ",
                size: 145,
                cell: ({ row }) => {
                    const { adb_connected, vpn_assigned } = row.original;

                    return (
                        <div className="flex h-full w-full flex-col justify-center gap-0.5 pr-2">
                            <div className="flex flex-col items-start gap-0.5" aria-label="Reported access flags">
                                <span className="inline-flex items-center gap-1" title={`ADB ${adb_connected ? "linked" : "not linked"}`}>
                                    {adb_connected ? <Wifi className="w-3 h-3 text-success" aria-hidden="true" /> : <Wifi className="w-3 h-3 text-muted-foreground/30" aria-hidden="true" />}
                                    <span className="text-[10px] font-mono text-muted-foreground">ADB {adb_connected ? "linked" : "—"}</span>
                                </span>
                                <span className="inline-flex items-center gap-1" title={`VPN ${vpn_assigned ? "assigned" : "not assigned"}`}>
                                    {vpn_assigned ? <Shield className="w-3 h-3 text-primary" aria-hidden="true" /> : <Shield className="w-3 h-3 text-muted-foreground/30" aria-hidden="true" />}
                                    <span className="text-[10px] font-mono text-muted-foreground">VPN {vpn_assigned ? "assigned" : "—"}</span>
                                </span>
                            </div>
                        </div>
                    );
                },
            },
            {
                accessorKey: "server_name",
                header: "Игровой сервер",
                size: 125,
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
                header: "Теги",
                size: 130,
                cell: ({ row }) => {
                    const tags = row.original.tags;
                    if (!tags || tags.length === 0) return <span className="text-muted-foreground text-xs">Нет тегов</span>;
                    return (
                        <div className="flex gap-1.5 items-center flex-wrap h-full overflow-hidden content-center py-1">
                            {tags.slice(0, 3).map((tag) => (
                                <Badge key={tag} variant="outline" className="text-[10px] bg-muted px-1.5 py-0 border-border">
                                    {tag}
                                </Badge>
                            ))}
                            {tags.length > 3 && (
                                <Badge variant="outline" className="text-[10px] bg-muted px-1.5 py-0 border-border text-muted-foreground">
                                    +{tags.length - 3}
                                </Badge>
                            )}
                        </div>
                    );
                },
            },
            {
                id: "last_seen",
                accessorFn: (device) => {
                    const timestamp = formatElapsedSince(device.last_heartbeat, clockNow) ? device.last_heartbeat
                        : formatElapsedSince(device.last_seen, clockNow) ? device.last_seen : null;
                    return timestamp ? Date.parse(timestamp) : 0;
                },
                header: "Heartbeat / контакт",
                size: 200,
                cell: ({ row }) => {
                    const heartbeatAge = formatElapsedSince(row.original.last_heartbeat, clockNow);
                    const contactAge = formatElapsedSince(row.original.last_seen, clockNow);
                    const ts = heartbeatAge ? row.original.last_heartbeat : contactAge ? row.original.last_seen : null;
                    if (!ts) return <div className="flex h-full items-center text-xs text-muted-foreground">Нет данных о сигнале</div>;
                    const date = new Date(ts);
                    const label = heartbeatAge ? `heartbeat ${heartbeatAge} назад` : `Контакт ${contactAge} назад`;
                    return (
                        <div className="flex h-full flex-col justify-center gap-1 whitespace-normal" title={`${label}\n${date.toISOString()}`}>
                            <span className="text-xs text-foreground">{label}</span>
                            <span className="font-mono text-[11px] text-muted-foreground">{date.toLocaleString('ru-RU', { timeZone: 'UTC', hour12: false })} UTC</span>
                        </div>
                    );
                },
            },
            {
                accessorKey: 'android_id',
                header: 'Android ID',
                size: 220,
                cell: ({ row }) => <span className="break-all font-mono text-xs" title={row.original.android_id}>{row.original.android_id || 'Не сообщён'}</span>,
            },
            {
                accessorKey: 'cpu_usage',
                header: 'CPU Android',
                size: 120,
                cell: ({ row }) => {
                    const value = row.original.cpu_usage;
                    return <span className="font-mono text-xs" title="Последний отчёт агента: загрузка CPU Android, не процесса APK">
                        {typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100 ? `${value.toFixed(1)}%` : 'Не сообщено'}
                    </span>;
                },
            },
            {
                accessorKey: 'ram_usage_mb',
                header: 'RAM Android',
                size: 145,
                cell: ({ row }) => {
                    const value = row.original.ram_usage_mb;
                    return <span className="font-mono text-xs" title="Последний отчёт агента: занятая память Android, не RSS/PSS процесса APK">
                        {typeof value === 'number' && Number.isFinite(value) && value >= 0 ? `${Math.round(value)} MiB` : 'Не сообщено'}
                    </span>;
                },
            },
            {
                id: "actions",
                size: 52,
                enableHiding: false,
                header: () => null,
                cell: ({ row }) => <FleetDeviceActions device={row.original} onDeviceAction={(id, action) => actionAuthority.current.onDeviceAction?.(id, action)} canDeviceAction={action => actionAuthority.current.canDeviceAction?.(action) ?? false} />,
            },
        ],
        [clockNow, onDeviceAction, openInspector, canDeviceAction, selectionId]
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
        autoResetPageIndex: false, // Pagination belongs to the registry API, not this virtualized table.
        getRowId: (row) => row.id,
    });

    const { rows } = table.getRowModel();

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

    if (cardLayout) return (
        <section aria-label="Карточки устройств" className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <label htmlFor={`${selectionId}-cards-all`} className="flex min-h-11 cursor-pointer items-center gap-2 text-xs text-muted-foreground">
                    <Checkbox id={`${selectionId}-cards-all`} checked={table.getIsAllPageRowsSelected() ? true : table.getIsSomePageRowsSelected() ? 'indeterminate' : false}
                        aria-label="Выбрать все видимые устройства" onCheckedChange={value => table.toggleAllPageRowsSelected(!!value)} />Выбрать все
                </label>
                <select data-ui="select" aria-label="Сортировка устройств" className="h-[var(--control-height)] max-w-full rounded-lg border border-input bg-background px-3 text-sm"
                    value={!sorting.length ? '' : `${sorting[0].id}:${sorting[0].desc ? 'desc' : 'asc'}`}
                    onChange={event => { const [id, direction] = event.target.value.split(':'); setSorting(id ? [{ id, desc: direction === 'desc' }] : []); }}>
                    <option value="">По умолчанию</option><option value="name:asc">Имя: А — Я</option><option value="name:desc">Имя: Я — А</option>
                    <option value="status:asc">Состояние</option><option value="last_seen:desc">Последний контакт</option>
                    {sorting.length > 0 && !['name:asc', 'name:desc', 'status:asc', 'last_seen:desc'].includes(`${sorting[0].id}:${sorting[0].desc ? 'desc' : 'asc'}`) &&
                        <option value={`${sorting[0].id}:${sorting[0].desc ? 'desc' : 'asc'}`}>Сортировка из таблицы</option>}
                </select>
            </div>
            <div className="grid min-h-0 min-w-0 gap-3 sm:flex-1 sm:grid-cols-2 sm:overflow-y-auto xl:grid-cols-3 2xl:grid-cols-4" role="list" aria-label="Устройства организации">
                {rows.map(row => {
                    const device = row.original; const heartbeat = formatElapsedSince(device.last_heartbeat, clockNow);
                    const contact = formatElapsedSince(device.last_seen, clockNow);
                    const uptime = formatElapsedSince(device.connected_since, clockNow);
                    return <article key={row.id} role="listitem" className={cn('min-w-0 rounded-xl border bg-background p-3 transition-colors hover:border-primary/40', row.getIsSelected() ? 'border-primary/50 bg-primary/5' : 'border-border')}>
                        <div className="flex items-center gap-2">
                            <label htmlFor={`${selectionId}-card-${row.id}`} className="flex h-11 w-7 shrink-0 cursor-pointer items-center justify-center">
                                <Checkbox id={`${selectionId}-card-${row.id}`} aria-label={`Выбрать ${device.name}`} checked={row.getIsSelected()} onCheckedChange={value => row.toggleSelected(!!value)} />
                            </label>
                            <button type="button" data-inspector-device={device.id} aria-label={`Открыть устройство ${device.name}`} onClick={() => openInspector('device', device.id, device)}
                                className="min-h-11 min-w-0 flex-1 truncate rounded-md text-left text-sm font-semibold text-foreground hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{device.name}</button>
                            <DeviceViewerBadge card={device.card_viewers} stream={device.stream_viewers} />
                            <FleetDeviceActions device={device} onDeviceAction={onDeviceAction} canDeviceAction={canDeviceAction} />
                        </div>
                        <p className="truncate text-xs text-muted-foreground" title={getReportedDeviceModel(device) ?? undefined}>{getReportedDeviceModel(device) ?? 'Модель не сообщена'}</p>
                        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                            <DeviceStatusBadge status={device.status} />
                            <span className="text-xs text-muted-foreground">{['online', 'busy'].includes(device.status) && uptime ? `В сети ${uptime}` : device.status === 'connecting' ? 'Ожидаем APK' : 'Нет активной связи'}</span>
                        </div>
                        <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-border pt-3 text-xs">
                            <div className="min-w-0"><dt className="text-muted-foreground">Android</dt><dd className="mt-1 truncate">{device.android_version?.replace(/^Android\s+/i, '') || 'Не сообщён'}</dd></div>
                            <div className="min-w-0"><dt className="text-muted-foreground">Sphere Agent</dt><dd className="mt-1 truncate font-mono" title={device.agent_version ?? undefined}>{device.agent_version || 'Не сообщён'}</dd></div>
                            <div className="col-span-2"><dt className="sr-only">Последний контакт</dt><dd className="text-muted-foreground">{heartbeat ? `heartbeat ${heartbeat} назад` : contact ? `Контакт ${contact} назад` : 'Нет данных о сигнале'}</dd></div>
                        </dl>
                    </article>;
                })}
            </div>
        </section>
    );

    if (isNarrow === null) return <div role="status" className="flex min-h-64 flex-1 items-center justify-center text-sm text-muted-foreground">Подготавливаем список…</div>;
    return <FleetDataGrid table={table} preferences={preferences} rowHeight={rowHeight} clockNow={clockNow} />;
}


function FleetDeviceActions({ device, onDeviceAction, canDeviceAction }: { device: Device; onDeviceAction?: (id: string, action: DeviceAction) => void; canDeviceAction?: (action: DeviceAction) => boolean }) {
    return <div className="flex h-full items-center justify-center" onClick={event => event.stopPropagation()}>
        <DropdownMenu>
            <DropdownMenuTrigger asChild><Button type="button" variant="ghost" size="icon" aria-label={`Действия устройства ${device.name}`} title={`Действия устройства ${device.name}`} className="h-9 w-9 text-muted-foreground hover:text-primary">
                <MoreHorizontal className="h-4 w-4" aria-hidden />
            </Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel className="truncate text-xs text-muted-foreground">{device.name}</DropdownMenuLabel>
                <DropdownMenuItem asChild><Link href={`/devices/${device.id}`}><Cpu className="mr-2 h-4 w-4" aria-hidden />Полная карточка</Link></DropdownMenuItem>
                <DropdownMenuSeparator />
                {([['rename', 'Переименовать', Pencil], ['assign_group', 'Назначить группу', FolderOpen], ['assign_location', 'Назначить локацию', MapPin], ['assign_server', 'Игровой сервер', Server]] as const).map(([action, label, Icon]) =>
                    <DropdownMenuItem key={action} disabled={!canDeviceAction?.(action) || !onDeviceAction} onClick={() => { if (canDeviceAction?.(action)) onDeviceAction?.(device.id, action); }}>
                        <Icon className="mr-2 h-4 w-4" aria-hidden />{label}
                    </DropdownMenuItem>)}
                <DropdownMenuSeparator />
                <DropdownMenuItem className="text-destructive focus:bg-destructive/10 focus:text-destructive" disabled={!canDeviceAction?.('delete') || !onDeviceAction} onClick={() => { if (canDeviceAction?.('delete')) onDeviceAction?.(device.id, 'delete'); }}>
                    <Trash2 className="mr-2 h-4 w-4" aria-hidden />Убрать из каталога
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    </div>;
}
