'use client';

import { useState } from 'react';
import { useLocations, useCreateLocation, useUpdateLocation, useDeleteLocation } from '@/lib/hooks/useLocations';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { AlertTriangle, MapPin, Pencil, Plus, Trash2, Wifi } from 'lucide-react';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';
import type { Location } from '@/lib/hooks/useLocations';

function LocationFields({
  name,
  setName,
  description,
  setDescription,
  address,
  setAddress,
  color,
  setColor,
  prefix,
}: {
  name: string;
  setName: (value: string) => void;
  description: string;
  setDescription: (value: string) => void;
  address: string;
  setAddress: (value: string) => void;
  color: string;
  setColor: (value: string) => void;
  prefix: string;
}) {
  return (
    <div className="space-y-4 pt-2">
      <div className="space-y-2"><Label htmlFor={`${prefix}-name`}>Название</Label><Input id={`${prefix}-name`} value={name} onChange={(event) => setName(event.target.value)} autoComplete="off" /></div>
      <div className="space-y-2"><Label htmlFor={`${prefix}-description`}>Описание <span className="font-normal text-muted-foreground">· необязательно</span></Label><Input id={`${prefix}-description`} value={description} onChange={(event) => setDescription(event.target.value)} /></div>
      <div className="space-y-2"><Label htmlFor={`${prefix}-address`}>Адрес</Label><Input id={`${prefix}-address`} value={address} onChange={(event) => setAddress(event.target.value)} placeholder="Город, дата-центр или площадка" /></div>
      <div className="space-y-2">
        <Label htmlFor={`${prefix}-color`}>Цвет метки</Label>
        <div className="flex items-center gap-3 rounded-lg border border-border p-2.5"><input id={`${prefix}-color`} type="color" value={color} onChange={(event) => setColor(event.target.value)} className="h-9 w-11 cursor-pointer rounded border-0 bg-transparent p-0" /><span className="font-mono text-sm text-muted-foreground">{color.toUpperCase()}</span></div>
      </div>
    </div>
  );
}

