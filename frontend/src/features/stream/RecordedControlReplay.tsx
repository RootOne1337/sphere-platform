'use client';
import {useEffect,useRef,useState} from 'react';
import {Play,Square} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {reconstructionRequest,type ReconstructionJob} from './reconstructionClient';
import {navigationReply,paintNavigation,freshNavigationFrame} from './routeNavigation';
import {readWalkPlan,walkReasonLabel} from './walkPilot';
import {readRecordedRouteFrame,type RouteSource} from './routeSource';
import {readImportedRouteGeometry} from './routeMapProjection';
import {saveRouteDebugReport} from './routeDebugStorage';
import {RouteDebugArchive} from './RouteDebugArchive';

type Sample={seconds:number;state:string;reason:string;poseState:string;poseReason:string;computeMs:number;method:string;jpegSha256:string;inliers:number;replyMs:number;stick:[number,number];planStick:[number,number];progress:number|null;sourceIndex:number};
type Session={id:string;epoch:string;job:ReconstructionJob;source:RouteSource;abort:AbortController;began:number;rows:Sample[];browserStopped:boolean;geometrySha?:string;report?:object};
const id=()=>crypto.randomUUID().replaceAll('-','');

/** No input lease, Android transport or native input control is accepted here. */
export function RecordedControlReplay({job,source,assetsReady,disabled=false,onBusyChange}:{job:ReconstructionJob|null;source:RouteSource|null;assetsReady:boolean;disabled?:boolean;onBusyChange:(busy:boolean)=>void}) {
  const [busy,setBusy]=useState(false),[notice,setNotice]=useState('Поток эмулятора не требуется. Выберите подготовленную запись и запустите проверку.'),[saved,setSaved]=useState(''),[last,setLast]=useState<Sample|null>(null),[count,setCount]=useState(0),[uncertain,setUncertain]=useState(false);
  const output=useRef<HTMLCanvasElement>(null),session=useRef<Session|null>(null),generation=useRef(0),stopRef=useRef<(reason:string)=>Promise<void>>(async()=>{});
  const digest=async(raw:ArrayBuffer)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),v=>v.toString(16).padStart(2,'0')).join('');
  const stop=async(reason:string)=>{
    generation.current++;const active=session.current;if(!active)return;
    active.abort.abort();setNotice(reason);
    try{
      await reconstructionRequest(`/jobs/${active.job.id}/navigation/replay-stop`,active.job,{method:'POST',body:JSON.stringify({id:active.id})});
      session.current=null;setUncertain(false);onBusyChange(false);
    }catch{setUncertain(true);onBusyChange(true);setNotice('Закрытие проверки записи не подтверждено. Нажмите «Стоп» для того же сеанса; новый запуск заблокирован.');}
    setBusy(false);
    const report=active.report??={schema:'sphere-recorded-control-replay-v1',runId:active.id,physicalActions:0,closedLoop:false,
      arrivalProven:false,queryTimesSentToLocalizer:false,referenceFramesExcluded:true,sourceManifestSha:active.source.manifestSha,geometrySha:active.geometrySha,reason,samples:active.rows};
    try{const result=await saveRouteDebugReport(active.source.scope,active.source.clip,active.id,report);setSaved(result.state==='saved'?'Отчёт проверки сохранён в локальном архиве.':result.state==='existing'?'Сохранённый отчёт подтверждён.':'Сохранение отчёта не подтверждено.');}
    catch{setSaved('Локальное сохранение отчёта не подтверждено; исходная запись сохранена.');}
  };
  stopRef.current=stop;
  useEffect(()=>()=>{void stopRef.current('Проверка закрыта при смене записи или страницы.');},[job?.id,job?.key,source?.clip,source?.scope,source?.manifestSha]);
  const start=async()=>{
    if(!job||!source||!assetsReady||disabled||busy||session.current)return;
    const active:Session={id:id(),epoch:id(),job,source,abort:new AbortController(),began:0,rows:[],browserStopped:false};
    session.current=active;const current=++generation.current;setBusy(true);onBusyChange(true);setLast(null);setCount(0);setNotice('Проверяем связь записи с картой…');
    const alive=()=>current===generation.current&&session.current===active&&!active.abort.signal.aborted;
    try{
      const response=await reconstructionRequest(`/jobs/${job.id}/geometry`,job,{signal:active.abort.signal});
      const raw=await response.arrayBuffer();if(raw.byteLength>16*1024**2)throw Error('replay_geometry_quota');
      active.geometrySha=await digest(raw);
      const geometry=readImportedRouteGeometry(JSON.parse(new TextDecoder().decode(raw)),source.manifestSha,new Set(source.rows.map(r=>r.relative_ticks_90k)));
      const taught=new Set(geometry.cameras.map(c=>c.ticks_90k));
      const opened=await(await reconstructionRequest(`/jobs/${job.id}/navigation/replay-start`,job,{method:'POST',signal:active.abort.signal,
        body:JSON.stringify({id:active.id,captureEpoch:active.epoch,width:960,height:540})})).json();
      if(!alive())return;if(opened.replayOnly!==true||opened.mode!=='recorded_replay'||opened.physicalActions!==0)throw Error('replay_scope_not_confirmed');
      const original=document.createElement('canvas'),scaled=document.createElement('canvas');scaled.width=960;scaled.height=540;
      const first=source.rows[0].relative_ticks_90k,lastSeconds=(source.rows.at(-1)!.relative_ticks_90k-first)/90000;
      active.began=performance.now();let previous=-1,sequence=0;
      const step=async()=>{
        if(!alive())return;const began=performance.now(),seconds=(began-active.began)/1000;
        if(seconds>Math.min(lastSeconds+.25,55)||active.rows.length>=300){await stopRef.current('Проверка записи завершена. Это диагностика команд, успешный проезд не доказан.');return;}
        let low=0,high=source.rows.length;
        const tick=first+seconds*90000;
        while(low<high){const middle=(low+high)>>>1;if(source.rows[middle].relative_ticks_90k<=tick)low=middle+1;else high=middle;}
        let index=low-1;while(index>=0&&taught.has(source.rows[index].relative_ticks_90k))index--;
        try{
          if(index<=previous)return;previous=index;
          await readRecordedRouteFrame(source,index,original,active.abort.signal);if(!alive())return;
          const capturedAt=active.began+(source.rows[index].relative_ticks_90k-first)/90;
          scaled.getContext('2d')?.drawImage(original,0,0,960,540);
          const blob=await new Promise<Blob>((resolve,reject)=>scaled.toBlob(value=>value?resolve(value):reject(Error('replay_jpeg_unavailable')),'image/jpeg',.92));
          const bytes=await blob.arrayBuffer();if(bytes.byteLength>384*1024)throw Error('replay_jpeg_quota');
          const sha=await digest(bytes);let binary='';for(const byte of new Uint8Array(bytes))binary+=String.fromCharCode(byte);
          const next=++sequence,value=await(await reconstructionRequest(`/jobs/${job.id}/navigation/replay-observe`,job,{method:'POST',signal:active.abort.signal,
            body:JSON.stringify({id:active.id,captureEpoch:active.epoch,sequence:next,jpeg:btoa(binary)})})).json();
          if(!alive())return;
          const reply=navigationReply(value,active.id,active.epoch,next,sha),plan=readWalkPlan(value.walk),now=performance.now();
          if(value.replayOnly!==true||!reply||!plan||reply.geometrySha256!==active.geometrySha)throw Error('replay_reply_not_bound');
          if(!freshNavigationFrame(capturedAt,now))active.browserStopped=true;
          const row:Sample={seconds:(source.rows[index].relative_ticks_90k-first)/90000,sourceIndex:source.rows[index].index,
            state:plan.phase,reason:plan.reason,poseState:reply.pose.state,poseReason:reply.pose.reason,computeMs:reply.computeMs,method:reply.method,jpegSha256:sha,inliers:reply.pose.inliers,replyMs:now-capturedAt,
            stick:active.browserStopped?[0,0]:plan.stick,planStick:plan.stick,progress:plan.progressFraction};
          active.rows.push(row);setLast(row);setCount(active.rows.length);
          const context=output.current?.getContext('2d');if(context)paintNavigation(context,scaled,reply);
          setNotice(active.browserStopped?'Превышен предел 250 мс: допустимый стик обнулён. Продолжаем только диагностику видео.':walkReasonLabel(plan.reason));
        }catch(error){if(alive())await stopRef.current(error instanceof Error?`Проверка остановлена: ${error.message}`:'Проверка не подтверждена.');}
        finally{if(alive())setTimeout(()=>{void step();},Math.max(0,200-(performance.now()-began)));}
      };
      void step();
    }catch(error){if(alive())await stopRef.current(error instanceof Error?`Проверка не запущена: ${error.message}`:'Запуск проверки не подтверждён.');}
  };
  return <section aria-label="Проверка управления на записи" className="space-y-3 rounded-xl border border-cyan-500/25 bg-slate-950/5 p-4">
    <div className="flex items-center gap-2"><Play size={17}/><h4 className="font-semibold">Проверить управление на записи</h4><span className="ml-auto rounded-full border px-2 py-1 text-[10px]">0 команд в Android</span></div>
    <p className="text-xs leading-5 text-muted-foreground">Исходные кадры подаются через тот же JPEG/API, локализатор и пеший контроллер. На экране — направление и расчётный стик. Кадры восстановления пропускаются. Запись продолжает свой путь независимо от команд: этот тест не доказывает, что персонаж действительно дойдёт.</p>
    <div className="flex flex-wrap gap-2"><Button size="sm" disabled={!job||!source||!assetsReady||disabled||busy||uncertain} onClick={()=>{void start();}}>Запустить проверку записи</Button><Button size="sm" variant="outline" disabled={!busy&&!uncertain} onClick={()=>{void stopRef.current('Проверка остановлена пользователем.');}}><Square size={13} className="mr-1"/>Стоп проверки записи</Button></div>
    <p role="status" className="rounded-lg border bg-background/70 p-3 text-xs">{notice}</p>
    <div className="grid grid-cols-2 gap-2 text-xs tabular-nums sm:grid-cols-4"><div>Кадров: {count}</div><div>Время: {last?.seconds.toFixed(2)??'0.00'} с</div><div>Опоры: {last?.inliers??0}</div><div>Кадр → ответ: {last?.replyMs.toFixed(0)??'—'} мс</div></div>
    <div className="flex items-center gap-4"><svg viewBox="0 0 100 100" width="72" height="72" aria-label="Расчётный стик записи"><circle cx="50" cy="50" r="39" fill="none" stroke="currentColor" opacity=".25"/><line x1="50" y1="50" x2={50+(last?.stick[0]??0)*100} y2={50+(last?.stick[1]??0)*100} stroke="#22d3ee" strokeWidth="3"/><circle cx={50+(last?.stick[0]??0)*100} cy={50+(last?.stick[1]??0)*100} r="5" fill="#22d3ee"/></svg><p className="text-xs">Стик X/Y: {last?.stick.map(v=>v.toFixed(2)).join(' / ')??'0 / 0'}<br/>Прогресс плана: {last?.progress==null?'—':`${(last.progress*100).toFixed(1)}%`}<br/>Положение: {last?.poseState==='localized'?'найдено':last?.poseState==='confirming'?'подтверждается':'не определено'}</p></div>
    <canvas ref={output} width={960} height={540} aria-label="Запись с направлением и диагностикой контроллера" className="aspect-video w-full rounded-xl border bg-black"/>
    <p className="text-[11px] text-muted-foreground">До 55 с, целевой ритм 5 кадров/с, один запрос в полёте. После остановки план не перезапускается автоматически. {saved}</p>
    {source&&<RouteDebugArchive scope={source.scope} clip={source.clip} refresh={saved}/>}
  </section>;
}
