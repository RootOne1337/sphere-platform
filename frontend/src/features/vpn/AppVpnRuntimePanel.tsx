'use client';

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, ArrowDown, ArrowUp, ArrowUpRight, ChevronLeft, ChevronRight, Clock3, ExternalLink, RefreshCw, Search, ShieldCheck, Smartphone } from 'lucide-react';
import Link from 'next/link';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/components/ui/button';
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { parseVpnRuntimePage, runtimeFreshness, vpnPhaseLabels, type VpnRuntimeDevice } from './runtimeTypes';
import { currentVpnRate, observeVpnRates, type VpnRate, type VpnRateHistory } from './runtimeRates';

function time(value: string | number | null | undefined) {
  if (!value) return 'Не сообщено';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? 'Не подтверждено' : `${date.toISOString().replace('T', ' ').slice(0, 19)} UTC`;
}
function bytes(value: number | null | undefined) {
  if (value === undefined || value === null) return '—';
  if (value < 1024) return `${value.toLocaleString('ru-RU', { maximumFractionDigits: 1 })} Б`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} КБ`;
  return `${(value / 1024 ** 2).toFixed(1)} МБ`;
}
function phaseStyle(row: VpnRuntimeDevice, fresh: boolean) {
  const phase = row.observation?.snapshot.phase;
  if (!fresh || !phase || ['IDLE', 'DISCONNECTED_CONFIRMED'].includes(phase)) return 'bg-muted text-muted-foreground';
  if (phase === 'HANDSHAKE_CONFIRMED') return 'bg-success/10 text-success';
  if (['UNKNOWN_GUARD_HELD', 'FAILED_GUARD_HELD', 'GUARD_UNCONFIRMED', 'REVOKED_GUARD_HELD', 'RECONCILIATION_REQUIRED', 'STATUS_UNKNOWN', 'OPERATION_REJECTED', 'OUTCOME_UNKNOWN'].includes(phase)) return 'bg-destructive/10 text-destructive';
  return 'bg-warning/10 text-warning';
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
  const rateScope = JSON.stringify([scope, filter, group, page]);
  const [rateState, setRateState] = useState<{ scope: string; history: VpnRateHistory }>({ scope: '', history: new Map() });
  useEffect(() => {
    setRateState(previous => ({ scope: rateScope, history: data && !query.isError
      ? observeVpnRates(previous.scope === rateScope ? previous.history : new Map(), data, Date.now()) : new Map() }));
  }, [data, query.isError, rateScope]);
  const chosen = data?.items.find(d => d.device_id === selected);
  // A query can complete between clock ticks. Use its render time immediately;
  // the interval still makes retained data expire when no response arrives.
  const renderedAt = Math.max(now, Date.now());
  const fresh = (row: VpnRuntimeDevice) => data ? runtimeFreshness(row, data.as_of, renderedAt) : 'unknown';
  const rate = (row: VpnRuntimeDevice) => data && !query.isError && rateState.scope === rateScope
    ? currentVpnRate(rateState.history, row, data.as_of, renderedAt) : null;
  const confirmed = data?.items.filter(row => fresh(row) === 'fresh').length ?? 0;
  return <section aria-label="VPN на устройствах Android" className="sphere-panel mb-6 overflow-hidden rounded-2xl border bg-card/60">
    <header className="flex items-start justify-between gap-4 border-b p-4 sm:p-5">
      <div className="min-w-0 flex-1"><h2 className="text-base font-semibold tracking-tight sm:text-lg">Подключения устройств</h2>
        <p className="mt-1 hidden max-w-2xl text-sm leading-relaxed text-muted-foreground sm:block">Состояние Android-сервиса, сетевые счётчики и диагностика соединения.</p></div>
      <Button size="sm" variant="outline" aria-label="Обновить состояние" className="h-9 shrink-0 px-2.5 sm:px-3" disabled={query.isFetching} onClick={() => void query.refetch()}><RefreshCw className={`h-4 w-4 sm:mr-2 ${query.isFetching ? 'motion-safe:animate-spin' : ''}`} /><span className="hidden sm:inline">Обновить</span></Button>
    </header>
    <div className="grid grid-cols-2 gap-4 border-b bg-muted/15 p-4 sm:grid-cols-3 sm:p-5">
      <div className="flex items-center gap-3"><span className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-xl border bg-background/60 sm:flex"><Smartphone className="h-4 w-4 text-muted-foreground" /></span><div><p className="text-xs text-muted-foreground">Устройств по фильтру</p><p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{data?.total ?? '—'}</p></div></div>
      <div className="flex items-center gap-3"><span className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-xl border bg-background/60 sm:flex"><Activity className="h-4 w-4 text-primary" /></span><div><p className="text-xs text-muted-foreground">Свежих отчётов на странице</p><p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{data ? confirmed : '—'}{data && <span className="ml-1 text-sm font-normal text-muted-foreground">/ {data.items.length}</span>}</p></div></div>
      <div className="col-span-2 flex items-center gap-2 text-xs text-muted-foreground sm:col-span-1"><ShieldCheck className="h-4 w-4 shrink-0 text-primary" /><p>Sphere, видео и управление — напрямую.<br /> Область VPN — в диагностике устройства.</p></div>
    </div>
    <div className="flex gap-2 p-4 sm:gap-3">
      <div className="relative min-w-0 flex-1"><Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" /><input aria-label="Поиск устройств VPN" placeholder="Найти устройство по имени" value={search} maxLength={120} onChange={e => { setSearch(e.target.value); setPage(1); }} className="h-10 w-full min-w-0 rounded-xl border bg-background/60 py-2 pl-9 pr-3 text-sm transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" /></div>
      <select aria-label="Группа устройств VPN" value={group} onChange={e => { setGroup(e.target.value); setPage(1); setSelected(null); }} disabled={!groups.data} className="w-32 max-w-full rounded-xl border bg-background/60 px-2 py-2 text-xs sm:w-56 sm:px-3 sm:text-sm"><option value="">{groups.isError ? 'Группы недоступны' : 'Все группы'}</option>{groups.data?.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}</select>
    </div>
    {query.isLoading && <p role="status" className="px-4 pb-4 text-sm text-muted-foreground">Получаем состояние устройств…</p>}
    {query.isError && <p role="alert" className="px-4 pb-4 text-sm text-destructive">Состояние VPN недоступно. Предыдущие данные не подтверждают текущее подключение.</p>}
    {data && !data.items.length && <p className="px-4 pb-5 text-sm text-muted-foreground">Устройств по этому фильтру нет.</p>}
    {!!data?.items.length && <div className={`overflow-x-auto ${query.isError ? 'opacity-50' : ''}`}><table className="block w-full text-left text-sm md:table"><thead className="hidden border-y bg-muted/20 text-xs text-muted-foreground md:table-header-group"><tr><th className="px-5 py-3 font-medium">Устройство</th><th className="px-5 py-3 font-medium">Android VPN</th><th className="hidden px-5 py-3 font-medium lg:table-cell">Последний handshake</th><th className="hidden px-5 py-3 font-medium xl:table-cell">Принято / отправлено</th><th className="w-20 px-5 py-3 font-medium"><span className="sr-only">Подробности</span></th></tr></thead>
      <tbody className="block md:table-row-group">{data.items.map(row => { const state = fresh(row); const sample = row.observation?.snapshot; const speed = rate(row); return <tr key={row.device_id} className="group grid grid-cols-[minmax(0,1fr)_2.5rem] gap-x-2 gap-y-3 border-b px-4 py-4 last:border-0 hover:bg-muted/20 motion-safe:transition-colors md:table-row md:p-0">
        <td className="col-start-1 row-start-1 min-w-0 md:max-w-64 md:px-5 md:py-4"><div className="flex min-w-0 items-center gap-3"><span className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-xl border bg-muted/30 text-muted-foreground lg:flex"><Smartphone className="h-4 w-4" /></span><div className="min-w-0"><p className="break-words font-medium">{row.name}</p><p className="mt-1 text-xs text-muted-foreground">{row.model || 'Модель не сообщена'} · {row.status === 'offline' ? 'Не в сети' : row.status === 'connecting' ? 'Подключается' : row.status === 'error' ? 'Ошибка связи' : 'На связи'}</p></div></div></td>
        <td className="col-start-1 row-start-2 min-w-0 md:max-w-72 md:px-5 md:py-4"><p className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-xs font-medium ${phaseStyle(row, state === 'fresh' && !query.isError)}`}><span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" />{sample ? vpnPhaseLabels[sample.phase] : 'Нет отчёта от сервиса'}</p><p className="mt-1.5 flex items-center gap-1 text-xs text-muted-foreground"><Clock3 className="h-3 w-3 shrink-0" />{query.isError ? 'Связь с API потеряна' : state === 'fresh' ? 'Свежий отчёт' : state === 'stale' ? 'Отчёт устарел' : 'Текущее состояние не подтверждено'}</p></td>
        <td className="hidden px-4 py-3 text-xs text-muted-foreground lg:table-cell">{time(sample?.handshakeEpochSeconds ? sample.handshakeEpochSeconds * 1000 : null)}</td>
        <td className="hidden px-4 py-3 font-mono text-xs xl:table-cell"><p>{bytes(sample?.rxBytes)} / {bytes(sample?.txBytes)}</p><p className="mt-1.5 text-muted-foreground">{speed ? `↓ ${bytes(speed.rx)}/с · ↑ ${bytes(speed.tx)}/с` : 'Скорость: нет пары замеров'}</p></td>
        <td className="col-start-2 row-span-2 row-start-1 self-start md:px-4 md:py-3"><Button size="sm" variant="ghost" className="h-10 w-10 rounded-xl p-0 text-muted-foreground hover:text-primary" aria-label={`Диагностика VPN ${row.name}`} onClick={() => setSelected(row.device_id)}><ArrowUpRight className="h-4 w-4" /></Button></td>
      </tr>; })}</tbody></table></div>}
    <footer className="flex flex-wrap items-center justify-between gap-2 border-t p-3 text-xs text-muted-foreground"><span>Страница {page}{data ? ` · показано ${data.items.length} из ${data.total}` : ''} · опрос 5 с</span><div className="flex gap-2"><Button size="sm" variant="outline" aria-label="Предыдущие устройства VPN" disabled={query.isFetching || page <= 1} onClick={() => setPage(p => p - 1)}><ChevronLeft className="h-4 w-4" /></Button><Button size="sm" variant="outline" aria-label="Следующие устройства VPN" disabled={query.isFetching || !data || page * data.page_size >= data.total} onClick={() => setPage(p => p + 1)}><ChevronRight className="h-4 w-4" /></Button></div></footer>
    {chosen && <RuntimeDetails row={chosen} rate={rate(chosen)} currentFreshness={query.isError ? 'unknown' : fresh(chosen)} onClose={() => setSelected(null)} />}
  </section>;
}