export default function LocationsPage() {
  const { data: locations, isLoading, isError, refetch } = useLocations();
  const createLocation = useCreateLocation();
  const updateLocation = useUpdateLocation();
  const deleteLocation = useDeleteLocation();
  const [createDialog, setCreateDialog] = useState(false);
  const [editDialog, setEditDialog] = useState<{ open: boolean; id: string }>({ open: false, id: '' });
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState('#3B82F6');
  const [address, setAddress] = useState('');
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editColor, setEditColor] = useState('#3B82F6');
  const [editAddress, setEditAddress] = useState('');

  const handleCreate = async () => {
    try {
      await createLocation.mutateAsync({ name: name.trim(), description: description.trim() || undefined, color, address: address.trim() || undefined });
      setName(''); setDescription(''); setAddress(''); setCreateDialog(false);
    } catch {
      // Preserve form values so the user can recover without retyping.
    }
  };

  const openEdit = (location: Location) => {
    setEditName(location.name);
    setEditDescription(location.description ?? '');
    setEditColor(location.color ?? '#3B82F6');
    setEditAddress(location.address ?? '');
    setEditDialog({ open: true, id: location.id });
  };

  const handleUpdate = async () => {
    try {
      await updateLocation.mutateAsync({ id: editDialog.id, name: editName.trim(), description: editDescription.trim(), color: editColor, address: editAddress.trim() });
      setEditDialog({ open: false, id: '' });
    } catch {
      // Keep the edit dialog open and show the mutation error.
    }
  };

  return (
    <PageFrame>
      <PageHeading
        eyebrow="Топология устройств"
        title="Локации"
        description="Сгруппируйте парк по площадкам, дата-центрам и регионам; данные об устройствах остаются привязаны к их собственным идентификаторам."
        actions={(
          <Dialog open={createDialog} onOpenChange={setCreateDialog}>
            <DialogTrigger asChild><Button><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Создать локацию</Button></DialogTrigger>
            <DialogContent aria-describedby={undefined}>
              <DialogHeader><DialogTitle>Новая локация</DialogTitle></DialogHeader>
              <LocationFields name={name} setName={setName} description={description} setDescription={setDescription} address={address} setAddress={setAddress} color={color} setColor={setColor} prefix="create-location" />
              {createLocation.isError && <p role="alert" className="mt-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">Не удалось создать локацию. Проверьте данные и права доступа.</p>}
              <Button onClick={() => { void handleCreate(); }} disabled={createLocation.isPending || !name.trim()} className="mt-4 w-full">{createLocation.isPending ? 'Создаём…' : 'Создать локацию'}</Button>
            </DialogContent>
          </Dialog>
        )}
      />

      {(deleteLocation.isError || updateLocation.isError) && <div role="alert" className="flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />Операция не выполнена. Обновите данные и проверьте привязанные устройства.</div>}

      {isError ? (
        <Card><CardContent className="flex flex-col gap-3 p-6 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-medium">Не удалось загрузить локации</p><p className="mt-1 text-sm text-muted-foreground">Состояние данных не подтверждено сервером.</p></div><Button type="button" variant="outline" onClick={() => { void refetch(); }}>Повторить</Button></CardContent></Card>
      ) : isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Загрузка локаций" aria-busy="true">{Array.from({ length: 3 }, (_, index) => <div key={index} className="h-44 animate-pulse rounded-xl border border-border bg-card motion-reduce:animate-none" />)}</div>
      ) : !locations?.length ? (
        <Card><CardContent className="flex min-h-64 flex-col items-center justify-center p-8 text-center"><span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary"><MapPin className="h-6 w-6" aria-hidden="true" /></span><p className="mt-4 font-semibold">Локаций пока нет</p><p className="mt-1 max-w-md text-sm text-muted-foreground">Создайте площадку, чтобы видеть расположение устройств и фильтровать парк по регионам.</p><Button className="mt-5" onClick={() => setCreateDialog(true)}><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Создать локацию</Button></CardContent></Card>
      ) : (
        <section aria-label="Список локаций" className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {locations.map((location) => (
            <Card key={location.id} className="group relative overflow-hidden shadow-soft transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md motion-reduce:transition-none motion-reduce:hover:translate-y-0">
              <span className="absolute inset-y-0 left-0 w-1" style={{ backgroundColor: location.color ?? 'hsl(var(--primary))' }} aria-hidden="true" />
              <CardContent className="p-5 pl-6">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2"><MapPin className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" /><h2 className="truncate font-semibold tracking-tight">{location.name}</h2></div>
                    <p className="mt-2 min-h-5 truncate text-sm text-muted-foreground" title={location.address ?? undefined}>{location.address || 'Адрес не указан'}</p>
                    <p className="mt-1 min-h-10 text-sm leading-5 text-muted-foreground">{location.description || 'Описание не добавлено'}</p>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <Button type="button" size="icon" variant="ghost" className="h-9 w-9 text-muted-foreground hover:text-primary" aria-label={`Изменить локацию ${location.name}`} onClick={() => openEdit(location)}><Pencil className="h-4 w-4" aria-hidden="true" /></Button>
                    <Button type="button" size="icon" variant="ghost" className="h-9 w-9 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" aria-label={`Удалить локацию ${location.name}`} disabled={deleteLocation.isPending} onClick={() => { if (window.confirm(`Удалить локацию «${location.name}»?`)) deleteLocation.mutate(location.id); }}><Trash2 className="h-4 w-4" aria-hidden="true" /></Button>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2 border-t border-border/70 pt-4"><Badge variant="outline" className="rounded-full px-2.5">{location.total_devices} устройств</Badge><Badge variant="success" className="rounded-full px-2.5"><Wifi className="mr-1 h-3 w-3" aria-hidden="true" />{location.online_devices} онлайн</Badge></div>
              </CardContent>
            </Card>
          ))}
        </section>
      )}

      <Dialog open={editDialog.open} onOpenChange={(open) => { if (!open) setEditDialog({ open: false, id: '' }); }}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader><DialogTitle>Редактирование локации</DialogTitle></DialogHeader>
          <LocationFields name={editName} setName={setEditName} description={editDescription} setDescription={setEditDescription} address={editAddress} setAddress={setEditAddress} color={editColor} setColor={setEditColor} prefix="edit-location" />
          {updateLocation.isError && <p role="alert" className="mt-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">Не удалось сохранить изменения. Проверьте данные и повторите попытку.</p>}
          <Button onClick={() => { void handleUpdate(); }} disabled={updateLocation.isPending || !editName.trim()} className="mt-4 w-full">{updateLocation.isPending ? 'Сохраняем…' : 'Сохранить изменения'}</Button>
        </DialogContent>
      </Dialog>
    </PageFrame>
  );
}
