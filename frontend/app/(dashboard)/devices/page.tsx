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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
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
        {row.original.tags.map((tag) => (
          <Badge key={tag} variant="outline" className="text-xs">
            {tag}
          </Badge>
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
      return <span className={lvl < 20 ? 'text-red-500' : ''}>{lvl}%</span>;
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

  // FIX 10.2: сбрасываем выделение при смене страницы
  useEffect(() => {
    setRowSelection({});
  }, [page]);

  const { data, isLoading } = useDevices({
    page,
    page_size: 50,
    search: search || undefined,
  });
  const bulkMutation = useBulkAction();

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    state: { rowSelection },
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    // FIX 10.2: стабильные ID (row.id), не array index
    getRowId: (row) => row.id,
  });

  // FIX 10.2: rowSelection использует стабильные device.id
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
            onChange={(e) => setSearch(e.target.value)}
            className="w-64"
          />
          {selectedIds.length > 0 && (
            <>
              <Button variant="outline" onClick={handleBulkReboot}>
                Reboot ({selectedIds.length})
              </Button>
              <Button
                variant="destructive"
                onClick={() =>
                  bulkMutation.mutate({
                    device_ids: selectedIds,
                    action: 'vpn_revoke',
                  })
                }
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
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id}>
                {hg.headers.map((h) => (
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
            ) : (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-state={row.getIsSelected() ? 'selected' : undefined}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>{data?.total ?? 0} total devices</span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
          >
            Previous
          </Button>
          <span className="self-center">Page {page}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setPage((p) => p + 1)}
            disabled={(data?.total ?? 0) <= page * 50}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
