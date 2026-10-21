'use client';

import { useEffect, useRef, useState } from 'react';
import { Archive, History, Plus, RefreshCw, Shield } from 'lucide-react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { VpnProfileInspector } from './VpnProfileInspector';
import { parseProfilePage, type SavedVpnProfile } from './profileTypes';

interface Version { id: string; revision: number; name: string; protocol_version: string; created_at: string }

export function VpnProfileCatalog({ canWrite }: { canWrite: boolean }) {
  const [data, setData] = useState<{ items: SavedVpnProfile[]; total: number }>({ items: [], total: 0 });
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1); const [search, setSearch] = useState('');
  const [archived, setArchived] = useState(false); const [reload, setReload] = useState(0);
  const [importing, setImporting] = useState<{ target?: SavedVpnProfile } | null>(null);
  const [history, setHistory] = useState<SavedVpnProfile | null>(null);
  const [archive, setArchive] = useState<SavedVpnProfile | null>(null);
  const generation = useRef(0);
  const fresh = !loading && !error;
  useEffect(() => {
    const id = ++generation.current; const controller = new AbortController();
    setLoading(true); setError(null);
    const timer = setTimeout(() => {
      void api.get('/vpn/profiles', { params: { page, page_size: 10, include_archived: archived, search }, signal: controller.signal })
        .then(({ data }) => { if (id === generation.current) setData(parseProfilePage(data, page)); })
        .catch(() => { if (id === generation.current && !controller.signal.aborted) setError('Каталог VPN-профилей недоступен. Данные не подтверждены.'); })
        .finally(() => { if (id === generation.current) setLoading(false); });
    }, 200);
    return () => { clearTimeout(timer); generation.current++; controller.abort(); };
  }, [page, search, archived, reload]);

  return <section aria-label="Каталог VPN-профилей" className="mb-6 rounded-xl border bg-background/50">
    <div className="flex flex-wrap items-start justify-between gap-3 border-b p-4">
      <div><h2 className="flex items-center gap-2 font-semibold"><Shield className="h-4 w-4 text-primary" /> VPN-профили</h2><p className="mt-1 max-w-2xl text-sm text-muted-foreground">Зашифрованные конфигурации и история версий. Сохранённый профиль не означает подключённый туннель.</p></div>
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={loading} onClick={() => setReload(v => v + 1)}><RefreshCw className="mr-2 h-4 w-4" />Обновить профили</Button>{canWrite && <Button size="sm" onClick={() => setImporting({})}><Plus className="mr-2 h-4 w-4" />Импорт профиля</Button>}</div>
    </div>
    <div className="flex flex-wrap items-center gap-3 p-4">
      <input aria-label="Поиск VPN-профилей" placeholder="Поиск по названию" value={search} maxLength={120} className="min-w-0 flex-1 rounded-lg border bg-background px-3 py-2 text-sm" onChange={e => { setSearch(e.target.value); setPage(1); }} />
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={archived} onChange={e => { setArchived(e.target.checked); setPage(1); }} />Показывать архив</label>
    </div>
    {loading && <p role="status" className="px-4 pb-4 text-sm text-muted-foreground">Загружаем профили…</p>}
    {error && <p role="alert" className="px-4 pb-4 text-sm text-destructive">{error}</p>}
    {fresh && !data.items.length && <p className="px-4 pb-4 text-sm text-muted-foreground">{search ? 'Профилей с таким названием нет.' : 'Профилей пока нет. Импортируй .conf для выбранных приложений.'}</p>}
    {data.items.length > 0 && <div className={loading || error ? 'opacity-50' : ''}>{data.items.map(profile => <article key={profile.id} className="flex min-w-0 flex-col gap-3 border-t p-4 lg:flex-row lg:items-center lg:justify-between">
      <div className="min-w-0"><p className="break-words font-medium">{profile.name} <span className="ml-2 text-xs font-normal text-muted-foreground">v{profile.current_revision}{profile.is_archived ? ' · Архив' : ''}</span></p>
        <p className="mt-1 text-xs text-muted-foreground">{profile.protocol === 'amneziawg' ? 'AmneziaWG' : 'WireGuard'} {profile.protocol_version} · Приложений: {profile.traffic_policy.included_packages.length} · Политика: Sphere вне VPN</p>
        {profile.description && <p className="mt-1 break-words text-sm text-muted-foreground">{profile.description}</p>}</div>
      <div className="flex shrink-0 flex-wrap gap-2"><Button size="sm" variant="outline" disabled={!fresh} onClick={() => setHistory(profile)}><History className="mr-2 h-4 w-4" />Версии</Button>
        {canWrite && !profile.is_archived && <><Button size="sm" variant="outline" disabled={!fresh} onClick={() => setImporting({ target: profile })}>Новая версия</Button><Button size="sm" variant="ghost" aria-label={`Архивировать ${profile.name}`} disabled={!fresh} onClick={() => setArchive(profile)}><Archive className="h-4 w-4" /></Button></>}
      </div>
    </article>)}</div>}
    <div className="flex items-center justify-between gap-2 border-t px-4 py-3 text-xs text-muted-foreground"><span>{fresh ? `Всего ${data.total} · страница ${page}` : 'Состояние обновляется'}</span><div className="flex gap-2"><Button size="sm" variant="outline" disabled={!fresh || page <= 1} onClick={() => setPage(p => p - 1)}>Назад</Button><Button size="sm" variant="outline" disabled={!fresh || page * 10 >= data.total} onClick={() => setPage(p => p + 1)}>Далее</Button></div></div>
    {importing && canWrite && <VpnProfileInspector purpose="save" target={importing.target} onSaved={() => setReload(v => v + 1)} onClose={() => setImporting(null)} />}
    {history && <ProfileVersions profile={history} onClose={() => setHistory(null)} />}
    {archive && canWrite && <ArchiveProfile profile={archive} onChanged={() => setReload(v => v + 1)} onClose={() => setArchive(null)} />}
  </section>;
}

