'use client';
import { useState } from 'react';
import type { PointerPath } from '@/lib/dag/pointerPath';

/** Local inspection only: moving the timeline never sends input to Android. */
export function PointerPathPreview({ path }: {path: PointerPath}) {
  const [position,setPosition] = useState(0);
  const duration = path.points.at(-1)!.t_ms;
  const time = Math.min(position,duration);
  const point = path.points.findLast(p=>p.t_ms<=time) ?? path.points[0];
  const start = path.points[0], end = path.points.at(-1)!;
  const d = path.points.map((p,i)=>`${i?'L':'M'}${p.x},${p.y}`).join(' ');
  return <section aria-label="Траектория касания" className="space-y-3 rounded-xl border p-3">
    <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs"><strong>Один непрерывный жест</strong><span className="text-muted-foreground">{path.points.length} точек · {duration} мс</span></div>
    <svg role="img" aria-label="Путь пальца от начала до отпускания" viewBox={`0 0 ${path.frame_width} ${path.frame_height}`} className="max-h-48 w-full rounded-lg border bg-muted/40">
      <path d={d} fill="none" stroke="currentColor" strokeWidth={Math.max(2,path.frame_width/320)} className="text-primary" />
      <circle cx={start.x} cy={start.y} r={path.frame_width/85} className="fill-emerald-500" />
      <circle cx={end.x} cy={end.y} r={path.frame_width/85} fill="none" stroke="currentColor" strokeWidth={path.frame_width/320} className="text-primary" />
      <circle cx={point.x} cy={point.y} r={path.frame_width/60} className="fill-primary stroke-background" strokeWidth={path.frame_width/320} />
    </svg>
    <label className="block space-y-2 text-xs"><span className="flex justify-between gap-2"><span>Время жеста</span><span className="tabular-nums">{time} / {duration} мс</span></span><input aria-label="Время жеста" type="range" className="w-full accent-primary" min={0} max={Math.max(1,duration)} step={1} value={time} onChange={e=>setPosition(Number(e.target.value))} /></label>
    <p className="text-[11px] leading-5 text-muted-foreground">Зелёная точка — нажатие, кольцо — отпускание. Между точками палец удерживается, включая паузы. Шкала показывает записанную траекторию и не управляет устройством.</p>
  </section>;
}
