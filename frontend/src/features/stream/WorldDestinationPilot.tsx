'use client';

import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { Flag, MapPin, Navigation, X } from 'lucide-react';
import { WorldDestinationMap } from './WorldDestinationMap';
import styles from './worldConsole.module.css';
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
export function WorldDestinationPilot({video,ready,inputIssue,openInput}:{
  video:RefObject<HTMLVideoElement|null>; ready:boolean; inputIssue:string|null; openInput:(signal:AbortSignal,journal:(event:TeachingInput)=>void)=>Promise<VehicleInputLease>;
}) {
  const [info,setInfo]=useState<WorldInfo|null>(null);
  const [covered,setCovered]=useState<number[]>([]);
  const [origin,setOrigin]=useState<XYZ|null>(null), [pickingOrigin,setPickingOrigin]=useState(false);
  const [originChoices,setOriginChoices]=useState<{x:number;y:number;levels:number[]}|null>(null);
  const [preview,setPreview]=useState<{path:XYZ[];distance:number;covered:boolean}|null>(null);
  const [previewError,setPreviewError]=useState('');
  const [point,setPoint]=useState<[number,number]|null>(null), [levels,setLevels]=useState<number[]>([]), [level,setLevel]=useState<number|null>(null);
  const [status,setStatus]=useState('Загрузка карты'), [active,setActive]=useState(false), [refresh,setRefresh]=useState(0);
  const [data,setData]=useState<Decision|null>(null), [age,setAge]=useState<number|null>(null);
  const choice=useRef<AbortController|null>(null), run=useRef<AbortController|null>(null), mounted=useRef(false);
  const opening=useRef(openInput); opening.current=openInput;
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
      setInfo(w);setStatus('Поставьте метку на дороге');
    }).catch(e=>{if(!c.signal.aborted)setStatus(problem(e));});
    return ()=>c.abort();
  },[refresh]);
  async function choose(x:number,y:number) {
    if(run.current)return;
    choice.current?.abort(); const c=new AbortController(); choice.current=c;
    if(pickingOrigin){
      setOrigin(null);setOriginChoices(null);setStatus('Проверяем точку отправления');
      try{
        const result=await worldRequest<{levels:number[]}>('/levels',AbortSignal.any([c.signal,AbortSignal.timeout(5000)]),{point:[x,y]});
        if(c.signal.aborted)return;
        if(!result.levels.length){setStatus('Под стартовой точкой нет дороги');return;}
        if(result.levels.length>1){setOriginChoices({x,y,levels:result.levels});setStatus('Выберите высоту старта');return;}
        setOrigin([x,y,result.levels[0]]);setPickingOrigin(false);setStatus('Старт для расчёта выбран');
      }catch(e){if(!c.signal.aborted)setStatus(problem(e));}
      return;
    }
    setCovered([]);setPoint([x,y]);setLevel(null);setLevels([]);setData(null);setAge(null);setStatus('Проверяем дорогу под меткой');
    try {
      const result=await worldRequest<{levels:number[];coveredLevels:number[]}>('/levels',AbortSignal.any([c.signal,AbortSignal.timeout(5000)]),{point:[x,y]});
      if(c.signal.aborted)return;
      const valid=result.levels;setCovered(result.coveredLevels);
      setLevels(valid);setLevel(valid.length===1?valid[0]:null);
      setStatus(!result.levels.length?'Под меткой нет проезжей дороги':valid.length>1?'Выберите уровень дороги':'Цель выбрана');
    } catch(e){if(!c.signal.aborted)setStatus(problem(e));}
  }
  async function start() {
    const el=video.current;
    if(!el||!info||!point||level===null||!covered.includes(level)||inputIssue||!ready||run.current)return;
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
  useEffect(()=>{
    const controller=new AbortController();
    setPreview(null);setPreviewError('');
    if(origin&&point&&level!==null&&info){
      worldRequest<{path:XYZ[];distance:number;covered:boolean}>('/preview',AbortSignal.any([controller.signal,AbortSignal.timeout(10000)]),
        {revision:info.mapRevision,start:origin,goal:[...point,level]}).then(r=>{
          if(!controller.signal.aborted)setPreview(r);
        }).catch(e=>{if(!controller.signal.aborted)setPreviewError(problem(e));});
    }
    return ()=>controller.abort();
  },[origin,point,level,info]);
  const clear=()=>{
    choice.current?.abort();setOrigin(null);setOriginChoices(null);setPickingOrigin(false);
    setPoint(null);setData(null);setAge(null);setLevels([]);setLevel(null);setCovered([]);setStatus('Поставьте метку на дороге');
  };
  const inAtlas=level!==null&&covered.includes(level);
  return <section aria-label="Поездка к метке" className={styles.panel}>
    <header className={styles.panelHeader}><div><MapPin size={17}/><h2>Карта мира</h2></div><span>Black Russia</span></header>
    {info?<WorldDestinationMap info={info} point={point} origin={origin} preview={preview?.path??[]} decision={data} onChoose={(x,y)=>void choose(x,y)}/>:
      <div className={styles.mapLoading}><p>{status}</p><Button size="sm" variant="outline" onClick={()=>setRefresh(n=>n+1)}>Повторить подключение к карте</Button></div>}
    <div className={styles.tripFooter}>
      <div className={styles.target}><Flag size={17}/><div><strong>{point?'Точка назначения':'Выберите точку назначения'}</strong>
        <p>{point?point.map(n=>n.toFixed(1)).join(' / '):'Щелчок ставит метку. Перетаскивание перемещает карту.'}</p></div>
        {point&&!active&&<button type="button" onClick={clear} aria-label="Сбросить метки"><X size={15}/></button>}</div>
      {levels.length>1&&<label className={styles.selectLabel}>Уровень дороги <select value={level??''} disabled={active} onChange={e=>setLevel(e.target.value===''?null:Number(e.target.value))}><option value="">Выберите</option>{levels.map(z=><option key={z} value={z}>{z.toFixed(1)} м</option>)}</select></label>}
      {(point||active||pickingOrigin)&&<p role="status" className={styles.status}>{status}</p>}
      {point&&level!==null&&!inAtlas&&<p className={styles.attention}>Дорога найдена. Для автопоездки здесь ещё нужны визуальные ориентиры.</p>}
      {data&&<p className={styles.status}>Опор {data.pose?.supports??0} · Кадр до решения {age} мс{data.remaining!=null?' · Осталось '+data.remaining.toFixed(1)+' м':''}</p>}
      <div className={styles.tripAction}>
        {active?<Button variant="destructive" onClick={stop}>Остановить · Esc</Button>:
        <Button disabled={!ready||!!inputIssue||!inAtlas||pickingOrigin} onClick={()=>void start()}><Navigation size={15}/>Ехать к метке</Button>}
        {!active&&inputIssue&&<small>{inputIssue}</small>}
      </div>
      <details className={styles.previewOptions}><summary>Проверить путь между двумя точками</summary>
        <p>Для поездки старт определяется по живому экрану. Здесь можно рассчитать путь от выбранной дороги.</p>
        <Button variant="outline" size="sm" disabled={active||!point||level===null} onClick={()=>{
          choice.current?.abort();setOriginChoices(null);setPickingOrigin(v=>!v);setStatus(pickingOrigin?'Цель выбрана':'Укажите стартовую дорогу на карте');
        }}>{pickingOrigin?'Отменить выбор старта':origin?'Изменить старт':'Указать старт на карте'}</Button>
        {originChoices&&<label>Уровень старта <select defaultValue="" onChange={e=>{setOrigin([originChoices.x,originChoices.y,Number(e.target.value)]);setOriginChoices(null);setPickingOrigin(false);setStatus('Старт для расчёта выбран');}}><option value="" disabled>Выберите</option>{originChoices.levels.map(z=><option key={z} value={z}>{z.toFixed(1)} м</option>)}</select></label>}
        {preview&&<p role="status">{preview.path.length?'Путь по дорогам · '+Math.round(preview.distance)+' м'+(preview.covered?' · в зоне ориентиров':' · вне полного покрытия ориентирами'):'Между этими точками нет связного проезда'}</p>}
        {previewError&&<p role="alert">{previewError}</p>}
      </details>
    </div>
  </section>;
}
