'use client';
import {useEffect,useRef,useState,type RefObject,type ReactNode} from 'react';
import {Footprints,Square,Download} from 'lucide-react';
import {Button} from '@/components/ui/button';
import Image from 'next/image';
import {reconstructionRequest,type ReconstructionJob} from './reconstructionClient';
import {freshNavigationFrame,navigationReply,paintNavigation,type LiveRouteObservation} from './routeNavigation';
import {readWalkPlan,walkReasonLabel,type WalkInputControl,type WalkInputLease} from './walkPilot';
import type {TeachingInput} from './teachingContacts';
import {saveRouteDebugReport} from './routeDebugStorage';
import {RouteDebugArchive} from './RouteDebugArchive';

type Binding={captureEpoch:string;width:number;height:number};
type Sample={elapsedMs:number;sequence:number;ageMs:number;computeMs:number;state:string;reason:string;
  inliers:number;progress:number|null;stick:[number,number];jpegSha256:string;image?:string;
  poseReason:string;segment:number|null;medianErrorPx:number|null;crossTrackUnits:number|null;center:number[]|null;rotation:number[]|null;geometrySha256:string|null};
type Run={id:string;job:ReconstructionJob;abort:AbortController;lease:WalkInputLease|null;opening:Promise<WalkInputLease>|null;began:number;
  binding:Binding;deadline:number;permitUntil:number;moving:boolean;lastSequence:number;clip:string|null;scope:string|null};

