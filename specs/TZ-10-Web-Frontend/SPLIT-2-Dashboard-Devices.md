# SPLIT-2 — Dashboard + Device List

**ТЗ-родитель:** TZ-10-Web-Frontend  
**Ветка:** `stage/10-frontend`  
**Задача:** `SPHERE-052`  
**Исполнитель:** Frontend  
**Оценка:** 1.5 дня  
**Блокирует:** TZ-10 SPLIT-3

---

## Цель Сплита

Страница списка устройств с React Query, TanStack Table, статусными бейджами, фильтрами, bulk actions (выбор + выполнить скрипт / перезагрузить / отключить VPN).

---

## Шаг 1 — React Query + API hooks

```typescript
// lib/hooks/useDevices.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

export interface Device {
    id: string;
    name: string;
    android_id: string;
    model: string;
    android_version: string;
    tags: string[];
    group_id: string | null;
    group_name: string | null;
    status: 'online' | 'offline' | 'unknown';
    battery_level: number | null;
    last_seen: string | null;
    adb_connected: boolean;
    vpn_assigned: boolean;
}

interface DevicesResponse {
    items: Device[];
    total: number;
    page: number;
    page_size: number;
}

export function useDevices(params: {
    page?: number;
    page_size?: number;
    status?: string;
    tags?: string;
    group_id?: string;
    search?: string;
}) {
    return useQuery<DevicesResponse>({
        queryKey: ['devices', params],
        queryFn: async () => {
            const { data } = await api.get('/devices', { params });
            return data;
        },
        staleTime: 15_000,
        refetchInterval: 30_000,
    });
}

export function useBulkAction() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: async (body: {
            device_ids: string[];
            action: string;
            params?: object;
        }) => {
            const { data } = await api.post('/devices/bulk', body);
            return data;
        },
        onSuccess: () => {
            qc.invalidateQueries({ queryKey: ['devices'] });
        },
    });
}
```

---

## Шаг 2 — DeviceStatusBadge

```tsx
// components/sphere/DeviceStatusBadge.tsx
import { Badge } from '@/components/ui/badge';
import { Wifi, WifiOff, HelpCircle } from 'lucide-react';

export function DeviceStatusBadge({ status }: { status: string }) {
    const variants = {
        online: { variant: 'default' as const, icon: Wifi, label: 'Online', className: 'bg-green-600' },
        offline: { variant: 'secondary' as const, icon: WifiOff, label: 'Offline', className: 'bg-gray-600' },
        unknown: { variant: 'outline' as const, icon: HelpCircle, label: 'Unknown', className: '' },
    };
    
    const cfg = variants[status as keyof typeof variants] ?? variants.unknown;
    const Icon = cfg.icon;
    
    return (
        <Badge variant={cfg.variant} className={`gap-1 ${cfg.className}`}>
            <Icon className="w-3 h-3" />
            {cfg.label}
        </Badge>
    );
}
```

---

## Шаг 3 — DevicesPage

