'use client';

import { useRef, useState } from 'react';
import { api } from '@/lib/api';
import { getApiErrorMessage } from '@/lib/apiError';
import { useCapabilities } from '@/src/features/access/Capabilities';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { MAX_ANDROID_PACKAGE, MAX_APPLICATION_NAME, MAX_APPLICATION_SERVERS, parseApplicationProfile, validAndroidPackage, validApplicationServer, validProfileKey,
  type ApplicationProfile, type ApplicationServer } from './applicationProfiles';

type CatalogProps = {
  profiles: readonly ApplicationProfile[];
  pending: boolean;
  failed: boolean;
  refresh: () => Promise<unknown>;
};

export function ApplicationProfilesPanel({ profiles, pending, failed, refresh }: CatalogProps) {
  const access = useCapabilities();
  const writable = access.can('account:write');
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<ApplicationProfile | 'new' | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const close = () => { setOpen(false); setEditing(null); setNotice(null); };
  return <>
    <Button variant="outline" size="sm" onClick={() => setOpen(true)}>Приложения и серверы</Button>
    {open && <Dialog open onOpenChange={next => { if (!next && !saving) close(); }}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-[680px]">
        <DialogHeader><DialogTitle>Приложения и серверы</DialogTitle><DialogDescription>Каталог организации для выбора в игровых аккаунтах.</DialogDescription></DialogHeader>
        {notice && <p role="status" className="text-sm">{notice}</p>}
        {pending && <p role="status">Загружаем каталог приложений…</p>}
        {failed && !editing && <div role="alert" className="space-y-2"><p>Каталог приложений недоступен.</p><Button variant="outline" onClick={() => { void refresh(); }}>Повторить</Button></div>}
        {editing ? <>
          {failed && <div role="alert" className="space-y-2"><p>Каталог приложений недоступен. Черновик сохранён в форме.</p><Button variant="outline" onClick={() => { void refresh(); }}>Повторить</Button></div>}
          <ProfileEditor key={editing === 'new' ? 'new' : editing.id} profile={editing === 'new' ? null : editing}
            writable={writable && !failed} onCancel={() => setEditing(null)} onSaved={async message => {
              setNotice(message); await refresh(); setEditing(null);
            }} setSaving={setSaving} />
        </> : !pending && !failed && <>
            {writable && <Button variant="outline" onClick={() => { setNotice(null); setEditing('new'); }}>Добавить приложение</Button>}
            <div className="space-y-2">{profiles.map(profile => <details key={profile.id} className="rounded-lg border p-3 text-sm">
                <summary className="cursor-pointer font-medium">{profile.name} · {profile.key} · {profile.servers.length} серверов</summary>
                <p className="mt-2 break-all text-xs text-muted-foreground">Android package {profile.android_package ?? 'не указан'}</p>
                {profile.source === 'builtin' && <p className="mt-1 text-xs text-muted-foreground">Встроенный профиль</p>}
                <ul className="mt-2 space-y-1">{profile.servers.map(server => <li className="break-all" key={server.key}>{server.name} · {server.domain}:{server.port}</li>)}</ul>
                {writable && profile.source === 'tenant' && <Button className="mt-2" size="sm" variant="outline" onClick={() => { setNotice(null); setEditing(profile); }}>Изменить {profile.name}</Button>}
              </details>)}</div>
          </>}
        {!editing && <DialogFooter><Button variant="outline" onClick={close}>Готово</Button></DialogFooter>}
      </DialogContent>
    </Dialog>}
  </>;
}

