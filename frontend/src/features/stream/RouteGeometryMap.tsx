'use client';
import {memo,useEffect,useId,useMemo,useRef,useState,type ReactNode} from 'react';
import {buildRouteMap,colorRoutePoints,nearestRouteCamera,projectRouteCamera,routeCameraFrame,routeMapTurn,routeTraceColor,routeWarningColor,unwrapRouteAngle,type RouteMapCamera,type RoutePointColorMode} from './routeMapProjection';

type CloudPoint={x:number;y:number;color:string};
/** Keep tens of thousands of landmarks out of React's live input render path. */
const RoutePointCloud=memo(function RoutePointCloud({points}:{points:CloudPoint[]}) {
  const canvas=useRef<HTMLCanvasElement>(null);
  useEffect(()=>{
    const context=canvas.current?.getContext('2d');if(!context)return;
    context.setTransform(2,0,0,2,0,0);context.clearRect(0,0,600,540);context.globalAlpha=.68;
    for(const p of points){context.fillStyle=p.color;context.beginPath();context.arc(p.x,p.y,1.25,0,Math.PI*2);context.fill();}
  },[points]);
  return <foreignObject x={0} y={0} width={600} height={540} pointerEvents="none" aria-label="Облако восстановленных ориентиров" data-point-count={points.length}>
    <canvas ref={canvas} width={1200} height={1080} className="h-full w-full"/>
  </foreignObject>;
});

