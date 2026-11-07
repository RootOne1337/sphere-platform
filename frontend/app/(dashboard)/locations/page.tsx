'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Plus, Pencil, Trash2, RefreshCw } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/src/shared/ui/button';
import { Badge } from '@/src/shared/ui/badge';
import { Input } from '@/src/shared/ui/input';
import { Card, CardContent } from '@/src/shared/ui/card';
import { PageFrame, PageHeading } from '@/src/shared/ui/page-layout';
import { LocationDialog } from '@/src/features/locations/LocationDialog';
import { locationPath, parseLocation } from '@/src/features/locations/locationContract';
import { PermissionNotice, useCapabilities } from '@/src/features/access/Capabilities';

export default function LocationsPage() {
  const actor = useAuthStore(s => s.user); const session = useAuthStore(s => s.sessionVersion);
  const access = useCapabilities();
  const scope = `${actor?.org_id}:${actor?.id}:${actor?.role}:${session}`;
  const canWrite = access.can('device:write');
  const canDelete = access.can('device:delete');
  const [target, setTarget] = useState<{ id?: string; mode: 'create' | 'edit' | 'delete'; scope: string } | null>(null);
  const [search, setSearch] = useState('');
  const query = useQuery({ queryKey: ['locations', scope], enabled: Boolean(actor), retry: false,
    refetchInterval: 15000, refetchIntervalInBackground: false,
    queryFn: async ({ signal }) => {
      const { data } = await api.get('/locations', { signal });
      if (!Array.isArray(data)) throw new Error('Invalid location catalog');
      const parsed = data.map(v => parseLocation(v, actor!.org_id));
      if (new Set(parsed.map(v => v.id)).size !== parsed.length) throw new Error('Duplicate location IDs');
      return parsed;
    } });
  const locations = query.data ?? []; const fresh = query.isSuccess && !query.isFetching && !query.isError;
  const shown = locations.filter(v => [v.name, v.address, v.description, locationPath(v, locations).label].some(text => text?.toLowerCase().includes(search.toLowerCase())));
  const roots = locations.filter(v => v.parent_location_id === null).length;
  const invalid = locations.filter(v => !locationPath(v, locations).valid).length;
  function openTarget(mode: 'create' | 'edit' | 'delete', id?: string) {
    if (!fresh || !(mode === 'delete' ? canDelete : canWrite)) return;
    setTarget({ mode, id, scope });
  }
  return <PageFrame>
    <PageHeading title="Локации" eyebrow="Каталог площадок" description="Иерархия площадок, адреса и ручные координаты. Данные организации обновляются каждые 15 секунд при открытой странице." actions={<div className="flex flex-wrap gap-2"><Button variant="outline" disabled={query.isFetching} onClick={() => { void query.refetch(); }}><RefreshCw className="mr-2 h-4 w-4" />Обновить список</Button>{canWrite && <Button disabled={!fresh} onClick={() => openTarget('create')}><Plus className="mr-2 h-4 w-4" />Создать локацию</Button>}</div>} />
    <PermissionNotice permission="device:write" action="создание и изменение локаций" />
    {query.isError ? <Card><CardContent className="p-6"><p role="alert">Не удалось получить достоверный каталог локаций. Изменения недоступны.</p><Button className="mt-3" variant="outline" onClick={() => { void query.refetch(); }}>Повторить загрузку</Button></CardContent></Card>
      : query.isPending ? <p role="status">Загрузка локаций…</p> : <>
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border bg-card p-4"><div className="flex flex-wrap gap-2"><Badge variant="outline">{locations.length} локаций</Badge><Badge variant="outline">{roots} корневых</Badge><Badge variant="outline">{locations.filter(v => v.latitude !== null && v.longitude !== null).length} с координатами</Badge>{invalid > 0 && <Badge variant="warning">{invalid} с ошибками иерархии</Badge>}</div><p className="text-xs text-muted-foreground">{query.isFetching ? 'Обновление…' : `Проверено: ${new Date(query.dataUpdatedAt).toLocaleTimeString('ru-RU')}`}</p></div>
        <Input className="max-w-xl" aria-label="Поиск локаций" placeholder="Название, путь, адрес или описание" value={search} onChange={e => setSearch(e.target.value)} />
        <p className="text-xs text-muted-foreground">Счётчики в карточках показывают прямые назначения. Устройство может входить в несколько локаций; сумма карточек не является размером парка.</p>
        {!shown.length ? <Card><CardContent className="p-8 text-center">{locations.length ? 'Нет локаций по вашему запросу' : 'Локаций пока нет'}</CardContent></Card> : <section aria-label="Список локаций" className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">{shown.map(location => {
          const path = locationPath(location, locations);
          return <Card key={location.id} className="relative min-w-0 overflow-hidden shadow-soft"><span className="absolute inset-y-0 left-0 w-1" style={{ backgroundColor: location.color ?? 'hsl(var(--primary))' }} aria-hidden="true" /><CardContent className="p-5 pl-6">
            <div className="flex items-start justify-between gap-3"><div className="min-w-0"><h2 className="break-words font-semibold">{location.name}</h2><p className={`mt-1 break-words text-xs ${path.valid ? 'text-muted-foreground' : 'text-warning'}`}>{location.parent_location_id === null ? 'Корневая локация' : path.label}</p></div><div className="flex shrink-0 gap-1">{canWrite && <Button size="icon" variant="ghost" aria-label={`Изменить локацию ${location.name}`} disabled={!fresh} onClick={() => openTarget('edit', location.id)}><Pencil className="h-4 w-4" /></Button>}{canDelete && <Button size="icon" variant="ghost" aria-label={`Удалить локацию ${location.name}`} disabled={!fresh} onClick={() => openTarget('delete', location.id)}><Trash2 className="h-4 w-4" /></Button>}</div></div>
            <p className="mt-3 break-words text-sm">{location.address || 'Адрес не указан'}</p><p className="mt-1 whitespace-pre-wrap break-words text-sm text-muted-foreground">{location.description || 'Описание не добавлено'}</p>
            <dl className="mt-4 grid gap-2 border-t pt-3 text-xs"><div className="flex flex-wrap justify-between gap-2"><dt className="text-muted-foreground">Координаты</dt><dd>{location.latitude ?? '—'}, {location.longitude ?? '—'}</dd></div><div className="flex flex-wrap justify-between gap-2"><dt className="text-muted-foreground">Прямые назначения</dt><dd>{location.total_devices} устройств · {location.online_devices} online</dd></div><div><dt className="text-muted-foreground">Обновлено (UTC)</dt><dd>{new Date(location.updated_at).toLocaleString('ru-RU', { timeZone: 'UTC' })}</dd></div><div><dt className="text-muted-foreground">ID</dt><dd className="break-all font-mono">{location.id}</dd></div></dl>
          </CardContent></Card>;
        })}</section>}
      </>}
    {actor && target?.scope === scope && <LocationDialog key={`${scope}:${target.mode}:${target.id ?? 'new'}`} {...target} orgId={actor.org_id} scope={scope} catalog={locations} catalogFresh={fresh} canWrite={canWrite} canDelete={canDelete} reloadCatalog={async () => !(await query.refetch()).isError} onClose={() => setTarget(null)} />}
  </PageFrame>;
}
