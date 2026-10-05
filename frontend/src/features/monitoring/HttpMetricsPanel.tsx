'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowRight, RefreshCw, Search } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { API_POLL_INTERVALS } from '@/lib/queryPollIntervals';
import { Button } from '@/src/shared/ui/button';
import { Card, CardContent } from '@/src/shared/ui/card';
import { HistoryChart } from './HistoryChart';
import type { HistoryWindow } from './observabilityTypes';
import type { HttpMetricsSnapshot, HttpSignal, MeasurementState } from './httpMetricsTypes';

const LABELS: Record<MeasurementState, string> = { ready: 'Измерено', empty: 'Нет измерения', partial: 'Неполные данные', error: 'Ошибка источника', stale: 'Устаревшие данные' };
const fmt = (value: number | null, unit: string) => value === null ? 'Нет измерения' : `${value.toLocaleString('ru-RU', { maximumFractionDigits: 3 })} ${unit}`;
function Signal({ title, unit, signal, step }: { title: string; unit: string; signal: HttpSignal; step: number }) {
    return <div role="group" className="min-w-0 space-y-2" aria-label={title}>
        <HistoryChart title={title} unit={unit} series={signal.series} step={step} />
        <p className={`px-1 text-xs ${signal.state === 'ready' ? 'text-muted-foreground' : 'text-amber-800 dark:text-amber-300'}`}><strong>{LABELS[signal.state]}</strong>{signal.reason && ` · ${signal.reason}`}</p>
    </div>;
}
export function HttpMetricsPanel({ window, now }: { window: HistoryWindow; now: number }) {
    const user = useAuthStore(state => state.user);
    const sessionVersion = useAuthStore(state => state.sessionVersion);
    const [filter, setFilter] = useState('');
    const [selectedKey, setSelectedKey] = useState<string | null>(null);
    const observation = useQuery<HttpMetricsSnapshot>({
        queryKey: ['platform-http-metrics', user?.id, sessionVersion, window],
        queryFn: async ({ signal }) => (await api.get<HttpMetricsSnapshot>('/api/observability/http', { baseURL: '', params: { window }, timeout: 10000, signal })).data,
        enabled: user?.role === 'super_admin', retry: false,
        refetchInterval: API_POLL_INTERVALS.prometheusMs, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always',
    });
    if (user?.role !== 'super_admin') return null;
    const at = Date.parse(observation.data?.observedAt ?? '');
    const scrapeAt = observation.data?.lastScrape ? Date.parse(observation.data.lastScrape) : null;
    const delayed = !!observation.data && (!Number.isFinite(at) || now - at > 45000 || at > now + 5000 || (scrapeAt !== null && (!Number.isFinite(scrapeAt) || now - scrapeAt > 45000 || scrapeAt > now + 5000)));
    const data = observation.isError || delayed ? undefined : observation.data;
    const selected = data?.endpoints.rows.find(row => `${row.method} ${row.endpoint}` === selectedKey);
    const rows = data?.endpoints.rows.filter(row => `${row.method} ${row.endpoint}`.toLowerCase().includes(filter.trim().toLowerCase())) ?? [];
    const panels = [{ key: 'rps', title: 'HTTP · запросы в секунду', unit: 'запр/с' }, { key: 'p95', title: 'HTTP · p95 до заголовков', unit: 'с' }, { key: 'serverErrors', title: 'HTTP · ошибки 5xx', unit: 'запр/с' }, { key: 'clientErrors', title: 'HTTP · ответы 4xx', unit: 'запр/с' }] as const;
    return <section aria-labelledby="http-metrics-title" className="space-y-4">
        <div className="flex items-start justify-between gap-3"><div><h3 id="http-metrics-title" className="text-lg font-semibold">Backend · HTTP-нагрузка и задержки</h3><p className="mt-1 max-w-4xl text-xs leading-relaxed text-muted-foreground">Все worker-процессы backend · скользящее окно 5 минут · история {window} · p95 по histogram является оценкой. Проверки здоровья и /metrics исключены. Время измеряется до заголовков ответа; передача тела, WebSocket, FPS и отклик Android сюда не входят.</p></div><Button variant="outline" size="icon" aria-label="Обновить HTTP-метрики" onClick={() => void observation.refetch()} disabled={observation.isFetching}><RefreshCw className={`h-4 w-4 ${observation.isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`} /></Button></div>
        {observation.isLoading && <p role="status" className="text-sm text-muted-foreground">Получаем HTTP-метрики…</p>}
        {(observation.isError || delayed) && <p role="alert" className="rounded-lg border border-amber-300 p-4 text-sm text-amber-900 dark:text-amber-200">{delayed && !observation.isError ? 'Срез HTTP-метрик устарел или его время некорректно.' : 'Не удалось подтвердить текущие HTTP-метрики.'} Прежние значения скрыты. Повторяем запрос автоматически.</p>}
        {data && <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{panels.map(panel => <Signal key={panel.key} title={panel.title} unit={panel.unit} signal={data.metrics[panel.key]} step={data.stepSeconds} />)}</div>
            <div className="grid items-start gap-4 2xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
                <Card className="min-w-0 overflow-hidden rounded-xl"><CardContent className="space-y-4 p-4 sm:p-5">
                    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center"><div><h4 className="font-medium">Маршруты HTTP</h4><p className="mt-1 text-xs text-muted-foreground">До 30 маршрутов с наибольшим RPS за 5 минут. Выберите строку для разбора.</p></div><label className="relative block"><span className="sr-only">Поиск HTTP-маршрута</span><Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><input type="search" value={filter} onChange={event => setFilter(event.target.value)} placeholder="Метод или маршрут" maxLength={256} className="h-9 w-full rounded-lg border bg-background pl-9 pr-3 text-sm sm:w-60" /></label></div>
                    {data.endpoints.state !== 'ready' && <p role="status" className="text-sm text-amber-800 dark:text-amber-300"><strong>{LABELS[data.endpoints.state]}</strong> · {data.endpoints.reason}</p>}
                    {data.endpoints.possiblyTruncated && <p className="text-xs text-muted-foreground">Достигнут лимит 30 строк. Остальные маршруты входят в общие метрики выше; полный реестр здесь не заявлен.</p>}
                    <div className="overflow-x-auto"><table className="w-full min-w-[650px] text-sm"><caption className="sr-only">HTTP по маршрутам за последние пять минут</caption><thead><tr className="border-b text-left text-xs text-muted-foreground"><th className="pb-3 pr-4 font-medium">Метод / шаблон маршрута</th><th className="pb-3 pr-4 font-medium">RPS</th><th className="pb-3 pr-4 font-medium">p95, с</th><th className="pb-3 pr-4 font-medium">5xx / с</th><th className="pb-3 pr-4 font-medium">4xx / с</th><th className="pb-3 font-medium"><span className="sr-only">Детали</span></th></tr></thead><tbody>{rows.map(row => {
                        const key = `${row.method} ${row.endpoint}`;
                        return <tr key={key} className={`border-b last:border-0 ${key === selectedKey ? 'bg-muted/70' : ''}`}><th scope="row" className="max-w-[420px] py-3 pr-4 text-left font-normal"><span className="mr-2 rounded border px-1.5 py-0.5 font-mono text-[10px]">{row.method}</span><span className="break-all font-mono text-xs">{row.endpoint}</span></th>{[row.rps, row.p95Seconds, row.serverErrorsRps, row.clientErrorsRps].map((value, index) => <td key={index} className="whitespace-nowrap py-3 pr-4 font-mono text-xs tabular-nums">{value === null ? '—' : value.toLocaleString('ru-RU', { maximumFractionDigits: 3 })}</td>)}<td><Button variant="ghost" size="icon" aria-label={`Разобрать ${key}`} aria-pressed={key === selectedKey} onClick={() => setSelectedKey(key)}><ArrowRight className="h-4 w-4" /></Button></td></tr>;
                    })}</tbody></table></div>
                    {!rows.length && <p className="py-4 text-sm text-muted-foreground">{filter ? 'В текущем срезе маршруты по фильтру не найдены.' : 'Нет подтверждённых маршрутов в текущем срезе.'}</p>}
                </CardContent></Card>
                <Card className="min-w-0 rounded-xl"><CardContent className="space-y-4 p-4 sm:p-5"><h4 className="font-medium">Разбор маршрута</h4>{selected ? <>
                    <p className="break-all font-mono text-xs">{selected.method} {selected.endpoint}</p>
                    <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-xs">{[['Нагрузка', fmt(selected.rps, 'запр/с')], ['p95 до заголовков', fmt(selected.p95Seconds, 'с')], ['Ошибки сервера 5xx', fmt(selected.serverErrorsRps, 'запр/с')], ['Ответы клиента 4xx', fmt(selected.clientErrorsRps, 'запр/с')]].map(([label, value]) => <div key={label}><dt className="text-muted-foreground">{label}</dt><dd className="mt-1 font-medium tabular-nums">{value}</dd></div>)}</dl>
                    <p className="text-xs leading-relaxed text-muted-foreground">Это агрегат всех запросов к шаблону. ID устройства и пользователь не определяются по этому срезу. При нулевой нагрузке p95 может отсутствовать; нулевой RPS не означает неисправность маршрута.</p>
                </> : <p className="text-sm text-muted-foreground">{selectedKey ? 'Выбранный маршрут отсутствует в новом срезе. Выберите доступную строку.' : 'Выберите маршрут в таблице, чтобы увидеть задержку и классы ошибок.'}</p>}
                    <div className="border-t pt-4"><h5 className="text-sm font-medium">Коды ответов · весь backend</h5>{data.statuses.state !== 'ready' && <p className="mt-2 text-xs text-amber-800 dark:text-amber-300">{LABELS[data.statuses.state]} · {data.statuses.reason}</p>}<div className="mt-3 flex flex-wrap gap-2">{data.statuses.rows.map(row => <span key={row.code} className="rounded-lg border px-2.5 py-1.5 font-mono text-xs"><strong>{row.code}</strong> · {fmt(row.rps, 'запр/с')}</span>)}</div></div>
                </CardContent></Card>
            </div>
            <p className="text-xs text-muted-foreground">Prometheus · job sphere-backend · срез {new Date(data.observedAt).toLocaleString('ru-RU')} · последний подтверждённый сбор {data.lastScrape ? new Date(data.lastScrape).toLocaleTimeString('ru-RU') : 'не подтверждён'} · шаг истории {data.stepSeconds} с · «—» означает отсутствие измерения.</p>
        </>}
    </section>;
}
