'use client';

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { Button } from '@/components/ui/button';
import type { TeachingInput } from './teachingContacts';
import type { VehicleInputLease } from './vehiclePilot';
import { runWorldTrip, worldRequest, type Decision, type WorldInfo, type XYZ } from './worldDestination';

const reasons: Record<string,string> = {
  no_motion:'Поездка остановлена. Газ был запрошен, но скутер не сдвинулся. Проверьте топливо и калибровку педали.',
  following:'Движение по маршруту', confirming_position:'Подтверждаем положение по следующему кадру',
  position_unknown:'Ищем ориентиры в кадре', road_level_unknown:'Под скутером не подтверждена проезжая дорога',
  no_road_path:'До цели нет связной дороги', endpoint_off_road:'Конец пути выходит за проезжую часть',
  outside_visual_coverage:'Путь выходит из зоны визуальных ориентиров', outside_path:'Уточняем положение на дороге',
  turnaround_required:'Перед началом движения разверните скутер по маршруту', stopping:'Остановка у метки',
  arrived:'Прибытие подтверждено', frame_stale:'Кадр устарел', input_closed:'Канал управления закрыт',
  stream_stopped:'Поток остановлен', stream_geometry_or_clock:'Нужен свежий горизонтальный кадр 16:9',
  unreachable_goal:'Метка вне проезжей части', session_active:'Другой сеанс уже использует карту',
};
function problem(e: unknown) {
  const msg = e instanceof Error ? e.message : '';
  return reasons[msg] ?? (msg==='Failed to fetch'?'Нет связи с локальной службой карты':msg || 'Ошибка связи с картой');
}
type View = [number,number,number,number];
function viewBounds(points: XYZ[], pad: number): View {
  const x=points.map(p=>p[0]), y=points.map(p=>-p[1]);
  return [Math.min(...x)-pad,Math.min(...y)-pad,Math.max(...x)-Math.min(...x)+2*pad,Math.max(...y)-Math.min(...y)+2*pad];
}
function outline(points:XYZ[]) { return points.map(([x,y])=>x+','+-y).join(' '); }

