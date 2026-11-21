'use client';

import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { API_POLL_INTERVALS } from '@/lib/queryPollIntervals';
import { Button } from '@/src/shared/ui/button';
import { HistoryChart } from './HistoryChart';
import type { HistoryWindow } from './observabilityTypes';
import type { MeasurementState } from './httpMetricsTypes';
import type { ResourceMetricsSnapshot } from './resourceMetricsTypes';

const LABELS: Record<MeasurementState, string> = { ready: 'Измерено', empty: 'Нет измерения', partial: 'Неполные данные', error: 'Ошибка источника', stale: 'Устаревшие данные' };
const PANELS = [
    { key: 'cpu', title: 'CPU · использованные ядра', unit: 'ядра', note: 'CPU-секунды / секунду, среднее за 1 минуту. 1 = одно полностью занятое ядро; значение может быть больше 1.' },
    { key: 'cpuQuota', title: 'CPU · лимит контейнера', unit: 'ядра', note: 'Квота / период cgroup. Отсутствующий или неограниченный лимит не превращается в ноль.' },
    { key: 'memory', title: 'Память · расход контейнера', unit: 'GiB', note: 'Память, учтённая cgroup, включая кэш. Это не сумма RSS worker-процессов и не память всего ПК.' },
    { key: 'memoryLimit', title: 'Память · лимит контейнера', unit: 'GiB', note: 'Лимит cgroup в GiB: 1 GiB = 1 073 741 824 байта. Неограниченный лимит не отображается нулём.' },
] as const;
export function ResourceMetricsPanel({ window, now }: { window: HistoryWindow; now: number }) {
    const user = useAuthStore(state => state.user);
    const sessionVersion = useAuthStore(state => state.sessionVersion);
    const observation = useQuery<ResourceMetricsSnapshot>({
        queryKey: ['platform-resource-metrics', user?.id, sessionVersion, window],
        queryFn: async ({ signal }) => (await api.get<ResourceMetricsSnapshot>('/api/observability/resources', { baseURL: '', params: { window }, timeout: 10000, signal })).data,
        enabled: user?.role === 'super_admin', retry: false,
        refetchInterval: API_POLL_INTERVALS.prometheusMs, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always',
    });
    if (user?.role !== 'super_admin') return null;
    const at = Date.parse(observation.data?.observedAt ?? '');
    const scrapeAt = observation.data?.lastScrape ? Date.parse(observation.data.lastScrape) : null;
    const delayed = !!observation.data && (!Number.isFinite(at) || now - at > 45000 || at > now + 5000 || (scrapeAt !== null && (!Number.isFinite(scrapeAt) || now - scrapeAt > 45000 || scrapeAt > now + 5000)));
    const data = observation.isError || delayed ? undefined : observation.data;
    return <section aria-labelledby="resource-metrics-title" className="space-y-4">
        <div className="flex items-start justify-between gap-3"><div className="min-w-0"><h3 id="resource-metrics-title" className="text-lg font-semibold">Backend · ресурсы контейнера</h3><p className="mt-1 max-w-4xl text-xs leading-relaxed text-muted-foreground">Источник: Linux cgroup внутри единственного контейнера backend · все его процессы · история {window}. Сбор и обновление каждые 15 с. История расхода Windows-хоста и RSS отдельных worker-процессов здесь не измеряется.</p></div><Button className="h-10 w-10 shrink-0" variant="outline" size="icon" aria-label="Обновить ресурсы backend" onClick={() => void observation.refetch()} disabled={observation.isFetching}><RefreshCw className={`h-4 w-4 ${observation.isFetching ? 'animate-spin motion-reduce:animate-none' : ''}`} /></Button></div>
        {observation.isLoading && <p role="status" className="text-sm text-muted-foreground">Получаем измерения ресурсов…</p>}
        {(observation.isError || delayed) && <p role="alert" className="rounded-lg border border-amber-300 p-4 text-sm text-amber-900 dark:text-amber-200">{delayed && !observation.isError ? 'Срез ресурсов устарел или его время некорректно.' : 'Не удалось подтвердить текущий расход ресурсов.'} Прежние значения скрыты. Повторяем запрос автоматически.</p>}
        {data && <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{PANELS.map(panel => {
                const signal = data.metrics[panel.key];
                return <div key={panel.key} role="group" aria-label={panel.title} className="min-w-0 space-y-2"><HistoryChart title={panel.title} unit={panel.unit} series={signal.series} step={data.stepSeconds} /><p className={`px-1 text-xs ${signal.state === 'ready' ? 'text-muted-foreground' : 'text-amber-800 dark:text-amber-300'}`}><strong>{LABELS[signal.state]}</strong>{signal.reason && ` · ${signal.reason}`}</p><p className="px-1 text-xs leading-relaxed text-muted-foreground">{panel.note}</p></div>;
            })}</div>
            <p className="text-xs text-muted-foreground">Prometheus · job sphere-backend · cgroup контейнера · срез {new Date(data.observedAt).toLocaleString('ru-RU')} · последний подтверждённый сбор {data.lastScrape ? new Date(data.lastScrape).toLocaleTimeString('ru-RU') : 'не подтверждён'} · шаг истории {data.stepSeconds} с. Пропуски остаются пропусками; доступность источника не доказывает отсутствие утечек.</p>
        </>}
    </section>;
}
