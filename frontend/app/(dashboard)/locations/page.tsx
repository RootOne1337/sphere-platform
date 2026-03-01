'use client';

import { useState } from 'react';
import { useLocations, useCreateLocation, useUpdateLocation, useDeleteLocation } from '@/lib/hooks/useLocations';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Plus, Trash2, MapPin, Pencil } from 'lucide-react';

export default function LocationsPage() {
  const { data: locations, isLoading } = useLocations();
  const createLocation = useCreateLocation();
  const updateLocation = useUpdateLocation();
  const deleteLocation = useDeleteLocation();

  const [createDialog, setCreateDialog] = useState(false);
  const [editDialog, setEditDialog] = useState<{ open: boolean; id: string }>({ open: false, id: '' });

  // Форма создания
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState('#3B82F6');
  const [address, setAddress] = useState('');

  // Форма редактирования
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editColor, setEditColor] = useState('#3B82F6');
  const [editAddress, setEditAddress] = useState('');

  const handleCreate = async () => {
    await createLocation.mutateAsync({
      name,
      description: description || undefined,
      color,
      address: address || undefined,
    });
    setName('');
    setDescription('');
    setAddress('');
    setCreateDialog(false);
  };

  const openEdit = (loc: { id: string; name: string; description: string | null; color: string | null; address: string | null }) => {
    setEditName(loc.name);
    setEditDescription(loc.description ?? '');
    setEditColor(loc.color ?? '#3B82F6');
    setEditAddress(loc.address ?? '');
    setEditDialog({ open: true, id: loc.id });
  };

  const handleUpdate = async () => {
    await updateLocation.mutateAsync({
      id: editDialog.id,
      name: editName,
      description: editDescription || undefined,
      color: editColor,
      address: editAddress || undefined,
    });
    setEditDialog({ open: false, id: '' });
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Locations</h1>
        <Dialog open={createDialog} onOpenChange={setCreateDialog}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="w-4 h-4 mr-2" />
              New Location
            </Button>
          </DialogTrigger>
          <DialogContent aria-describedby={undefined}>
            <DialogHeader>
              <DialogTitle>Создать локацию</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 pt-2">
              <div className="space-y-1">
                <Label>Название</Label>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Дата-Центр #1" />
              </div>
              <div className="space-y-1">
                <Label>Описание</Label>
                <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Серверная комната, 3 этаж" />
              </div>
              <div className="space-y-1">
                <Label>Адрес</Label>
                <Input value={address} onChange={(e) => setAddress(e.target.value)} placeholder="ул. Примерная 42" />
              </div>
              <div className="space-y-1">
                <Label>Цвет</Label>
                <div className="flex gap-2 items-center">
                  <input type="color" value={color} onChange={(e) => setColor(e.target.value)} className="w-8 h-8 rounded cursor-pointer" />
                  <span className="text-sm text-muted-foreground">{color}</span>
                </div>
              </div>
              <Button onClick={handleCreate} disabled={createLocation.isPending || !name} className="w-full">
                {createLocation.isPending ? 'Создание…' : 'Создать'}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {isLoading ? (
        <p className="text-muted-foreground text-sm">Загрузка…</p>
      ) : !locations || locations.length === 0 ? (
        <div className="text-center py-12 text-muted-foreground">
          <MapPin className="w-12 h-12 mx-auto mb-3 opacity-50" />
          <p>Локаций пока нет. Создай первую локацию для организации устройств.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {locations.map((loc) => (
            <div
              key={loc.id}
              className="rounded-lg border p-4 hover:bg-accent/50 transition-colors"
              style={{ borderLeftColor: loc.color ?? undefined, borderLeftWidth: loc.color ? 4 : undefined }}
            >
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="font-semibold">{loc.name}</h3>
                  {loc.address && (
                    <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1">
                      <MapPin className="w-3 h-3" /> {loc.address}
                    </p>
                  )}
                  {loc.description && (
                    <p className="text-xs text-muted-foreground mt-1">{loc.description}</p>
                  )}
                </div>
                <div className="flex gap-1">
                  <Button
                    size="icon"
                    variant="ghost"
                    className="text-muted-foreground hover:text-primary h-7 w-7"
                    onClick={() => openEdit(loc)}
                  >
                    <Pencil className="w-4 h-4" />
                  </Button>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="text-red-400 hover:text-red-300 h-7 w-7"
                    onClick={() => {
                      if (confirm(`Удалить локацию "${loc.name}"?`)) deleteLocation.mutate(loc.id);
                    }}
                  >
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </div>
              </div>
              <div className="flex gap-2 mt-3">
                <Badge variant="outline">
                  {loc.total_devices} устройств
                </Badge>
                <Badge variant="outline" className="text-green-400 border-green-600">
                  {loc.online_devices} онлайн
                </Badge>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Диалог редактирования */}
      <Dialog open={editDialog.open} onOpenChange={(open) => { if (!open) setEditDialog({ open: false, id: '' }); }}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Редактировать локацию</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            <div className="space-y-1">
              <Label>Название</Label>
              <Input value={editName} onChange={(e) => setEditName(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Описание</Label>
              <Input value={editDescription} onChange={(e) => setEditDescription(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Адрес</Label>
              <Input value={editAddress} onChange={(e) => setEditAddress(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label>Цвет</Label>
              <div className="flex gap-2 items-center">
                <input type="color" value={editColor} onChange={(e) => setEditColor(e.target.value)} className="w-8 h-8 rounded cursor-pointer" />
                <span className="text-sm text-muted-foreground">{editColor}</span>
              </div>
            </div>
            <Button onClick={handleUpdate} disabled={updateLocation.isPending || !editName} className="w-full">
              {updateLocation.isPending ? 'Сохранение…' : 'Сохранить'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
