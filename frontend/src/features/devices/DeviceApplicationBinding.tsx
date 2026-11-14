'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/src/shared/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { useCapabilities } from '@/src/features/access/Capabilities';
import { useApplicationProfiles, validProfileKey, type ApplicationProfile } from '@/src/features/accounts/applicationProfiles';
import { useRevisionedApplicationResource } from '@/src/features/accounts/useRevisionedApplicationResource';

type Binding = {
  application_profile_id: string | null;
  application_server_key: string | null;
};

type BindingReceipt = Binding & { device_id: string; revision: number };

export function hasApplicationBinding(device: { application_profile_id?: string | null }): boolean {
  return typeof device.application_profile_id === 'string' && device.application_profile_id.length > 0;
}

export function applicationBindingLabel(device: Partial<Binding> & { server_name?: string | null }, profiles: readonly ApplicationProfile[] = []): string {
  if (!hasApplicationBinding(device)) return device.server_name || 'Не назначен';
  const profile = profiles.find(item => item.id === device.application_profile_id);
  const server = profile?.servers.find(item => item.key === device.application_server_key);
  return `${profile?.name ?? device.application_profile_id} · ${server?.name ?? device.application_server_key ?? 'сервер не подтверждён'}`;
}

function validateBinding(value: unknown, deviceId: string): BindingReceipt {
  const data = value as Partial<BindingReceipt> | null;
  if (!data || data.device_id !== deviceId || typeof data.revision !== 'number' || !Number.isSafeInteger(data.revision) || data.revision < 0
    || !((data.application_profile_id === null && data.application_server_key === null)
      || (typeof data.application_profile_id === 'string' && Boolean(data.application_profile_id) && validProfileKey(data.application_server_key)))) {
    throw new Error('Некорректная привязка приложения.');
  }
  return data as BindingReceipt;
}

function equalBinding(observed: Binding, requested: Binding) {
  return observed.application_profile_id === requested.application_profile_id
    && observed.application_server_key === requested.application_server_key;
}

export function DeviceApplicationBinding({ deviceId, name, onClose }: { deviceId: string; name: string; onClose: () => void }) {
  const access = useCapabilities();
  const canWrite = access.can('device:write') && access.can('account:read');
  const profilesQuery = useApplicationProfiles(access.can('account:read'));
  const profiles = access.can('account:read') && !profilesQuery.isError ? profilesQuery.data?.filter(profile => profile.source === 'tenant') ?? [] : [];
  const cache = useQueryClient();
  const resource = useRevisionedApplicationResource<BindingReceipt, Binding>(`/devices/${encodeURIComponent(deviceId)}/application-binding`,
    value => validateBinding(value, deviceId), equalBinding);
  const current = resource.query.data;
  const [draft, setDraft] = useState<Binding | null>(null);
  const [baseRevision, setBaseRevision] = useState<number | null>(null);
  const [saved, setSaved] = useState(false);
  const selection = draft ?? current;
  const profile = profiles.find(item => item.id === selection?.application_profile_id);
  const staleDraft = draft !== null && current?.revision !== baseRevision;
  const writable = canWrite && resource.query.isSuccess && !resource.query.isFetching
    && profilesQuery.isSuccess && !resource.pending && !resource.blocked && !staleDraft;
  const canSubmit = Boolean(writable && selection && current && !equalBinding(selection, current)
    && (!selection.application_profile_id || profile?.servers.some(server => server.key === selection.application_server_key)));

  function edit(next: Binding) {
    if (!writable || !current) return;
    setBaseRevision(current.revision);
    setDraft(next);
    setSaved(false);
  }

  async function save() {
    if (!canSubmit || !selection || !current) return;
    setSaved(false);
    if (await resource.save(selection, current.revision)) {
      setDraft(null);
      setSaved(true);
      void cache.invalidateQueries({ queryKey: ['devices'] });
    }
  }

  async function reload() {
    if (await resource.reload()) { setDraft(null); setSaved(false); }
    if (access.can('account:read')) void profilesQuery.refetch();
  }

  return <Dialog open onOpenChange={open => { if (!open && !resource.pending) onClose(); }}>
    <DialogContent className="max-h-[90dvh] overflow-y-auto">
      <DialogHeader><DialogTitle>Привязка приложения и сервера</DialogTitle><DialogDescription>{name}. Сохранение меняет цель для будущих запусков автоматизации.</DialogDescription></DialogHeader>
      {!access.can('account:read') && <p role="status" className="text-sm">Для чтения каталога приложений требуется право account:read.</p>}
      {resource.query.isLoading && <p role="status">Читаем сохранённую привязку…</p>}
      {resource.query.isError && <p role="alert">Привязка устройства недоступна.</p>}
      {profilesQuery.isError && <p role="alert">Каталог приложений недоступен.</p>}
      {profilesQuery.isLoading && <p role="status">Читаем каталог приложений…</p>}
      {current && <p className="text-sm text-muted-foreground">Сохранено {current.application_profile_id
        ? applicationBindingLabel(current, profiles)
        : 'без привязки к профилю'}.</p>}
      {selection && <div className="space-y-3">
        <label className="block text-sm">Профиль приложения
          <select className="mt-1 h-10 w-full rounded-md border border-input bg-background px-2" value={selection.application_profile_id ?? ''} disabled={!writable}
            onChange={event => edit({ application_profile_id: event.target.value || null, application_server_key: null })}>
            <option value="">Без привязки к профилю</option>
            {selection.application_profile_id && !profile && <option value={selection.application_profile_id}>{selection.application_profile_id}</option>}
            {profiles.map(item => <option key={item.id} value={item.id}>{item.name} · {item.key}</option>)}
          </select>
        </label>
        {selection.application_profile_id && <label className="block text-sm">Сервер приложения
          <select className="mt-1 h-10 w-full rounded-md border border-input bg-background px-2" value={selection.application_server_key ?? ''} disabled={!writable || !profile?.servers.length}
            onChange={event => edit({ ...selection, application_server_key: event.target.value || null })}>
            <option value="">Выберите сервер</option>
            {selection.application_server_key && !profile?.servers.some(server => server.key === selection.application_server_key)
              && <option value={selection.application_server_key}>{selection.application_server_key}</option>}
            {profile?.servers.map(server => <option key={server.key} value={server.key}>{server.name} · {server.key}</option>)}
          </select>
        </label>}
        {profile && profile.servers.length === 0 && <p className="text-sm">Добавьте сервер в разделе «Игровые аккаунты → Приложения и серверы».</p>}
      </div>}
      {!canWrite && <p className="text-sm text-muted-foreground">Изменение требует права device:write и доступа к каталогу приложений.</p>}
      {staleDraft && <p role="alert">Привязка изменилась. Перечитайте сохранённые значения.</p>}
      {resource.error && <p role="alert" className="text-sm text-destructive">{resource.error}</p>}
      {saved && <p role="status">Привязка подтверждена повторным чтением.</p>}
      <DialogFooter>
        <Button variant="outline" disabled={resource.pending || resource.query.isFetching} onClick={() => { void reload(); }}>Перечитать привязку</Button>
        <Button variant="outline" disabled={resource.pending} onClick={onClose}>Готово</Button>
        <Button disabled={!canSubmit} onClick={() => { void save(); }}>{resource.pending ? 'Проверяем сохранение…' : 'Сохранить привязку'}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
