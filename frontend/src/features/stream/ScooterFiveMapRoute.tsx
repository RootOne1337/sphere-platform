import type { TeachingMapCatalogEntry } from './teachingCatalog';
import preview from './scooter5MapPreview.json';

export const scooterFiveCatalogEntry = {
  id: preview.id,
  title: 'Scooter 5 · Вокруг Кремля',
  createdAt: Date.parse('2026-11-16T11:34:47+05:00'),
  game: 'Black Russia',
  sourceName: 'Карта Ariane',
  length: preview.length,
} satisfies TeachingMapCatalogEntry;

const distanceFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });

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
  return <div className="grid gap-4 sm:grid-cols-2">
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
      <ol className="space-y-1 text-xs text-muted-foreground">
        {preview.markers.map(({ name, distance }, index) => <li key={name} className="flex justify-between gap-2">
          <span>{index + 1}. {name}</span><span className="shrink-0 tabular-nums">{distanceFormat.format(distance)}</span>
        </li>)}
      </ol>
      <p className="border-t border-border pt-3 text-xs leading-5 text-muted-foreground">
        Финиш подтверждён в {Object.keys(preview.simulator).length} прогонах симулятора. Живой запуск ожидает проверки на кадрах Black Russia.
      </p>
    </div>
  </div>;
}