function ProfileEditor({ profile, writable, onCancel, onSaved, setSaving }: {
  profile: ApplicationProfile | null; writable: boolean; onCancel: () => void; onSaved: (message: string | null) => Promise<void>; setSaving: (value: boolean) => void;
}) {
  const [key, setKey] = useState(profile?.key ?? '');
  const [name, setName] = useState(profile?.name ?? '');
  const [androidPackage, setAndroidPackage] = useState(profile?.android_package ?? '');
  const [servers, setServers] = useState<ApplicationServer[]>(profile?.servers ?? []);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const locked = useRef(false);
  const savedCount = profile?.servers.length ?? 0;
  const updateServer = (index: number, patch: Partial<ApplicationServer>) => setServers(current => current.map((server, row) => row === index ? { ...server, ...patch } : server));

  async function save() {
    if (locked.current || !writable || needsRefresh) return;
    const values = servers.map(server => ({ ...server, key: server.key.trim(), name: server.name.trim(), domain: server.domain.trim() }));
    if (!validProfileKey(key.trim()) || !name.trim() || name.trim().length > MAX_APPLICATION_NAME
      || (androidPackage.trim() && !validAndroidPackage(androidPackage.trim())) || !values.every(validApplicationServer)
      || new Set(values.map(server => server.key)).size !== values.length
      || new Set(values.map(server => server.name.toLowerCase())).size !== values.length) {
      setError('Проверьте ключ, название, Android package и поля серверов. Ключи и названия серверов не должны повторяться.');
      return;
    }
    const payload = { name: name.trim(), android_package: androidPackage.trim() || null, servers: values };
    locked.current = true; setPending(true); setSaving(true); setError(null);
    try {
      const response = profile
        ? await api.patch(`/application-profiles/${encodeURIComponent(profile.id)}`, { ...payload, expected_updated_at: profile.updated_at })
        : await api.post('/application-profiles', { ...payload, key: key.trim() });
      const receipt = parseApplicationProfile(response.data);
      if (response.status !== (profile ? 200 : 201) || receipt.source !== 'tenant' || receipt.key !== key.trim()
        || (profile && receipt.id !== profile.id) || receipt.name !== payload.name || receipt.android_package !== payload.android_package
        || receipt.servers.length !== values.length || values.some(server => !receipt.servers.some(observed =>
          observed.key === server.key && observed.name === server.name && observed.port === server.port
          && observed.domain === server.domain.toLowerCase().replace(/\.$/, '')))) {
        throw new Error('Ответ не подтверждает сохранение профиля.');
      }
      await onSaved(`Сохранено приложение «${receipt.name}».`);
    } catch (failure) {
      const status = (failure as { response?: { status?: number } } | null)?.response?.status;
      if (!status || status === 409 || status >= 500) setNeedsRefresh(true);
      const reason = getApiErrorMessage(failure, 'Исход сохранения не подтверждён. Перечитайте каталог перед повтором.');
      setError(reason === 'Disable profile registration and farming before changing the Android package'
        ? 'Перед сменой Android-пакета выключите регистрацию и фарм для этого профиля в настройках пайплайнов.' : reason);
    } finally { locked.current = false; setPending(false); setSaving(false); }
  }

  return <form className="space-y-3" onSubmit={event => { event.preventDefault(); void save(); }}>
    <fieldset className="space-y-3" disabled={!writable || pending || needsRefresh}>
      <legend className="font-medium">{profile ? 'Изменение приложения' : 'Новое приложение'}</legend>
      <label className="block text-sm">Ключ приложения<Input required maxLength={64} readOnly={Boolean(profile)} value={key} onChange={event => setKey(event.target.value)} /></label>
      <label className="block text-sm">Название приложения<Input required maxLength={MAX_APPLICATION_NAME} value={name} onChange={event => setName(event.target.value)} /></label>
      <label className="block text-sm">Android package<Input maxLength={MAX_ANDROID_PACKAGE} value={androidPackage} onChange={event => setAndroidPackage(event.target.value)} /></label>
      <p className="text-xs text-muted-foreground">Ключи и названия уже сохранённых серверов используются в связанных записях. Можно обновить адрес и порт или добавить сервер.</p>
      {servers.map((server, index) => <fieldset key={index} className="grid gap-2 rounded-lg border p-3 sm:grid-cols-2">
        <legend className="px-1 text-xs">Сервер {index + 1}</legend>
        <label className="text-sm">Ключ сервера<Input required maxLength={64} readOnly={index < savedCount} value={server.key} onChange={event => updateServer(index, { key: event.target.value })} /></label>
        <label className="text-sm">Название сервера<Input required maxLength={50} readOnly={index < savedCount} value={server.name} onChange={event => updateServer(index, { name: event.target.value })} /></label>
        <label className="text-sm">Домен<Input required maxLength={254} value={server.domain} onChange={event => updateServer(index, { domain: event.target.value })} /></label>
        <label className="text-sm">Порт<Input required type="number" min={1} max={65535} value={server.port || ''} onChange={event => updateServer(index, { port: Number(event.target.value) })} /></label>
        {index >= savedCount && <Button type="button" size="sm" variant="ghost" onClick={() => setServers(current => current.filter((_, row) => row !== index))}>Убрать черновик сервера</Button>}
      </fieldset>)}
      <Button type="button" variant="outline" size="sm" disabled={servers.length >= MAX_APPLICATION_SERVERS} onClick={() => setServers(current => [...current, { key: '', name: '', domain: '', port: 0 }])}>Добавить сервер</Button>
    </fieldset>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <DialogFooter>
      <Button type="button" variant="outline" disabled={pending} onClick={() => { if (needsRefresh) void onSaved(null); else onCancel(); }}>{needsRefresh ? 'Перечитать каталог' : 'Отмена'}</Button>
      <Button type="submit" disabled={!writable || pending || needsRefresh}>{pending ? 'Сохраняем…' : 'Сохранить приложение'}</Button>
    </DialogFooter>
  </form>;
}
