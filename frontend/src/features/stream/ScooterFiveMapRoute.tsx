import { ChevronDown, Map } from 'lucide-react';
import preview from './scooter5MapPreview.json';

function routeNumber(value: number) {
  return value.toLocaleString('ru-RU', { maximumFractionDigits: 1, minimumFractionDigits: 1 });
}

const margin = 10;
const xs = preview.points.map(([x]) => x);
const ys = preview.points.map(([, y]) => y);
const viewBox = [
  Math.min(...xs) - margin,
  Math.min(...ys) - margin,
  Math.max(...xs) - Math.min(...xs) + 2 * margin,
  Math.max(...ys) - Math.min(...ys) + 2 * margin,
].join(' ');
const polyline = preview.points.map(([x, y]) => `${x},${y}`).join(' ');

/** A map-native preview. Its geometry is never used as a saved recording or live control package. */
export function ScooterFiveMapRoute() {
  return <details className="group overflow-hidden rounded-xl border border-border bg-background/65">
    <summary className="flex min-w-0 cursor-pointer list-none items-center gap-3 p-4 [&::-webkit-details-marker]:hidden">
      <Map size={20} className="shrink-0 text-primary" aria-hidden="true"/>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold">Scooter 5 · Вокруг Кремля</span>
        <span className="mt-1 block text-xs text-muted-foreground">Black Russia · Маршрут из карты Ariane</span>
      </span>
      <span className="rounded-md border border-border px-2 py-1 text-right text-xs text-muted-foreground">Просмотр карты</span>
      <ChevronDown size={16} className="shrink-0 group-open:rotate-180" aria-hidden="true"/>
    </summary>
    <div className="grid gap-4 border-t border-border p-4 md:grid-cols-[minmax(11rem,1fr)_minmax(14rem,1.35fr)]">
      <svg role="img" aria-label="Контур Scooter 5 от переулка вдоль набережной и вокруг Кремля"
        viewBox={viewBox} className="h-64 w-full rounded-lg border border-border bg-muted/30 text-primary">
        <polyline points={polyline} fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinejoin="round" strokeLinecap="round"/>
        {preview.markers.map(({ name, position: [x, y] }, index) => <g key={name}>
          <circle cx={x} cy={y} r="2.9" className="fill-background stroke-primary" strokeWidth="1.2"/>
          <text x={x} y={y} dy=".32em" textAnchor="middle" fontSize="3.5" className="fill-foreground">{index + 1}</text>
        </g>)}
      </svg>
      <div className="min-w-0 space-y-3">
        <p className="text-sm font-medium">{routeNumber(preview.length)} ед. карты</p>
        <ol className="space-y-1 text-xs text-muted-foreground">
          {preview.markers.map(({ name, distance }, index) => <li key={name} className="flex justify-between gap-2">
            <span>{index + 1}. {name}</span><span className="shrink-0 tabular-nums">{routeNumber(distance)}</span>
          </li>)}
        </ol>
        <p className="border-t border-border pt-3 text-xs leading-5 text-muted-foreground">
          Финиш подтверждён в {Object.keys(preview.simulator).length} прогонах симулятора. Живой запуск ожидает проверки на кадрах Black Russia.
        </p>
      </div>
    </div>
  </details>;
}
