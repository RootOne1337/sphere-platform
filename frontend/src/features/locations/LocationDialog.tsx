'use client';

import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Location } from '@/lib/hooks/useLocations';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { emptyLocationDraft, locationDraft, locationFailure, locationPath, parentChoices, parseLocation, validateLocationDraft, verifyLocationReceipt, type LocationDraft } from './locationContract';
import { PermissionNotice } from '@/src/features/access/Capabilities';

export function LocationDialog({ id, mode, orgId, scope, catalog, catalogFresh, canWrite, canDelete, reloadCatalog, onClose }: {
  id?: string; mode: 'create' | 'edit' | 'delete'; orgId: string; scope: string; catalog: Location[]; catalogFresh: boolean;
  canWrite: boolean; canDelete: boolean; reloadCatalog: () => Promise<boolean>; onClose: () => void;
}) {
  const qc = useQueryClient(); const busy = useRef(false); const live = useRef(true);
  const [baseline, setBaseline] = useState<Location | null>(null);
  const [draft, setDraft] = useState<LocationDraft>(emptyLocationDraft);
  const [pending, setPending] = useState(false); const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState<string | null>(null); const [notice, setNotice] = useState<string | null>(null);
  const [discard, setDiscard] = useState<'close' | 'reload' | null>(null);
  const detail = useQuery({ queryKey: ['location-detail', scope, id], enabled: Boolean(id), retry: false, staleTime: 0,
    refetchInterval: 15000, refetchIntervalInBackground: false,
    queryFn: async ({ signal }) => parseLocation((await api.get('/locations/' + id, { signal })).data, orgId, id) });
  useEffect(() => { live.current = true; return () => { live.current = false; }; }, []);
  useEffect(() => {
    if (!baseline && detail.data && !detail.isError && !detail.isFetching) { setBaseline(detail.data); setDraft(locationDraft(detail.data)); }
  }, [baseline, detail.data, detail.isError, detail.isFetching]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(baseline ? locationDraft(baseline) : emptyLocationDraft());
  const stale = Boolean(id && baseline && detail.data?.updated_at !== baseline.updated_at);
  const fresh = catalogFresh && (!id || Boolean(baseline && detail.data && !detail.isError && !detail.isFetching));
  const writable = fresh && !pending && !blocked && !stale && (mode === 'delete' ? canDelete : canWrite);
  function close() { if (!busy.current) { if (dirty && mode !== 'delete') setDiscard('close'); else onClose(); } }
  async function refresh() {
    if (busy.current) return;
    setNotice(null);
    const catalogOK = await reloadCatalog();
    const result = id ? await detail.refetch() : null;
    if (!live.current) return;
    if (!catalogOK || result?.isError) { setError('Не удалось перечитать состояние. Запись остаётся недоступной.'); return; }
    if (result?.data) { setBaseline(result.data); setDraft(locationDraft(result.data)); }
    else setDraft(emptyLocationDraft());
    setBlocked(false); setError(null);
  }
  async function submit() {
    if (busy.current || !writable) return;
    let patch;
    try { patch = mode === 'delete' ? null : validateLocationDraft(draft, catalog, baseline ?? undefined); }
    catch (failure) { setError((failure as Error).message); return; }
    if (patch && !Object.keys(patch).length) { setNotice('Нет изменений для сохранения.'); return; }
    if (mode === 'create' && catalog.some(v => v.name === draft.name.trim())) { setError('Локация с таким именем уже есть. Проверьте её состояние вместо повторного создания.'); return; }
    busy.current = true; setPending(true); setError(null); setNotice(null);
    try {
      if (mode === 'delete') {
        const response = await api.delete('/locations/' + id, { params: { expected_updated_at: baseline!.updated_at } });
        if (response.status !== 204) throw new Error('Unconfirmed delete');
        if (live.current) { void qc.invalidateQueries({ queryKey: ['locations'] }); void qc.invalidateQueries({ queryKey: ['devices'] }); onClose(); }
      } else {
        const response = id ? await api.put('/locations/' + id, { ...patch, expected_updated_at: baseline!.updated_at }) : await api.post('/locations', patch);
        if (response.status !== (id ? 200 : 201)) throw new Error('Unconfirmed write');
        const result = verifyLocationReceipt(response.data, orgId, patch!, baseline ?? undefined);
        if (!live.current) return;
        if (id) { qc.setQueryData(['location-detail', scope, id], result); setBaseline(result); setDraft(locationDraft(result)); }
        else { setDraft(emptyLocationDraft()); setBlocked(true); }
        setNotice(`Сохранение подтверждено API: ${result.name} · ${new Date(result.updated_at).toLocaleString('ru-RU', { timeZone: 'UTC' })} UTC.`);
        void qc.invalidateQueries({ queryKey: ['locations'] });
      }
    } catch (failure) { if (live.current) { setError(locationFailure(failure)); setBlocked(true); } }
    finally { busy.current = false; if (live.current) setPending(false); }
  }
  const title = mode === 'create' ? 'Создание локации' : mode === 'delete' ? 'Удаление локации' : 'Редактирование локации';
  const set = (field: keyof LocationDraft, value: string) => { setDraft(v => ({ ...v, [field]: value })); setNotice(null); };
  const choices = parentChoices(catalog, id);
  return <Dialog open onOpenChange={open => { if (!open) close(); }}>
    <DialogContent className="sm:max-w-2xl" onEscapeKeyDown={event => { if (busy.current || dirty) event.preventDefault(); if (dirty && !busy.current) setDiscard('close'); }} onPointerDownOutside={event => { if (busy.current || dirty) event.preventDefault(); }}>
      <DialogHeader><DialogTitle>{title}</DialogTitle><DialogDescription>Ручные координаты и иерархия организации. Счётчики относятся к прямым назначениям устройств; геолокация автоматически не определяется.</DialogDescription></DialogHeader>
      <PermissionNotice permission={mode === 'delete' ? 'device:delete' : 'device:write'} action={mode === 'delete' ? 'удаление локации' : mode === 'create' ? 'создание локации' : 'изменение локации'} />
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="break-all font-mono text-xs text-muted-foreground">{id ?? 'Новая локация'}</p><Button variant="outline" disabled={pending || detail.isFetching} onClick={() => { if (dirty) setDiscard('reload'); else void refresh(); }}>Перечитать состояние</Button></div>
      {id && !baseline && !detail.isError && <p role="status">Загрузка локации…</p>}
      {detail.isError && <p role="alert">Не удалось получить достоверную карточку локации. Изменения заблокированы.</p>}
      {stale && <p role="alert" className="rounded-lg border border-warning/40 p-3 text-sm">Состояние изменилось на сервере. Черновик сохранён; перечитайте состояние перед записью.</p>}
      {error && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">{error}</p>}
      {notice && <p role="status" className="rounded-lg border border-success/30 bg-success/5 p-3 text-sm">{notice}</p>}
      {mode === 'delete' ? baseline && <section className="space-y-3 rounded-lg border border-destructive/30 p-4" aria-label="Подтверждение удаления">
        <p className="break-words font-semibold">Удалить «{baseline.name}»?</p><p className="text-sm">Локация и её прямые назначения ({baseline.total_devices} устройств) будут удалены. Устройства сохранятся. Дочерние локации станут корневыми; их назначения сохранятся.</p>
        <p className="break-words text-sm">Дочерние локации: {catalog.filter(v => v.parent_location_id === id).map(v => v.name).join(', ') || 'нет'}.</p>
        <Button variant="destructive" disabled={!writable} onClick={() => { void submit(); }}>{pending ? 'Удаляем…' : 'Подтвердить удаление'}</Button>
      </section> : (!id || baseline) && <>
        <fieldset disabled={pending || !canWrite} className="grid min-w-0 gap-4 sm:grid-cols-2">
          <label className="space-y-2 text-sm sm:col-span-2">Название<Input value={draft.name} maxLength={255} autoComplete="off" onChange={e => set('name', e.target.value)} /></label>
          <label className="space-y-2 text-sm sm:col-span-2">Описание<Input value={draft.description} maxLength={1000} onChange={e => set('description', e.target.value)} /></label>
          <label className="space-y-2 text-sm sm:col-span-2">Адрес<Input value={draft.address} maxLength={500} onChange={e => set('address', e.target.value)} /></label>
          <label className="space-y-2 text-sm sm:col-span-2">Родительская локация<select className="flex h-10 w-full min-w-0 rounded-md border bg-background px-3 text-sm" value={draft.parent_location_id} onChange={e => set('parent_location_id', e.target.value)}>
            <option value="">Без родителя (корневая)</option>{draft.parent_location_id && !choices.some(v => v.id === draft.parent_location_id) && <option value={draft.parent_location_id}>Недоступный родитель — выберите другой или очистите</option>}
            {choices.map(v => <option key={v.id} value={v.id}>{locationPath(v, catalog).label}</option>)}
          </select></label>
          <label className="space-y-2 text-sm">Широта<Input inputMode="decimal" value={draft.latitude} placeholder="−90…90" onChange={e => set('latitude', e.target.value)} /></label>
          <label className="space-y-2 text-sm">Долгота<Input inputMode="decimal" value={draft.longitude} placeholder="−180…180" onChange={e => set('longitude', e.target.value)} /></label>
          <p className="text-xs text-muted-foreground sm:col-span-2">Десятичные градусы, разделитель — точка. Пустое поле очищает координату; 0 является допустимым значением.</p>
          <label className="space-y-2 text-sm">Цвет (#RRGGBB)<Input value={draft.color} maxLength={7} placeholder="Не задан" onChange={e => set('color', e.target.value)} /></label>
          {baseline && <p className="self-center break-words text-xs text-muted-foreground">Прямые назначения: {baseline.total_devices} · online по сохранённому статусу: {baseline.online_devices}</p>}
        </fieldset>
        <Button disabled={!writable || !draft.name.trim()} onClick={() => { void submit(); }}>{pending ? 'Сохраняем…' : mode === 'create' ? 'Создать локацию' : 'Сохранить изменения'}</Button>
      </>}
      {discard && <section className="space-y-3 rounded-lg border border-warning/40 p-4"><p>Отбросить несохранённый черновик?</p><div className="flex flex-wrap gap-2"><Button disabled={pending} onClick={() => { const action = discard; setDiscard(null); if (action === 'close') onClose(); else void refresh(); }}>Да, отбросить</Button><Button variant="outline" onClick={() => setDiscard(null)}>Оставить черновик</Button></div></section>}
    </DialogContent>
  </Dialog>;
}
