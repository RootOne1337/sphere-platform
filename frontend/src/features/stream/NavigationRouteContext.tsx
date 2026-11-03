'use client';
import {useCallback,useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import {reconstructionRequest,type ReconstructionJob,type NavigationMapSource} from './reconstructionClient';
import {readImportedRouteGeometry,type ImportedRouteGeometry,type RouteMapCamera} from './routeMapProjection';
import {boundLiveRouteCamera,type LiveRouteObservation} from './routeNavigation';
import type {RouteSource} from './routeSource';
import RouteGeometryMap from './RouteGeometryMap';
import {RecordedRouteFrame} from './RecordedRouteFrame';
import {assertReconstructionSource,routeRecordingIdentity} from './routeSourceBinding';
import type {NavigationGeometrySelection} from './navigationGeometrySource';
import {sceneCameraCoverage} from './sceneGeometrySelection';
import {CameraCoverageNotice} from './CameraCoverageNotice';

/** A preview never authorizes movement. A live pin requires the exact map hash. */
export function NavigationRouteContext({job,source,recordingTitle,assetsReady,observation,comparison,busy=false,preparedLandmarks=null,preparedSource,initialChoice,onGeometryChange}:{job:ReconstructionJob;source:RouteSource;assetsReady:boolean;recordingTitle?:string;
  observation:LiveRouteObservation|null;comparison?:ReactNode;busy?:boolean;preparedLandmarks?:number|null;preparedSource?:NavigationMapSource;initialChoice?:string|null;onGeometryChange?:(selection:NavigationGeometrySelection|null)=>void}) {
  const identity=JSON.stringify([job.id,job.key,source.scope,source.clip,source.manifestSha]);
  const requestJob=useMemo(()=>({id:job.id,key:job.key}),[job.id,job.key]);
  const activeIdentity=useRef(identity);activeIdentity.current=identity;
  const ready=useRef(assetsReady);ready.current=assetsReady;
  const prepared=useRef(preparedSource);prepared.current=preparedSource;
  const initial=useRef(initialChoice);initial.current=initialChoice;
  const manualChoice=useRef<string|null>(null);
  const [validatedIdentity,setValidatedIdentity]=useState<string|null>(null);
  const [catalog,setCatalog]=useState<{identity:string;items:{id:string;cameras:number;label?:string}[]}|null>(null);
  const [selection,setSelection]=useState<{identity:string;id:string}|null>(null);
  const choices=useMemo(()=>catalog?.identity===identity?catalog.items:[],[catalog,identity]),choice=selection?.identity===identity?selection.id:'primary';
  const setChoice=useCallback((id:string)=>setSelection({identity,id}),[identity]);
  const [storedGeometry,setStoredGeometry]=useState<{identity:string;data:ImportedRouteGeometry;sha:string;choice:string}|null>(null),[notice,setNotice]=useState('Загружаем связанную карту…');
  const geometry=validatedIdentity===identity&&storedGeometry?.identity===identity&&storedGeometry.choice===choice?storedGeometry:null;
  const [ticks,setTicks]=useState<number|null>(null),[follow,setFollow]=useState(true),[live,setLive]=useState<RouteMapCamera|null>(null);
  const [orientation,setOrientation]=useState<RouteMapCamera|null>(null);
  const [recentPose,setRecentPose]=useState<{camera:RouteMapCamera;at:number;epoch:string}|null>(null);
  const lastReferenceAt=useRef(-Infinity),validTicks=useMemo(()=>new Set(source.rows.map(row=>row.relative_ticks_90k)),[source.rows]);
  const recordingRange=useMemo(()=>source.rows.length?{firstTicks:source.rows[0].relative_ticks_90k,lastTicks:source.rows.at(-1)!.relative_ticks_90k,frames:source.rows.length}:undefined,[source.rows]);
  const cameraCoverage=useMemo(()=>geometry?sceneCameraCoverage(geometry.data.cameras,recordingRange,validTicks):null,[geometry,recordingRange,validTicks]);
  const selectedGeometry=useMemo<NavigationGeometrySelection|null>(()=>geometry?{
    alternativeId:geometry.choice==='primary'?null:geometry.choice,geometry_sha256:geometry.sha,
    label:geometry.choice==='primary'?'Основная реконструкция':choices.find(item=>item.id===geometry.choice)?.label||geometry.choice,
    cameras:geometry.data.cameras.length,points:geometry.data.points.length,
  }:null,[geometry,choices]);
  const geometryReady=!!geometry&&assetsReady&&(preparedSource?
    preparedSource.geometry_sha256===geometry.sha&&preparedSource.alternativeId===(geometry.choice==='primary'?null:geometry.choice):geometry.choice==='primary');
  useEffect(()=>{onGeometryChange?.(selectedGeometry);},[onGeometryChange,selectedGeometry]);
  useEffect(()=>()=>onGeometryChange?.(null),[onGeometryChange]);
  useEffect(()=>{
    const abort=new AbortController();let retired=false;setCatalog(null);setChoice('primary');manualChoice.current=null;
    void(async()=>{
      const status=await(await reconstructionRequest(`/jobs/${requestJob.id}`,requestJob,{signal:abort.signal})).json();
      assertReconstructionSource(status,source.manifestSha);
      const result=await(await reconstructionRequest(`/jobs/${requestJob.id}/geometry-alternatives`,requestJob,{signal:abort.signal})).json();
      const items=Array.isArray(result.alternatives)?result.alternatives.filter((v:{id?:unknown;cameras?:unknown;label?:unknown})=>typeof v.id==='string'&&/^[a-z0-9][a-z0-9-]{0,47}$/.test(v.id)&&Number.isInteger(v.cameras)&&Number(v.cameras)>=2&&Number(v.cameras)<=240&&(v.label===undefined||typeof v.label==='string'&&v.label.length<=128)).slice(0,16):[];
      if(!retired&&activeIdentity.current===identity){
        setCatalog({identity,items});
        if(manualChoice.current===null){
          const navigation=status.navigation,activeSource=prepared.current??(navigation?.phase==='ready'?navigation.source:undefined);
          if(initial.current==='primary'||items.some((v:{id:string})=>v.id===initial.current))setChoice(initial.current!);
          else if(activeSource?.alternativeId&&items.some((v:{id:string})=>v.id===activeSource.alternativeId))setChoice(activeSource.alternativeId);
          else if(ready.current||navigation?.phase==='ready')setChoice('primary');
          else if(items.some((v:{id:string})=>v.id===result.preferredAlternativeId))setChoice(result.preferredAlternativeId);
        }
        setValidatedIdentity(identity);
      }
    })().catch(error=>{if(!retired&&activeIdentity.current===identity)setNotice(error instanceof Error?error.message:'Список связанных схем недоступен.');});
    return()=>{retired=true;abort.abort();};
  },[identity,requestJob,source.manifestSha,setChoice]);
  useEffect(()=>{
    const abort=new AbortController();let retired=false;setStoredGeometry(null);setLive(null);setOrientation(null);setRecentPose(null);setTicks(null);setFollow(true);lastReferenceAt.current=-Infinity;setNotice('Загружаем связанную карту…');
    void(async()=>{
      const response=await reconstructionRequest(`/jobs/${requestJob.id}/${choice==='primary'?'geometry':`geometry-alternatives/${choice}`}`,requestJob,{signal:abort.signal});
      const raw=await response.arrayBuffer();if(raw.byteLength>16*1024**2)throw Error('Размер карты превышает предел.');
      const sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),v=>v.toString(16).padStart(2,'0')).join('');
      const data=readImportedRouteGeometry(JSON.parse(new TextDecoder().decode(raw)),source.manifestSha,validTicks);
      if(!retired&&activeIdentity.current===identity){setStoredGeometry({identity,data,sha,choice});setTicks(data.cameras[0].ticks_90k);setNotice(choice==='primary'?'Основная геометрия связана с выбранной записью.':'Сохранённая схема связана с исходной записью. Для движения нужна карта, подготовленная именно из этой геометрии.');}
    })().catch(error=>{if(!retired)setNotice(error instanceof Error?error.message:'Связанная карта недоступна.');});
    return()=>{retired=true;abort.abort();};
  },[identity,requestJob,source.manifestSha,choice,validTicks]);
  useEffect(()=>{
    setLive(null);if(!observation||!geometry||!geometryReady)return;
    const {reply,capturedAt}=observation,p=reply.pose,camera=boundLiveRouteCamera(observation,geometry.sha,performance.now());
    if(!camera)return;setLive(camera);setOrientation(camera);setRecentPose({camera,at:capturedAt,epoch:reply.captureEpoch});
    if(follow&&performance.now()-lastReferenceAt.current>=1000){
      const index=Math.min(p.segment??0,geometry.data.cameras.length-1),reference=reply.referenceTicks90k??geometry.data.cameras[index].ticks_90k;
      if(validTicks.has(reference)){setTicks(reference);lastReferenceAt.current=performance.now();}
    }
    const timeout=setTimeout(()=>setLive(null),Math.max(0,250-(performance.now()-capturedAt)));
    return()=>clearTimeout(timeout);
  },[observation,geometry,geometryReady,follow,validTicks]);
  useEffect(()=>{
    if(!recentPose)return;
    const timeout=setTimeout(()=>setRecentPose(null),Math.max(0,1000-(performance.now()-recentPose.at)));
    return()=>clearTimeout(timeout);
  },[recentPose]);
  const recent=busy&&recentPose&&geometry&&geometryReady&&geometry.sha===observation?.reply.geometrySha256&&recentPose.epoch===observation.reply.captureEpoch&&performance.now()-recentPose.at<1000?recentPose.camera:null;
  return <div aria-label="Карта и опорный кадр в живой проверке" className="space-y-2">
    <p aria-label="Запись и обработка живой карты" className="break-words text-xs font-medium text-cyan-600 dark:text-cyan-400">{routeRecordingIdentity(recordingTitle,source.clip,job.id)}</p>
    <div className="flex flex-wrap items-center gap-3 text-xs"><label className="min-w-0 flex-1">Схема<select aria-label="Схема для живой проверки" className="mt-1 block w-full min-w-0 rounded-lg border bg-background p-2" disabled={busy} value={choice} onChange={e=>{manualChoice.current=e.target.value;setChoice(e.target.value);}}><option value="primary">Основная карта локализации</option>{choices.map(item=><option key={item.id} value={item.id}>{item.label||item.id} · {item.cameras} камер · осмотр</option>)}</select></label><label className="flex items-center gap-2"><input type="checkbox" checked={follow} onChange={e=>setFollow(e.target.checked)}/>Опорный кадр вслед за локализацией · до 1/с</label><span className="inline-block w-64 shrink-0 truncate text-muted-foreground">{live||recent?'Слежение за маршрутом':'Живое положение не нанесено'}</span></div>
    <p className="text-xs text-muted-foreground">{notice}</p>
    {cameraCoverage&&<CameraCoverageNotice coverage={cameraCoverage}/>}
    <div aria-label="Состояние локализации" className="flex h-10 items-center overflow-hidden text-xs leading-5">
      <p className={`line-clamp-2 ${observation?.reply.pose.state==='unknown'&&!recent?'text-amber-500':'text-slate-400'}`}>
        {busy&&(live||recent)?'Позиция обновляется по живым кадрам. Пунктир — последняя измеренная позиция, без предсказания движения.':
          observation?.reply.pose.state==='unknown'&&!recent?'Положение сейчас не узнано. Сохранённый опорный кадр остаётся для сравнения и не обозначает текущую позицию.':
          live?'Положение подтверждено по свежим 3D-ориентирам.':'Сохранённая схема и опорный кадр доступны для сравнения.'}
      </p>
    </div>
    <p className="text-xs text-muted-foreground">Ориентиров карты: <span className="inline-block min-w-10 tabular-nums">{preparedLandmarks??'—'}</span> · Совпадений кадра: <span className="inline-block min-w-10 tabular-nums">{observation?.reply.pose.inliers??0}</span>. Облако сцены показано отдельно от текущих совпадений.</p>
    {geometry&&ticks!==null?<RouteGeometryMap cameras={geometry.data.cameras} points={geometry.data.points} motionWarning={!geometryReady}
      selectedTicks={ticks} validTicks={validTicks} onSeekCamera={value=>{setFollow(false);setTicks(value);}} liveCamera={live} orientationCamera={orientation} recentCamera={recent} showStaleWarning={busy}
      sourcePreview={<RecordedRouteFrame source={source} ticks={ticks}/>} comparison={comparison}/>:comparison}
  </div>;
}
