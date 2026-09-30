'use client';

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Activity, AlertTriangle, ChartNoAxesCombined, RefreshCw, X } from 'lucide-react';
import { api } from '@/lib/api';
import { API_POLL_INTERVALS } from '@/lib/queryPollIntervals';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/src/shared/ui/button';
import { Card, CardContent } from '@/src/shared/ui/card';
import type { HistoryWindow, ObservationSeries, ObservabilitySnapshot } from './observabilityTypes';

function errorLabel(error: unknown) {
    const candidate = error as { response?: { data?: { detail?: unknown } } };
    return typeof candidate?.response?.data?.detail === 'string' ? candidate.response.data.detail : 'Не удалось получить данные наблюдаемости. Проверьте подключение сервисов.';
}

export function HistoryChart({ title, series, unit, step, availability = false }: {
    title: string; series: ObservationSeries[]; unit: string; step: number; availability?: boolean;
}) {
    const points = series.flatMap(item => item.points);
    const valid = points.filter((point): point is { at: number; value: number } => point.value !== null && Number.isFinite(point.value));
    const maximum = availability ? 1 : Math.max(...valid.map(point => point.value), 0.001);
    const first = Math.min(...points.map(point => point.at));
    const last = Math.max(...points.map(point => point.at));
    const latest = series[0]?.points.at(-1)?.value;
    const paths = series.map(item => {
        let previous = 0;
        return item.points.map(point => {
            if (point.value === null) { previous = 0; return ''; }
            const command = previous && point.at - previous <= step * 1500 ? 'L' : 'M';
            previous = point.at;
            return `${command}${((point.at - first) / Math.max(last - first, 1) * 460 + 10).toFixed(1)},${(120 - Math.max(0, point.value) / maximum * 105).toFixed(1)}`;
        }).join(' ');
    });
    const format = (value: number) => availability ? value === 1 ? 'Доступен' : 'Недоступен' : `${value.toLocaleString('ru-RU', { maximumFractionDigits: 3 })}${unit ? ` ${unit}` : ''}`;
    return <Card className="min-w-0 rounded-xl border-border/80">
        <CardContent className="p-4">
            <h3 className="text-sm font-medium">{title}</h3>
            <p className="mt-2 text-xl font-semibold tabular-nums">{latest == null ? 'Нет измерения' : format(latest)}</p>
            {valid.length > 1 ? <>
                <svg viewBox="0 0 480 140" className="mt-3 h-28 w-full text-primary" role="img" aria-label={`${title}: ${valid.length} измерений; пропуски не соединены`}>
                    {[15, 67, 120].map(y => <line key={y} x1="10" x2="470" y1={y} y2={y} className="stroke-border" strokeDasharray="3 4" />)}
                    {paths.map((path, index) => <path key={index} d={path} fill="none" stroke="currentColor" strokeWidth="2" />)}
                </svg>
                <div className="flex justify-between gap-3 text-[11px] text-muted-foreground">
                    <span>{new Date(first).toLocaleTimeString('ru-RU')}</span><span>{new Date(last).toLocaleTimeString('ru-RU')}</span>
                </div>
            </> : <p className="flex min-h-36 items-center text-xs text-muted-foreground">{valid.length ? 'История накапливается с момента запуска Prometheus.' : 'Измерения ещё не поступили. Пустой ряд не означает ноль.'}</p>}
        </CardContent>
    </Card>;
}

