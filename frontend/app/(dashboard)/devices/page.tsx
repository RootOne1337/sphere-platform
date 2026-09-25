'use client';

import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { RowSelectionState } from '@tanstack/react-table';
import { useDevices, useBulkAction, useDeleteDevice, useUpdateDevice, useBulkDeleteDevices, type Device } from '@/lib/hooks/useDevices';
import { useBulkRevokeVpn } from '@/lib/hooks/useVpn';
import { getApiErrorMessage } from '@/lib/apiError';
import { useDebounce } from '@/lib/hooks/useDebounce';
import { useGroups, useMoveDevices } from '@/lib/hooks/useGroups';
import { useLocations, useAssignDevicesToLocation } from '@/lib/hooks/useLocations';
import { FleetMatrix, type DeviceAction } from '@/src/features/devices/FleetMatrix';
import { MultiStreamGrid } from '@/src/features/devices/MultiStreamGrid';
import { DeviceBulkDeleteButton } from '@/src/features/devices/DeviceBulkDeleteButton';
import { DeviceDeleteConfirmationDialog } from '@/src/features/devices/DeviceDeleteConfirmationDialog';
import { MAX_BULK_DEVICE_OPERATION_COUNT } from '@/src/features/devices/constants';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
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
import { AlertTriangle, Cpu, Filter, FolderOpen, LayoutGrid, List, Loader2, MapPin, Pencil, RefreshCcw, Search, Server, ShieldOff, Wifi, WifiOff } from 'lucide-react';
import { useGameServers } from '@/lib/hooks/usePipelineSettings';
import { toast } from 'sonner';

type DeviceActionFailure = { device_id: string; error: string | null };

function formatDeviceFailures(failures: DeviceActionFailure[], devices: Device[]): string {
  const examples = failures.slice(0, 3).map((failure) => {
    const label = devices.find((device) => device.id === failure.device_id)?.name ?? failure.device_id.slice(0, 8);
    const reason = failure.error?.replace(/\s+/g, ' ').slice(0, 160) || 'причина не указана';
    return `${label}: ${reason}`;
  });
  const remainder = failures.length > examples.length ? `; и ещё ${failures.length - examples.length}` : '';
  return examples.length ? `${examples.join('; ')}${remainder}.` : '';
}

