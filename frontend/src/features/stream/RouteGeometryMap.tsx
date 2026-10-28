'use client';
import {useMemo,useState,type ReactNode} from 'react';
import {buildRouteMap,nearestRouteCamera,type RouteMapCamera} from './routeMapProjection';

/** A bounded visual overview, not a map of traversable or metric space. */
export default function RouteGeometryMap({cameras,points,motionWarning=false,selectedTicks=null,onSeekCamera,validTicks,sourcePreview}:{cameras:RouteMapCamera[];points:number[][];motionWarning?:boolean;selectedTicks?:number|null;onSeekCamera?:(ticks:number)=>void;validTicks?:ReadonlySet<number>;sourcePreview?:ReactNode}) {
  const [highDensity,setHighDensity]=useState(false);
  const map=useMemo(()=>buildRouteMap(cameras,points,highDensity?24000:3000),[cameras,points,highDensity]);
  if(!map)return <p className="p-3 text-xs text-muted-foreground">Недостаточно движения камеры для проекции ориентиров.</p>;
  const selected=nearestRouteCamera(cameras,selectedTicks),interactive=!!onSeekCamera&&!!validTicks;
  const seek=(index:number)=>{const camera=cameras[index];if(camera&&validTicks?.has(camera.ticks_90k))onSeekCamera?.(camera.ticks_90k);};
  const quantile=(values:number[],q:number)=>{const ordered=[...values].sort((a,b)=>a-b);return ordered[Math.floor((ordered.length-1)*q)];};
  const bounds=(axis:'x'|'y')=>{const cloud=map.points.map(p=>p[axis]),trace=map.cameras.map(p=>p[axis]);
    return [Math.min(...trace,cloud.length?quantile(cloud,.01):Infinity),Math.max(...trace,cloud.length?quantile(cloud,.99):-Infinity)];};
  const [xmin,xmax]=bounds('x'),[ymin,ymax]=bounds('y'),extent=Math.max(xmax-xmin,ymax-ymin,1e-6);
  const scale=480/extent,cx=(xmin+xmax)/2,cy=(ymin+ymax)/2;
  const xy=(p:{x:number;y:number})=>({x:300+(p.x-cx)*scale,y:270-(p.y-cy)*scale});
  const shown=map.points.map(xy).filter(p=>p.x>=20&&p.x<=580&&p.y>=20&&p.y<=520);
  const start=xy(map.cameras[0]),end=xy(map.cameras[map.cameras.length-1]);
  return <section aria-label="Обзор ориентиров и камер" className="border-t border-border bg-slate-950/30 px-4 py-4">
    <div className="flex flex-wrap items-baseline justify-between gap-2"><div><h4 className="text-sm font-semibold">Ориентиры и восстановленный путь камеры</h4><p className="mt-1 text-xs text-muted-foreground">Проекция PCA по движению камеры · условные единицы</p></div><div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground"><span>{cameras.length} камер · {points.length.toLocaleString('ru')} точек</span><label className="flex items-center gap-2"><input type="checkbox" checked={highDensity} onChange={e=>setHighDensity(e.target.checked)}/>Больше точек</label></div></div>
    <div className="mt-3 grid items-start gap-4 xl:grid-cols-2"><svg role={interactive?'group':'img'} aria-label="Проекция опорных точек и положений камеры" viewBox="0 0 600 540" className="max-h-[520px] w-full rounded-xl border border-slate-700/60 bg-[#0d1727]">
      <defs><pattern id="route-map-grid" width="60" height="60" patternUnits="userSpaceOnUse"><path d="M 60 0 L 0 0 0 60" fill="none" stroke="#26374d" strokeWidth="1"/></pattern></defs>
      <rect x="0" y="0" width="600" height="540" fill="url(#route-map-grid)"/>
      {shown.map((p,i)=><circle key={i} cx={p.x} cy={p.y} r="1.3" fill="#e6bd73" opacity=".58"/>)}
      {map.segments.map((segment,i)=>{const a=xy(segment.a),b=xy(segment.b);return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={motionWarning?'#fbbf78':'#55debd'} strokeWidth="2.5"/>;})}
      {map.cameras.map((camera,i)=>{const p=xy(camera),enabled=interactive&&validTicks?.has(cameras[i].ticks_90k);return <g key={i}>{enabled?<g role="button" tabIndex={0} aria-label={`Показать исходный кадр ${i+1} · ${(cameras[i].ticks_90k/90000).toFixed(2)} с`} onClick={()=>seek(i)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();seek(i);}}} className="cursor-pointer outline-none focus-visible:opacity-70"><circle cx={p.x} cy={p.y} r="10" fill="transparent"/><circle cx={p.x} cy={p.y} r={selected===i?5:3} fill={selected===i?'#ffffff':motionWarning?'#fbbf78':'#67e8d1'}/></g>:<circle cx={p.x} cy={p.y} r="2.5" fill={motionWarning?'#fbbf78':'#67e8d1'}/>}</g>;})}
      <circle cx={start.x} cy={start.y} r="7" fill="#0d1727" stroke="#e7f3ff" strokeWidth="2" pointerEvents="none"/>
      <path d={`M ${end.x-5} ${end.y-5} l 10 10 m -10 0 l 10 -10`} stroke="#fbbf78" strokeWidth="2" pointerEvents="none"/>
    </svg><div className="space-y-3">{interactive?<><label className="block text-xs text-muted-foreground">Ракурс {selected===null?'—':selected+1} / {cameras.length}{selected===null?'':` · ${(cameras[selected].ticks_90k/90000).toFixed(2)} с`}<input aria-label="Ракурс на схеме ориентиров" type="range" min={0} max={cameras.length-1} step={1} value={selected??0} onChange={e=>seek(Number(e.target.value))} className="mt-2 w-full accent-emerald-400"/></label>{selected!==null&&selectedTicks!==null&&<p className="text-xs text-muted-foreground">Ближайшая восстановленная камера: разница с текущим кадром {Math.abs(cameras[selected].ticks_90k-selectedTicks)/90000<.001?'менее 1 мс':`${(Math.abs(cameras[selected].ticks_90k-selectedTicks)/90000).toFixed(2)} с`}. Между ракурсами положение не вычисляется.</p>}{sourcePreview}</>:<p className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-3 text-xs text-amber-500">Связь с исходной записью не подтверждена. Схема доступна только для просмотра.</p>}</div></div>
    {motionWarning&&<p role="status" className="mt-2 text-xs text-amber-400">Движение камеры требует проверки: для этой реконструкции весь путь выделен оранжевым, точные границы ошибки не установлены.</p>}
    <p className="mt-2 text-xs leading-5 text-muted-foreground">Круг — первый ракурс, крест — последний. Жёлтые точки — 3D-признаки; показано {shown.length.toLocaleString('ru')} из {points.length.toLocaleString('ru')}, крайние значения обрезаны. Разрывы больше секунды не соединяются: {map.gaps}. Проекция не доказывает положение дороги, масштаб или безопасность проезда.</p>
  </section>;
}