export function WorldDestinationPilot({video,ready,inputIssue,openInput}:{
  video:RefObject<HTMLVideoElement|null>; ready:boolean; inputIssue:string|null; openInput:(signal:AbortSignal,journal:(event:TeachingInput)=>void)=>Promise<VehicleInputLease>;
}) {
  const [info,setInfo]=useState<WorldInfo|null>(null), [view,setView]=useState<View|null>(null);
  const [point,setPoint]=useState<[number,number]|null>(null), [levels,setLevels]=useState<number[]>([]), [level,setLevel]=useState<number|null>(null);
  const [status,setStatus]=useState('Загрузка карты'), [active,setActive]=useState(false), [refresh,setRefresh]=useState(0);
  const [data,setData]=useState<Decision|null>(null), [age,setAge]=useState<number|null>(null);
  const choice=useRef<AbortController|null>(null), run=useRef<AbortController|null>(null), mounted=useRef(false);
  const drag=useRef<{x:number;y:number;view:View;m:DOMMatrix}|null>(null);
  const map=useRef<SVGSVGElement|null>(null), opening=useRef(openInput); opening.current=openInput;
  const stop=useCallback(()=>{ if(run.current){run.current.abort();setStatus('Поездка остановлена');} },[]);
  useEffect(()=>{
    mounted.current=true;
    const blur=()=>stop(), key=(e:KeyboardEvent)=>{if(e.key==='Escape')stop();}, hidden=()=>{if(document.hidden)stop();};
    window.addEventListener('blur',blur);window.addEventListener('keydown',key);document.addEventListener('visibilitychange',hidden);
    return ()=>{mounted.current=false;run.current?.abort();choice.current?.abort();window.removeEventListener('blur',blur);window.removeEventListener('keydown',key);document.removeEventListener('visibilitychange',hidden);};
  },[stop]);
  useEffect(()=>{if(!ready)stop();},[ready,stop]);
  useEffect(()=>{
    const c=new AbortController();
    worldRequest<WorldInfo>('/world',AbortSignal.any([c.signal,AbortSignal.timeout(6000)])).then(w=>{
      if(c.signal.aborted)return;
      setInfo(w);setView(viewBounds(w.atlas.visualTrace,30));setStatus('Поставьте метку на дороге');
    }).catch(e=>{if(!c.signal.aborted)setStatus(problem(e));});
    return ()=>c.abort();
  },[refresh]);
  async function choose(x:number,y:number) {
    if(run.current)return;
    choice.current?.abort(); const c=new AbortController(); choice.current=c;
    setPoint([x,y]);setLevel(null);setLevels([]);setData(null);setAge(null);setStatus('Проверяем дорогу под меткой');
    try {
      const result=await worldRequest<{levels:number[];coveredLevels:number[]}>('/levels',AbortSignal.any([c.signal,AbortSignal.timeout(5000)]),{point:[x,y]});
      if(c.signal.aborted)return;
      const valid=result.coveredLevels;
      setLevels(valid);setLevel(valid.length===1?valid[0]:null);
      setStatus(!result.levels.length?'Под меткой нет проезжей дороги':!valid.length?'У этой дороги ещё нет визуальных ориентиров':valid.length>1?'Выберите уровень дороги':'Цель выбрана');
    } catch(e){if(!c.signal.aborted)setStatus(problem(e));}
  }
  async function start() {
    const el=video.current;
    if(!el||!info||!point||level===null||inputIssue||!ready||run.current)return;
    const c=new AbortController();run.current=c;setActive(true);setData(null);setAge(null);setStatus('Ищем скутер по живому кадру');
    let session:string|undefined;
    let applied=0, rejected=0;
    const journal=(e:TeachingInput)=>{if(e.stage==='receipt'){if(e.outcome==='applied')applied++;else rejected++;}};
    try {
      // Retain the session handle even if Stop is pressed while /start is in flight.
      const res=await worldRequest<{session:string}>('/start',AbortSignal.timeout(5500),{goal:[...point,level],revision:info.mapRevision});
      session=res.session;
      if(!c.signal.aborted)await runWorldTrip(el,session,c.signal,()=>opening.current(c.signal,journal),(d,ms)=>{
        if(!c.signal.aborted){setData(d);setAge(ms);setStatus(ms>=320?'Ответ по устаревшему кадру':reasons[d.reason]??d.reason);}
      });
    } catch(e){if(!c.signal.aborted&&mounted.current)setStatus(problem(e));}
    finally {
      if(session)await worldRequest('/stop',AbortSignal.timeout(3000),{applied,rejected},session).catch(()=>undefined);
      if(run.current===c)run.current=null;
      if(mounted.current)setActive(false);
    }
  }
  const goWide=()=>{if(info){const [l,r,b,t]=info.bounds;setView([l,-t,r-l,t-b]);}};
  const zoom=(factor:number)=>{if(view){const [x,y,w,h]=view;setView([x+w*(1-factor)/2,y+h*(1-factor)/2,w*factor,h*factor]);}};
  const bounds=info?.bounds;
  const dot=Math.max(2.4,(view?.[3]??0)/70);
  return <section aria-label="Поездка к метке" className="min-w-0 space-y-3 rounded-2xl border border-border bg-card p-4">
    <h2 className="text-lg font-semibold">Поездка к метке</h2>
    {info&&view&&bounds&&<>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" onClick={goWide}>Вся карта</Button>
        <Button variant="outline" size="sm" onClick={()=>setView(viewBounds(info.atlas.visualTrace,30))}>Зона ориентиров</Button>
        <Button variant="outline" size="sm" aria-label="Приблизить" disabled={view[2]<16} onClick={()=>zoom(.5)}>+</Button>
        <Button variant="outline" size="sm" aria-label="Отдалить" disabled={view[2]>=bounds[1]-bounds[0]} onClick={()=>zoom(2)}>−</Button>
      </div>
      <svg ref={map} viewBox={view.join(' ')} aria-label="Выбрать точку назначения на карте Black Russia" className="h-80 w-full touch-none cursor-crosshair rounded-lg bg-slate-950"
        onPointerDown={e=>{const m=map.current?.getScreenCTM();if(!m||e.button!==0)return;
          e.currentTarget.setPointerCapture(e.pointerId);drag.current={x:e.clientX,y:e.clientY,view,m:m.inverse()};}}
        onPointerMove={e=>{const d=drag.current;if(!d||Math.hypot(e.clientX-d.x,e.clientY-d.y)<4)return;
          const a=new DOMPoint(d.x,d.y).matrixTransform(d.m),b=new DOMPoint(e.clientX,e.clientY).matrixTransform(d.m);
          setView([d.view[0]+a.x-b.x,d.view[1]+a.y-b.y,d.view[2],d.view[3]]);}}
        onPointerCancel={()=>{drag.current=null;}}
        onPointerUp={e=>{const d=drag.current;drag.current=null;if(!d||active||Math.hypot(e.clientX-d.x,e.clientY-d.y)>=4)return;
          const p=new DOMPoint(e.clientX,e.clientY).matrixTransform(d.m);void choose(p.x,-p.y);}}
      >
        {['world','drive'].map(layer=><image key={layer} href={'http://127.0.0.1:8817/'+layer+'.png'} x={bounds[0]} y={-bounds[3]} width={bounds[1]-bounds[0]} height={bounds[3]-bounds[2]} preserveAspectRatio="none" opacity={layer==='drive'?.45:1}/>)}
        <polyline points={outline(info.atlas.visualTrace)} fill="none" stroke="#22d3ee" strokeOpacity=".28" strokeLinejoin="round" strokeLinecap="round" strokeWidth={2*info.atlas.coverageRadius}/>
        {data?.path&&<polyline points={outline(data.path)} fill="none" stroke="#34d399" strokeWidth="3" vectorEffect="non-scaling-stroke"/>}
        {point&&<circle cx={point[0]} cy={-point[1]} r={dot} fill="#f59e0b" stroke="white" strokeWidth="2" vectorEffect="non-scaling-stroke"/>}
        {data?.pose&&<circle cx={data.pose.eye[0]} cy={-data.pose.eye[1]} r={dot} fill="#38bdf8" stroke="white" strokeWidth="2" vectorEffect="non-scaling-stroke"/>}
      </svg>
      <p className="text-xs text-muted-foreground">Голубая полоса — зона ориентиров у Кремля. Зелёная линия показывает построенный путь. Для старта сядьте на скутер и направьте камеру вперёд.</p>
    </>}
    {levels.length>1&&<label>Уровень дороги <select value={level??''} disabled={active} onChange={e=>setLevel(e.target.value===''?null:Number(e.target.value))}><option value="">Выберите уровень</option>{levels.map(z=><option key={z} value={z}>{z.toFixed(1)} м</option>)}</select></label>}
    <p role="status" className="text-sm">{status}</p>
    {data&&<p className="text-xs text-muted-foreground">Опор {data.pose?.supports??0} · кадр до ответа {age} мс{data.remaining!==null?' · до цели '+data.remaining.toFixed(1)+' м':''}</p>}
    {!active&&inputIssue&&<p className="text-xs text-muted-foreground">{inputIssue}</p>}
    <div className="flex flex-wrap gap-2">
      {!info&&<Button variant="outline" onClick={()=>setRefresh(n=>n+1)}>Повторить подключение к карте</Button>}
      <Button disabled={active||!ready||!!inputIssue||level===null} onClick={()=>void start()}>Ехать к метке</Button>
      {active&&<Button variant="outline" onClick={stop}>Остановить · Esc</Button>}
    </div>
  </section>;
}
