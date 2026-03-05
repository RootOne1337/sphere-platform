'use client';

import { useState, useCallback } from 'react';
import { RowSelectionState } from '@tanstack/react-table';
import { useDevices, useBulkAction, useDeleteDevice, useUpdateDevice, useBulkDeleteDevices } from '@/lib/hooks/useDevices';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { useGroups, useMoveDevices } from '@/lib/hooks/useGroups';
import { useLocations, useAssignDevicesToLocation, useRemoveDevicesFromLocation } from '@/lib/hooks/useLocations';
import { FleetMatrix, type DeviceAction } from '@/src/features/devices/FleetMatrix';
import { MultiStreamGrid } from '@/src/features/devices/MultiStreamGrid';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Cpu, RefreshCcw, ShieldOff, LayoutGrid, List, Trash2, Pencil, MapPin, FolderOpen } from 'lucide-react';

export default function DevicesPage() {
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 300);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [viewMode, setViewMode] = useState<'table' | 'grid'>('table');

  // Диалоги
  const [renameDialog, setRenameDialog] = useState<{ open: boolean; deviceId: string; currentName: string }>({ open: false, deviceId: '', currentName: '' });
  const [newName, setNewName] = useState('');
  const [assignGroupDialog, setAssignGroupDialog] = useState(false);
  const [assignLocationDialog, setAssignLocationDialog] = useState(false);
  const [selectedGroupId, setSelectedGroupId] = useState<string>('');
  const [selectedLocationId, setSelectedLocationId] = useState<string>('');

  // Backend поддерживает до 5000 — запрашиваем все устройства одной страницей
  const { data, isLoading, refetch } = useDevices({
    page: 1,
    page_size: 5000,
    search: debouncedSearch || undefined,
  });
  const bulkMutation = useBulkAction();
  const deleteDevice = useDeleteDevice();
  const bulkDelete = useBulkDeleteDevices();
  const updateDevice = useUpdateDevice();
  const { data: groups } = useGroups();
  const { data: locations } = useLocations();
  const moveDevices = useMoveDevices();
  const assignToLocation = useAssignDevicesToLocation();

  const selectedIds = Object.keys(rowSelection).filter(Boolean);

  // Обработчик действий из контекстного меню FleetMatrix (для одного устройства)
  const handleDeviceAction = useCallback((deviceId: string, action: DeviceAction) => {
    const device = data?.items.find(d => d.id === deviceId);
    if (!device) return;

    switch (action) {
      case 'rename':
        setRenameDialog({ open: true, deviceId: device.id, currentName: device.name });
        setNewName(device.name);
        break;
      case 'assign_group':
        // Выбираем только одно устройство и открываем диалог
        setRowSelection({ [deviceId]: true });
        setAssignGroupDialog(true);
        break;
      case 'assign_location':
        setRowSelection({ [deviceId]: true });
        setAssignLocationDialog(true);
        break;
      case 'delete':
        if (confirm(`Удалить устройство "${device.name}"? Это действие необратимо.`)) {
          deleteDevice.mutate(deviceId);
        }
        break;
    }
  }, [data?.items, deleteDevice]);

  const handleBulkReboot = () => {
    bulkMutation.mutate({ device_ids: selectedIds, action: 'reboot' });
    setRowSelection({});
  };

  const handleBulkRevokeVpn = () => {
    bulkMutation.mutate({ device_ids: selectedIds, action: 'vpn_revoke' });
    setRowSelection({});
  };

  const handleBulkDelete = () => {
    if (!confirm(`Удалить ${selectedIds.length} устройств? Это действие необратимо.`)) return;
    bulkDelete.mutate(selectedIds);
    setRowSelection({});
  };

  const handleRename = async () => {
    if (!newName.trim()) return;
    await updateDevice.mutateAsync({ id: renameDialog.deviceId, name: newName.trim() });
    setRenameDialog({ open: false, deviceId: '', currentName: '' });
    setNewName('');
  };

  const handleAssignGroup = async () => {
    if (!selectedGroupId) return;
    await moveDevices.mutateAsync({ groupId: selectedGroupId, deviceIds: selectedIds });
    setAssignGroupDialog(false);
    setSelectedGroupId('');
    setRowSelection({});
  };

  const handleAssignLocation = async () => {
    if (!selectedLocationId) return;
    await assignToLocation.mutateAsync({ locationId: selectedLocationId, deviceIds: selectedIds });
    setAssignLocationDialog(false);
    setSelectedLocationId('');
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
              <Button variant="outline" size="sm" onClick={() => setAssignGroupDialog(true)} className="h-9 hover:border-primary hover:text-primary" title="Assign to Group">
                <FolderOpen className="w-3.5 h-3.5 mr-1.5" />
                GRP
              </Button>
              <Button variant="outline" size="sm" onClick={() => setAssignLocationDialog(true)} className="h-9 hover:border-primary hover:text-primary" title="Assign to Location">
                <MapPin className="w-3.5 h-3.5 mr-1.5" />
                LOC
              </Button>
              {selectedIds.length === 1 && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    const d = data?.items.find(d => d.id === selectedIds[0]);
                    if (d) {
                      setRenameDialog({ open: true, deviceId: d.id, currentName: d.name });
                      setNewName(d.name);
                    }
                  }}
                  className="h-9 hover:border-primary hover:text-primary"
                  title="Rename Device"
                >
                  <Pencil className="w-3.5 h-3.5 mr-1.5" />
                  REN
                </Button>
              )}
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
              <Button
                variant="destructive"
                size="sm"
                onClick={handleBulkDelete}
                className="h-9"
                title="Delete Selected"
              >
                <Trash2 className="w-3.5 h-3.5 mr-1.5" />
                DEL
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
            onDeviceAction={handleDeviceAction}
          />
        ) : (
          <MultiStreamGrid
            devices={data?.items ?? []}
            selectedIds={selectedIds}
          />
        )}
      </div>

      {/* Диалог переименования */}
      <Dialog open={renameDialog.open} onOpenChange={(open) => { if (!open) setRenameDialog({ open: false, deviceId: '', currentName: '' }); }}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Переименовать устройство</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="space-y-1">
              <Label>Новое имя</Label>
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleRename()}
                autoFocus
              />
            </div>
            <Button onClick={handleRename} disabled={updateDevice.isPending || !newName.trim()} className="w-full">
              {updateDevice.isPending ? 'Сохранение…' : 'Сохранить'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Диалог назначения группы */}
      <Dialog open={assignGroupDialog} onOpenChange={setAssignGroupDialog}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Назначить в группу</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="space-y-1">
              <Label>Группа</Label>
              <Select value={selectedGroupId} onValueChange={setSelectedGroupId}>
                <SelectTrigger>
                  <SelectValue placeholder="Выбери группу" />
                </SelectTrigger>
                <SelectContent>
                  {groups?.map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      <span className="flex items-center gap-2">
                        {g.color && <span className="w-3 h-3 rounded-full inline-block" style={{ backgroundColor: g.color }} />}
                        {g.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <p className="text-xs text-muted-foreground">{selectedIds.length} устройств будут назначены в группу</p>
            <Button onClick={handleAssignGroup} disabled={moveDevices.isPending || !selectedGroupId} className="w-full">
              {moveDevices.isPending ? 'Назначение…' : 'Назначить'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Диалог назначения локации */}
      <Dialog open={assignLocationDialog} onOpenChange={setAssignLocationDialog}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Назначить в локацию</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="space-y-1">
              <Label>Локация</Label>
              <Select value={selectedLocationId} onValueChange={setSelectedLocationId}>
                <SelectTrigger>
                  <SelectValue placeholder="Выбери локацию" />
                </SelectTrigger>
                <SelectContent>
                  {locations?.map((l) => (
                    <SelectItem key={l.id} value={l.id}>
                      <span className="flex items-center gap-2">
                        {l.color && <span className="w-3 h-3 rounded-full inline-block" style={{ backgroundColor: l.color }} />}
                        {l.name}
                        {l.address && <span className="text-muted-foreground text-xs ml-1">— {l.address}</span>}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <p className="text-xs text-muted-foreground">{selectedIds.length} устройств будут добавлены в локацию (аддитивно)</p>
            <Button onClick={handleAssignLocation} disabled={assignToLocation.isPending || !selectedLocationId} className="w-full">
              {assignToLocation.isPending ? 'Назначение…' : 'Назначить'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
