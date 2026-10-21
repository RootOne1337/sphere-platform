'use client';

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, ArrowDown, ArrowUp, ChevronLeft, ChevronRight, ExternalLink, RefreshCw, ShieldCheck, Smartphone } from 'lucide-react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/components/ui/button';
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { parseVpnRuntimePage, runtimeFreshness, vpnPhaseLabels, type VpnRuntimeDevice } from './runtimeTypes';

function time(value: string | number | null | undefined) {
  if (!value) return 'Не сообщено';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? 'Не подтверждено' : `${date.toISOString().replace('T', ' ').slice(0, 19)} UTC`;
}
function bytes(value: number | null | undefined) {
  if (value === undefined || value === null) return '—';
  if (value < 1024) return `${value} Б`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} КБ`;
  return `${(value / 1024 ** 2).toFixed(1)} МБ`;
}

export function AppVpnRuntimePanel() {
  const actor = useAuthStore(s => s.user); const session = useAuthStore(s => s.sessionVersion);
  const scope = `${actor?.org_id}:${actor?.id}:${actor?.role}:${session}`;
  const [search, setSearch] = useState(''); const [filter, setFilter] = useState(''); const [page, setPage] = useState(1);
  const [group, setGroup] = useState(''); const [selected, setSelected] = useState<string | null>(null); const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = setTimeout(() => setFilter(search), 250); return () => clearTimeout(timer); }, [search]);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 2000); return () => clearInterval(timer); }, []);
  const groups = useQuery<{ id: string; name: string }[]>({ queryKey: ['vpn-runtime-groups', scope], queryFn: async ({ signal }) => {
    const { data } = await api.get('/groups', { signal });
    if (!Array.isArray(data) || data.some(g => !g || typeof g.id !== 'string' || typeof g.name !== 'string')) throw new Error('groups_unavailable');
    return data;
  }, retry: false, enabled: Boolean(actor) });
  const query = useQuery({ queryKey: ['vpn-runtime', scope, filter, group, page], queryFn: async ({ signal }) => {
    const { data } = await api.get('/vpn/runtime', { signal, params: { page, page_size: 25, search: filter, group_id: group || undefined } });
    return parseVpnRuntimePage(data, page);
  }, refetchInterval: 5000, retry: false, enabled: Boolean(actor) });
  const data = query.data;
  const chosen = data?.items.find(d => d.device_id === selected);
  const fresh = (row: VpnRuntimeDevice) => data ? runtimeFreshness(row, data.as_of, now) : 'unknown';
  const confirmed = data?.items.filter(row => fresh(row) === 'fresh').length ?? 0;
  return <section aria-label="VPN на устройствах Android" className="mb-6 overflow-hidden rounded-2xl border bg-background/60">
    <header className="flex flex-wrap items-start justify-between gap-4 border-b p-4 sm:p-5">
      <div className="min-w-0"><h2 className="flex items-center gap-2 font-semibold"><Smartphone className="h-4 w-4 text-primary" /> VPN на устройствах</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">Состояние встроенного Android-сервиса. Назначение профиля и соединение с VPN проверяются отдельно.</p></div>
      <Button size="sm" variant="outline" disabled={query.isFetching} onClick={() => void query.refetch()}><RefreshCw className={`mr-2 h-4 w-4 ${query.isFetching ? 'motion-safe:animate-spin' : ''}`} />Обновить состояние</Button>
    </header>
    <div className="grid gap-3 border-b bg-muted/20 p-4 sm:grid-cols-3">
      <div><p className="text-xs text-muted-foreground">Устройств по фильтру</p><p className="mt-1 text-xl font-semibold tabular-nums">{data?.total ?? '—'}</p></div>
      <div><p className="text-xs text-muted-foreground">Свежих отчётов на странице</p><p className="mt-1 text-xl font-semibold tabular-nums">{data ? `${confirmed} / ${data.items.length}` : '—'}</p></div>
      <div className="flex items-start gap-2 text-sm text-muted-foreground"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><p>Политика туннеля: выбранные приложения. Управление Sphere должно идти вне VPN.</p></div>
    </div>
    <div className="flex flex-col gap-3 p-4 sm:flex-row">
      <input aria-label="Поиск устройств VPN" placeholder="Найти устройство по имени" value={search} maxLength={120} onChange={e => { setSearch(e.target.value); setPage(1); }} className="min-w-0 flex-1 rounded-lg border bg-background px-3 py-2 text-sm" />
      <select aria-label="Группа устройств VPN" value={group} onChange={e => { setGroup(e.target.value); setPage(1); setSelected(null); }} disabled={!groups.data} className="max-w-full rounded-lg border bg-background px-3 py-2 text-sm sm:w-56"><option value="">{groups.isError ? 'Группы недоступны' : 'Все группы'}</option>{groups.data?.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}</select>
    </div>
    {query.isLoading && <p role="status" className="px-4 pb-4 text-sm text-muted-foreground">Получаем состояние устройств…</p>}
    {query.isError && <p role="alert" className="px-4 pb-4 text-sm text-destructive">Состояние VPN недоступно. Предыдущие данные не подтверждают текущее подключение.</p>}
    {data && !data.items.length && <p className="px-4 pb-5 text-sm text-muted-foreground">Устройств по этому фильтру нет.</p>}
    {!!data?.items.length && <div className={`overflow-x-auto ${query.isError ? 'opacity-50' : ''}`}><table className="w-full text-left text-sm"><thead className="border-y bg-muted/25 text-xs text-muted-foreground"><tr><th className="px-4 py-3 font-medium">Устройство</th><th className="px-4 py-3 font-medium">Android VPN</th><th className="hidden px-4 py-3 font-medium lg:table-cell">Handshake</th><th className="hidden px-4 py-3 font-medium xl:table-cell">Принято / отправлено</th><th className="w-24 px-4 py-3 font-medium"><span className="sr-only">Подробности</span></th></tr></thead>
      <tbody>{data.items.map(row => { const state = fresh(row); const sample = row.observation?.snapshot; return <tr key={row.device_id} className="border-b last:border-0 hover:bg-muted/20 motion-safe:transition-colors">
        <td className="max-w-56 px-4 py-3"><p className="break-words font-medium">{row.name}</p><p className="mt-1 text-xs text-muted-foreground">{row.model || 'Модель не сообщена'} · {row.status === 'offline' ? 'Не в сети' : row.status === 'connecting' ? 'Подключается' : row.status === 'error' ? 'Ошибка связи' : 'На связи'}</p></td>
        <td className="max-w-72 px-4 py-3"><p className={state === 'fresh' ? 'font-medium' : 'text-muted-foreground'}>{sample ? vpnPhaseLabels[sample.phase] : 'Нет отчёта от сервиса'}</p><p className={`mt-1 text-xs ${state === 'fresh' ? 'text-success' : 'text-muted-foreground'}`}>{query.isError ? 'Связь с API потеряна' : state === 'fresh' ? 'Свежий отчёт' : state === 'stale' ? 'Отчёт устарел' : 'Текущее состояние не подтверждено'}</p></td>
        <td className="hidden px-4 py-3 text-xs text-muted-foreground lg:table-cell">{time(sample?.handshakeEpochSeconds ? sample.handshakeEpochSeconds * 1000 : null)}</td>
        <td className="hidden px-4 py-3 font-mono text-xs xl:table-cell">{bytes(sample?.rxBytes)} / {bytes(sample?.txBytes)}</td>
        <td className="px-4 py-3"><Button size="sm" variant="ghost" aria-label={`Диагностика VPN ${row.name}`} onClick={() => setSelected(row.device_id)}><Activity className="h-4 w-4" /></Button></td>
      </tr>; })}</tbody></table></div>}
    <footer className="flex flex-wrap items-center justify-between gap-2 border-t p-3 text-xs text-muted-foreground"><span>Страница {page}{data ? ` · показано ${data.items.length} из ${data.total}` : ''} · опрос 5 с</span><div className="flex gap-2"><Button size="sm" variant="outline" aria-label="Предыдущие устройства VPN" disabled={query.isFetching || page <= 1} onClick={() => setPage(p => p - 1)}><ChevronLeft className="h-4 w-4" /></Button><Button size="sm" variant="outline" aria-label="Следующие устройства VPN" disabled={query.isFetching || !data || page * data.page_size >= data.total} onClick={() => setPage(p => p + 1)}><ChevronRight className="h-4 w-4" /></Button></div></footer>
    {chosen && <RuntimeDetails row={chosen} currentFreshness={query.isError ? 'unknown' : fresh(chosen)} onClose={() => setSelected(null)} />}
  </section>;
}

function RuntimeDetails({ row, currentFreshness, onClose }: { row: VpnRuntimeDevice; currentFreshness: string; onClose: () => void }) {
  const observation = row.observation; const sample = observation?.snapshot;
  const fields = [
    ['Сервис', sample ? vpnPhaseLabels[sample.phase] : 'Отчёт не получен'], ['Свежесть', currentFreshness === 'fresh' ? 'Подтверждён свежий отчёт' : 'Текущее состояние не подтверждено'],
    ['Agent', row.agent_version ?? 'Не сообщено'], ['Android', row.android_version ?? 'Не сообщено'],
    ['Снимок состояния на устройстве', time(sample?.sampledAtEpochMs)], ['Получено сервером', time(observation?.received_at)],
    ['Последний handshake', time(sample?.handshakeEpochSeconds ? sample.handshakeEpochSeconds * 1000 : null)], ['Последний heartbeat Sphere', time(row.last_heartbeat)],
    ['Native provider', sample?.nativeVersion ?? 'Не сообщено'], ['Процесс VPN', sample?.providerPid?.toString() ?? 'Не сообщено'],
    ['Сессия туннеля', sample?.sessionId ?? 'Не сообщено'], ['Версия профиля', sample?.profileRevisionId ?? 'Не сообщено'],
    ['Последний запрос', sample?.requestId ?? 'Не сообщено'], ['Причина / код', sample?.reason ?? 'Не сообщено'],
  ];
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}><DialogContent className="max-w-3xl"><DialogHeader><DialogTitle>VPN · {row.name}</DialogTitle><DialogDescription>Диагностика встроенного сервиса. Handshake сам по себе не подтверждает доступность игры или внешний IP.</DialogDescription></DialogHeader><DialogBody>
    <div className="mb-4 grid grid-cols-2 gap-3"><div className="rounded-xl border p-4"><p className="flex items-center gap-2 text-xs text-muted-foreground"><ArrowDown className="h-4 w-4" />Принято туннелем</p><p className="mt-2 text-xl font-semibold tabular-nums">{bytes(sample?.rxBytes)}</p></div><div className="rounded-xl border p-4"><p className="flex items-center gap-2 text-xs text-muted-foreground"><ArrowUp className="h-4 w-4" />Отправлено туннелем</p><p className="mt-2 text-xl font-semibold tabular-nums">{bytes(sample?.txBytes)}</p></div></div>
    <dl className="grid gap-3 sm:grid-cols-2">{fields.map(([label, value]) => <div key={label} className="min-w-0 rounded-lg border p-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-words text-sm [overflow-wrap:anywhere]">{value}</dd></div>)}</dl>
    <p className="my-4 text-xs text-muted-foreground">Счётчики накоплены текущим native-туннелем и могут сброситься при его замене. Отсутствие отчёта не означает, что приложения вышли в сеть напрямую.</p>
    <Button variant="outline" asChild><Link href={`/devices/${row.device_id}`}><ExternalLink className="mr-2 h-4 w-4" />Открыть устройство</Link></Button>
  </DialogBody></DialogContent></Dialog>;
}
