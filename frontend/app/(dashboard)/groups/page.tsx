'use client';

import { useState } from 'react';
import Link from 'next/link';
import { type Group, useGroups } from '@/lib/hooks/useGroups';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { FolderOpen, Layers3, Pencil, Plus, RefreshCw, Trash2, Users, Wifi } from 'lucide-react';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';
import { GroupEditor } from '@/src/features/groups/GroupEditor';
import { GroupDeleteDialog } from '@/src/features/groups/GroupDeleteDialog';
import { PermissionNotice, useCapabilities } from '@/src/features/access/Capabilities';

export default function GroupsPage() {
  const access = useCapabilities();
  const canWrite = access.can('device:write');
  const canDelete = access.can('device:delete');
  const { data: groups, isLoading, isError, isFetching, refetch } = useGroups();
  const [editor, setEditor] = useState<{ group: Group | null } | null>(null);
  const [deleting, setDeleting] = useState<Group | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const available = !isError && !isLoading && groups !== undefined;
  const exists = (group: Group | null) => available && (!group || groups?.some((item) => item.id === group.id) === true);
  function openEditor(group: Group | null) { if (!canWrite || !exists(group)) return; setNotice(null); setEditor({ group }); }
  function openDeletion(group: Group) { if (!canDelete || !exists(group)) return; setNotice(null); setDeleting(group); }

  return (
    <PageFrame>
      <PageHeading eyebrow="Организация парка" title="Группы устройств"
        description="Состав, доступность и настройки групп. Счётчики обновляются каждые 30 секунд по данным сервера."
        actions={<>
          <Button type="button" variant="outline" disabled={isFetching} onClick={() => { void refetch(); }}><RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />Обновить группы</Button>
          <Button type="button" disabled={!available || !canWrite} onClick={() => openEditor(null)}><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Создать группу</Button>
        </>}
      />
      <PermissionNotice permission="device:write" action="создание и изменение групп" />
      {notice && <p role="status" className="rounded-lg border border-success/30 bg-success/5 p-3 text-sm">{notice}</p>}
      {isError ? (
        <Card><CardContent className="flex flex-col items-start gap-3 p-6 sm:flex-row sm:items-center sm:justify-between">
          <div><p className="font-medium">Не удалось загрузить группы</p><p className="mt-1 text-sm text-muted-foreground">Состояние данных не подтверждено сервером. Операции с группами приостановлены.</p></div>
          <Button type="button" variant="outline" onClick={() => { void refetch(); }}>Повторить</Button>
        </CardContent></Card>
      ) : isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-label="Загрузка групп" aria-busy="true">
          {Array.from({ length: 3 }, (_, index) => <div key={index} className="h-40 animate-pulse rounded-xl border border-border bg-card motion-reduce:animate-none" />)}
        </div>
      ) : !groups?.length ? (
        <Card><CardContent className="flex min-h-64 flex-col items-center justify-center p-8 text-center">
          <FolderOpen className="h-10 w-10 text-primary" aria-hidden="true" />
          <p className="mt-4 font-semibold">Групп пока нет</p><p className="mt-1 max-w-md text-sm text-muted-foreground">Создайте первую группу, чтобы разделить парк по локациям, задачам или профилям работы.</p>
          <Button className="mt-5" disabled={!available || !canWrite} onClick={() => openEditor(null)}><Plus className="mr-2 h-4 w-4" aria-hidden="true" />Создать группу</Button>
        </CardContent></Card>
      ) : (
        <section aria-label="Список групп" className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {groups.map((group) => (
            <Card key={group.id} className="relative overflow-hidden shadow-soft transition-[border-color,box-shadow] duration-200 hover:border-primary/30 hover:shadow-md motion-reduce:transition-none">
              <span className="absolute inset-y-0 left-0 w-1" style={{ backgroundColor: group.color ?? 'hsl(var(--primary))' }} aria-hidden="true" />
              <CardContent className="p-5 pl-6">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0"><div className="flex items-start gap-2"><Layers3 className="mt-1 h-4 w-4 shrink-0 text-primary" aria-hidden="true" /><h2 className="break-words font-semibold tracking-tight">{group.name}</h2></div>
                    <p className="mt-2 min-h-10 break-words text-sm leading-5 text-muted-foreground">{group.description || 'Описание не добавлено'}</p>
                  </div>
                  <Button type="button" size="icon" variant="ghost" className="h-9 w-9 shrink-0 text-muted-foreground hover:bg-destructive/10 hover:text-destructive" aria-label={`Удалить группу ${group.name}`} disabled={!canDelete || !available} title={!canDelete ? 'Текущие права не разрешают удаление групп' : undefined} onClick={() => openDeletion(group)}>
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                  </Button>
                </div>
                <div className="mt-4 flex flex-wrap gap-2 border-t border-border/70 pt-4">
                  <Badge variant="outline" className="rounded-full px-2.5"><Users className="mr-1 h-3 w-3" aria-hidden="true" />{group.total_devices} устройств</Badge>
                  <Badge variant="success" className="rounded-full px-2.5"><Wifi className="mr-1 h-3 w-3" aria-hidden="true" />{group.online_devices} онлайн</Badge>
                </div>
                {group.parent_group_id && <p className="mt-3 break-words text-xs text-muted-foreground">Родительская группа: {groups.find((item) => item.id === group.parent_group_id)?.name ?? group.parent_group_id}</p>}
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button type="button" variant="outline" size="sm" asChild><Link href={`/devices?group_id=${encodeURIComponent(group.id)}`} aria-label={`Устройства группы ${group.name}`}><Users className="mr-2 h-4 w-4" aria-hidden="true" />Устройства</Link></Button>
                  <Button type="button" variant="outline" size="sm" aria-label={`Изменить группу ${group.name}`} disabled={!canWrite || !available} onClick={() => openEditor(group)}><Pencil className="mr-2 h-4 w-4" aria-hidden="true" />Изменить</Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </section>
      )}
      {editor && <GroupEditor key={editor.group?.id ?? '__create__'} group={editor.group} groups={groups ?? []} available={exists(editor.group)} canWrite={canWrite} onClose={() => setEditor(null)} onSaved={() => { setNotice(editor.group ? 'Группа обновлена' : 'Группа создана'); setEditor(null); }} />}
      {deleting && <GroupDeleteDialog key={deleting.id} group={deleting} available={exists(deleting)} canDelete={canDelete} onClose={() => setDeleting(null)} onDeleted={() => { setNotice(`Группа «${deleting.name}» удалена`); setDeleting(null); }} />}
    </PageFrame>
  );
}