export default function DevicesPage() {
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebounce(search, 300);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [viewMode, setViewMode] = useState<'table' | 'grid'>('table');

  // Диалоги
  const [renameDialog, setRenameDialog] = useState<{ open: boolean; deviceId: string; currentName: string }>({ open: false, deviceId: '', currentName: '' });
  const [singleDeleteDialog, setSingleDeleteDialog] = useState<{ deviceId: string; deviceName: string } | null>(null);
  const [singleDeleteError, setSingleDeleteError] = useState<string | null>(null);
  const singleDeleteLock = useRef(false);
  const [vpnRevokeConfirmationOpen, setVpnRevokeConfirmationOpen] = useState(false);
  const [vpnRevokeError, setVpnRevokeError] = useState<string | null>(null);
  const [newName, setNewName] = useState('');
  const [assignGroupDialog, setAssignGroupDialog] = useState(false);
  const [assignLocationDialog, setAssignLocationDialog] = useState(false);
  const [assignServerDialog, setAssignServerDialog] = useState<{ open: boolean; deviceId: string; currentServer: string | null }>({
    open: false, deviceId: '', currentServer: null,
  });
  const [selectedServerName, setSelectedServerName] = useState<string>('');
  const [selectedGroupId, setSelectedGroupId] = useState<string>('');
  const [selectedLocationId, setSelectedLocationId] = useState<string>('');

  // Фильтры по группе и локации
  const [filterGroupId, setFilterGroupId] = useState<string>('');
  const [filterLocationId, setFilterLocationId] = useState<string>('');

  // Backend поддерживает до 5000 — запрашиваем все устройства одной страницей
  const { data, isLoading, isFetching, isError: devicesLoadError, error: devicesError, refetch } = useDevices({
    page: 1,
    page_size: 5000,
    search: debouncedSearch || undefined,
  });
  const bulkMutation = useBulkAction();
  const deleteDevice = useDeleteDevice();
  const bulkDelete = useBulkDeleteDevices();
  const bulkRevokeVpn = useBulkRevokeVpn();
  const updateDevice = useUpdateDevice();
  const { data: groups, isLoading: groupsLoading, isError: groupsLoadError, refetch: refetchGroups } = useGroups();
  const { data: locations, isLoading: locationsLoading, isError: locationsLoadError, refetch: refetchLocations } = useLocations();
  const moveDevices = useMoveDevices();
  const assignToLocation = useAssignDevicesToLocation();
  const { data: gameServers } = useGameServers();

  // Клиентская фильтрация по группе и локации
  const filteredItems = useMemo(() => {
    let items = data?.items ?? [];
    if (filterGroupId && filterGroupId !== '__all__') {
      items = items.filter(
        (d) => d.group_id === filterGroupId || d.group_ids?.includes(filterGroupId),
      );
    }
    if (filterLocationId && filterLocationId !== '__all__') {
      items = items.filter((d) => d.location_ids?.includes(filterLocationId));
    }
    return items;
  }, [data?.items, filterGroupId, filterLocationId]);

  const visibleDeviceIds = useMemo(() => new Set(filteredItems.map((device) => device.id)), [filteredItems]);
  const selectedIds = Object.entries(rowSelection)
    .filter(([deviceId, selected]) => selected && visibleDeviceIds.has(deviceId))
    .map(([deviceId]) => deviceId);

  // Selection is scoped to the currently visible result set. A filter/search change
  // must not leave hidden devices queued for a destructive or operational action.
  useEffect(() => {
    setRowSelection((current) => {
      const next = Object.fromEntries(
        Object.entries(current).filter(([deviceId, selected]) => selected && visibleDeviceIds.has(deviceId)),
      );
      return Object.keys(next).length === Object.keys(current).length ? current : next;
    });
  }, [visibleDeviceIds]);

  const exceedsBulkLimit = selectedIds.length > MAX_BULK_DEVICE_OPERATION_COUNT;

  const statusCounts = useMemo(() => ({
    online: filteredItems.filter((device) => device.status === 'online').length,
    offline: filteredItems.filter((device) => device.status === 'offline').length,
    issues: filteredItems.filter((device) => device.status === 'error' || device.status === 'unknown').length,
  }), [filteredItems]);

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
      case 'assign_server':
        setAssignServerDialog({ open: true, deviceId: device.id, currentServer: device.server_name });
        setSelectedServerName(device.server_name ?? '');
        break;
      case 'delete':
        setSingleDeleteError(null);
        setSingleDeleteDialog({ deviceId: device.id, deviceName: device.name });
        break;
    }
  }, [data?.items]);

  const handleSingleDelete = async () => {
    const target = singleDeleteDialog;
    if (!target || deleteDevice.isPending || singleDeleteLock.current) return;

    singleDeleteLock.current = true;
    setSingleDeleteError(null);
    try {
      await deleteDevice.mutateAsync(target.deviceId);
      setSingleDeleteDialog(null);
      toast.success(`Устройство «${target.deviceName}» удалено из каталога`);
    } catch (error) {
      const message = getApiErrorMessage(
        error,
        'Проверьте права доступа и соединение с сервером. Запись не подтверждена как удалённая.',
      );
      setSingleDeleteError(message);
      toast.error('Не удалось удалить устройство', { description: message });
    } finally {
      singleDeleteLock.current = false;
    }
  };

  const handleBulkReboot = async () => {
    const deviceIds = [...selectedIds];
    if (deviceIds.length === 0 || deviceIds.length > MAX_BULK_DEVICE_OPERATION_COUNT || bulkMutation.isPending) return;
    try {
      const result = await bulkMutation.mutateAsync({ device_ids: deviceIds, action: 'reboot' });
      const failures = result.results.filter((item) => !item.success);
      const failedIds = failures.map((item) => item.device_id);
      if (failedIds.length === 0) {
        setRowSelection({});
        toast.success(`Команду перезапуска подтвердили ${result.succeeded} устройств`);
      } else {
        setRowSelection(Object.fromEntries(failedIds.map((deviceId) => [deviceId, true])));
        toast.warning(`Не подтверждены команды: ${failedIds.length} из ${result.total}`, {
          description: `${formatDeviceFailures(failures, data?.items ?? [])} Выделение оставлено только на устройствах с ошибкой.`,
        });
      }
    } catch (error) {
      toast.error('Не удалось отправить команды перезапуска', {
        description: getApiErrorMessage(error, 'Проверьте связь с сервером. Выделение сохранено.'),
      });
    }
  };

  const handleBulkRevokeVpn = async () => {
    const deviceIds = [...selectedIds];
    if (deviceIds.length === 0 || deviceIds.length > MAX_BULK_DEVICE_OPERATION_COUNT || bulkRevokeVpn.isPending) return;
    setVpnRevokeError(null);
    try {
      const result = await bulkRevokeVpn.mutateAsync(deviceIds);
      const failures = result.results.filter((item) => !item.success);
      const failedIds = failures.map((item) => item.device_id);
      if (failedIds.length === 0) {
        setRowSelection({});
        setVpnRevokeConfirmationOpen(false);
        toast.success(`VPN отозван у ${result.succeeded} устройств`);
      } else {
        setRowSelection(Object.fromEntries(failedIds.map((deviceId) => [deviceId, true])));
        setVpnRevokeConfirmationOpen(false);
        toast.warning(`Не отозван VPN у ${failedIds.length} из ${result.total} устройств`, {
          description: `${formatDeviceFailures(failures, data?.items ?? [])} Выделение оставлено только на устройствах с ошибкой.`,
        });
      }
    } catch (error) {
      const message = getApiErrorMessage(error, 'Проверьте права доступа и соединение с сервером. Выделение сохранено.');
      setVpnRevokeError(message);
      toast.error('Не удалось выполнить отзыв VPN', {
        description: message,
      });
    }
  };

  const handleRename = async () => {
    if (!newName.trim()) return;
    try {
      await updateDevice.mutateAsync({ id: renameDialog.deviceId, name: newName.trim() });
      setRenameDialog({ open: false, deviceId: '', currentName: '' });
      setNewName('');
      toast.success('Устройство переименовано');
    } catch (error) {
      toast.error('Не удалось переименовать устройство', {
        description: getApiErrorMessage(error, 'Проверьте права доступа и повторите попытку.'),
      });
    }
  };

  const handleAssignGroup = async () => {
    if (!selectedGroupId || selectedIds.length === 0 || exceedsBulkLimit) return;
    try {
      const requestedIds = [...selectedIds];
      const result = await moveDevices.mutateAsync({ groupId: selectedGroupId, deviceIds: requestedIds });
      if (result.moved === requestedIds.length) {
        setAssignGroupDialog(false);
        setSelectedGroupId('');
        setRowSelection({});
        toast.success(`В группу назначено устройств: ${result.moved}`);
      } else {
        toast.warning('Группа назначена частично', {
          description: `Сервер обработал ${result.moved} из ${requestedIds.length} устройств. Выделение сохранено для проверки.`,
        });
      }
    } catch (error) {
      toast.error('Не удалось назначить группу', {
        description: getApiErrorMessage(error, 'Проверьте связь и доступ к группе.'),
      });
    }
  };

  const handleAssignLocation = async () => {
    if (!selectedLocationId || selectedIds.length === 0 || exceedsBulkLimit) return;
    try {
      const requestedIds = [...selectedIds];
      const result = await assignToLocation.mutateAsync({ locationId: selectedLocationId, deviceIds: requestedIds });
      setAssignLocationDialog(false);
      setSelectedLocationId('');
      setRowSelection({});
      toast.success(`Добавлено новых привязок к локации: ${result.assigned}`);
    } catch (error) {
      toast.error('Не удалось назначить локацию', {
        description: getApiErrorMessage(error, 'Проверьте связь и доступ к локации.'),
      });
    }
  };

  const handleAssignServer = async () => {
    try {
      await updateDevice.mutateAsync({
        id: assignServerDialog.deviceId,
        server_name: selectedServerName || null,
      });
      setAssignServerDialog({ open: false, deviceId: '', currentServer: null });
      toast.success('Игровой сервер обновлён');
    } catch (error) {
      toast.error('Не удалось обновить игровой сервер', {
        description: getApiErrorMessage(error, 'Проверьте права доступа и повторите попытку.'),
      });
    }
  };

  return (
    <div className="flex min-h-full flex-col gap-5 p-4 md:h-full md:min-h-0 md:p-6">
      <header className="shrink-0 space-y-5">
        <div className="flex flex-col gap-4 rounded-xl border border-border bg-card/70 p-5 shadow-sm md:flex-row md:items-center md:justify-between">
          <div className="min-w-0">
            <p className="mb-1 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">Операционный центр</p>
            <h1 className="flex items-center gap-3 text-2xl font-semibold tracking-tight text-foreground">
              <span className="flex h-10 w-10 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
                <Cpu className="h-5 w-5" aria-hidden="true" />
              </span>
              Fleet Matrix
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Устройства организации · показано {filteredItems.length} из {data?.total ?? 0}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div role="group" aria-label="Режим отображения устройств" className="inline-flex rounded-lg border border-border bg-background p-1">
              <Button
                type="button"
                variant={viewMode === 'table' ? 'secondary' : 'ghost'}
                size="icon"
                aria-label="Табличный вид"
                aria-pressed={viewMode === 'table'}
                title="Табличный вид"
                onClick={() => setViewMode('table')}
                className="h-9 w-9 rounded-md"
              >
                <List className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button
                type="button"
                variant={viewMode === 'grid' ? 'secondary' : 'ghost'}
                size="icon"
                aria-label="Сетка видеопотоков"
                aria-pressed={viewMode === 'grid'}
                title="Сетка видеопотоков"
                onClick={() => setViewMode('grid')}
                className="h-9 w-9 rounded-md"
              >
                <LayoutGrid className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
            <Button
              variant="outline"
              onClick={() => { void refetch(); }}
              disabled={isFetching}
              className="h-11 rounded-lg px-4"
              aria-live="polite"
            >
              <RefreshCcw className={`mr-2 h-4 w-4 ${isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
              {isFetching ? 'Обновление…' : 'Обновить список'}
            </Button>
          </div>
        </div>

        <section aria-label="Состояние устройств" className="grid grid-cols-2 gap-2 sm:gap-3 xl:grid-cols-4">
          {[
            { label: 'В каталоге', value: isLoading ? '—' : data?.total ?? 0, note: 'результат поиска', icon: Cpu, tone: 'text-primary' },
            { label: 'В сети', value: isLoading ? '—' : statusCounts.online, note: 'текущий статус API', icon: Wifi, tone: 'text-emerald-400' },
            { label: 'Не в сети', value: isLoading ? '—' : statusCounts.offline, note: 'нет активного heartbeat', icon: WifiOff, tone: 'text-muted-foreground' },
            { label: 'Требуют внимания', value: isLoading ? '—' : statusCounts.issues, note: 'ошибка или статус неизвестен', icon: AlertTriangle, tone: 'text-amber-400' },
          ].map(({ label, value, note, icon: Icon, tone }) => (
            <div key={label} className="rounded-xl border border-border bg-card p-3 transition-colors duration-150 hover:border-primary/30 motion-reduce:transition-none sm:p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-muted-foreground">{label}</p>
                <Icon className={`h-4 w-4 ${tone}`} aria-hidden="true" />
              </div>
              <p className={`mt-2 text-xl font-semibold tabular-nums sm:mt-3 sm:text-2xl ${tone}`} aria-live="polite">{value}</p>
              <p className="mt-1 hidden text-xs text-muted-foreground sm:block">{note}</p>
            </div>
          ))}
        </section>
      </header>

      <section aria-label="Устройства и операции" className="flex min-h-[28rem] flex-1 flex-col overflow-hidden rounded-xl border border-border bg-card shadow-sm md:min-h-0">
        <div className="shrink-0 space-y-3 border-b border-border p-4">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
            <div className="relative min-w-0 flex-1 xl:max-w-xl">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input
                aria-label="Поиск устройств"
                placeholder="Поиск по имени, модели или идентификатору"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-11 rounded-lg bg-background pl-9 font-sans text-sm placeholder:text-muted-foreground/70"
              />
            </div>

            <div className="grid grid-cols-2 gap-2 xl:ml-auto">
              <Select value={filterGroupId || '__all__'} onValueChange={setFilterGroupId}>
                <SelectTrigger aria-label="Фильтр по группе" className="h-11 w-full rounded-lg bg-background sm:w-[190px]">
                  <SelectValue placeholder="Все группы" />
                </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">Все группы</SelectItem>
                {groupsLoadError && !groups?.length && <SelectItem value="__groups_unavailable" disabled>Список групп недоступен</SelectItem>}
                {groupsLoading && <SelectItem value="__groups_loading" disabled>Загрузка групп…</SelectItem>}
                {groups?.map((g) => (
                    <SelectItem key={g.id} value={g.id}>
                      <span className="flex items-center gap-2">
                        {g.color && <span className="h-2 w-2 rounded-full" style={{ backgroundColor: g.color }} />}
                        {g.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select value={filterLocationId || '__all__'} onValueChange={setFilterLocationId}>
                <SelectTrigger aria-label="Фильтр по локации" className="h-11 w-full rounded-lg bg-background sm:w-[190px]">
                  <SelectValue placeholder="Все локации" />
                </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">Все локации</SelectItem>
                {locationsLoadError && !locations?.length && <SelectItem value="__locations_unavailable" disabled>Список локаций недоступен</SelectItem>}
                {locationsLoading && <SelectItem value="__locations_loading" disabled>Загрузка локаций…</SelectItem>}
                {locations?.map((l) => (
                    <SelectItem key={l.id} value={l.id}>
                      <span className="flex items-center gap-2">
                        {l.color && <span className="h-2 w-2 rounded-full" style={{ backgroundColor: l.color }} />}
                        {l.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {(filterGroupId && filterGroupId !== '__all__' || filterLocationId && filterLocationId !== '__all__') && (
                <Button
                  variant="ghost"
                  onClick={() => { setFilterGroupId('__all__'); setFilterLocationId('__all__'); }}
                  className="col-span-2 h-11 rounded-lg px-3 text-sm"
                >
                  <Filter className="mr-2 h-4 w-4" aria-hidden="true" /> Сбросить фильтры
                </Button>
              )}
            </div>
          </div>

          {devicesLoadError && (
            <div role="alert" className="flex flex-col gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
              <div className="flex min-w-0 items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" aria-hidden="true" />
                <div>
                  <p className="font-medium text-foreground">Не удалось загрузить актуальный список устройств</p>
                  <p className="mt-1 break-words text-muted-foreground">
                    {getApiErrorMessage(devicesError, 'Проверьте доступность сервера и повторите запрос.')}
                    {data ? ' Показаны последние полученные данные.' : ''}
                  </p>
                </div>
              </div>
              <Button variant="outline" size="sm" onClick={() => { void refetch(); }} disabled={isFetching} className="shrink-0">
                {isFetching ? 'Повтор…' : 'Повторить'}
              </Button>
            </div>
          )}
          {selectedIds.length > 0 && viewMode === 'table' && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 p-3" aria-live="polite">
              <span className="mr-1 inline-flex min-h-9 items-center rounded-md bg-primary/10 px-3 text-sm font-semibold text-primary">
                Выбрано: {selectedIds.length}
              </span>
              <Button variant="outline" size="sm" onClick={handleBulkReboot} disabled={bulkMutation.isPending || exceedsBulkLimit} className="h-9 rounded-md">
                <RefreshCcw className={`mr-2 h-4 w-4 ${bulkMutation.isPending ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />
                {bulkMutation.isPending ? 'Отправка…' : 'Перезапустить'}
              </Button>
            <Button variant="outline" size="sm" onClick={() => setAssignGroupDialog(true)} disabled={exceedsBulkLimit || !groups?.length} className="h-9 rounded-md">
                <FolderOpen className="mr-2 h-4 w-4" aria-hidden="true" /> Группа
              </Button>
              <Button variant="outline" size="sm" onClick={() => setAssignLocationDialog(true)} disabled={exceedsBulkLimit || !locations?.length} className="h-9 rounded-md">
                <MapPin className="mr-2 h-4 w-4" aria-hidden="true" /> Локация
              </Button>
              {selectedIds.length === 1 && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    const device = data?.items.find((item) => item.id === selectedIds[0]);
                    if (!device) return;
                    setRenameDialog({ open: true, deviceId: device.id, currentName: device.name });
                    setNewName(device.name);
                  }}
                  className="h-9 rounded-md"
                >
                  <Pencil className="mr-2 h-4 w-4" aria-hidden="true" /> Переименовать
                </Button>
              )}
              <Button
                variant="destructive"
                size="sm"
                onClick={() => {
                  setVpnRevokeError(null);
                  setVpnRevokeConfirmationOpen(true);
                }}
                disabled={bulkRevokeVpn.isPending || exceedsBulkLimit}
                className="h-9 rounded-md"
              >
                {bulkRevokeVpn.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <ShieldOff className="mr-2 h-4 w-4" aria-hidden="true" />}
                {bulkRevokeVpn.isPending ? 'Отзываем VPN…' : 'Отозвать VPN'}
              </Button>
              <DeviceBulkDeleteButton
                deviceIds={selectedIds}
                isPending={bulkDelete.isPending}
                onDelete={bulkDelete.mutateAsync}
                onDeleted={() => setRowSelection({})}
              />
              {exceedsBulkLimit && (
                <p role="alert" className="basis-full text-sm text-amber-700 dark:text-amber-300">
                  Массовая операция принимает до {MAX_BULK_DEVICE_OPERATION_COUNT} устройств за запрос. Уменьшите выделение.
                </p>
              )}
            </div>
          )}
        </div>

        <div className="flex min-h-0 flex-1 flex-col p-3 md:p-4">
          {!data && devicesLoadError ? (
            <div className="flex min-h-64 flex-1 flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-destructive/40 bg-destructive/5 p-6 text-center">
              <AlertTriangle className="h-8 w-8 text-destructive" aria-hidden="true" />
              <div>
                <h2 className="font-semibold text-foreground">Реестр временно недоступен</h2>
                <p className="mt-1 max-w-md text-sm text-muted-foreground">Данные устройств не получены; пустой список не означает, что устройств нет.</p>
              </div>
              <Button variant="outline" onClick={() => { void refetch(); }} disabled={isFetching}>
                {isFetching ? 'Повтор…' : 'Повторить загрузку'}
              </Button>
            </div>
          ) : viewMode === 'table' ? (
            <FleetMatrix
              data={filteredItems}
              isLoading={isLoading}
              rowSelection={rowSelection}
              onRowSelectionChange={setRowSelection}
              onDeviceAction={handleDeviceAction}
            />
          ) : (
            <MultiStreamGrid devices={filteredItems} selectedIds={selectedIds} />
          )}
        </div>
      </section>

      {/* Диалог удаления одной записи */}
      <DeviceDeleteConfirmationDialog
        open={singleDeleteDialog !== null}
        title={singleDeleteDialog ? `Удалить «${singleDeleteDialog.deviceName}» из каталога?` : 'Удалить устройство из каталога?'}
        description="Будет удалена запись устройства из каталога Sphere. APK и приложения на Android останутся установленными; работающий агент может зарегистрироваться снова."
        confirmLabel="Удалить запись"
        pendingLabel="Удаление…"
        isPending={deleteDevice.isPending}
        errorMessage={singleDeleteError}
        onOpenChange={(open) => {
          if (open) return;
          setSingleDeleteDialog(null);
          setSingleDeleteError(null);
        }}
        onConfirm={() => { void handleSingleDelete(); }}
      />

      <Dialog
        open={vpnRevokeConfirmationOpen}
        onOpenChange={(open) => {
          if (!bulkRevokeVpn.isPending) setVpnRevokeConfirmationOpen(open);
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldOff className="h-5 w-5 text-destructive" aria-hidden="true" />
              Отозвать VPN у выбранных устройств?
            </DialogTitle>
            <DialogDescription>
              Будут отозваны VPN-пиры у {selectedIds.length} устройств в текущей организации. Записи устройств, APK и приложения на Android останутся без изменений.
            </DialogDescription>
          </DialogHeader>
          {vpnRevokeError && (
            <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {vpnRevokeError} Выделение сохранено.
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setVpnRevokeConfirmationOpen(false)}
              disabled={bulkRevokeVpn.isPending}
            >
              Отмена
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => { void handleBulkRevokeVpn(); }}
              disabled={bulkRevokeVpn.isPending || selectedIds.length === 0 || exceedsBulkLimit}
              aria-busy={bulkRevokeVpn.isPending}
            >
              {bulkRevokeVpn.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <ShieldOff className="mr-2 h-4 w-4" aria-hidden="true" />}
              {bulkRevokeVpn.isPending ? 'Отзываем VPN…' : `Отозвать VPN (${selectedIds.length})`}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
            {groupsLoadError && (
              <p role="alert" className="text-sm text-destructive">
                Не удалось обновить список групп. {groups?.length ? 'Доступны ранее загруженные значения.' : 'Назначение группы временно недоступно.'}
                {' '}<button type="button" className="underline underline-offset-2" onClick={() => { void refetchGroups(); }}>Повторить</button>
              </p>
            )}
            <div className="space-y-1">
              <Label htmlFor="fleet-bulk-group">Группа</Label>
              <Select value={selectedGroupId} onValueChange={setSelectedGroupId}>
                <SelectTrigger id="fleet-bulk-group">
                  <SelectValue placeholder="Выбери группу" />
                </SelectTrigger>
                <SelectContent>
                  {groupsLoading && <SelectItem value="__groups_loading" disabled>Загрузка групп…</SelectItem>}
                  {groupsLoadError && !groups?.length && <SelectItem value="__groups_unavailable" disabled>Список групп недоступен</SelectItem>}
                  {!groupsLoading && !groupsLoadError && !groups?.length && <SelectItem value="__groups_empty" disabled>Групп пока нет</SelectItem>}
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
            <Button onClick={handleAssignGroup} disabled={moveDevices.isPending || !selectedGroupId || selectedIds.length === 0 || exceedsBulkLimit || !groups?.length} className="w-full">
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
            {locationsLoadError && (
              <p role="alert" className="text-sm text-destructive">
                Не удалось обновить список локаций. {locations?.length ? 'Доступны ранее загруженные значения.' : 'Назначение локации временно недоступно.'}
                {' '}<button type="button" className="underline underline-offset-2" onClick={() => { void refetchLocations(); }}>Повторить</button>
              </p>
            )}
            <div className="space-y-1">
              <Label htmlFor="fleet-bulk-location">Локация</Label>
              <Select value={selectedLocationId} onValueChange={setSelectedLocationId}>
                <SelectTrigger id="fleet-bulk-location">
                  <SelectValue placeholder="Выбери локацию" />
                </SelectTrigger>
                <SelectContent>
                  {locationsLoading && <SelectItem value="__locations_loading" disabled>Загрузка локаций…</SelectItem>}
                  {locationsLoadError && !locations?.length && <SelectItem value="__locations_unavailable" disabled>Список локаций недоступен</SelectItem>}
                  {!locationsLoading && !locationsLoadError && !locations?.length && <SelectItem value="__locations_empty" disabled>Локаций пока нет</SelectItem>}
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
            <Button onClick={handleAssignLocation} disabled={assignToLocation.isPending || !selectedLocationId || selectedIds.length === 0 || exceedsBulkLimit || !locations?.length} className="w-full">
              {assignToLocation.isPending ? 'Назначение…' : 'Назначить'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* Диалог назначения игрового сервера */}
      <Dialog
        open={assignServerDialog.open}
        onOpenChange={(open) => {
          if (!open) setAssignServerDialog({ open: false, deviceId: '', currentServer: null });
        }}
      >
        <DialogContent aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Server className="w-4 h-4" />
              Назначить игровой сервер
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="space-y-1">
              <Label>Сервер Black Russia</Label>
              <Select value={selectedServerName || '__none__'} onValueChange={(v) => setSelectedServerName(v === '__none__' ? '' : v)}>
                <SelectTrigger>
                  <SelectValue placeholder="Выбери сервер" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">— Снять привязку —</SelectItem>
                  {gameServers?.map((s) => (
                    <SelectItem key={s.id} value={s.name}>
                      #{s.id} {s.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {assignServerDialog.currentServer && (
              <p className="text-xs text-muted-foreground">
                Текущий сервер: <span className="text-foreground font-mono">{assignServerDialog.currentServer}</span>
              </p>
            )}
            <Button
              onClick={handleAssignServer}
              disabled={updateDevice.isPending}
              className="w-full"
            >
              {updateDevice.isPending ? 'Сохранение…' : 'Сохранить'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