/** Explicit supervised foot experiment; the observer above remains read-only. */
export function WalkingRoutePilot({job,clip,video,ready,binding,assetsReady,input,observerBusy,onBusyChange,onObservation,renderView,scope=null}:{
  job:ReconstructionJob|null;clip:string|null;video:RefObject<HTMLVideoElement|null>;ready:boolean;
  binding:Binding|null;assetsReady:boolean;input:WalkInputControl;observerBusy:boolean;onBusyChange:(busy:boolean)=>void;
  onObservation?:(observation:LiveRouteObservation|null)=>void;renderView?:(view:ReactNode)=>ReactNode;
  scope?:string|null;
}) {
  const [confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[saveFrames,setSaveFrames]=useState(true);
  const [notice,setNotice]=useState('Пеший тест запускается отдельно. Записанные клавиши не воспроизводятся.');
  const [release,setRelease]=useState<'none'|'pending'|'closed'|'unknown'>('none');
  const [samples,setSamples]=useState<Sample[]>([]),[events,setEvents]=useState(0);
  const [savedDebug,setSavedDebug]=useState('Диагностика сохранится локально после освобождения ввода.');
  const history=useRef<Sample[]>([]),inputs=useRef<TeachingInput[]>([]),images=useRef(0),lastImageAt=useRef(-Infinity);
  const output=useRef<HTMLCanvasElement>(null),run=useRef<Run|null>(null),retired=useRef<Promise<void>|null>(null);
  const current=useRef({ready,binding});current.current={ready,binding};
  const recent=useRef({sequence:0,at:0}),stopRef=useRef<(reason:string)=>Promise<void>>(async()=>{});
  const busyChange=useRef(onBusyChange);busyChange.current=onBusyChange;
  const observed=useRef(onObservation);observed.current=onObservation;
  const captureEpoch=binding?.captureEpoch;
  const clear=()=>output.current?.getContext('2d')?.clearRect(0,0,960,540);
  const stop=async(reason:string)=>{
    const active=run.current;
    if(!active)return retired.current??Promise.resolve();
    run.current=null;active.abort.abort();clear();observed.current?.(null);setNotice(walkReasonLabel(reason));setRelease('pending');
    const closing=(async()=>{
      let released=true,lease=active.lease;
      try{if(!lease&&active.opening)lease=await active.opening;if(lease)released=await lease.close();}
      catch{released=false;}
      try{await reconstructionRequest(`/jobs/${active.job.id}/navigation/stop`,active.job,{method:'POST',body:JSON.stringify({id:active.id})});}catch{/* Same intent is fenced by its deadline; never retry a start. */}
      setRelease(released?'closed':'unknown');setBusy(false);busyChange.current(false);
      if(!released)setNotice('Освобождение ввода НЕ подтверждено. Новый запуск заблокирован; переподключите поток.');
      if(active.scope&&active.clip){
        const report={schema:'sphere-walk-debug-v1',scope:'supervised_camera_trace_pilot',clip:active.clip,job:active.job.id,
          executionQualified:false,metricAccuracyKnown:false,sourceCaptureAgeKnown:false,release:released?'closed':'unknown',stopReason:reason,
          observations:history.current.map(row=>({...row,center:row.center?[...row.center]:null,rotation:row.rotation?[...row.rotation]:null})),nativeInputs:inputs.current.map(row=>({...row})),nativeInputTailLimit:4096};
        setSavedDebug('Сохраняем диагностику завершённого теста…');
        void saveRouteDebugReport(active.scope,active.clip,active.id,report).then(result=>setSavedDebug(result.state==='saved'?'Диагностика сохранена в локальном архиве браузера.':result.state==='existing'?'Существующий отчёт подтверждён.':'Запись отчёта не подтверждена; прежние файлы сохранены.'))
          .catch(()=>setSavedDebug('Сохранение диагностики не подтверждено. Скачайте отчёт; автоматического повтора нет.'));
      }
    })();
    retired.current=closing;await closing;
  };
  stopRef.current=stop;
  useEffect(()=>()=>{void stopRef.current('walk_stream_changed');},[]);
  useEffect(()=>{setConfirmed(false);void stopRef.current('walk_stream_changed');},[job?.id,job?.key,clip,binding?.captureEpoch,binding?.width,binding?.height]);
  useEffect(()=>{if(binding?.captureEpoch)setRelease('none');},[binding?.captureEpoch]);
  useEffect(()=>{
    recent.current={sequence:0,at:0};const element=video.current;
    if(!ready||!captureEpoch||!element?.requestVideoFrameCallback)return;
    let closed=false,id=0;
    const next=()=>{id=element.requestVideoFrameCallback(()=>{if(closed)return;recent.current={sequence:recent.current.sequence+1,at:performance.now()};next();});};
    next();return()=>{closed=true;element.cancelVideoFrameCallback(id);};
  },[video,ready,captureEpoch]);
  useEffect(()=>{
    const timer=setInterval(()=>{
      const active=run.current;if(!active)return;
      const now=performance.now(),source=current.current;
      if(!source.ready||source.binding?.captureEpoch!==active.binding.captureEpoch||!freshNavigationFrame(recent.current.at,now))void stopRef.current('walk_stream_changed');
      else if(now>=active.deadline)void stopRef.current('walk_time_limit');
      else if(active.moving&&now>active.permitUntil)void stopRef.current('walk_decision_expired');
      else if(active.lease&&!active.lease.active())void stopRef.current('walk_native_closed');
    },25);
    const hidden=()=>{if(document.hidden)void stopRef.current('walk_manual_stop');};
    const blur=()=>{void stopRef.current('walk_manual_stop');};
    const escape=(event:KeyboardEvent)=>{if(event.code==='Escape'){event.preventDefault();void stopRef.current('walk_manual_stop');}};
    document.addEventListener('visibilitychange',hidden);window.addEventListener('blur',blur);window.addEventListener('keydown',escape);
    return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',hidden);window.removeEventListener('blur',blur);window.removeEventListener('keydown',escape);};
  },[]);
  const start=async()=>{
    if(!job||!binding||!ready||!assetsReady||!confirmed||input.issue||observerBusy||busy||run.current||release==='unknown')return;
    if(!freshNavigationFrame(recent.current.at,performance.now())){setNotice('Дождитесь свежего кадра прямого потока.');return;}
    const began=performance.now();
    const active:Run={id:crypto.randomUUID().replaceAll('-',''),job,abort:new AbortController(),lease:null,opening:null,began,
      binding:{...binding},deadline:began+60000,permitUntil:0,moving:false,lastSequence:0,clip,scope};
    run.current=active;setBusy(true);busyChange.current(true);setRelease('none');setNotice('Открываем отдельный пеший тест. До узнавания старта стик нейтрален.');
    history.current=[];inputs.current=[];images.current=0;lastImageAt.current=-Infinity;setSamples([]);setEvents(0);
    const signal=active.abort.signal,alive=()=>run.current===active&&!signal.aborted;
    try{
      const state=await(await reconstructionRequest(`/jobs/${job.id}/navigation/walk-start`,job,{method:'POST',signal,
        body:JSON.stringify({id:active.id,captureEpoch:binding.captureEpoch,width:binding.width,height:binding.height,sceneConfirmed:true,footCameraAssumptionConfirmed:true})})).json();
      if(!alive())return;
      if(state.id!==active.id||state.phase!=='observing'||state.mode!=='foot_camera_trace_v1'||state.physicalActions!==0||state.maxSeconds!==60)throw Error('walk_start_unconfirmed');
      active.opening=input.open(signal,event=>{if(inputs.current.length>=4096)inputs.current.shift();inputs.current.push(event);setEvents(inputs.current.length);});
      const lease=await active.opening;
      active.lease=lease;
      if(!alive()){await lease.close();return;}
      if(!lease.active())throw Error('walk_native_closed');
      const canvas=document.createElement('canvas');canvas.width=960;canvas.height=540;
      const context=canvas.getContext('2d');if(!context)throw Error('walk_canvas_unavailable');
      const observe=async()=>{
        if(!alive())return;
        const began=performance.now(),frame=recent.current;
        try{
          if(frame.sequence===active.lastSequence||!freshNavigationFrame(frame.at,began))return;
          active.lastSequence=frame.sequence;context.drawImage(video.current!,0,0,960,540);
          const blob=await new Promise<Blob>((resolve,reject)=>canvas.toBlob(v=>v?resolve(v):reject(Error('walk_jpeg_unavailable')),'image/jpeg',.92));
          if(blob.size>384*1024)throw Error('walk_jpeg_quota');
          const bytes=await blob.arrayBuffer(),sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
          const jpeg=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(Error('walk_jpeg_unavailable'));reader.readAsDataURL(blob);});
          if(!alive())return;
          if(!freshNavigationFrame(frame.at,performance.now()))throw Error('walk_decision_expired');
          const value=await(await reconstructionRequest(`/jobs/${job.id}/navigation/observe`,job,{method:'POST',signal,body:JSON.stringify({id:active.id,captureEpoch:binding.captureEpoch,sequence:frame.sequence,jpeg})})).json();
          if(!alive())return;
          const reply=navigationReply(value,active.id,binding.captureEpoch,frame.sequence,sha),plan=readWalkPlan(value.walk),now=performance.now();
          if(!reply||!plan)throw Error('walk_reply_not_bound');
          if(!freshNavigationFrame(frame.at,now)||!lease.active())throw Error('walk_decision_expired');
          observed.current?.({reply,capturedAt:frame.at,answeredAt:now});
          const keep=saveFrames&&images.current<60&&now-lastImageAt.current>=1000;
          if(keep){images.current++;lastImageAt.current=now;}
          const sample:Sample={elapsedMs:now-active.began,sequence:frame.sequence,ageMs:now-frame.at,computeMs:reply.computeMs,
            state:plan.phase,reason:plan.reason,inliers:reply.pose.inliers,progress:plan.progressFraction,stick:plan.stick,jpegSha256:sha,
            poseReason:reply.pose.reason,segment:reply.pose.segment,medianErrorPx:reply.pose.median_error_px??null,
            crossTrackUnits:reply.pose.cross_track_units??null,center:reply.pose.center?[...reply.pose.center]:null,rotation:reply.pose.rotation?[...reply.pose.rotation]:null,geometrySha256:reply.geometrySha256??null,
            ...(keep?{image:`data:image/jpeg;base64,${jpeg}`}:{})};
          if(history.current.length<1200)history.current.push(sample);setSamples([...history.current.slice(-8)]);
          const draw=output.current?.getContext('2d');if(draw)paintNavigation(draw,canvas,reply);
          setNotice(walkReasonLabel(plan.reason));
          if(plan.phase==='stopped'||plan.phase==='arrived'){await stop(plan.reason);return;}
          active.permitUntil=frame.at+250;
          active.moving=plan.phase==='following'&&Math.hypot(...plan.stick)>0;
          lease.set(plan.stick);
        }catch(error){if(alive())await stop(error instanceof Error?error.message:'walk_request_failed');}
        finally{if(alive())setTimeout(()=>{void observe();},Math.max(0,100-(performance.now()-began)));}
      };
      void observe();
    }catch(error){if(alive())await stop(error instanceof Error?error.message:'walk_start_unconfirmed');}
  };
  const download=()=>{
    const report={schema:'sphere-walk-debug-v1',scope:'supervised_camera_trace_pilot',clip,job:job?.id,
      executionQualified:false,metricAccuracyKnown:false,sourceCaptureAgeKnown:false,release,
      observations:history.current,nativeInputs:inputs.current,nativeInputTailLimit:4096};
    const url=URL.createObjectURL(new Blob([JSON.stringify(report)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='sphere-walk-debug.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const last=samples.at(-1);
  return <section aria-label="Пеший тест маршрута" className="space-y-3 rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4">
    <div className="flex items-center gap-2"><Footprints size={19} className="text-amber-500"/><h3 className="font-semibold">Пеший тест · живой стик</h3><span className="ml-auto text-xs text-muted-foreground">до 60 с · до 35% стика</span></div>
    <p className="text-xs leading-5 text-muted-foreground">По свежим ориентирам выбираем ближайшую цель на записанном пути камеры. Клавиши записи не нужны. Объезд препятствий не реализован: при потере позиции или прогресса тест останавливается. Это проверка алгоритма, точность в метрах ещё не измерена.</p>
    <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)}/>Персонаж пешком у начала записи, ракурс и FOV сохранены, путь свободен; готов остановить тест</label>
    <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={saveFrames} disabled={busy} onChange={e=>setSaveFrames(e.target.checked)}/>Диагностика: до 60 кадров, положения стика и подтверждения Android остаются в этой вкладке</label>
    {(input.issue||!assetsReady)&&<p className="text-xs text-amber-500">{input.issue??'Сначала подготовьте карту ориентиров выбранной записи.'}</p>}
    <div className="flex flex-wrap gap-2"><Button size="sm" disabled={busy||observerBusy||!job||!ready||!assetsReady||!confirmed||!!input.issue||release==='unknown'} onClick={()=>{void start();}}>Запустить пеший тест · 60 с</Button><Button size="sm" variant="destructive" disabled={!busy} onClick={()=>{void stop('walk_manual_stop');}}><Square size={13} className="mr-1"/>Стоп пешего теста · Esc</Button><Button size="sm" variant="outline" disabled={!samples.length||busy} onClick={download}><Download size={13} className="mr-1"/>Скачать отчёт теста</Button></div>
    <p role="status" className="rounded-lg border bg-background/60 p-3 text-xs">{notice}</p>
    <p className="text-[11px] text-muted-foreground">{savedDebug}</p>
    {scope&&clip&&<RouteDebugArchive scope={scope} clip={clip} refresh={savedDebug}/>}
    <div className="grid grid-cols-3 gap-2 text-xs tabular-nums"><div>Прогресс: {last?.progress==null?'—':`${(last.progress*100).toFixed(1)}%`}</div><div>Опоры: {last?.inliers??0}</div><div>Кадр → ответ: {last?`${last.ageMs.toFixed(0)} мс`:'—'}</div><div>Стик: {release==='unknown'?'UNKNOWN':busy&&last?last.stick.map(v=>v.toFixed(2)).join(' / '):'0 / 0'}</div><div>События ввода: {events}</div><div>Освобождение: {({none:'—',pending:'ожидается',closed:'CLOSED',unknown:'UNKNOWN'})[release]}</div></div>
    {renderView?renderView(<canvas ref={output} width={960} height={540} aria-label="Диагностика пешего теста на свежем кадре" className="aspect-video w-full rounded-lg border bg-black"/>):<canvas ref={output} width={960} height={540} aria-label="Диагностика пешего теста на свежем кадре" className="aspect-video w-full rounded-lg border bg-black"/>}
    {!busy&&samples.length>0&&<details><summary className="cursor-pointer text-xs">Кадры диагностики · {images.current}</summary><div className="mt-2 grid grid-cols-2 gap-2">{history.current.filter(s=>s.image).map(s=><figure key={s.sequence}><Image src={s.image!} width={960} height={540} unoptimized alt={`Кадр теста ${(s.elapsedMs/1000).toFixed(1)} с`} className="w-full rounded border"/><figcaption className="text-[10px]">{(s.elapsedMs/1000).toFixed(1)} с · {s.inliers} опор · {s.progress==null?'позиция неизвестна':`${(s.progress*100).toFixed(1)}%`}</figcaption></figure>)}</div></details>}
    {!!samples.length&&<div className="overflow-auto"><table className="w-full text-left text-[11px] tabular-nums"><caption className="pb-2 text-left text-muted-foreground">Последние наблюдения · относительный прогресс, без метров</caption><thead><tr><th>Время</th><th>Опоры</th><th>Стик X/Y</th><th>Состояние</th></tr></thead><tbody>{samples.map(s=><tr key={s.sequence}><td>{(s.elapsedMs/1000).toFixed(1)} с</td><td>{s.inliers}</td><td>{s.stick.map(n=>n.toFixed(2)).join(' / ')}</td><td>{walkReasonLabel(s.reason)}</td></tr>)}</tbody></table></div>}
  </section>;
}