function RuntimeDetails({ row, rate, currentFreshness, onClose }: { row: VpnRuntimeDevice; rate: VpnRate | null; currentFreshness: string; onClose: () => void }) {
  const observation = row.observation; const sample = observation?.snapshot;
  const fields = [
    ['Сервис', sample ? vpnPhaseLabels[sample.phase] : 'Отчёт не получен'], ['Свежесть', currentFreshness === 'fresh' ? 'Подтверждён свежий отчёт' : 'Текущее состояние не подтверждено'],
    ['Область VPN', sample?.trafficMode === 'all_apps_except_control' ? 'Все приложения, кроме Sphere' : sample?.trafficMode === 'selected_apps' ? 'Выбранные приложения' : 'Не сообщено агентом'],
    ['Agent', row.agent_version ?? 'Не сообщено'], ['Android', row.android_version ?? 'Не сообщено'],
    ['Снимок состояния на устройстве', time(sample?.sampledAtEpochMs)], ['Получено сервером', time(observation?.received_at)],
    ['Последний handshake', time(sample?.handshakeEpochSeconds ? sample.handshakeEpochSeconds * 1000 : null)], ['Последний heartbeat Sphere', time(row.last_heartbeat)],
    ['Native provider', sample?.nativeVersion ?? 'Не сообщено'], ['Процесс VPN', sample?.providerPid?.toString() ?? 'Не сообщено'],
    ['Сессия туннеля', sample?.sessionId ?? 'Не сообщено'], ['Версия профиля', sample?.profileRevisionId ?? 'Не сообщено'],
    ['Последний запрос', sample?.requestId ?? 'Не сообщено'], ['Причина / код', sample?.reason ?? 'Не сообщено'],
  ];
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}><DialogContent className="max-w-3xl" layout="workspace"><DialogHeader><DialogTitle className="flex items-center gap-3"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border bg-primary/10 text-primary"><Smartphone className="h-5 w-5" /></span><span className="min-w-0 break-words">{row.name}<span className="mt-1 block text-xs font-normal text-muted-foreground">Соединение VPN · диагностика устройства</span></span></DialogTitle><DialogDescription>Диагностика встроенного сервиса. Handshake сам по себе не подтверждает доступность игры или внешний IP.</DialogDescription></DialogHeader><DialogBody>
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/20 px-4 py-3"><div><p className="text-sm font-medium">{sample ? vpnPhaseLabels[sample.phase] : 'Нет отчёта от VPN-сервиса'}</p><p className="mt-1 text-xs text-muted-foreground">{row.model ?? 'Модель не сообщена'} · Android {row.android_version ?? '—'}</p></div><span className={`rounded-full px-2.5 py-1 text-xs font-medium ${currentFreshness === 'fresh' ? 'bg-primary/10 text-primary' : 'bg-warning/10 text-warning'}`}>{currentFreshness === 'fresh' ? 'Свежий отчёт' : currentFreshness === 'stale' ? 'Отчёт устарел' : 'Нет актуального отчёта'}</span></div>
    <div className="grid grid-cols-2 gap-3"><div className="rounded-xl border bg-muted/10 p-4"><p className="flex items-center gap-2 text-xs text-muted-foreground"><ArrowDown className="h-4 w-4 text-primary" />Принято туннелем</p><p className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">{bytes(sample?.rxBytes)}</p><p className="mt-2 text-xs text-muted-foreground">{rate ? `${bytes(rate.rx)}/с` : 'Скорость пока не измерена'}</p></div><div className="rounded-xl border bg-muted/10 p-4"><p className="flex items-center gap-2 text-xs text-muted-foreground"><ArrowUp className="h-4 w-4 text-primary" />Отправлено туннелем</p><p className="mt-2 text-2xl font-semibold tracking-tight tabular-nums">{bytes(sample?.txBytes)}</p><p className="mt-2 text-xs text-muted-foreground">{rate ? `${bytes(rate.tx)}/с` : 'Скорость пока не измерена'}</p></div></div>
    <p className="text-xs leading-relaxed text-muted-foreground">{rate ? `Средняя скорость между двумя замерами Android за ${(rate.intervalMs / 1000).toLocaleString('ru-RU')} с. Это трафик туннеля целиком.` : 'Для скорости нужны два свежих замера одного туннеля. После переподключения, паузы или сброса счётчиков измерение начинается заново.'}</p>
    <Tabs defaultValue="connection"><TabsList className="mb-3 grid w-full grid-cols-2"><TabsTrigger value="connection">Соединение</TabsTrigger><TabsTrigger value="identifiers">Идентификаторы</TabsTrigger></TabsList><TabsContent value="connection"><dl className="divide-y rounded-xl border px-4">{fields.slice(2, 10).map(([label, value]) => <div key={label} className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-4 py-3"><dt className="text-xs leading-relaxed text-muted-foreground">{label}</dt><dd className="break-words text-right text-sm [overflow-wrap:anywhere]">{value}</dd></div>)}</dl></TabsContent><TabsContent value="identifiers"><dl className="space-y-4 rounded-xl border p-4">{fields.slice(10).map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-words font-mono text-xs leading-relaxed [overflow-wrap:anywhere]">{value}</dd></div>)}</dl></TabsContent></Tabs>
    <p className="text-xs leading-relaxed text-muted-foreground">Счётчики относятся к текущему туннелю. При его замене они могут сброситься. Внешний IP и доступность приложений проверяются отдельно.</p>
  </DialogBody><DialogFooter><Button variant="outline" onClick={onClose}>Готово</Button><Button asChild><Link href={`/devices/${row.device_id}`}><ExternalLink className="mr-2 h-4 w-4" />Открыть устройство</Link></Button></DialogFooter></DialogContent></Dialog>;

}