/** A bounded visual overview, not a map of traversable or metric space. */
export default function RouteGeometryMap({cameras,points,motionWarning=false,selectedTicks=null,onSeekCamera,validTicks,sourcePreview,liveCamera=null,orientationCamera=null,comparison}:{cameras:RouteMapCamera[];points:number[][];motionWarning?:boolean;selectedTicks?:number|null;onSeekCamera?:(ticks:number)=>void;validTicks?:ReadonlySet<number>;sourcePreview?:ReactNode;liveCamera?:RouteMapCamera|null;orientationCamera?:RouteMapCamera|null;comparison?:ReactNode}) {
  const [highDensity,setHighDensity]=useState(false),[colorMode,setColorMode]=useState<RoutePointColorMode>('depth');
  const [follow,setFollow]=useState(true),[manual,setManual]=useState(0),[angle,setAngle]=useState(0);
  const id=useId().replaceAll(':',''),gridId=`route-grid-${id}`,arrowId=`route-heading-${id}`;
  const map=useMemo(()=>buildRouteMap(cameras,points,highDensity?24000:3000),[cameras,points,highDensity]);
  const selected=nearestRouteCamera(cameras,selectedTicks),active=selected??0;
  // Keep the expensive cloud paint stable during live input. Only the current
  // pose/heading moves at live cadence; depth colours belong to reference 1.
  const depthIndex=liveCamera||orientationCamera?0:active,depthCamera=cameras[depthIndex],hasFrame=!!depthCamera&&!!routeCameraFrame(depthCamera);
  const live=map&&liveCamera?projectRouteCamera(map,liveCamera):null;
  // A stale pin must disappear, but the overview must not snap between a live
  // heading and a different recorded camera every time its 250 ms TTL expires.
  // Held orientation is presentation only and never a live-pose authority.
  const heldDirection=map&&orientationCamera?projectRouteCamera(map,orientationCamera)?.heading:null;
  const direction=live?.heading??heldDirection??map?.headings[active]??null,target=routeMapTurn(direction,follow,manual);
  useEffect(()=>{setAngle(previous=>unwrapRouteAngle(previous,target));},[target]);
  useEffect(()=>{setManual(0);setFollow(true);},[cameras]);
  const effectiveMode=colorMode==='depth'&&!hasFrame?'distance':colorMode;
  const appearance=useMemo(()=>map&&depthCamera?colorRoutePoints(map.points.map(p=>points[p.sourceIndex]),depthCamera,effectiveMode):null,[map,points,depthCamera,effectiveMode]);
  const layout=useMemo(()=>{
    if(!map)return null;
    const quantile=(values:number[],q:number)=>{const ordered=[...values].sort((a,b)=>a-b);return ordered[Math.floor((ordered.length-1)*q)];};
    const bounds=(axis:'x'|'y')=>{const cloud=map.points.map(p=>p[axis]),trace=map.cameras.map(p=>p[axis]);
      return [Math.min(...trace,cloud.length?quantile(cloud,.01):Infinity),Math.max(...trace,cloud.length?quantile(cloud,.99):-Infinity)];};
    const [xmin,xmax]=bounds('x'),[ymin,ymax]=bounds('y'),cx=(xmin+xmax)/2,cy=(ymin+ymax)/2;
    const radius=Math.max(1e-6,...map.cameras.map(p=>Math.hypot(p.x-cx,p.y-cy)),map.points.length?quantile(map.points.map(p=>Math.hypot(p.x-cx,p.y-cy)),.98):0);
    const scale=240/radius,xy=(p:{x:number;y:number})=>({x:300+(p.x-cx)*scale,y:270-(p.y-cy)*scale});
    return {xy,cloud:map.points.map(xy)};
  },[map]);
  const shown=useMemo(()=>layout&&appearance?layout.cloud.map((point,i)=>({...point,color:appearance.colors[i]}))
    .filter(p=>p.x>=20&&p.x<=580&&p.y>=20&&p.y<=520):[],[layout,appearance]);
  if(!map||!appearance||!layout)return <p className="p-3 text-xs text-muted-foreground">Недостаточно движения камеры для проекции ориентиров.</p>;
  const interactive=!!onSeekCamera&&!!validTicks;
  const seek=(index:number)=>{const camera=cameras[index];if(camera&&validTicks?.has(camera.ticks_90k))onSeekCamera?.(camera.ticks_90k);};
  const {xy}=layout;
  const start=xy(map.cameras[0]),end=xy(map.cameras[map.cameras.length-1]),current=xy(map.cameras[active]),heading=map.headings[active];
  return <section aria-label="Обзор ориентиров и камер" className="rounded-xl border border-slate-700/60 bg-[#0b1422] p-4 text-slate-100">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[10px] font-semibold uppercase tracking-[.16em] text-cyan-300">Карта прохода</p><h4 className="mt-1 text-sm font-semibold">Ориентиры и восстановленный путь камеры</h4><p className="mt-1 text-xs text-slate-400">{map.orientation==='camera'?'Оси первого ракурса: вперёд ↑ · вправо →':'Проекция PCA · ориентация относительно взгляда неизвестна'} · условные единицы</p></div><div className="flex flex-wrap items-center gap-3 text-xs text-slate-300"><span className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 tabular-nums">{cameras.length} камер · {points.length.toLocaleString('ru')} точек</span><label className="flex items-center gap-2"><input type="checkbox" checked={highDensity} onChange={e=>setHighDensity(e.target.checked)}/>Больше точек</label></div></div>
    <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-700/60 bg-slate-900/60 px-3 py-2 text-xs"><div className="flex flex-wrap items-center gap-4"><span className="flex items-center gap-2"><span className="h-[3px] w-6 rounded bg-cyan-400"/>Путь камеры</span><span className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-fuchsia-300"/>3D-ориентиры</span>{motionWarning&&<span className="flex items-center gap-2 text-amber-300"><span className="h-2 w-2 rounded-sm border border-amber-300"/>Позы требуют проверки</span>}</div><label className="flex items-center gap-2 text-slate-400">Цвет точек<select aria-label="Цвет опорных точек" value={effectiveMode} onChange={e=>setColorMode(e.target.value as RoutePointColorMode)} className="rounded-md border border-slate-600 bg-slate-950 px-2 py-1.5 text-xs text-slate-100"><option value="depth" disabled={!hasFrame}>Глубина от камеры</option><option value="distance">Дистанция до камеры</option><option value="rgb">Исходные цвета</option></select></label></div>
    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-300"><label className="flex items-center gap-2">Верх карты<select aria-label="Ориентация карты" value={follow&&direction?'heading':'reference'} onChange={e=>setFollow(e.target.value==='heading')} className="rounded-md border border-slate-600 bg-slate-950 p-1.5"><option value="heading" disabled={!direction}>Текущий взгляд ↑</option><option value="reference">Первый ракурс</option></select></label><button type="button" aria-label="Повернуть карту влево на 90 градусов" className="rounded border border-slate-600 px-2 py-1.5" onClick={()=>setManual(v=>v-90)}>↶ 90°</button><button type="button" aria-label="Повернуть карту вправо на 90 градусов" className="rounded border border-slate-600 px-2 py-1.5" onClick={()=>setManual(v=>v+90)}>↷ 90°</button><button type="button" className="rounded border border-slate-600 px-2 py-1.5" onClick={()=>{setManual(0);setFollow(true);}}>Сброс поворота</button><span className="text-slate-400">Плавный компас · {manual%360}° поправки</span></div>
    {orientationCamera&&!liveCamera&&<p className="mt-2 text-xs text-amber-300">Положение сейчас не подтверждено. Поворот схемы сохранён по последнему подтверждённому взгляду; живой маркер скрыт.</p>}
    <div className={`mt-3 grid items-start gap-4 xl:grid-cols-2 ${comparison?'2xl:grid-cols-3':''}`}><div className="space-y-2"><svg role={interactive?'group':'img'} aria-label="Проекция опорных точек и положений камеры" viewBox="0 0 600 540" className="max-h-[520px] w-full rounded-xl border border-slate-700/60 bg-[#0d1727]">
      <defs><pattern id={gridId} width="60" height="60" patternUnits="userSpaceOnUse"><path d="M 60 0 L 0 0 0 60" fill="none" stroke="#26374d" strokeWidth=".7"/></pattern><marker id={arrowId} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#f8fafc"/></marker></defs>
      <rect x="0" y="0" width="600" height="540" fill={`url(#${gridId})`}/>
      <text x="16" y="24" fill="#94a3b8" fontSize="10" letterSpacing="1">{follow&&direction?'ТЕКУЩИЙ ВЗГЛЯД ↑':map.orientation==='camera'?'СТАРТОВЫЙ ВЗГЛЯД ↑ · ПРАВО →':'PCA · ОРИЕНТАЦИЯ НЕ ПРИВЯЗАНА'}</text>
      <g aria-label="Поворот схемы" data-angle-radians={angle} style={{transform:`rotate(${-angle*180/Math.PI}deg)`,transformOrigin:'50% 50%',transformBox:'view-box'}} className="transition-transform duration-150 ease-linear motion-reduce:transition-none">
      <RoutePointCloud points={shown}/>
      {map.segments.map((segment,i)=>{const a=xy(segment.a),b=xy(segment.b);return <g key={i}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#07111e" strokeWidth="7"/>{motionWarning&&<line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={routeWarningColor} strokeWidth="5" strokeDasharray="3 6" opacity=".85"/>}<line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={routeTraceColor} strokeWidth="2.6" strokeLinecap="round"/></g>;})}
      {map.cameras.map((camera,i)=>{const p=xy(camera),enabled=interactive&&validTicks?.has(cameras[i].ticks_90k);return <g key={i}>{enabled?<g role="button" tabIndex={0} aria-label={`Показать исходный кадр ${i+1} · ${(cameras[i].ticks_90k/90000).toFixed(2)} с`} onClick={()=>seek(i)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();seek(i);}}} className="cursor-pointer outline-none focus-visible:opacity-70"><circle cx={p.x} cy={p.y} r="10" fill="transparent"/><circle cx={p.x} cy={p.y} r={selected===i?5:2.4} fill={selected===i?'#ffffff':routeTraceColor}/></g>:<circle cx={p.x} cy={p.y} r="2.2" fill={routeTraceColor}/>}</g>;})}
      {selected!==null&&heading&&<line aria-label="Направление взгляда выбранной камеры" x1={current.x} y1={current.y} x2={current.x+heading.x*25} y2={current.y-heading.y*25} stroke="#f8fafc" strokeWidth="2" markerEnd={`url(#${arrowId})`} pointerEvents="none"/>}
      <circle cx={start.x} cy={start.y} r="7" fill="#0d1727" stroke="#e7f3ff" strokeWidth="2" pointerEvents="none"/>
      <path d={`M ${end.x-5} ${end.y-5} l 10 10 m -10 0 l 10 -10`} stroke="#fda4af" strokeWidth="2" pointerEvents="none"/>
      {live&&(()=>{const p=xy(live.point);return <g aria-label="Подтверждённое живое положение" pointerEvents="none"><circle cx={p.x} cy={p.y} r="8" fill="#38bdf8" stroke="#fff" strokeWidth="2"/>{live.heading&&<line x1={p.x} y1={p.y} x2={p.x+live.heading.x*25} y2={p.y-live.heading.y*25} stroke="#fff" strokeWidth="2" markerEnd={`url(#${arrowId})`}/>}</g>;})()}
      </g>
    </svg>{effectiveMode!=='rgb'&&<div className="rounded-lg border border-slate-700/60 bg-slate-900/60 p-3 text-[11px] text-slate-400"><div className="flex flex-wrap justify-between gap-2"><span>{effectiveMode==='depth'?'Глубина вдоль взгляда':'Дистанция в 3D'} · {live?'опорная камера 1 · цвет облака закреплён':`камера ${depthIndex+1}`}</span><span className="text-slate-300">{appearance.low===null?'Нет положительных значений':`${appearance.low.toFixed(2)}–${appearance.high!.toFixed(2)} усл. ед.`}</span></div><div aria-hidden="true" className="mt-2 h-1.5 rounded-full bg-gradient-to-r from-fuchsia-300 via-violet-500 to-slate-600"/><p className="mt-2">Ближе → дальше · цветовой диапазон 5–95% · масштаб в метрах неизвестен{effectiveMode==='depth'?` · за камерой серым: ${appearance.behind.toLocaleString('ru')}`:''}</p></div>}</div>
    <div className="space-y-3">{interactive?<><label className="block text-xs text-slate-400">Ракурс {selected===null?'—':selected+1} / {cameras.length}{selected===null?'':` · ${(cameras[selected].ticks_90k/90000).toFixed(2)} с`}<input aria-label="Ракурс на схеме ориентиров" type="range" min={0} max={cameras.length-1} step={1} value={selected??0} onChange={e=>seek(Number(e.target.value))} className="mt-2 w-full accent-cyan-400"/></label>{selected!==null&&selectedTicks!==null&&<p className="text-xs text-slate-400">Ближайшая восстановленная камера: разница с текущим кадром {Math.abs(cameras[selected].ticks_90k-selectedTicks)/90000<.001?'менее 1 мс':`${(Math.abs(cameras[selected].ticks_90k-selectedTicks)/90000).toFixed(2)} с`}. Между ракурсами положение не вычисляется.</p>}{sourcePreview}</>:<p className="rounded-lg border border-amber-500/25 bg-amber-500/5 p-3 text-xs text-amber-300">Связь с исходной записью не подтверждена. Схема доступна только для просмотра.</p>}
    <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400"><p className="rounded-lg border border-slate-700/60 p-3">Ориентация<br/><span className="mt-1 block text-slate-200">{map.orientation==='camera'?'Первый ракурс · без отражения':'PCA · сторона поворота не определена'}</span></p><p className="rounded-lg border border-slate-700/60 p-3">Основание схемы<br/><span className="mt-1 block text-slate-200">Камеры и 3D-точки SfM</span></p></div></div>{comparison&&<div className="xl:col-span-2 2xl:col-span-1">{comparison}</div>}</div>
    {motionWarning&&<p role="status" className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-300">Движение камеры требует проверки; точные границы ошибки не установлены. Янтарный пунктир обозначает этот статус.</p>}
    <p className="mt-3 text-xs leading-5 text-slate-400">Круг — первый ракурс, крест — последний; белая стрелка — взгляд выбранной камеры. Показано {shown.length.toLocaleString('ru')} из {points.length.toLocaleString('ru')} 3D-признаков, крайние значения обрезаны. Разрывы больше секунды не соединяются: {map.gaps}. Проекция не доказывает положение дороги, масштаб или безопасность проезда. Плоскость первого ракурса не определяет вертикаль мира; цвет глубины не подтверждает точность реконструкции.</p>
  </section>;
}
