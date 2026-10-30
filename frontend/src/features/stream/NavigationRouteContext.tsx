'use client';
import {useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import {reconstructionRequest,type ReconstructionJob} from './reconstructionClient';
import {readImportedRouteGeometry,type ImportedRouteGeometry,type RouteMapCamera} from './routeMapProjection';
import {boundLiveRouteCamera,type LiveRouteObservation} from './routeNavigation';
import type {RouteSource} from './routeSource';
import RouteGeometryMap from './RouteGeometryMap';
import {RecordedRouteFrame} from './RecordedRouteFrame';

/** A preview never authorizes movement. A live pin requires the exact map hash. */
export function NavigationRouteContext({job,source,assetsReady,observation,comparison,busy=false,preparedLandmarks=null}:{job:ReconstructionJob;source:RouteSource;assetsReady:boolean;
  observation:LiveRouteObservation|null;comparison?:ReactNode;busy?:boolean;preparedLandmarks?:number|null}) {
  const [choices,setChoices]=useState<{id:string;cameras:number}[]>([]),[choice,setChoice]=useState('primary');
  const [geometry,setGeometry]=useState<{data:ImportedRouteGeometry;sha:string;choice:string}|null>(null),[notice,setNotice]=useState('Загружаем связанную карту…');
  const [ticks,setTicks]=useState<number|null>(null),[follow,setFollow]=useState(true),[live,setLive]=useState<RouteMapCamera|null>(null);
  const [orientation,setOrientation]=useState<RouteMapCamera|null>(null);
  const lastReferenceAt=useRef(-Infinity),validTicks=useMemo(()=>new Set(source.rows.map(row=>row.relative_ticks_90k)),[source]);
  useEffect(()=>{if(busy&&assetsReady)setChoice('primary');},[busy,assetsReady]);
  useEffect(()=>{
    const abort=new AbortController();let retired=false;setChoices([]);setChoice('primary');
    void(async()=>{
      const result=await(await reconstructionRequest(`/jobs/${job.id}/geometry-alternatives`,job,{signal:abort.signal})).json();
      const items=Array.isArray(result.alternatives)?result.alternatives.filter((v:{id?:unknown;cameras?:unknown})=>typeof v.id==='string'&&/^[a-z0-9][a-z0-9-]{0,47}$/.test(v.id)&&Number.isInteger(v.cameras)&&Number(v.cameras)>=2&&Number(v.cameras)<=240).slice(0,16):[];
      if(!retired){setChoices(items);if(!assetsReady&&items.length)setChoice([...items].sort((a,b)=>b.cameras-a.cameras)[0].id);}
    })().catch(()=>{/* Primary geometry remains independently available. */});
    return()=>{retired=true;abort.abort();};
  },[job.id,job.key,source,assetsReady]);
  useEffect(()=>{
    const abort=new AbortController();let retired=false;setGeometry(null);setLive(null);setOrientation(null);setTicks(null);setFollow(true);lastReferenceAt.current=-Infinity;setNotice('Загружаем связанную карту…');
    void(async()=>{
      const response=await reconstructionRequest(`/jobs/${job.id}/${choice==='primary'?'geometry':`geometry-alternatives/${choice}`}`,job,{signal:abort.signal});
      const raw=await response.arrayBuffer();if(raw.byteLength>16*1024**2)throw Error('Размер карты превышает предел.');
      const sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),v=>v.toString(16).padStart(2,'0')).join('');
      const data=readImportedRouteGeometry(JSON.parse(new TextDecoder().decode(raw)),source.manifestSha,validTicks);
      if(!retired){setGeometry({data,sha,choice});setTicks(data.cameras[0].ticks_90k);setNotice(choice==='primary'?'Основная геометрия связана с выбранной записью.':'Дополнительная схема для осмотра; живое положение на ней не наносится.');}
    })().catch(error=>{if(!retired)setNotice(error instanceof Error?error.message:'Связанная карта недоступна.');});
    return()=>{retired=true;abort.abort();};
  },[job.id,job.key,source,choice,validTicks,assetsReady]);
  useEffect(()=>{
    setLive(null);if(!observation||!geometry||geometry.choice!=='primary')return;
    const {reply,capturedAt}=observation,p=reply.pose,camera=boundLiveRouteCamera(observation,geometry.sha,performance.now());
    if(!camera)return;setLive(camera);setOrientation(camera);
    if(follow&&performance.now()-lastReferenceAt.current>=1000){
      const index=Math.min(p.segment??0,geometry.data.cameras.length-1),reference=reply.referenceTicks90k??geometry.data.cameras[index].ticks_90k;
      if(validTicks.has(reference)){setTicks(reference);lastReferenceAt.current=performance.now();}
    }
    const timeout=setTimeout(()=>setLive(null),Math.max(0,250-(performance.now()-capturedAt)));
    return()=>clearTimeout(timeout);
  },[observation,geometry,follow,validTicks]);
  return <div aria-label="Карта и опорный кадр в живой проверке" className="space-y-2">
    <div className="flex flex-wrap items-center gap-3 text-xs"><label>Схема<select aria-label="Схема для живой проверки" className="ml-2 rounded-lg border bg-background p-2" disabled={busy} value={choice} onChange={e=>setChoice(e.target.value)}><option value="primary">Основная карта локализации</option>{choices.map(item=><option key={item.id} value={item.id}>Дополнительная · {item.cameras} камер · осмотр</option>)}</select></label><label className="flex items-center gap-2"><input type="checkbox" checked={follow} onChange={e=>setFollow(e.target.checked)}/>Опорный кадр вслед за локализацией · до 1/с</label><span className={live?'text-emerald-500':'text-muted-foreground'}>{live?'Живое положение подтверждено':'Живое положение не нанесено'}</span></div>
    <p className="text-xs text-muted-foreground">{notice}</p>
    {observation?.reply.pose.state==='unknown'&&<p className="text-xs text-amber-500">Положение сейчас не узнано. Сохранённый опорный кадр остаётся для сравнения и не обозначает текущую позицию.</p>}
    <p className="text-xs text-muted-foreground">Признаки карты локализатора: {preparedLandmarks??'—'} · Совпадения последнего кадра: {observation?.reply.pose.inliers??0}. Облако сцены показано отдельно от совпадений текущего кадра.</p>
    {geometry&&ticks!==null?<RouteGeometryMap cameras={geometry.data.cameras} points={geometry.data.points} motionWarning={choice!=='primary'||!assetsReady}
      selectedTicks={ticks} validTicks={validTicks} onSeekCamera={value=>{setFollow(false);setTicks(value);}} liveCamera={live} orientationCamera={orientation}
      sourcePreview={<RecordedRouteFrame source={source} ticks={ticks}/>} comparison={comparison}/>:comparison}
  </div>;
}
