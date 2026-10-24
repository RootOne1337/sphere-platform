'use client';

import { Card, CardContent } from '@/src/shared/ui/card';
import type { ObservationSeries } from './observabilityTypes';

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