```tsx
// app/(dashboard)/devices/page.tsx
'use client';
import { useState, useEffect } from 'react';
import {
    ColumnDef,
    flexRender,
    getCoreRowModel,
    useReactTable,
    getFilteredRowModel,
    getPaginationRowModel,
    RowSelectionState,
} from '@tanstack/react-table';
import { useDevices, useBulkAction, Device } from '@/lib/hooks/useDevices';
import { DeviceStatusBadge } from '@/components/sphere/DeviceStatusBadge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';

const columns: ColumnDef<Device>[] = [
    {
        id: 'select',
        header: ({ table }) => (
            <Checkbox
                checked={table.getIsAllPageRowsSelected()}
                onCheckedChange={(v) => table.toggleAllPageRowsSelected(!!v)}
            />
        ),
        cell: ({ row }) => (
            <Checkbox
                checked={row.getIsSelected()}
                onCheckedChange={(v) => row.toggleSelected(!!v)}
            />
        ),
        enableSorting: false,
    },
    { accessorKey: 'name', header: 'Name' },
    { accessorKey: 'model', header: 'Model' },
    {
        accessorKey: 'status',
        header: 'Status',
        cell: ({ row }) => <DeviceStatusBadge status={row.original.status} />,
    },
    {
        accessorKey: 'tags',
        header: 'Tags',
        cell: ({ row }) => (
            <div className="flex gap-1 flex-wrap">
                {row.original.tags.map(tag => (
                    <Badge key={tag} variant="outline" className="text-xs">{tag}</Badge>
                ))}
            </div>
        ),
    },
    {
        accessorKey: 'battery_level',
        header: 'Battery',
        cell: ({ row }) => {
            const lvl = row.original.battery_level;
            if (lvl === null) return '—';
            return (
                <span className={lvl < 20 ? 'text-red-500' : ''}>
                    {lvl}%
                </span>
            );
        },
    },
    {
        accessorKey: 'last_seen',
        header: 'Last Seen',
        cell: ({ row }) => {
            const ts = row.original.last_seen;
            if (!ts) return '—';
            return new Date(ts).toLocaleString();
        },
    },
];

export default function DevicesPage() {
    const [search, setSearch] = useState('');
    const [page, setPage] = useState(1);
    const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
    // FIX: rowSelection хранит индексы текущей страницы — при смене страницы старые индексы
    // указывают на другие строки. Сбрасываем выделение при каждой смене page.
    useEffect(() => { setRowSelection({}); }, [page]);
    
    const { data, isLoading } = useDevices({ page, page_size: 50, search: search || undefined });
    const bulkMutation = useBulkAction();
    
    const table = useReactTable({
        data: data?.items ?? [],
        columns,
        state: { rowSelection },
        onRowSelectionChange: setRowSelection,
        getCoreRowModel: getCoreRowModel(),
        getFilteredRowModel: getFilteredRowModel(),
        getPaginationRowModel: getPaginationRowModel(),
        // FIX 10.2: БЫЛО — без getRowId, TanStack использовал array index
        // → При refetch react-query rowSelection сбрасывалась!
        getRowId: (row) => row.id,
    });
    
    // FIX 10.2: rowSelection теперь использует стабильные ID (row.id), не индексы
    const selectedIds = Object.keys(rowSelection).filter(Boolean);
    
    const handleBulkReboot = () => {
        bulkMutation.mutate({ device_ids: selectedIds, action: 'reboot' });
        setRowSelection({});
    };
    
    return (
        <div className="p-6 space-y-4">
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-bold">Devices</h1>
                <div className="flex gap-2">
                    <Input
                        placeholder="Search devices…"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        className="w-64"
                    />
                    {selectedIds.length > 0 && (
                        <>
                            <Button variant="outline" onClick={handleBulkReboot}>
                                Reboot ({selectedIds.length})
                            </Button>
                            <Button
                                variant="destructive"
                                onClick={() => bulkMutation.mutate({
                                    device_ids: selectedIds,
                                    action: 'vpn_revoke',
                                })}
                            >
                                Revoke VPN ({selectedIds.length})
                            </Button>
                        </>
                    )}
                </div>
            </div>
            
            <div className="rounded-md border">
                <Table>
                    <TableHeader>
                        {table.getHeaderGroups().map(hg => (
                            <TableRow key={hg.id}>
                                {hg.headers.map(h => (
                                    <TableHead key={h.id}>
                                        {flexRender(h.column.columnDef.header, h.getContext())}
                                    </TableHead>
                                ))}
                            </TableRow>
                        ))}
                    </TableHeader>
                    <TableBody>
                        {isLoading ? (
                            <TableRow>
                                <TableCell colSpan={columns.length} className="text-center py-10">
                                    Loading…
                                </TableCell>
                            </TableRow>
                        ) : table.getRowModel().rows.map(row => (
                            <TableRow key={row.id} data-state={row.getIsSelected() ? 'selected' : undefined}>
                                {row.getVisibleCells().map(cell => (
                                    <TableCell key={cell.id}>
                                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                    </TableCell>
                                ))}
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </div>
            
            <div className="flex items-center justify-between text-sm text-muted-foreground">
                <span>{data?.total ?? 0} total devices</span>
                <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}>
                        Previous
                    </Button>
                    <span className="self-center">Page {page}</span>
                    <Button variant="outline" size="sm" onClick={() => setPage(p => p + 1)} disabled={(data?.total ?? 0) <= page * 50}>
                        Next
                    </Button>
                </div>
            </div>
        </div>
    );
}
```

---

## Критерии готовности

- [ ] React Query `refetchInterval=30s` — auto-refresh без ручного обновления
- [ ] Bulk selection через TanStack Table RowSelectionState
- [ ] Bulk Reboot/Revoke VPN кнопки появляются только при выбранных устройствах
- [ ] Battery < 20% — красный цвет
- [ ] `staleTime=15s` — не делает лишних запросов при быстрой навигации
- [ ] `isLoading` показывает loading state в таблице