function ProfileVersions({ profile, onClose }: { profile: SavedVpnProfile; onClose: () => void }) {
  const [items, setItems] = useState<Version[]>([]); const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true); const [page, setPage] = useState(1); const [total, setTotal] = useState(0);
  useEffect(() => {
    let active = true; const controller = new AbortController(); setLoading(true); setError(false);
    void api.get(`/vpn/profiles/${profile.id}/revisions`, { params: { page, page_size: 10 }, signal: controller.signal }).then(({ data }) => {
      if (!active) return;
      if (!data || data.page !== page || data.page_size !== 10 || !Array.isArray(data.items) || data.items.length > 10 || !Number.isInteger(data.total)
        || data.total < data.items.length || data.items.some((v: Version & { profile_id: string }) => !v || v.profile_id !== profile.id || !Number.isInteger(v.revision) || v.revision < 1 || typeof v.name !== 'string' || typeof v.protocol_version !== 'string' || typeof v.created_at !== 'string' || !Number.isFinite(Date.parse(v.created_at)))) throw new Error('invalid_history');
      setItems(data.items.map((v: Version) => ({ id: v.id, revision: v.revision, name: v.name, protocol_version: v.protocol_version, created_at: v.created_at }))); setTotal(data.total);
    }).catch(() => { if (active && !controller.signal.aborted) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [profile.id, page]);
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}><DialogContent className="max-w-2xl" layout="workspace"><DialogHeader><DialogTitle>Версии · {profile.name}</DialogTitle><DialogDescription>История конфигураций без ключей. Старые версии не перезаписываются.</DialogDescription></DialogHeader>
    <DialogBody>
    {loading ? <p role="status">Загружаем историю…</p> : error ? <p role="alert">История версий недоступна.</p> : <div className="divide-y rounded-lg border">{items.map(item => <div key={item.id} className="grid gap-1 p-3 text-sm"><p className="break-words font-medium">v{item.revision} · {item.name}</p><p className="text-xs text-muted-foreground">Протокол {item.protocol_version} · {new Date(item.created_at).toLocaleString('ru-RU', { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'short' })} UTC</p></div>)}</div>}
    </DialogBody>
    <DialogFooter><Button variant="outline" disabled={loading || page === 1} onClick={() => setPage(p => p - 1)}>Назад</Button><Button variant="outline" disabled={loading || error || page * 10 >= total} onClick={() => setPage(p => p + 1)}>Далее</Button></DialogFooter>
  </DialogContent></Dialog>;
}

function ArchiveProfile({ profile, onClose, onChanged }: { profile: SavedVpnProfile; onClose: () => void; onChanged: () => void }) {
  const [pending, setPending] = useState(false); const [done, setDone] = useState(false); const [error, setError] = useState<string | null>(null);
  const active = useRef(true); const controller = useRef<AbortController | null>(null);
  useEffect(() => { active.current = true; return () => { active.current = false; controller.current?.abort(); }; }, []);
  async function archive() {
    if (controller.current || done) return;
    controller.current = new AbortController(); setPending(true);
    try {
      const { data } = await api.post(`/vpn/profiles/${profile.id}/archive`, { expected_revision: profile.current_revision }, { signal: controller.current.signal });
      if (!active.current) return;
      if (data?.id !== profile.id || data.current_revision !== profile.current_revision || data.is_archived !== true || data.apply_allowed !== false) throw new Error('invalid_archive_receipt');
      setDone(true); onChanged();
    } catch { if (active.current) { setError('Архивирование не подтверждено. Обнови каталог перед следующей операцией.'); setDone(true); } }
    finally { if (active.current) setPending(false); }
  }
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}><DialogContent><DialogHeader><DialogTitle>Архивировать профиль?</DialogTitle><DialogDescription>«{profile.name}», версия {profile.current_revision}. История сохранится. Сеть устройств не изменится.</DialogDescription></DialogHeader>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}{done && !error && <p role="status">Профиль перенесён в архив.</p>}
    <div className="flex justify-end gap-2"><Button variant="outline" onClick={onClose}>Закрыть</Button><Button disabled={pending || done} onClick={() => void archive()}>{pending ? 'Архивируем…' : 'В архив'}</Button></div>
  </DialogContent></Dialog>;
}
