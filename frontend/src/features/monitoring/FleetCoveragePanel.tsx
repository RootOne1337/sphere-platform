'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Radio, RefreshCw } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { API_POLL_INTERVALS } from '@/lib/queryPollIntervals';
import { Button } from '@/src/shared/ui/button';
import { type CoverageKey, type CoverageState, parseFleetCoverage } from './fleetCoverageTypes';

const STATES: Record<CoverageState, string> = {
    ready: 'Срез получен', unavailable: 'Источник недоступен', forbidden: 'Нет разрешения VPN',
    limited: 'Превышен бюджет сбора', unmeasured: 'Проверки не подключены',
};
const PANELS: Array<{ key: CoverageKey; title: string; note: string; fields: Array<[string, string]> }> = [
    { key: 'inventory', title: 'Инвентарь организации', note: 'SQL · только активные зарегистрированные устройства текущей организации.', fields: [['total', 'Устройств']] },
    { key: 'presence', title: 'Связь с Android', note: 'Redis · online/busy требуют текущий сеанс и heartbeat моложе 120 с. Отсутствующий или повреждённый отчёт — неизвестно.', fields: [['online', 'Онлайн'], ['busy', 'Заняты'], ['connecting', 'Подключаются'], ['offline', 'Сообщили offline'], ['error', 'Сообщили ошибку'], ['unknown', 'Не подтверждено']] },
    { key: 'android_vpn', title: 'VPN · отчёты Android', note: 'Состояние VPN-службы агента · собственное время приёма и текущий сеанс. Это не проверка трафика или внешнего IP.', fields: [['active', 'Включён'], ['inactive', 'Выключен'], ['stale', 'Отчёт устарел'], ['unknown', 'Нет подтверждения']] },
    { key: 'vpn_assignment', title: 'VPN · назначения', note: 'SQL · все peers организации. Назначение не подтверждает применение на Android. Последняя строка — подмножество assigned.', fields: [['assigned', 'Назначены'], ['provisioning', 'Настраиваются'], ['revoking', 'Отзываются'], ['error', 'Ошибка'], ['free', 'Освобождены'], ['outside_active_inventory', 'Assigned вне активного парка']] },
    { key: 'handshakes', title: 'VPN · сохранённые handshakes', note: 'SQL · assigned peers активного парка. Сохранённый handshake моложе 180 с; текущий опрос роутера здесь не выполняется.', fields: [['recent', 'Недавний + active flag'], ['stale', 'Старше срока'], ['unknown', 'Нет / время в будущем'], ['inactive', 'Недавний без active flag']] },
    { key: 'transport_tunnels', title: 'Публичный транспорт', note: 'Tuna / Cloudflare · проверки провайдеров ещё не подключены. Android VPN и presence не подменяют состояние публичного туннеля.', fields: [] },
];
function time(value: string) {
    return `${new Date(value).toLocaleTimeString('ru-RU', { timeZone: 'UTC' })} UTC`;
}

export function FleetCoveragePanel() {
    const user = useAuthStore(state => state.user);
    const sessionVersion = useAuthStore(state => state.sessionVersion);
    const [now, setNow] = useState(Date.now);
    const observation = useQuery({
        queryKey: ['fleet-coverage', user?.org_id, user?.id, user?.role, sessionVersion],
        queryFn: async ({ signal }) => parseFleetCoverage((await api.get('/monitoring/fleet-coverage', { signal, timeout: 10000 })).data, user!.org_id),
        enabled: !!user?.org_id, retry: false,
        refetchInterval: API_POLL_INTERVALS.fleetCoverageMs, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always',
    });
    useEffect(() => {
        const tick = () => setNow(Date.now());
        const timer = setInterval(tick, 5000);
        document.addEventListener('visibilitychange', tick);
        return () => { clearInterval(timer); document.removeEventListener('visibilitychange', tick); };
    }, []);
    if (!user?.org_id) return null;
    const at = Date.parse(observation.data?.generated_at ?? '');
    const stale = !!observation.data && (!Number.isFinite(at) || now - at > 45000 || at > now + 5000);
    const data = observation.isError || stale ? undefined : observation.data;
    return <section aria-labelledby="fleet-coverage-title" className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0"><h2 id="fleet-coverage-title" className="flex items-center gap-2 text-lg font-semibold"><Radio className="h-4 w-4 text-primary" aria-hidden="true" />Покрытие парка и VPN</h2>
                <p className="mt-1 max-w-4xl text-xs leading-relaxed text-muted-foreground">Текущая организация · единица: устройства / peers · события связи и VPN обновляют открытый срез; резервный опрос каждые 15 с. SQL и Redis читаются последовательно, общей транзакции между ними нет.</p></div>
            <Button variant="outline" size="sm" onClick={() => void observation.refetch()} disabled={observation.isFetching} aria-label="Обновить покрытие парка"><RefreshCw className={`mr-2 h-4 w-4 ${observation.isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`} aria-hidden="true" />Обновить</Button>
        </div>
        {observation.isLoading && <p role="status">Получаем покрытие текущей организации…</p>}
        {(observation.isError || stale) && <p role="alert" className="rounded-xl border border-amber-300 bg-amber-50/60 p-4 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">{stale && !observation.isError ? 'Срез покрытия устарел.' : 'Не удалось подтвердить покрытие текущей организации.'} Предыдущие числа скрыты. Запрос повторяется автоматически.</p>}
        {data && <>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{PANELS.map(panel => {
                const signal = data[panel.key];
                return <article key={panel.key} aria-label={panel.title} className="min-w-0 rounded-xl border border-border/80 bg-card p-4 shadow-sm">
                    <h3 className="text-sm font-semibold">{panel.title}</h3>
                    <p className={`mt-2 text-xs font-medium ${signal.state === 'ready' ? 'text-muted-foreground' : 'text-amber-800 dark:text-amber-300'}`}>{STATES[signal.state]}</p>
                    {signal.counts ? <dl className="mt-3 grid gap-2">{panel.fields.map(([key, label]) => <div key={key} className="flex items-baseline justify-between gap-3 text-sm"><dt className="min-w-0 text-muted-foreground">{label}</dt><dd className="shrink-0 font-mono font-semibold tabular-nums">{signal.counts![key].toLocaleString('ru-RU')}</dd></div>)}</dl>
                        : <p className="mt-3 text-sm text-muted-foreground">Нет подтверждённых измерений</p>}
                    <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{panel.note}</p>
                    {signal.observed_at && <p className="mt-3 text-[11px] text-muted-foreground">Срез источника: {time(signal.observed_at)}</p>}
                </article>;
            })}</div>
            <footer className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground">
                <p>Сформировано {time(data.generated_at)} · до {data.max_inventory_devices.toLocaleString('ru-RU')} устройств за срез · неизвестно не означает ноль или исправность.</p>
                <div className="flex gap-4"><Link href="/devices" className="text-primary hover:underline">Открыть парк</Link><Link href="/vpn" className="text-primary hover:underline">Назначения VPN</Link></div>
            </footer>
        </>}
    </section>;
}
