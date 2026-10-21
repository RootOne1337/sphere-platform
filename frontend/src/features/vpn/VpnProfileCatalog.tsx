'use client';

import { useEffect, useRef, useState } from 'react';
import { Archive, FileKey2, History, Plus, RefreshCw, Search, Shield, Smartphone } from 'lucide-react';
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

  return <section aria-label="Каталог VPN-профилей" className="sphere-panel mb-6 overflow-hidden rounded-2xl border bg-card/60">
    <div className="flex flex-wrap items-start justify-between gap-4 border-b p-5">
      <div><h2 className="text-lg font-semibold tracking-tight">Библиотека профилей</h2><p className="mt-1 max-w-xl text-sm leading-relaxed text-muted-foreground">Конфигурации подключений с историей версий и отдельной политикой приложений.</p></div>
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" aria-label="Обновить профили" disabled={loading} onClick={() => setReload(v => v + 1)}><RefreshCw className={`h-4 w-4 ${loading ? 'motion-safe:animate-spin' : ''}`} /></Button>{canWrite && <Button size="sm" onClick={() => setImporting({})}><Plus className="mr-2 h-4 w-4" />Импорт профиля</Button>}</div>
    </div>
    <div className="flex flex-wrap items-center gap-3 p-4 sm:p-5">
      <div className="relative min-w-0 flex-1"><Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" /><input aria-label="Поиск VPN-профилей" placeholder="Найти профиль по названию" value={search} maxLength={120} className="h-10 w-full rounded-xl border bg-background/60 py-2 pl-9 pr-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onChange={e => { setSearch(e.target.value); setPage(1); }} /></div>
      <label className="flex items-center gap-2 rounded-xl border bg-background/40 px-3 py-2.5 text-xs"><input type="checkbox" checked={archived} onChange={e => { setArchived(e.target.checked); setPage(1); }} className="accent-primary" />Показывать архив</label>
    </div>
    {loading && <p role="status" className="px-5 pb-5 text-sm text-muted-foreground">Загружаем профили…</p>}
    {error && <p role="alert" className="mx-5 mb-5 rounded-xl border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive">{error}</p>}
    {fresh && !data.items.length && <div className="mx-4 mb-5 flex min-h-56 flex-col items-center justify-center rounded-2xl border border-dashed bg-muted/10 px-5 py-8 text-center"><span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border bg-background text-primary"><FileKey2 className="h-6 w-6" strokeWidth={1.5} /></span><p className="font-medium">{search ? 'Профилей с таким названием нет.' : 'Добавьте первый VPN-профиль'}</p><p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">{search ? 'Измените запрос или включите отображение архива.' : 'Импортируйте .conf от провайдера, выберите приложения и сохраните конфигурацию в зашифрованном каталоге.'}</p></div>}
    {data.items.length > 0 && <div className={`grid gap-4 px-4 pb-5 sm:px-5 lg:grid-cols-2 2xl:grid-cols-3 ${loading || error ? 'opacity-50' : ''}`}>{data.items.map(profile => <article key={profile.id} className="group flex min-w-0 flex-col overflow-hidden rounded-2xl border bg-background/40 transition-colors hover:border-primary/30">
      <div className="flex items-start justify-between gap-3 p-5"><div className="flex min-w-0 items-start gap-3"><span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-primary/15 bg-primary/10 text-primary"><FileKey2 className="h-5 w-5" strokeWidth={1.7} /></span><div className="min-w-0"><h3 className="break-words font-semibold">{profile.name}</h3><p className="mt-1 text-xs text-muted-foreground">{profile.protocol === 'amneziawg' ? 'AmneziaWG' : 'WireGuard'} {profile.protocol_version}</p></div></div><span className="shrink-0 rounded-lg border bg-muted/30 px-2 py-1 font-mono text-[11px] text-muted-foreground">v{profile.current_revision}</span></div>
      <div className="flex-1 px-5 pb-5">{profile.description && <p className="mb-4 break-words text-sm leading-relaxed text-muted-foreground">{profile.description}</p>}<div className="flex flex-wrap gap-2"><span className="inline-flex items-center gap-1.5 rounded-full bg-muted/70 px-2.5 py-1 text-xs text-muted-foreground"><Smartphone className="h-3.5 w-3.5" />Приложений: {profile.traffic_policy.included_packages.length}</span><span className="rounded-full bg-muted/70 px-2.5 py-1 text-xs text-muted-foreground">{profile.traffic_policy.ipv6 === 'tunnel' ? 'IPv4 + IPv6' : 'IPv6 заблокирован'}</span>{profile.is_archived && <span className="rounded-full bg-warning/10 px-2.5 py-1 text-xs text-warning">Архив</span>}</div><p className="mt-4 flex items-center gap-1.5 text-xs text-muted-foreground"><Shield className="h-3.5 w-3.5" />Политика: Sphere вне VPN</p></div>
      <div className="flex items-center justify-between gap-2 border-t bg-muted/10 px-3 py-2.5"><Button size="sm" variant="ghost" disabled={!fresh} onClick={() => setHistory(profile)}><History className="mr-2 h-4 w-4" />Версии</Button><div className="flex gap-1">{canWrite && !profile.is_archived && <><Button size="sm" variant="outline" disabled={!fresh} onClick={() => setImporting({ target: profile })}>Новая версия</Button><Button size="sm" variant="ghost" className="px-2 text-muted-foreground" aria-label={`Архивировать ${profile.name}`} disabled={!fresh} onClick={() => setArchive(profile)}><Archive className="h-4 w-4" /></Button></>}</div></div>
    </article>)}</div>}
    <div className="flex flex-wrap items-center justify-between gap-3 border-t px-5 py-3 text-xs text-muted-foreground"><span>{fresh ? `Всего ${data.total} · страница ${page}` : 'Состояние обновляется'}</span><div className="flex gap-2"><Button size="sm" variant="outline" disabled={!fresh || page <= 1} onClick={() => setPage(p => p - 1)}>Назад</Button><Button size="sm" variant="outline" disabled={!fresh || page * 10 >= data.total} onClick={() => setPage(p => p + 1)}>Далее</Button></div></div>
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
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}><DialogContent className="max-w-2xl" layout="workspace"><DialogHeader><DialogTitle className="flex items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border bg-primary/10 text-primary"><History className="h-5 w-5" /></span><span className="min-w-0 break-words">Версии · {profile.name}</span></DialogTitle><DialogDescription>История конфигураций без ключей. Старые версии не перезаписываются.</DialogDescription></DialogHeader>
    <DialogBody>
    {loading ? <p role="status" className="text-sm text-muted-foreground">Загружаем историю…</p> : error ? <p role="alert" className="rounded-xl border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive">История версий недоступна.</p> : <div className="divide-y rounded-xl border">{items.map(item => <div key={item.id} className="flex items-start gap-3 p-4 text-sm"><span className="rounded-lg border bg-muted/30 px-2.5 py-1 font-mono text-xs text-muted-foreground">v{item.revision}</span><div className="min-w-0"><p className="break-words font-medium">{item.name}</p><p className="mt-1 text-xs leading-relaxed text-muted-foreground">Протокол {item.protocol_version} · {new Date(item.created_at).toLocaleString('ru-RU', { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'short' })} UTC</p></div></div>)}{!items.length && <p className="p-5 text-sm text-muted-foreground">На этой странице нет версий.</p>}</div>}
    </DialogBody>
    <DialogFooter><span className="mr-auto self-center text-xs text-muted-foreground">Страница {page} · версий {total}</span><Button variant="outline" disabled={loading || page === 1} onClick={() => setPage(p => p - 1)}>Назад</Button><Button variant="outline" disabled={loading || error || page * 10 >= total} onClick={() => setPage(p => p + 1)}>Далее</Button></DialogFooter>
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
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}><DialogContent layout="workspace"><DialogHeader><DialogTitle className="flex items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border bg-muted text-muted-foreground"><Archive className="h-5 w-5" /></span>Архивировать профиль?</DialogTitle><DialogDescription>Профиль исчезнет из активного каталога. История и текущая сеть устройств сохранятся.</DialogDescription></DialogHeader>
    <DialogBody><div className="flex items-center gap-3 rounded-xl border bg-muted/15 p-4"><FileKey2 className="h-5 w-5 shrink-0 text-primary" /><p className="min-w-0 break-words text-sm font-medium">{profile.name}<span className="mt-1 block text-xs font-normal text-muted-foreground">Версия {profile.current_revision}</span></p></div>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}{done && !error && <p role="status" className="text-sm text-success">Профиль перенесён в архив.</p>}</DialogBody>
    <DialogFooter><Button variant="outline" onClick={onClose}>Закрыть</Button><Button disabled={pending || done} onClick={() => void archive()}>{pending ? 'Архивируем…' : 'В архив'}</Button></DialogFooter>
  </DialogContent></Dialog>;
}