export function ObservabilityPanel() {
    const user = useAuthStore(state => state.user);
    const sessionVersion = useAuthStore(state => state.sessionVersion);
    const [window, setWindow] = useState<HistoryWindow>('1h');
    const [showGrafana, setShowGrafana] = useState(false);
    const [grafanaReady, setGrafanaReady] = useState(false);
    const [grafanaError, setGrafanaError] = useState('');
    const [now, setNow] = useState(() => Date.now());
    const isAdmin = user?.role === 'super_admin';
    const observation = useQuery<ObservabilitySnapshot>({
        queryKey: ['platform-observability', user?.id, sessionVersion, window],
        queryFn: async ({ signal }) => (await api.get<ObservabilitySnapshot>('/api/observability', { baseURL: '', params: { window }, timeout: 10000, signal })).data,
        enabled: isAdmin,
        refetchInterval: API_POLL_INTERVALS.prometheusMs,
        refetchOnWindowFocus: 'always',
        refetchIntervalInBackground: false,
        retry: false,
    });
    useEffect(() => {
        const tick = () => setNow(Date.now());
        const timer = setInterval(tick, 5000);
        document.addEventListener('visibilitychange', tick);
        return () => { clearInterval(timer); document.removeEventListener('visibilitychange', tick); };
    }, []);
    useEffect(() => {
        setGrafanaReady(false);
        setGrafanaError('');
        if (!showGrafana || !isAdmin) return;
        let stopped = false;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let active: AbortController | undefined;
        const renew = async () => {
            if (stopped || document.visibilityState === 'hidden') return;
            const controller = new AbortController();
            active = controller;
            try {
                await api.post('/api/observability/session', null, { baseURL: '', timeout: 5000, signal: controller.signal });
                if (!stopped && !controller.signal.aborted) { setGrafanaReady(true); setGrafanaError(''); }
            } catch (error) {
                if (!stopped && !controller.signal.aborted) { setGrafanaReady(false); setGrafanaError(errorLabel(error)); }
            } finally {
                if (!stopped && active === controller && !controller.signal.aborted) {
                    active = undefined;
                    timer = setTimeout(() => void renew(), 60000);
                }
            }
        };
        const visibility = () => {
            clearTimeout(timer);
            active?.abort();
            setGrafanaReady(false);
            // Remount with a freshly authorized cookie after background expiry.
            if (document.visibilityState !== 'hidden') void renew();
        };
        void renew();
        document.addEventListener('visibilitychange', visibility);
        return () => { stopped = true; clearTimeout(timer); active?.abort(); document.removeEventListener('visibilitychange', visibility); };
    }, [showGrafana, isAdmin, user?.id, sessionVersion]);

    if (!isAdmin) return <Card className="rounded-xl"><CardContent className="p-4 text-sm text-muted-foreground">Prometheus и Grafana содержат метрики всей платформы. Этот раздел доступен супер-администратору; проверки API ниже сохраняют ваши обычные права доступа.</CardContent></Card>;
    const sampleTime = observation.data ? Date.parse(observation.data.observedAt) : Number.NaN;
    const delayed = Boolean(observation.data) && (!Number.isFinite(sampleTime) || now - sampleTime > 45_000 || sampleTime > now + 5000);
    const data = observation.isError || delayed ? undefined : observation.data;
    const panels: Array<{ key: keyof ObservabilitySnapshot['charts']; title: string; unit: string }> = [
        { key: 'availability', title: 'Доступность /metrics', unit: '' },
        { key: 'scrapeDuration', title: 'Время сбора метрик', unit: 'с' },
        { key: 'samples', title: 'Измерений в последнем сборе', unit: '' },
        { key: 'storageSeries', title: 'Рядов в хранилище Prometheus', unit: '' },
    ];
    return <section aria-labelledby="observability-title" className="space-y-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div><h2 id="observability-title" className="flex items-center gap-2 text-lg font-semibold"><Activity className="h-5 w-5 text-primary" />Prometheus · история и контроль сбора</h2><p className="mt-1 text-xs text-muted-foreground">Сбор и обновление каждые 15 с · история сохраняется сервером · при возвращении на вкладку данные сверяются заново</p></div>
            <div className="flex flex-wrap items-center gap-2">
                <div role="group" aria-label="Интервал истории" className="flex rounded-lg border p-1">{(['1h', '6h', '24h'] as const).map(value => <Button key={value} variant={window === value ? 'secondary' : 'ghost'} size="sm" aria-pressed={window === value} onClick={() => setWindow(value)}>{value === '1h' ? '1 час' : value === '6h' ? '6 часов' : '24 часа'}</Button>)}</div>
                <Button variant="outline" size="sm" onClick={() => void observation.refetch()} disabled={observation.isFetching} aria-label="Обновить Prometheus"><RefreshCw className={`h-4 w-4 ${observation.isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`} /></Button>
                <Button variant="outline" size="sm" onClick={() => setShowGrafana(value => !value)} aria-expanded={showGrafana} aria-controls="embedded-grafana"><ChartNoAxesCombined className="mr-2 h-4 w-4" />{showGrafana ? 'Скрыть Grafana' : 'Открыть Grafana здесь'}</Button>
            </div>
        </div>
        <div className="flex items-start gap-3 rounded-xl border border-amber-300/70 bg-amber-50/60 p-4 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/20 dark:text-amber-200"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><p><strong>Покрытие метрик ограничено.</strong> Backend отдаёт счётчики отдельных процессов. Общие RPS, p95, CPU и размер парка по этим счётчикам пока не подтверждены и здесь не показываются. Доступность /metrics не доказывает исправность стрима или сценария Android.</p></div>
        {observation.isError && <div role="alert" className="rounded-lg border border-rose-300 bg-rose-50 p-4 text-sm text-rose-950 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">{errorLabel(observation.error)} Последние графики скрыты, чтобы старый срез не выглядел текущим.</div>}
        {!observation.isError && delayed && <p role="alert" className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/20 dark:text-amber-200">Срез Prometheus задерживается или его время некорректно. Графики скрыты до следующего актуального ответа; обновление выполняется автоматически.</p>}
        {observation.isLoading && <p role="status" className="text-sm text-muted-foreground">Подключаемся к Prometheus…</p>}
        {data && <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{panels.map(panel => <HistoryChart key={panel.key} title={panel.title} unit={panel.unit} series={data.charts[panel.key]} step={data.stepSeconds} availability={panel.key === 'availability'} />)}</div>
            <Card className="overflow-hidden rounded-xl"><CardContent className="space-y-4 p-4 sm:p-5">
                <div className="flex flex-wrap justify-between gap-2"><h3 className="font-medium">Источники и активные алерты</h3><span className="text-xs text-muted-foreground">Срез {new Date(data.observedAt).toLocaleString('ru-RU')} · шаг {data.stepSeconds} с</span></div>
                <div className="grid gap-3 sm:grid-cols-2">{data.targets.map(target => {
                    const scrapedAt = Date.parse(target.lastScrape);
                    const knownTime = Number.isFinite(scrapedAt) && scrapedAt > 0;
                    const late = !knownTime || now - scrapedAt > 45_000 || scrapedAt > now + 5000;
                    const healthy = target.health === 'up' && !late;
                    const label = target.health === 'down' ? 'Сбор недоступен' : target.health === 'unknown' ? 'Состояние неизвестно' : late ? 'Сбор задерживается' : 'Сбор работает';
                    return <div key={target.job} className="min-w-0 rounded-lg border p-3"><div className="flex justify-between gap-3"><span className="font-mono text-sm">{target.job}</span><span className={`text-xs font-medium ${healthy ? 'text-emerald-700 dark:text-emerald-400' : target.health === 'down' ? 'text-rose-700 dark:text-rose-400' : 'text-amber-700 dark:text-amber-400'}`}>{label}</span></div><p className="mt-2 text-xs text-muted-foreground">Последний сбор: {knownTime ? new Date(scrapedAt).toLocaleTimeString('ru-RU') : 'нет подтверждённого времени'} · {(target.durationSeconds * 1000).toFixed(0)} мс</p>{target.error && <p className="mt-2 break-words text-xs text-rose-700 dark:text-rose-400">{target.error}</p>}</div>;
                })}</div>
                {!data.targets.length && <p className="text-sm text-amber-700">Источники сбора не найдены; это не здоровое состояние.</p>}
                {data.alerts.length ? <ul className="space-y-2">{data.alerts.map(alert => <li key={`${alert.name}-${alert.since}`} className="rounded-lg border border-amber-300 p-3 text-sm"><strong>{alert.name}</strong> · {alert.state === 'firing' ? 'Срабатывает' : 'Ожидает порога'}<p className="mt-1 text-muted-foreground">{alert.summary}</p></li>)}</ul> : <p className="text-xs text-muted-foreground">Активных алертов по подключённым правилам нет. Сейчас правило проверяет потерю /metrics; оно не покрывает всю платформу.</p>}
            </CardContent></Card>
        </>}
        {showGrafana && <Card id="embedded-grafana" className="overflow-hidden rounded-xl">
            <div className="flex items-center justify-between gap-3 border-b p-4"><div><h3 className="font-medium">Grafana · серверная история</h3><p className="mt-1 text-xs text-muted-foreground">Режим просмотра · максимум 24 часа на запрос · сессия подтверждается Sphere каждую минуту</p></div><Button variant="ghost" size="icon" aria-label="Закрыть Grafana" onClick={() => setShowGrafana(false)}><X className="h-4 w-4" /></Button></div>
            {grafanaError ? <p role="alert" className="p-4 text-sm text-rose-700 dark:text-rose-400">{grafanaError}</p> : !grafanaReady ? <p role="status" className="p-4 text-sm text-muted-foreground">Проверяем доступ к Grafana…</p> : <iframe title="Grafana — наблюдаемость Sphere" className="h-[680px] w-full border-0" src="/observability/grafana/d/sphere-collection/sphere-metrics-collection?orgId=1&kiosk&from=now-1h&to=now&refresh=30s" sandbox="allow-scripts allow-same-origin allow-forms allow-downloads" referrerPolicy="same-origin" />}
        </Card>}
    </section>;
}
