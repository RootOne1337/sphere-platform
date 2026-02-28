'use client';

import { useState, useEffect } from 'react';
import { RowSelectionState } from '@tanstack/react-table';
import { useDevices, useBulkAction } from '@/lib/hooks/useDevices';
import { FleetMatrix } from '@/src/features/devices/FleetMatrix';
import { MultiStreamGrid } from '@/src/features/devices/MultiStreamGrid';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/components/ui/input';
import { Cpu, RefreshCcw, ShieldOff, LayoutGrid, List } from 'lucide-react';

export default function DevicesPage() {
  const [search, setSearch] = useState('');
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [viewMode, setViewMode] = useState<'table' | 'grid'>('table');

  // For NOC scale we might want 1000 items per page or infinite loading
  const { data, isLoading, refetch } = useDevices({
    page: 1,
    page_size: 1000,
    search: search || undefined,
  });
  const bulkMutation = useBulkAction();

  const selectedIds = Object.keys(rowSelection).filter(Boolean);

  const handleBulkReboot = () => {
    bulkMutation.mutate({ device_ids: selectedIds, action: 'reboot' });
    setRowSelection({});
  };

  const handleBulkRevokeVpn = () => {
    bulkMutation.mutate({ device_ids: selectedIds, action: 'vpn_revoke' });
    setRowSelection({});
  };

  return (
    <div className="flex flex-col h-full p-6 space-y-4">
      {/* Header Area */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between shrink-0 gap-4">
        <div>
          <h1 className="text-xl font-bold font-mono tracking-widest text-primary flex items-center gap-2 uppercase">
            <Cpu className="w-5 h-5 text-primary" />
            Fleet_Matrix
          </h1>
          <p className="text-[11px] text-muted-foreground mt-1 uppercase tracking-wider font-mono">
            {data?.total ?? 0} Global Endpoints Registered
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">

          {/* View Toggles */}
          <div className="flex items-center p-1 bg-muted border border-border rounded-sm mr-2 select-none">
            <div
              onClick={() => setViewMode('table')}
              className={`p-1.5 rounded-sm cursor-pointer transition-colors ${viewMode === 'table' ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:text-foreground'}`}
              title="Data Grid View"
            >
              <List className="w-4 h-4" />
            </div>
            <div
              onClick={() => setViewMode('grid')}
              className={`p-1.5 rounded-sm cursor-pointer transition-colors ${viewMode === 'grid' ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:text-foreground'}`}
              title="Multi-Stream Grid (Select devices to monitor)"
            >
              <LayoutGrid className="w-4 h-4" />
            </div>
          </div>

          <Input
            placeholder="[ SEARCH IDENTIFIER ]"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full sm:w-[250px] lg:w-[300px] h-9 bg-card border-border font-mono text-xs rounded-sm focus-visible:ring-1 focus-visible:ring-primary focus-visible:border-primary placeholder:text-[#555]"
          />
          {selectedIds.length > 0 && viewMode === 'table' && (
            <div className="flex items-center gap-2 border-l border-border pl-2 ml-2">
              <span className="text-[10px] text-warning font-mono mr-1">
                {selectedIds.length} SEL
              </span>
              <Button variant="outline" size="sm" onClick={handleBulkReboot} className="h-9 hover:border-warning hover:text-warning" title="Reboot Selected">
                <RefreshCcw className="w-3.5 h-3.5 mr-1.5" />
                RBT
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={handleBulkRevokeVpn}
                className="h-9"
                title="Revoke VPN"
              >
                <ShieldOff className="w-3.5 h-3.5 mr-1.5" />
                NO_VPN
              </Button>
            </div>
          )}
          <Button variant="noc" onClick={() => refetch()} className="ml-2 h-9">
            SYNC
          </Button>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-hidden flex flex-col pt-2">
        {viewMode === 'table' ? (
          <FleetMatrix
            data={data?.items ?? []}
            isLoading={isLoading}
            rowSelection={rowSelection}
            onRowSelectionChange={setRowSelection}
          />
        ) : (
          <MultiStreamGrid
            devices={data?.items ?? []}
            selectedIds={selectedIds}
          />
        )}
      </div>
    </div>
  );
}
