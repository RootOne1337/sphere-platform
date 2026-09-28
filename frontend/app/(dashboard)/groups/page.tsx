'use client';

import { useState } from 'react';
import { useGroups, useCreateGroup, useDeleteGroup } from '@/lib/hooks/useGroups';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { AlertTriangle, FolderOpen, Layers3, Plus, Trash2, Users, Wifi } from 'lucide-react';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';

export default function GroupsPage() {
  const { data: groups, isLoading, isError, refetch } = useGroups();
  const createGroup = useCreateGroup();
  const deleteGroup = useDeleteGroup();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState('#3B82F6');

  const handleCreate = async () => {
    try {
      await createGroup.mutateAsync({ name: name.trim(), description: description.trim() || undefined, color });
      setName('');
      setDescription('');
      setDialogOpen(false);
    } catch {
      // The mutation error is rendered in the dialog; keep the entered values for correction.
    }
  };

  return (
    <PageFrame>
      <PageHeading
        eyebrow="Организация парка"
        title="Группы устройств"
        description="Объединяйте устройства по назначению и следите за доступностью каждой группы."
        actions={(
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Создать группу</Button>
            </DialogTrigger>
            <DialogContent aria-describedby={undefined}>
              <DialogHeader><DialogTitle>Новая группа</DialogTitle></DialogHeader>
              <div className="space-y-4 pt-2">
                <div className="space-y-2"><Label htmlFor="group-name">Название</Label><Input id="group-name" value={name} onChange={(event) => setName(event.target.value)} autoComplete="off" /></div>
                <div className="space-y-2"><Label htmlFor="group-description">Описание <span className="font-normal text-muted-foreground">· необязательно</span></Label><Input id="group-description" value={description} onChange={(event) => setDescription(event.target.value)} /></div>
                <div className="space-y-2">
                  <Label htmlFor="group-color">Цвет метки</Label>
                  <div className="flex items-center gap-3 rounded-lg border border-border p-2.5">
                    <input id="group-color" type="color" value={color} onChange={(event) => setColor(event.target.value)} className="h-9 w-11 cursor-pointer rounded border-0 bg-transparent p-0" />
                    <span className="font-mono text-sm text-muted-foreground">{color.toUpperCase()}</span>
                  </div>
                </div>
                {createGroup.isError && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">Не удалось создать группу. Проверьте данные и права доступа.</p>}
                <Button onClick={() => { void handleCreate(); }} disabled={createGroup.isPending || !name.trim()} className="w-full">
                  {createGroup.isPending ? 'Создаём…' : 'Создать группу'}
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        )}
      />

      {deleteGroup.isError && <div role="alert" className="flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><AlertTriangle className="h-4 w-4 shrink-0" aria-hidden="true" />Не удалось удалить группу. Обновите данные и проверьте, не назначены ли на неё устройства.</div>}

      {isError ? (
        <Card><CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
          <div><p className="font-medium">Не удалось загрузить группы</p><p className="mt-1 text-sm text-muted-foreground">Состояние данных не подтверждено сервером.</p></div>
          <Button type="button" variant="outline" onClick={() => { void refetch(); }}>Повторить</Button>
        </CardContent></Card>
      ) : isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Загрузка групп" aria-busy="true">
          {Array.from({ length: 3 }, (_, index) => <div key={index} className="h-40 animate-pulse rounded-xl border border-border bg-card motion-reduce:animate-none" />)}
        </div>
      ) : !groups?.length ? (
        <Card><CardContent className="flex min-h-64 flex-col items-center justify-center p-8 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary/10 text-primary"><FolderOpen className="h-6 w-6" aria-hidden="true" /></span>
          <p className="mt-4 font-semibold">Групп пока нет</p><p className="mt-1 max-w-md text-sm text-muted-foreground">Создайте первую группу, чтобы разделить парк по локациям, задачам или профилям работы.</p>
          <Button className="mt-5" onClick={() => setDialogOpen(true)}><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Создать группу</Button>
        </CardContent></Card>
      ) : (
        <section aria-label="Список групп" className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {groups.map((group) => (
            <Card key={group.id} className="group relative overflow-hidden shadow-soft transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md motion-reduce:transition-none motion-reduce:hover:translate-y-0">
              <span className="absolute inset-y-0 left-0 w-1" style={{ backgroundColor: group.color ?? 'hsl(var(--primary))' }} aria-hidden="true" />
              <CardContent className="p-5 pl-6">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2"><Layers3 className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" /><h2 className="truncate font-semibold tracking-tight">{group.name}</h2></div>
                    <p className="mt-2 min-h-10 text-sm leading-5 text-muted-foreground">{group.description || 'Описание не добавлено'}</p>
                  </div>
                  <Button type="button" size="icon" variant="ghost" className="h-9 w-9 shrink-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" aria-label={`Удалить группу ${group.name}`} disabled={deleteGroup.isPending} onClick={() => { if (window.confirm(`Удалить группу «${group.name}»?`)) deleteGroup.mutate(group.id); }}>
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>
                <div className="mt-4 flex flex-wrap gap-2 border-t border-border/70 pt-4">
                  <Badge variant="outline" className="rounded-full px-2.5"><Users className="mr-1 h-3 w-3" aria-hidden="true" />{group.total_devices} устройств</Badge>
                  <Badge variant="success" className="rounded-full px-2.5"><Wifi className="mr-1 h-3 w-3" aria-hidden="true" />{group.online_devices} онлайн</Badge>
                </div>
              </CardContent>
            </Card>
          ))}
        </section>
      )}
    </PageFrame>
  );
}
